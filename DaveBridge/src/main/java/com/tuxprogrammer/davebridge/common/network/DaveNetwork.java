package com.tuxprogrammer.davebridge.common.network;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import net.minecraft.entity.player.EntityPlayerMP;

import com.google.gson.Gson;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.protocol.DavePacket;
import com.tuxprogrammer.davebridge.common.protocol.DavePackets;

import cpw.mods.fml.common.network.NetworkRegistry;
import cpw.mods.fml.common.network.simpleimpl.IMessage;
import cpw.mods.fml.common.network.simpleimpl.IMessageHandler;
import cpw.mods.fml.common.network.simpleimpl.MessageContext;
import cpw.mods.fml.common.network.simpleimpl.SimpleNetworkWrapper;
import cpw.mods.fml.relauncher.Side;

/**
 * The {@code davebridge} FML channel between the server and clients that have the mod.
 * <p>
 * Side safety: this class and its frame handlers are loaded on both sides and reference no client classes. Client
 * behavior is attached at runtime by {@code client.ClientProxy} through {@link #onClient}; server behavior by
 * {@code server.DaveServer} through {@link #onServer}. Handlers must not assume a thread: depending on the side and
 * the loaded coremods FML calls them on the netty thread or the main thread, so game-state work always goes through a
 * main-thread queue.
 */
public final class DaveNetwork {

    public static final String CHANNEL = "davebridge";

    /** Largest reassembled packet a client may send. Clients are untrusted. */
    public static final int MAX_TO_SERVER_BYTES = 256 * 1024;
    /** Largest reassembled packet the client accepts from the server. */
    public static final int MAX_TO_CLIENT_BYTES = 8 * 1024 * 1024;

    private static final Gson GSON = new Gson();
    private static final AtomicInteger NEXT_STREAM = new AtomicInteger();

    private static final Map<Class<?>, ServerHandler<?>> SERVER_HANDLERS = new ConcurrentHashMap<>();
    private static final Map<Class<?>, ClientHandler<?>> CLIENT_HANDLERS = new ConcurrentHashMap<>();
    private static final Map<UUID, PayloadChunker.Assembler> SERVER_ASSEMBLERS = new ConcurrentHashMap<>();
    private static final PayloadChunker.Assembler CLIENT_ASSEMBLER = new PayloadChunker.Assembler(
        MAX_TO_CLIENT_BYTES,
        8,
        TimeUnit.SECONDS.toNanos(60));

    private static SimpleNetworkWrapper wrapper;

    /** Handles a packet from a client. Any thread; queue game-state work. */
    public interface ServerHandler<T extends DavePacket> {

        void handle(T packet, EntityPlayerMP player);
    }

    /** Handles a packet from the server. Any thread; queue game-state work. */
    public interface ClientHandler<T extends DavePacket> {

        void handle(T packet);
    }

    private DaveNetwork() {}

    public static void init() {
        wrapper = NetworkRegistry.INSTANCE.newSimpleChannel(CHANNEL);
        wrapper.registerMessage(ToServerHandler.class, Frame.ToServer.class, 0, Side.SERVER);
        wrapper.registerMessage(ToClientHandler.class, Frame.ToClient.class, 1, Side.CLIENT);
    }

    public static <T extends DavePacket> void onServer(Class<T> type, ServerHandler<T> handler) {
        SERVER_HANDLERS.put(type, handler);
    }

    public static <T extends DavePacket> void onClient(Class<T> type, ClientHandler<T> handler) {
        CLIENT_HANDLERS.put(type, handler);
    }

    public static void sendTo(DavePacket packet, EntityPlayerMP player) {
        int stream = NEXT_STREAM.incrementAndGet();
        List<byte[]> chunks = PayloadChunker.split(encode(packet), PayloadChunker.DEFAULT_CHUNK_BYTES);
        for (int i = 0; i < chunks.size(); i++) {
            wrapper.sendTo(new Frame.ToClient(packet.kind(), stream, i, chunks.size(), chunks.get(i)), player);
        }
    }

    /** Client only (call from client code): sends to the server the client is connected to. */
    public static void sendToServer(DavePacket packet) {
        int stream = NEXT_STREAM.incrementAndGet();
        List<byte[]> chunks = PayloadChunker.split(encode(packet), PayloadChunker.DEFAULT_CHUNK_BYTES);
        for (int i = 0; i < chunks.size(); i++) {
            wrapper.sendToServer(new Frame.ToServer(packet.kind(), stream, i, chunks.size(), chunks.get(i)));
        }
    }

    /** Drops partial streams of a player who left. */
    public static void forgetPlayer(UUID player) {
        SERVER_ASSEMBLERS.remove(player);
    }

    /** Drops partial streams from the previous server connection. */
    public static void resetClientStreams() {
        CLIENT_ASSEMBLER.clear();
    }

    static byte[] encode(DavePacket packet) {
        return GSON.toJson(packet)
            .getBytes(StandardCharsets.UTF_8);
    }

    static DavePacket decode(String kind, byte[] data, DavePackets.Direction expected) {
        Class<? extends DavePacket> type = DavePackets.type(kind);
        if (type == null || DavePackets.direction(kind) != expected) {
            throw new IllegalArgumentException("unexpected packet kind '" + kind + "'");
        }
        DavePacket packet = GSON.fromJson(new String(data, StandardCharsets.UTF_8), type);
        if (packet == null) {
            throw new IllegalArgumentException("empty packet");
        }
        return packet;
    }

    @SuppressWarnings({ "unchecked", "rawtypes" })
    private static void dispatchToServer(DavePacket packet, EntityPlayerMP player) {
        ServerHandler handler = SERVER_HANDLERS.get(packet.getClass());
        if (handler != null) {
            handler.handle(packet, player);
        }
    }

    @SuppressWarnings({ "unchecked", "rawtypes" })
    private static void dispatchToClient(DavePacket packet) {
        ClientHandler handler = CLIENT_HANDLERS.get(packet.getClass());
        if (handler != null) {
            handler.handle(packet);
        }
    }

    /** Receives client frames on the server. Public with a no-arg constructor because FML instantiates it. */
    public static final class ToServerHandler implements IMessageHandler<Frame.ToServer, IMessage> {

        @Override
        public IMessage onMessage(Frame.ToServer frame, MessageContext ctx) {
            EntityPlayerMP player = ctx.getServerHandler().playerEntity;
            try {
                if (frame.invalid || player == null) {
                    return null;
                }
                PayloadChunker.Assembler assembler = SERVER_ASSEMBLERS.computeIfAbsent(
                    player.getUniqueID(),
                    id -> new PayloadChunker.Assembler(MAX_TO_SERVER_BYTES, 4, TimeUnit.SECONDS.toNanos(30)));
                byte[] payload = assembler.accept(frame.streamId, frame.index, frame.total, frame.data);
                if (payload != null) {
                    dispatchToServer(decode(frame.kind, payload, DavePackets.Direction.TO_SERVER), player);
                }
            } catch (Throwable e) { // includes StackOverflowError from absurdly nested JSON
                DaveBridge.LOG.warn(
                    "Ignoring bad davebridge packet '{}' from {}: {}",
                    frame.kind,
                    player == null ? "?" : player.getCommandSenderName(),
                    e.toString());
            }
            return null;
        }
    }

    /** Receives server frames on the client. Must not touch client classes itself; handlers do that. */
    public static final class ToClientHandler implements IMessageHandler<Frame.ToClient, IMessage> {

        @Override
        public IMessage onMessage(Frame.ToClient frame, MessageContext ctx) {
            try {
                if (frame.invalid) {
                    return null;
                }
                byte[] payload = CLIENT_ASSEMBLER.accept(frame.streamId, frame.index, frame.total, frame.data);
                if (payload != null) {
                    dispatchToClient(decode(frame.kind, payload, DavePackets.Direction.TO_CLIENT));
                }
            } catch (Throwable e) {
                DaveBridge.LOG.warn("Ignoring bad davebridge packet '{}' from server: {}", frame.kind, e.toString());
            }
            return null;
        }
    }
}

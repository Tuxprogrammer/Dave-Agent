package com.tuxprogrammer.davebridge.server.lesson;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import net.minecraft.block.Block;
import net.minecraft.entity.EntityLiving;
import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.init.Blocks;
import net.minecraft.pathfinding.PathFinder;
import net.minecraft.pathfinding.PathPoint;
import net.minecraft.world.World;
import net.minecraft.world.WorldServer;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.lesson.LessonLimits;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.DavePacket;
import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.common.protocol.LessonStatus;
import com.tuxprogrammer.davebridge.common.protocol.LessonStop;
import com.tuxprogrammer.davebridge.server.ClientModTracker;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.PlayerJson;
import com.tuxprogrammer.davebridge.server.bridge.MessageRouter;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.bridge.ProtocolException;
import com.tuxprogrammer.davebridge.server.chat.DaveChat;

import cpw.mods.fml.common.FMLCommonHandler;
import cpw.mods.fml.common.eventhandler.SubscribeEvent;
import cpw.mods.fml.common.gameevent.PlayerEvent;
import cpw.mods.fml.common.registry.GameData;

/**
 * Guided demonstrations, server side: the agent's {@code lesson} and {@code lesson_stop} requests and the client's
 * {@code lesson_status} packet (PROTOCOL.md 1.4, 2.3, 2.6).
 * <p>
 * A lesson is validated by {@link LessonParser} on the server thread (it reads chunk and registry state) and sent to
 * the one player's client half as a chunked packet. It needs that player's client half with the {@value #CAP_LESSON}
 * capability, but not {@code clientEvalAllowed}: a lesson is data the client draws, never code. Players without it
 * get a {@value #ERR_NO_CLIENT_MOD} error back to the agent, so Dave can answer in chat instead.
 */
public final class LessonService {

    /** Client capability: plays lessons. */
    public static final String CAP_LESSON = "lesson";
    /** Error code: the player has no client half that can play lessons. */
    public static final String ERR_NO_CLIENT_MOD = "no_client_mod";

    /** Minimum time between two {@code lesson_status} packets from one client that are relayed. */
    static final long STATUS_INTERVAL_MILLIS = 200;
    static final int MAX_STATUS_FIELD = 64;

    /** Sends a packet to a player. Replaceable in tests. */
    interface Sender {

        void send(DavePacket packet, EntityPlayerMP player);
    }

    static Sender sender = DaveNetwork::sendTo;

    private static final Map<UUID, Long> LAST_STATUS = new ConcurrentHashMap<>();

    private LessonService() {}

    /** Registers the agent requests and the client packet. Call once from {@code DaveServer.init}. */
    public static void register(MessageRouter router) {
        router.register("lesson", request -> {
            String target = request.requireString("player");
            JsonElement spec = request.body()
                .get("lesson");
            if (spec == null || !spec.isJsonObject()) {
                throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "missing 'lesson' object");
            }
            router.runOnMainThread(request, "lesson", () -> {
                EntityPlayerMP player = lessonPlayer(target);
                LessonParser.Result result = LessonParser.parse(
                    spec,
                    new double[] { player.posX, player.posY, player.posZ },
                    player.rotationYaw,
                    player.dimension,
                    env(player));
                for (String w : result.warnings) {
                    DaveBridge.LOG.info("lesson warning for {}: {}", player.getCommandSenderName(), w);
                }
                if (result.lesson == null) {
                    throw new ProtocolException(Protocol.ERR_BAD_REQUEST, result.error);
                }
                sender.send(result.lesson, player);
                DaveBridge.LOG.info(
                    "Sent lesson {} ({} steps, {} ticks per pass) to {}",
                    result.lesson.id,
                    result.lesson.steps.length,
                    result.passTicks,
                    player.getCommandSenderName());
                JsonObject ack = request.ackMessage();
                if (ack != null) {
                    ack.addProperty("id", result.lesson.id);
                    ack.addProperty("steps", result.lesson.steps.length);
                    ack.addProperty("dropped", result.dropped);
                    ack.addProperty("passTicks", result.passTicks);
                    JsonArray warnings = new JsonArray();
                    for (String w : result.warnings) warnings.add(new JsonPrimitive(w));
                    ack.add("warnings", warnings);
                }
                return ack;
            });
        });

        router.register("lesson_stop", request -> {
            String target = request.requireString("player");
            String id = request.optString("id", null);
            router.runOnMainThread(request, "lesson_stop", () -> {
                EntityPlayerMP player = lessonPlayer(target);
                LessonStop stop = new LessonStop();
                stop.id = id;
                sender.send(stop, player);
                return null;
            });
        });

        DaveNetwork.onServer(LessonStatus.class, LessonService::onStatus);
        FMLCommonHandler.instance()
            .bus()
            .register(new LogoutHandler());
    }

    /** Forgets the status rate limit of players who leave. Public: FML generates the event dispatcher elsewhere. */
    public static final class LogoutHandler {

        @SubscribeEvent
        public void onLogout(PlayerEvent.PlayerLoggedOutEvent event) {
            try {
                if (event.player != null) {
                    LAST_STATUS.remove(event.player.getUniqueID());
                }
            } catch (Throwable t) {
                DaveBridge.LOG.debug("lesson logout cleanup failed", t);
            }
        }
    }

    /**
     * The online player named {@code target} whose client half plays lessons. Server thread.
     *
     * @throws ProtocolException {@code not_found} if offline, {@value #ERR_NO_CLIENT_MOD} without a capable client
     */
    static EntityPlayerMP lessonPlayer(String target) throws ProtocolException {
        if (target == null || target.isEmpty() || "@a".equals(target)) {
            throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "'player' must name one player");
        }
        // resolveTargets returns nobody for an absent player (a say only warns); a lesson needs a player
        List<EntityPlayerMP> found = DaveChat.resolveTargets(target);
        if (found.isEmpty()) {
            throw new ProtocolException(Protocol.ERR_NOT_FOUND, "player " + target + " is not online");
        }
        EntityPlayerMP player = found.get(0);
        if (!canPlayLessons(DaveServer.CLIENTS.get(player.getUniqueID()))) {
            throw new ProtocolException(
                ERR_NO_CLIENT_MOD,
                player.getCommandSenderName()
                    + " doesn't have the DaveBridge client half (with lesson support); explain it in chat instead");
        }
        return player;
    }

    /** The client half speaks our packet protocol and reported the lesson capability. */
    static boolean canPlayLessons(ClientModTracker.Info info) {
        if (info == null || info.protocol != DavePackets.PROTOCOL_VERSION || info.capabilities == null) {
            return false;
        }
        for (String capability : info.capabilities) {
            if (CAP_LESSON.equals(capability)) {
                return true;
            }
        }
        return false;
    }

    /** World and registry lookups for the parser. Server thread only. */
    /** A mob-sized body (0.6 x 1.8, vanilla's PathPoint size 1 x 2 x 1) for vanilla's stand check. */
    private static final PathPoint MOB_SIZE = new PathPoint(1, 2, 1);

    /** Never spawned: only its world and position are read, by vanilla's canEntityStandAt. */
    private static final class Probe extends EntityLiving {

        Probe(World world) {
            super(world);
            setSize(0.6F, 1.8F);
        }
    }

    /**
     * Vanilla's mob walkability on the player's world, for loaded chunks only: doors count as passable (the player
     * can open them), water is swum, lava is avoided.
     */
    static MobPath.Grid grid(WorldServer world, EntityPlayerMP player) {
        Probe probe = new Probe(world);
        probe.setPosition(player.posX, player.posY, player.posZ);
        return new MobPath.Grid() {

            @Override
            public int stand(int x, int y, int z) {
                if (y < 0 || y > 255) return y < 0 ? 0 : 1;
                // PathFinder.canEntityStandAt, the static one (unnamed in the dev mappings)
                return PathFinder.func_82565_a(probe, x, y, z, MOB_SIZE, false, true, true);
            }

            @Override
            public boolean loaded(int x, int z) {
                return world.theChunkProviderServer.chunkExists(x >> 4, z >> 4);
            }

            @Override
            public int maxFall() {
                return 3; // vanilla getMaxFallHeight for a mob with no attack target
            }
        };
    }

    static LessonParser.Env env(EntityPlayerMP player) {
        WorldServer world = player.getServerForPlayer();
        ClientModTracker.Info client = DaveServer.CLIENTS.get(player.getUniqueID());
        String version = client == null ? null : client.modVersion;
        double radius = LessonLimits.radiusFor(version);
        int steps = LessonLimits.stepsFor(version);
        MobPath.Grid grid = world == null ? null : grid(world, player);
        return new LessonParser.Env() {

            @Override
            public double maxRadius() {
                return radius;
            }

            @Override
            public int maxSteps() {
                return steps;
            }

            @Override
            public MobPath.Route route(double[] from, double[] to) {
                return grid == null ? null : MobPath.find(grid, from, to, MobPath.NODE_BUDGET);
            }

            @Override
            public boolean chunkLoaded(int x, int z) {
                // chunkExists only looks at loaded chunks; it never loads or generates one.
                return world != null && world.theChunkProviderServer.chunkExists(x >> 4, z >> 4);
            }

            @Override
            public boolean itemExists(String name) {
                return GameData.getItemRegistry()
                    .getObject(name) != null;
            }

            @Override
            public boolean blockExists(String name) {
                // The block registry answers air for unknown names.
                Block block = (Block) GameData.getBlockRegistry()
                    .getObject(name);
                return block != null && block != Blocks.air;
            }
        };
    }

    /** A lesson ended on a client: tell the agent. Any thread; the client is untrusted. */
    private static void onStatus(LessonStatus status, EntityPlayerMP player) {
        UUID id = player.getUniqueID();
        if (!DaveServer.CLIENTS.hasClientMod(id)) {
            return;
        }
        long now = System.currentTimeMillis();
        Long last = LAST_STATUS.put(id, now);
        if (last != null && now - last < STATUS_INTERVAL_MILLIS) {
            return; // a misbehaving client; drop the burst
        }
        JsonObject event = statusEvent(status);
        if (event == null) {
            return;
        }
        DaveServer.QUEUE.submit("lesson_status", () -> {
            PlayerJson.describe(player, event);
            DaveServer.BRIDGE.broadcast(event);
        });
    }

    /** The agent event for a status packet, or null if the packet is not a valid status. Pure. */
    static JsonObject statusEvent(LessonStatus status) {
        if (status == null
            || !(LessonStatus.STATE_FINISHED.equals(status.state) || LessonStatus.STATE_STOPPED.equals(status.state))) {
            return null;
        }
        JsonObject event = Protocol.message("lesson_status");
        event.addProperty("id", clip(status.id));
        event.addProperty("state", status.state);
        event.addProperty("reason", knownReason(status.reason));
        return event;
    }

    static String knownReason(String reason) {
        if (reason == null) return "other";
        switch (reason) {
            case LessonStatus.REASON_PLAYER:
            case LessonStatus.REASON_WALKED_AWAY:
            case LessonStatus.REASON_DIMENSION:
            case LessonStatus.REASON_REPLACED:
            case LessonStatus.REASON_AGENT:
            case LessonStatus.REASON_TIMEOUT:
            case LessonStatus.REASON_REJECTED:
            case LessonStatus.REASON_DONE:
                return reason;
            default:
                return "other";
        }
    }

    private static String clip(String s) {
        if (s == null) return "";
        return s.length() > MAX_STATUS_FIELD ? s.substring(0, MAX_STATUS_FIELD) : s;
    }
}

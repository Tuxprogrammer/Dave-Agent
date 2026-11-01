package com.tuxprogrammer.davebridge.server;

import net.minecraft.server.MinecraftServer;
import net.minecraftforge.common.MinecraftForge;

import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.tasks.MainThreadQueue;
import com.tuxprogrammer.davebridge.server.bridge.BridgeService;
import com.tuxprogrammer.davebridge.server.chat.ChatHandlers;
import com.tuxprogrammer.davebridge.server.command.CommandDave;
import com.tuxprogrammer.davebridge.server.eval.EvalService;
import com.tuxprogrammer.davebridge.server.network.ServerPacketHandlers;

import cpw.mods.fml.common.FMLCommonHandler;
import cpw.mods.fml.common.event.FMLServerStartingEvent;

/**
 * Logical-server half of the mod: the agent WebSocket, chat hooks, the relay to and from client mods, and the
 * {@code /dave} command. Runs on a dedicated server and, inside a client, on the integrated server; it never references
 * client classes.
 */
public final class DaveServer {

    /** Runs agent actions on the server thread. Later milestones (eval, introspection) submit work here too. */
    public static final MainThreadQueue QUEUE = new MainThreadQueue();

    /** Which online players have the client half, and what it told us. */
    public static final ClientModTracker CLIENTS = new ClientModTracker();

    /** Owns the WebSocket server and the message router. */
    public static final BridgeService BRIDGE = new BridgeService(QUEUE);

    private DaveServer() {}

    public static void init() {
        QUEUE.setMaxDepth(Config.maxQueueDepth);
        ChatHandlers.register(BRIDGE.router());
        EvalService.register(BRIDGE.router());
        ServerPacketHandlers.register();

        ServerEventHandler handler = new ServerEventHandler();
        MinecraftForge.EVENT_BUS.register(handler); // ServerChatEvent
        FMLCommonHandler.instance()
            .bus()
            .register(handler); // server tick, login and logout

        // A SIGTERM (e.g. "docker stop" without an RCON stop) runs MinecraftServer's shutdown hook, which does not fire
        // FMLServerStoppingEvent. Close the socket politely in that case too; every step is idempotent.
        Runtime.getRuntime()
            .addShutdownHook(new Thread(() -> {
                try {
                    shutdownBridge();
                } catch (Throwable ignored) {}
            }, "DaveBridge-shutdown"));
    }

    public static void serverStarting(FMLServerStartingEvent event) {
        // The queue is static: on an integrated server, tasks queued after the previous world stopped would otherwise
        // run against that world's stale players on this world's first tick.
        int stale = QUEUE.clear("stale task from a previous server");
        if (stale > 0) {
            DaveBridge.LOG.info("Dropped {} stale main-thread tasks", stale);
        }
        event.registerServerCommand(new CommandDave());
    }

    public static void serverStarted() {
        MinecraftServer server = MinecraftServer.getServer();
        if (server != null && !server.isDedicatedServer() && !Config.startOnIntegratedServer) {
            DaveBridge.LOG.info("Integrated server: not opening the agent socket (network.startOnIntegratedServer)");
            return;
        }
        BRIDGE.start();
    }

    public static void serverStopping() {
        EvalService.serverStopping();
        shutdownBridge();
        CLIENTS.clear();
    }

    /**
     * Order matters: refuse new agent messages, fail the queued actions while the sockets are still open (so the
     * agent gets {@code cancelled} for each reqId), then close the sockets. The second clear catches anything a socket
     * thread queued in between.
     */
    private static void shutdownBridge() {
        BRIDGE.beginStopping();
        QUEUE.clear("server stopping");
        BRIDGE.stop();
        QUEUE.clear("server stopping");
    }

    /**
     * Re-reads the config and restarts the socket if its settings changed. Call on the server thread.
     *
     * @return false if the file could not be parsed; nothing changed then
     */
    public static boolean reload() {
        if (!Config.reload()) {
            return false;
        }
        QUEUE.setMaxDepth(Config.maxQueueDepth);
        MinecraftServer server = MinecraftServer.getServer();
        boolean allowed = server == null || server.isDedicatedServer() || Config.startOnIntegratedServer;
        BRIDGE.applyConfig(allowed);
        return true;
    }
}

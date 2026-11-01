package com.tuxprogrammer.davebridge.server;

import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.server.MinecraftServer;
import net.minecraftforge.event.ServerChatEvent;

import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.chat.ChatRelay;
import com.tuxprogrammer.davebridge.server.chat.TriggerMatcher;

import cpw.mods.fml.common.eventhandler.EventPriority;
import cpw.mods.fml.common.eventhandler.SubscribeEvent;
import cpw.mods.fml.common.gameevent.PlayerEvent;
import cpw.mods.fml.common.gameevent.TickEvent;

/**
 * Game events the bridge reacts to. Every handler catches everything: a bridge problem must never break chat, logins
 * or the tick loop.
 */
public class ServerEventHandler {

    /**
     * Players we announced with player_join. FML fires the logout event even for connections it rejected during the
     * mod handshake, which never logged in; those must not produce a player_leave.
     */
    private final Set<UUID> joined = ConcurrentHashMap.newKeySet();

    /**
     * Forwards chat to the agent. LOWEST priority without receiveCanceled, so messages muted or cancelled by other mods
     * are not forwarded.
     * <p>
     * In Forge 10.13.4 chat packets are queued and processed on the server thread, but this handler does not rely on
     * that: it only reads plain player fields and hands a string to the socket's send queue.
     */
    @SubscribeEvent(priority = EventPriority.LOWEST)
    public void onServerChat(ServerChatEvent event) {
        try {
            if (event.player == null) {
                return;
            }
            String prompt = TriggerMatcher.match(event.message, Config.triggerPrefixes);
            boolean triggered = prompt != null;
            if (!triggered && !Config.forwardAllChat) {
                return;
            }
            ChatRelay.relay(event.player, event.message, "chat", triggered, prompt, null);
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Failed to forward chat message", t);
        }
    }

    @SubscribeEvent
    public void onPlayerLoggedIn(PlayerEvent.PlayerLoggedInEvent event) {
        try {
            if (event.player instanceof EntityPlayerMP) {
                joined.add(event.player.getUniqueID());
                JsonObject msg = Protocol.message("player_join");
                PlayerJson.describe((EntityPlayerMP) event.player, msg);
                DaveServer.BRIDGE.broadcast(msg);
            }
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Failed to forward player join", t);
        }
    }

    @SubscribeEvent
    public void onPlayerLoggedOut(PlayerEvent.PlayerLoggedOutEvent event) {
        try {
            if (event.player instanceof EntityPlayerMP) {
                EntityPlayerMP player = (EntityPlayerMP) event.player;
                UUID id = player.getUniqueID();
                if (joined.remove(id)) {
                    JsonObject msg = Protocol.message("player_leave");
                    PlayerJson.describe(player, msg);
                    DaveServer.BRIDGE.broadcast(msg);
                }
                DaveServer.CLIENTS.remove(id);
                DaveNetwork.forgetPlayer(id);
                com.tuxprogrammer.davebridge.server.eval.ClientEvalRelay.playerLeft(id);
            }
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Failed to forward player leave", t);
        }
    }

    /** Drains the main-thread queue once per server tick within the configured time budget. */
    @SubscribeEvent
    public void onServerTick(TickEvent.ServerTickEvent event) {
        if (event.phase != TickEvent.Phase.END) {
            return;
        }
        try {
            MinecraftServer server = MinecraftServer.getServer();
            if (server != null) {
                DaveServer.BRIDGE.setServerTick(server.getTickCounter());
            }
            DaveServer.QUEUE.drain(Config.tickBudgetMillis * 1_000_000L);
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Main-thread queue drain failed", t);
        }
    }
}

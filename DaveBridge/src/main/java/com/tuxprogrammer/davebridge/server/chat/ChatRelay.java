package com.tuxprogrammer.davebridge.server.chat;

import java.util.UUID;

import net.minecraft.entity.player.EntityPlayerMP;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.PlayerJson;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;

/** Builds and sends {@code chat} events to the agent, for both plain chat and client-mod asks. */
public final class ChatRelay {

    private ChatRelay() {}

    /**
     * Forwards a player's message to connected agents.
     *
     * @param source    {@code "chat"} for normal chat, {@code "client"} for an Ask from the client half
     * @param triggered whether the message addressed Dave
     * @param prompt    the message without its trigger prefix, or null when not triggered
     * @param context   client-reported context (untrusted), or null
     * @return the number of agents that received it
     */
    public static int relay(EntityPlayerMP player, String message, String source, boolean triggered, String prompt,
        JsonElement context) {
        JsonObject event = Protocol.message("chat");
        event.addProperty(
            "id",
            UUID.randomUUID()
                .toString());
        PlayerJson.describe(player, event);
        event.addProperty("message", message);
        event.addProperty("triggered", triggered);
        if (prompt != null) {
            event.addProperty("prompt", prompt);
        }
        event.addProperty("source", source);
        if (context != null) {
            event.add("context", context);
        }
        int sent = DaveServer.BRIDGE.broadcast(event);
        if (triggered && sent == 0 && Config.notifyWhenOffline) {
            player.addChatMessage(DaveChat.notice(Config.botName + " is not connected right now."));
        }
        return sent;
    }
}

package com.tuxprogrammer.davebridge.server.chat;

import java.util.List;

import net.minecraft.entity.player.EntityPlayerMP;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.tuxprogrammer.davebridge.server.PlayerJson;
import com.tuxprogrammer.davebridge.server.bridge.MessageRouter;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.bridge.ProtocolException;
import com.tuxprogrammer.davebridge.server.bridge.Request;

/** Milestone 1 agent actions: {@code say}, {@code thinking}, {@code list_players}. */
public final class ChatHandlers {

    private ChatHandlers() {}

    public static void register(MessageRouter router) {
        router.register("say", request -> {
            String target = request.optString("target", "@a");
            String text = request.optString("text", null);
            String markup = request.optString("markup", null);
            JsonElement components = request.body()
                .get("components");
            if (components != null && components.isJsonNull()) components = null;
            int given = (text != null ? 1 : 0) + (markup != null ? 1 : 0) + (components != null ? 1 : 0);
            if (given != 1) {
                throw new ProtocolException(
                    Protocol.ERR_BAD_REQUEST,
                    "say needs exactly one of 'text', 'markup' or 'components'");
            }
            String replyTo = request.optString("replyTo", null);
            JsonElement comps = components;
            router.runOnMainThread(request, "say", () -> {
                DaveChat.SayResult result = DaveChat.say(target, text, markup, comps, replyTo);
                JsonObject ack = withRecipients(request, result.recipients);
                if (ack != null) {
                    JsonArray warnings = new JsonArray();
                    for (String w : result.warnings) warnings.add(new JsonPrimitive(w));
                    ack.add("warnings", warnings);
                }
                for (String w : result.warnings) {
                    com.tuxprogrammer.davebridge.DaveBridge.LOG.info("say warning: {}", w);
                }
                return ack;
            });
        });

        router.register("thinking", request -> {
            String target = request.optString("target", "@a");
            router.runOnMainThread(request, "thinking", () -> withRecipients(request, DaveChat.thinking(target)));
        });

        router.register("list_players", request -> router.runOnMainThread(request, "list_players", () -> {
            List<EntityPlayerMP> online = DaveChat.onlinePlayers();
            JsonArray players = new JsonArray();
            for (EntityPlayerMP player : online) {
                players.add(PlayerJson.describe(player, new JsonObject()));
            }
            JsonObject reply = Protocol.message("players");
            reply.add("players", players);
            return reply;
        }));
    }

    private static JsonObject withRecipients(Request request, int recipients) {
        JsonObject ack = request.ackMessage();
        if (ack != null) {
            ack.addProperty("recipients", recipients);
        }
        return ack;
    }
}

package com.tuxprogrammer.davebridge.server.eval;

import java.util.Iterator;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import net.minecraft.entity.player.EntityPlayerMP;

import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.Config;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.ClientEvalRequest;
import com.tuxprogrammer.davebridge.common.protocol.ClientEvalResult;
import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.server.ClientModTracker;
import com.tuxprogrammer.davebridge.server.DaveServer;
import com.tuxprogrammer.davebridge.server.bridge.MessageRouter;
import com.tuxprogrammer.davebridge.server.bridge.Protocol;
import com.tuxprogrammer.davebridge.server.bridge.ProtocolException;
import com.tuxprogrammer.davebridge.server.bridge.Request;

/**
 * {@code client_eval} (PROTOCOL.md 1.8): relays a script to one player's own client and the result back.
 * <p>
 * Client eval runs code on a friend's machine, so it is strictly opt-in: the request is sent only if the player's
 * client half reported {@code clientEvalAllowed} (checked against the tracker on the server thread at send time, so
 * a mid-session opt-out is respected) and can run scripts (the {@code eval} capability). The client re-checks its own
 * setting too. A result is accepted only for an id this server sent to that same player.
 */
public final class ClientEvalRelay {

    /** Client capability: the client half can run {@code client_eval_request}. */
    public static final String CAP_EVAL = "eval";

    private static final AtomicLong NEXT_ID = new AtomicLong();
    private static final Map<String, Waiting> WAITING = new ConcurrentHashMap<>();

    private ClientEvalRelay() {}

    private static final class Waiting {

        final Request request;
        final UUID player;
        final String playerName;
        final String agentId;

        Waiting(Request request, UUID player, String playerName, String agentId) {
            this.request = request;
            this.player = player;
            this.playerName = playerName;
            this.agentId = agentId;
        }
    }

    public static void register(MessageRouter router) {
        router.register("client_eval", ClientEvalRelay::handle);
    }

    /**
     * Whether client eval may be sent to a player with this client record: null if yes, else the error code
     * ({@code not_opted_in} or {@code unsupported}). Pure; unit-tested.
     */
    public static String gate(ClientModTracker.Info info) {
        if (info == null || info.protocol != DavePackets.PROTOCOL_VERSION) {
            return "not_opted_in";
        }
        if (!info.clientEvalAllowed) {
            return "not_opted_in";
        }
        if (info.capabilities == null) {
            return "unsupported";
        }
        for (String c : info.capabilities) {
            if (CAP_EVAL.equals(c)) {
                return null;
            }
        }
        return "unsupported";
    }

    private static void handle(Request request) throws ProtocolException {
        if (!Config.clientEvalRelay) {
            throw new ProtocolException("disabled", "client eval is turned off on this server (eval.clientEvalRelay)");
        }
        String playerName = request.requireString("player");
        String script = request.requireString("script");
        if (script.length() > EvalService.MAX_SCRIPT_CHARS) {
            throw new ProtocolException(Protocol.ERR_BAD_REQUEST, "script too long");
        }
        String agentId = request.optString("id", null);
        long timeoutMs = EvalService.optLong(request.body(), "timeoutMs", 500);
        JsonObject params = request.body()
            .has("params")
            && request.body()
                .get("params")
                .isJsonObject() ? request.body()
                    .getAsJsonObject("params") : null;
        EvalService.onMain(request, "client_eval", () -> {
            EntityPlayerMP player = EvalService.findPlayer(playerName);
            if (player == null) {
                throw new ProtocolException(Protocol.ERR_NOT_FOUND, "player " + playerName + " is not online");
            }
            // The opt-in is read now, on the server thread, from the latest client_hello / client_settings.
            String refused = gate(DaveServer.CLIENTS.get(player.getUniqueID()));
            if (refused != null) {
                throw new ProtocolException(
                    refused,
                    "not_opted_in".equals(refused)
                        ? player.getCommandSenderName()
                            + " has not opted in to client eval (needs the DaveBridge client mod and /davebridge optin)"
                        : player.getCommandSenderName() + "'s DaveBridge client is too old to run scripts");
            }
            String id = "ce" + NEXT_ID.incrementAndGet();
            WAITING.put(id, new Waiting(request, player.getUniqueID(), player.getCommandSenderName(), agentId));
            ClientEvalRequest packet = new ClientEvalRequest();
            packet.id = id;
            packet.script = script;
            packet.mode = "groovy";
            packet.timeoutMs = (int) Math.max(10, Math.min(60000, timeoutMs));
            packet.params = params;
            DaveNetwork.sendTo(packet, player);
            DaveBridge.LOG.info("Sent client eval {} to {}", id, player.getCommandSenderName());
            long wait = Math.max(1, Config.clientEvalTimeoutSeconds);
            EvalService.schedule(
                () -> finish(id, null, "timeout", "no answer from the client in " + wait + " s"),
                wait,
                TimeUnit.SECONDS);
            return EvalService.PENDING;
        });
    }

    /** A {@code client_eval_result} packet from a player (any thread). */
    public static void onResult(ClientEvalResult result, EntityPlayerMP from) {
        if (result == null || result.id == null) {
            return;
        }
        Waiting w = WAITING.get(result.id);
        if (w == null || !w.player.equals(from.getUniqueID())) {
            DaveBridge.LOG
                .debug("Dropping unexpected client_eval_result {} from {}", result.id, from.getCommandSenderName());
            return;
        }
        if (WAITING.remove(result.id, w)) {
            JsonObject reply = message(w);
            reply.addProperty("ok", result.ok);
            if (result.result != null) {
                reply.add("result", result.result);
            }
            if (result.error != null) {
                reply.addProperty("error", EvalService.clip(result.error, 4000));
            }
            if (result.errorType != null) {
                reply.addProperty("errorType", EvalService.clip(result.errorType, 40));
            }
            if (result.output != null && !result.output.isEmpty()) {
                reply.addProperty("output", EvalService.clip(result.output, Config.evalMaxOutputChars));
            }
            reply.addProperty("ms", result.ms);
            if (result.truncated) {
                reply.addProperty("truncated", true);
            }
            w.request.reply(reply);
        }
    }

    /** A player left: every eval waiting on them fails at once. */
    public static void playerLeft(UUID player) {
        for (Iterator<Map.Entry<String, Waiting>> it = WAITING.entrySet()
            .iterator(); it.hasNext();) {
            Map.Entry<String, Waiting> e = it.next();
            if (e.getValue().player.equals(player)) {
                finish(e.getKey(), e.getValue(), "disconnected", e.getValue().playerName + " logged out");
            }
        }
    }

    /** Server stopping: answers everything still waiting. */
    public static void serverStopping() {
        for (String id : WAITING.keySet()) {
            finish(id, null, "disconnected", "server stopping");
        }
    }

    private static void finish(String id, Waiting expected, String errorType, String error) {
        Waiting w = expected != null ? (WAITING.remove(id, expected) ? expected : null) : WAITING.remove(id);
        if (w == null) {
            return; // already answered
        }
        JsonObject reply = message(w);
        reply.addProperty("ok", false);
        reply.addProperty("errorType", errorType);
        reply.addProperty("error", error);
        w.request.reply(reply);
    }

    private static JsonObject message(Waiting w) {
        JsonObject reply = Protocol.message("client_eval_result");
        if (w.agentId != null) {
            reply.addProperty("id", w.agentId);
        }
        reply.addProperty("player", w.playerName);
        reply.addProperty("side", "client");
        return reply;
    }
}

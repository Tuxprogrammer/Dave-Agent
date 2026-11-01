package com.tuxprogrammer.davebridge.client;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletionException;

import net.minecraft.client.Minecraft;
import net.minecraft.item.ItemStack;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.eval.EvalHelpers;
import com.tuxprogrammer.davebridge.common.eval.JsonDump;
import com.tuxprogrammer.davebridge.common.eval.ScriptEngine;
import com.tuxprogrammer.davebridge.common.network.DaveNetwork;
import com.tuxprogrammer.davebridge.common.protocol.ClientEvalRequest;
import com.tuxprogrammer.davebridge.common.protocol.ClientEvalResult;

/**
 * Runs a {@code client_eval_request} on this client (PROTOCOL.md 1.8), only if the player opted in
 * ({@link ClientConfig#clientEvalAllowed}, re-read here: the server's check is not enough, since the code runs on
 * this machine). Compiled off-thread, run on the client thread with a time limit; the result goes back as
 * {@link ClientEvalResult}.
 */
public final class ClientEval {

    /** The client's own ceiling, whatever the server asks: a script holds the render thread while it runs. */
    static final int MAX_TIMEOUT_MS = 2000;
    static final int DEFAULT_TIMEOUT_MS = 500;
    /** Results stay well under the 256 KiB a client packet may have. */
    static final int MAX_RESULT_CHARS = 64 * 1024;

    private static final Gson GSON = new Gson();

    private ClientEval() {}

    /** Packet handler (any thread). */
    public static void onRequest(ClientEvalRequest req) {
        if (req == null || req.id == null) {
            return;
        }
        if (!ClientConfig.clientEvalAllowed) {
            DaveBridge.LOG.info("Refused client eval {}: client eval is not allowed in davebridge-client.cfg", req.id);
            reply(failure(req.id, "not_opted_in", "this player has not opted in to client eval"));
            return;
        }
        if (req.script == null || req.script.isEmpty()) {
            reply(failure(req.id, "compile", "empty script"));
            return;
        }
        int timeout = req.timeoutMs <= 0 ? DEFAULT_TIMEOUT_MS : Math.min(MAX_TIMEOUT_MS, req.timeoutMs);
        Object params = req.params == null || req.params.isJsonNull() ? new HashMap<String, Object>()
            : GSON.fromJson(req.params, Object.class);
        DaveBridge.LOG.info("Running client eval {} from the server", req.id);
        ScriptEngine.shared()
            .compileAsync(req.script)
            .whenComplete((compiled, failure) -> {
                if (failure != null) {
                    Throwable cause = failure instanceof CompletionException && failure.getCause() != null
                        ? failure.getCause()
                        : failure;
                    String kind = cause instanceof ScriptEngine.CompileError ? ((ScriptEngine.CompileError) cause).kind
                        : "compile";
                    reply(failure(req.id, kind, String.valueOf(cause.getMessage())));
                    return;
                }
                ClientProxy.QUEUE.submit("client_eval", () -> {
                    // Re-check on the client thread: the player may have opted out while it compiled.
                    if (!ClientConfig.clientEvalAllowed) {
                        reply(failure(req.id, "not_opted_in", "this player opted out"));
                        return;
                    }
                    JsonObject out = ScriptEngine.shared()
                        .run(
                            compiled,
                            bindings(params),
                            timeout,
                            new JsonDump.Limits(8, 300, 4000, MAX_RESULT_CHARS),
                            8 * 1024);
                    reply(toPacket(req.id, out));
                });
            });
    }

    static Map<String, Object> bindings(Object params) {
        Minecraft mc = Minecraft.getMinecraft();
        Map<String, Object> b = new HashMap<>();
        b.put("mc", mc);
        b.put("player", mc.thePlayer);
        b.put("world", mc.theWorld);
        b.put("params", params);
        b.put("dave", new Helpers());
        b.put("log", DaveBridge.LOG);
        return b;
    }

    private static ClientEvalResult toPacket(String id, JsonObject out) {
        ClientEvalResult r = new ClientEvalResult();
        r.id = id;
        r.ok = out.has("ok") && out.get("ok")
            .getAsBoolean();
        r.result = out.get("result");
        r.error = string(out.get("error"));
        r.errorType = string(out.get("errorType"));
        r.output = string(out.get("output"));
        r.ms = out.has("ms") ? out.get("ms")
            .getAsDouble() : 0;
        r.truncated = out.has("truncated");
        return r;
    }

    private static String string(JsonElement e) {
        return e == null || e.isJsonNull() ? null : e.getAsString();
    }

    private static ClientEvalResult failure(String id, String type, String message) {
        ClientEvalResult r = new ClientEvalResult();
        r.id = id;
        r.ok = false;
        r.errorType = type;
        r.error = message;
        return r;
    }

    private static void reply(ClientEvalResult result) {
        try {
            DaveNetwork.sendToServer(result);
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Could not send the client eval result", t);
        }
    }

    /** The client's {@code dave}: the common helpers plus what only a client has. */
    public static final class Helpers extends EvalHelpers {

        /** An item's tooltip lines as this client shows them (formatting codes removed). */
        @SuppressWarnings("unchecked")
        public List<String> tooltip(ItemStack stack) {
            List<String> out = new ArrayList<>();
            if (stack == null) {
                return out;
            }
            Minecraft mc = Minecraft.getMinecraft();
            for (Object line : stack.getTooltip(mc.thePlayer, mc.gameSettings.advancedItemTooltips)) {
                out.add(
                    String.valueOf(line)
                        .replaceAll("§.", ""));
            }
            return out;
        }

        public Minecraft mc() {
            return Minecraft.getMinecraft();
        }
    }
}

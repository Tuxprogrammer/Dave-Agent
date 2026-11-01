package com.tuxprogrammer.davebridge.server.bridge;

import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.concurrent.Callable;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.RejectedExecutionException;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import com.google.gson.JsonParser;
import com.tuxprogrammer.davebridge.DaveBridge;
import com.tuxprogrammer.davebridge.common.tasks.MainThreadQueue;

/**
 * Maps inbound message types to handlers. Milestone 1 registers chat actions; later milestones register eval,
 * introspection and mapping handlers the same way.
 */
public final class MessageRouter {

    private final Map<String, MessageHandler> handlers = new ConcurrentHashMap<>();
    private final MainThreadQueue queue;

    public MessageRouter(MainThreadQueue queue) {
        this.queue = queue;
    }

    public void register(String type, MessageHandler handler) {
        handlers.put(type, handler);
    }

    public Set<String> types() {
        return Collections.unmodifiableSet(new TreeSet<>(handlers.keySet()));
    }

    /**
     * Parses a raw JSON object. Throws a {@code bad_json} {@link ProtocolException} on anything that is not an object
     * with a string {@code type}; when the object parsed, the exception carries its reqId so the error can echo it.
     */
    public static JsonObject parse(String raw) throws ProtocolException {
        JsonElement el;
        try {
            el = new JsonParser().parse(raw);
        } catch (JsonParseException | IllegalStateException e) {
            throw new ProtocolException(Protocol.ERR_BAD_JSON, "malformed JSON: " + e.getMessage());
        }
        if (el == null || !el.isJsonObject()) {
            throw new ProtocolException(Protocol.ERR_BAD_JSON, "expected a JSON object");
        }
        JsonObject obj = el.getAsJsonObject();
        JsonElement type = obj.get("type");
        if (type == null || !type.isJsonPrimitive()
            || !type.getAsJsonPrimitive()
                .isString()) {
            throw new ProtocolException(Protocol.ERR_BAD_JSON, "missing string 'type'", Protocol.reqIdOf(obj));
        }
        return obj;
    }

    /** Dispatches one message from an authenticated session. Never throws. */
    void dispatch(ClientSession session, JsonObject body) {
        Request request = null;
        try {
            String type = Protocol.requireString(body, "type");
            request = new Request(session, type, body);
            MessageHandler handler = handlers.get(type);
            if (handler == null) {
                request.error(Protocol.ERR_UNKNOWN_TYPE, "unknown message type '" + type + "'");
                return;
            }
            handler.handle(request);
        } catch (ProtocolException e) {
            JsonElement reqId = request == null ? null : request.reqId();
            session.send(Protocol.error(e.code(), e.getMessage(), reqId));
        } catch (Throwable t) {
            DaveBridge.LOG.warn("Handler failed for message from {}", session, t);
            JsonElement reqId = request == null ? null : request.reqId();
            session.send(Protocol.error(Protocol.ERR_INTERNAL, t.toString(), reqId));
        }
    }

    /**
     * Runs {@code work} on the server thread. When it returns a message, that message is sent as the reply (with
     * reqId). When it returns null, an {@code ack} is sent if the agent supplied a reqId. Failures become
     * {@code error} messages; a {@link ProtocolException} keeps its code.
     */
    public void runOnMainThread(Request request, String label, Callable<JsonObject> work) {
        queue.submit(label, work)
            .whenComplete((result, failure) -> {
                try {
                    if (failure == null) {
                        if (result != null) {
                            request.reply(result);
                        } else {
                            request.ack();
                        }
                        return;
                    }
                    Throwable cause = failure instanceof CompletionException && failure.getCause() != null
                        ? failure.getCause()
                        : failure;
                    if (cause instanceof ProtocolException) {
                        request.error(((ProtocolException) cause).code(), cause.getMessage());
                    } else if (cause instanceof RejectedExecutionException) {
                        request.error(Protocol.ERR_QUEUE_FULL, cause.getMessage());
                    } else if (cause instanceof CancellationException) {
                        request.error(Protocol.ERR_CANCELLED, String.valueOf(cause.getMessage()));
                    } else {
                        DaveBridge.LOG.warn("Main-thread task '{}' for {} failed", label, request.session(), cause);
                        request.error(Protocol.ERR_INTERNAL, cause.toString());
                    }
                } catch (Throwable t) {
                    DaveBridge.LOG.warn("Failed to report result of '{}'", label, t);
                }
            });
    }
}

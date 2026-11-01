package com.tuxprogrammer.davebridge.server.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

/** Helpers and constants for the agent WebSocket protocol. See PROTOCOL.md. */
public final class Protocol {

    /** Bumped on incompatible changes to the WebSocket protocol. */
    public static final int VERSION = 1;

    public static final String ERR_BAD_JSON = "bad_json";
    public static final String ERR_BAD_REQUEST = "bad_request";
    public static final String ERR_UNKNOWN_TYPE = "unknown_type";
    public static final String ERR_UNAUTHORIZED = "unauthorized";
    public static final String ERR_NOT_FOUND = "not_found";
    public static final String ERR_QUEUE_FULL = "queue_full";
    public static final String ERR_CANCELLED = "cancelled";
    public static final String ERR_INTERNAL = "internal";

    private Protocol() {}

    /** A new outbound message with {@code type} and {@code ts} (epoch millis) set. */
    public static JsonObject message(String type) {
        JsonObject obj = new JsonObject();
        obj.addProperty("type", type);
        obj.addProperty("ts", System.currentTimeMillis());
        return obj;
    }

    /** The message's {@code reqId}, or null when it is absent or JSON null. */
    public static JsonElement reqIdOf(JsonObject body) {
        JsonElement id = body.get("reqId");
        return id == null || id.isJsonNull() ? null : id;
    }

    public static JsonObject error(String code, String message, JsonElement reqId) {
        JsonObject obj = message("error");
        obj.addProperty("code", code);
        obj.addProperty("message", message);
        if (reqId != null) {
            obj.add("reqId", reqId);
        }
        return obj;
    }

    /** The string value of {@code key}, or {@code def} if absent or null. Fails if it is not a string. */
    public static String optString(JsonObject obj, String key, String def) throws ProtocolException {
        JsonElement el = obj.get(key);
        if (el == null || el.isJsonNull()) {
            return def;
        }
        if (!el.isJsonPrimitive() || !el.getAsJsonPrimitive()
            .isString()) {
            throw new ProtocolException(ERR_BAD_REQUEST, "'" + key + "' must be a string");
        }
        return el.getAsString();
    }

    public static String requireString(JsonObject obj, String key) throws ProtocolException {
        String value = optString(obj, key, null);
        if (value == null) {
            throw new ProtocolException(ERR_BAD_REQUEST, "missing '" + key + "'");
        }
        return value;
    }
}

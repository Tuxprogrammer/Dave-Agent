package com.tuxprogrammer.davebridge.server.bridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

/** One inbound message from an authenticated agent, with helpers that echo its {@code reqId} back. */
public final class Request {

    private final ClientSession session;
    private final String type;
    private final JsonObject body;
    private final JsonElement reqId;

    Request(ClientSession session, String type, JsonObject body) {
        this.session = session;
        this.type = type;
        this.body = body;
        this.reqId = Protocol.reqIdOf(body);
    }

    public ClientSession session() {
        return session;
    }

    public String type() {
        return type;
    }

    public JsonObject body() {
        return body;
    }

    /** The agent's request id (any JSON value), or null. */
    public JsonElement reqId() {
        return reqId;
    }

    public String optString(String key, String def) throws ProtocolException {
        return Protocol.optString(body, key, def);
    }

    public String requireString(String key) throws ProtocolException {
        return Protocol.requireString(body, key);
    }

    /** Sends {@code message}, adding this request's reqId. */
    public void reply(JsonObject message) {
        if (reqId != null) {
            message.add("reqId", reqId);
        }
        session.send(message);
    }

    /** Sends {@code {"type":"ack","ok":true}} if the agent supplied a reqId; otherwise nothing. */
    public void ack() {
        JsonObject ack = ackMessage();
        if (ack != null) {
            reply(ack);
        }
    }

    /**
     * An {@code ack} for this request to add result fields to, or null when the agent gave no reqId (and so wants no
     * ack). Return it from a {@link MessageRouter#runOnMainThread} task to send it.
     */
    public JsonObject ackMessage() {
        if (reqId == null) {
            return null;
        }
        JsonObject ack = Protocol.message("ack");
        ack.addProperty("ok", true);
        ack.addProperty("for", type);
        return ack;
    }

    public void error(String code, String message) {
        session.send(Protocol.error(code, message, reqId));
    }
}

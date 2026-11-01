package com.tuxprogrammer.davebridge.server.bridge;

import com.google.gson.JsonElement;

/** A request the agent got wrong. Turned into an {@code error} message, never logged as a server fault. */
public class ProtocolException extends Exception {

    private static final long serialVersionUID = 1L;

    private final String code;
    /** The offending message's reqId when it is known before a {@link Request} exists (e.g. a bad type). */
    private final transient JsonElement reqId;

    public ProtocolException(String code, String message) {
        this(code, message, null);
    }

    public ProtocolException(String code, String message, JsonElement reqId) {
        super(message);
        this.code = code;
        this.reqId = reqId;
    }

    public String code() {
        return code;
    }

    /** The reqId to echo in the error, or null. */
    public JsonElement reqId() {
        return reqId;
    }
}

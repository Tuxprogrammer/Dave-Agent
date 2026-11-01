package com.tuxprogrammer.davebridge.common.protocol;

import com.google.gson.JsonElement;

/**
 * C-&gt;S: a question for Dave with client-side context (what the player looks at, holds, has open). The server
 * validates it, rate-limits it and relays it to the agent as a chat event with {@code "source":"client"}. Context is
 * client-reported and untrusted.
 */
public class Ask extends DavePacket {

    public static final String KIND = "ask";

    public String text;
    /** Expected to be a JSON object; the server drops anything else. */
    public JsonElement context;

    @Override
    public String kind() {
        return KIND;
    }
}

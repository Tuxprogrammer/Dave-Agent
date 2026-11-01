package com.tuxprogrammer.davebridge.common.protocol;

import com.google.gson.JsonElement;

/**
 * S-&gt;C: run a script on this client (PROTOCOL.md 1.8, {@code client_eval}). The server sends it only to players
 * whose client reported {@code clientEvalAllowed} and the {@code eval} capability; the client re-checks its own
 * opt-in before running anything and answers with {@link ClientEvalResult}.
 */
public class ClientEvalRequest extends DavePacket {

    public static final String KIND = "client_eval_request";

    /** Server-chosen id; the result must echo it. */
    public String id;
    public String script;
    /** "groovy". */
    public String mode;
    /** Time limit in milliseconds (the client caps it). 0 or missing: the client's default. */
    public int timeoutMs;
    /** Bound as {@code params} in the script; a JSON object or null. */
    public JsonElement params;

    @Override
    public String kind() {
        return KIND;
    }
}

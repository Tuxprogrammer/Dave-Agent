package com.tuxprogrammer.davebridge.common.protocol;

import com.google.gson.JsonElement;

/**
 * C-&gt;S: the outcome of a {@link ClientEvalRequest}. Untrusted like every client packet: the server only relays a
 * result whose {@code id} it is waiting for from this very player, and caps its size (the packet channel already
 * limits a client packet to 256 KiB).
 */
public class ClientEvalResult extends DavePacket {

    public static final String KIND = "client_eval_result";

    public String id;
    public boolean ok;
    public JsonElement result;
    public String error;
    /** compile, blocked, timeout, exception, not_opted_in. */
    public String errorType;
    public String output;
    public double ms;
    public boolean truncated;

    @Override
    public String kind() {
        return KIND;
    }
}

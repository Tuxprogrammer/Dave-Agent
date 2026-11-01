package com.tuxprogrammer.davebridge.common.protocol;

/**
 * S-&gt;C, RESERVED for milestone 2: ask a client (that opted in with {@code clientEvalAllowed}) to run a script.
 * Registered so the wire format is fixed, but the server never sends it yet and clients reject it.
 */
public class ClientEvalRequest extends DavePacket {

    public static final String KIND = "client_eval_request";

    public String id;
    public String script;
    /** e.g. "groovy". */
    public String mode;

    @Override
    public String kind() {
        return KIND;
    }
}

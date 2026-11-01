package com.tuxprogrammer.davebridge.common.protocol;

import com.google.gson.JsonElement;

/** C-&gt;S, RESERVED for milestone 2: the outcome of a {@link ClientEvalRequest}. The server ignores it for now. */
public class ClientEvalResult extends DavePacket {

    public static final String KIND = "client_eval_result";

    public String id;
    public boolean ok;
    public JsonElement result;
    public String error;

    @Override
    public String kind() {
        return KIND;
    }
}

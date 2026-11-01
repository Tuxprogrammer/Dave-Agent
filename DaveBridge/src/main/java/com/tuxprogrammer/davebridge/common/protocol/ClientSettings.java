package com.tuxprogrammer.davebridge.common.protocol;

/**
 * C-&gt;S, sent when the player changes an opt-in mid-session ({@code /davebridge optin|optout} or the config screen),
 * so the server and the agent learn it without a reconnect. Only accepted after {@link ClientHello}.
 */
public class ClientSettings extends DavePacket {

    public static final String KIND = "client_settings";

    /** Same meaning as {@link ClientHello#clientEvalAllowed}. */
    public boolean clientEvalAllowed;

    @Override
    public String kind() {
        return KIND;
    }
}

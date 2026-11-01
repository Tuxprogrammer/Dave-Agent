package com.tuxprogrammer.davebridge.common.protocol;

/** S-&gt;C: a line (or several, newline-separated) from Dave for a client that has the mod. */
public class DaveMessage extends DavePacket {

    public static final String KIND = "dave_message";

    public String botName;
    public String text;
    /** Id of the chat event this answers, if the agent supplied one. */
    public String replyTo;

    @Override
    public String kind() {
        return KIND;
    }
}

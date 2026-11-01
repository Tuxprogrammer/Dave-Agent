package com.tuxprogrammer.davebridge.common.protocol;

/** S-&gt;C: Dave is working on an answer. Clients with the mod show a transient indicator. */
public class Thinking extends DavePacket {

    public static final String KIND = "thinking";

    public String botName;
    /** True when Dave's answer has arrived (as chat): remove the indicator instead of showing it. */
    public boolean clear;

    @Override
    public String kind() {
        return KIND;
    }
}

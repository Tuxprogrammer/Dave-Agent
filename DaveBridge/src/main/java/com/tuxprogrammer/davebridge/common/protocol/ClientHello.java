package com.tuxprogrammer.davebridge.common.protocol;

/** C-&gt;S, sent once per connection by a client with the mod, after the player has joined. */
public class ClientHello extends DavePacket {

    public static final String KIND = "client_hello";

    public String modVersion;
    public int protocol = DavePackets.PROTOCOL_VERSION;
    /** What the client half can do, e.g. "render", "ask", "context". "eval" is reserved for milestone 2. */
    public String[] capabilities = new String[0];
    /** The player has opted in (client config) to letting Dave run code on their machine. Unused until M2. */
    public boolean clientEvalAllowed;

    @Override
    public String kind() {
        return KIND;
    }
}

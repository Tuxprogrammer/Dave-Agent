package com.tuxprogrammer.davebridge.common.protocol;

/** S-&gt;C reply to {@link ClientHello}: tells the client half that this server runs DaveBridge. */
public class ServerHello extends DavePacket {

    public static final String KIND = "server_hello";

    public String modVersion;
    public int protocol = DavePackets.PROTOCOL_VERSION;
    public String botName;
    /** Chat prefixes the server treats as addressing Dave. */
    public String[] triggerPrefixes = new String[0];
    /** Longest {@code ask} text the server accepts; 0 from servers that predate the field. */
    public int maxAskLength;

    @Override
    public String kind() {
        return KIND;
    }
}

package com.tuxprogrammer.davebridge.common.protocol;

/**
 * A message on the {@code davebridge} packet channel. Packets are plain DTOs serialized to JSON (with the vanilla Gson)
 * and carried in chunked frames, so adding a field never breaks the wire format. See PROTOCOL.md.
 */
public abstract class DavePacket {

    /** Wire name of this packet type; must match an entry in {@link DavePackets}. */
    public abstract String kind();
}

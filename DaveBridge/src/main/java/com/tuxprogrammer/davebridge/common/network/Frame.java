package com.tuxprogrammer.davebridge.common.network;

import com.tuxprogrammer.davebridge.DaveBridge;

import cpw.mods.fml.common.network.ByteBufUtils;
import cpw.mods.fml.common.network.simpleimpl.IMessage;
import io.netty.buffer.ByteBuf;

/**
 * One chunk of a serialized {@code DavePacket}. Two subclasses exist only so each direction gets its own
 * discriminator on the shared SimpleNetworkWrapper.
 * <p>
 * Wire: {@code byte version, utf8 kind, varint streamId, varint index, varint total, varint length, bytes}. Decoding
 * never throws: a malformed frame is marked {@link #invalid} and dropped by the handler, so a bad client cannot make
 * the codec kick or crash anything.
 */
public abstract class Frame implements IMessage {

    static final int VERSION = 1;
    static final int MAX_KIND_LENGTH = 64;

    String kind;
    int streamId;
    int index;
    int total;
    byte[] data;
    boolean invalid;

    Frame() {}

    Frame(String kind, int streamId, int index, int total, byte[] data) {
        this.kind = kind;
        this.streamId = streamId;
        this.index = index;
        this.total = total;
        this.data = data;
    }

    @Override
    public void fromBytes(ByteBuf buf) {
        try {
            int version = buf.readByte();
            if (version != VERSION) {
                throw new IllegalArgumentException("unsupported frame version " + version);
            }
            kind = ByteBufUtils.readUTF8String(buf);
            if (kind.length() > MAX_KIND_LENGTH) {
                throw new IllegalArgumentException("kind too long");
            }
            streamId = ByteBufUtils.readVarInt(buf, 5);
            index = ByteBufUtils.readVarInt(buf, 5);
            total = ByteBufUtils.readVarInt(buf, 5);
            int length = ByteBufUtils.readVarInt(buf, 5);
            if (length < 0 || length > PayloadChunker.DEFAULT_CHUNK_BYTES || length > buf.readableBytes()) {
                throw new IllegalArgumentException("bad chunk length " + length);
            }
            data = new byte[length];
            buf.readBytes(data);
        } catch (Exception e) {
            invalid = true;
            buf.skipBytes(buf.readableBytes());
            DaveBridge.LOG.debug("Dropping malformed davebridge frame", e);
        }
    }

    @Override
    public void toBytes(ByteBuf buf) {
        buf.writeByte(VERSION);
        ByteBufUtils.writeUTF8String(buf, kind);
        ByteBufUtils.writeVarInt(buf, streamId, 5);
        ByteBufUtils.writeVarInt(buf, index, 5);
        ByteBufUtils.writeVarInt(buf, total, 5);
        ByteBufUtils.writeVarInt(buf, data.length, 5);
        buf.writeBytes(data);
    }

    /** Client to server. */
    public static final class ToServer extends Frame {

        public ToServer() {}

        ToServer(String kind, int streamId, int index, int total, byte[] data) {
            super(kind, streamId, index, total, data);
        }
    }

    /** Server to client. */
    public static final class ToClient extends Frame {

        public ToClient() {}

        ToClient(String kind, int streamId, int index, int total, byte[] data) {
            super(kind, streamId, index, total, data);
        }
    }
}

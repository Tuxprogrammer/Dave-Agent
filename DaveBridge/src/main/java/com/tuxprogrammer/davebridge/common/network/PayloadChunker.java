package com.tuxprogrammer.davebridge.common.network;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.LongSupplier;

/**
 * Splits payloads into numbered chunks and puts them back together.
 * <p>
 * 1.7.10 rejects client-to-server custom payloads of 32767 bytes or more, so anything that might grow (questions with
 * context now, script results later) is sent as a stream of chunks no larger than {@link #DEFAULT_CHUNK_BYTES}. The
 * receiving side treats the sender as untrusted: total size, chunk counts and open streams are bounded and stale
 * streams expire. No Minecraft types, so this is unit-tested on its own.
 */
public final class PayloadChunker {

    /** Leaves room under the 32767-byte limit for the channel discriminator and frame header. */
    public static final int DEFAULT_CHUNK_BYTES = 30000;

    private PayloadChunker() {}

    /** Splits {@code data} into chunks of at most {@code maxChunk} bytes. An empty payload yields one empty chunk. */
    public static List<byte[]> split(byte[] data, int maxChunk) {
        if (maxChunk <= 0) {
            throw new IllegalArgumentException("maxChunk must be positive");
        }
        if (data.length <= maxChunk) {
            return Collections.singletonList(data);
        }
        List<byte[]> chunks = new ArrayList<>((data.length + maxChunk - 1) / maxChunk);
        for (int off = 0; off < data.length; off += maxChunk) {
            chunks.add(Arrays.copyOfRange(data, off, Math.min(data.length, off + maxChunk)));
        }
        return chunks;
    }

    /** Reassembles chunk streams from one sender. Thread-safe. */
    public static final class Assembler {

        private final int maxTotalBytes;
        private final int maxChunks;
        private final int maxStreams;
        private final long timeoutNanos;
        private final LongSupplier nanoClock;
        private final Map<Integer, Stream> streams = new LinkedHashMap<>();

        /** Limits sized for senders that use {@link #DEFAULT_CHUNK_BYTES} chunks. */
        public Assembler(int maxTotalBytes, int maxStreams, long timeoutNanos) {
            this(maxTotalBytes, maxTotalBytes / DEFAULT_CHUNK_BYTES + 1, maxStreams, timeoutNanos, System::nanoTime);
        }

        /**
         * @param maxChunks bounds the chunk count a sender may announce, so a hostile {@code total} cannot allocate a
         *                  huge chunk table before any data arrives
         */
        public Assembler(int maxTotalBytes, int maxChunks, int maxStreams, long timeoutNanos, LongSupplier nanoClock) {
            this.maxTotalBytes = maxTotalBytes;
            this.maxChunks = maxChunks;
            this.maxStreams = maxStreams;
            this.timeoutNanos = timeoutNanos;
            this.nanoClock = nanoClock;
        }

        /**
         * Accepts one chunk.
         *
         * @return the complete payload when this was the last missing chunk, otherwise {@code null}
         * @throws IllegalArgumentException if the chunk is malformed or a limit is exceeded; the stream is dropped
         */
        public synchronized byte[] accept(int streamId, int index, int total, byte[] chunk) {
            long now = nanoClock.getAsLong();
            expire(now);
            if (total < 1 || total > maxChunks || index < 0 || index >= total) {
                streams.remove(streamId);
                throw new IllegalArgumentException("bad chunk index " + index + "/" + total);
            }
            if (total == 1) {
                if (chunk.length > maxTotalBytes) {
                    throw new IllegalArgumentException("payload too large: " + chunk.length);
                }
                return chunk;
            }
            Stream stream = streams.get(streamId);
            if (stream == null) {
                if (streams.size() >= maxStreams) {
                    throw new IllegalArgumentException("too many open chunk streams");
                }
                stream = new Stream(total, now);
                streams.put(streamId, stream);
            }
            if (stream.parts.length != total) {
                streams.remove(streamId);
                throw new IllegalArgumentException("chunk count changed mid-stream");
            }
            if (stream.parts[index] == null) {
                stream.bytes += chunk.length;
                stream.received++;
            } else {
                stream.bytes += chunk.length - stream.parts[index].length;
            }
            stream.parts[index] = chunk;
            if (stream.bytes > maxTotalBytes) {
                streams.remove(streamId);
                throw new IllegalArgumentException("payload too large: over " + maxTotalBytes + " bytes");
            }
            if (stream.received < total) {
                return null;
            }
            streams.remove(streamId);
            byte[] out = new byte[stream.bytes];
            int off = 0;
            for (byte[] part : stream.parts) {
                System.arraycopy(part, 0, out, off, part.length);
                off += part.length;
            }
            return out;
        }

        public synchronized int openStreams() {
            return streams.size();
        }

        public synchronized void clear() {
            streams.clear();
        }

        private void expire(long now) {
            Iterator<Stream> it = streams.values()
                .iterator();
            while (it.hasNext()) {
                if (now - it.next().startedAt > timeoutNanos) {
                    it.remove();
                }
            }
        }

        private static final class Stream {

            final byte[][] parts;
            final long startedAt;
            int received;
            int bytes;

            Stream(int total, long startedAt) {
                this.parts = new byte[total][];
                this.startedAt = startedAt;
            }
        }
    }
}

package com.tuxprogrammer.davebridge.common.network;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.List;
import java.util.Random;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.Test;

class PayloadChunkerTest {

    private static byte[] random(int n) {
        byte[] b = new byte[n];
        new Random(42).nextBytes(b);
        return b;
    }

    @Test
    void smallPayloadIsOneChunk() {
        byte[] data = random(100);
        List<byte[]> chunks = PayloadChunker.split(data, 1000);
        assertEquals(1, chunks.size());
        assertArrayEquals(data, chunks.get(0));
    }

    @Test
    void splitsAndReassemblesInAnyOrder() {
        byte[] data = random(100_000);
        List<byte[]> chunks = PayloadChunker.split(data, PayloadChunker.DEFAULT_CHUNK_BYTES);
        assertEquals(4, chunks.size());
        PayloadChunker.Assembler a = new PayloadChunker.Assembler(1 << 20, 4, Long.MAX_VALUE);
        assertNull(a.accept(7, 3, 4, chunks.get(3)));
        assertNull(a.accept(7, 0, 4, chunks.get(0)));
        assertNull(a.accept(7, 2, 4, chunks.get(2)));
        assertArrayEquals(data, a.accept(7, 1, 4, chunks.get(1)));
        assertEquals(0, a.openStreams());
    }

    @Test
    void interleavedStreamsDoNotMix() {
        byte[] x = random(50);
        byte[] y = new byte[50];
        List<byte[]> xs = PayloadChunker.split(x, 20);
        List<byte[]> ys = PayloadChunker.split(y, 20);
        PayloadChunker.Assembler a = new PayloadChunker.Assembler(1000, 10, 4, Long.MAX_VALUE, System::nanoTime);
        a.accept(1, 0, 3, xs.get(0));
        a.accept(2, 0, 3, ys.get(0));
        a.accept(1, 1, 3, xs.get(1));
        a.accept(2, 1, 3, ys.get(1));
        assertArrayEquals(y, a.accept(2, 2, 3, ys.get(2)));
        assertArrayEquals(x, a.accept(1, 2, 3, xs.get(2)));
    }

    @Test
    void enforcesLimits() {
        PayloadChunker.Assembler a = new PayloadChunker.Assembler(100, 10, 1, Long.MAX_VALUE, System::nanoTime);
        assertThrows(IllegalArgumentException.class, () -> a.accept(1, 0, 1, new byte[101]));
        assertThrows(IllegalArgumentException.class, () -> a.accept(1, 5, 2, new byte[1]));
        a.accept(1, 0, 3, new byte[60]);
        assertThrows(IllegalArgumentException.class, () -> a.accept(2, 0, 2, new byte[1])); // too many streams
        assertThrows(IllegalArgumentException.class, () -> a.accept(1, 1, 3, new byte[60])); // too large
        assertEquals(0, a.openStreams());
    }

    @Test
    void rejectsAbsurdChunkCounts() {
        PayloadChunker.Assembler a = new PayloadChunker.Assembler(64 * 1024, 4, Long.MAX_VALUE);
        // 64 KiB allows 3 chunks of DEFAULT_CHUNK_BYTES; a hostile sender claiming millions must not allocate them
        assertThrows(IllegalArgumentException.class, () -> a.accept(1, 0, Integer.MAX_VALUE, new byte[1]));
        assertNull(a.accept(2, 0, 3, new byte[1]));
    }

    @Test
    void staleStreamsExpire() {
        AtomicLong clock = new AtomicLong();
        PayloadChunker.Assembler a = new PayloadChunker.Assembler(1000, 10, 1, 10, clock::get);
        a.accept(1, 0, 2, new byte[5]);
        clock.set(11);
        // stream 1 expired, so a new stream fits within maxStreams = 1
        assertNull(a.accept(2, 0, 2, new byte[5]));
        assertEquals(1, a.openStreams());
    }
}

package com.tuxprogrammer.davebridge.common.network;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Collections;
import java.util.List;
import java.util.Random;

import org.junit.jupiter.api.Test;

import com.tuxprogrammer.davebridge.common.lesson.LessonLimits;
import com.tuxprogrammer.davebridge.common.protocol.DavePackets;
import com.tuxprogrammer.davebridge.common.protocol.Lesson;
import com.tuxprogrammer.davebridge.common.protocol.LessonStatus;
import com.tuxprogrammer.davebridge.common.protocol.LessonStop;

/** Lesson packets survive the real encode, chunk, reassemble and decode path, and only travel their direction. */
class LessonPacketRoundTripTest {

    private static Lesson bigLesson() {
        Lesson l = new Lesson();
        l.id = "ebf-muffler";
        l.title = "EBF muffler hatch";
        l.loop = true;
        l.speed = 0.6;
        l.dim = -1;
        l.anchor = new double[] { 100.5, 64, -20.5 };
        l.start = new double[] { 102.5, 64, -20.5 };
        Lesson.Step[] steps = new Lesson.Step[LessonLimits.MAX_STEPS];
        String text = new String(new char[LessonLimits.MAX_SAY_CHARS]).replace('\0', 'é'); // 2 bytes each in UTF-8
        for (int i = 0; i < steps.length; i++) {
            Lesson.Step s = new Lesson.Step();
            s.op = i % 2 == 0 ? Lesson.GHOST : Lesson.SAY;
            s.pos = new double[] { 100 + i % 5, 64, -20 };
            s.id = "gregtech:gt.blockmachines";
            s.meta = 1000 + i;
            s.facing = "north";
            s.color = 0xFFAA00;
            s.text = text;
            s.ticks = 25;
            steps[i] = s;
        }
        l.steps = steps;
        return l;
    }

    @Test
    void lessonRoundTripsThroughChunks() {
        Lesson sent = bigLesson();
        byte[] data = DaveNetwork.encode(sent);
        // Use small chunks so the multi-chunk path runs, delivered out of order.
        List<byte[]> chunks = PayloadChunker.split(data, 4000);
        assertTrue(chunks.size() > 3, "expected several chunks, got " + chunks.size());
        PayloadChunker.Assembler assembler = new PayloadChunker.Assembler(
            DaveNetwork.MAX_TO_CLIENT_BYTES,
            8,
            Long.MAX_VALUE);
        Integer[] order = new Integer[chunks.size()];
        for (int i = 0; i < order.length; i++) order[i] = i;
        java.util.List<Integer> shuffled = java.util.Arrays.asList(order);
        Collections.shuffle(shuffled, new Random(7));
        byte[] whole = null;
        for (int i : shuffled) {
            byte[] r = assembler.accept(1, i, chunks.size(), chunks.get(i));
            if (r != null) whole = r;
        }
        Lesson got = (Lesson) DaveNetwork.decode(Lesson.KIND, whole, DavePackets.Direction.TO_CLIENT);
        assertEquals(sent.id, got.id);
        assertEquals(sent.title, got.title);
        assertEquals(sent.loop, got.loop);
        assertEquals(sent.speed, got.speed, 0);
        assertEquals(sent.dim, got.dim);
        assertArrayEquals(sent.anchor, got.anchor);
        assertArrayEquals(sent.start, got.start);
        assertEquals(sent.steps.length, got.steps.length);
        for (int i = 0; i < sent.steps.length; i++) {
            Lesson.Step a = sent.steps[i], b = got.steps[i];
            assertEquals(a.op, b.op);
            assertArrayEquals(a.pos, b.pos);
            assertEquals(a.id, b.id);
            assertEquals(a.meta, b.meta);
            assertEquals(a.facing, b.facing);
            assertEquals(a.color, b.color);
            assertEquals(a.text, b.text);
            assertEquals(a.ticks, b.ticks);
        }
    }

    @Test
    void largestLessonFitsTheClientLimit() {
        assertTrue(DaveNetwork.encode(bigLesson()).length < DaveNetwork.MAX_TO_CLIENT_BYTES);
    }

    @Test
    void stopAndStatusRoundTrip() {
        LessonStop stop = new LessonStop();
        stop.id = "x";
        LessonStop gotStop = (LessonStop) DaveNetwork
            .decode(LessonStop.KIND, DaveNetwork.encode(stop), DavePackets.Direction.TO_CLIENT);
        assertEquals("x", gotStop.id);
        LessonStop any = (LessonStop) DaveNetwork
            .decode(LessonStop.KIND, DaveNetwork.encode(new LessonStop()), DavePackets.Direction.TO_CLIENT);
        assertNull(any.id);

        LessonStatus status = new LessonStatus();
        status.id = "x";
        status.state = LessonStatus.STATE_STOPPED;
        status.reason = LessonStatus.REASON_PLAYER;
        LessonStatus gotStatus = (LessonStatus) DaveNetwork
            .decode(LessonStatus.KIND, DaveNetwork.encode(status), DavePackets.Direction.TO_SERVER);
        assertEquals("stopped", gotStatus.state);
        assertEquals("player", gotStatus.reason);
    }

    @Test
    void lessonsOnlyTravelTheirDirection() {
        byte[] lesson = DaveNetwork.encode(bigLesson());
        assertThrows(
            IllegalArgumentException.class,
            () -> DaveNetwork.decode(Lesson.KIND, lesson, DavePackets.Direction.TO_SERVER),
            "a client must not be able to send a lesson");
        assertThrows(
            IllegalArgumentException.class,
            () -> DaveNetwork.decode(LessonStatus.KIND, lesson, DavePackets.Direction.TO_CLIENT));
        assertSame(Lesson.class, DavePackets.type(Lesson.KIND));
        assertSame(DavePackets.Direction.TO_CLIENT, DavePackets.direction(LessonStop.KIND));
        assertSame(DavePackets.Direction.TO_SERVER, DavePackets.direction(LessonStatus.KIND));
    }

    @Test
    void unknownFieldsAndMissingFieldsDecode() {
        byte[] json = "{\"id\":\"a\",\"future\":true,\"steps\":[{\"op\":\"dance\",\"ticks\":5}]}"
            .getBytes(java.nio.charset.StandardCharsets.UTF_8);
        Lesson got = (Lesson) DaveNetwork.decode(Lesson.KIND, json, DavePackets.Direction.TO_CLIENT);
        assertEquals("a", got.id);
        assertNull(got.anchor); // LessonPlayback rejects it; decoding itself must not fail
        assertEquals("dance", got.steps[0].op);
    }
}

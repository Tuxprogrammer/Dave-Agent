package com.tuxprogrammer.davebridge.client.lesson;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

import com.tuxprogrammer.davebridge.common.lesson.LessonLimits;
import com.tuxprogrammer.davebridge.common.protocol.Lesson;

class LessonPlaybackTest {

    private static Lesson.Step step(String op, int ticks) {
        Lesson.Step s = new Lesson.Step();
        s.op = op;
        s.ticks = ticks;
        return s;
    }

    private static Lesson.Step at(String op, int ticks, double x, double y, double z) {
        Lesson.Step s = step(op, ticks);
        s.pos = new double[] { x, y, z };
        return s;
    }

    private static Lesson lesson(boolean loop, Lesson.Step... steps) {
        Lesson l = new Lesson();
        l.id = "t";
        l.title = "Test";
        l.loop = loop;
        l.anchor = new double[] { 0, 64, 0 };
        l.start = new double[] { 0, 64, 2 };
        l.steps = steps;
        return l;
    }

    private static void ticks(LessonPlayback p, int n) {
        for (int i = 0; i < n; i++) p.tick();
    }

    @Test
    void walksAlongWaypointsLinearly() {
        LessonPlayback p = new LessonPlayback(
            lesson(false, at(Lesson.WALK_TO, 10, 10, 64, 2), at(Lesson.WALK_TO, 10, 10, 64, 12)));
        assertEquals(0, p.x, 1e-9);
        ticks(p, 5);
        assertEquals(5, p.x, 1e-9);
        assertEquals(2, p.z, 1e-9);
        assertTrue(p.walking());
        ticks(p, 5);
        assertEquals(10, p.x, 1e-9);
        ticks(p, 5);
        assertEquals(10, p.x, 1e-9);
        assertEquals(7, p.z, 1e-9);
        assertEquals(2, p.stepNumber());
    }

    @Test
    void facesWhereHeWalksThenTurnsToTheTarget() {
        LessonPlayback p = new LessonPlayback(
            lesson(false, at(Lesson.WALK_TO, 4, 0, 64, 10), at(Lesson.LOOK_AT, 20, 10, 65.62, 10)));
        ticks(p, 4);
        assertEquals(0f, LessonPlayback.wrap(p.bodyYaw), 1e-3); // walking +z is yaw 0
        assertFalse(p.pointing);
        ticks(p, 10);
        assertTrue(p.pointing);
        assertEquals(-90f, LessonPlayback.wrap(p.headYaw), 1e-3); // +x is yaw -90
        assertEquals(0f, p.pitch, 1e-3); // target at eye height
    }

    @Test
    void highlightsAndGhostsAccumulateAndClearOnLoop() {
        Lesson.Step ghost = at(Lesson.GHOST, 5, 1, 64, 1);
        ghost.id = "minecraft:chest";
        LessonPlayback p = new LessonPlayback(
            lesson(true, at(Lesson.HIGHLIGHT, 5, 2, 64, 2), ghost, step(Lesson.WAIT, 5)));
        ticks(p, 1);
        assertEquals(1, p.highlights.size());
        assertTrue(p.pointing);
        ticks(p, 5);
        assertEquals(1, p.ghosts.size());
        ticks(p, 9); // end of pass
        assertTrue(p.betweenPasses());
        assertEquals(1, p.ghosts.size());
        ticks(p, LessonLimits.LOOP_GAP_TICKS);
        assertTrue(p.ghosts.isEmpty());
        assertTrue(p.highlights.isEmpty());
        assertEquals(1, p.stepNumber());
        assertEquals(LessonPlayback.End.NONE, p.end());
    }

    @Test
    void nonLoopingLessonFinishesAfterHoldingTheLastFrame() {
        LessonPlayback p = new LessonPlayback(lesson(false, step(Lesson.WAIT, 3)));
        ticks(p, 3);
        assertEquals(LessonPlayback.End.NONE, p.end());
        ticks(p, LessonLimits.END_HOLD_TICKS + 1);
        assertEquals(LessonPlayback.End.FINISHED, p.end());
    }

    @Test
    void loopingLessonTimesOut() {
        LessonPlayback p = new LessonPlayback(lesson(true, step(Lesson.WAIT, 20)));
        ticks(p, LessonLimits.MAX_PLAY_TICKS);
        assertEquals(LessonPlayback.End.NONE, p.end());
        p.tick();
        assertEquals(LessonPlayback.End.TIMEOUT, p.end());
    }

    @Test
    void pauseFreezesEverything() {
        LessonPlayback p = new LessonPlayback(lesson(false, at(Lesson.WALK_TO, 10, 10, 64, 2)));
        ticks(p, 3);
        double x = p.x;
        p.setPaused(true);
        ticks(p, 50);
        assertEquals(x, p.x, 1e-9);
        assertEquals(x, p.prevX, 1e-9); // no interpolation jitter while paused
        p.setPaused(false);
        p.tick();
        assertTrue(p.x > x);
    }

    @Test
    void holdSayAndSwingUpdateState() {
        Lesson.Step hold = step(Lesson.HOLD, 2);
        hold.id = "minecraft:stick";
        hold.meta = 3;
        Lesson.Step say = step(Lesson.SAY, 2);
        say.text = "Hello";
        LessonPlayback p = new LessonPlayback(lesson(false, hold, step(Lesson.SWING, 2), say));
        assertNull(p.held);
        ticks(p, 1);
        assertEquals("minecraft:stick", p.held);
        assertEquals(3, p.heldMeta);
        ticks(p, 2);
        assertEquals(1, p.swings);
        ticks(p, 2);
        assertEquals("Hello", p.sayText);
    }

    @Test
    void sanitizeDropsMalformedAndFarSteps() {
        Lesson.Step unknown = step("teleport", 5);
        Lesson.Step noPos = step(Lesson.WALK_TO, 5);
        Lesson.Step far = at(Lesson.HIGHLIGHT, 5, 500, 64, 0);
        Lesson.Step nan = at(Lesson.LOOK_AT, 5, Double.NaN, 64, 0);
        Lesson.Step ghostNoBlock = at(Lesson.GHOST, 5, 1, 64, 1);
        Lesson.Step emptySay = step(Lesson.SAY, 5);
        Lesson.Step huge = step(Lesson.WAIT, Integer.MAX_VALUE);
        Lesson.Step negative = step(Lesson.WAIT, -5);
        Lesson.Step[] kept = LessonPlayback.sanitize(
            new Lesson.Step[] { null, unknown, noPos, far, nan, ghostNoBlock, emptySay, negative, huge },
            new double[] { 0, 64, 0 });
        // The negative wait is kept as 1 tick; the huge one is clamped to a full pass, which no longer fits.
        assertEquals(1, kept.length);
        assertEquals(1, kept[0].ticks);
        Lesson.Step alone = step(Lesson.WAIT, Integer.MAX_VALUE);
        kept = LessonPlayback.sanitize(new Lesson.Step[] { alone }, new double[] { 0, 64, 0 });
        assertEquals(LessonLimits.MAX_PASS_TICKS, kept[0].ticks);
    }

    @Test
    void sanitizeCapsStepCount() {
        Lesson.Step[] many = new Lesson.Step[LessonLimits.MAX_STEPS * 2];
        for (int i = 0; i < many.length; i++) many[i] = step(Lesson.SWING, 1);
        assertEquals(LessonLimits.MAX_STEPS, LessonPlayback.sanitize(many, new double[] { 0, 0, 0 }).length);
    }

    @Test
    void rejectsUnplayableLessons() {
        assertThrows(IllegalArgumentException.class, () -> new LessonPlayback(lesson(true)));
        assertThrows(IllegalArgumentException.class, () -> new LessonPlayback(null));
        Lesson noAnchor = lesson(true, step(Lesson.WAIT, 1));
        noAnchor.anchor = null;
        assertThrows(IllegalArgumentException.class, () -> new LessonPlayback(noAnchor));
    }

    @Test
    void farStartFallsBackToTheAnchor() {
        Lesson l = lesson(true, step(Lesson.WAIT, 1));
        l.start = new double[] { 9999, 64, 0 };
        LessonPlayback p = new LessonPlayback(l);
        assertEquals(0, p.x, 1e-9);
        assertNotNull(p.anchor);
    }

    @Test
    void angleHelpers() {
        assertEquals(0f, LessonPlayback.yawOf(0, 1), 1e-4);
        assertEquals(-90f, LessonPlayback.yawOf(1, 0), 1e-4);
        assertEquals(-45f, LessonPlayback.pitchOf(1, 1, 0), 1e-4); // up is negative pitch
        assertEquals(190f, LessonPlayback.approach(170f, -170f, 30f), 1e-4); // the short way round
        assertEquals(-10f, LessonPlayback.wrap(350f), 1e-4);
    }
}

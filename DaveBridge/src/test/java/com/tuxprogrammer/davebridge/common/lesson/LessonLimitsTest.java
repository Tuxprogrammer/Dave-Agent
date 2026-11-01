package com.tuxprogrammer.davebridge.common.lesson;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class LessonLimitsTest {

    @Test
    void speedClamps() {
        assertEquals(LessonLimits.DEFAULT_SPEED, LessonLimits.clampSpeed(Double.NaN), 0);
        assertEquals(LessonLimits.DEFAULT_SPEED, LessonLimits.clampSpeed(0), 0);
        assertEquals(LessonLimits.DEFAULT_SPEED, LessonLimits.clampSpeed(Double.POSITIVE_INFINITY), 0);
        assertEquals(LessonLimits.MIN_SPEED, LessonLimits.clampSpeed(0.001), 0);
        assertEquals(LessonLimits.MAX_SPEED, LessonLimits.clampSpeed(50), 0);
        assertEquals(1.0, LessonLimits.clampSpeed(1.0), 0);
    }

    @Test
    void walkTicksMatchVanillaWalkingSpeed() {
        // 4.317 blocks at full speed is one second.
        assertEquals(20, LessonLimits.walkTicks(4.317, 1.0));
        assertEquals(40, LessonLimits.walkTicks(4.317, 0.5));
        assertEquals(1, LessonLimits.walkTicks(0, 1.0));
        assertEquals(LessonLimits.MAX_PASS_TICKS, LessonLimits.walkTicks(1e9, 0.1));
    }

    @Test
    void sayAndWaitTicksAreBounded() {
        assertEquals(40, LessonLimits.sayTicks(null));
        assertEquals(40, LessonLimits.sayTicks("hi"));
        assertEquals(200, LessonLimits.sayTicks(new String(new char[500])));
        assertTrue(LessonLimits.sayTicks("Right-click with a screwdriver") > 40);
        assertEquals(1, LessonLimits.waitTicks(-5));
        assertEquals(LessonLimits.MAX_WAIT_TICKS, LessonLimits.waitTicks(Long.MAX_VALUE));
    }

    @Test
    void stopDistanceLeavesRoomToFollowDave() {
        assertTrue(LessonLimits.STOP_DISTANCE > LessonLimits.MAX_RADIUS + 8);
    }

    @Test
    void radiusDependsOnTheClientVersion() {
        assertEquals(LessonLimits.MAX_RADIUS, LessonLimits.radiusFor("0.2.4"));
        assertEquals(LessonLimits.MAX_RADIUS, LessonLimits.radiusFor("0.2.10"));
        assertEquals(LessonLimits.MAX_RADIUS, LessonLimits.radiusFor("0.3.0-dev"));
        assertEquals(LessonLimits.LEGACY_RADIUS, LessonLimits.radiusFor("0.2.3"));
        assertEquals(LessonLimits.LEGACY_RADIUS, LessonLimits.radiusFor("0.1.9"));
        assertEquals(LessonLimits.LEGACY_RADIUS, LessonLimits.radiusFor(null));
        assertEquals(256.0, LessonLimits.MAX_RADIUS);
    }
}

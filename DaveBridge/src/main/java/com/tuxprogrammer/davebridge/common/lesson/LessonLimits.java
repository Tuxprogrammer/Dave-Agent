package com.tuxprogrammer.davebridge.common.lesson;

/**
 * Caps and timings for guided demonstrations, shared by the server (which validates and times each step) and the
 * client (which bounds what it plays). Pure Java, no Minecraft types, unit-tested.
 */
public final class LessonLimits {

    /** Most steps one lesson may keep; later steps are dropped with a warning. */
    public static final int MAX_STEPS = 64;
    /** Longest single pass of a lesson, in ticks (3 minutes). Steps past it are dropped with a warning. */
    public static final int MAX_PASS_TICKS = 3 * 60 * 20;
    /** Every position must lie within this many blocks of where the player stood when the lesson was made. */
    public static final double MAX_RADIUS = 32.0;
    /** The client stops the lesson when the player is this far from that point. */
    public static final double STOP_DISTANCE = 48.0;
    /** Pause between passes of a looping lesson. */
    public static final int LOOP_GAP_TICKS = 40;
    /** How long the last frame of a non-looping lesson stays up before it clears itself. */
    public static final int END_HOLD_TICKS = 100;
    /** Longest a lesson plays in total, loops included (10 minutes); then it stops by itself. */
    public static final int MAX_PLAY_TICKS = 10 * 60 * 20;

    public static final double MIN_SPEED = 0.1;
    public static final double MAX_SPEED = 2.0;
    public static final double DEFAULT_SPEED = 0.6;
    /** Vanilla walking speed, about 4.317 blocks per second. */
    public static final double WALK_BLOCKS_PER_TICK = 4.317 / 20.0;

    public static final int MAX_ID_CHARS = 64;
    public static final int MAX_TITLE_CHARS = 64;
    public static final int MAX_LABEL_CHARS = 80;
    public static final int MAX_SAY_CHARS = 200;
    public static final int MAX_WAIT_TICKS = 400;

    public static final int LOOK_TICKS = 15;
    public static final int HOLD_TICKS = 10;
    public static final int HIGHLIGHT_TICKS = 25;
    public static final int GHOST_TICKS = 25;
    public static final int SWING_TICKS = 10;

    private LessonLimits() {}

    /** Clamps a requested speed into range; NaN, infinities and non-positive values give the default. */
    public static double clampSpeed(double speed) {
        if (Double.isNaN(speed) || Double.isInfinite(speed) || speed <= 0) {
            return DEFAULT_SPEED;
        }
        return Math.max(MIN_SPEED, Math.min(MAX_SPEED, speed));
    }

    /** Ticks to walk {@code distance} blocks at {@code speed} (at least 1). */
    public static int walkTicks(double distance, double speed) {
        double perTick = WALK_BLOCKS_PER_TICK * clampSpeed(speed);
        double ticks = Math.ceil(Math.max(0, distance) / perTick);
        return (int) Math.max(1, Math.min(MAX_PASS_TICKS, ticks));
    }

    /** Ticks a line of Dave's stays up as the current step: enough time to read it. */
    public static int sayTicks(String text) {
        int len = text == null ? 0 : text.length();
        return Math.max(40, Math.min(200, 30 + 2 * len));
    }

    /** Clamps a wait to 1..{@link #MAX_WAIT_TICKS}. */
    public static int waitTicks(long ticks) {
        return (int) Math.max(1, Math.min(MAX_WAIT_TICKS, ticks));
    }
}

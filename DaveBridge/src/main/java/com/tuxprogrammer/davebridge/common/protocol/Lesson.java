package com.tuxprogrammer.davebridge.common.protocol;

/**
 * S-&gt;C: a guided demonstration ("lesson") for one player's client half to play. Lessons are data, never code: the
 * client draws a ghost Dave, ghost blocks, highlights and labels, and changes nothing in the world. The server builds
 * this packet only from a validated agent request ({@code server.lesson.LessonParser}), so every step is in its
 * normalized form here; the client still bounds everything again ({@code client.lesson.LessonPlayback}), because
 * client-bound packets are decoded defensively too. See PROTOCOL.md section 2.6.
 */
public class Lesson extends DavePacket {

    public static final String KIND = "lesson";

    public static final String WALK_TO = "walkTo";
    public static final String LOOK_AT = "lookAt";
    public static final String HOLD = "hold";
    public static final String HIGHLIGHT = "highlight";
    public static final String GHOST = "ghost";
    public static final String SWING = "swing";
    public static final String SAY = "say";
    public static final String WAIT = "wait";

    /** The agent's id for this lesson (or one the server made up); echoed in {@code lesson_status}. */
    public String id;
    /** Short title for the chat line and HUD; may be empty. */
    public String title;
    /** Replay from the start after a short pause until the player stops it. */
    public boolean loop;
    /** Walking speed as a multiple of vanilla walking speed (already folded into each step's {@code ticks}). */
    public double speed;
    /** Dimension the lesson belongs to; the client stops it if the player changes dimension. */
    public int dim;
    /** Where the player stood when the lesson was made: the center of the allowed area and of auto-stop. */
    public double[] anchor;
    /** Where the ghost Dave appears at the start of every pass. */
    public double[] start;
    public Step[] steps;

    @Override
    public String kind() {
        return KIND;
    }

    /** One normalized step. Which fields are set depends on {@link #op}. */
    public static class Step {

        /** One of the op constants of {@link Lesson}. */
        public String op;
        /** walkTo / lookAt: a point (feet position for walkTo). highlight / ghost: the block's integer position. */
        public double[] pos;
        /** hold: item registry name, or empty for empty hands. ghost: block registry name. */
        public String id;
        /** hold / ghost: item damage or block meta (GT machines use their meta tile entity id here). */
        public int meta;
        /** ghost: north, south, east, west, up or down; null to keep the block's inventory orientation. */
        public String facing;
        /** highlight: 0xRRGGBB. */
        public int color;
        /** highlight: text floating above the block. say: Dave's line. */
        public String text;
        /** How long the step lasts in client ticks, computed by the server (walkTo: from distance and speed). */
        public int ticks;
    }
}

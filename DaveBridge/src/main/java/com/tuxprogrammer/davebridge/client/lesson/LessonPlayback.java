package com.tuxprogrammer.davebridge.client.lesson;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import com.tuxprogrammer.davebridge.common.lesson.LessonLimits;
import com.tuxprogrammer.davebridge.common.protocol.Lesson;

/**
 * Plays a lesson tick by tick: where the ghost Dave stands, where he looks and points, what he holds, which ghost
 * blocks, highlights and labels are up. One {@link #tick()} per client tick; renderers read the public state and
 * interpolate with the previous values.
 * <p>
 * Pure Java with no Minecraft types, so the timeline is unit-tested. The packet comes from the server, but
 * client-bound packets are still decoded defensively ({@link #sanitize}): anything malformed is dropped, and counts,
 * durations and distances are capped again.
 */
public final class LessonPlayback {

    /** Why playback ended. */
    public enum End {
        /** Still playing (or paused). */
        NONE,
        /** A non-looping lesson played to the end. */
        FINISHED,
        /** Played for {@link LessonLimits#MAX_PLAY_TICKS}. */
        TIMEOUT
    }

    /** A ghost block on display. */
    public static final class Ghost {

        public final int x, y, z;
        public final String block;
        public final int meta;
        public final String facing;
        /** Ticks since it appeared, for a fade-in. */
        public int age;

        Ghost(Lesson.Step s) {
            x = (int) s.pos[0];
            y = (int) s.pos[1];
            z = (int) s.pos[2];
            block = s.id;
            meta = s.meta;
            facing = s.facing;
        }
    }

    /** A highlighted block on display. */
    public static final class Highlight {

        public final int x, y, z;
        public final int color;
        public final String label;
        public int age;

        Highlight(Lesson.Step s) {
            x = (int) s.pos[0];
            y = (int) s.pos[1];
            z = (int) s.pos[2];
            color = s.color & 0xFFFFFF;
            label = s.text == null ? "" : s.text;
        }
    }

    /** Dave's eye height above his feet, for look angles. */
    static final double EYE_HEIGHT = 1.62;
    static final float MAX_BODY_TURN = 20f;
    static final float MAX_HEAD_TURN = 30f;

    public final String id;
    public final String title;
    public final boolean loop;
    public final int dim;
    public final double[] anchor;
    private final double[] start;
    private final Lesson.Step[] steps;

    // ---- ghost state (read by the renderer) ----
    public double x, y, z;
    public double prevX, prevY, prevZ;
    public float bodyYaw, prevBodyYaw;
    public float headYaw, prevHeadYaw;
    public float pitch, prevPitch;
    /** Arm raised toward {@link #lookTarget}. */
    public boolean pointing;
    /** Point being looked at (block centers for highlights and ghosts), or null. */
    public double[] lookTarget;
    /** Item to hold: null when the lesson never said (idle item allowed), "" for empty hands. */
    public String held;
    public int heldMeta;
    /** Increments on every swing step; the renderer starts a swing when it changes. */
    public int swings;
    /** Dave's current line, or null. */
    public String sayText;
    public final List<Ghost> ghosts = new ArrayList<>();
    public final List<Highlight> highlights = new ArrayList<>();

    // ---- timeline ----
    private int stepIndex;
    private int stepTick;
    private double[] segmentFrom;
    private int gapLeft;
    private int endHoldLeft = -1;
    private int played;
    private boolean paused;
    private End end = End.NONE;

    /**
     * @throws IllegalArgumentException if nothing in the packet is playable
     */
    public LessonPlayback(Lesson lesson) {
        if (lesson == null || !isPoint(lesson.anchor)) {
            throw new IllegalArgumentException("lesson without an anchor");
        }
        this.anchor = lesson.anchor.clone();
        this.steps = sanitize(lesson.steps, anchor);
        if (steps.length == 0) {
            throw new IllegalArgumentException("lesson has no playable steps");
        }
        this.id = lesson.id == null ? "" : clip(lesson.id, LessonLimits.MAX_ID_CHARS);
        this.title = lesson.title == null ? "" : clip(lesson.title, LessonLimits.MAX_TITLE_CHARS);
        this.loop = lesson.loop;
        this.dim = lesson.dim;
        this.start = isPoint(lesson.start) && near(lesson.start, anchor) ? lesson.start.clone() : anchor.clone();
        restart();
        prevX = x;
        prevY = y;
        prevZ = z;
    }

    /**
     * Keeps the well-formed steps: known op, finite positions within reach of the anchor, bounded text and ticks,
     * at most {@link LessonLimits#MAX_PLAYED_STEPS} and one pass of at most {@link LessonLimits#MAX_PASS_TICKS}.
     */
    static Lesson.Step[] sanitize(Lesson.Step[] in, double[] anchor) {
        if (in == null) {
            return new Lesson.Step[0];
        }
        List<Lesson.Step> out = new ArrayList<>();
        int total = 0;
        for (Lesson.Step s : in) {
            if (out.size() >= LessonLimits.MAX_PLAYED_STEPS) break;
            if (s == null || s.op == null) continue;
            switch (s.op) {
                case Lesson.WALK_TO:
                case Lesson.LOOK_AT:
                case Lesson.HIGHLIGHT:
                    if (!isPoint(s.pos) || !near(s.pos, anchor)) continue;
                    break;
                case Lesson.GHOST:
                    if (!isPoint(s.pos) || !near(s.pos, anchor) || s.id == null || s.id.isEmpty()) continue;
                    break;
                case Lesson.HOLD:
                    if (s.id == null) s.id = "";
                    break;
                case Lesson.SAY:
                    if (s.text == null || s.text.isEmpty()) continue;
                    break;
                case Lesson.SWING:
                case Lesson.WAIT:
                    break;
                default:
                    continue; // unknown op from a newer server
            }
            if (s.text != null) {
                s.text = clip(
                    s.text,
                    Lesson.SAY.equals(s.op) ? LessonLimits.MAX_SAY_CHARS : LessonLimits.MAX_LABEL_CHARS);
            }
            if (s.id != null) s.id = clip(s.id, 128);
            if (s.facing != null) s.facing = clip(s.facing, 8);
            s.meta = Math.max(0, Math.min(Short.MAX_VALUE, s.meta));
            s.ticks = Math.max(1, Math.min(LessonLimits.MAX_PASS_TICKS, s.ticks));
            if (total + s.ticks > LessonLimits.MAX_PASS_TICKS) break;
            total += s.ticks;
            out.add(s);
        }
        return out.toArray(new Lesson.Step[0]);
    }

    /** Back to the first step: Dave at the start, nothing shown. */
    private void restart() {
        x = start[0];
        y = start[1];
        z = start[2];
        prevX = x; // appear at the start, don't slide there
        prevY = y;
        prevZ = z;
        stepIndex = 0;
        stepTick = 0;
        segmentFrom = start;
        ghosts.clear();
        highlights.clear();
        lookTarget = null;
        pointing = false;
        held = null;
        heldMeta = 0;
        sayText = null;
    }

    /** Advances one tick. Does nothing once {@link #end()} is set or while paused. */
    public void tick() {
        prevX = x;
        prevY = y;
        prevZ = z;
        prevBodyYaw = bodyYaw;
        prevHeadYaw = headYaw;
        prevPitch = pitch;
        if (end != End.NONE || paused) {
            return;
        }
        if (++played > LessonLimits.MAX_PLAY_TICKS) {
            end = End.TIMEOUT;
            return;
        }
        for (Ghost g : ghosts) g.age++;
        for (Highlight h : highlights) h.age++;

        if (endHoldLeft >= 0) {
            if (endHoldLeft-- == 0) end = End.FINISHED;
            return;
        }
        if (gapLeft > 0) {
            if (--gapLeft == 0) restart();
            turn();
            return;
        }

        Lesson.Step step = steps[stepIndex];
        if (stepTick == 0) {
            enter(step);
        }
        stepTick++;
        if (Lesson.WALK_TO.equals(step.op)) {
            double t = Math.min(1.0, stepTick / (double) step.ticks);
            x = segmentFrom[0] + (step.pos[0] - segmentFrom[0]) * t;
            y = segmentFrom[1] + (step.pos[1] - segmentFrom[1]) * t;
            z = segmentFrom[2] + (step.pos[2] - segmentFrom[2]) * t;
        }
        turn();
        if (stepTick >= step.ticks) {
            stepIndex++;
            stepTick = 0;
            if (stepIndex >= steps.length) {
                stepIndex = steps.length - 1; // keep showing the last step number
                if (loop) {
                    gapLeft = LessonLimits.LOOP_GAP_TICKS;
                } else {
                    endHoldLeft = LessonLimits.END_HOLD_TICKS;
                }
            }
        }
    }

    private void enter(Lesson.Step s) {
        switch (s.op) {
            case Lesson.WALK_TO:
                segmentFrom = new double[] { x, y, z };
                lookTarget = null;
                pointing = false;
                break;
            case Lesson.LOOK_AT:
                lookTarget = s.pos.clone();
                pointing = true;
                break;
            case Lesson.HIGHLIGHT:
                highlights.add(new Highlight(s));
                lookTarget = center(s.pos);
                pointing = true;
                break;
            case Lesson.GHOST:
                ghosts.add(new Ghost(s));
                lookTarget = center(s.pos);
                pointing = true;
                break;
            case Lesson.HOLD:
                held = s.id;
                heldMeta = s.meta;
                break;
            case Lesson.SWING:
                swings++;
                break;
            case Lesson.SAY:
                sayText = s.text;
                break;
            default:
                break; // wait
        }
    }

    /** Turns body and head toward the walking direction or the look target, a limited angle per tick. */
    private void turn() {
        float bodyTarget = bodyYaw;
        float headTarget = bodyYaw;
        float pitchTarget = 0f;
        double mx = x - prevX, mz = z - prevZ;
        if (lookTarget != null) {
            double dx = lookTarget[0] - x, dy = lookTarget[1] - (y + EYE_HEIGHT), dz = lookTarget[2] - z;
            headTarget = yawOf(dx, dz);
            pitchTarget = pitchOf(dx, dy, dz);
            bodyTarget = headTarget;
        } else if (mx * mx + mz * mz > 1e-6) {
            bodyTarget = yawOf(mx, mz);
            headTarget = bodyTarget;
        }
        bodyYaw = approach(bodyYaw, bodyTarget, MAX_BODY_TURN);
        headYaw = approach(headYaw, headTarget, MAX_HEAD_TURN);
        pitch = pitch + clamp(pitchTarget - pitch, -MAX_HEAD_TURN, MAX_HEAD_TURN);
    }

    /** Minecraft yaw (degrees) that faces along (dx, dz). */
    static float yawOf(double dx, double dz) {
        return (float) (Math.toDegrees(Math.atan2(dz, dx)) - 90.0);
    }

    /** Minecraft pitch (degrees, positive looks down) toward (dx, dy, dz). */
    static float pitchOf(double dx, double dy, double dz) {
        return (float) -Math.toDegrees(Math.atan2(dy, Math.sqrt(dx * dx + dz * dz)));
    }

    /** Moves {@code from} toward {@code to} along the shorter way round, by at most {@code max} degrees. */
    static float approach(float from, float to, float max) {
        float diff = wrap(to - from);
        return from + clamp(diff, -max, max);
    }

    static float wrap(float degrees) {
        float d = degrees % 360f;
        if (d >= 180f) d -= 360f;
        if (d < -180f) d += 360f;
        return d;
    }

    private static float clamp(float v, float lo, float hi) {
        return Math.max(lo, Math.min(hi, v));
    }

    private static double[] center(double[] block) {
        return new double[] { block[0] + 0.5, block[1] + 0.5, block[2] + 0.5 };
    }

    static boolean isPoint(double[] p) {
        if (p == null || p.length != 3) return false;
        for (double v : p) {
            if (Double.isNaN(v) || Double.isInfinite(v)) return false;
        }
        return p[1] >= -64 && p[1] <= 320;
    }

    /** Within the lesson area (a little slack over the server's radius for block centers). */
    static boolean near(double[] p, double[] anchor) {
        double dx = p[0] - anchor[0], dy = p[1] - anchor[1], dz = p[2] - anchor[2];
        return dx * dx + dy * dy + dz * dz <= (LessonLimits.MAX_RADIUS + 2) * (LessonLimits.MAX_RADIUS + 2);
    }

    private static String clip(String s, int max) {
        return s.length() > max ? s.substring(0, max) : s;
    }

    // ---- controls and queries ----

    public void setPaused(boolean paused) {
        this.paused = paused;
    }

    public boolean isPaused() {
        return paused;
    }

    public End end() {
        return end;
    }

    /** 1-based number of the step playing now (the last one during the pause between passes). */
    public int stepNumber() {
        return stepIndex + 1;
    }

    public int stepCount() {
        return steps.length;
    }

    /** The op of the step playing now. */
    public String currentOp() {
        return steps[stepIndex].op;
    }

    /** True while Dave walks (for the limb animation). */
    public boolean walking() {
        return gapLeft == 0 && endHoldLeft < 0 && Lesson.WALK_TO.equals(steps[stepIndex].op) && stepTick > 0;
    }

    /** Between passes of a looping lesson. */
    public boolean betweenPasses() {
        return gapLeft > 0;
    }

    public List<Lesson.Step> steps() {
        List<Lesson.Step> list = new ArrayList<>(steps.length);
        Collections.addAll(list, steps);
        return list;
    }

    /** Ticks played so far (all passes). */
    public int played() {
        return played;
    }
}

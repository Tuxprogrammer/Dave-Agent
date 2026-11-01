package com.tuxprogrammer.davebridge.server.lesson;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Map.Entry;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Pattern;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.tuxprogrammer.davebridge.common.lesson.LessonLimits;
import com.tuxprogrammer.davebridge.common.protocol.Lesson;
import com.tuxprogrammer.davebridge.server.chat.markup.ItemRef;

/**
 * Turns the agent's lesson JSON (docs/plans/guided-demos.md, PROTOCOL.md 1.4 {@code lesson}) into a normalized
 * {@link Lesson} packet, or explains why it can't.
 * <p>
 * Rules: every position lies within {@link LessonLimits#MAX_RADIUS} of the player and in a loaded chunk, items and
 * blocks exist, the step count and the length of one pass are capped, and unknown or invalid steps are dropped with a
 * warning. A lesson with no step left is refused. Each kept step gets its duration in ticks, so the client never has
 * to guess timings.
 * <p>
 * Pure: the world is reached only through {@link Env}, so this is unit-tested without a game.
 */
public final class LessonParser {

    /** What the parser needs to know about the player's world. Called on the server thread. */
    public interface Env {

        /** The chunk holding block column (x, z) is loaded in the player's world. */
        boolean chunkLoaded(int x, int z);

        /** An item with this registry name ("modid:name") exists. */
        boolean itemExists(String name);

        /** A block with this registry name ("modid:name") exists and is not air. */
        boolean blockExists(String name);

        /** How far from the player positions may be: the player's client decides (older ones play less). */
        default double maxRadius() {
            return LessonLimits.MAX_RADIUS;
        }

        /** How many steps the player's client plays once walks are routed. */
        default int maxSteps() {
            return LessonLimits.MAX_PLAYED_STEPS;
        }

        /** A mob's walking route between two feet positions ({@link MobPath}), or null to walk straight. */
        default MobPath.Route route(double[] from, double[] to) {
            return null;
        }
    }

    /** The outcome: a lesson to send, or an {@link #error}. Warnings either way. */
    public static final class Result {

        public final Lesson lesson;
        public final String error;
        public final List<String> warnings;
        /** Steps the agent sent that were not kept. */
        public final int dropped;
        /** Length of one pass in ticks. */
        public final int passTicks;

        Result(Lesson lesson, String error, List<String> warnings, int dropped, int passTicks) {
            this.lesson = lesson;
            this.error = error;
            this.warnings = warnings;
            this.dropped = dropped;
            this.passTicks = passTicks;
        }
    }

    /** Named highlight colors (Minecraft chat palette plus a few aliases), as 0xRRGGBB. */
    static final Map<String, Integer> COLORS = new HashMap<>();
    static final int DEFAULT_COLOR = 0xFFAA00; // gold

    static {
        COLORS.put("black", 0x000000);
        COLORS.put("dark_blue", 0x0000AA);
        COLORS.put("dark_green", 0x00AA00);
        COLORS.put("dark_aqua", 0x00AAAA);
        COLORS.put("dark_red", 0xAA0000);
        COLORS.put("dark_purple", 0xAA00AA);
        COLORS.put("purple", 0xAA00AA);
        COLORS.put("gold", 0xFFAA00);
        COLORS.put("orange", 0xFF8800);
        COLORS.put("gray", 0xAAAAAA);
        COLORS.put("grey", 0xAAAAAA);
        COLORS.put("dark_gray", 0x555555);
        COLORS.put("blue", 0x5555FF);
        COLORS.put("green", 0x55FF55);
        COLORS.put("lime", 0x55FF55);
        COLORS.put("aqua", 0x55FFFF);
        COLORS.put("cyan", 0x55FFFF);
        COLORS.put("red", 0xFF5555);
        COLORS.put("light_purple", 0xFF55FF);
        COLORS.put("pink", 0xFF55FF);
        COLORS.put("magenta", 0xFF55FF);
        COLORS.put("yellow", 0xFFFF55);
        COLORS.put("white", 0xFFFFFF);
    }

    static final String[] FACINGS = { "down", "up", "north", "south", "west", "east" };
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9_.:\\-]{1," + LessonLimits.MAX_ID_CHARS + "}");
    private static final Pattern HEX = Pattern.compile("#?[0-9a-fA-F]{6}");
    private static final AtomicInteger NEXT_ID = new AtomicInteger();

    private LessonParser() {}

    /**
     * @param spec   the agent's lesson object
     * @param anchor the player's feet position {x, y, z} when the lesson is made
     * @param yaw    the player's yaw (degrees, Minecraft convention), used to place Dave in front of them
     * @param dim    the player's dimension
     */
    public static Result parse(JsonElement spec, double[] anchor, float yaw, int dim, Env env) {
        List<String> warnings = new ArrayList<>();
        if (spec == null || !spec.isJsonObject()) {
            return fail("'lesson' must be an object", warnings);
        }
        JsonObject obj = spec.getAsJsonObject();
        JsonElement stepsEl = obj.get("steps");
        if (stepsEl == null || !stepsEl.isJsonArray()) {
            return fail("lesson needs a 'steps' array", warnings);
        }
        JsonArray raw = stepsEl.getAsJsonArray();

        Lesson lesson = new Lesson();
        lesson.id = lessonId(obj.get("id"), warnings);
        lesson.title = clean(string(obj.get("title")), LessonLimits.MAX_TITLE_CHARS);
        lesson.loop = bool(obj.get("loop"), true);
        lesson.speed = LessonLimits.clampSpeed(number(obj.get("speed"), LessonLimits.DEFAULT_SPEED));
        lesson.dim = dim;
        lesson.anchor = new double[] { anchor[0], anchor[1], anchor[2] };

        List<Lesson.Step> steps = new ArrayList<>();
        int dropped = 0;
        for (int i = 0; i < raw.size(); i++) {
            String where = "step " + (i + 1);
            if (steps.size() >= LessonLimits.MAX_STEPS) {
                int rest = raw.size() - i;
                warnings.add("only " + LessonLimits.MAX_STEPS + " steps are kept; dropped the last " + rest);
                dropped += rest;
                break;
            }
            Lesson.Step step = parseStep(raw.get(i), where, lesson.anchor, env, warnings);
            if (step == null) {
                dropped++;
            } else {
                steps.add(step);
            }
        }

        lesson.start = startPoint(lesson.anchor, yaw, env);
        steps = route(steps, lesson.start, env, warnings);
        lesson.speed = fitSpeed(steps, lesson.start, lesson.speed, warnings);
        // Time every step; drop what doesn't fit in one pass.
        double[] at = lesson.start;
        int total = 0;
        List<Lesson.Step> timed = new ArrayList<>();
        for (int i = 0; i < steps.size(); i++) {
            Lesson.Step step = steps.get(i);
            int ticks = duration(step, at, lesson.speed);
            if (total + ticks > LessonLimits.MAX_PASS_TICKS) {
                int rest = steps.size() - i;
                warnings.add(
                    "a pass may last at most " + LessonLimits.MAX_PASS_TICKS / 20
                        + " s; dropped the last "
                        + rest
                        + " steps");
                dropped += rest;
                break;
            }
            step.ticks = ticks;
            total += ticks;
            if (Lesson.WALK_TO.equals(step.op)) {
                at = step.pos;
            }
            timed.add(step);
        }
        if (timed.isEmpty()) {
            return fail(
                "no playable steps left" + (warnings.isEmpty() ? "" : ": " + String.join("; ", warnings)),
                warnings);
        }
        lesson.steps = timed.toArray(new Lesson.Step[0]);
        return new Result(lesson, null, warnings, dropped, total);
    }

    /**
     * Replaces each straight walk with the route a mob would walk (a walk step per turn), so Dave doesn't walk through
     * walls. When no mob could get there, the walk ends at the closest point one can reach. Routes are thinned to fit
     * the steps the player's client plays.
     */
    static List<Lesson.Step> route(List<Lesson.Step> steps, double[] start, Env env, List<String> warnings) {
        List<List<double[]>> turns = new ArrayList<>();
        double[] at = start;
        int extra = 0;
        for (Lesson.Step step : steps) {
            List<double[]> mids = Collections.emptyList();
            if (Lesson.WALK_TO.equals(step.op)) {
                MobPath.Route r = env.route(at, step.pos);
                if (r != null && !r.points.isEmpty()) {
                    mids = new ArrayList<>(r.points.subList(0, r.points.size() - 1));
                    if (!r.reached) {
                        double[] end = r.points.get(r.points.size() - 1);
                        warnings.add(
                            "no walking route reaches " + fmt(step.pos[0])
                                + ","
                                + fmt(step.pos[1])
                                + ","
                                + fmt(step.pos[2])
                                + "; Dave stops "
                                + fmt(distance(end, step.pos))
                                + " blocks short, at "
                                + fmt(end[0])
                                + ","
                                + fmt(end[1])
                                + ","
                                + fmt(end[2]));
                        step.pos = end;
                    }
                } else if (r == null && distance(at, step.pos) > 2) {
                    warnings.add(
                        "could not route the walk to " + fmt(step.pos[0])
                            + ","
                            + fmt(step.pos[1])
                            + ","
                            + fmt(step.pos[2])
                            + "; Dave walks there in a straight line");
                }
                at = step.pos;
            }
            turns.add(mids);
            extra += mids.size();
        }
        int room = Math.max(0, env.maxSteps() - steps.size());
        if (extra > room) {
            warnings.add(
                "the routes have " + extra
                    + " turns; kept "
                    + room
                    + " (the player's client plays at most "
                    + env.maxSteps()
                    + " steps)");
        }
        List<Lesson.Step> out = new ArrayList<>();
        for (int i = 0; i < steps.size(); i++) {
            Lesson.Step step = steps.get(i);
            List<double[]> mids = turns.get(i);
            int keep = extra > room ? (int) ((long) mids.size() * room / extra) : mids.size();
            for (int j = 0; j < keep; j++) {
                // Evenly spaced through the route when it has to be thinned.
                double[] p = mids.get(keep == mids.size() ? j : (int) ((long) (j + 1) * mids.size() / (keep + 1)));
                Lesson.Step walk = new Lesson.Step();
                walk.op = Lesson.WALK_TO;
                walk.pos = p;
                out.add(walk);
            }
            out.add(step);
        }
        return out;
    }

    private static Result fail(String error, List<String> warnings) {
        return new Result(null, error, warnings, 0, 0);
    }

    /**
     * Parses one step object, which has exactly one step key ({@code {"walkTo":[x,y,z]}}). Returns null (with a
     * warning) for anything unknown or invalid.
     */
    static Lesson.Step parseStep(JsonElement el, String where, double[] anchor, Env env, List<String> warnings) {
        if (el == null || !el.isJsonObject()) {
            warnings.add(where + ": not an object, dropped");
            return null;
        }
        JsonObject obj = el.getAsJsonObject();
        String op = null;
        JsonElement arg = null;
        List<String> extra = new ArrayList<>();
        for (Entry<String, JsonElement> e : obj.entrySet()) {
            if (isOp(e.getKey()) && op == null) {
                op = e.getKey();
                arg = e.getValue();
            } else {
                extra.add(e.getKey());
            }
        }
        if (op == null) {
            warnings.add(
                where + ": unknown step "
                    + obj.entrySet()
                        .stream()
                        .map(Entry::getKey)
                        .findFirst()
                        .orElse("{}")
                    + ", dropped");
            return null;
        }
        if (!extra.isEmpty()) {
            warnings.add(where + ": ignored extra keys " + extra);
        }
        String w = where + " (" + op + ")";
        Lesson.Step step = new Lesson.Step();
        step.op = op;
        switch (op) {
            case Lesson.WALK_TO:
            case Lesson.LOOK_AT: {
                double[] pos = point(arg, w, warnings);
                if (pos == null
                    || !inRange(pos, (int) Math.floor(pos[0]), (int) Math.floor(pos[2]), anchor, env, w, warnings))
                    return null;
                step.pos = pos;
                return step;
            }
            case Lesson.HOLD: {
                String ref = arg == null || arg.isJsonNull() ? "" : string(arg);
                if (ref == null) {
                    warnings.add(w + ": expected an item id string, dropped");
                    return null;
                }
                if (ref.trim()
                    .isEmpty()) {
                    step.id = ""; // empty hands
                    return step;
                }
                ItemRef item = ItemRef.parse(ref);
                if (item == null || item.name == null) {
                    warnings.add(w + ": '" + ref + "' is not a modid:name[:meta] item id, dropped");
                    return null;
                }
                if (!env.itemExists(item.name)) {
                    warnings.add(w + ": unknown item " + item.name + ", dropped");
                    return null;
                }
                step.id = item.name;
                step.meta = clampMeta(item.meta);
                return step;
            }
            case Lesson.HIGHLIGHT: {
                JsonObject h = arg != null && arg.isJsonObject() ? arg.getAsJsonObject() : null;
                double[] pos = blockPos(h != null ? h.get("pos") : arg, w, warnings);
                if (pos == null || !inRange(pos, (int) pos[0], (int) pos[2], anchor, env, w, warnings)) return null;
                step.pos = pos;
                step.color = h == null ? DEFAULT_COLOR : color(h.get("color"), w, warnings);
                step.text = h == null ? "" : clean(string(h.get("label")), LessonLimits.MAX_LABEL_CHARS);
                return step;
            }
            case Lesson.GHOST: {
                if (arg == null || !arg.isJsonObject()) {
                    warnings.add(w + ": expected {pos, block, meta, facing}, dropped");
                    return null;
                }
                JsonObject g = arg.getAsJsonObject();
                double[] pos = blockPos(g.get("pos"), w, warnings);
                if (pos == null || !inRange(pos, (int) pos[0], (int) pos[2], anchor, env, w, warnings)) return null;
                String block = string(g.get("block"));
                if (block == null || block.trim()
                    .isEmpty()) {
                    warnings.add(w + ": missing 'block', dropped");
                    return null;
                }
                ItemRef ref = ItemRef.parse(block);
                if (ref == null || ref.name == null || !env.blockExists(ref.name)) {
                    warnings.add(w + ": unknown block " + block + ", dropped");
                    return null;
                }
                step.pos = pos;
                step.id = ref.name;
                double meta = number(g.get("meta"), ref.meta);
                step.meta = clampMeta((int) meta);
                step.facing = facing(g.get("facing"), w, warnings);
                return step;
            }
            case Lesson.SWING:
                if (arg != null && arg.isJsonPrimitive()
                    && arg.getAsJsonPrimitive()
                        .isBoolean()
                    && !arg.getAsBoolean()) {
                    warnings.add(w + ": swing:false does nothing, dropped");
                    return null;
                }
                return step;
            case Lesson.SAY: {
                String text = clean(string(arg), LessonLimits.MAX_SAY_CHARS);
                if (text.isEmpty()) {
                    warnings.add(w + ": empty text, dropped");
                    return null;
                }
                step.text = text;
                return step;
            }
            case Lesson.WAIT: {
                double ticks = number(arg, Double.NaN);
                if (Double.isNaN(ticks) || ticks < 1) {
                    warnings.add(w + ": expected a tick count of at least 1, dropped");
                    return null;
                }
                if (ticks > LessonLimits.MAX_WAIT_TICKS) {
                    warnings.add(w + ": capped at " + LessonLimits.MAX_WAIT_TICKS + " ticks");
                }
                step.ticks = LessonLimits.waitTicks((long) ticks);
                return step;
            }
            default:
                return null; // unreachable: isOp
        }
    }

    static boolean isOp(String key) {
        switch (key) {
            case Lesson.WALK_TO:
            case Lesson.LOOK_AT:
            case Lesson.HOLD:
            case Lesson.HIGHLIGHT:
            case Lesson.GHOST:
            case Lesson.SWING:
            case Lesson.SAY:
            case Lesson.WAIT:
                return true;
            default:
                return false;
        }
    }

    /** How long a step plays, in ticks. walkTo depends on the distance from {@code from}. */
    static int duration(Lesson.Step step, double[] from, double speed) {
        switch (step.op) {
            case Lesson.WALK_TO:
                return LessonLimits.walkTicks(distance(from, step.pos), speed);
            case Lesson.LOOK_AT:
                return LessonLimits.LOOK_TICKS;
            case Lesson.HOLD:
                return LessonLimits.HOLD_TICKS;
            case Lesson.HIGHLIGHT:
                return LessonLimits.HIGHLIGHT_TICKS;
            case Lesson.GHOST:
                return LessonLimits.GHOST_TICKS;
            case Lesson.SWING:
                return LessonLimits.SWING_TICKS;
            case Lesson.SAY:
                return LessonLimits.sayTicks(step.text);
            case Lesson.WAIT:
                return LessonLimits.waitTicks(step.ticks);
            default:
                return 1;
        }
    }

    /**
     * Where the ghost appears: always with the player, two blocks in front of them (where they're looking), so every
     * walk starts from the player, even to a far target. When that spot is inside a wall, the closest spot a mob can
     * walk to from the player's feet; when they're boxed in, their feet.
     */
    static double[] startPoint(double[] anchor, float yaw, Env env) {
        double rad = Math.toRadians(yaw);
        double[] front = { anchor[0] - Math.sin(rad) * 2.0, anchor[1], anchor[2] + Math.cos(rad) * 2.0 };
        MobPath.Route r = env.route(anchor, front);
        if (r == null || r.reached) return front;
        if (r.points.isEmpty()) return anchor.clone();
        double[] p = r.points.get(r.points.size() - 1);
        return new double[] { p[0], p[1], p[2] };
    }

    /**
     * Raises the walking speed (up to {@link LessonLimits#MAX_SPEED}) when the walks would push a pass past
     * {@link LessonLimits#MAX_PASS_TICKS}: a far target means a long walk from the player, and the steps at the end of
     * it (the highlight, the point) are the ones that matter.
     */
    static double fitSpeed(List<Lesson.Step> steps, double[] start, double speed, List<String> warnings) {
        double walked = 0;
        int other = 0;
        double[] at = start;
        for (Lesson.Step step : steps) {
            if (Lesson.WALK_TO.equals(step.op)) {
                walked += distance(at, step.pos);
                at = step.pos;
            } else {
                other += duration(step, at, speed);
            }
        }
        int walkTicks = (int) Math.ceil(walked / (LessonLimits.WALK_BLOCKS_PER_TICK * speed));
        if (walkTicks + other <= LessonLimits.MAX_PASS_TICKS || other >= LessonLimits.MAX_PASS_TICKS) return speed;
        // Margin for each walk step rounding up to whole ticks.
        double room = LessonLimits.MAX_PASS_TICKS - other - steps.size();
        double needed = room <= 0 ? LessonLimits.MAX_SPEED : walked / (LessonLimits.WALK_BLOCKS_PER_TICK * room);
        double faster = LessonLimits.clampSpeed(Math.max(speed, needed * 1.02));
        warnings.add(
            "the walks are " + fmt(walked)
                + " blocks; Dave walks at speed "
                + fmt(faster)
                + " instead of "
                + fmt(speed)
                + " so the pass fits in "
                + LessonLimits.MAX_PASS_TICKS / 20
                + " s");
        return faster;
    }

    static double distance(double[] a, double[] b) {
        double dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
        return Math.sqrt(dx * dx + dy * dy + dz * dz);
    }

    private static boolean inRange(double[] pos, int bx, int bz, double[] anchor, Env env, String w,
        List<String> warnings) {
        if (pos[1] < 0 || pos[1] > 255) {
            warnings.add(w + ": y " + fmt(pos[1]) + " is outside the world, dropped");
            return false;
        }
        double d = distance(pos, anchor);
        if (d > env.maxRadius()) {
            warnings.add(
                w + ": "
                    + fmt(pos[0])
                    + ","
                    + fmt(pos[1])
                    + ","
                    + fmt(pos[2])
                    + " is "
                    + fmt(d)
                    + " blocks from the player (max "
                    + (int) env.maxRadius()
                    + "), dropped");
            return false;
        }
        if (!env.chunkLoaded(bx, bz)) {
            warnings.add(w + ": " + bx + "," + bz + " is in an unloaded chunk, dropped");
            return false;
        }
        return true;
    }

    /** [x, y, z] of finite numbers. */
    static double[] point(JsonElement el, String w, List<String> warnings) {
        if (el == null || !el.isJsonArray()
            || el.getAsJsonArray()
                .size() != 3) {
            warnings.add(w + ": expected [x, y, z], dropped");
            return null;
        }
        double[] p = new double[3];
        for (int i = 0; i < 3; i++) {
            p[i] = number(
                el.getAsJsonArray()
                    .get(i),
                Double.NaN);
            if (Double.isNaN(p[i]) || Double.isInfinite(p[i])) {
                warnings.add(w + ": expected [x, y, z] numbers, dropped");
                return null;
            }
        }
        return p;
    }

    /** A block position: [x, y, z] floored to integers. */
    static double[] blockPos(JsonElement el, String w, List<String> warnings) {
        double[] p = point(el, w, warnings);
        if (p == null) return null;
        for (int i = 0; i < 3; i++) {
            p[i] = Math.floor(p[i]);
        }
        return p;
    }

    static int color(JsonElement el, String w, List<String> warnings) {
        String s = string(el);
        if (s == null || s.trim()
            .isEmpty()) return DEFAULT_COLOR;
        s = s.trim()
            .toLowerCase(Locale.ROOT);
        Integer named = COLORS.get(s);
        if (named != null) return named;
        if (HEX.matcher(s)
            .matches()) {
            return Integer.parseInt(s.startsWith("#") ? s.substring(1) : s, 16);
        }
        warnings.add(w + ": unknown color '" + s + "', using gold");
        return DEFAULT_COLOR;
    }

    static String facing(JsonElement el, String w, List<String> warnings) {
        String s = string(el);
        if (s == null || s.trim()
            .isEmpty()) return null;
        s = s.trim()
            .toLowerCase(Locale.ROOT);
        for (String f : FACINGS) {
            if (f.equals(s)) return f;
        }
        warnings.add(w + ": unknown facing '" + s + "', ignored");
        return null;
    }

    private static String lessonId(JsonElement el, List<String> warnings) {
        String id = string(el);
        if (id != null && ID.matcher(id)
            .matches()) {
            return id;
        }
        if (id != null) {
            warnings.add("lesson id must be 1-" + LessonLimits.MAX_ID_CHARS + " of A-Z a-z 0-9 _ . : -; made one up");
        }
        return "lesson-" + NEXT_ID.incrementAndGet();
    }

    private static int clampMeta(int meta) {
        return Math.max(0, Math.min(Short.MAX_VALUE, meta));
    }

    /** Text for a label: no formatting codes or control characters, trimmed and cut to {@code max}. */
    static String clean(String s, int max) {
        if (s == null) return "";
        StringBuilder out = new StringBuilder(Math.min(s.length(), max));
        for (int i = 0; i < s.length() && out.length() < max; i++) {
            char c = s.charAt(i);
            if (c == '§') {
                i++; // skip the code character too
            } else if (c == '\n' || c == '\t') {
                out.append(' ');
            } else if (c >= ' ' && c != 0x7f) {
                out.append(c);
            }
        }
        return out.toString()
            .trim();
    }

    static String string(JsonElement el) {
        if (el == null || !el.isJsonPrimitive()
            || !el.getAsJsonPrimitive()
                .isString())
            return null;
        return el.getAsString();
    }

    static double number(JsonElement el, double def) {
        if (el == null || !el.isJsonPrimitive()) return def;
        JsonPrimitive p = el.getAsJsonPrimitive();
        if (!p.isNumber()) return def;
        return p.getAsDouble();
    }

    static boolean bool(JsonElement el, boolean def) {
        if (el == null || !el.isJsonPrimitive()
            || !el.getAsJsonPrimitive()
                .isBoolean())
            return def;
        return el.getAsBoolean();
    }

    private static String fmt(double v) {
        return v == Math.rint(v) ? Long.toString((long) v) : String.format(Locale.ROOT, "%.1f", v);
    }
}

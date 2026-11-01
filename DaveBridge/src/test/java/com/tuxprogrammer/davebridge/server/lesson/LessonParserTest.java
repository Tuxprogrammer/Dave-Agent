package com.tuxprogrammer.davebridge.server.lesson;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

import org.junit.jupiter.api.Test;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.tuxprogrammer.davebridge.common.lesson.LessonLimits;
import com.tuxprogrammer.davebridge.common.protocol.Lesson;

class LessonParserTest {

    private static final double[] ANCHOR = { 100.5, 64.0, -20.5 };

    /** Chunks with chunk x &lt; 10 are loaded; a few known items and blocks exist. */
    private static class FakeEnv implements LessonParser.Env {

        final Set<String> items = new HashSet<>(
            Arrays.asList("minecraft:stick", "gregtech:gt.metatool.01", "gregguns:golden_revolver"));
        final Set<String> blocks = new HashSet<>(Arrays.asList("minecraft:chest", "gregtech:gt.blockmachines"));

        @Override
        public boolean chunkLoaded(int x, int z) {
            return (x >> 4) < 10;
        }

        @Override
        public boolean itemExists(String name) {
            return items.contains(name);
        }

        @Override
        public boolean blockExists(String name) {
            return blocks.contains(name);
        }
    }

    private static LessonParser.Result parse(String json) {
        return LessonParser.parse(new JsonParser().parse(json), ANCHOR, 0f, 0, new FakeEnv());
    }

    private static String steps(String... steps) {
        return "{\"id\":\"t1\",\"steps\":[" + String.join(",", steps) + "]}";
    }

    @Test
    void parsesThePlanExample() {
        LessonParser.Result r = parse(
            "{\"id\":\"ebf\",\"title\":\"EBF muffler\",\"loop\":true,\"speed\":0.6,\"steps\":["
                + "{\"walkTo\":[102,64,-18]},"
                + "{\"lookAt\":[104.5,65,-18.5]},"
                + "{\"hold\":\"gregtech:gt.metatool.01:22\"},"
                + "{\"highlight\":{\"pos\":[104,64,-19],\"color\":\"gold\",\"label\":\"Controller goes here\"}},"
                + "{\"ghost\":{\"pos\":[104,65,-19],\"block\":\"gregtech:gt.blockmachines\",\"meta\":1000,\"facing\":\"north\"}},"
                + "{\"swing\":true},"
                + "{\"say\":\"Right-click with a screwdriver to set the output side\"},"
                + "{\"wait\":40}]}");
        assertNull(r.error);
        assertTrue(r.warnings.isEmpty(), r.warnings.toString());
        Lesson l = r.lesson;
        assertEquals("ebf", l.id);
        assertEquals("EBF muffler", l.title);
        assertTrue(l.loop);
        assertEquals(0.6, l.speed, 1e-9);
        assertEquals(8, l.steps.length);
        assertArrayEquals(ANCHOR, l.anchor);
        // Starts by walking: Dave appears on the first waypoint, so that step takes one tick.
        assertArrayEquals(new double[] { 102, 64, -18 }, l.start);
        assertEquals(1, l.steps[0].ticks);

        Lesson.Step hold = l.steps[2];
        assertEquals("gregtech:gt.metatool.01", hold.id);
        assertEquals(22, hold.meta);
        Lesson.Step hl = l.steps[3];
        assertEquals(0xFFAA00, hl.color);
        assertEquals("Controller goes here", hl.text);
        Lesson.Step ghost = l.steps[4];
        assertEquals("gregtech:gt.blockmachines", ghost.id);
        assertEquals(1000, ghost.meta);
        assertEquals("north", ghost.facing);
        assertEquals(40, l.steps[7].ticks);

        int total = 0;
        for (Lesson.Step s : l.steps) total += s.ticks;
        assertEquals(total, r.passTicks);
    }

    @Test
    void unknownAndMalformedStepsAreDroppedWithWarnings() {
        LessonParser.Result r = parse(steps("{\"jump\":true}", "42", "{\"walkTo\":[1,2]}", "{\"say\":\"hi\"}"));
        assertNull(r.error);
        assertEquals(1, r.lesson.steps.length);
        assertEquals(Lesson.SAY, r.lesson.steps[0].op);
        assertEquals(3, r.dropped);
        assertEquals(3, r.warnings.size(), r.warnings.toString());
        assertTrue(
            r.warnings.get(0)
                .contains("jump"),
            r.warnings.get(0));
    }

    @Test
    void positionsMustBeNearThePlayerAndLoadedAndInTheWorld() {
        LessonParser.Result r = parse(
            steps(
                "{\"walkTo\":[-200,64,-20]}", // 300.5 blocks away
                "{\"lookAt\":[100,300,-20]}", // above the world
                "{\"highlight\":[200,64,-20]}", // chunk 12: not loaded
                "{\"highlight\":[161,64,-20]}", // chunk 10: not loaded (and far)
                "{\"walkTo\":[120,64,-20]}"));
        assertEquals(1, r.lesson.steps.length);
        assertEquals(4, r.dropped);
        assertTrue(
            r.warnings.get(0)
                .contains("blocks from the player"),
            r.warnings.get(0));
        assertTrue(
            r.warnings.get(1)
                .contains("outside the world"),
            r.warnings.get(1));
    }

    @Test
    void farTargetsAreFineButOlderClientsKeepTheOldRadius() {
        String spec = steps("{\"walkTo\":[140,64,-20]}", "{\"say\":\"here\"}"); // 39.5 blocks away
        assertEquals(2, parse(spec).lesson.steps.length);
        LessonParser.Env legacy = new FakeEnv() {

            @Override
            public double maxRadius() {
                return LessonLimits.LEGACY_RADIUS;
            }
        };
        LessonParser.Result r = LessonParser.parse(new JsonParser().parse(spec), ANCHOR, 0f, 0, legacy);
        assertEquals(1, r.lesson.steps.length);
        assertTrue(
            r.warnings.get(0)
                .contains("(max 32)"),
            r.warnings.toString());
    }

    @Test
    void unloadedChunkIsRefused() {
        double[] anchor = { 158, 64, 0 };
        LessonParser.Result r = LessonParser.parse(
            new JsonParser().parse(steps("{\"highlight\":[161,64,0]}", "{\"say\":\"x\"}")),
            anchor,
            0f,
            0,
            new FakeEnv());
        assertEquals(1, r.lesson.steps.length);
        assertTrue(
            r.warnings.get(0)
                .contains("unloaded chunk"),
            r.warnings.toString());
    }

    @Test
    void itemsAndBlocksMustExist() {
        LessonParser.Result r = parse(
            steps(
                "{\"hold\":\"nope:thing\"}",
                "{\"hold\":\"ore:ingotSteel\"}",
                "{\"ghost\":{\"pos\":[101,64,-20],\"block\":\"nope:block\"}}",
                "{\"ghost\":{\"pos\":[101,64,-20]}}",
                "{\"hold\":\"stick\"}",
                "{\"ghost\":{\"pos\":[101.7,64.2,-20.1],\"block\":\"minecraft:chest\",\"facing\":\"sideways\"}}"));
        assertEquals(2, r.lesson.steps.length, r.warnings.toString());
        assertEquals("minecraft:stick", r.lesson.steps[0].id);
        Lesson.Step ghost = r.lesson.steps[1];
        assertArrayEquals(new double[] { 101, 64, -21 }, ghost.pos); // floored to the block
        assertNull(ghost.facing);
        assertTrue(
            r.warnings.stream()
                .anyMatch(w -> w.contains("unknown facing")));
    }

    @Test
    void emptyHoldMeansEmptyHands() {
        LessonParser.Result r = parse(steps("{\"hold\":\"\"}", "{\"hold\":null}"));
        assertEquals(2, r.lesson.steps.length);
        assertEquals("", r.lesson.steps[0].id);
        assertEquals("", r.lesson.steps[1].id);
    }

    @Test
    void stepCountIsCapped() {
        String[] many = new String[LessonLimits.MAX_STEPS + 10];
        Arrays.fill(many, "{\"swing\":true}");
        LessonParser.Result r = parse(steps(many));
        assertEquals(LessonLimits.MAX_STEPS, r.lesson.steps.length);
        assertEquals(10, r.dropped);
        assertTrue(
            r.warnings.get(0)
                .contains("dropped the last 10"),
            r.warnings.toString());
    }

    @Test
    void passDurationIsCapped() {
        String[] waits = new String[20];
        Arrays.fill(waits, "{\"wait\":400}"); // 20 x 20 s > 180 s
        LessonParser.Result r = parse(steps(waits));
        assertEquals(LessonLimits.MAX_PASS_TICKS / 400, r.lesson.steps.length);
        assertTrue(r.passTicks <= LessonLimits.MAX_PASS_TICKS);
        assertTrue(
            r.warnings.stream()
                .anyMatch(w -> w.contains("at most 180 s")),
            r.warnings.toString());
    }

    @Test
    void waitIsBoundedAndMustBePositive() {
        LessonParser.Result r = parse(steps("{\"wait\":100000}", "{\"wait\":0}", "{\"wait\":\"soon\"}"));
        assertEquals(1, r.lesson.steps.length);
        assertEquals(LessonLimits.MAX_WAIT_TICKS, r.lesson.steps[0].ticks);
        assertEquals(2, r.dropped);
    }

    @Test
    void walkTimeFollowsDistanceAndSpeed() {
        LessonParser.Result slow = parse("{\"speed\":0.5,\"steps\":[{\"say\":\"hi\"},{\"walkTo\":[100.5,64,-10.5]}]}");
        LessonParser.Result fast = parse("{\"speed\":1.0,\"steps\":[{\"say\":\"hi\"},{\"walkTo\":[100.5,64,-10.5]}]}");
        // Dave starts 2 blocks in front of the player (yaw 0 faces +z): 8 blocks to walk.
        assertArrayEquals(new double[] { 100.5, 64, -18.5 }, slow.lesson.start, 1e-9);
        assertEquals(LessonLimits.walkTicks(8, 0.5), slow.lesson.steps[1].ticks);
        assertEquals(LessonLimits.walkTicks(8, 1.0), fast.lesson.steps[1].ticks);
        assertTrue(slow.lesson.steps[1].ticks > fast.lesson.steps[1].ticks);
    }

    @Test
    void speedAndLoopDefaultsAndClamps() {
        LessonParser.Result r = parse("{\"speed\":99,\"steps\":[{\"swing\":true}]}");
        assertEquals(LessonLimits.MAX_SPEED, r.lesson.speed, 1e-9);
        assertTrue(r.lesson.loop);
        r = parse("{\"speed\":-1,\"loop\":false,\"steps\":[{\"swing\":true}]}");
        assertEquals(LessonLimits.DEFAULT_SPEED, r.lesson.speed, 1e-9);
        assertFalse(r.lesson.loop);
    }

    @Test
    void colorsByNameAndHex() {
        LessonParser.Result r = parse(
            steps(
                "{\"highlight\":{\"pos\":[101,64,-20],\"color\":\"red\"}}",
                "{\"highlight\":{\"pos\":[101,64,-20],\"color\":\"#12abEF\"}}",
                "{\"highlight\":{\"pos\":[101,64,-20],\"color\":\"plaid\"}}"));
        assertEquals(0xFF5555, r.lesson.steps[0].color);
        assertEquals(0x12ABEF, r.lesson.steps[1].color);
        assertEquals(LessonParser.DEFAULT_COLOR, r.lesson.steps[2].color);
        assertEquals(1, r.warnings.size());
    }

    @Test
    void textIsCleanedAndCut() {
        String longText = new String(new char[500]).replace('\0', 'a');
        LessonParser.Result r = parse(
            steps("{\"say\":\"\\u00a7cRed\\u00a7r line\\nnext\"}", "{\"say\":\"" + longText + "\"}"));
        assertEquals("Red line next", r.lesson.steps[0].text);
        assertEquals(LessonLimits.MAX_SAY_CHARS, r.lesson.steps[1].text.length());
    }

    @Test
    void badIdIsReplaced() {
        LessonParser.Result r = parse("{\"id\":\"has spaces!\",\"steps\":[{\"swing\":true}]}");
        assertTrue(r.lesson.id.startsWith("lesson-"), r.lesson.id);
        assertEquals(1, r.warnings.size());
        r = parse("{\"steps\":[{\"swing\":true}]}");
        assertTrue(r.lesson.id.startsWith("lesson-"));
        assertTrue(r.warnings.isEmpty());
    }

    @Test
    void refusesLessonsWithNothingPlayable() {
        assertNotNull(parse("{\"steps\":[]}").error);
        assertNotNull(parse("{\"steps\":[{\"fly\":1}]}").error);
        assertNotNull(parse("{}").error);
        assertNotNull(parse("[]").error);
        assertNull(parse("{}").lesson);
    }

    @Test
    void extraKeysAreIgnoredWithAWarning() {
        LessonParser.Result r = parse(steps("{\"say\":\"hi\",\"color\":\"red\"}"));
        assertEquals(1, r.lesson.steps.length);
        assertTrue(
            r.warnings.get(0)
                .contains("extra keys"),
            r.warnings.toString());
    }

    @Test
    void nonFiniteNumbersAreRejected() {
        JsonObject spec = new JsonParser().parse("{\"steps\":[{\"swing\":true}]}")
            .getAsJsonObject();
        com.google.gson.JsonArray bad = new com.google.gson.JsonArray();
        bad.add(new com.google.gson.JsonPrimitive(Double.NaN));
        bad.add(new com.google.gson.JsonPrimitive(64));
        bad.add(new com.google.gson.JsonPrimitive(0));
        JsonObject step = new JsonObject();
        step.add("walkTo", bad);
        spec.getAsJsonArray("steps")
            .add(step);
        LessonParser.Result r = LessonParser.parse(spec, ANCHOR, 0f, 0, new FakeEnv());
        assertEquals(1, r.lesson.steps.length);
        assertEquals(1, r.dropped);
    }

    @Test
    void walksFollowTheMobRouteAndPartialRoutesStopShort() {
        LessonParser.Env env = new FakeEnv() {

            @Override
            public MobPath.Route route(double[] from, double[] to) {
                // Around a wall: two turns, then the target, which is out of reach for the second walk.
                if (to[2] < -35) {
                    return new MobPath.Route(
                        java.util.Arrays
                            .asList(new double[] { from[0], 64, -30.5 }, new double[] { from[0] + 3, 64, -30.5 }),
                        false);
                }
                return new MobPath.Route(
                    java.util.Arrays.asList(new double[] { 105.5, 64, -15.5 }, new double[] { 108.5, 64, -15.5 }, to),
                    true);
            }
        };
        LessonParser.Result r = LessonParser.parse(
            new JsonParser().parse(steps("{\"walkTo\":[110,64,-10]}", "{\"walkTo\":[110,64,-40]}")),
            ANCHOR,
            0f,
            0,
            env);
        // walk 1: two turns + the target; walk 2: one turn + the closest point
        assertEquals(5, r.lesson.steps.length);
        assertEquals(-30.5, r.lesson.steps[4].pos[2]);
        assertTrue(
            r.warnings.stream()
                .anyMatch(w -> w.contains("no walking route reaches")),
            r.warnings.toString());
    }

    @Test
    void routesAreThinnedForOlderClients() {
        LessonParser.Env env = new FakeEnv() {

            @Override
            public int maxSteps() {
                return 4;
            }

            @Override
            public MobPath.Route route(double[] from, double[] to) {
                java.util.List<double[]> pts = new java.util.ArrayList<>();
                for (int i = 1; i <= 10; i++) pts.add(new double[] { 100.5 + i, 64, -20.5 });
                pts.add(to);
                return new MobPath.Route(pts, true);
            }
        };
        LessonParser.Result r = LessonParser.parse(
            new JsonParser().parse(steps("{\"walkTo\":[115,64,-20]}", "{\"say\":\"here\"}")),
            ANCHOR,
            0f,
            0,
            env);
        assertEquals(4, r.lesson.steps.length);
        assertEquals(115.0, r.lesson.steps[2].pos[0], "the walk still ends at the target");
    }
}

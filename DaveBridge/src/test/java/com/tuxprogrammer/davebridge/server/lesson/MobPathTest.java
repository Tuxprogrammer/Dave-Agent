package com.tuxprogrammer.davebridge.server.lesson;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class MobPathTest {

    /**
     * A flat world drawn as rows of z, columns of x. Ground is solid at y 63; feet stand at y 64. '.' open, 'X' a
     * two-block wall, 'S' a one-block step (stand on top at y 65), outside the map is unloaded.
     */
    static final class MapGrid implements MobPath.Grid {

        final String[] rows;

        MapGrid(String... rows) {
            this.rows = rows;
        }

        char at(int x, int z) {
            return z >= 0 && z < rows.length && x >= 0 && x < rows[z].length() ? rows[z].charAt(x) : '#';
        }

        @Override
        public int stand(int x, int y, int z) {
            char c = at(x, z);
            if (y <= 63) return 0;
            if (c == 'X') return y <= 65 ? 0 : 1;
            if (c == 'S') return y == 64 ? 0 : 1;
            return 1;
        }

        @Override
        public boolean loaded(int x, int z) {
            return at(x, z) != '#';
        }

        @Override
        public int maxFall() {
            return 3;
        }
    }

    private static double[] feet(int x, int y, int z) {
        return new double[] { x + 0.5, y, z + 0.5 };
    }

    /** No straight leg of the route crosses a wall cell (sampled finely). */
    private static void assertNoWallCrossing(MapGrid g, double[] from, MobPath.Route r) {
        double[] at = from;
        for (double[] p : r.points) {
            for (int s = 0; s <= 100; s++) {
                double t = s / 100.0;
                int x = (int) Math.floor(at[0] + (p[0] - at[0]) * t), z = (int) Math.floor(at[2] + (p[2] - at[2]) * t);
                assertTrue(g.at(x, z) != 'X', "walked through the wall at " + x + "," + z);
            }
            at = p;
        }
    }

    @Test
    void goesAroundAWallThroughItsGap() {
        MapGrid g = new MapGrid("..........", "..........", "XXXXXXXX..", "..........", "..........");
        double[] from = feet(1, 64, 0), to = feet(1, 64, 4);
        MobPath.Route r = MobPath.find(g, from, to, MobPath.NODE_BUDGET);
        assertNotNull(r);
        assertTrue(r.reached);
        assertTrue(r.points.size() >= 2, "a detour has turns");
        assertNoWallCrossing(g, from, r);
        double[] end = r.points.get(r.points.size() - 1);
        assertEquals(1.5, end[0]);
        assertEquals(4.5, end[2]);
    }

    @Test
    void openGroundIsOneStraightWalk() {
        MapGrid g = new MapGrid("..........", "..........", "..........");
        MobPath.Route r = MobPath.find(g, feet(0, 64, 0), feet(9, 64, 2), MobPath.NODE_BUDGET);
        assertTrue(r.reached);
        assertEquals(1, r.points.size(), "corners are cut where the walk is clear");
    }

    @Test
    void anEnclosedTargetEndsAtTheClosestReachablePoint() {
        MapGrid g = new MapGrid("......XXX", "......X.X", "......XXX");
        MobPath.Route r = MobPath.find(g, feet(0, 64, 1), feet(7, 64, 1), MobPath.NODE_BUDGET);
        assertNotNull(r);
        assertFalse(r.reached);
        double[] end = r.points.get(r.points.size() - 1);
        assertEquals(5.5, end[0], "stops at the wall");
    }

    @Test
    void stepsUpOneBlockButNotTwo() {
        MapGrid step = new MapGrid("...S...");
        MobPath.Route up = MobPath.find(step, feet(0, 64, 0), feet(3, 65, 0), MobPath.NODE_BUDGET);
        assertTrue(up.reached, "one block up is a step");
        MapGrid wall = new MapGrid("...X...");
        MobPath.Route blocked = MobPath.find(wall, feet(0, 64, 0), feet(6, 64, 0), MobPath.NODE_BUDGET);
        assertFalse(blocked.reached, "a two-block wall in a one-wide corridor can't be crossed");
    }

    @Test
    void anUnloadedStartIsNotRouted() {
        MapGrid g = new MapGrid("....");
        assertEquals(null, MobPath.find(g, feet(10, 64, 10), feet(1, 64, 0), MobPath.NODE_BUDGET));
    }
}

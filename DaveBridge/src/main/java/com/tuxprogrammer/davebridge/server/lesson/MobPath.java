package com.tuxprogrammer.davebridge.server.lesson;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;

/**
 * Routes the lesson ghost the way a mob walks: the walkability rules of vanilla's {@code PathFinder} (step up one
 * block, drop at most {@link Grid#maxFall()} blocks, no lava, fences and closed trapdoors block), searched with A*
 * under a node budget, then shortened where a straight walk at one height is clear, as mobs cut corners. Vanilla's
 * own search reads the live world (it would load chunks) and only expands near its target, so long routes are searched
 * here instead, through {@link Grid}, which only answers for loaded chunks. Pure: unit-tested with a fake grid.
 */
// Source: Minecraft 1.7.10 PathFinder (findPathOptions, getSafePoint, canEntityStandAt) and
// PathNavigate.isDirectPathBetweenPoints, read in gtnh-src/minecraft/net/minecraft/pathfinding/.
public final class MobPath {

    /** What the search needs to know about the world. Called on the server thread. */
    public interface Grid {

        /**
         * Vanilla's {@code PathFinder.canEntityStandAt} for a mob-sized body with its feet at (x, y, z): 1 open, 2 open
         * water, 0 blocked, -1 water (when avoided), -2 lava, -3 fence or rail edge, -4 trapdoor.
         */
        int stand(int x, int y, int z);

        /** The chunk holding column (x, z) is loaded; nothing outside loaded chunks is read. */
        boolean loaded(int x, int z);

        /** Most blocks the mob drops in one step (vanilla: 3). */
        int maxFall();
    }

    /** A route: the points after the start, in order, as feet positions at block centers. */
    public static final class Route {

        public final List<double[]> points;
        /** The route ends at the target; false when it ends at the closest point a mob can reach. */
        public final boolean reached;

        Route(List<double[]> points, boolean reached) {
            this.points = points;
            this.reached = reached;
        }
    }

    /** Nodes the search may visit for one route. */
    public static final int NODE_BUDGET = 30_000;
    private static final double HEURISTIC_WEIGHT = 1.2;

    private MobPath() {}

    private static final class Node implements Comparable<Node> {

        final int x, y, z;
        double cost, estimate;
        Node previous;
        boolean closed;

        Node(int x, int y, int z) {
            this.x = x;
            this.y = y;
            this.z = z;
        }

        @Override
        public int compareTo(Node o) {
            return Double.compare(cost + estimate, o.cost + o.estimate);
        }
    }

    private static long key(int x, int y, int z) {
        return ((long) (x & 0x3FFFFFF) << 38) | ((long) (z & 0x3FFFFFF) << 12) | (y & 0xFFF);
    }

    private static double dist(int ax, int ay, int az, int bx, int by, int bz) {
        double dx = ax - bx, dy = ay - by, dz = az - bz;
        return Math.sqrt(dx * dx + dy * dy + dz * dz);
    }

    /**
     * Finds a walking route from feet position {@code from} to {@code to}. Returns null when no step can be taken at
     * all (the start is boxed in or not loaded): the caller then keeps the straight walk.
     */
    public static Route find(Grid grid, double[] from, double[] to, int budget) {
        int sx = floor(from[0]), sy = floor(from[1] + 0.01), sz = floor(from[2]);
        int tx = floor(to[0]), ty = floor(to[1] + 0.01), tz = floor(to[2]);
        if (!grid.loaded(sx, sz)) return null;
        Map<Long, Node> nodes = new HashMap<>();
        PriorityQueue<Node> open = new PriorityQueue<>();
        Node start = new Node(sx, sy, sz);
        start.estimate = HEURISTIC_WEIGHT * dist(sx, sy, sz, tx, ty, tz);
        nodes.put(key(sx, sy, sz), start);
        open.add(start);
        Node best = start;
        double bestDist = dist(sx, sy, sz, tx, ty, tz);
        boolean reached = false;
        int visited = 0;
        int[][] dirs = { { 0, 1 }, { -1, 0 }, { 1, 0 }, { 0, -1 } };
        while (!open.isEmpty() && visited < budget) {
            Node n = open.poll();
            if (n.closed) continue;
            n.closed = true;
            visited++;
            double d = dist(n.x, n.y, n.z, tx, ty, tz);
            if (d < bestDist) {
                best = n;
                bestDist = d;
            }
            if (n.x == tx && n.y == ty && n.z == tz) {
                reached = true;
                break;
            }
            int stepUp = grid.stand(n.x, n.y + 1, n.z) == 1 ? 1 : 0;
            for (int[] dir : dirs) {
                int[] p = safePoint(grid, n.x + dir[0], n.y, n.z + dir[1], stepUp);
                if (p == null) continue;
                long k = key(p[0], p[1], p[2]);
                Node m = nodes.get(k);
                double cost = n.cost + dist(n.x, n.y, n.z, p[0], p[1], p[2]);
                if (m == null) {
                    m = new Node(p[0], p[1], p[2]);
                    m.estimate = HEURISTIC_WEIGHT * dist(p[0], p[1], p[2], tx, ty, tz);
                    nodes.put(k, m);
                } else if (m.closed || cost >= m.cost) {
                    continue;
                }
                m.cost = cost;
                m.previous = n;
                open.add(m);
            }
        }
        if (best == start) {
            return bestDist < 1.0 ? new Route(Collections.<double[]>emptyList(), true) : null;
        }
        List<int[]> cells = new ArrayList<>();
        for (Node n = best; n != null; n = n.previous) cells.add(new int[] { n.x, n.y, n.z });
        Collections.reverse(cells);
        List<int[]> corners = shorten(grid, cells);
        List<double[]> points = new ArrayList<>();
        for (int i = 1; i < corners.size(); i++) {
            int[] c = corners.get(i);
            points.add(new double[] { c[0] + 0.5, c[1], c[2] + 0.5 });
        }
        return new Route(points, reached || bestDist < 1.5);
    }

    /**
     * Vanilla's getSafePoint: the cell a mob ends up in after stepping into column (x, z) from height y, or null.
     * Steps up one block when there is headroom, then drops to the ground, at most {@link Grid#maxFall()} blocks.
     */
    static int[] safePoint(Grid grid, int x, int y, int z, int stepUp) {
        if (!grid.loaded(x, z)) return null;
        int r = grid.stand(x, y, z);
        if (r == 2) return new int[] { x, y, z };
        int[] p = r == 1 ? new int[] { x, y, z } : null;
        if (p == null && stepUp > 0 && r != -3 && r != -4 && grid.stand(x, y + stepUp, z) == 1) {
            y += stepUp;
            p = new int[] { x, y, z };
        }
        if (p == null) return null;
        int fallen = 0;
        int below = 0;
        while (y > 0) {
            below = grid.stand(x, y - 1, z);
            if (below != 1) break;
            if (fallen++ >= grid.maxFall()) return null;
            y--;
            p = new int[] { x, y, z };
        }
        return below == -2 ? null : p;
    }

    /**
     * Drops cells a mob would walk past on a straight line: from each kept cell, jump to the farthest later cell at the
     * same height whose straight walk stays on open, supported ground (vanilla's isDirectPathBetweenPoints, for a
     * body one block wide).
     */
    static List<int[]> shorten(Grid grid, List<int[]> cells) {
        List<int[]> out = new ArrayList<>();
        if (cells.isEmpty()) return out;
        int i = 0;
        out.add(cells.get(0));
        while (i < cells.size() - 1) {
            int j = i + 1;
            for (int k = cells.size() - 1; k > i + 1; k--) {
                if (clearWalk(grid, cells.get(i), cells.get(k))) {
                    j = k;
                    break;
                }
            }
            out.add(cells.get(j));
            i = j;
        }
        return out;
    }

    /** A straight walk between two cells at one height crosses only open cells with solid ground under them. */
    static boolean clearWalk(Grid grid, int[] a, int[] b) {
        if (a[1] != b[1]) return false;
        int y = a[1];
        double ax = a[0] + 0.5, az = a[2] + 0.5, bx = b[0] + 0.5, bz = b[2] + 0.5;
        double len = Math.sqrt((bx - ax) * (bx - ax) + (bz - az) * (bz - az));
        int samples = Math.max(1, (int) Math.ceil(len / 0.25));
        for (int s = 0; s <= samples; s++) {
            double t = (double) s / samples;
            double x = ax + (bx - ax) * t, z = az + (bz - az) * t;
            // The body is about 0.6 wide: check the cells under both edges.
            for (double ox : new double[] { -0.3, 0.3 }) {
                for (double oz : new double[] { -0.3, 0.3 }) {
                    int cx = floor(x + ox), cz = floor(z + oz);
                    if (!grid.loaded(cx, cz) || grid.stand(cx, y, cz) != 1 || grid.stand(cx, y - 1, cz) == 1) {
                        return false;
                    }
                }
            }
        }
        return true;
    }

    private static int floor(double v) {
        int i = (int) v;
        return v < i ? i - 1 : i;
    }
}

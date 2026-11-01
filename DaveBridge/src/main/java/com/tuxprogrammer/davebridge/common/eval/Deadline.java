package com.tuxprogrammer.davebridge.common.eval;

import java.util.function.LongSupplier;

/**
 * The time limit of the script running on this thread. {@link ScriptChecks} compiles a call to {@link #check()} into
 * the start of every loop body, method and closure of a script, so a runaway loop or recursion stops with a
 * {@link ScriptTimeout} instead of freezing the server tick.
 * <p>
 * Scripts run on the server or client main thread, which must never be interrupted, so the limit is a per-thread
 * deadline rather than {@link Thread#interrupt()}. Java code a script calls (a long scan inside another mod) is not
 * interrupted; the check fires again as soon as control is back in the script.
 */
public final class Deadline {

    private static final ThreadLocal<long[]> DEADLINE = new ThreadLocal<>();
    static volatile LongSupplier clock = System::nanoTime;

    private Deadline() {}

    /** Compiled into scripts. Throws {@link ScriptTimeout} once the current thread's deadline has passed. */
    public static void check() {
        long[] d = DEADLINE.get();
        if (d != null && clock.getAsLong() - d[0] > 0) {
            throw new ScriptTimeout(d[1]);
        }
    }

    /** Starts a deadline {@code millis} from now on this thread. Pair with {@link #end()} in a finally block. */
    static void begin(long millis) {
        DEADLINE.set(new long[] { clock.getAsLong() + millis * 1_000_000L, millis });
    }

    static void end() {
        DEADLINE.remove();
    }
}

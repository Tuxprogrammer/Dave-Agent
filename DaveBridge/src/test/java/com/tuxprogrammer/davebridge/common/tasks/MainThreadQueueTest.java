package com.tuxprogrammer.davebridge.common.tasks;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.Test;

class MainThreadQueueTest {

    @Test
    void runsTasksInOrderAndCompletesFutures() throws Exception {
        MainThreadQueue queue = new MainThreadQueue();
        List<Integer> order = new ArrayList<>();
        CompletableFuture<Integer> a = queue.submit("a", () -> {
            order.add(1);
            return 10;
        });
        CompletableFuture<Void> b = queue.submit("b", () -> { order.add(2); });
        assertEquals(2, queue.depth());
        assertFalse(a.isDone());

        assertEquals(2, queue.drain(Long.MAX_VALUE));
        assertEquals(10, a.get());
        assertTrue(b.isDone());
        assertEquals(java.util.Arrays.asList(1, 2), order);
        assertEquals(0, queue.depth());
        assertEquals(2, queue.executedCount());
    }

    @Test
    void stopsWhenBudgetIsSpentButAlwaysRunsOne() {
        AtomicLong clock = new AtomicLong();
        MainThreadQueue queue = new MainThreadQueue(clock::get);
        for (int i = 0; i < 5; i++) {
            queue.submit("t" + i, () -> clock.addAndGet(3));
        }
        // each task "takes" 3ns; budget 1ns -> exactly one task per drain
        assertEquals(1, queue.drain(1));
        assertEquals(4, queue.depth());
        // budget 6ns -> two tasks
        assertEquals(2, queue.drain(6));
        assertEquals(2, queue.depth());
    }

    @Test
    void exceptionsCompleteTheFutureAndDoNotEscape() {
        MainThreadQueue queue = new MainThreadQueue();
        CompletableFuture<Object> f = queue.submit("boom", () -> { throw new IllegalStateException("boom"); });
        CompletableFuture<Integer> after = queue.submit("after", () -> 1);
        assertEquals(2, queue.drain(Long.MAX_VALUE));
        ExecutionException e = org.junit.jupiter.api.Assertions.assertThrows(ExecutionException.class, f::get);
        assertTrue(e.getCause() instanceof IllegalStateException);
        assertTrue(after.isDone());
        assertEquals(1, queue.failedCount());
    }

    @Test
    void rejectsWhenFull() {
        MainThreadQueue queue = new MainThreadQueue();
        queue.setMaxDepth(2);
        queue.submit("1", () -> 1);
        queue.submit("2", () -> 2);
        CompletableFuture<Integer> third = queue.submit("3", () -> 3);
        assertTrue(third.isCompletedExceptionally());
        ExecutionException e = org.junit.jupiter.api.Assertions.assertThrows(ExecutionException.class, third::get);
        assertTrue(e.getCause() instanceof RejectedExecutionException);
        assertEquals(2, queue.depth());
    }

    @Test
    void clearCancelsPending() {
        MainThreadQueue queue = new MainThreadQueue();
        CompletableFuture<Integer> f = queue.submit("1", () -> 1);
        assertEquals(1, queue.clear("stopping"));
        // CompletableFuture rethrows a CancellationException as-is rather than wrapping it
        org.junit.jupiter.api.Assertions.assertThrows(CancellationException.class, f::get);
        assertEquals(0, queue.depth());
    }

    @Test
    void skipsTasksCancelledBySubmitter() {
        MainThreadQueue queue = new MainThreadQueue();
        AtomicLong ran = new AtomicLong();
        CompletableFuture<Void> f = queue.submit("x", () -> { ran.incrementAndGet(); });
        f.cancel(false);
        queue.drain(Long.MAX_VALUE);
        assertEquals(0, ran.get());
    }

    @Test
    void knowsItsMainThread() {
        MainThreadQueue queue = new MainThreadQueue();
        assertFalse(queue.isMainThread());
        queue.drain(1);
        assertTrue(queue.isMainThread());
    }
}

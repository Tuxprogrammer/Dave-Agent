package com.tuxprogrammer.davebridge.common.tasks;

import java.util.concurrent.Callable;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.LongSupplier;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

/**
 * A bounded, thread-safe queue of work that must run on the server thread.
 * <p>
 * Any thread may {@link #submit} a task; the server thread calls {@link #drain} once per tick, which runs tasks until
 * the per-tick time budget is used up (always at least one, so a busy server still makes progress). Every task gets a
 * {@link CompletableFuture} so the submitter (usually a socket thread) can send a result or an error back.
 * <p>
 * This is deliberately not chat-specific: later milestones (script eval, introspection) submit their work here.
 * No Minecraft types are used so it can be unit-tested without a game.
 */
public final class MainThreadQueue {

    private static final Logger LOG = LogManager.getLogger("davebridge");

    private final ConcurrentLinkedQueue<Task<?>> queue = new ConcurrentLinkedQueue<>();
    private final AtomicInteger depth = new AtomicInteger();
    private final AtomicLong executed = new AtomicLong();
    private final AtomicLong failed = new AtomicLong();
    private final LongSupplier nanoClock;

    private volatile int maxDepth = 1000;
    private volatile Thread mainThread;
    private volatile long lastDrainNanos;
    private volatile int lastDrainCount;

    public MainThreadQueue() {
        this(System::nanoTime);
    }

    /** For tests: supply a fake clock. */
    public MainThreadQueue(LongSupplier nanoClock) {
        this.nanoClock = nanoClock;
    }

    public void setMaxDepth(int maxDepth) {
        this.maxDepth = Math.max(1, maxDepth);
    }

    /**
     * Queues {@code work} to run on the server thread. The returned future completes with its result or exception.
     * If the queue is full the future is already failed with {@link RejectedExecutionException}.
     */
    public <T> CompletableFuture<T> submit(String label, Callable<T> work) {
        Task<T> task = new Task<>(label, work, nanoClock.getAsLong());
        if (depth.incrementAndGet() > maxDepth) {
            depth.decrementAndGet();
            task.future.completeExceptionally(
                new RejectedExecutionException("main-thread queue is full (" + maxDepth + " tasks)"));
            return task.future;
        }
        queue.add(task);
        return task.future;
    }

    public CompletableFuture<Void> submit(String label, Runnable work) {
        return submit(label, () -> {
            work.run();
            return null;
        });
    }

    /**
     * Runs queued tasks on the calling thread (the server thread) until the queue is empty or {@code budgetNanos} has
     * elapsed. At least one task runs if any is queued. Never throws.
     *
     * @return the number of tasks run
     */
    public int drain(long budgetNanos) {
        mainThread = Thread.currentThread();
        long start = nanoClock.getAsLong();
        int ran = 0;
        Task<?> task;
        while ((task = queue.poll()) != null) {
            depth.decrementAndGet();
            task.run();
            ran++;
            if (nanoClock.getAsLong() - start >= budgetNanos) {
                break;
            }
        }
        lastDrainCount = ran;
        lastDrainNanos = nanoClock.getAsLong() - start;
        return ran;
    }

    /** Fails every pending task with a {@link CancellationException}. Returns how many were dropped. */
    public int clear(String reason) {
        int dropped = 0;
        Task<?> task;
        while ((task = queue.poll()) != null) {
            depth.decrementAndGet();
            task.future.completeExceptionally(new CancellationException(reason));
            dropped++;
        }
        return dropped;
    }

    /** True when called from the thread that last drained the queue (the server thread once ticking). */
    public boolean isMainThread() {
        return Thread.currentThread() == mainThread;
    }

    public int depth() {
        return depth.get();
    }

    public int maxDepth() {
        return maxDepth;
    }

    public long executedCount() {
        return executed.get();
    }

    public long failedCount() {
        return failed.get();
    }

    public long lastDrainNanos() {
        return lastDrainNanos;
    }

    public int lastDrainCount() {
        return lastDrainCount;
    }

    private final class Task<T> {

        final String label;
        final Callable<T> work;
        final long submittedAt;
        final CompletableFuture<T> future = new CompletableFuture<>();

        Task(String label, Callable<T> work, long submittedAt) {
            this.label = label;
            this.work = work;
            this.submittedAt = submittedAt;
        }

        void run() {
            if (future.isDone()) {
                return; // cancelled by the submitter while queued
            }
            try {
                future.complete(work.call());
                executed.incrementAndGet();
            } catch (Throwable t) {
                failed.incrementAndGet();
                LOG.debug("Main-thread task '{}' failed", label, t);
                future.completeExceptionally(t);
            }
        }
    }
}

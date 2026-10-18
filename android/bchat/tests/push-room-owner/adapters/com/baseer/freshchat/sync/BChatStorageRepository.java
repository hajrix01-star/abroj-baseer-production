package com.baseer.freshchat.sync;
import java.util.concurrent.*;
/** Existing deterministic routing queue, plus explicit bounded-queue/rejection observations.
 * Actual production State/Owner/Index run on its worker thread; not the Android executor.
 */
public final class BChatStorageRepository {
    private static final ConcurrentLinkedQueue<Runnable> tasks = new ConcurrentLinkedQueue<>();
    public static volatile boolean rejectNext;
    public static volatile Runnable onEnqueue;
    public static int attempts, queued, executed;
    public static Executor executor() { return work -> {
        ++attempts;
        Runnable observe = onEnqueue; if (observe != null) observe.run();
        if (rejectNext) { rejectNext = false; throw new RejectedExecutionException("Explicit fixture storage rejection"); }
        tasks.add(work); ++queued;
    }; }
    public static int pending() { return tasks.size(); }
    public static void drain() throws Exception { run(false); }
    public static void one() throws Exception { run(true); }
    private static void run(boolean one) throws Exception {
        Throwable[] failure = {null};
        Thread worker = new Thread(() -> {
            try { Runnable work; while ((work = tasks.poll()) != null) { ++executed; work.run(); if (one) break; } }
            catch (Throwable problem) { failure[0] = problem; }
        }, "bchat-test-io");
        worker.start(); worker.join(5000);
        if (worker.isAlive()) throw new AssertionError("Fixture disk lane did not finish");
        if (failure[0] != null) throw new AssertionError(failure[0]);
    }
}

package com.baseer.freshchat.sync;

import android.os.Looper;
import java.util.ArrayDeque;
import java.util.concurrent.Executor;

/** Test-only bounded deterministic disk-lane adapter; real production code still commits real prefs. */
public final class BChatStorageRepository {
    private static final ArrayDeque<Runnable> QUEUE = new ArrayDeque<>();
    public static Executor executor() {
        return work -> { synchronized (QUEUE) {
            if (QUEUE.size() >= 64) throw new IllegalStateException("Native fixture queue full");
            QUEUE.add(work);
        }};
    }
    public static boolean drainOne() {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("No disk on UI");
        Runnable work;
        synchronized (QUEUE) { work = QUEUE.poll(); }
        if (work == null) return false;
        work.run(); return true;
    }
    public static int pending() { synchronized (QUEUE) { return QUEUE.size(); } }
    private BChatStorageRepository() { }
}

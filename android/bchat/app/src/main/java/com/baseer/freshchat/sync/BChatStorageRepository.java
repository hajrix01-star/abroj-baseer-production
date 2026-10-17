package com.baseer.freshchat.sync;

import android.os.Handler;
import android.os.Looper;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.*;

/** One process-wide disk lane survives Activity replacement; no caller waits on its UI thread. */
public final class BChatStorageRepository {
    private static final ExecutorService IO = Executors.newSingleThreadExecutor(r -> new Thread(r, "bchat-local-storage"));
    private static final Map<String, Long> GENERATIONS = new HashMap<>();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    public interface Work<T> { T run() throws Exception; }
    public interface Ready<T> { void complete(T value, Exception failure); }
    public static Executor executor() { return IO; }
    public static synchronized long generation(AccountScope account) {
        Long value = GENERATIONS.get(account.key); return value == null ? 0 : value;
    }
    /** Synchronous memory fence; queued old work and callbacks cannot resurrect revoked state. */
    public static synchronized void invalidate(AccountScope account) {
        GENERATIONS.put(account.key, generation(account) + 1);
    }
    public static <T> void submit(AccountScope account, Work<T> work, Ready<T> callback) {
        final long generation = account == null ? 0 : generation(account);
        IO.execute(() -> {
            if (account != null && generation != generation(account)) return;
            T value = null; Exception failure = null;
            try { value = work.run(); } catch (Exception problem) { failure = problem; }
            final T result = value; final Exception error = failure;
            MAIN.post(() -> {
                if (account != null && generation != generation(account)) return;
                callback.complete(result, error);
            });
        });
    }
    public static void write(AccountScope account, Work<Void> work) { submit(account, work, (ignored, error) -> { }); }
    private BChatStorageRepository() { }
}

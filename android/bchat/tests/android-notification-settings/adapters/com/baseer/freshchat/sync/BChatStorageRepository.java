package com.baseer.freshchat.sync;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Test-only executor adapter. No SQLite repository or durable database is substituted or claimed. */
public final class BChatStorageRepository {
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    public static ExecutorService executor() { return WORKER; }
    private BChatStorageRepository() { }
}

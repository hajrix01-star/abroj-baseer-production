package com.baseer.freshchat;

import android.app.Instrumentation;
import android.content.Context;
import android.content.ContextWrapper;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.json.JSONObject;

/** Actual Android35 AtomicFile/JSONObject/Looper/files plus declared narrow I/O injections. */
public final class StoreInstrumentation extends Instrumentation {
    private String phase, session;
    private int checks;
    @Override public void onCreate(Bundle args) {
        super.onCreate(args); phase = args.getString("phase", "all"); session = args.getString("session", ""); start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context base = getContext();
            if (!"com.baseer.bchat.room.preferences.store.test".equals(base.getPackageName()) || Build.VERSION.SDK_INT != 35
                    || !session.matches("[0-9a-f]{32}") || !Arrays.asList("all", "ambiguous", "seed", "started", "ack", "verify").contains(phase))
                throw new IllegalStateException("Refusing non-isolated test identity/phase");
            if ("all".equals(phase) || "ambiguous".equals(phase)) {
                StoreCases.Host host = new StoreCases.Host() {
                    public Context context(String name) throws Exception { return new FixtureContext(base, new File(base.getFilesDir(), "all-" + session + "/" + name)); }
                    public File files(Context context) { return ((FixtureContext) context).files; }
                    public int lookups(Context context) { return ((FixtureContext) context).lookups; }
                    public void main(Runnable action) { runOnMainSync(action); }
                };
                checks = "ambiguous".equals(phase) ? StoreCases.ambiguousEpoch(host) : StoreCases.run(host);
            } else restart(base);
            JSONObject evidence = new JSONObject().put("schema", 1).put("passed", true).put("phase", phase)
                    .put("session", session).put("sdk", Build.VERSION.SDK_INT).put("process_id", Process.myPid())
                    .put("assertions", checks).put("scope", "Actual Android35 AtomicFile/JSON/private files and sequential process restart; explicit sync/finish I/O faults, not power loss; no auth/HTTP/controller/UI/FCM");
            try (FileOutputStream out = new FileOutputStream(new File(base.getFilesDir(), "store-results-" + phase + "-" + session + ".json"))) {
                out.write(evidence.toString(2).getBytes(StandardCharsets.UTF_8));
            }
            result.putString("stream", "PASS " + checks + " actual Android35 RoomPreferencesStore assertions; phase=" + phase
                    + "; pid=" + Process.myPid() + "; no HTTP/controller/power-loss claim\n"); finish(0, result);
        } catch (Throwable failure) {
            result.putString("stream", "FAIL " + failure + " " + Arrays.toString(failure.getStackTrace()) + "\n"); finish(1, result);
        }
    }
    private void check(boolean value, String why) { ++checks; if (!value) throw new AssertionError("Restart " + why); }
    private void restart(Context base) throws Exception {
        FixtureContext context = new FixtureContext(base, new File(base.getFilesDir(), "restart-" + session));
        RoomPreferencesStore store = new RoomPreferencesStore(context, StoreCases.ACCOUNT);
        RoomPreferencesProtocol.Pending a = StoreCases.pending(11, 23, 1, 501), b = StoreCases.pending(12, 24, 1, 502);
        RoomPreferencesStore.Result loaded = store.load();
        if ("seed".equals(phase)) {
            check(loaded.kind == RoomPreferencesStore.Kind.ABSENT, "Fresh owned restart namespace");
            check(store.stage(a, 0).kind == RoomPreferencesStore.Kind.COMMITTED, "Durable stage before first process stop");
            check(store.saveSnapshot(StoreCases.fresh(11, 23, 1), 1).kind == RoomPreferencesStore.Kind.COMMITTED, "Saved metadata before process stop");
            check(store.load().state.operation(11, 23).pending.payload.equals(a.payload), "Exact original UUID/expiry bytes");
        } else if ("started".equals(phase)) {
            check(loaded.kind == RoomPreferencesStore.Kind.LOADED && loaded.state.revision == 2, "Stage survives separate process");
            check(!loaded.state.operation(11, 23).dispatchStarted && loaded.state.operation(11, 23).pending.payload.equals(a.payload), "Never-started identity/bytes restored");
            check(store.markDispatchStarted(a).kind == RoomPreferencesStore.Kind.COMMITTED, "Start persisted before second process stop");
            check(store.stage(b, 3).kind == RoomPreferencesStore.Kind.COMMITTED, "Separate blocked operation admitted");
            check(store.markBlocked(b, "membership_changed").kind == RoomPreferencesStore.Kind.COMMITTED, "Blocked code durable");
        } else if ("ack".equals(phase)) {
            check(loaded.kind == RoomPreferencesStore.Kind.LOADED && loaded.state.revision == 5, "Started flags survive separate process");
            check(loaded.state.operation(11, 23).dispatchStarted && loaded.state.operation(11, 23).pending.payload.equals(a.payload), "Unknown operation retains exact bytes");
            check(loaded.state.operation(12, 24).blockedCode.equals("membership_changed") && !loaded.state.operation(12, 24).dispatchStarted, "Blocked never-started operation preserved");
            check(store.markDispatchStarted(b).kind == RoomPreferencesStore.Kind.BLOCKED, "Restart never grants blocked dispatch");
            check(store.acknowledge(a, StoreCases.ack(a, 2, false)).kind == RoomPreferencesStore.Kind.COMMITTED, "Exact lost-ACK settlement before third process stop");
        } else {
            check(loaded.kind == RoomPreferencesStore.Kind.LOADED && loaded.state.revision == 6, "Settled state survives new process");
            check(loaded.state.operation(11, 23) == null && loaded.state.pending.size() == 1, "Retired operation does not resurrect");
            check(loaded.state.snapshot(11).revision == 2 && !loaded.state.snapshot(11).freshGet, "Disk cache always nonfresh");
            check(loaded.state.operation(12, 24).pending.payload.equals(b.payload)
                    && loaded.state.operation(12, 24).blockedCode.equals("membership_changed"), "Other operation unchanged");
            check(store.acknowledge(a, StoreCases.ack(a, 99, true)).kind == RoomPreferencesStore.Kind.NO_MATCH, "Duplicate cannot update cache after restart");
            check(store.load().state.revision == 6, "Duplicate is exact no-op");
        }
    }
    private static final class FixtureContext extends ContextWrapper {
        final File files; int lookups;
        FixtureContext(Context base, File files) throws IOException {
            super(base); this.files = files;
            if (!files.isDirectory() && !files.mkdirs()) throw new IOException("Owned fixture directory unavailable");
        }
        @Override public Context getApplicationContext() { return this; }
        @Override public File getFilesDir() { ++lookups; return files; }
    }
}

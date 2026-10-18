package com.baseer.freshchat;

import android.app.Instrumentation;
import android.content.Context;
import android.content.ContextWrapper;
import android.os.Build;
import android.os.Bundle;
import android.os.Looper;
import android.os.Process;
import com.baseer.freshchat.sync.AccountScope;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** No Activity or INTERNET permission. Actual SDK35 JSON/AtomicFile/Looper and production
 * components; deterministic worker queue and explicitly fake HTTP/verified-account context. */
public final class MuteIndexInstrumentation extends Instrumentation {
    private String phase, session;
    private File root;
    private int checks, cases;
    private final List<Object> ownedPorts = new ArrayList<>(); // Explicit strong fixture owners of weak production ports.
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments); phase = arguments.getString("phase", "all"); session = arguments.getString("session", ""); start();
    }
    private void check(boolean value, String message) { ++checks; if (!value) throw new AssertionError("Native mute check " + checks + ": " + message); }
    private static final class PrivateContext extends ContextWrapper {
        final File files;
        int lookups;
        PrivateContext(Context context, File files) { super(context); this.files = files; }
        @Override public Context getApplicationContext() { return this; }
        @Override public File getFilesDir() { ++lookups; return files; }
    }
    private PrivateContext context(String name) {
        File directory = new File(root, name);
        if (!directory.isDirectory() && !directory.mkdirs()) throw new AssertionError("Owned test files unavailable");
        return new PrivateContext(getTargetContext(), directory);
    }
    @Override public void onStart() {
        boolean passed = false; String failure = "";
        try {
            check(Build.VERSION.SDK_INT == 35 && session.matches("[0-9a-f]{32}") && phase.matches("all|seed|clear|verify"), "Authorized API35 phase/session");
            root = new File(getTargetContext().getFilesDir(), "mute-index-" + session);
            if (!root.isDirectory() && !root.mkdirs()) throw new AssertionError("Owned root unavailable");
            if (phase.equals("all")) {
                checks += IndexCases.run(new IndexCases.Host() {
                    public Context context(String name) { return MuteIndexInstrumentation.this.context("case-" + (++cases) + "-" + name); }
                    public File files(Context context) { return ((PrivateContext) context).files; }
                    public int lookups(Context context) { return ((PrivateContext) context).lookups; }
                    public void main(Runnable action) { runOnMainSync(action); }
                });
                nativeFlow(false, false); nativeFlow(true, false); nativeFlow(true, true);
            } else restartPhase();
            passed = true;
        } catch (Throwable error) { failure = error.getClass().getSimpleName(); error.printStackTrace(); }
        try {
            JSONObject result = new JSONObject().put("schema", 1).put("passed", passed).put("phase", phase).put("session", session)
                    .put("sdk", Build.VERSION.SDK_INT).put("process_id", Process.myPid()).put("assertions", checks)
                    .put("failure_class", failure).put("scope", "Actual Android35 AtomicFile/JSON and production index/port/controller; deterministic queue/HTTP/auth fixtures; no Activity/FCM/power-loss");
            File output = new File(getTargetContext().getFilesDir(), "mute-results-" + phase + "-" + session + ".json");
            try (FileOutputStream stream = new FileOutputStream(output)) { stream.write(result.toString().getBytes(StandardCharsets.UTF_8)); stream.getFD().sync(); }
        } catch (Exception ignored) { passed = false; }
        Bundle results = new Bundle(); results.putString("stream", (passed ? "PASS " : "FAIL ") + checks
                + " actual Android35 room mute assertions; phase=" + phase + "; pid=" + Process.myPid() + "; explicit queue/HTTP/auth fixtures, no FCM/power-loss");
        finish(passed ? 0 : 1, results);
    }
    private void restartPhase() {
        PrivateContext context = context("restart");
        BChatRoomMuteIndex index = new BChatRoomMuteIndex(context, IndexCases.SCOPE, IndexCases.ACCOUNT);
        if (phase.equals("seed")) {
            check(index.load().kind == BChatRoomMuteIndex.Kind.ABSENT, "Seed only clean owned test index");
            check(index.put(IndexCases.room(1), IndexCases.token(1)).kind == BChatRoomMuteIndex.Kind.COMMITTED, "Seed durable floor");
            check(index.load().state.floors.size() == 1, "Seed exact floor present");
        } else if (phase.equals("clear")) {
            check(index.load().kind == BChatRoomMuteIndex.Kind.LOADED, "New process cold reads floor");
            check(IndexCases.token(1).equals(index.load().state.token(IndexCases.room(1))), "New process same token");
            check(index.clear(IndexCases.room(1), IndexCases.token(2)).kind == BChatRoomMuteIndex.Kind.NO_MATCH, "Changed token never a clear success");
            check(index.clear(IndexCases.room(1), IndexCases.token(1)).kind == BChatRoomMuteIndex.Kind.COMMITTED, "Exact clear persisted");
        } else {
            check(index.load().kind == BChatRoomMuteIndex.Kind.LOADED && index.load().state.floors.isEmpty(), "New process reads persisted empty index");
            check(index.load().state.revision == 2, "Persisted revision monotonic across processes");
        }
    }
    private final class Queue implements RoomPreferencesController.Scheduler {
        final ArrayDeque<Runnable> work = new ArrayDeque<>();
        public synchronized void worker(Runnable action) { work.add(action); }
        public void main(Runnable action) { runOnMainSync(action); }
        public boolean isMain() { return Looper.myLooper() == Looper.getMainLooper(); }
        void one() {
            check(!isMain(), "Actual disk execution off MAIN"); Runnable next;
            synchronized (this) { next = work.poll(); }
            check(next != null, "Bounded work exists"); next.run();
        }
        void drain() { int limit = 100; while (true) { synchronized (this) { if (work.isEmpty()) return; } if (--limit == 0) throw new AssertionError("Unbounded queue"); one(); } }
    }
    private void nativeFlow(boolean desiredMute, boolean revokeAfterIndex) throws Exception {
        PrivateContext context = context("flow-" + desiredMute + "-" + revokeAfterIndex);
        AccountScope account = new AccountScope("https://native-mute.invalid", "synthetic", 41);
        RoomPreferencesController.Binding binding = new RoomPreferencesController.Binding(account, new Object(), new Object(), new RoomPreferencesController.Authority(), 1, 1, 17, 23, 1);
        Queue queue = new Queue();
        BChatRoomMuteIndex index = new BChatRoomMuteIndex(context, account.key, IndexCases.ACCOUNT);
        BChatRoomMutePort.Mirror mirror = new BChatRoomMutePort.Mirror(account.key, IndexCases.ACCOUNT, new BChatRoomMutePort.MonitorGate());
        BChatRoomMutePort.RouteSource source = expected -> new BChatRoomMutePort.Route(binding, IndexCases.ACCOUNT, 7);
        BChatRoomMutePort port = new BChatRoomMutePort(index, mirror, source, queue);
        RoomPreferencesStore store = new RoomPreferencesStore(context, account);
        AtomicReference<RoomPreferencesController.Reply> get = new AtomicReference<>();
        AtomicReference<String> posted = new AtomicReference<>();
        RoomPreferencesController.Host host = new RoomPreferencesController.Host() {
            public RoomPreferencesController.Binding currentBinding(long room) { return room == 17 ? binding : null; }
            public boolean get(RoomPreferencesController.Binding value, RoomPreferencesController.Reply callback) { check(queue.isMain(), "GET fixture final gate on actual MAIN"); get.set(callback); return true; }
            public boolean post(RoomPreferencesController.Binding value, String payload, RoomPreferencesController.Reply callback) { check(queue.isMain(), "POST fixture final gate on actual MAIN"); posted.set(payload); return true; }
        };
        RoomPreferencesController.Observer observer = value -> check(queue.isMain(), "Observer on actual MAIN");
        ownedPorts.add(source); ownedPorts.add(host); ownedPorts.add(observer);
        RoomPreferencesController controller = new RoomPreferencesController(store, binding, host, queue, observer, port);
        check(context.lookups == 0, "Constructors no disk");
        check(port.loadColdWorker() == BChatRoomMuteIndex.Kind.ABSENT, "Actual worker cold absence");
        runOnMainSync(controller::open); queue.drain();
        get.get().complete(200, new JSONObject().put("api_version", 2).put("room_id", 17).put("membership_id", 23).put("revision", 1)
                .put("muted_until", JSONObject.NULL).put("mute_forever", false).put("muted", false).put("pinned", false).put("pinned_at", JSONObject.NULL).put("archived", false));
        queue.drain();
        runOnMainSync(() -> check(controller.state().serverDecisionReady, "Native JSON GET current and durable"));
        runOnMainSync(() -> controller.submit(IndexCases.token(801), null, desiredMute, !desiredMute, false));
        String room = NotificationPresentation.roomKey(IndexCases.ACCOUNT, 7, 17, 23);
        check(port.blocks(account.key, IndexCases.ACCOUNT, room) == desiredMute && store.load().state.pending.isEmpty(), "RAM floor only for desired mute, before stage");
        queue.one(); // Index commit/read-before-stage.
        check(store.load().state.pending.isEmpty(), "Index step before stage");
        if (desiredMute) check(index.load().state.token(room) != null, "Real AtomicFile floor persisted first");
        else check(index.load().kind == BChatRoomMuteIndex.Kind.ABSENT, "Pin no synthetic disk floor");
        if (revokeAfterIndex) runOnMainSync(binding.authority::invalidate);
        queue.drain();
        if (revokeAfterIndex) check(store.load().state.pending.isEmpty() && posted.get() == null && index.load().state.token(room) != null, "Revoked after floor commit: no stage/POST, conservative floor retained");
        else check(store.load().state.pending.size() == 1 && store.load().state.pending.get(0).dispatchStarted && posted.get() != null,
                "Production Controller stages/starts only after exact durable admission");
    }
}

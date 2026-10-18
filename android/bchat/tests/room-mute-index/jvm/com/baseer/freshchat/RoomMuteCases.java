package com.baseer.freshchat;

import android.content.Context;
import android.os.Looper;
import android.util.AtomicFile;
import java.io.*;
import java.lang.ref.WeakReference;
import java.nio.file.Files;
import java.util.*;
import org.json.JSONObject;

/** Actual production index/port/controller and JVM files, explicit Android/JSON/queue/HTTP adapters. */
public final class RoomMuteCases {
    private static int checks;
    private static File root;
    private static final String ACCOUNT = "00000000-0000-4000-8000-000000000099";
    private static final String UUID = "00000000-0000-4000-8000-000000000001";
    private static void check(boolean value, String message) { ++checks; if (!value) throw new AssertionError("Mute component check " + checks + ": " + message); }
    static final class Gate implements BChatRoomMutePort.Gate {
        boolean inside;
        public synchronized <T> T run(BChatRoomMutePort.Value<T> value) {
            check(!inside, "No accidental nested RAM/ROUTING gate"); inside = true;
            try { return value.get(); } finally { inside = false; }
        }
    }
    static final class IndexIo implements BChatRoomMuteIndex.AtomicFiles {
        final Gate gate;
        int writes, failAt;
        Runnable afterFinish;
        IndexIo(Gate gate) { this.gate = gate; }
        public AtomicFile create(File base) {
            check(!gate.inside, "No AtomicFile creation under RAM gate");
            return new AtomicFile(base) {
                public void finishWrite(FileOutputStream stream) {
                    check(!gate.inside, "No finish/sync under RAM gate");
                    if (++writes == failAt) { try { stream.close(); } catch (IOException ignored) { } }
                    else super.finishWrite(stream);
                    Runnable hook = afterFinish; afterFinish = null; if (hook != null) hook.run();
                }
            };
        }
    }
    static final class Logged implements RoomPreferencesController.MutePort {
        final BChatRoomMutePort delegate;
        final List<RoomPreferencesController.RestrictionTicket> tickets = new ArrayList<>();
        final List<Object> admissions = new ArrayList<>(), checked = new ArrayList<>();
        Logged(BChatRoomMutePort port) { delegate = port; }
        public Object checkpoint(RoomPreferencesController.Binding binding) { return delegate.checkpoint(binding); }
        public Object prepare(RoomPreferencesController.RestrictionTicket ticket) {
            Object admission = delegate.prepare(ticket); tickets.add(ticket); admissions.add(admission); return admission;
        }
        public boolean currentDurable(Object admission, RoomPreferencesController.Binding binding, RoomPreferencesProtocol.Pending pending) {
            checked.add(admission); return delegate.currentDurable(admission, binding, pending);
        }
        public void release(RoomPreferencesController.DurableProof proof) { delegate.release(proof); }
    }
    static final class Env {
        final ControllerCases.Fixture fixture = new ControllerCases.Fixture();
        final Gate gate = new Gate();
        final IndexIo io = new IndexIo(gate);
        final BChatRoomMuteIndex index = new BChatRoomMuteIndex(fixture.context, fixture.binding.account.key, ACCOUNT, io);
        final BChatRoomMutePort.Mirror mirror = new BChatRoomMutePort.Mirror(index.scopeKey, ACCOUNT, gate);
        String routeUuid = ACCOUNT;
        long company = 7;
        final BChatRoomMutePort.RouteSource source = expected -> {
            check(!gate.inside, "No Host/RouteSource callback under RAM gate");
            return new BChatRoomMutePort.Route(fixture.binding, routeUuid, company);
        };
        final BChatRoomMutePort port = new BChatRoomMutePort(index, mirror, source, fixture.queue);
        final Logged logged = new Logged(port);
        Env() { replace(); }
        void replace() { fixture.controller = new RoomPreferencesController(fixture.store, fixture.binding, fixture, fixture.queue, fixture, logged); }
        BChatRoomMuteIndex.Kind load() { Looper.mainForTest(false); try { return port.loadColdWorker(); } finally { Looper.mainForTest(true); } }
        BChatRoomMuteIndex.Result disk() { Looper.mainForTest(false); try { return index.load(); } finally { Looper.mainForTest(true); } }
        String room() { return NotificationPresentation.roomKey(ACCOUNT, company, fixture.binding.roomId, fixture.binding.membershipId); }
        boolean blocked() { return port.blocks(index.scopeKey, ACCOUNT, room()); }
        void ready() throws Exception { check(load() == BChatRoomMuteIndex.Kind.ABSENT, "Explicit cold load healthy absence"); fixture.ready(1); }
        void readyMuted() throws Exception {
            Looper.mainForTest(false); try { check(index.put(room(), IndexCases.token(701)).kind == BChatRoomMuteIndex.Kind.COMMITTED, "Seed existing durable floor"); }
            finally { Looper.mainForTest(true); }
            check(load() == BChatRoomMuteIndex.Kind.LOADED, "Cold load existing floor");
            fixture.controller.open(); fixture.queue.drain(); fixture.gets.get(0).complete(200, state(1, true)); fixture.queue.drain();
            check(fixture.controller.state().serverDecisionReady && blocked(), "Muted fresh GET never clears existing floor");
        }
        void replyUnmute() throws Exception {
            fixture.posts.get(0).complete(200, state(2, false).put("client_uuid", UUID).put("operation_revision", 2).put("replayed", false));
        }
    }
    private static JSONObject state(long revision, boolean mute) throws Exception {
        return new JSONObject().put("api_version", 2).put("room_id", 17).put("membership_id", 23).put("revision", revision)
                .put("muted_until", JSONObject.NULL).put("mute_forever", mute).put("muted", mute)
                .put("pinned", false).put("pinned_at", JSONObject.NULL).put("archived", false);
    }
    private static void ordering() throws Exception {
        Env env = new Env(); env.ready();
        env.fixture.controller.submit(UUID, null, true, false, false);
        check(env.blocked() && env.disk().kind == BChatRoomMuteIndex.Kind.ABSENT && env.fixture.load().state.pending.isEmpty(), "Immediate RAM then no stage before durable index");
        env.fixture.queue.disk();
        check(env.disk().state.token(env.room()) != null && env.fixture.load().state.pending.isEmpty(), "Index commits before stage job");
        env.fixture.queue.disk(); env.fixture.queue.ui();
        check(env.fixture.load().state.pending.size() == 1 && !env.fixture.load().state.pending.get(0).dispatchStarted, "Stage only after exact admission");
        env.fixture.queue.disk(); env.fixture.queue.ui();
        check(env.fixture.posts.size() == 1 && env.logged.admissions.size() == 1 && env.logged.checked.size() >= 3,
                "One prepare, gates at stage/mark/actual POST");
        for (Object value : env.logged.checked) check(value == env.logged.admissions.get(0), "Same immutable admission throughout attempt");
        RoomPreferencesProtocol.Pending pending = env.logged.tickets.get(0).pending;
        check(!env.port.currentDurable(new Object(), env.fixture.binding, pending), "Forged opaque admission rejected");
        JSONObject changed = pending.payloadObject().put("archived", true);
        RoomPreferencesProtocol.Pending different = RoomPreferencesProtocol.restorePending(changed, pending.account, pending.roomId);
        check(!env.port.currentDurable(env.logged.admissions.get(0), env.fixture.binding, different), "Same UUID with changed exact payload rejected");
        env.fixture.posts.get(0).complete(0, null); env.fixture.queue.drain();
        env.fixture.controller.retryExplicit(UUID); env.fixture.queue.drain();
        check(env.logged.admissions.size() == 2 && env.logged.admissions.get(0) != env.logged.admissions.get(1)
                && env.fixture.posts.size() == 2 && env.fixture.payloads.get(0).equals(env.fixture.payloads.get(1)), "Explicit retry new admission, unchanged payload");
    }
    private static void nonMutingAndClear() throws Exception {
        for (int mode = 0; mode < 3; mode++) {
            Env env = new Env(); env.ready(); env.fixture.controller.submit(UUID, null, false, mode == 1, mode == 2); env.fixture.queue.drain();
            check(!env.blocked() && env.disk().kind == BChatRoomMuteIndex.Kind.ABSENT && env.fixture.posts.size() == 1,
                    "Unmute/pin/archive admission creates no artificial floor: " + mode);
        }
        Env env = new Env(); env.readyMuted(); String original = env.disk().state.token(env.room());
        env.fixture.controller.submit(UUID, null, false, false, false); env.fixture.queue.drain();
        check(env.blocked() && original.equals(env.disk().state.token(env.room())), "Pending unmute preserves existing index token/floor");
        env.replyUnmute(); env.fixture.queue.ui(); env.fixture.queue.disk(); env.fixture.queue.ui();
        check(env.fixture.load().state.pending.isEmpty() && env.blocked() && original.equals(env.disk().state.token(env.room())), "Store ACK commit does not clear RAM/index early");
        env.fixture.queue.disk();
        check(!env.blocked() && env.disk().state.floors.isEmpty(), "Clear-last index commit before RAM release");
        Env pinMuted = new Env(); pinMuted.readyMuted();
        pinMuted.fixture.controller.submit(UUID, null, true, true, false); pinMuted.fixture.queue.drain();
        check(pinMuted.blocked() && pinMuted.io.writes == 2, "Pin carrying desired mute still writes a new floor");
    }
    private static void failures() throws Exception {
        Env unknown = new Env(); unknown.fixture.controller.open(); unknown.fixture.queue.drain();
        unknown.fixture.gets.get(0).complete(200, state(1, false)); unknown.fixture.queue.drain();
        check(!unknown.fixture.controller.state().serverDecisionReady && unknown.blocked(), "Unknown cold index blocks controls/scoped presentation, not GET");
        for (boolean mute : new boolean[]{false, true}) {
            Env absent = new Env(); absent.ready();
            java.lang.reflect.Field field = RoomPreferencesController.class.getDeclaredField("mute"); field.setAccessible(true);
            ((WeakReference<?>) field.get(absent.fixture.controller)).clear();
            absent.fixture.controller.submit(UUID, null, mute, false, false); absent.fixture.queue.drain();
            check(absent.fixture.posts.isEmpty() && absent.fixture.load().state.pending.isEmpty(), "Collected port prevents all stage/new POST");
        }
        Env failed = new Env(); failed.ready(); failed.io.failAt = 1;
        failed.fixture.controller.submit(UUID, null, true, false, false); failed.fixture.queue.drain();
        check(failed.blocked() && failed.fixture.posts.isEmpty() && failed.fixture.load().state.pending.isEmpty(), "Uncertain floor commit prevents stage, keeps conservative RAM");
        for (boolean afterStarted : new boolean[]{false, true}) {
            Env missing = new Env(); missing.ready(); missing.fixture.controller.submit(UUID, null, true, false, false);
            missing.fixture.queue.disk(); missing.fixture.queue.disk();
            if (afterStarted) { missing.fixture.queue.ui(); missing.fixture.queue.disk(); }
            java.lang.reflect.Field field = RoomPreferencesController.class.getDeclaredField("mute"); field.setAccessible(true);
            ((WeakReference<?>) field.get(missing.fixture.controller)).clear(); missing.fixture.queue.drain();
            check(missing.fixture.posts.isEmpty() && missing.fixture.load().state.pending.get(0).dispatchStarted == afterStarted,
                    "Port lost before mark/actual POST preserves flags, never dispatches");
        }
        Env route = new Env(); route.ready(); route.routeUuid = "00000000-0000-4000-8000-000000000098";
        route.fixture.controller.submit(UUID, null, true, false, false); route.fixture.queue.drain();
        check(route.fixture.posts.isEmpty() && route.fixture.load().state.pending.isEmpty(), "Wrong registered account route cannot admit");
    }
    private static void newerFloorSurvives() throws Exception {
        for (boolean alreadyQueuedClear : new boolean[]{false, true}) {
            Env env = new Env(); env.ready(); env.fixture.send(true); String original = env.disk().state.token(env.room());
            env.fixture.posts.get(0).complete(200, state(3, false).put("client_uuid", UUID).put("operation_revision", 2).put("replayed", true));
            env.fixture.queue.ui(); env.fixture.queue.disk();
            if (alreadyQueuedClear) env.fixture.queue.ui(); // Queue old clear, but do not run its worker.
            Object replacement = env.logged.prepare(env.logged.tickets.get(0)); // Direct component registration, NOT another HTTP write.
            check(replacement != null && env.blocked(), "A new current floor invalidates old checkpoint immediately");
            env.fixture.queue.drain(); String token = env.disk().state.token(env.room());
            check(token != null && !token.equals(original) && env.blocked(), "Old proof cannot clear newer index token: " + alreadyQueuedClear);
            BChatRoomMutePort.Mirror cold = new BChatRoomMutePort.Mirror(env.index.scopeKey, ACCOUNT, new Gate());
            BChatRoomMutePort restarted = new BChatRoomMutePort(env.index, cold, env.source, env.fixture.queue);
            Looper.mainForTest(false); try { check(restarted.loadColdWorker() == BChatRoomMuteIndex.Kind.LOADED, "Cold worker loads actual surviving floor"); }
            finally { Looper.mainForTest(true); }
            check(restarted.blocks(env.index.scopeKey, ACCOUNT, env.room()), "Persisted floor survives a new mirror");
        }
        Env invalidated = new Env(); invalidated.readyMuted(); invalidated.fixture.controller.submit(UUID, null, false, false, false); invalidated.fixture.queue.drain();
        invalidated.replyUnmute(); invalidated.fixture.queue.ui(); invalidated.fixture.queue.disk(); invalidated.fixture.queue.ui();
        invalidated.fixture.invalidate(); invalidated.fixture.queue.drain();
        check(invalidated.disk().state.token(invalidated.room()) != null && invalidated.blocked(), "Revocation before clear worker preserves persisted floor");
    }
    private static void admissionObserverState() throws Exception {
        for (boolean retryStarted : new boolean[]{false, true}) {
            Env env = new Env(); env.ready();
            if (retryStarted) {
                env.fixture.send(true); env.fixture.posts.get(0).complete(0, null); env.fixture.queue.drain();
                env.fixture.controller.retryExplicit(UUID); env.fixture.queue.disk(); env.fixture.queue.ui();
            } else env.fixture.controller.submit(UUID, null, true, false, false);
            env.fixture.queue.disk(); // Floor durable.
            if (!retryStarted) { env.fixture.queue.disk(); env.fixture.queue.ui(); } // Stage committed.
            env.fixture.queue.disk(); // mark COMMITTED or exact explicit-retry UNCHANGED.
            check(env.fixture.load().state.operation(17, 23).dispatchStarted, "Durable flag true before losing port");
            int views = env.fixture.views.size(), posts = env.fixture.posts.size();
            java.lang.reflect.Field field = RoomPreferencesController.class.getDeclaredField("mute"); field.setAccessible(true);
            ((WeakReference<?>) field.get(env.fixture.controller)).clear(); env.fixture.queue.ui();
            RoomPreferencesController.ViewState state = env.fixture.controller.state();
            check(state.pending != null && state.pending.dispatchStarted
                    && state.pending.pending.clientUuid.equals(UUID), "Observer must not report staged-unsent after durable started: " + retryStarted);
            check(env.fixture.posts.size() == posts && state.phase == RoomPreferencesController.Phase.ERROR && !state.serverDecisionReady,
                    "Admission loss still forbids HTTP and writes");
            check(env.fixture.views.size() == views + 1 && env.fixture.views.get(views).pending.dispatchStarted,
                    "Only error emit; refreshed exact metadata has no extra observer event");
        }
    }
    public static void main(String[] args) throws Exception {
        root = new File(args[0]); Files.createDirectories(root.toPath()); ControllerCases.componentRoot(root);
        if (args.length > 1 && args[1].equals("admission-state")) {
            Looper.mainForTest(true); admissionObserverState();
            System.out.println("PASS " + (checks + ControllerCases.fixtureChecks()) + " production room mute component assertions; index=0, port/controller=" + checks
                    + ", fixture=" + ControllerCases.fixtureChecks() + "; focused admission-state only; declared Android/JSON/queue/HTTP adapters, no Android runtime/FCM");
            return;
        }
        Looper.mainForTest(false);
        IndexCases.Host host = new IndexCases.Host() {
            int sequence;
            public Context context(String name) throws Exception { File directory = new File(root, "index-" + (++sequence) + "-" + name); Files.createDirectories(directory.toPath()); return new Context(directory); }
            public File files(Context context) { return context.getFilesDir(); }
            public int lookups(Context context) { return context.fileLookups; }
            public void main(Runnable action) { Looper.mainForTest(true); try { action.run(); } finally { Looper.mainForTest(false); } }
        };
        int indexChecks = IndexCases.run(host); Looper.mainForTest(true);
        ordering(); nonMutingAndClear(); failures(); newerFloorSurvives(); admissionObserverState();
        System.out.println("PASS " + (indexChecks + checks + ControllerCases.fixtureChecks()) + " production room mute component assertions; index=" + indexChecks
                + ", port/controller=" + checks + ", fixture=" + ControllerCases.fixtureChecks() + "; actual JVM files with declared Android/JSON/scheduler/HTTP adapters; no Android runtime/FCM/wiring/power-loss claim");
    }
}

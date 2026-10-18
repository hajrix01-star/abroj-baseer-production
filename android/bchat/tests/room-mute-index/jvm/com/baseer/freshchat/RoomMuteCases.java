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
        final List<RoomPreferencesController.DurableProof> proofs = new ArrayList<>();
        Logged(BChatRoomMutePort port) { delegate = port; }
        public Object checkpoint(RoomPreferencesController.Binding binding) { return delegate.checkpoint(binding); }
        public boolean currentReadHealthy(Object checkpoint, RoomPreferencesController.Binding binding) { return delegate.currentReadHealthy(checkpoint, binding); }
        public Object prepare(RoomPreferencesController.RestrictionTicket ticket) {
            Object admission = delegate.prepare(ticket); tickets.add(ticket); admissions.add(admission); return admission;
        }
        public boolean currentDurable(Object admission, RoomPreferencesController.Binding binding, RoomPreferencesProtocol.Pending pending) {
            checked.add(admission); return delegate.currentDurable(admission, binding, pending);
        }
        public void release(RoomPreferencesController.DurableProof proof) { proofs.add(proof); delegate.release(proof); }
    }
    static final class Env {
        final ControllerCases.Fixture fixture = new ControllerCases.Fixture();
        final Gate gate = new Gate();
        final IndexIo io = new IndexIo(gate);
        final BChatRoomMuteIndex index = new BChatRoomMuteIndex(fixture.context, fixture.binding.account.key, ACCOUNT, io);
        final BChatRoomMutePort.Mirror mirror = new BChatRoomMutePort.Mirror(index.scopeKey, ACCOUNT, gate);
        String routeUuid = ACCOUNT;
        long company = 7;
        boolean rejectPortWorker;
        final BChatRoomMutePort.RouteSource source = expected -> {
            check(!gate.inside, "No Host/RouteSource callback under RAM gate");
            return new BChatRoomMutePort.Route(fixture.binding, routeUuid, company);
        };
        final RoomPreferencesController.Scheduler guardedQueue = new RoomPreferencesController.Scheduler() {
            public void worker(Runnable work) {
                check(!gate.inside, "No worker scheduling under RAM gate");
                if (rejectPortWorker) throw new java.util.concurrent.RejectedExecutionException("Synthetic port queue rejection");
                fixture.queue.worker(work);
            }
            public void main(Runnable work) { check(!gate.inside, "No MAIN scheduling under RAM gate"); fixture.queue.main(work); }
            public boolean isMain() { return fixture.queue.isMain(); }
        };
        final BChatRoomMutePort port = new BChatRoomMutePort(index, mirror, source, guardedQueue);
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
    private static void recovery() throws Exception {
        for (boolean desiredMute : new boolean[]{false, true}) {
            Env env = new Env(); env.ready(); env.fixture.controller.submit(UUID, null, desiredMute, !desiredMute, false);
            env.fixture.queue.disk(); env.fixture.queue.disk(); // index read/put then actual stage.
            env.fixture.controller.pause(); env.fixture.queue.drain(); env.fixture.controller.resume();
            String token = env.disk().state.token(env.room()); int writes = env.io.writes;
            Object checkpoint = env.port.checkpoint(env.fixture.binding);
            check(env.port.currentReadHealthy(checkpoint, env.fixture.binding), "Exact durable index read-health for unsent cancellation");
            env.fixture.controller.cancelUnsentExplicit(UUID); env.fixture.queue.drain();
            check(env.fixture.load().state.pending.isEmpty() && env.fixture.posts.isEmpty() && env.io.writes == writes
                    && Objects.equals(env.disk().state.token(env.room()), token) && env.blocked() == desiredMute,
                    "Read-only cancellation neither creates nor clears floor/token: " + desiredMute);
        }
        Env nondurable = new Env(); nondurable.ready(); nondurable.fixture.controller.submit(UUID, null, true, false, false);
        Object old = nondurable.port.checkpoint(nondurable.fixture.binding);
        check(!nondurable.port.currentReadHealthy(old, nondurable.fixture.binding), "Pending index sync is not read-health");
        nondurable.fixture.queue.disk(); check(nondurable.port.currentReadHealthy(old, nondurable.fixture.binding), "Same checkpoint healthy only after index commit");
        nondurable.logged.prepare(nondurable.logged.tickets.get(0));
        check(!nondurable.port.currentReadHealthy(old, nondurable.fixture.binding), "New checkpoint invalidates cancellation read proof");
        nondurable.fixture.queue.drain(); Object current = nondurable.port.checkpoint(nondurable.fixture.binding);
        nondurable.routeUuid = "00000000-0000-4000-8000-000000000098";
        check(!nondurable.port.currentReadHealthy(current, nondurable.fixture.binding), "Route swap invalidates RAM read-health");
        for (boolean newMute : new boolean[]{false, true}) {
            Env env = new Env(); env.ready(); env.fixture.send(true);
            env.fixture.posts.get(0).complete(409, new JSONObject().put("api_version", 2).put("error", new JSONObject().put("code", "revision_conflict"))); env.fixture.queue.drain();
            env.fixture.controller.refreshConflictExplicit(UUID); env.fixture.queue.drain();
            env.fixture.gets.get(1).complete(200, state(3, false)); env.fixture.queue.drain();
            String original = env.disk().state.token(env.room()); int writes = env.io.writes;
            env.fixture.controller.replaceRejectedExplicit("00000000-0000-4000-8000-000000000002", null, newMute, false, false);
            check(env.blocked() && env.fixture.load().state.operation(17, 23).pending.clientUuid.equals(UUID), "Immediate replacement floor precedes Store mutation");
            env.fixture.queue.disk(); // Real index put or read, same worker lane.
            String admitted = env.disk().state.token(env.room());
            check(admitted != null && (newMute ? !admitted.equals(original) && env.io.writes == writes + 1 : admitted.equals(original) && env.io.writes == writes),
                    "Replacement desired mute persists new token; unmute preserves prior floor: " + newMute);
            check(env.fixture.posts.size() == 1 && env.fixture.load().state.operation(17, 23).pending.clientUuid.equals(UUID), "Index durable before atomic replacement");
            env.fixture.queue.disk(); env.fixture.queue.ui(); env.fixture.queue.disk(); env.fixture.queue.ui();
            check(env.fixture.posts.size() == 2 && env.fixture.load().state.operation(17, 23).dispatchStarted && env.blocked(), "Actual port admission gates replace, mark, new POST without early release");
            Object exact = env.logged.admissions.get(env.logged.admissions.size() - 1);
            check(env.logged.checked.subList(env.logged.checked.size() - 3, env.logged.checked.size()).stream().allMatch(value -> value == exact),
                    "Same immutable replacement admission at all three boundaries");
        }
        Env failed = new Env(); failed.ready(); failed.fixture.send(true);
        failed.fixture.posts.get(0).complete(409, new JSONObject().put("api_version", 2).put("error", new JSONObject().put("code", "revision_conflict"))); failed.fixture.queue.drain();
        failed.fixture.controller.refreshConflictExplicit(UUID); failed.fixture.queue.drain(); failed.fixture.gets.get(1).complete(200, state(3, false)); failed.fixture.queue.drain();
        failed.io.failAt = failed.io.writes + 1;
        failed.fixture.controller.replaceRejectedExplicit("00000000-0000-4000-8000-000000000002", null, true, false, false); failed.fixture.queue.drain();
        check(failed.fixture.posts.size() == 1 && failed.fixture.load().state.operation(17, 23).pending.clientUuid.equals(UUID) && failed.blocked(), "Uncertain replacement floor prevents Store replace and HTTP");
    }
    private static int cells(Env env) throws Exception {
        java.lang.reflect.Field field = BChatRoomMutePort.Mirror.class.getDeclaredField("cells");
        field.setAccessible(true); return ((Map<?, ?>) field.get(env.mirror)).size();
    }
    private static void health() throws Exception {
        Env fresh = new Env();
        BChatRoomMutePort.Health unknown = fresh.port.health(fresh.fixture.binding);
        check(unknown.status == BChatRoomMutePort.HealthStatus.UNKNOWN && unknown.effectiveBlocked
                && unknown.durableFloor == BChatRoomMutePort.DurableFloor.UNKNOWN && cells(fresh) == 0,
                "Initial read is conservative and never allocates a cell/floor");
        List<BChatRoomMutePort.Health> seen = new ArrayList<>();
        BChatRoomMutePort.HealthObserver listener = value -> {
            check(!fresh.gate.inside && fresh.fixture.queue.isMain(), "Health observer outside RAM gate on MAIN");
            check(fresh.port.isCurrent(value, fresh.fixture.binding), "Delivered value is current");
            seen.add(value);
        };
        BChatRoomMutePort.Subscription subscription = fresh.port.observe(fresh.fixture.binding, listener);
        fresh.fixture.queue.ui(); check(seen.size() == 1 && cells(fresh) == 0, "Initial observation does not allocate cell");
        fresh.ready(); fresh.fixture.queue.drain();
        BChatRoomMutePort.Health ready = fresh.port.health(fresh.fixture.binding);
        check(ready.status == BChatRoomMutePort.HealthStatus.READY && !ready.effectiveBlocked
                && ready.durableFloor == BChatRoomMutePort.DurableFloor.OFF
                && !fresh.port.isCurrent(unknown, fresh.fixture.binding), "Cold healthy absence is local OFF, old value stale");
        fresh.fixture.controller.submit(UUID, null, true, false, false);
        BChatRoomMutePort.Health staged = fresh.port.health(fresh.fixture.binding);
        check(staged.status == BChatRoomMutePort.HealthStatus.UNKNOWN && staged.effectiveBlocked
                && staged.durableFloor == BChatRoomMutePort.DurableFloor.UNKNOWN, "Uncommitted floor is not READY");
        fresh.fixture.queue.disk();
        BChatRoomMutePort.Health durable = fresh.port.health(fresh.fixture.binding);
        check(durable.status == BChatRoomMutePort.HealthStatus.READY && durable.effectiveBlocked
                && durable.durableFloor == BChatRoomMutePort.DurableFloor.ON && fresh.fixture.posts.isEmpty(),
                "Durable floor health is not server/POST readiness");
        fresh.fixture.queue.drain();
        check(seen.get(seen.size() - 1).revision == durable.revision && !fresh.port.isCurrent(ready, fresh.fixture.binding),
                "One queued notice coalesces to latest version, never stale READY OFF");
        subscription.close(); int notices = seen.size();
        fresh.port.checkpoint(fresh.fixture.binding); fresh.fixture.queue.drain();
        check(seen.size() == notices && listener != null, "Closed observer receives no later notices");

        for (int kind = 0; kind < 5; ++kind) {
            Env closed = new Env(); closed.ready(); final int[] calls = {0};
            BChatRoomMutePort.HealthObserver observer = value -> { ++calls[0]; check(!closed.gate.inside, "Reentrant callback outside gate"); };
            BChatRoomMutePort.Subscription sub = closed.port.observe(closed.fixture.binding, observer);
            if (kind == 0) sub.close();
            else if (kind == 1) closed.fixture.invalidate();
            else if (kind == 2) closed.company = 8;
            else if (kind == 3) closed.routeUuid = "00000000-0000-4000-8000-000000000098";
            else {
                // Deterministic WeakReference collection seam, not a claim about GC timing.
                java.lang.reflect.Field field = BChatRoomMutePort.Subscription.class.getDeclaredField("observer");
                field.setAccessible(true); ((WeakReference<?>) field.get(sub)).clear();
            }
            closed.fixture.queue.drain(); check(calls[0] == 0, "Queued observer refused after close/revoke/company/route/weak-clear: " + kind);
            sub.close();
        }
        Env reentrant = new Env(); reentrant.ready();
        final BChatRoomMutePort.Subscription[] own = new BChatRoomMutePort.Subscription[1]; final int[] entered = {0};
        BChatRoomMutePort.HealthObserver reentry = value -> {
            ++entered[0]; check(!reentrant.gate.inside, "No observer callback under gate");
            reentrant.port.health(reentrant.fixture.binding); own[0].close();
        };
        own[0] = reentrant.port.observe(reentrant.fixture.binding, reentry); reentrant.fixture.queue.drain();
        check(entered[0] == 1, "Observer can read/unsubscribe/reenter without deadlock or rescheduling");

        Env bounded = new Env(); final int[] boundedCalls = {0};
        BChatRoomMutePort.HealthObserver boundedObserver = value -> ++boundedCalls[0];
        List<BChatRoomMutePort.Subscription> subscriptions = new ArrayList<>();
        for (int n = 0; n < 100; ++n) subscriptions.add(bounded.port.observe(bounded.fixture.binding, boundedObserver));
        boolean refused = false;
        try { bounded.port.observe(bounded.fixture.binding, boundedObserver); }
        catch (IllegalStateException expected) { refused = true; }
        check(refused && cells(bounded) == 0 && bounded.io.writes == 0, "Observer capacity bounded100 without cell/disk effects");
        for (BChatRoomMutePort.Subscription sub : subscriptions) sub.close();
        while (!bounded.fixture.queue.ui.isEmpty()) bounded.fixture.queue.ui();
        check(boundedCalls[0] == 0, "All100 canceled queued notices remain inert");

        for (int outcome = 0; outcome < 3; ++outcome) {
            Env clear = new Env(); clear.readyMuted();
            List<BChatRoomMutePort.Health> values = new ArrayList<>(); BChatRoomMutePort.HealthObserver observer = values::add;
            BChatRoomMutePort.Subscription sub = clear.port.observe(clear.fixture.binding, observer); clear.fixture.queue.drain();
            clear.fixture.controller.submit(UUID, null, false, false, false); clear.fixture.queue.drain();
            clear.replyUnmute(); clear.fixture.queue.ui(); clear.fixture.queue.disk(); clear.fixture.queue.ui();
            BChatRoomMutePort.Health clearing = clear.port.health(clear.fixture.binding);
            check(clear.fixture.controller.state().phase == RoomPreferencesController.Phase.SAVED
                    && clearing.status == BChatRoomMutePort.HealthStatus.CLEARING && clearing.effectiveBlocked
                    && clearing.durableFloor == BChatRoomMutePort.DurableFloor.ON, "Server SAVED is not local unmute success");
            int queued = clear.fixture.queue.disk.size(); long revision = clearing.revision;
            clear.port.release(clear.logged.proofs.get(clear.logged.proofs.size() - 1));
            check(clear.fixture.queue.disk.size() == queued && clear.port.health(clear.fixture.binding).revision == revision,
                    "Repeated exact release does not queue duplicate clear or health revision");
            if (outcome == 1) clear.io.failAt = clear.io.writes + 1;
            else if (outcome == 2) {
                Looper.mainForTest(false);
                try { check(clear.index.put(clear.room(), IndexCases.token(999)).kind == BChatRoomMuteIndex.Kind.COMMITTED,
                        "Concurrent index token CAS witness committed"); }
                finally { Looper.mainForTest(true); }
            }
            clear.fixture.queue.disk(); clear.fixture.queue.drain();
            BChatRoomMutePort.Health settled = clear.port.health(clear.fixture.binding);
            check(!clear.port.isCurrent(clearing, clear.fixture.binding), "Settled health invalidates CLEARING value");
            if (outcome == 0) check(settled.status == BChatRoomMutePort.HealthStatus.READY
                    && settled.durableFloor == BChatRoomMutePort.DurableFloor.OFF && !settled.effectiveBlocked && !clear.blocked(),
                    "OFF only after actual clear COMMITTED and current binding");
            else {
                check(settled.status == BChatRoomMutePort.HealthStatus.FAILED
                        && settled.durableFloor == BChatRoomMutePort.DurableFloor.UNKNOWN && settled.effectiveBlocked && clear.blocked(),
                        "Uncertain/CAS failed clear never publishes local OFF: " + outcome);
                clear.fixture.controller.refresh(); clear.fixture.queue.drain();
                clear.fixture.gets.get(clear.fixture.gets.size() - 1).complete(200, state(3, false)); clear.fixture.queue.drain();
                check(clear.port.health(clear.fixture.binding).status == BChatRoomMutePort.HealthStatus.FAILED && clear.blocked(),
                        "GET/cachedfalse never heals unknown index");
            }
            check(values.stream().noneMatch(value -> value.revision >= clearing.revision
                    && !value.effectiveBlocked && settled.status == BChatRoomMutePort.HealthStatus.FAILED), "No false-unmute observer value");
            sub.close();
        }
        Env newer = new Env(); newer.ready(); newer.fixture.send(true);
        newer.fixture.posts.get(0).complete(200, state(3, false).put("client_uuid", UUID).put("operation_revision", 2).put("replayed", true));
        newer.fixture.queue.ui(); newer.fixture.queue.disk(); newer.fixture.queue.ui();
        BChatRoomMutePort.Health previous = newer.port.health(newer.fixture.binding);
        check(previous.status == BChatRoomMutePort.HealthStatus.CLEARING, "Old legitimate clear is pending");
        newer.logged.prepare(newer.logged.tickets.get(0)); newer.fixture.queue.drain();
        BChatRoomMutePort.Health latest = newer.port.health(newer.fixture.binding);
        check(latest.status == BChatRoomMutePort.HealthStatus.READY && latest.durableFloor == BChatRoomMutePort.DurableFloor.ON
                && latest.effectiveBlocked && !newer.port.isCurrent(previous, newer.fixture.binding), "New floor supersedes clear and keeps current durable ON");

        Env refusedClear = new Env(); refusedClear.readyMuted();
        List<BChatRoomMutePort.Health> rejectedStates = new ArrayList<>();
        BChatRoomMutePort.HealthObserver observer = rejectedStates::add;
        BChatRoomMutePort.Subscription sub = refusedClear.port.observe(refusedClear.fixture.binding, observer); refusedClear.fixture.queue.drain();
        refusedClear.fixture.controller.submit(UUID, null, false, false, false); refusedClear.fixture.queue.drain();
        refusedClear.replyUnmute(); refusedClear.fixture.queue.ui(); refusedClear.fixture.queue.disk();
        refusedClear.rejectPortWorker = true; refusedClear.fixture.queue.ui(); refusedClear.fixture.queue.drain();
        BChatRoomMutePort.Health failedClear = refusedClear.port.health(refusedClear.fixture.binding);
        check(refusedClear.fixture.controller.state().phase == RoomPreferencesController.Phase.SAVED
                && failedClear.status == BChatRoomMutePort.HealthStatus.FAILED && failedClear.effectiveBlocked
                && refusedClear.disk().state.token(refusedClear.room()) != null && refusedClear.fixture.queue.disk.isEmpty(),
                "Rejected clear scheduling is terminal FAILED/blocked, no throw or fictitious running work");
        check(rejectedStates.get(rejectedStates.size() - 1).status == BChatRoomMutePort.HealthStatus.FAILED,
                "Rejected clear notifies FAILED outside gate");
        refusedClear.port.release(refusedClear.logged.proofs.get(refusedClear.logged.proofs.size() - 1));
        check(refusedClear.port.health(refusedClear.fixture.binding).status == BChatRoomMutePort.HealthStatus.FAILED,
                "Repeated rejected release cannot heal floor"); sub.close();
        Env refusedPut = new Env(); refusedPut.ready(); refusedPut.rejectPortWorker = true;
        refusedPut.fixture.controller.submit(UUID, null, true, false, false); refusedPut.fixture.queue.drain();
        check(refusedPut.port.health(refusedPut.fixture.binding).status == BChatRoomMutePort.HealthStatus.FAILED
                && refusedPut.blocked() && refusedPut.fixture.posts.isEmpty() && refusedPut.fixture.load().state.pending.isEmpty(),
                "Rejected prepare scheduling cannot grant admission/Store stage/POST");
    }
    public static void main(String[] args) throws Exception {
        root = new File(args[0]); Files.createDirectories(root.toPath()); ControllerCases.componentRoot(root);
        if (args.length > 1 && args[1].equals("health")) {
            Looper.mainForTest(true); health();
            System.out.println("PASS " + (checks + ControllerCases.fixtureChecks()) + " production room mute component assertions; port/controller=" + checks
                    + ", fixture=" + ControllerCases.fixtureChecks() + "; focused health; declared Android/JSON/queue/HTTP adapters, no Android runtime/FCM");
            return;
        }
        if (args.length > 1 && args[1].equals("recovery")) {
            Looper.mainForTest(true); recovery();
            System.out.println("PASS " + (checks + ControllerCases.fixtureChecks()) + " production room mute component assertions; index=0, port/controller=" + checks
                    + ", fixture=" + ControllerCases.fixtureChecks() + "; focused recovery only; declared Android/JSON/queue/HTTP adapters, no Android runtime/FCM");
            return;
        }
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
        ordering(); nonMutingAndClear(); failures(); newerFloorSurvives(); admissionObserverState(); health();
        System.out.println("PASS " + (indexChecks + checks + ControllerCases.fixtureChecks()) + " production room mute component assertions; index=" + indexChecks
                + ", port/controller=" + checks + ", fixture=" + ControllerCases.fixtureChecks() + "; actual JVM files with declared Android/JSON/scheduler/HTTP adapters; no Android runtime/FCM/wiring/power-loss claim");
    }
}

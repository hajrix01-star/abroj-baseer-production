package com.baseer.freshchat;

import android.os.Looper;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Objects;
import org.json.JSONObject;

/** DEV176 only. Actual Protocol/Store/Controller and JVM files; reuses the declared
 * Context/Looper/AtomicFile/Gson, deterministic Queue/transport/MutePort test adapters.
 * No authentication, HTTP, actual Owner, Android/FCM or power-loss acceptance. */
final class ControllerCancellationCases {
    private static final String ID = "00000000-0000-4000-8000-000000000001", NEXT = "00000000-0000-4000-8000-000000000002";
    private static int checks, groups;
    interface Action { void run() throws Exception; }
    interface Work<T> { T run() throws Exception; }
    private static void check(boolean value, String label) { ++checks; if (!value) throw new AssertionError("Cancellation " + checks + ": " + label); }
    private static int total() { return checks + ControllerCases.fixtureChecks(); }
    private static void group(String name, Action work) throws Exception { int before = total(); work.run(); ++groups; System.out.println("GROUP " + name + " PASS " + (total() - before)); }
    private static <T> T disk(Work<T> work) throws Exception { Looper.mainForTest(false); try { return work.run(); } finally { Looper.mainForTest(true); } }
    private static JSONObject copy(JSONObject body) throws Exception { return new JSONObject(body.toString()); }
    private static void invalid(Action work, String label) throws Exception { boolean failed = false; try { work.run(); } catch (IllegalArgumentException expected) { failed = true; } check(failed, label); }
    private static JSONObject snapshot(long room, long member, long revision) throws Exception {
        return new JSONObject().put("api_version", 2).put("room_id", room).put("membership_id", member).put("revision", revision)
                .put("muted_until", JSONObject.NULL).put("mute_forever", false).put("muted", false).put("pinned", false).put("pinned_at", JSONObject.NULL).put("archived", false);
    }
    private static JSONObject cancelled(RoomPreferencesProtocol.Pending pending) throws Exception {
        return new JSONObject().put("api_version", 2).put("room_id", pending.roomId).put("membership_id", pending.membershipId)
                .put("client_uuid", pending.clientUuid).put("expected_revision", pending.expectedRevision).put("cancelled", true);
    }
    private static JSONObject ack(RoomPreferencesProtocol.Pending pending) throws Exception {
        return snapshot(pending.roomId, pending.membershipId, pending.expectedRevision + 1)
                .put("muted_until", pending.mutedUntil == null ? JSONObject.NULL : pending.mutedUntil).put("mute_forever", pending.muteForever)
                .put("muted", pending.muteForever || pending.mutedUntil != null).put("pinned", pending.pinned)
                .put("pinned_at", pending.pinned ? "2026-10-17T01:02:03Z" : JSONObject.NULL).put("archived", pending.archived)
                .put("client_uuid", pending.clientUuid).put("operation_revision", pending.expectedRevision + 1).put("replayed", true);
    }
    private static RoomPreferencesProtocol.Pending make(ControllerCases.Fixture f, String uuid, long room, long member, String until, boolean forever) throws Exception {
        return RoomPreferencesProtocol.newPending(RoomPreferencesProtocol.freshSnapshot(snapshot(room, member, 1), f.binding.account, room, member), uuid, until, forever, false, false);
    }
    private static RoomPreferencesController.Binding version(RoomPreferencesController.Binding b, int v) {
        return new RoomPreferencesController.Binding(b.account, b.accountIdentity, b.sessionIdentity, b.authority,
                b.globalGeneration, b.repositoryGeneration, b.roomId, b.membershipId, b.contractVersion, v);
    }
    private static final class Env implements RoomPreferencesController.Host {
        final ControllerCases.Fixture f = new ControllerCases.Fixture();
        final List<RoomPreferencesController.Reply> cancels = new ArrayList<>();
        final List<String> payloads = new ArrayList<>();
        boolean accepted = true, throwing;
        Env() { this(1); }
        Env(int v) { f.binding = version(f.binding, v); install(); }
        void install() { f.controller = new RoomPreferencesController(f.store, f.binding, this, f.queue, f, f); }
        public RoomPreferencesController.Binding currentBinding(long room) { return f.currentBinding(room); }
        public boolean get(RoomPreferencesController.Binding binding, RoomPreferencesController.Reply reply) { return f.get(binding, reply); }
        public boolean post(RoomPreferencesController.Binding binding, String payload, RoomPreferencesController.Reply reply) { return f.post(binding, payload, reply); }
        public boolean cancel(RoomPreferencesController.Binding binding, String payload, RoomPreferencesController.Reply reply) {
            check(f.queue.isMain() && binding == f.binding && binding.authority.valid() && binding.cancelContractVersion == 1, "cancel final declared Host MAIN/current/version gate");
            RoomPreferencesStore.Operation loaded = pending();
            check(loaded != null && loaded.dispatchStarted && loaded.pending.payload.equals(payload), "cancel exact existing durable started bytes; no mark/new UUID");
            if (throwing) throw new IllegalStateException("synthetic transport refusal");
            cancels.add(reply); payloads.add(payload); return accepted;
        }
        RoomPreferencesStore.Operation pending() { return f.load().state.operation(f.binding.roomId, f.binding.membershipId); }
        void unknown(boolean muted) throws Exception {
            f.ready(1); f.send(muted); f.posts.get(0).complete(0, null); f.queue.drain();
            check(f.controller.state().phase == RoomPreferencesController.Phase.UNKNOWN, "original reply loss remains unknown");
        }
        void startCancel() { f.controller.cancelStartedExplicit(ID); f.queue.drain(); check(!cancels.isEmpty(), "explicit cancellation accepted by fake transport"); }
        RoomPreferencesProtocol.Pending exact() { return pending().pending; }
    }
    private static void protocol() throws Exception {
        Env e = new Env(); RoomPreferencesProtocol.Pending pending = make(e.f, ID, 17, 23, "2000-01-01T00:00:00Z", false);
        JSONObject valid = cancelled(pending); RoomPreferencesProtocol.Cancellation receipt = RoomPreferencesProtocol.cancellation(200, valid, pending);
        check(receipt.matches(pending), "expired but canonical request binds immutable six-field receipt without a clock");
        valid.put("cancelled", false); check(receipt.matches(pending), "caller JSON mutation cannot change typed receipt");
        for (Constructor<?> c : RoomPreferencesProtocol.Cancellation.class.getDeclaredConstructors()) check(Modifier.isPrivate(c.getModifiers()), "private typed receipt construction");
        for (Field field : RoomPreferencesProtocol.Cancellation.class.getDeclaredFields()) check(Modifier.isFinal(field.getModifiers()), "receipt fields immutable");
        JSONObject good = cancelled(pending);
        for (String key : new String[]{"api_version", "room_id", "membership_id", "client_uuid", "expected_revision", "cancelled"}) {
            JSONObject missing = copy(good); missing.remove(key); invalid(() -> RoomPreferencesProtocol.cancellation(200, missing, pending), "missing field " + key);
        }
        Object[][] bad = {{"api_version", 2.0}, {"room_id", 17.0}, {"membership_id", 24}, {"client_uuid", NEXT}, {"expected_revision", 2}, {"cancelled", false}, {"cancelled", "true"}};
        for (Object[] row : bad) { JSONObject changed = copy(good).put((String) row[0], row[1]); invalid(() -> RoomPreferencesProtocol.cancellation(200, changed, pending), "wrong strict field " + row[0]); }
        invalid(() -> RoomPreferencesProtocol.cancellation(201, good, pending), "only status200");
        invalid(() -> RoomPreferencesProtocol.cancellation(200, copy(good).put("extra", true), pending), "extra key refused");
        invalid(() -> RoomPreferencesProtocol.cancellation(200, ack(pending), pending), "ACK not cancellation");
        invalid(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending).put("cancelled", false), pending), "ACK parser rejects discriminant instead of fallback");
        RoomPreferencesProtocol.Pending otherPayload = RoomPreferencesProtocol.newPending(RoomPreferencesProtocol.freshSnapshot(snapshot(17, 23, 1), e.f.binding.account, 17, 23), ID, pending.mutedUntil, false, true, false);
        check(!receipt.matches(otherPayload), "same UUID/six fields do not authorize another original payload");
        JSONObject bootstrap = new JSONObject().put("api_version", 2).put("room_preferences_contract_version", 1);
        check(RoomPreferencesProtocol.supported(bootstrap) && !RoomPreferencesProtocol.cancelSupported(bootstrap), "optional absence preserves base C17");
        for (Object value : new Object[]{true, "1", 1.0, 2, -1, JSONObject.NULL}) {
            bootstrap.put("room_preferences_cancel_contract_version", value); check(!RoomPreferencesProtocol.cancelSupported(bootstrap) && RoomPreferencesProtocol.supported(bootstrap), "unsupported optional contract only hides cancellation");
        }
        bootstrap.put("room_preferences_cancel_contract_version", 1); check(RoomPreferencesProtocol.cancelSupported(bootstrap), "strict optional version1");
        check(new ControllerCases.Fixture().binding.cancelContractVersion == 0 && new Env(7).f.binding.cancelContractVersion == 0, "old Binding constructor/unknown version default0");
    }
    private static void store() throws Exception {
        Env e = new Env(); e.f.cache(snapshot(17, 23, 1));
        RoomPreferencesProtocol.Pending first = make(e.f, ID, 17, 23, null, true), other = make(e.f, NEXT, 18, 24, null, true);
        disk(() -> e.f.store.stage(first, e.f.store.load().state.revision)); disk(() -> e.f.store.stage(other, e.f.store.load().state.revision));
        RoomPreferencesProtocol.Cancellation receipt = RoomPreferencesProtocol.cancellation(200, cancelled(first), first);
        check(disk(() -> e.f.store.cancelledExact(first, receipt)).kind == RoomPreferencesStore.Kind.INVALID, "unsent cannot be settled by cancellation receipt");
        disk(() -> e.f.store.markDispatchStarted(first));
        String snapshots = new JSONObject(Files.readString(e.f.file().toPath())).opt("snapshots").toString(); long revision = e.f.load().state.revision;
        RoomPreferencesProtocol.Pending wrong = RoomPreferencesProtocol.newPending(RoomPreferencesProtocol.freshSnapshot(snapshot(17, 23, 1), e.f.binding.account, 17, 23), ID, null, true, true, false);
        check(disk(() -> e.f.store.cancelledExact(wrong, receipt)).kind == RoomPreferencesStore.Kind.NO_MATCH, "payload CAS exact");
        RoomPreferencesProtocol.Cancellation wrongReceipt = RoomPreferencesProtocol.cancellation(200, cancelled(wrong), wrong);
        check(disk(() -> e.f.store.cancelledExact(first, wrongReceipt)).kind == RoomPreferencesStore.Kind.INVALID, "receipt bound to exact request payload");
        RoomPreferencesStore.Result result = disk(() -> e.f.store.cancelledExact(first, receipt));
        check(result.kind == RoomPreferencesStore.Kind.COMMITTED && result.state.revision == revision + 1 && result.state.pending.size() == 1
                && result.state.operation(18, 24).pending.payload.equals(other.payload), "single exact retirement preserves other pending");
        check(snapshots.equals(new JSONObject(Files.readString(e.f.file().toPath())).opt("snapshots").toString()), "all snapshots exact unchanged");
        byte[] saved = Files.readAllBytes(e.f.file().toPath());
        check(disk(() -> e.f.store.cancelledExact(first, receipt)).kind == RoomPreferencesStore.Kind.NO_MATCH
                && Arrays.equals(saved, Files.readAllBytes(e.f.file().toPath())), "duplicate cancellation no mutation");
        RoomPreferencesProtocol.Pending replacement = make(e.f, "00000000-0000-4000-8000-000000000003", 17, 23, null, true);
        disk(() -> e.f.store.stage(replacement, e.f.store.load().state.revision));
        check(disk(() -> e.f.store.cancelledExact(first, receipt)).kind == RoomPreferencesStore.Kind.NO_MATCH && e.pending().pending.clientUuid.equals(replacement.clientUuid), "late cancellation cannot retire a replacement intent");
        check(disk(() -> e.f.store.acknowledge(first, RoomPreferencesProtocol.acknowledgement(200, ack(first), first))).kind == RoomPreferencesStore.Kind.NO_MATCH, "late ACK cannot mutate retired intent/cache");
    }
    private static void explicitFlow() throws Exception {
        Env e = new Env(); e.unknown(true); RoomPreferencesProtocol.Pending exact = e.exact(); int releases = e.f.releases.size(), writes = e.f.faults.writes, gets = e.f.gets.size();
        e.startCancel(); check(e.f.faults.writes == writes && e.payloads.get(0).equals(exact.payload), "no new staging/mark/cancel UUID before dispatch");
        e.cancels.get(0).complete(200, cancelled(exact)); e.f.queue.drain();
        check(e.pending() == null && e.f.controller.state().phase == RoomPreferencesController.Phase.CACHED
                && !e.f.controller.state().serverDecisionReady && e.f.floorHeld && e.f.releases.size() == releases, "cancel commits then read-only CACHED, floor held despite cached muted=false");
        check(e.f.gets.size() == gets && e.f.posts.size() == 1 && e.cancels.size() == 1, "cancel settlement no automatic GET or original POST");
        e.f.controller.pause(); e.f.controller.resume(); check(e.f.gets.size() == gets && e.cancels.size() == 1, "resume no transport");
        e.f.controller.refresh(); e.f.queue.drain(); e.f.gets.get(gets).complete(200, snapshot(17, 23, 1)); e.f.queue.drain();
        check(e.f.releases.size() == releases + 1 && !e.f.floorHeld && e.f.controller.state().serverDecisionReady, "only later explicit current GET/Store proof releases floor");
    }
    private static void outcomes() throws Exception {
        Env normal = new Env(0); normal.f.ready(1); normal.f.send(true); RoomPreferencesProtocol.Pending sent = normal.exact(); int releases = normal.f.releases.size();
        normal.f.posts.get(0).complete(200, cancelled(sent)); normal.f.queue.drain();
        check(normal.pending() == null && normal.cancels.isEmpty() && normal.f.releases.size() == releases && normal.f.floorHeld, "late original POST tombstone settles even optional action hidden");
        Env malformed = new Env(); malformed.unknown(true); RoomPreferencesProtocol.Pending p = malformed.exact(); malformed.startCancel();
        malformed.cancels.get(0).complete(200, ack(p).put("cancelled", false)); malformed.f.queue.drain();
        check(malformed.pending() != null && malformed.f.controller.state().code == RoomPreferencesController.Code.INVALID_RESPONSE, "ambiguous valid ACK plus cancelled does not fallback");
        for (boolean muted : new boolean[]{true, false}) {
            Env applied = new Env(); applied.unknown(muted); applied.f.floorHeld = true; RoomPreferencesProtocol.Pending pending = applied.exact(); int before = applied.f.releases.size(); applied.startCancel();
            applied.cancels.get(0).complete(200, ack(pending)); applied.f.queue.drain();
            check(applied.pending() == null && applied.f.controller.state().phase == RoomPreferencesController.Phase.SAVED, "applied cancellation reply uses existing ACK settlement");
            check(applied.f.releases.size() == before + (muted ? 0 : 1), "ACK mute proof semantics unchanged, not cancellation floor release");
        }
    }
    private static void restart() throws Exception {
        Env e = new Env(); RoomPreferencesProtocol.Pending pending = make(e.f, ID, 17, 23, "2000-01-01T00:00:00Z", false);
        disk(() -> e.f.store.stage(pending, 0)); disk(() -> e.f.store.markDispatchStarted(pending));
        e.startCancel(); e.cancels.get(0).complete(0, null); e.f.queue.drain();
        check(e.pending() != null && e.f.controller.state().phase == RoomPreferencesController.Phase.UNKNOWN, "lost cancel reply retains exact started intent");
        e.f.controller.close(); e.install(); e.f.controller.open(); e.f.queue.drain();
        check(e.cancels.size() == 1 && e.f.posts.isEmpty(), "restore/open no automatic original/cancel POST");
        e.f.gets.get(0).complete(200, snapshot(17, 23, 1)); e.f.queue.drain();
        check(e.pending() != null && !e.f.controller.state().serverDecisionReady && e.f.floorHeld, "fresh GET false cannot prove cancellation or expiry");
        e.startCancel(); check(e.payloads.size() == 2 && e.payloads.get(0).equals(e.payloads.get(1)) && e.payloads.get(1).equals(pending.payload), "restart explicit cancel uses original expired payload/UUID bytes");
        e.cancels.get(1).complete(200, cancelled(pending)); e.f.queue.drain(); check(e.pending() == null && e.f.floorHeld, "restart exact cancellation commits without floor release");
    }
    private static void gates() throws Exception {
        Env absent = new Env(0); absent.unknown(true); int lookups = absent.f.context.fileLookups;
        absent.f.controller.cancelStartedExplicit(ID); absent.f.queue.drain(); check(absent.cancels.isEmpty() && absent.f.context.fileLookups == lookups, "unsupported optional action no disk/probing/offline transition");
        ControllerCases.Fixture legacy = new ControllerCases.Fixture(); legacy.binding = version(legacy.binding, 1); legacy.replaceController(); legacy.ready(1); legacy.send(true); legacy.posts.get(0).complete(0, null); legacy.queue.drain();
        legacy.controller.cancelStartedExplicit(ID); legacy.queue.drain(); check(legacy.posts.size() == 1 && legacy.load().state.pending.size() == 1 && legacy.controller.state().phase == RoomPreferencesController.Phase.UNKNOWN, "legacy Host.cancel default false never routes to post");
        Env wrong = new Env(); wrong.unknown(true); wrong.f.controller.cancelStartedExplicit(NEXT); wrong.f.queue.drain(); check(wrong.cancels.isEmpty(), "wrong UUID never cancels");
        for (boolean afterLoad : new boolean[]{false, true}) {
            Env unhealthy = new Env(); unhealthy.unknown(true);
            if (!afterLoad) unhealthy.f.nullCheckpoint = true;
            unhealthy.f.controller.cancelStartedExplicit(ID);
            if (afterLoad) { unhealthy.f.queue.disk(); unhealthy.f.nullCheckpoint = true; }
            unhealthy.f.queue.drain(); check(unhealthy.cancels.isEmpty() && unhealthy.pending() != null, "read-health required before load and final cancel dispatch");
        }
        for (boolean throwing : new boolean[]{false, true}) {
            Env refused = new Env(); refused.unknown(true); refused.accepted = false; refused.throwing = throwing; refused.f.controller.cancelStartedExplicit(ID); refused.f.queue.drain();
            check(refused.pending() != null && refused.f.controller.state().phase == RoomPreferencesController.Phase.UNKNOWN && refused.f.floorHeld, "transport refusal/exception not cancellation proof");
        }
    }
    private static void lifecycle() throws Exception {
        for (boolean close : new boolean[]{false, true}) {
            Env e = new Env(); e.unknown(true); RoomPreferencesProtocol.Pending pending = e.exact(); e.startCancel(); int views = e.f.views.size(), releases = e.f.releases.size();
            if (close) e.f.controller.close(); else e.f.controller.pause();
            e.cancels.get(0).complete(200, cancelled(pending)); e.f.queue.drain();
            check(e.pending() == null && e.f.views.size() == views && e.f.releases.size() == releases && e.f.floorHeld, "valid cancellation settles after pause/close without UI/floor release");
        }
        for (int boundary = 0; boundary < 3; ++boundary) {
            Env e = new Env(); e.unknown(true); RoomPreferencesProtocol.Pending p = e.exact(); e.startCancel(); byte[] before = Files.readAllBytes(e.f.file().toPath()); int views = e.f.views.size();
            e.cancels.get(0).complete(200, cancelled(p));
            if (boundary > 0) e.f.queue.ui();
            if (boundary == 2) e.f.faults.afterFinish = e.f::invalidate; else e.f.invalidate();
            e.f.queue.drain();
            check(boundary == 2 ? e.pending() == null : Arrays.equals(before, Files.readAllBytes(e.f.file().toPath())), "identity invalidation before Store rejects; commit entered valid may finish");
            check(e.f.views.size() == views && e.f.floorHeld, "invalid identity no later presentation or release");
        }
        Env version = new Env(); version.unknown(true); RoomPreferencesProtocol.Pending pending = version.exact(); version.startCancel(); version.f.binding.authority.invalidate();
        RoomPreferencesController.Binding b = version.f.binding;
        version.f.binding = new RoomPreferencesController.Binding(b.account, b.accountIdentity, b.sessionIdentity, new RoomPreferencesController.Authority(), b.globalGeneration, b.repositoryGeneration, b.roomId, b.membershipId, 1, 0);
        version.cancels.get(0).complete(200, cancelled(pending)); version.f.queue.drain(); check(version.pending() != null, "old version-bound callback cannot borrow replacement Binding");
    }
    private static void faultsAndLate() throws Exception {
        Env uncertain = new Env(); uncertain.unknown(true); RoomPreferencesProtocol.Pending p = uncertain.exact(); uncertain.startCancel(); uncertain.f.faults.failAt = uncertain.f.faults.writes + 1;
        uncertain.cancels.get(0).complete(200, cancelled(p)); uncertain.f.queue.drain();
        check(uncertain.f.controller.state().code == RoomPreferencesController.Code.STORAGE_UNCERTAIN && uncertain.pending() != null && uncertain.f.floorHeld, "silent finish never announces cancelled/clears floor");
        Env race = new Env(); race.f.ready(1); race.f.send(true); RoomPreferencesProtocol.Pending old = race.exact();
        race.f.controller.pause(); race.f.controller.resume(); race.startCancel();
        race.f.posts.get(0).complete(200, ack(old)); race.f.queue.drain(); check(race.pending() == null, "late original applied ACK settles exact old intent while cancel outstanding");
        RoomPreferencesProtocol.Pending next = make(race.f, NEXT, 17, 23, null, true); disk(() -> race.f.store.stage(next, race.f.store.load().state.revision));
        byte[] before = Files.readAllBytes(race.f.file().toPath()); race.cancels.get(0).complete(200, cancelled(old)); race.f.queue.drain();
        check(race.pending().pending.clientUuid.equals(NEXT) && Arrays.equals(before, Files.readAllBytes(race.f.file().toPath())), "late opposite terminal receipt cannot erase new operation/cache");
    }
    static int run() throws Exception {
        group("strict-six-field-request-bound-parser", ControllerCancellationCases::protocol);
        group("exact-store-retirement-and-payload-cas", ControllerCancellationCases::store);
        group("explicit-cancel-floor-and-later-get", ControllerCancellationCases::explicitFlow);
        group("exclusive-discriminant-original-and-applied", ControllerCancellationCases::outcomes);
        group("lost-reply-expired-restart-same-bytes", ControllerCancellationCases::restart);
        group("support-health-uuid-transport-gates", ControllerCancellationCases::gates);
        group("pause-close-identity-commit-linearization", ControllerCancellationCases::lifecycle);
        group("uncertain-and-late-opposite-terminal", ControllerCancellationCases::faultsAndLate);
        System.out.println("INVENTORY cancellation-only groups=" + groups + "; actual production Protocol/Store/Controller; declared transport/queue/MutePort/Android/Gson adapters; no old suites or authenticated HTTP claim");
        return checks;
    }
}

package com.baseer.freshchat;

import android.content.Context;
import android.os.Looper;
import android.util.AtomicFile;
import com.baseer.freshchat.sync.AccountScope;
import java.io.*;
import java.lang.ref.WeakReference;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import org.json.JSONObject;

/** Deterministic scheduling/transport fixtures, real production Store and actual JVM files.
 * Looper/Context/AtomicFile/JSON are explicitly JVM adapters; no Android/HTTP/Activity claim. */
public final class ControllerCases {
    private static int checks, fixtures;
    private static File root;
    private static final long ROOM = 17, MEMBER = 23;
    private static final AccountScope ACCOUNT = new AccountScope("https://controller.invalid", "synthetic", 41);
    private static final String UUID = "00000000-0000-4000-8000-000000000001";
    private static final String UUID2 = "00000000-0000-4000-8000-000000000002";
    private static final String STAMP = "2026-10-18T12:00:00Z";
    private static void check(boolean condition, String message) {
        ++checks; if (!condition) throw new AssertionError("Controller check " + checks + ": " + message);
    }
    private static void eq(Object first, Object second, String message) { check(Objects.equals(first, second), message); }
    private static JSONObject json(long member, long revision, String until, boolean forever, boolean pin, boolean archived) throws Exception {
        return new JSONObject().put("api_version", 2).put("room_id", ROOM).put("membership_id", member)
                .put("revision", revision).put("muted_until", until == null ? JSONObject.NULL : until)
                .put("mute_forever", forever).put("muted", forever || until != null)
                .put("pinned", pin).put("pinned_at", pin ? STAMP : JSONObject.NULL).put("archived", archived);
    }
    private static JSONObject ack(String payload, long current, boolean replayed) throws Exception {
        JSONObject input = new JSONObject(payload);
        return json(((Number) input.opt("membership_id")).longValue(), current,
                input.opt("muted_until") == JSONObject.NULL ? null : (String) input.opt("muted_until"),
                (Boolean) input.opt("mute_forever"), (Boolean) input.opt("pinned"), (Boolean) input.opt("archived"))
                .put("client_uuid", input.opt("client_uuid"))
                .put("operation_revision", ((Number) input.opt("expected_revision")).longValue() + 1)
                .put("replayed", replayed);
    }
    private static JSONObject error(String code) throws Exception {
        return new JSONObject().put("error", new JSONObject().put("code", code).put("message", "DO_NOT_EXPOSE_RAW_BODY"));
    }

    static final class Queue implements RoomPreferencesController.Scheduler {
        final ArrayDeque<Runnable> disk = new ArrayDeque<>(), ui = new ArrayDeque<>();
        public void worker(Runnable work) { disk.add(work); }
        public void main(Runnable work) { ui.add(work); }
        public boolean isMain() { return Looper.myLooper() == Looper.getMainLooper(); }
        void disk() { check(!disk.isEmpty(), "Worker work queued"); Looper.mainForTest(false); try { disk.remove().run(); } finally { Looper.mainForTest(true); } }
        void ui() { check(!ui.isEmpty(), "MAIN callback queued"); Looper.mainForTest(true); ui.remove().run(); }
        void drain() { int limit = 100; while (!disk.isEmpty() || !ui.isEmpty()) { if (--limit == 0) throw new AssertionError("Unbounded scheduling"); if (!ui.isEmpty()) ui(); else disk(); } }
    }
    static final class Faults implements RoomPreferencesStore.AtomicFiles {
        int writes, failAt;
        Runnable afterFinish;
        public AtomicFile create(File base) {
            return new AtomicFile(base) {
                @Override public void finishWrite(FileOutputStream stream) {
                    if (++writes == failAt) { try { stream.close(); } catch (IOException ignored) { } }
                    else super.finishWrite(stream);
                    Runnable hook = afterFinish; afterFinish = null; if (hook != null) hook.run();
                }
            };
        }
    }
    static final class Fixture implements RoomPreferencesController.Host, RoomPreferencesController.Observer, RoomPreferencesController.MutePort {
        final Queue queue = new Queue();
        final Context context;
        final Faults faults = new Faults();
        final RoomPreferencesStore store;
        final Object accountIdentity = new Object(), sessionIdentity = new Object();
        RoomPreferencesController.Binding binding;
        RoomPreferencesController controller;
        final List<RoomPreferencesController.Reply> gets = new ArrayList<>(), posts = new ArrayList<>();
        final List<String> payloads = new ArrayList<>();
        final List<RoomPreferencesController.ViewState> views = new ArrayList<>();
        final List<RoomPreferencesController.RestrictionTicket> blocks = new ArrayList<>();
        final List<RoomPreferencesController.DurableProof> releases = new ArrayList<>();
        Object muteCheckpoint = new Object();
        int checkpoints, rejectedReleases;
        boolean floorHeld, nullCheckpoint;
        Object admission;
        static final class Prepared {
            final RoomPreferencesController.Binding binding;
            final RoomPreferencesProtocol.Pending pending;
            final Object checkpoint;
            Prepared(RoomPreferencesController.RestrictionTicket ticket, Object checkpoint) {
                binding = ticket.binding; pending = ticket.pending; this.checkpoint = checkpoint;
            }
        }
        boolean acceptGet = true, acceptPost = true, throwGet, throwPost;
        Fixture() {
            File owned = new File(root, "fixture-" + (++fixtures));
            if (!owned.mkdirs()) throw new AssertionError("Synthetic application files directory required");
            context = new Context(owned);
            store = new RoomPreferencesStore(context, ACCOUNT, faults);
            binding = binding(ACCOUNT, accountIdentity, sessionIdentity, new RoomPreferencesController.Authority(), 1, 1, MEMBER, 1);
            replaceController();
        }
        RoomPreferencesController.Binding binding(AccountScope account, Object identity, Object session,
                RoomPreferencesController.Authority authority, long global, long repository, long member, int version) {
            return new RoomPreferencesController.Binding(account, identity, session, authority, global, repository, ROOM, member, version);
        }
        void replaceController() { controller = new RoomPreferencesController(store, binding, this, queue, this, this); }
        public RoomPreferencesController.Binding currentBinding(long room) { return room == ROOM ? binding : null; }
        public boolean get(RoomPreferencesController.Binding expected, RoomPreferencesController.Reply reply) {
            check(queue.isMain(), "GET final gate on MAIN"); check(expected == binding && binding.authority.valid(), "GET exact current authority");
            if (throwGet) throw new IllegalStateException("PRIVATE_TRANSPORT_FAILURE");
            gets.add(reply); return acceptGet;
        }
        public boolean post(RoomPreferencesController.Binding expected, String payload, RoomPreferencesController.Reply reply) {
            check(queue.isMain(), "POST final gate on MAIN"); check(expected == binding && binding.authority.valid(), "POST exact current authority");
            try {
                String disk = Files.readString(file().toPath());
                check(disk.contains("\"dispatch_started\":true"), "Test-only file inspection: durable started before HTTP fake");
                check(disk.contains(JSONObject.quote(payload)), "Test-only file inspection: exact payload durable before HTTP fake");
            } catch (IOException failure) { throw new AssertionError(failure); }
            if (throwPost) throw new IllegalStateException("PRIVATE_TRANSPORT_FAILURE");
            posts.add(reply); payloads.add(payload); return acceptPost;
        }
        public void changed(RoomPreferencesController.ViewState value) { check(queue.isMain(), "Observer on MAIN"); views.add(value); }
        public Object checkpoint(RoomPreferencesController.Binding value) {
            check(queue.isMain() && value == binding, "Checkpoint read at MAIN dispatch, exact scope"); ++checkpoints; return nullCheckpoint ? null : muteCheckpoint;
        }
        public boolean currentReadHealthy(Object checkpoint, RoomPreferencesController.Binding expected) {
            return !nullCheckpoint && checkpoint == muteCheckpoint && binding == expected && binding.authority.valid();
        }
        public Object prepare(RoomPreferencesController.RestrictionTicket value) {
            check(value.binding == binding && value.binding.authority.valid(), "Floor bound to current identity");
            muteCheckpoint = new Object();
            if (value.pending.muteForever || value.pending.mutedUntil != null) { floorHeld = true; blocks.add(value); }
            admission = new Prepared(value, muteCheckpoint); return admission;
        }
        public boolean currentDurable(Object value, RoomPreferencesController.Binding expected, RoomPreferencesProtocol.Pending pending) {
            if (value != admission || !(value instanceof Prepared)) return false;
            Prepared prepared = (Prepared) value;
            return prepared.binding == expected && expected.authority.valid() && prepared.checkpoint == muteCheckpoint
                    && prepared.pending.clientUuid.equals(pending.clientUuid) && prepared.pending.payload.equals(pending.payload);
        }
        public void release(RoomPreferencesController.DurableProof value) {
            // Deterministic single-MAIN fixture for the future atomic RAM port, not ROUTING/FCM.
            if (value.muteCheckpoint == null || value.muteCheckpoint != muteCheckpoint
                    || value.binding != binding || !value.binding.authority.valid()) { ++rejectedReleases; return; }
            check(value.binding == binding && value.binding.authority.valid() && value.storeRevision > 0 && !value.snapshot.muted,
                    "Release has current binding, durable revision and server-unmuted observation"); floorHeld = false; releases.add(value);
        }
        File file() { return new File(new File(context.getFilesDir(), "bchat-room-preferences"), ACCOUNT.key + ".json"); }
        RoomPreferencesStore.Result load() { Looper.mainForTest(false); try { return store.load(); } finally { Looper.mainForTest(true); } }
        RoomPreferencesStore.Result cache(long member, long revision) throws Exception {
            return cache(json(member, revision, null, false, false, false));
        }
        RoomPreferencesStore.Result cache(JSONObject body) throws Exception {
            RoomPreferencesProtocol.Snapshot snapshot = RoomPreferencesProtocol.freshSnapshot(body, ACCOUNT, ROOM, ((Number) body.opt("membership_id")).longValue());
            Looper.mainForTest(false); try { return store.saveSnapshot(snapshot, store.load().state.revision); } finally { Looper.mainForTest(true); }
        }
        void ready(long revision) throws Exception {
            controller.open(); queue.drain(); eq(gets.size(), 1, "One explicit GET");
            gets.get(0).complete(200, json(MEMBER, revision, null, false, false, false)); queue.drain();
            check(controller.state().serverDecisionReady, "Only current GET plus durable snapshot enables new intent");
            check(!load().state.snapshot(ROOM).freshGet, "Disk snapshot never fresh");
        }
        void send(boolean muted) {
            controller.submit(UUID, null, muted, false, false); queue.drain(); eq(posts.size(), 1, "One explicit POST");
        }
        void invalidate() { binding.authority.invalidate(); }
    }

    private static void basics() throws Exception {
        Fixture fixture = new Fixture();
        check(fixture.context.fileLookups == 0 && fixture.queue.disk.isEmpty(), "Controller/Store constructors no disk or async work");
        Looper.mainForTest(false);
        try { fixture.controller.open(); throw new AssertionError("Worker entry accepted"); }
        catch (IllegalStateException expected) { check(fixture.context.fileLookups == 0, "Reject MAIN contract before file lookup"); }
        finally { Looper.mainForTest(true); }
        fixture.controller.open(); fixture.queue.drain();
        eq(fixture.controller.state().phase, RoomPreferencesController.Phase.CACHED, "Absent is read-only while GET outstanding");
        check(!fixture.controller.state().serverDecisionReady && fixture.releases.isEmpty(), "Absent is not authenticated unmute");
        fixture.gets.get(0).complete(200, json(MEMBER, 3, null, false, false, false)); fixture.queue.drain();
        check(fixture.controller.state().serverDecisionReady && fixture.releases.size() == 1, "Fresh GET durable proof only after save");
        eq(fixture.releases.get(0).reason, RoomPreferencesController.ProofReason.CURRENT_GET_COMMITTED, "GET proof reason");
        Fixture unsupported = new Fixture(); unsupported.binding = unsupported.binding(ACCOUNT, unsupported.accountIdentity, unsupported.sessionIdentity,
                new RoomPreferencesController.Authority(), 1, 1, MEMBER, 2); unsupported.replaceController(); unsupported.controller.open();
        check(unsupported.gets.isEmpty() && unsupported.context.fileLookups == 0, "Unsupported version no I/O or probing");
        for (String field : new String[]{"host", "observer", "mute"})
            eq(RoomPreferencesController.class.getDeclaredField(field).getType(), WeakReference.class, "Weak port: " + field);
    }

    private static void staleGets() throws Exception {
        Fixture fixture = new Fixture(); fixture.controller.open(); fixture.queue.drain();
        fixture.controller.pause(); int observed = fixture.views.size();
        fixture.gets.get(0).complete(200, json(MEMBER, 3, null, false, false, false)); fixture.queue.drain();
        check(fixture.load().kind == RoomPreferencesStore.Kind.ABSENT && fixture.views.size() == observed, "Paused GET cannot save or draw");
        fixture.controller.resume(); check(fixture.gets.size() == 1 && !fixture.controller.state().serverDecisionReady, "Resume no auto GET/freshness");
        fixture.controller.refresh(); fixture.queue.drain(); fixture.gets.get(1).complete(200, json(MEMBER, 4, null, false, false, false)); fixture.queue.drain();
        check(fixture.controller.state().serverDecisionReady && fixture.controller.state().snapshot.revision == 4, "Explicit new GET obtains fresh state");
        Fixture bad = new Fixture(); bad.controller.open(); bad.queue.drain(); bad.gets.get(0).complete(200, error("private_server_error")); bad.queue.drain();
        check(!bad.controller.state().serverDecisionReady && bad.load().kind == RoomPreferencesStore.Kind.ABSENT, "Invalid GET never stored or writable");
        Fixture higher = new Fixture(); higher.cache(MEMBER, 9); higher.controller.open(); higher.queue.drain();
        higher.gets.get(0).complete(200, json(MEMBER, 8, null, false, false, false)); higher.queue.drain();
        check(higher.controller.state().snapshot.revision == 9 && !higher.controller.state().serverDecisionReady && higher.releases.isEmpty(), "Older GET displays newer cache without freshness/release");
        Fixture conflict = new Fixture(); conflict.controller.open(); conflict.queue.drain(); conflict.cache(MEMBER, 6);
        conflict.gets.get(0).complete(200, json(MEMBER, 7, null, false, false, false)); conflict.queue.drain();
        check(!conflict.controller.state().serverDecisionReady && conflict.controller.state().code == RoomPreferencesController.Code.STORAGE_CONFLICT, "GET save CAS failure no write authority");
        Fixture epoch = new Fixture(); epoch.cache(MEMBER + 1, 2); epoch.controller.open(); epoch.queue.drain();
        epoch.gets.get(0).complete(200, json(MEMBER, 3, null, false, false, false)); epoch.queue.drain();
        check(!epoch.controller.state().serverDecisionReady && epoch.controller.state().code == RoomPreferencesController.Code.MEMBERSHIP_CHANGED, "No implicit cache epoch reconciliation");
    }

    private static void dispatchOrdering() throws Exception {
        Fixture fixture = new Fixture(); fixture.ready(3); int floors = fixture.blocks.size();
        fixture.controller.submit(UUID, null, true, false, false);
        check(fixture.blocks.size() == floors + 1 && fixture.posts.isEmpty(), "Mute floor immediate before worker/HTTP");
        fixture.queue.disk(); check(fixture.posts.isEmpty(), "Stage commit alone no dispatch"); fixture.queue.ui();
        fixture.queue.disk(); check(fixture.posts.isEmpty() && fixture.load().state.operation(ROOM, MEMBER).dispatchStarted, "Started durable before dispatch callback");
        fixture.queue.ui(); check(fixture.posts.size() == 1, "POST only after two commits");
        String exact = fixture.payloads.get(0); fixture.posts.get(0).complete(0, null); fixture.queue.drain();
        eq(fixture.controller.state().phase, RoomPreferencesController.Phase.UNKNOWN, "Timeout remains unknown");
        int released = fixture.releases.size(); fixture.controller.pause(); fixture.controller.resume();
        check(fixture.releases.size() == released && fixture.posts.size() == 1, "Pause/resume no retry or unmute");
        fixture.controller.close(); fixture.replaceController(); fixture.controller.open(); fixture.queue.drain();
        check(fixture.posts.size() == 1 && fixture.blocks.size() > floors + 1, "Restore floor, never auto POST");
        fixture.gets.get(1).complete(200, json(MEMBER, 3, null, false, false, false)); fixture.queue.drain();
        check(!fixture.controller.state().serverDecisionReady && fixture.releases.size() == released, "GET unmuted cannot lift unknown pending floor");
        fixture.controller.retryExplicit(UUID2); fixture.queue.drain(); check(fixture.posts.size() == 1, "Wrong UUID no retry grant");
        fixture.controller.retryExplicit(UUID); fixture.queue.drain();
        check(fixture.posts.size() == 2 && exact.equals(fixture.payloads.get(1)), "Explicit started retry exact UUID/payload, no rebase");
        fixture.posts.get(1).complete(200, ack(exact, 4, true)); fixture.queue.drain();
        check(fixture.load().state.pending.isEmpty() && fixture.controller.state().phase == RoomPreferencesController.Phase.SAVED, "ACK commits before saved");
        check(fixture.releases.size() == released, "Muted ACK never unmute");
        byte[] before = Files.readAllBytes(fixture.file().toPath()); fixture.posts.get(1).complete(200, ack(exact, 4, true)); fixture.queue.drain();
        check(Arrays.equals(before, Files.readAllBytes(fixture.file().toPath())), "Duplicate callback no disk mutation");
    }

    private static void viewFences() throws Exception {
        for (boolean afterStarted : new boolean[]{false, true}) {
            Fixture fixture = new Fixture(); fixture.ready(2); fixture.controller.submit(UUID, null, true, false, false);
            fixture.queue.disk();
            if (afterStarted) { fixture.queue.ui(); fixture.queue.disk(); }
            fixture.controller.close(); fixture.queue.drain();
            RoomPreferencesStore.Operation pending = fixture.load().state.operation(ROOM, MEMBER);
            check(pending != null && pending.dispatchStarted == afterStarted && fixture.posts.isEmpty(), "Close preserves staged flags and bars late HTTP");
            fixture.replaceController(); fixture.controller.retryExplicit(UUID); fixture.queue.drain();
            check(fixture.posts.size() == 1, "Explicit loaded unsent/started path only");
        }
        Fixture closed = new Fixture(); closed.ready(2); closed.send(false); int oldViews = closed.views.size(), oldRelease = closed.releases.size();
        closed.controller.close(); closed.posts.get(0).complete(200, ack(closed.payloads.get(0), 3, false)); closed.queue.drain();
        check(closed.load().state.pending.isEmpty() && closed.views.size() == oldViews, "Sent ACK settles after close without UI retention/update");
        check(closed.releases.size() == oldRelease + 1 && closed.releases.get(oldRelease).reason == RoomPreferencesController.ProofReason.MATCHED_ACK_COMMITTED,
                "Close itself no release; matched durable ACK proof may release");
        Fixture oldView = new Fixture(); oldView.ready(2); oldView.send(false); oldView.controller.pause(); oldView.controller.resume();
        oldView.posts.get(0).complete(200, ack(oldView.payloads.get(0), 3, false)); oldView.queue.drain();
        check(oldView.load().state.pending.isEmpty() && oldView.controller.state().phase != RoomPreferencesController.Phase.SAVED, "Old sent ACK cannot present saved on new view ticket");
    }

    private static void authorityFences() throws Exception {
        for (int boundary = 0; boundary < 3; boundary++) {
            Fixture fixture = new Fixture(); fixture.ready(2); fixture.send(false); int seen = fixture.views.size(), released = fixture.releases.size();
            if (boundary == 0) fixture.invalidate();
            fixture.posts.get(0).complete(200, ack(fixture.payloads.get(0), 3, false));
            if (boundary == 1) { fixture.queue.ui(); fixture.invalidate(); }
            if (boundary == 2) { fixture.queue.ui(); fixture.queue.disk(); fixture.invalidate(); }
            fixture.queue.drain();
            check(fixture.load().state.pending.isEmpty() == (boundary == 2), "Store-entry linearization boundary " + boundary);
            check(fixture.views.size() == seen && fixture.releases.size() == released, "Revoked identity no UI/RAM release " + boundary);
        }
        for (int changed = 0; changed < 7; changed++) {
            Fixture fixture = new Fixture(); fixture.ready(2);
            RoomPreferencesController.Binding old = fixture.binding;
            fixture.binding = fixture.binding(changed == 0 ? new AccountScope(ACCOUNT.origin, ACCOUNT.database, ACCOUNT.userId) : ACCOUNT,
                    changed == 1 ? new Object() : old.accountIdentity, changed == 2 ? new Object() : old.sessionIdentity,
                    old.authority, changed == 3 ? 2 : 1, changed == 4 ? 2 : 1, changed == 5 ? MEMBER + 1 : MEMBER, changed == 6 ? 2 : 1);
            fixture.controller.submit(UUID, null, true, false, false); fixture.queue.drain();
            check(fixture.posts.isEmpty() && fixture.load().state.pending.isEmpty(), "Binding identity/session/global/repository/epoch/contract fence " + changed);
        }
    }

    private static void failedCommitsAndDenials() throws Exception {
        for (int failed : new int[]{2, 3}) {
            Fixture fixture = new Fixture(); fixture.ready(2); int released = fixture.releases.size(); fixture.faults.failAt = failed;
            fixture.controller.submit(UUID, null, true, false, false); fixture.queue.drain();
            check(fixture.posts.isEmpty() && fixture.controller.state().code == RoomPreferencesController.Code.STORAGE_UNCERTAIN,
                    "Silent finish stage/started failure never grants HTTP");
            check(fixture.blocks.size() == 1 && fixture.releases.size() == released, "Storage uncertainty keeps temporary restrictive floor");
        }
        for (String code : new String[]{"revision_conflict", "membership_changed", "unknown_private_code", "permission_denied"}) {
            Fixture fixture = new Fixture(); fixture.ready(2); fixture.send(false);
            fixture.posts.get(0).complete(code.equals("permission_denied") ? 403 : 409, error(code)); fixture.queue.drain();
            RoomPreferencesStore.Operation pending = fixture.load().state.operation(ROOM, MEMBER);
            check(pending != null && pending.dispatchStarted && !pending.blockedCode.isEmpty(), "Denial preserves exact started operation");
            check(!fixture.controller.state().serverDecisionReady && fixture.controller.state().phase == RoomPreferencesController.Phase.BLOCKED, "Denied no replace/overwrite");
            fixture.controller.retryExplicit(UUID); fixture.queue.drain(); check(fixture.posts.size() == 1, "Blocked not retryable");
            check(!Files.readString(fixture.file().toPath()).contains("DO_NOT_EXPOSE_RAW_BODY"), "Only allowlisted codes persisted");
        }
    }

    private static void replayAndValidation() throws Exception {
        Fixture replay = new Fixture(); replay.ready(2); replay.send(true);
        JSONObject later = json(MEMBER, 8, null, false, false, true).put("client_uuid", UUID).put("operation_revision", 3).put("replayed", true);
        replay.posts.get(0).complete(200, later); replay.queue.drain();
        check(replay.load().state.pending.isEmpty() && replay.controller.state().snapshot.revision == 8 && replay.controller.state().snapshot.archived,
                "Higher replay settles UUID and displays current server state");
        Fixture newer = new Fixture(); newer.ready(2); newer.send(false); newer.cache(MEMBER, 9);
        newer.posts.get(0).complete(200, ack(newer.payloads.get(0), 3, true)); newer.queue.drain();
        check(newer.load().state.snapshot(ROOM).revision == 9 && newer.load().state.pending.isEmpty(), "ACK cannot roll back newer stored snapshot");
        Fixture invalid = new Fixture(); invalid.ready(2); invalid.send(false);
        invalid.posts.get(0).complete(200, ack(invalid.payloads.get(0), 3, false).put("client_uuid", UUID2)); invalid.queue.drain();
        check(invalid.load().state.pending.size() == 1 && invalid.controller.state().phase == RoomPreferencesController.Phase.UNKNOWN,
                "Wrong UUID 200 remains unknown, never saved");
        Fixture noGet = new Fixture(); noGet.acceptGet = false; noGet.controller.open(); noGet.queue.drain();
        check(!noGet.controller.state().serverDecisionReady && noGet.controller.state().code == RoomPreferencesController.Code.REQUEST_UNKNOWN, "Rejected transport GET no fresh snapshot");
        Fixture noPost = new Fixture(); noPost.ready(2); noPost.acceptPost = false; noPost.send(false);
        check(noPost.controller.state().phase == RoomPreferencesController.Phase.UNKNOWN && noPost.load().state.pending.get(0).dispatchStarted,
                "Transport refusal after started remains conservative unknown");
    }

    private static void additionalFences() throws Exception {
        for (int status : new int[]{403, 409}) {
            Fixture denied = new Fixture(); denied.ready(2); denied.send(true);
            denied.posts.get(0).complete(0, null); denied.queue.drain();
            denied.controller.refresh(); denied.queue.drain(); denied.gets.get(1).complete(status, error("membership_changed")); denied.queue.drain();
            check(!denied.load().state.operation(ROOM, MEMBER).blockedCode.isEmpty(), "GET denial blocks already-persisted intent");
            denied.controller.retryExplicit(UUID); denied.queue.drain(); check(denied.posts.size() == 1, "GET denial cannot be bypassed by explicit retry");
        }
        Fixture corrupt = new Fixture(); File metadata = corrupt.file(); Files.createDirectories(metadata.getParentFile().toPath());
        Files.writeString(metadata.toPath(), "{broken"); corrupt.controller.open(); corrupt.queue.drain();
        check(corrupt.gets.isEmpty() && corrupt.posts.isEmpty() && !corrupt.controller.state().serverDecisionReady, "Corrupt store neither overwritten nor bypassed");
        eq(Files.readString(metadata.toPath()), "{broken", "Corrupt bytes retained");
        Fixture collected = new Fixture(); collected.ready(2);
        java.lang.reflect.Field weak = RoomPreferencesController.class.getDeclaredField("host"); weak.setAccessible(true);
        ((WeakReference<?>) weak.get(collected.controller)).clear();
        collected.controller.submit(UUID, null, true, false, false); collected.queue.drain();
        check(collected.posts.isEmpty() && collected.load().state.pending.isEmpty(), "Missing weak Host grants no authority");
        Fixture observer = new Fixture(); observer.ready(2); observer.send(false); int views = observer.views.size();
        weak = RoomPreferencesController.class.getDeclaredField("observer"); weak.setAccessible(true);
        ((WeakReference<?>) weak.get(observer.controller)).clear();
        observer.posts.get(0).complete(200, ack(observer.payloads.get(0), 3, false)); observer.queue.drain();
        check(observer.load().state.pending.isEmpty() && observer.views.size() == views, "Missing observer does not prevent valid durable settlement");
        Fixture throwingGet = new Fixture(); throwingGet.throwGet = true; throwingGet.controller.open(); throwingGet.queue.drain();
        eq(throwingGet.controller.state().code, RoomPreferencesController.Code.REQUEST_UNKNOWN, "Throwing Host maps to allowlisted error");
        Fixture throwingPost = new Fixture(); throwingPost.ready(2); throwingPost.throwPost = true;
        throwingPost.controller.submit(UUID, null, false, false, false); throwingPost.queue.drain();
        check(throwingPost.load().state.pending.get(0).dispatchStarted && throwingPost.controller.state().phase == RoomPreferencesController.Phase.UNKNOWN,
                "Throwing transport after persisted started never cancels operation");
    }

    private static void crossControllerMuteFence() throws Exception {
        Fixture fixture = new Fixture(); fixture.ready(2);
        RoomPreferencesController first = fixture.controller;
        check(fixture.checkpoints == 1, "Checkpoint taken at GET dispatch, not construction/load");
        fixture.replaceController(); RoomPreferencesController second = fixture.controller;
        second.open(); fixture.queue.drain(); fixture.gets.get(1).complete(200, json(MEMBER, 2, null, false, false, false)); fixture.queue.drain();
        check(second.state().serverDecisionReady, "Independent second controller has a current observation");
        first.submit(UUID, null, false, false, false); fixture.queue.drain();
        check(fixture.checkpoints == 3, "POST checkpoint taken only after both commits");
        int released = fixture.releases.size();
        fixture.posts.get(0).complete(200, ack(fixture.payloads.get(0), 3, false));
        fixture.queue.ui(); fixture.queue.disk(); // Exact ACK is committed; MAIN publication not run yet.
        second.submit(UUID2, null, true, false, false); // Fresh conservative floor, even if later disk CAS conflicts.
        check(fixture.blocks.size() == 1, "Another controller restricts immediately in commit/publication gap");
        fixture.queue.drain();
        check(fixture.releases.size() == released && fixture.rejectedReleases == 1,
                "Atomic port rejects old proof after another controller changed checkpoint");
        check(fixture.load().state.pending.isEmpty() && fixture.posts.size() == 1,
                "New floor is not proof of another write; failed CAS no POST/no intent overwrite");
        Fixture absent = new Fixture(); absent.nullCheckpoint = true; absent.controller.open(); absent.queue.drain();
        absent.gets.get(0).complete(200, json(MEMBER, 2, null, false, false, false)); absent.queue.drain();
        check(absent.releases.isEmpty() && !absent.controller.state().serverDecisionReady, "Missing checkpoint is no release or new-intent permission");
    }

    private static void ackProofMatrix() throws Exception {
        // First row is the precise RED: expected1, ACK2 muted=true, newer GET3 false
        // persisted through real Store while pending. The GET fixture is not HTTP/auth proof.
        String[] labels = {"mute ACK / newer false", "unmute ACK / newer true", "unmute ACK / newer false",
                "equal derived ACKtrue cachefalse", "equal derived ACKfalse cachetrue", "equal false proof",
                "current unmute ACK", "replay current unmute"};
        for (int index = 0; index < labels.length; index++) {
            Fixture fixture = new Fixture(); fixture.ready(1);
            fixture.floorHeld = true; // Declared RAM-port fixture: an existing conservative floor.
            boolean timed = index >= 3 && index <= 5;
            boolean requestMute = index == 0 || index == 7;
            fixture.controller.submit(UUID, timed ? STAMP : null, requestMute, false, false); fixture.queue.drain();
            eq(fixture.posts.size(), 1, "One explicit POST: " + labels[index]);
            String payload = fixture.payloads.get(0);
            long ackRevision = index == 7 ? 5 : 2;
            JSONObject receipt = index == 7
                    ? json(MEMBER, 5, null, false, false, false).put("client_uuid", UUID).put("operation_revision", 2).put("replayed", true)
                    : ack(payload, 2, false);
            if (index == 4 || index == 5) receipt.put("muted", false);
            if (index <= 5) {
                JSONObject cached = timed ? json(MEMBER, 2, STAMP, false, false, false).put("muted", index == 4)
                        : json(MEMBER, 3, null, index == 1, false, false);
                eq(fixture.cache(cached).kind, RoomPreferencesStore.Kind.COMMITTED, "Server-shaped GET cache persisted while pending");
                check(fixture.load().state.pending.size() == 1 && fixture.floorHeld, "GET cache is not permission to remove pending floor");
            }
            int released = fixture.releases.size(), getCount = fixture.gets.size();
            fixture.posts.get(0).complete(200, receipt); fixture.queue.drain();
            boolean mayRelease = index >= 5;
            check(fixture.load().state.pending.isEmpty(), "Exact ACK retires intent independently of release: " + labels[index]);
            check(fixture.releases.size() == released + (mayRelease ? 1 : 0), "No borrowed cache ACK mute proof: " + labels[index]);
            check(fixture.floorHeld != mayRelease && fixture.gets.size() == getCount, "Floor conservative; no automatic recovery GET: " + labels[index]);
            if (mayRelease) {
                RoomPreferencesController.DurableProof proof = fixture.releases.get(released);
                check(proof.snapshot != fixture.controller.state().snapshot && !proof.snapshot.muted
                        && proof.snapshot.revision == ackRevision && proof.snapshot.revision == fixture.controller.state().snapshot.revision,
                        "Proof carries actual ACK snapshot, not selected cache");
                check(proof.binding == fixture.binding && proof.binding.account == ACCOUNT && proof.binding.roomId == ROOM
                        && proof.binding.membershipId == MEMBER && proof.clientUuid.equals(UUID)
                        && proof.reason == RoomPreferencesController.ProofReason.MATCHED_ACK_COMMITTED
                        && proof.muteCheckpoint == fixture.muteCheckpoint, "ACK proof scope/UUID/checkpoint exact");
            } else if (index == 0) {
                fixture.controller.refresh(); fixture.queue.drain(); fixture.gets.get(getCount).complete(200, json(MEMBER, 3, null, false, false, false)); fixture.queue.drain();
                check(!fixture.floorHeld && fixture.releases.size() == released + 1,
                        "Only explicit current fresh GET after settlement may now release");
            }
        }
        for (int fence = 0; fence < 3; fence++) {
            Fixture fixture = new Fixture(); fixture.ready(1); fixture.floorHeld = true;
            if (fence == 0) fixture.nullCheckpoint = true;
            fixture.send(false); int released = fixture.releases.size(), observed = fixture.views.size();
            fixture.posts.get(0).complete(200, ack(fixture.payloads.get(0), 2, false));
            fixture.queue.ui(); fixture.queue.disk(); // ACK committed before final effect gate.
            if (fence == 1) fixture.muteCheckpoint = new Object(); // Another RAM floor's newer checkpoint.
            if (fence == 2) fixture.invalidate();
            fixture.queue.drain();
            check(fixture.load().state.pending.isEmpty() && fixture.releases.size() == released && fixture.floorHeld,
                    "Missing/newer checkpoint or invalid Authority preserves floor: " + fence);
            if (fence == 2) check(fixture.views.size() == observed, "No UI effects after invalidated authority");
        }
    }

    public static void main(String[] args) throws Exception {
        root = new File(args[0]); Files.createDirectories(root.toPath()); Looper.mainForTest(true);
        int recovery = 0;
        if (args.length > 1 && args[1].equals("cancellation")) recovery = ControllerCancellationCases.run();
        else if (args.length > 1 && args[1].equals("recovery")) recovery = ControllerRecoveryCases.run();
        else if (args.length > 1 && args[1].equals("ack-proof")) ackProofMatrix();
        else { basics(); staleGets(); dispatchOrdering(); viewFences(); authorityFences(); failedCommitsAndDenials(); replayAndValidation(); additionalFences(); crossControllerMuteFence(); ackProofMatrix(); recovery = ControllerRecoveryCases.run(); }
        checks += recovery;
        System.out.println("PASS " + checks + " production RoomPreferencesController assertions with actual Store/JVM files; declared queue/transport/Android/JSON adapters; no Android/HTTP/FCM/Activity claim");
    }
    static void componentRoot(File owned) { root = owned; checks = 0; fixtures = 0; }
    static int fixtureChecks() { return checks; }
}

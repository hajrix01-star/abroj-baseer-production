package com.baseer.freshchat;

import android.os.Looper;
import java.lang.ref.WeakReference;
import java.nio.file.Files;
import java.util.Arrays;
import org.json.JSONObject;

/** Actual production Controller/Store files; deterministic queue/transport and Android/JSON
 * adapters, not authenticated HTTP, Android UI, index wiring, FCM or recovery after restart. */
final class ControllerRecoveryCases {
    private static int checks;
    private static final String OLD = "00000000-0000-4000-8000-000000000001";
    private static final String NEXT = "00000000-0000-4000-8000-000000000002";
    private static void check(boolean value, String message) { ++checks; if (!value) throw new AssertionError("Controller recovery " + checks + ": " + message); }
    private static JSONObject body(long revision, boolean muted) throws Exception {
        return new JSONObject().put("api_version", 2).put("room_id", 17).put("membership_id", 23).put("revision", revision)
                .put("muted_until", JSONObject.NULL).put("mute_forever", muted).put("muted", muted)
                .put("pinned", false).put("pinned_at", JSONObject.NULL).put("archived", false);
    }
    private static JSONObject error() throws Exception {
        return new JSONObject().put("api_version", 2).put("error", new JSONObject().put("code", "revision_conflict").put("message", "PRIVATE-NOT-PUBLISHED"));
    }
    private static ControllerCases.Fixture rejected(JSONObject response) throws Exception {
        ControllerCases.Fixture f = new ControllerCases.Fixture(); f.ready(1); f.send(true);
        f.posts.get(0).complete(409, response); f.queue.drain(); return f;
    }
    private static ControllerCases.Fixture review() throws Exception {
        ControllerCases.Fixture f = rejected(error()); review(f, 3); return f;
    }
    private static void review(ControllerCases.Fixture f, long revision) throws Exception {
        int count = f.gets.size(); f.controller.refreshConflictExplicit(OLD); f.queue.drain();
        check(f.gets.size() == count + 1, "Only explicit live rejection handoff dispatches review GET");
        f.gets.get(count).complete(200, body(revision, false)); f.queue.drain();
    }
    private static RoomPreferencesProtocol.Pending pending(ControllerCases.Fixture f) {
        boolean main = Looper.myLooper() == Looper.getMainLooper(); Looper.mainForTest(false);
        try { return f.store.load().state.operation(17, 23).pending; } finally { Looper.mainForTest(main); }
    }
    private static void replace(ControllerCases.Fixture f) { f.controller.replaceRejectedExplicit(NEXT, null, false, false, true); f.queue.drain(); }
    static int run() throws Exception {
        checks = 0; success(); proofBoundary(); observation(); lifecycle(); cancellation(); failures(); reviewHint();
        return checks;
    }
    private static void success() throws Exception {
        ControllerCases.Fixture f = review();
        check(f.controller.state().phase == RoomPreferencesController.Phase.REVIEW_READY && !f.controller.state().serverDecisionReady,
                "Actual review GET is separate from ordinary freshness/index/UI readiness");
        String original = f.payloads.get(0); int release = f.releases.size(), get = f.gets.size();
        f.controller.replaceRejectedExplicit(OLD, null, false, false, false); f.queue.drain();
        check(f.posts.size() == 1 && pending(f).payload.equals(original), "Replacement cannot reuse old UUID or mutate old bytes");
        replace(f);
        JSONObject next = new JSONObject(f.payloads.get(1));
        check(f.posts.size() == 2 && NEXT.equals(next.opt("client_uuid")) && ((Number) next.opt("expected_revision")).longValue() == 3,
                "Explicit new decision dispatches new UUID at ACTUAL GET revision");
        check(f.load().state.operation(17, 23).dispatchStarted && f.load().state.operation(17, 23).blockedCode.isEmpty(), "Replacement committed then markStarted committed before HTTP fake");
        check(f.gets.size() == get && f.floorHeld && f.releases.size() == release, "No automatic GET/unmute from replacement or new unmute payload");
        f.posts.get(0).complete(200, body(2, true).put("client_uuid", OLD).put("operation_revision", 2).put("replayed", false)); f.queue.drain();
        check(pending(f).clientUuid.equals(NEXT) && original.equals(f.payloads.get(0)), "Duplicate old callback cannot settle new UUID");
        f.posts.get(1).complete(200, body(4, false).put("archived", true).put("client_uuid", NEXT).put("operation_revision", 4).put("replayed", false)); f.queue.drain();
        check(f.load().state.pending.isEmpty() && f.controller.state().phase == RoomPreferencesController.Phase.SAVED, "Exact new ACK settles normally after Store commit");
        check(f.releases.size() == release + 1 && f.releases.get(release).snapshot.revision == 4, "Only new ACK proof, not review/cancellation, may release");
        ControllerCases.Fixture expiry = rejected(error());
        String oldPayload = pending(expiry).payload;
        expiry.controller.refreshConflictExplicit(OLD); expiry.queue.drain();
        expiry.gets.get(1).complete(200, body(3, false).put("muted_until", "2000-01-01T00:00:00Z")); expiry.queue.drain();
        expiry.controller.replaceRejectedExplicit(NEXT, "2000-01-01T00:00:00Z", false, true, false); expiry.queue.drain();
        check(new JSONObject(expiry.payloads.get(1)).opt("muted_until") == JSONObject.NULL && oldPayload.equals(expiry.payloads.get(0)),
                "Only NEW explicit payload normalizes inherited expiry using actual server-muted=false, never old retry bytes/device clock");
    }
    private static void proofBoundary() throws Exception {
        for (Object version : new Object[]{JSONObject.NULL, "2", 2.0, true, 1, 3}) {
            JSONObject response = error(); if (version == JSONObject.NULL) response.remove("api_version"); else response.put("api_version", version);
            ControllerCases.Fixture f = rejected(response); int gets = f.gets.size();
            f.controller.refreshConflictExplicit(OLD); replace(f);
            check(f.gets.size() == gets && f.posts.size() == 1 && pending(f).clientUuid.equals(OLD), "Wrong/missing native API type cannot create rejection authority: " + version);
        }
        for (String code : new String[]{"idempotency_conflict", "request_unknown", "membership_changed", "revision_conflict "}) {
            ControllerCases.Fixture f = rejected(error().put("error", new JSONObject().put("code", code)));
            f.controller.refreshConflictExplicit(OLD); replace(f);
            check(f.gets.size() == 1 && f.posts.size() == 1, "Other rejection code never replace/unblock: " + code);
        }
        ControllerCases.Fixture restored = rejected(error()); restored.controller.close(); restored.replaceController();
        restored.controller.open(); restored.queue.drain(); restored.gets.get(1).complete(200, body(5, false)); restored.queue.drain();
        restored.controller.refreshConflictExplicit(OLD); restored.controller.retryExplicit(OLD); replace(restored);
        check(restored.gets.size() == 2 && restored.posts.size() == 1 && pending(restored).clientUuid.equals(OLD), "Stored revision_conflict plus actual GET cannot restore HTTP proof or allow blocked POST");
        ControllerCases.Fixture fabricated = new ControllerCases.Fixture(); fabricated.ready(1); fabricated.send(true);
        fabricated.posts.get(0).complete(0, null); fabricated.queue.drain();
        Looper.mainForTest(false); try { fabricated.store.markBlocked(pending(fabricated), "revision_conflict"); } finally { Looper.mainForTest(true); }
        fabricated.controller.refreshConflictExplicit(OLD); replace(fabricated);
        check(fabricated.gets.size() == 1 && fabricated.posts.size() == 1, "Local blockedCode alone is not an authenticated rejection");
        ControllerCases.Fixture wrongUuid = rejected(error()); wrongUuid.controller.refreshConflictExplicit(NEXT); wrongUuid.queue.drain();
        check(wrongUuid.gets.size() == 1, "Proof exact UUID required at handoff");
    }
    private static void observation() throws Exception {
        for (long actual : new long[]{1, 2, 8}) {
            ControllerCases.Fixture f = rejected(error());
            if (actual == 8) f.cache(23, 9);
            review(f, actual); int before = f.posts.size(); replace(f);
            check(actual == 2 ? f.posts.size() == before + 1 : f.posts.size() == before,
                    "Only actual higher-than-old GET without higher selected cache authorizes replacement: " + actual);
            if (actual == 8) check(f.controller.state().snapshot.revision == 9 && pending(f).clientUuid.equals(OLD), "Do not borrow higher cache or downgrade it");
        }
        ControllerCases.Fixture oldReply = rejected(error());
        oldReply.controller.refreshConflictExplicit(OLD); oldReply.queue.drain();
        oldReply.gets.get(1).complete(200, body(4, false).put("membership_id", 24)); oldReply.queue.drain(); replace(oldReply);
        check(oldReply.posts.size() == 1 && pending(oldReply).clientUuid.equals(OLD), "Wrong GET epoch cannot manufacture FreshDecision");
        ControllerCases.Fixture cas = review(); cas.cache(23, 7); replace(cas);
        check(cas.posts.size() == 1 && pending(cas).clientUuid.equals(OLD) && cas.controller.state().code == RoomPreferencesController.Code.STORAGE_CONFLICT,
                "Concurrent cache/store revision changes reject atomic replace, never stale POST");
        // A failed local CAS retains only this live rejection; user must GET again explicitly.
        review(cas, 8); replace(cas);
        check(cas.posts.size() == 2 && ((Number) new JSONObject(cas.payloads.get(1)).opt("expected_revision")).longValue() == 8,
                "Recovery from local CAS failure requires another explicit actual GET/choice");
        ControllerCases.Fixture competing = review(); RoomPreferencesProtocol.Pending old = pending(competing);
        RoomPreferencesProtocol.Snapshot fresh = RoomPreferencesProtocol.freshSnapshot(body(3, false), competing.binding.account, 17, 23);
        RoomPreferencesProtocol.Pending other = RoomPreferencesProtocol.newPending(fresh, "00000000-0000-4000-8000-000000000003", null, false, false, false);
        Looper.mainForTest(false); try { competing.store.replaceExactRejected(old, fresh, other, competing.store.load().state.revision); } finally { Looper.mainForTest(true); }
        replace(competing);
        check(competing.posts.size() == 1 && pending(competing).payload.equals(other.payload), "Competing replacement wins exact CAS; stale Controller cannot overwrite it");
    }
    private static void lifecycle() throws Exception {
        for (boolean afterGet : new boolean[]{false, true}) for (int action = 0; action < 4; action++) {
            ControllerCases.Fixture f = afterGet ? review() : rejected(error());
            if (action == 0) { f.controller.pause(); f.controller.resume(); }
            else if (action == 1) { f.controller.close(); f.replaceController(); }
            else if (action == 2) { f.controller.refresh(); f.queue.drain(); f.gets.get(f.gets.size() - 1).complete(200, body(6, false)); f.queue.drain(); }
            else f.invalidate();
            int gets = f.gets.size(); f.controller.refreshConflictExplicit(OLD); replace(f);
            check(f.gets.size() == gets && f.posts.size() == 1, "No proof survives pause/close/ordinary refresh/identity: " + afterGet + "/" + action);
        }
        ControllerCases.Fixture late = new ControllerCases.Fixture(); late.ready(1); late.send(true);
        late.controller.pause(); late.posts.get(0).complete(409, error()); late.queue.drain(); late.controller.resume();
        late.controller.refreshConflictExplicit(OLD); replace(late);
        check(late.gets.size() == 1 && late.posts.size() == 1, "Late valid 409 may persist marker, never create new-view authority");
        ControllerCases.Fixture get = rejected(error()); get.controller.refreshConflictExplicit(OLD); get.queue.drain();
        get.controller.pause(); get.gets.get(1).complete(200, body(5, false)); get.queue.drain(); get.controller.resume(); replace(get);
        check(get.posts.size() == 1 && get.load().state.snapshot(17).revision == 1, "Paused review callback cannot save or authorize replacement");
        ControllerCases.Fixture queued = review(); byte[] before = Files.readAllBytes(queued.file().toPath());
        queued.controller.replaceRejectedExplicit(NEXT, null, true, false, false); queued.invalidate(); queued.queue.drain();
        check(queued.posts.size() == 1 && Arrays.equals(before, Files.readAllBytes(queued.file().toPath())), "Authority invalidated before Store entry blocks replacement");
        ControllerCases.Fixture entered = review(); entered.faults.afterFinish = entered::invalidate;
        entered.controller.replaceRejectedExplicit(NEXT, null, false, false, false); int views = entered.views.size(); entered.queue.drain();
        check(pending(entered).clientUuid.equals(NEXT) && !entered.load().state.operation(17, 23).dispatchStarted
                && entered.posts.size() == 1 && entered.views.size() == views,
                "Entered-valid replacement commit may finish during logout, no rollback/RAM/UI/mark/HTTP afterward");
    }
    private static ControllerCases.Fixture unsent() throws Exception {
        ControllerCases.Fixture f = new ControllerCases.Fixture(); f.ready(1); f.controller.submit(OLD, null, true, false, false);
        f.queue.disk(); f.controller.pause(); f.queue.drain(); f.controller.resume();
        check(!f.load().state.operation(17, 23).dispatchStarted && f.posts.isEmpty(), "Unsent fixture is actual committed Store stage, not a fabricated operation"); return f;
    }
    private static void cancellation() throws Exception {
        ControllerCases.Fixture f = unsent(); int released = f.releases.size(), gets = f.gets.size(), blocks = f.blocks.size();
        f.controller.cancelUnsentExplicit(OLD); f.queue.drain();
        check(f.load().state.pending.isEmpty() && f.floorHeld && f.releases.size() == released && f.gets.size() == gets && f.blocks.size() == blocks,
                "Cancel commits only exact unsent intent, no new floor/GET/release");
        f.controller.retryExplicit(OLD); f.queue.drain(); check(f.posts.isEmpty(), "Cancellation is not retry permission");
        ControllerCases.Fixture started = rejected(error()); started.controller.cancelUnsentExplicit(OLD); started.queue.drain();
        check(started.load().state.operation(17, 23).dispatchStarted && started.posts.size() == 1, "Started blocked/unknown cannot be canceled");
        ControllerCases.Fixture wrong = unsent(); wrong.controller.cancelUnsentExplicit(NEXT); wrong.queue.drain();
        check(wrong.load().state.pending.size() == 1, "Wrong UUID cancellation cannot affect exact pending");
        ControllerCases.Fixture raced = unsent(); raced.controller.cancelUnsentExplicit(OLD);
        Looper.mainForTest(false); try { raced.store.markDispatchStarted(pending(raced)); } finally { Looper.mainForTest(true); }
        raced.queue.drain(); check(raced.load().state.operation(17, 23).dispatchStarted, "Concurrent mark wins lock and cancel refuses started state");
        for (int fault = 0; fault < 4; fault++) {
            ControllerCases.Fixture denied = unsent(); byte[] before = Files.readAllBytes(denied.file().toPath());
            denied.controller.cancelUnsentExplicit(OLD);
            if (fault == 0) denied.muteCheckpoint = new Object();
            else if (fault == 1) denied.invalidate();
            else if (fault == 2) denied.controller.pause();
            else clearPort(denied);
            denied.queue.drain(); check(Arrays.equals(before, Files.readAllBytes(denied.file().toPath())), "Cancel queued after checkpoint/authority/view/port loss leaves exact pending: " + fault);
        }
        ControllerCases.Fixture uncertain = unsent(); uncertain.faults.failAt = uncertain.faults.writes + 1;
        uncertain.controller.cancelUnsentExplicit(OLD); uncertain.queue.drain();
        check(uncertain.controller.state().code == RoomPreferencesController.Code.STORAGE_UNCERTAIN && !uncertain.load().state.pending.isEmpty() && uncertain.floorHeld,
                "Uncertain cancel does not report success or clear floor");
        ControllerCases.Fixture entered = unsent(); entered.faults.afterFinish = entered::invalidate;
        entered.controller.cancelUnsentExplicit(OLD); int views = entered.views.size(); entered.queue.drain();
        check(entered.load().state.pending.isEmpty() && entered.views.size() == views && entered.floorHeld && entered.posts.isEmpty(),
                "Entered-valid cancel commit can finish, but no logout-time UI effect or automatic unmute");
    }
    private static void clearPort(ControllerCases.Fixture f) throws Exception {
        java.lang.reflect.Field field = RoomPreferencesController.class.getDeclaredField("mute"); field.setAccessible(true); ((WeakReference<?>) field.get(f.controller)).clear();
    }
    private static void failures() throws Exception {
        for (int commit = 1; commit <= 2; commit++) {
            ControllerCases.Fixture f = review(); f.faults.failAt = f.faults.writes + commit; replace(f);
            check(f.posts.size() == 1 && f.controller.state().code == RoomPreferencesController.Code.STORAGE_UNCERTAIN && f.floorHeld, "Uncertain replace/mark cannot dispatch or unmute: " + commit);
            check(pending(f).clientUuid.equals(commit == 1 ? OLD : NEXT), "Exact durable boundary preserved after uncertain write");
        }
        for (int boundary = 0; boundary < 3; boundary++) {
            ControllerCases.Fixture f = review(); f.controller.replaceRejectedExplicit(NEXT, null, false, false, false);
            if (boundary > 0) f.queue.disk(); // Replacement commit.
            if (boundary > 1) { f.queue.ui(); f.queue.disk(); } // markStarted commit.
            clearPort(f); f.queue.drain();
            check(f.posts.size() == 1 && pending(f).clientUuid.equals(boundary == 0 ? OLD : NEXT), "Port required before replace/mark/actual POST: " + boundary);
            check(f.load().state.operation(17, 23).dispatchStarted == (boundary == 0 || boundary == 2), "Durable started flags reported, no rollback from port loss");
        }
    }
    private static void reviewHint() throws Exception {
        ControllerCases.Fixture live = rejected(error());
        check(live.controller.state().canReviewConflict && !live.controller.state().serverDecisionReady,
                "Private exact original rejection exposes read-only review hint, not write readiness");
        live.controller.refreshConflictExplicit(OLD);
        check(!live.controller.state().canReviewConflict, "Review in flight is not another review button");
        live.queue.drain(); live.gets.get(1).complete(200, body(3, false)); live.queue.drain();
        check(live.controller.state().phase == RoomPreferencesController.Phase.REVIEW_READY
                && !live.controller.state().canReviewConflict && !live.controller.state().serverDecisionReady,
                "New-choice review phase is not old-retry or generic write readiness");
        for (int action = 0; action < 5; ++action) {
            ControllerCases.Fixture f = rejected(error()); check(f.controller.state().canReviewConflict, "Review hint starts exact and owned");
            if (action == 0) { f.controller.pause(); f.controller.resume(); }
            else if (action == 1) { f.controller.close(); f.replaceController(); }
            else if (action == 2) f.controller.refresh();
            else if (action == 3) f.invalidate();
            else { f.controller.cancelUnsentExplicit(OLD); f.queue.drain(); }
            check(!f.controller.state().canReviewConflict, "Hint drops after pause/close/refresh/authority/ordinary action: " + action);
        }
        ControllerCases.Fixture malformed = rejected(new JSONObject().put("error", new JSONObject().put("code", "revision_conflict")));
        check(!malformed.controller.state().canReviewConflict, "No API2 original proof, no hint from stored conflict text");
        ControllerCases.Fixture unknown = new ControllerCases.Fixture(); unknown.ready(1); unknown.send(true);
        unknown.posts.get(0).complete(0, null); unknown.queue.drain();
        check(!unknown.controller.state().canReviewConflict, "Unknown transport never manufactures rejected proof hint");
    }
    private ControllerRecoveryCases() { }
}

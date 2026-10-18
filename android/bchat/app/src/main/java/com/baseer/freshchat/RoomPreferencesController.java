package com.baseer.freshchat;

import com.baseer.freshchat.sync.AccountScope;
import java.lang.ref.WeakReference;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/**
 * C17 orchestration only; deliberately unconnected to Activity, HTTP, notifications or FCM.
 * Scheduler adapters must enqueue on the existing BChatStorageRepository disk lane and MAIN.
 * Host owns current authentication/rights, the final MAIN transport gate and a thread-safe
 * immutable binding mirror. Ordinary Activity fields are NOT a valid worker-side mirror.
 */
final class RoomPreferencesController {
    /** Host invalidates this RAM token BEFORE replacing identity, rights or membership. */
    static final class Authority {
        private final AtomicBoolean valid = new AtomicBoolean(true);
        void invalidate() { valid.set(false); }
        boolean valid() { return valid.get(); }
    }

    static final class Binding {
        final AccountScope account;
        final Object accountIdentity, sessionIdentity;
        final Authority authority;
        final long globalGeneration, repositoryGeneration, roomId, membershipId;
        final int contractVersion;
        Binding(AccountScope account, Object accountIdentity, Object sessionIdentity, Authority authority,
                long global, long repository, long room, long membership, int contractVersion) {
            if (account == null || accountIdentity == null || sessionIdentity == null || authority == null
                    || global < 0 || repository < 0 || room <= 0 || room > Integer.MAX_VALUE
                    || membership <= 0 || membership > Integer.MAX_VALUE || contractVersion < 0)
                throw new IllegalArgumentException("Verified binding required");
            this.account = account; this.accountIdentity = accountIdentity; this.sessionIdentity = sessionIdentity;
            this.authority = authority; globalGeneration = global; repositoryGeneration = repository;
            roomId = room; membershipId = membership; this.contractVersion = contractVersion;
        }
        boolean same(Binding other) {
            return other != null && authority.valid() && other.authority.valid()
                    && account == other.account && accountIdentity == other.accountIdentity
                    && sessionIdentity == other.sessionIdentity && authority == other.authority
                    && globalGeneration == other.globalGeneration && repositoryGeneration == other.repositoryGeneration
                    && roomId == other.roomId && membershipId == other.membershipId
                    && contractVersion == 1 && other.contractVersion == 1;
        }
    }

    interface Reply { void complete(int status, JSONObject body); }
    interface Host {
        /** RAM-only/thread-safe; includes authorized membership even when its room is not selected.
         * Publish immutable bindings through an atomic mirror, invalidate old Authority first.
         * Repository generation must be read from the existing repository, not an Activity copy. */
        Binding currentBinding(long roomId);
        /** MAIN-only narrow adapters to existing routes; recheck binding atomically before dispatch.
         * Return false if no request was accepted. Never perform blocking I/O on this caller. */
        boolean get(Binding binding, Reply reply);
        boolean post(Binding binding, String exactPayload, Reply reply);
    }
    interface Scheduler {
        void worker(Runnable work);
        void main(Runnable work);
        boolean isMain();
    }
    interface Observer { void changed(ViewState state); }
    enum Phase { IDLE, LOADING, CACHED, READY, REVIEW_READY, SAVING, PENDING, UNKNOWN, BLOCKED, SAVED, ERROR, CLOSED }
    enum Code { OK, UNSUPPORTED, STALE, NOT_READY, PENDING_REVIEW, REQUEST_UNKNOWN, INVALID_RESPONSE,
        INVALID_INPUT, REVISION_CONFLICT, MEMBERSHIP_CHANGED, PERMISSION_DENIED,
        STORAGE_UNAVAILABLE, STORAGE_CONFLICT, STORAGE_UNCERTAIN, STORAGE_FULL }
    static final class ViewState {
        final Phase phase;
        final Code code;
        final RoomPreferencesProtocol.Snapshot snapshot;
        final RoomPreferencesStore.Operation pending;
        /** Fresh server GET plus preference-Store inputs only. NOT UI-control enablement,
         * current index/mirror health, durable Admission or local mute-release confirmation.
         * Future Panel wiring must observe index health/async clear feedback separately. */
        final boolean serverDecisionReady;
        /** Presentation hint from this lifetime's private rejection, never a public proof.
         * Actions revalidate the private proof; state() drops this hint after revocation. */
        final boolean canReviewConflict;
        private ViewState(Phase phase, Code code, RoomPreferencesProtocol.Snapshot snapshot,
                RoomPreferencesStore.Operation pending, boolean serverDecisionReady, boolean canReviewConflict) {
            this.phase = phase; this.code = code; this.snapshot = snapshot;
            this.pending = pending; this.serverDecisionReady = serverDecisionReady;
            this.canReviewConflict = canReviewConflict;
        }
    }

    enum RestrictionReason { USER_INTENT, RESTORED_INTENT, EXPLICIT_RETRY }
    static final class RestrictionTicket {
        final Binding binding;
        final long viewTicket;
        final String clientUuid;
        final RoomPreferencesProtocol.Pending pending;
        final RestrictionReason reason;
        private RestrictionTicket(Ticket ticket, RoomPreferencesProtocol.Pending pending, RestrictionReason reason) {
            binding = ticket.binding; viewTicket = ticket.view; clientUuid = pending.clientUuid; this.pending = pending; this.reason = reason;
        }
    }
    enum ProofReason { CURRENT_GET_COMMITTED, MATCHED_ACK_COMMITTED }
    static final class DurableProof {
        final Binding binding;
        final long viewTicket, storeRevision;
        final String clientUuid;
        final Object muteCheckpoint;
        final RoomPreferencesProtocol.Snapshot snapshot;
        final ProofReason reason;
        private DurableProof(Ticket ticket, RoomPreferencesStore.State state,
                RoomPreferencesProtocol.Snapshot snapshot, String uuid, ProofReason reason) {
            binding = ticket.binding; viewTicket = ticket.view; storeRevision = state.revision;
            muteCheckpoint = ticket.muteCheckpoint;
            this.snapshot = snapshot; clientUuid = uuid; this.reason = reason;
        }
    }
    interface MutePort {
        /** RAM-only opaque checkpoint for account/room/member/Authority. Missing means no release
         * permission. Every block creates a new object; never reuse an earlier checkpoint (ABA). */
        Object checkpoint(Binding binding);
        /** Local unsent-cancel read-health only. No admission/floor/release or HTTP permission.
         * An absent implementation deliberately fails closed. RAM-only on MAIN or worker. */
        default boolean currentReadHealthy(Object checkpoint, Binding expected) { return false; }
        /** RAM-only conservative floor; implementation must recheck Authority/binding/ticket.
         * No clock-based expiry, route/hash inference, disk, notification or audio work here. */
        Object prepare(RestrictionTicket ticket);
        /** Opaque exact admission, not a generic boolean HTTP permission. Mandatory immediately
         * before stage/mark and actual new/retry POST. Same object for the whole attempt. */
        boolean currentDurable(Object admission, Binding expected, RoomPreferencesProtocol.Pending exact);
        /** Atomically verify current Authority AND identical nonnull checkpoint before removing
         * this binding's floor. A controller-side check followed by unchecked removal is invalid.
         * Future concrete port uses a short RAM/ROUTING gate, no I/O. Never a global unmute. */
        void release(DurableProof proof);
    }

    private static final class Ticket {
        final Binding binding;
        final long view;
        final Object muteCheckpoint;
        Ticket(Binding binding, long view) { this(binding, view, null); }
        Ticket(Binding binding, long view, Object checkpoint) {
            this.binding = binding; this.view = view; muteCheckpoint = checkpoint;
        }
    }
    /** Constructed ONLY after the original strict authenticated POST callback is durably
     * blocked. No server body, stored marker or restored snapshot can manufacture this. */
    private static final class RejectedProof {
        final Ticket request;
        final RoomPreferencesProtocol.Pending pending;
        private RejectedProof(Ticket request, RoomPreferencesProtocol.Pending pending) {
            this.request = request; this.pending = pending;
        }
    }
    /** The actual explicit conflict GET, never a higher snapshot selected from disk. */
    private static final class FreshDecision {
        final RejectedProof rejected;
        final Ticket get;
        final RoomPreferencesProtocol.Snapshot snapshot;
        final long storeRevision;
        private FreshDecision(RejectedProof rejected, Ticket get, RoomPreferencesProtocol.Snapshot snapshot, long revision) {
            this.rejected = rejected; this.get = get; this.snapshot = snapshot; storeRevision = revision;
        }
    }
    private final RoomPreferencesStore store;
    private final Binding binding;
    private final Scheduler scheduler;
    private final WeakReference<Host> host;
    private final WeakReference<Observer> observer;
    private final WeakReference<MutePort> mute;
    private volatile long viewTicket;
    private volatile boolean paused, closed;
    // Remaining fields are confined to MAIN. Worker closures retain only immutable request data.
    private boolean busy;
    private long storeRevision;
    private RoomPreferencesProtocol.Snapshot fresh;
    // MAIN-only rejection ownership. An explicit recovery action may hand the same immutable
    // original proof to its new view ticket. Ordinary actions, pause/close and restart cannot.
    private RejectedProof rejectedProof;
    private long rejectedView;
    private FreshDecision freshDecision;
    private ViewState state = new ViewState(Phase.IDLE, Code.OK, null, null, false, false);

    RoomPreferencesController(RoomPreferencesStore store, Binding binding, Host host, Scheduler scheduler,
            Observer observer, MutePort mute) {
        if (store == null || binding == null || host == null || scheduler == null)
            throw new IllegalArgumentException("Store and verified ports required");
        this.store = store; this.binding = binding; this.scheduler = scheduler;
        this.host = new WeakReference<>(host); this.observer = new WeakReference<>(observer);
        this.mute = new WeakReference<>(mute);
    }

    ViewState state() {
        mainThread();
        if (state.canReviewConflict && (state.pending == null
                || !currentRejection(state.pending.pending.clientUuid)))
            state = new ViewState(state.phase, state.code, state.snapshot, state.pending, state.serverDecisionReady, false);
        return state;
    }
    void open() { refresh(); }
    /** Explicit user GET only. Loading/restoring never drains, retries, cancels or overwrites intents. */
    void refresh() {
        mainThread();
        if (closed || paused || busy) return;
        refreshWithProof(null);
    }

    /** Explicit review of THIS lifetime's authenticated conflict, not a blocked-intent POST. */
    void refreshConflictExplicit(String uuid) {
        mainThread();
        if (closed || paused || busy || !currentRejection(uuid)) return;
        refreshWithProof(rejectedProof);
    }

    private void refreshWithProof(RejectedProof proof) {
        if (binding.contractVersion != 1) { emit(Phase.ERROR, Code.UNSUPPORTED, null, null, false); return; }
        Ticket ticket = proof == null ? begin() : beginRecovery(proof);
        if (!active(ticket)) return;
        fresh = null;
        busy = true; emit(Phase.LOADING, Code.OK, state.snapshot, state.pending, false);
        scheduler.worker(() -> {
            if (!active(ticket)) return;
            RoomPreferencesStore.Result loaded = store.load();
            scheduler.main(() -> {
                if (!active(ticket)) return;
                if (!readable(loaded)) { busy = false; storageError(loaded); return; }
                storeRevision = loaded.state.revision;
                RoomPreferencesStore.Operation pending = operation(loaded.state);
                if (proof != null && (!recoveryCurrent(ticket, proof) || !rejectedOperation(loaded.state, proof))) {
                    busy = false; clearRecovery();
                    emit(Phase.BLOCKED, Code.PENDING_REVIEW, snapshot(loaded.state), pending, false); return;
                }
                if (proof == null) restoreFloor(ticket, pending, RestrictionReason.RESTORED_INTENT);
                emit(Phase.CACHED, pending == null ? Code.OK : Code.PENDING_REVIEW,
                        snapshot(loaded.state), pending, false);
                requestGet(ticket, proof);
            });
        });
    }

    private void requestGet(Ticket ticket, RejectedProof proof) {
        if (!active(ticket)) return;
        final Ticket request = dispatchTicket(ticket);
        Host port = host.get();
        AtomicBoolean answered = new AtomicBoolean();
        Reply reply = (status, body) -> {
            if (!answered.compareAndSet(false, true)) return;
            RoomPreferencesProtocol.Snapshot parsed = null;
            if (status == 200) try {
                parsed = RoomPreferencesProtocol.freshSnapshot(body, binding.account, binding.roomId, binding.membershipId);
            } catch (RuntimeException ignored) { }
            final RoomPreferencesProtocol.Snapshot response = parsed;
            scheduler.main(() -> receiveGet(request, status, response, proof));
        };
        boolean accepted;
        try { accepted = active(request) && port != null && port.get(request.binding, reply); }
        catch (RuntimeException unavailable) { accepted = false; }
        if (!accepted && answered.compareAndSet(false, true)) receiveGet(request, 0, null, proof);
    }

    private void receiveGet(Ticket ticket, int status, RoomPreferencesProtocol.Snapshot response, RejectedProof proof) {
        if (!active(ticket)) return;
        if (proof != null && !recoveryCurrent(ticket, proof)) return;
        if (response == null) {
            final RoomPreferencesStore.Operation pending = state.pending;
            if (pending != null && (status == 403 || status == 409)) {
                scheduler.worker(() -> {
                    if (!active(ticket)) return;
                    RoomPreferencesStore.Result blocked = store.markBlocked(pending.pending,
                            status == 403 ? "permission_denied" : "membership_changed");
                    scheduler.main(() -> {
                        if (!active(ticket)) return;
                        busy = false;
                        if (blocked.kind == RoomPreferencesStore.Kind.COMMITTED || blocked.kind == RoomPreferencesStore.Kind.UNCHANGED)
                            emit(Phase.BLOCKED, denied(status), snapshot(blocked.state), operation(blocked.state), false);
                        else storageError(blocked);
                    });
                });
                return;
            }
            busy = false;
            emit(Phase.ERROR, denied(status), state.snapshot, state.pending, false); return;
        }
        final long expected = storeRevision;
        scheduler.worker(() -> {
            if (!active(ticket)) return;
            RoomPreferencesStore.Result saved = store.saveSnapshot(response, expected);
            scheduler.main(() -> {
                if (!active(ticket)) return;
                busy = false;
                if (saved.kind != RoomPreferencesStore.Kind.COMMITTED && saved.kind != RoomPreferencesStore.Kind.UNCHANGED) {
                    storageError(saved); return;
                }
                storeRevision = saved.state.revision;
                RoomPreferencesStore.Operation pending = operation(saved.state);
                RoomPreferencesProtocol.Snapshot cached = snapshot(saved.state);
                // A valid but older GET cannot promote a newer disk snapshot into fresh authority.
                boolean currentObservation = cached != null && cached.revision == response.revision;
                if (proof != null) {
                    freshDecision = null;
                    if (recoveryCurrent(ticket, proof) && rejectedOperation(saved.state, proof)
                            && currentObservation && response.revision > proof.pending.expectedRevision) {
                        freshDecision = new FreshDecision(proof, ticket, response, saved.state.revision);
                        // A review decision is not ordinary new-intent readiness or index health.
                        emit(Phase.REVIEW_READY, Code.REVISION_CONFLICT, cached, pending, false);
                    } else emit(Phase.BLOCKED, Code.STORAGE_CONFLICT, cached, pending, false);
                    return;
                }
                fresh = currentObservation && ticket.muteCheckpoint != null && mute.get() != null
                        && !hasRoomPending(saved.state) ? response : null;
                emit(fresh == null ? Phase.CACHED : Phase.READY,
                        pending == null ? Code.OK : Code.PENDING_REVIEW, cached, pending, fresh != null);
                if (fresh != null && !fresh.muted && identity(ticket.binding))
                    release(ticket, saved.state, fresh, null, ProofReason.CURRENT_GET_COMMITTED);
            });
        });
    }

    /** Local cancellation only. Serial Store locking decides any race with markStarted.
     * Never dispatches, fabricates a floor or releases one, even after COMMITTED. */
    void cancelUnsentExplicit(String uuid) {
        mainThread();
        if (closed || paused || busy || uuid == null) return;
        Ticket ticket = dispatchTicket(begin());
        if (!active(ticket)) return;
        fresh = null; busy = true;
        if (!readHealthy(ticket)) { admissionError(ticket); return; }
        emit(Phase.SAVING, Code.OK, state.snapshot, state.pending, false);
        scheduler.worker(() -> {
            if (!active(ticket)) return;
            RoomPreferencesStore.Result loaded = store.load();
            if (!active(ticket)) return;
            RoomPreferencesStore.Operation pending = readable(loaded) ? operation(loaded.state) : null;
            if (!readHealthy(ticket)) { scheduler.main(() -> admissionError(ticket)); return; }
            RoomPreferencesStore.Result result = pending != null && uuid.equals(pending.pending.clientUuid)
                    ? store.cancelUnsent(pending.pending) : loaded;
            scheduler.main(() -> {
                if (!active(ticket)) return;
                busy = false;
                if (result.kind == RoomPreferencesStore.Kind.COMMITTED) {
                    storeRevision = result.state.revision;
                    emit(Phase.CACHED, Code.OK, snapshot(result.state), operation(result.state), false);
                } else if (readable(result))
                    emit(Phase.BLOCKED, Code.PENDING_REVIEW, snapshot(result.state), operation(result.state), false);
                else storageError(result);
            });
        });
    }

    /** Only a new explicit user choice creates the replacement UUID/payload. The original
     * rejected payload is never edited, auto-retried, or dispatched after restart. */
    void replaceRejectedExplicit(String uuid, String until, boolean forever, boolean pinned, boolean archived) {
        mainThread();
        FreshDecision decision = freshDecision;
        if (closed || paused || busy || decision == null || !active(decision.get)
                || !recoveryCurrent(decision.get, decision.rejected)) return;
        final RoomPreferencesProtocol.Pending replacement;
        try {
            replacement = RoomPreferencesProtocol.newPending(decision.snapshot, uuid, until, forever, pinned, archived);
            if (replacement.clientUuid.equals(decision.rejected.pending.clientUuid)) throw new IllegalArgumentException();
        } catch (RuntimeException invalid) { emit(Phase.ERROR, Code.INVALID_INPUT, state.snapshot, state.pending, false); return; }
        Ticket ticket = beginRecovery(decision.rejected);
        if (!active(ticket)) return;
        fresh = null; busy = true;
        Object admission = prepareAttempt(ticket, replacement, RestrictionReason.USER_INTENT);
        if (admission == null) { admissionError(ticket); return; }
        emit(Phase.SAVING, Code.OK, state.snapshot, state.pending, false);
        scheduler.worker(() -> {
            if (!active(ticket)) return;
            if (!currentDurable(ticket, replacement, admission)) { scheduler.main(() -> admissionError(ticket)); return; }
            RoomPreferencesStore.Result result = store.replaceExactRejected(decision.rejected.pending,
                    decision.snapshot, replacement, decision.storeRevision);
            scheduler.main(() -> {
                if (!active(ticket)) return;
                if (result.kind != RoomPreferencesStore.Kind.COMMITTED) { busy = false; storageError(result); return; }
                clearRecovery(); storeRevision = result.state.revision;
                emit(Phase.PENDING, Code.PENDING_REVIEW, snapshot(result.state), operation(result.state), false);
                markAndPost(ticket, replacement, false, admission);
            });
        });
    }

    void submit(String uuid, String until, boolean forever, boolean pinned, boolean archived) {
        mainThread();
        if (closed || paused || busy || fresh == null || !state.serverDecisionReady) return;
        Ticket ticket = begin();
        if (!active(ticket)) return;
        final RoomPreferencesProtocol.Pending pending;
        try { pending = RoomPreferencesProtocol.newPending(fresh, uuid, until, forever, pinned, archived); }
        catch (RuntimeException invalid) { emit(Phase.ERROR, Code.INVALID_INPUT, state.snapshot, state.pending, false); return; }
        fresh = null; busy = true;
        final Object admission = prepareAttempt(ticket, pending, RestrictionReason.USER_INTENT);
        if (admission == null) { admissionError(ticket); return; }
        emit(Phase.SAVING, Code.OK, state.snapshot, null, false);
        final long expected = storeRevision;
        scheduler.worker(() -> {
            if (!active(ticket)) return;
            if (!currentDurable(ticket, pending, admission)) { scheduler.main(() -> admissionError(ticket)); return; }
            RoomPreferencesStore.Result staged = store.stage(pending, expected);
            scheduler.main(() -> {
                if (!active(ticket)) return;
                if (staged.kind != RoomPreferencesStore.Kind.COMMITTED) { busy = false; storageError(staged); return; }
                storeRevision = staged.state.revision;
                emit(Phase.PENDING, Code.PENDING_REVIEW, snapshot(staged.state), operation(staged.state), false);
                markAndPost(ticket, pending, false, admission);
            });
        });
    }

    /** Explicit retry path, not permission inferred from stage/mark UNCHANGED or opening a view. */
    void retryExplicit(String uuid) {
        mainThread();
        if (closed || paused || busy || uuid == null) return;
        Ticket ticket = begin();
        if (!active(ticket)) return;
        fresh = null; busy = true;
        scheduler.worker(() -> {
            if (!active(ticket)) return;
            RoomPreferencesStore.Result loaded = store.load();
            scheduler.main(() -> {
                if (!active(ticket)) return;
                if (!readable(loaded)) { busy = false; storageError(loaded); return; }
                RoomPreferencesStore.Operation pending = operation(loaded.state);
                RoomPreferencesProtocol.Snapshot cached = loaded.state.snapshot(binding.roomId);
                if (pending == null || !uuid.equals(pending.pending.clientUuid) || !pending.blockedCode.isEmpty()
                        || cached != null && cached.membershipId != binding.membershipId) {
                    busy = false; emit(Phase.BLOCKED, Code.PENDING_REVIEW, snapshot(loaded.state), pending, false); return;
                }
                storeRevision = loaded.state.revision;
                Object admission = prepareAttempt(ticket, pending.pending, RestrictionReason.EXPLICIT_RETRY);
                if (admission == null) { admissionError(ticket); return; }
                markAndPost(ticket, pending.pending, pending.dispatchStarted, admission);
            });
        });
    }

    private void markAndPost(Ticket ticket, RoomPreferencesProtocol.Pending pending, boolean retryStarted, Object admission) {
        scheduler.worker(() -> {
            if (!active(ticket)) return;
            if (!currentDurable(ticket, pending, admission)) { scheduler.main(() -> admissionError(ticket)); return; }
            RoomPreferencesStore.Result marked = store.markDispatchStarted(pending);
            scheduler.main(() -> {
                if (!active(ticket)) return;
                RoomPreferencesStore.Operation exact = marked.state == null ? null : operation(marked.state);
                // Only explicit loaded-started retry may use UNCHANGED, after exact readback.
                boolean durable = marked.kind == RoomPreferencesStore.Kind.COMMITTED
                        || retryStarted && marked.kind == RoomPreferencesStore.Kind.UNCHANGED;
                if (!durable || exact == null || !exact.dispatchStarted || !exact.blockedCode.isEmpty()
                        || !exact.pending.payload.equals(pending.payload) || !exact.pending.clientUuid.equals(pending.clientUuid)) {
                    busy = false; storageError(marked); return;
                }
                storeRevision = marked.state.revision;
                // Keep exact durable flags even if the port disappears at the final gate.
                // No extra observer event: the next outcome publishes this current metadata.
                state = new ViewState(Phase.PENDING, Code.PENDING_REVIEW, snapshot(marked.state), exact, false, false);
                requestPost(ticket, pending, admission);
            });
        });
    }

    private void requestPost(Ticket ticket, RoomPreferencesProtocol.Pending pending, Object admission) {
        if (!active(ticket)) return;
        if (!currentDurable(ticket, pending, admission)) { admissionError(ticket); return; }
        final Ticket request = dispatchTicket(ticket);
        Host port = host.get();
        AtomicBoolean answered = new AtomicBoolean();
        Reply reply = (status, body) -> {
            if (!answered.compareAndSet(false, true)) return;
            RoomPreferencesProtocol.Acknowledgement parsed = null;
            if (status == 200) try { parsed = RoomPreferencesProtocol.acknowledgement(status, body, pending); }
            catch (RuntimeException ignored) { }
            final RoomPreferencesProtocol.Acknowledgement response = parsed;
            final Code rejected = postCode(status, body);
            final boolean strictConflict = strictRevisionConflict(status, body);
            // Original request's immutable pending/binding, never the currently selected view.
            scheduler.main(() -> receivePost(request, pending, status, response, rejected, strictConflict));
        };
        boolean accepted;
        try { accepted = active(request) && port != null && port.post(request.binding, pending.payload, reply); }
        catch (RuntimeException unavailable) { accepted = false; }
        if (!accepted && answered.compareAndSet(false, true)) receivePost(request, pending, 0, null, Code.REQUEST_UNKNOWN, false);
    }

    private void receivePost(Ticket ticket, RoomPreferencesProtocol.Pending pending, int status,
            RoomPreferencesProtocol.Acknowledgement response, Code rejected, boolean strictConflict) {
        // Pause/close is NOT identity invalidation; valid sent receipts may settle while unselected.
        if (!identity(ticket.binding)) return;
        if (response == null && status != 403 && status != 409) {
            if (active(ticket)) { busy = false; emit(Phase.UNKNOWN, status == 200 ? Code.INVALID_RESPONSE : denied(status),
                    state.snapshot, state.pending, false); }
            return;
        }
        scheduler.worker(() -> {
            // Linearization boundary: queued work after revocation cannot enter Store. A commit
            // already entered while valid may finish; no auth lock spans sync/finish/readback.
            if (!identity(ticket.binding)) return;
            RoomPreferencesStore.Result result = response == null
                    ? store.markBlocked(pending, rejected == Code.PERMISSION_DENIED ? "permission_denied"
                            : rejected == Code.MEMBERSHIP_CHANGED ? "membership_changed"
                            : rejected == Code.REVISION_CONFLICT ? "revision_conflict" : "request_unknown")
                    : store.acknowledge(pending, response);
            scheduler.main(() -> {
                if (!identity(ticket.binding)) return; // No RAM/UI/mute effects after invalidation.
                if (response != null && result.kind == RoomPreferencesStore.Kind.COMMITTED) {
                    if (active(ticket)) {
                        clearRecovery();
                        busy = false; fresh = null; storeRevision = result.state.revision;
                        emit(Phase.SAVED, Code.OK, snapshot(result.state), operation(result.state), false);
                    }
                    RoomPreferencesProtocol.Snapshot cached = snapshot(result.state);
                    // A newer/equal-derived cache is not the sent request's mute proof. Do
                    // not borrow its false bit/checkpoint provenance for an older ACK.
                    if (!response.snapshot.muted && cached != null && !cached.muted
                            && cached.revision == response.snapshot.revision && !hasRoomPending(result.state))
                        release(ticket, result.state, response.snapshot, pending.clientUuid, ProofReason.MATCHED_ACK_COMMITTED);
                } else if (active(ticket)) {
                    busy = false;
                    if (response == null && (result.kind == RoomPreferencesStore.Kind.COMMITTED || result.kind == RoomPreferencesStore.Kind.UNCHANGED)) {
                        RoomPreferencesStore.Operation exact = operation(result.state);
                        if (strictConflict && exact != null && exact.dispatchStarted
                                && "revision_conflict".equals(exact.blockedCode) && samePending(exact.pending, pending)) {
                            rejectedProof = new RejectedProof(ticket, pending); rejectedView = ticket.view; freshDecision = null;
                        }
                        emit(Phase.BLOCKED, rejected,
                                snapshot(result.state), operation(result.state), false);
                    } else storageError(result);
                }
            });
        });
    }

    void pause() { mainThread(); if (!closed) { paused = true; invalidateView(); } }
    /** No automatic GET, POST, cancellation or retry on resume. */
    void resume() { mainThread(); if (!closed) { paused = false; invalidateView(); } }
    void close() {
        mainThread(); closed = true; invalidateView(); observer.clear();
        state = new ViewState(Phase.CLOSED, Code.OK, null, null, false, false);
    }
    private void invalidateView() {
        ++viewTicket; busy = false; fresh = null; clearRecovery();
        if (!closed) state = new ViewState(Phase.CACHED, Code.NOT_READY, state.snapshot, state.pending, false, false);
    }
    private Ticket begin() { clearRecovery(); return new Ticket(binding, ++viewTicket); }
    private Ticket beginRecovery(RejectedProof proof) {
        Ticket ticket = begin(); rejectedProof = proof; rejectedView = ticket.view; return ticket;
    }
    private void clearRecovery() { rejectedProof = null; freshDecision = null; }
    private boolean currentRejection(String uuid) {
        return rejectedProof != null && uuid != null && uuid.equals(rejectedProof.pending.clientUuid)
                && recoveryCurrent(new Ticket(binding, viewTicket), rejectedProof);
    }
    private boolean recoveryCurrent(Ticket ticket, RejectedProof proof) {
        return proof != null && rejectedProof == proof && rejectedView == ticket.view && active(ticket)
                && ticket.binding.same(proof.request.binding);
    }
    private boolean rejectedOperation(RoomPreferencesStore.State value, RejectedProof proof) {
        RoomPreferencesStore.Operation item = operation(value);
        return item != null && item.dispatchStarted && "revision_conflict".equals(item.blockedCode)
                && samePending(item.pending, proof.pending);
    }
    private static boolean samePending(RoomPreferencesProtocol.Pending first, RoomPreferencesProtocol.Pending second) {
        return RoomPreferencesProtocol.sameBinding(first.account, first.roomId, first.membershipId,
                second.account, second.roomId, second.membershipId)
                && first.clientUuid.equals(second.clientUuid) && first.payload.equals(second.payload);
    }
    private Ticket dispatchTicket(Ticket ticket) {
        Object checkpoint = null;
        MutePort port = mute.get();
        if (port != null) try { checkpoint = port.checkpoint(ticket.binding); }
        catch (RuntimeException unavailable) { /* No checkpoint cannot grant a later release. */ }
        return new Ticket(ticket.binding, ticket.view, checkpoint);
    }
    private boolean identity(Binding expected) {
        if (!expected.authority.valid()) return false;
        Host port = host.get();
        try { return port != null && expected.same(port.currentBinding(expected.roomId)); }
        catch (RuntimeException unavailable) { return false; }
    }
    private boolean active(Ticket ticket) {
        return !closed && !paused && ticket.view == viewTicket && identity(ticket.binding);
    }
    private RoomPreferencesStore.Operation operation(RoomPreferencesStore.State value) {
        return value.operation(binding.roomId, binding.membershipId);
    }
    private RoomPreferencesProtocol.Snapshot snapshot(RoomPreferencesStore.State value) {
        RoomPreferencesProtocol.Snapshot item = value.snapshot(binding.roomId);
        return item != null && item.membershipId == binding.membershipId ? item : null;
    }
    private boolean hasRoomPending(RoomPreferencesStore.State value) {
        for (RoomPreferencesStore.Operation item : value.pending) if (item.pending.roomId == binding.roomId) return true;
        return false;
    }
    private void restoreFloor(Ticket ticket, RoomPreferencesStore.Operation operation, RestrictionReason reason) {
        if (operation != null) restoreFloor(ticket, operation.pending, reason);
    }
    private void restoreFloor(Ticket ticket, RoomPreferencesProtocol.Pending pending, RestrictionReason reason) {
        if ((pending.muteForever || pending.mutedUntil != null) && active(ticket)) {
            prepareAttempt(ticket, pending, reason);
        }
    }
    private Object prepareAttempt(Ticket ticket, RoomPreferencesProtocol.Pending pending, RestrictionReason reason) {
        if (!active(ticket)) return null;
        MutePort port = mute.get();
        try { return port == null ? null : port.prepare(new RestrictionTicket(ticket, pending, reason)); }
        catch (RuntimeException unavailable) { return null; }
    }
    private boolean currentDurable(Ticket ticket, RoomPreferencesProtocol.Pending pending, Object admission) {
        if (admission == null || !active(ticket)) return false;
        MutePort port = mute.get();
        try { return port != null && port.currentDurable(admission, ticket.binding, pending); }
        catch (RuntimeException unavailable) { return false; }
    }
    private boolean readHealthy(Ticket ticket) {
        if (ticket.muteCheckpoint == null || !active(ticket)) return false;
        MutePort port = mute.get();
        try { return port != null && port.currentReadHealthy(ticket.muteCheckpoint, ticket.binding); }
        catch (RuntimeException unavailable) { return false; }
    }
    private void admissionError(Ticket ticket) {
        if (!active(ticket)) return;
        busy = false; fresh = null; emit(Phase.ERROR, Code.STORAGE_UNAVAILABLE, state.snapshot, state.pending, false);
    }
    private void release(Ticket ticket, RoomPreferencesStore.State state, RoomPreferencesProtocol.Snapshot snapshot,
            String uuid, ProofReason reason) {
        // ACK settlement can finish after close, but no close/timeout is itself a release reason.
        if (ticket.muteCheckpoint == null || !identity(ticket.binding)) return;
        MutePort port = mute.get(); if (port != null) port.release(new DurableProof(ticket, state, snapshot, uuid, reason));
    }
    private static boolean readable(RoomPreferencesStore.Result value) {
        return value.kind == RoomPreferencesStore.Kind.LOADED || value.kind == RoomPreferencesStore.Kind.ABSENT;
    }
    private static Code denied(int status) {
        return status == 401 || status == 403 ? Code.PERMISSION_DENIED
                : status == 409 ? Code.MEMBERSHIP_CHANGED : Code.REQUEST_UNKNOWN;
    }
    private static Code postCode(int status, JSONObject body) {
        if (status == 403) return Code.PERMISSION_DENIED;
        Object error = body == null ? null : body.opt("error");
        Object code = error instanceof JSONObject ? ((JSONObject) error).opt("code") : null;
        if (status == 409 && "membership_changed".equals(code)) return Code.MEMBERSHIP_CHANGED;
        if (status == 409 && "revision_conflict".equals(code)) return Code.REVISION_CONFLICT;
        return Code.REQUEST_UNKNOWN;
    }
    private static boolean strictRevisionConflict(int status, JSONObject body) {
        Object version = body == null ? null : body.opt("api_version");
        Object error = body == null ? null : body.opt("error");
        Object code = error instanceof JSONObject ? ((JSONObject) error).opt("code") : null;
        return status == 409 && (version instanceof Integer || version instanceof Long)
                && ((Number) version).longValue() == 2 && "revision_conflict".equals(code);
    }
    private void storageError(RoomPreferencesStore.Result result) {
        fresh = null;
        Code code;
        switch (result.kind) {
            case CONFLICT: case UNCHANGED: case NO_MATCH: code = Code.STORAGE_CONFLICT; break;
            case EPOCH_CONFLICT: code = Code.MEMBERSHIP_CHANGED; break;
            case CAPACITY: case TOO_LARGE: case EXHAUSTED: code = Code.STORAGE_FULL; break;
            case UNCERTAIN: code = Code.STORAGE_UNCERTAIN; break;
            case BLOCKED: code = Code.PENDING_REVIEW; break;
            default: code = Code.STORAGE_UNAVAILABLE;
        }
        emit(Phase.ERROR, code, state.snapshot, result.state == null ? state.pending : operation(result.state), false);
    }
    private void emit(Phase phase, Code code, RoomPreferencesProtocol.Snapshot snapshot,
            RoomPreferencesStore.Operation pending, boolean ready) {
        boolean review = phase == Phase.BLOCKED && code == Code.REVISION_CONFLICT && pending != null
                && pending.dispatchStarted && "revision_conflict".equals(pending.blockedCode)
                && currentRejection(pending.pending.clientUuid);
        state = new ViewState(phase, code, snapshot, pending, ready, review);
        if (closed || paused || !identity(binding)) return;
        Observer port = observer.get(); if (port != null) port.changed(state);
    }
    private void mainThread() { if (!scheduler.isMain()) throw new IllegalStateException("Controller entry requires MAIN"); }
}

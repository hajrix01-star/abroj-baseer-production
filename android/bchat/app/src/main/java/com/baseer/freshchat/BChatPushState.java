package com.baseer.freshchat;

import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.BChatStorageRepository;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Routing hints, not authentication. Odoo must re-authorize any opened notification target. */
public final class BChatPushState {
    public static final String EXTRA_EVENT_ID = "com.baseer.bchat.PUSH_EVENT_ID";
    public static final String EXTRA_ACCOUNT_KEY = "com.baseer.bchat.PUSH_ACCOUNT_KEY";
    public static final String EXTRA_KIND = "com.baseer.bchat.PUSH_KIND";
    private static final String PREFS = "bchat-push-v1";
    private static final String SCOPE = "verified-account-scope", ACCOUNT = "registered-account-key";
    private static final String TOKEN = "fcm-token", REGISTERED_TOKEN = "registered-fcm-token";
    private static final String INSTALLATION = "installation-id";
    private static final String PREVIEW_ACCOUNT = "preview-account-key", PREVIEW_MODE = "preview-mode";
    private static final String PREVIEW_REVISION = "preview-revision";
    private static final String PREVIEW_DESIRED = "preview-pending-mode";
    private static final String PREVIEW_SCOPE = "preview-pending-scope", PREVIEW_INSTALLATION = "preview-pending-installation";
    private static final String CONTROL_UUID = "preview-control-uuid", CONTROL_ACCOUNT = "preview-control-account";
    private static final String CONTROL_REVISION = "preview-control-expected-revision";
    private static final Object ROUTING = new Object();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final BChatRoomMutePort.Gate ROOM_GATE = new BChatRoomMutePort.Gate() {
        public <T> T run(BChatRoomMutePort.Value<T> value) { synchronized (ROUTING) { return value.get(); } }
    };
    private static final RoomPreferencesController.Scheduler ROOM_SCHEDULER = new RoomPreferencesController.Scheduler() {
        public void worker(Runnable work) { BChatStorageRepository.executor().execute(work); }
        public void main(Runnable work) {
            if (!MAIN.post(work)) throw new java.util.concurrent.RejectedExecutionException("MAIN rejected room health work");
        }
        public boolean isMain() { return Looper.myLooper() == Looper.getMainLooper(); }
    };
    private static final IdentityHashMap<SharedPreferences.OnSharedPreferenceChangeListener, Boolean> OBSERVERS
            = new IdentityHashMap<>();
    private static State state;

    public interface Ready<T> { void complete(T result, boolean durable); }
    interface Presentation { void show(String currentPreviewMode); }
    private static final class State {
        final Context context;
        final NotificationManager notifications;
        final CountDownLatch loaded = new CountDownLatch(1);
        SharedPreferences prefs;
        boolean ready, scopeTouched, tokenTouched, routeCleared, routeDurable, storageHealthy;
        String scope, account, token, registeredToken, installation, savedInstallation;
        String preview = "none", previewDesired, privacyScope, privacyInstallation;
        String controlUuid, controlAccount, durableControl;
        long controlRevision = -1;
        long epoch, intent, previewRevision = -1, sequence, registrationSerial, presentationSerial;
        BChatRoomPreferencesOwner roomOwner;
        Object bindingGeneration = new Object();
        boolean needsVerifiedBindings;
        String verifiedRAMScope; // Set ONLY by verifiedAccount, never by preferences/registration.
        RoomReconcile roomReconcile;
        State(Context context, NotificationManager manager) { this.context = context; notifications = manager; }
    }
    public static final class Registration {
        public final String token, installationId;
        private final State owner;
        private final String scope;
        private final long epoch, serial;
        private Registration(State owner) {
            this.owner = owner; scope = owner.scope; epoch = owner.epoch; serial = ++owner.registrationSerial;
            token = owner.token; installationId = owner.installation;
        }
    }
    static final class PreviewRequest {
        private final State owner;
        private final String account;
        private final long epoch, intent;
        private PreviewRequest(State owner) {
            this.owner = owner; account = owner.account; epoch = owner.epoch; intent = owner.intent;
        }
    }
    /** An immutable control payload, never an authentication credential. */
    static final class PreviewControl {
        final String clientUuid, accountKey, installationId, mode;
        final long expectedRevision;
        private final State owner;
        private final String fingerprint;
        private final long epoch, intent;
        private final boolean dispatchable;
        private PreviewControl(State s, boolean dispatchable) {
            owner = s; epoch = s.epoch; intent = s.intent;
            clientUuid = s.controlUuid; accountKey = s.controlAccount;
            installationId = s.privacyInstallation; mode = s.previewDesired;
            expectedRevision = s.controlRevision; fingerprint = controlFingerprint(s);
            this.dispatchable = dispatchable;
        }
    }
    static final class Delivery {
        private final State owner;
        private final String account;
        private final long epoch, presentationSerial;
        private final String roomKey, scope;
        private final BChatRoomPreferencesOwner roomOwner;
        private final BChatRoomPreferencesOwner.Frame roomFrame;
        private Delivery(State owner) { this(owner, null); }
        private Delivery(State owner, String roomKey) {
            this.owner = owner; account = owner.account; epoch = owner.epoch;
            presentationSerial = owner.presentationSerial;
            this.roomKey = roomKey; scope = owner.scope; roomOwner = owner.roomOwner;
            roomFrame = roomKey == null || roomOwner == null ? null : roomOwner.snapshot();
        }
    }
    /** Immutable RAM observation/load ticket, not authentication or POST permission. Capture
     * before dispatch; a callback may not borrow the newer Owner/Frame/binding generation.
     */
    static final class RoomRoute {
        final String scope, account;
        final BChatRoomPreferencesOwner roomOwner;
        final BChatRoomPreferencesOwner.Frame frame;
        final Object lifetimeKey; // Opaque rendezvous key, NEVER sufficient authority alone.
        private final State state;
        private final long epoch;
        private final Object bindingGeneration;
        private final boolean needsVerifiedBindings;
        private RoomRoute(State state) {
            this.state = state; scope = state.scope; account = state.account; epoch = state.epoch;
            roomOwner = state.roomOwner; frame = roomOwner == null ? null : roomOwner.snapshot();
            bindingGeneration = state.bindingGeneration; needsVerifiedBindings = state.needsVerifiedBindings;
            lifetimeKey = bindingGeneration;
        }
    }
    static final class RoomPublication {
        final BChatRoomPreferencesOwner.Kind kind;
        final RoomRoute route;
        private RoomPublication(BChatRoomPreferencesOwner.Kind kind, RoomRoute route) {
            this.kind = kind; this.route = route;
        }
    }
    private static RoomRoute roomRouteLocked(State s) {
        return validScope(s.scope) && validUuid(s.account) ? new RoomRoute(s) : null;
    }
    private static boolean currentRoomRouteLocked(RoomRoute ticket) {
        return currentRoomLifetimeLocked(ticket)
                && (ticket.roomOwner == null || ticket.roomOwner.snapshot() == ticket.frame);
    }
    private static boolean currentRoomLifetimeLocked(RoomRoute ticket) {
        State s = state;
        return ticket != null && s == ticket.state && s.epoch == ticket.epoch
                && s.bindingGeneration == ticket.bindingGeneration
                && Objects.equals(s.scope, ticket.scope) && Objects.equals(s.account, ticket.account)
                && s.roomOwner == ticket.roomOwner;
    }
    /** Worker prelude on the EXISTING serial disk lane, called directly, never queue+wait.
     * Factory and index I/O are outside ROUTING. Failure never grants scoped presentation.
     */
    private static void prepareRoomOwnerWorker(RoomRoute ticket) {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Room index requires worker");
        synchronized (ROUTING) { if (!currentRoomRouteLocked(ticket)) return; }
        BChatRoomPreferencesOwner owner = ticket.roomOwner;
        BChatRoomPreferencesOwner.Frame frame = ticket.frame;
        boolean attached = false;
        if (owner == null) {
            BChatRoomMuteIndex index = new BChatRoomMuteIndex(ticket.state.context, ticket.scope, ticket.account);
            BChatRoomPreferencesOwner created = new BChatRoomPreferencesOwner(index, ROOM_GATE, ROOM_SCHEDULER);
            if (ticket.needsVerifiedBindings)
                created.invalidateBindings(created.snapshot(), BChatRoomPreferencesOwner.Reason.RIGHTS_CHANGED);
            synchronized (ROUTING) {
                if (!currentRoomRouteLocked(ticket)) { created.revokeRoute(created.snapshot()); return; }
                ticket.state.roomOwner = created; owner = created; frame = created.snapshot(); attached = true;
            }
        }
        try {
            owner.loadColdWorker(frame); // A late load cannot publish routes or rearm an invalid Frame.
        } finally {
            boolean hint;
            synchronized (ROUTING) {
                State s = state;
                hint = attached && s == ticket.state && s.epoch == ticket.epoch
                        && s.bindingGeneration == ticket.bindingGeneration && s.roomOwner == owner
                        && Objects.equals(s.scope, ticket.scope) && Objects.equals(s.account, ticket.account);
            }
            if (hint) changedLocked(); // Enqueue outside Gate; an observation hint, not authority.
        }
    }
    private static void invalidateRoomOwnerLocked(State s, boolean terminal, BChatRoomPreferencesOwner.Reason reason) {
        s.bindingGeneration = new Object(); s.needsVerifiedBindings = true;
        if (s.roomOwner == null) return; // The generation/marker still fences a pending factory.
        if (terminal) { s.roomOwner.revokeRoute(s.roomOwner.snapshot()); s.roomOwner = null; }
        else s.roomOwner.invalidateBindings(s.roomOwner.snapshot(), reason);
    }
    /** A queued local request belongs to ONE route key, not a reusable ready/retry flag.
     * The original factory CAS stays strict; this job gets its own current ticket at entry.
     */
    private static final class RoomReconcile {
        final State state;
        final long epoch;
        final String scope, account;
        RoomReconcile(State state) {
            this.state = state; epoch = state.epoch; scope = state.scope; account = state.account;
        }
        boolean same(State current) {
            return current == state && current.epoch == epoch
                    && Objects.equals(current.scope, scope) && Objects.equals(current.account, account);
        }
    }
    /** Called AFTER releasing ROUTING. One queued job per current route key; no self-requeue,
     * wait, extra registration or HTTP. New content during its factory may request one next job.
     */
    private static void queueRoomReconcile(RoomReconcile request) {
        try {
            BChatStorageRepository.executor().execute(() -> {
                RoomRoute ticket;
                synchronized (ROUTING) {
                    State s = request.state;
                    if (s.roomReconcile == request) s.roomReconcile = null;
                    if (state != s || !request.same(s) || s.roomOwner != null) return;
                    ticket = roomRouteLocked(s); // Latest generation, but ONLY for this original key.
                }
                try { prepareRoomOwnerWorker(ticket); } catch (RuntimeException unavailable) { }
            });
        } catch (RuntimeException unavailable) {
            synchronized (ROUTING) {
                if (request.state.roomReconcile == request) request.state.roomReconcile = null;
            }
        }
    }
    /** Future Host read only: no initialization, I/O, room publication or write authorization. */
    static RoomRoute roomRoute(AccountScope verifiedScope) {
        synchronized (ROUTING) {
            State s = state;
            return s != null && active(s) && verifiedScope != null && verifiedScope.key.equals(s.scope)
                    && verifiedScope.key.equals(s.verifiedRAMScope) && s.roomOwner != null ? roomRouteLocked(s) : null;
        }
    }
    /** Existing immutable Route only; no new Authority, I/O or selected-room dependence.
     * Frame may have advanced normally, but the original process lifetime must still hold. */
    static BChatRoomMutePort.Route currentRoomBinding(RoomRoute lifetime, long roomId) {
        synchronized (ROUTING) {
            if (!currentRoomLifetimeLocked(lifetime) || !active(state)
                    || !Objects.equals(state.scope, state.verifiedRAMScope) || lifetime.roomOwner == null)
                return null;
            return lifetime.roomOwner.currentRoom(roomId);
        }
    }
    /** MAIN only. The full authenticated rooms reply must own ORIGINAL's captured Frame.
     * Owner copies/validates/hashes outside ROUTING; its final publication CAS is unchanged.
     * No caller may stamp an old reply with a newly observed route after a failed CAS. */
    static RoomPublication publishRoomRoutes(RoomRoute original, BChatRoomPreferencesOwner.VerifiedRoutes verified) {
        if (Looper.myLooper() != Looper.getMainLooper()) throw new IllegalStateException("Room publication requires MAIN");
        synchronized (ROUTING) {
            if (!currentRoomRouteLocked(original) || !active(state) || original.roomOwner == null
                    || !Objects.equals(state.scope, state.verifiedRAMScope))
                return new RoomPublication(BChatRoomPreferencesOwner.Kind.STALE, null);
        }
        BChatRoomPreferencesOwner.PublishResult published = original.roomOwner.publishVerifiedRoutes(original.frame, verified);
        synchronized (ROUTING) {
            if (!currentRoomLifetimeLocked(original) || !active(state)
                    || !Objects.equals(state.scope, state.verifiedRAMScope)
                    || original.roomOwner.snapshot() != published.frame)
                return new RoomPublication(BChatRoomPreferencesOwner.Kind.STALE, null);
            return new RoomPublication(published.kind, published.kind == BChatRoomPreferencesOwner.Kind.PUBLISHED
                    ? roomRouteLocked(state) : null);
        }
    }
    private static State current(Context context) {
        synchronized (ROUTING) { if (state != null) return state; }
        Context app = context.getApplicationContext();
        NotificationManager manager = app.getSystemService(NotificationManager.class);
        synchronized (ROUTING) {
            if (state == null) {
                state = new State(app, manager);
                State created = state;
                BChatStorageRepository.executor().execute(() -> load(created));
            }
            return state;
        }
    }
    /** Disk is initialized off main. A cold FCM callback may wait briefly on its worker thread. */
    public static boolean awaitReady(Context context, long timeoutMillis) {
        State s = current(context);
        if (Looper.myLooper() == Looper.getMainLooper()) return ready(context);
        try { s.loaded.await(Math.max(0, Math.min(3000, timeoutMillis)), TimeUnit.MILLISECONDS); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); return false; }
        synchronized (ROUTING) { return state == s && s.ready; }
    }
    public static boolean ready(Context context) {
        State s = current(context);
        synchronized (ROUTING) { return s.ready; }
    }
    private static void load(State s) {
        SharedPreferences prefs = null;
        String scope = null, account = null, token = null, registered = null, installation = null;
        String pendingScope = null, pendingInstallation = null, desired = null, controlUuid = null, controlAccount = null;
        long controlRevision = -1;
        boolean read = true;
        try {
            prefs = s.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            scope = prefs.getString(SCOPE, null); account = prefs.getString(ACCOUNT, null);
            token = prefs.getString(TOKEN, null); registered = prefs.getString(REGISTERED_TOKEN, null);
            installation = prefs.getString(INSTALLATION, null);
            pendingScope = prefs.getString(PREVIEW_SCOPE, null);
            pendingInstallation = prefs.getString(PREVIEW_INSTALLATION, null);
            desired = prefs.getString(PREVIEW_DESIRED, null);
            controlUuid = prefs.getString(CONTROL_UUID, null);
            controlAccount = prefs.getString(CONTROL_ACCOUNT, null);
            controlRevision = prefs.getLong(CONTROL_REVISION, -1);
        } catch (RuntimeException unavailable) { read = false; }
        try {
          RoomRoute room;
          synchronized (ROUTING) {
            if (state != s) return;
            s.prefs = prefs;
            boolean changedScope = s.scopeTouched && !Objects.equals(s.scope, scope);
            boolean changedToken = s.tokenTouched && !Objects.equals(s.token, token);
            if (!s.scopeTouched) s.scope = validScope(scope) ? scope : null;
            if (!s.tokenTouched) s.token = validToken(token) ? token : null;
            if (read && validUuid(installation) && !s.routeCleared && !changedScope && !changedToken
                    && s.scope != null && validUuid(account) && s.token != null && s.token.equals(registered)) {
                s.account = account; s.registeredToken = registered; s.routeDurable = true;
            }
            s.installation = validUuid(installation) ? installation : UUID.randomUUID().toString();
            s.savedInstallation = validUuid(installation) ? installation : null;
            // Never restore an opt-in from possibly stale/failed preference writes after process death.
            // Only a fresh authenticated preference response can enable sender/full in this process.
            s.preview = "none"; s.previewRevision = -1; s.storageHealthy = read;
            clearPresentationLocked(s); // Cold/unknown privacy must also retract earlier-process rich rows.
            if (read && validPreview(desired) && s.scope != null && s.scope.equals(pendingScope)
                    && s.installation.equals(pendingInstallation)) {
                s.previewDesired = desired; s.privacyScope = pendingScope; s.privacyInstallation = pendingInstallation;
                // A pending operation outlives token rotation and its temporarily absent route.
                // The next current registration rechecks controlAccount before any sendable ticket.
                if (validUuid(controlUuid) && validUuid(controlAccount)
                        && controlRevision > 0 && controlRevision < Integer.MAX_VALUE) {
                    s.controlUuid = controlUuid; s.controlAccount = controlAccount; s.controlRevision = controlRevision;
                    s.durableControl = controlFingerprint(s);
                    if (s.account != null && !s.account.equals(controlAccount)) {
                        // Contradictory routing hints require a fresh authenticated registration.
                        // Keep the operation until that response determines its rightful binding.
                        s.account = null; s.registeredToken = null; s.routeDurable = false; s.routeCleared = true;
                    }
                }
            }
            room = roomRouteLocked(s);
          }
          try { prepareRoomOwnerWorker(room); } catch (RuntimeException unavailable) { /* Unknown room index stays blocked. */ }
        } finally {
          synchronized (ROUTING) {
            try {
                if (state == s) {
                    s.ready = true;
                    if (s.scopeTouched || s.tokenTouched || s.routeCleared || !read || s.savedInstallation == null)
                        persistLocked(s, null);
                    changedLocked();
                }
            } finally {
                s.loaded.countDown(); // Includes failure to enqueue a final change notice/save.
            }
          }
        }
    }
    private static void invalidateRouteLocked(State s, boolean preservePrivacyIntent) {
        invalidateRoomOwnerLocked(s, !preservePrivacyIntent, BChatRoomPreferencesOwner.Reason.TOKEN_ROTATED);
        ++s.epoch; ++s.intent; s.routeCleared = true; s.routeDurable = false;
        s.account = null; s.registeredToken = null; s.preview = "none"; s.previewRevision = -1;
        if (!preservePrivacyIntent) {
            s.previewDesired = null; s.privacyScope = null; s.privacyInstallation = null;
            clearControlLocked(s);
        }
        clearPresentationLocked(s);
    }
    /** Only presentation is invalidated; authenticated registration/control tickets and sound claims survive. */
    private static void clearPresentationLocked(State s) {
        ++s.presentationSerial;
        BChatNotificationConversations.reset();
        BChatNotificationPresentationReset.cancel(s.notifications);
    }
    private static void previewLocked(State s, String mode) {
        if (rank(mode) < rank(s.preview)) clearPresentationLocked(s);
        s.preview = mode;
    }
    /** Called only after a current authenticated rights/membership result, never from a stale Activity. */
    public static void contentInvalidated(Context context, AccountScope scope) {
        State s = current(context);
        RoomReconcile request = null;
        synchronized (ROUTING) {
            // Retraction needs a current verified scope, not a durable delivery route. A same-binding
            // registration write temporarily disables routing but must never defer a rights reset.
            if (scope == null || !Objects.equals(scope.key, s.scope)
                    || !s.ready && !Objects.equals(scope.key, s.verifiedRAMScope)) return;
            invalidateRoomOwnerLocked(s, false, BChatRoomPreferencesOwner.Reason.RIGHTS_CHANGED);
            clearPresentationLocked(s);
            if (s.roomOwner == null && validScope(s.scope) && validUuid(s.account)
                    && (s.roomReconcile == null || !s.roomReconcile.same(s))) {
                request = new RoomReconcile(s); s.roomReconcile = request;
            }
        }
        if (request != null) queueRoomReconcile(request);
    }
    public static void verifiedAccount(Context context, AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        State s = current(context);
        synchronized (ROUTING) {
            s.verifiedRAMScope = account.key; // Also on the same-scope early-return path.
            if (account.key.equals(s.scope)) return;
            invalidateRouteLocked(s, false); s.scope = account.key; s.scopeTouched = true;
            persistLocked(s, null);
        }
    }
    public static void clearAccount(Context context) {
        State s = current(context);
        synchronized (ROUTING) {
            s.verifiedRAMScope = null;
            invalidateRouteLocked(s, false); s.scope = null; s.scopeTouched = true;
            persistLocked(s, null);
        }
    }
    public static String installationId(Context context) {
        State s = current(context);
        synchronized (ROUTING) {
            return s.ready && Objects.equals(s.installation, s.savedInstallation) ? s.installation : null;
        }
    }
    public static boolean needsRegistration(Context context, AccountScope account) {
        State s = current(context);
        synchronized (ROUTING) {
            return s.ready && account != null && account.key.equals(s.scope) && s.token != null
                    && (!s.routeDurable || s.account == null || !s.token.equals(s.registeredToken));
        }
    }
    /** Capture before the authenticated HTTP request, not after its response. */
    public static Registration registration(Context context, AccountScope account) {
        State s = current(context);
        synchronized (ROUTING) {
            return s.ready && account != null && account.key.equals(s.scope) && validToken(s.token)
                    && Objects.equals(s.installation, s.savedInstallation) ? new Registration(s) : null;
        }
    }
    private static boolean currentRegistration(Registration request) {
        State s = state;
        return request != null && s == request.owner && s.ready && s.epoch == request.epoch
                && s.registrationSerial == request.serial
                && Objects.equals(s.scope, request.scope) && Objects.equals(s.token, request.token)
                && Objects.equals(s.installation, request.installationId);
    }
    public static void registeredAsync(Context context, Registration request, String serverAccountKey, Ready<Boolean> callback) {
        current(context);
        synchronized (ROUTING) {
            if (!validUuid(serverAccountKey) || !currentRegistration(request)) {
                deliver(callback, false, false); return;
            }
            State s = state;
            if (s.roomOwner != null && (!s.scope.equals(s.roomOwner.scopeKey) || !serverAccountKey.equals(s.roomOwner.accountUuid))
                    || s.account != null && !serverAccountKey.equals(s.account))
                invalidateRoomOwnerLocked(s, true, BChatRoomPreferencesOwner.Reason.IDENTITY_CHANGED);
            boolean sameBinding = serverAccountKey.equals(s.account) && request.token.equals(s.registeredToken);
            s.account = serverAccountKey; s.registeredToken = request.token; s.routeDurable = false;
            if (!sameBinding) {
                clearPresentationLocked(s);
                s.preview = "none"; s.previewRevision = -1; ++s.intent;
                if (!Objects.equals(s.scope, s.privacyScope) || !Objects.equals(s.installation, s.privacyInstallation)
                        || s.controlAccount != null && !serverAccountKey.equals(s.controlAccount)) {
                    s.previewDesired = null; s.privacyScope = null; s.privacyInstallation = null;
                    clearControlLocked(s);
                }
            }
            persistLocked(s, saved -> MAIN.post(() -> {
                boolean accepted;
                synchronized (ROUTING) {
                    accepted = saved && currentRegistration(request) && serverAccountKey.equals(s.account) && s.routeDurable;
                }
                if (callback != null) callback.complete(accepted, accepted);
            }));
        }
    }
    public static String accountKey(Context context) {
        State s = current(context);
        synchronized (ROUTING) { return active(s) ? s.account : null; }
    }
    private static boolean active(State s) {
        return s.ready && s.routeDurable && s.scope != null && validUuid(s.account)
                && validToken(s.token) && s.token.equals(s.registeredToken);
    }
    public static boolean matches(Context context, String key) {
        State s = current(context);
        synchronized (ROUTING) { return validUuid(key) && active(s) && key.equals(s.account); }
    }
    public static String scopeForKey(Context context, String key) {
        State s = current(context);
        synchronized (ROUTING) { return validUuid(key) && active(s) && key.equals(s.account) ? s.scope : null; }
    }
    static Delivery delivery(Context context, String key) {
        State s = current(context);
        synchronized (ROUTING) { return validUuid(key) && active(s) && key.equals(s.account) ? new Delivery(s) : null; }
    }
    /** Room key is supplied only after the separately approved strict scoped-payload parser.
     * No guessing from titles or synthetic account/room identities. Existing unscoped API stays.
     */
    static Delivery roomDelivery(Context context, String key, String roomKey) {
        State s = current(context);
        synchronized (ROUTING) {
            return validUuid(key) && active(s) && key.equals(s.account) && BChatRoomMuteIndex.hash(roomKey)
                    && s.roomOwner != null ? new Delivery(s, roomKey) : null;
        }
    }
    /** No preferences/disk work in the gate. The callback may only build/post a notification. */
    static boolean present(Delivery delivery, Presentation presentation) {
        synchronized (ROUTING) {
            State s = state;
            if (delivery == null || s != delivery.owner || !active(s) || s.epoch != delivery.epoch
                    || s.presentationSerial != delivery.presentationSerial
                    || !delivery.account.equals(s.account)) return false;
            if (delivery.roomKey != null && (delivery.roomOwner == null || s.roomOwner != delivery.roomOwner
                    || delivery.roomOwner.blocks(delivery.roomFrame, delivery.scope, delivery.account, delivery.roomKey))) return false;
            presentation.show(s.preview);
            return true;
        }
    }
    static String previewMode(Context context, String accountKey) {
        State s = current(context);
        synchronized (ROUTING) { return active(s) && Objects.equals(accountKey, s.account) ? s.preview : "none"; }
    }
    static PreviewRequest previewRequest(Context context, String accountKey) {
        State s = current(context);
        synchronized (ROUTING) { return active(s) && Objects.equals(accountKey, s.account) ? new PreviewRequest(s) : null; }
    }
    private static boolean currentPreview(PreviewRequest request) {
        State s = state;
        return request != null && s == request.owner && active(s) && s.epoch == request.epoch
                && s.intent == request.intent && request.account.equals(s.account);
    }
    static boolean currentPreviewRequest(PreviewRequest request) {
        synchronized (ROUTING) { return currentPreview(request); }
    }
    /** Restriction takes effect now; caller receives a sendable ticket only after local commit succeeds. */
    static void beginPreviewChange(Context context, String key, String desired, Ready<PreviewRequest> callback) {
        State s = current(context);
        synchronized (ROUTING) {
            if (!active(s) || !Objects.equals(key, s.account) || !validPreview(desired) || s.controlUuid != null) {
                deliver(callback, null, false); return;
            }
            ++s.intent; s.previewDesired = desired; s.privacyScope = s.scope; s.privacyInstallation = s.installation;
            if (rank(desired) < rank(s.preview)) previewLocked(s, desired);
            PreviewRequest request = new PreviewRequest(s);
            persistLocked(s, saved -> MAIN.post(() -> {
                boolean valid;
                synchronized (ROUTING) { valid = saved && currentPreview(request); }
                if (callback != null) callback.complete(valid ? request : null, valid);
            }));
        }
    }
    static void acceptPreviewMode(Context context, PreviewRequest request, String mode, long revision, Ready<Boolean> callback) {
        current(context);
        synchronized (ROUTING) {
            if (!currentPreview(request) || state.controlUuid != null || !validPreview(mode) || revision < state.previewRevision
                    || revision < 0 || state.previewDesired != null && !state.previewDesired.equals(mode)
                    || revision == state.previewRevision && !state.preview.equals(mode)) {
                deliver(callback, false, false); return;
            }
            State s = state; previewLocked(s, mode); s.previewRevision = revision; s.previewDesired = null;
            s.privacyScope = null; s.privacyInstallation = null;
            persistLocked(s, saved -> MAIN.post(() -> {
                boolean valid;
                synchronized (ROUTING) { valid = saved && currentPreview(request) && mode.equals(s.preview); }
                if (callback != null) callback.complete(valid, valid);
            }));
        }
    }
    private static void clearControlLocked(State s) {
        s.controlUuid = null; s.controlAccount = null; s.controlRevision = -1; s.durableControl = null;
    }
    private static String controlFingerprint(State s) {
        if (!validUuid(s.controlUuid) || !validUuid(s.controlAccount) || !validScope(s.privacyScope)
                || !validUuid(s.privacyInstallation) || !validPreview(s.previewDesired)
                || s.controlRevision < 1 || s.controlRevision >= Integer.MAX_VALUE) return null;
        return s.controlUuid + "|" + s.controlAccount + "|" + s.privacyScope + "|"
                + s.privacyInstallation + "|" + s.previewDesired + "|" + s.controlRevision;
    }
    private static boolean currentControl(PreviewControl request) {
        State s = state;
        return request != null && s == request.owner && active(s) && s.epoch == request.epoch
                && s.intent == request.intent && request.accountKey.equals(s.account)
                && Objects.equals(s.installation, request.installationId)
                && request.fingerprint != null && request.fingerprint.equals(controlFingerprint(s));
    }
    static boolean currentPreviewControl(PreviewControl request) {
        synchronized (ROUTING) {
            return currentControl(request) && request.dispatchable && request.fingerprint.equals(state.durableControl);
        }
    }
    /** Metadata for the panel only. It is deliberately not a sendable HTTP ticket. */
    static PreviewControl pendingPreviewControl(Context context, String accountKey) {
        State s = current(context);
        synchronized (ROUTING) {
            return active(s) && Objects.equals(accountKey, s.account) && Objects.equals(s.controlAccount, s.account)
                    && Objects.equals(s.scope, s.privacyScope) && Objects.equals(s.installation, s.privacyInstallation)
                    && controlFingerprint(s) != null
                    ? new PreviewControl(s, false) : null;
        }
    }
    /** Called only from an explicit choice after a fresh validated GET captured by serverSnapshot. */
    static void beginPreviewControl(Context context, PreviewRequest serverSnapshot, String desired,
                                    long expectedRevision, Ready<PreviewControl> callback) {
        State s = current(context);
        synchronized (ROUTING) {
            if (!currentPreview(serverSnapshot) || !validPreview(desired) || expectedRevision < 1
                    || expectedRevision >= Integer.MAX_VALUE || s.controlUuid != null) {
                deliver(callback, null, false); return;
            }
            ++s.intent; s.previewDesired = desired; s.privacyScope = s.scope; s.privacyInstallation = s.installation;
            s.controlUuid = UUID.randomUUID().toString(); s.controlAccount = s.account;
            s.controlRevision = expectedRevision; s.durableControl = null;
            if (rank(desired) < rank(s.preview)) previewLocked(s, desired);
            saveControlTicketLocked(s, callback);
        }
    }
    /** Unknown outcomes retain the exact UUID, revision and payload, including after restart. */
    static void retryPreviewControl(Context context, String accountKey, Ready<PreviewControl> callback) {
        State s = current(context);
        synchronized (ROUTING) {
            if (!active(s) || !Objects.equals(accountKey, s.account) || controlFingerprint(s) == null
                    || !Objects.equals(s.scope, s.privacyScope) || !Objects.equals(s.installation, s.privacyInstallation)) {
                deliver(callback, null, false); return;
            }
            // Every dispatch proves this payload's own durable snapshot, not just a registered route.
            saveControlTicketLocked(s, callback);
        }
    }
    private static void saveControlTicketLocked(State s, Ready<PreviewControl> callback) {
        PreviewControl request = new PreviewControl(s, true);
        persistLocked(s, saved -> MAIN.post(() -> {
            boolean valid = saved && currentPreviewControl(request);
            if (callback != null) callback.complete(valid ? request : null, valid);
        }));
    }
    static void acceptPreviewControl(Context context, PreviewControl request, String mode, long revision,
                                     long operationRevision, Ready<Boolean> callback) {
        acceptPreviewControl(context, request, mode, revision, operationRevision, false, callback);
    }
    static void acceptPreviewControl(Context context, PreviewControl request, String mode, long revision,
                                     long operationRevision, boolean replayed, Ready<Boolean> callback) {
        current(context);
        synchronized (ROUTING) {
            if (!currentPreviewControl(request) || !validPreview(mode)
                    || operationRevision != request.expectedRevision + 1 || revision < operationRevision
                    || revision < state.previewRevision || revision >= Integer.MAX_VALUE
                    || revision == operationRevision && !request.mode.equals(mode)
                    || revision > operationRevision && !replayed) {
                deliver(callback, false, false); return;
            }
            State s = state;
            boolean superseded = revision > operationRevision;
            String acceptedMode = superseded && rank(mode) > rank(s.preview) ? s.preview : mode;
            previewLocked(s, acceptedMode); s.previewRevision = revision;
            // The original operation is proven, but its later replacement is not a new
            // opt-in by this UI. Keep the stricter ceiling across GET and process death.
            s.previewDesired = superseded ? acceptedMode : null;
            s.privacyScope = superseded ? s.scope : null;
            s.privacyInstallation = superseded ? s.installation : null; clearControlLocked(s);
            long acceptedIntent = ++s.intent, acceptedEpoch = s.epoch;
            persistLocked(s, saved -> MAIN.post(() -> {
                boolean valid;
                synchronized (ROUTING) {
                    valid = saved && state == s && active(s) && s.epoch == acceptedEpoch
                            && s.intent == acceptedIntent && s.controlUuid == null && acceptedMode.equals(s.preview);
                }
                if (callback != null) callback.complete(valid, valid);
            }));
        }
    }
    /** Only a definitive revision_conflict response may release this operation for a new choice. */
    static void rejectPreviewControl(Context context, PreviewControl request, Ready<Boolean> callback) {
        current(context);
        synchronized (ROUTING) {
            if (!currentPreviewControl(request)) { deliver(callback, false, false); return; }
            State s = state;
            // Keep the conservative ceiling until the next explicit choice is accepted.
            s.previewDesired = s.preview; s.privacyScope = s.scope; s.privacyInstallation = s.installation;
            clearControlLocked(s); long rejectedIntent = ++s.intent, rejectedEpoch = s.epoch;
            persistLocked(s, saved -> MAIN.post(() -> {
                boolean valid;
                synchronized (ROUTING) {
                    valid = saved && state == s && active(s) && s.epoch == rejectedEpoch
                            && s.intent == rejectedIntent && s.controlUuid == null;
                }
                if (callback != null) callback.complete(valid, valid);
            }));
        }
    }
    public static void token(Context context, String token) {
        if (!validToken(token)) return;
        State s = current(context);
        synchronized (ROUTING) {
            if (token.equals(s.token)) return;
            invalidateRouteLocked(s, true); s.token = token; s.tokenTouched = true; persistLocked(s, null);
        }
    }
    public static void clearToken(Context context) {
        State s = current(context);
        synchronized (ROUTING) {
            invalidateRouteLocked(s, true); s.token = null; s.tokenTouched = true; persistLocked(s, null);
        }
    }
    public static String pendingToken(Context context) {
        State s = current(context);
        synchronized (ROUTING) { return s.ready ? s.token : null; }
    }
    public static void observe(Context context, SharedPreferences.OnSharedPreferenceChangeListener listener) {
        current(context);
        synchronized (ROUTING) { OBSERVERS.put(listener, Boolean.TRUE); changedLocked(); }
    }
    public static void stopObserving(Context context, SharedPreferences.OnSharedPreferenceChangeListener listener) {
        synchronized (ROUTING) { OBSERVERS.remove(listener); }
    }
    private interface Saved { void complete(boolean saved); }
    /** Queue while holding ROUTING to preserve snapshot order; the worker never commits under it. */
    private static void persistLocked(State s, Saved callback) {
        if (!s.ready) return; // load merges memory intents and queues their first complete snapshot.
        final String scope = s.scope, account = s.account, token = s.token, registered = s.registeredToken;
        final String installation = s.installation, mode = s.preview, desired = s.previewDesired;
        final String privacyScope = s.privacyScope, privacyInstallation = s.privacyInstallation;
        final String controlUuid = s.controlUuid, controlAccount = s.controlAccount, controlFingerprint = controlFingerprint(s);
        final long controlRevision = s.controlRevision;
        final long revision = s.previewRevision, sequence = ++s.sequence, epoch = s.epoch;
        final RoomRoute room = roomRouteLocked(s);
        BChatStorageRepository.executor().execute(() -> {
            boolean saved;
            try {
                SharedPreferences.Editor edit = s.prefs.edit();
                put(edit, SCOPE, scope); put(edit, ACCOUNT, account); put(edit, TOKEN, token);
                put(edit, REGISTERED_TOKEN, registered); put(edit, INSTALLATION, installation);
                put(edit, PREVIEW_ACCOUNT, account); put(edit, PREVIEW_MODE, mode);
                put(edit, PREVIEW_DESIRED, desired);
                put(edit, PREVIEW_SCOPE, privacyScope); put(edit, PREVIEW_INSTALLATION, privacyInstallation);
                put(edit, CONTROL_UUID, controlUuid); put(edit, CONTROL_ACCOUNT, controlAccount);
                edit.putLong(CONTROL_REVISION, controlRevision);
                saved = edit.putLong(PREVIEW_REVISION, revision).commit();
            } catch (RuntimeException failure) { saved = false; }
            // Keep routing snapshot order unchanged; no new Owner task under ROUTING. The
            // current saved route gets its index attempt before routeDurable is accepted.
            if (saved) try { prepareRoomOwnerWorker(room); } catch (RuntimeException unavailable) { }
            synchronized (ROUTING) {
                if (state == s) {
                    s.storageHealthy = saved;
                    if (saved && epoch == s.epoch && Objects.equals(controlFingerprint, controlFingerprint(s)))
                        s.durableControl = controlFingerprint;
                    if (saved && Objects.equals(installation, s.installation)) s.savedInstallation = installation;
                    if (epoch == s.epoch && Objects.equals(scope, s.scope) && Objects.equals(account, s.account)
                            && Objects.equals(token, s.token) && Objects.equals(registered, s.registeredToken))
                        s.routeDurable = saved && validUuid(account);
                    // A failed broader preview write is never left enabled in RAM or restored on cold load.
                    if (!saved && sequence == s.sequence) { previewLocked(s, "none"); ++s.intent; }
                    changedLocked();
                }
            }
            if (callback != null) callback.complete(saved);
        });
    }
    private static void put(SharedPreferences.Editor edit, String key, String value) {
        if (value == null) edit.remove(key); else edit.putString(key, value);
    }
    private static <T> void deliver(Ready<T> callback, T value, boolean durable) {
        if (callback != null) MAIN.post(() -> callback.complete(value, durable));
    }
    private static void changedLocked() {
        MAIN.post(() -> {
            ArrayList<SharedPreferences.OnSharedPreferenceChangeListener> listeners;
            SharedPreferences prefs;
            synchronized (ROUTING) { listeners = new ArrayList<>(OBSERVERS.keySet()); prefs = state == null ? null : state.prefs; }
            if (prefs != null) for (SharedPreferences.OnSharedPreferenceChangeListener listener : listeners)
                listener.onSharedPreferenceChanged(prefs, "routing-state");
        });
    }
    private static boolean validScope(String value) { return value != null && value.matches("[0-9a-f]{64}"); }
    private static boolean validUuid(String value) {
        return value != null && value.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
    }
    private static boolean validToken(String value) {
        if (value == null || value.length() < 32 || value.length() > 4096) return false;
        for (int i = 0; i < value.length(); i++) if (value.charAt(i) < '!' || value.charAt(i) > '~') return false;
        return true;
    }
    private static boolean validPreview(String value) { return "none".equals(value) || "sender".equals(value) || "full".equals(value); }
    private static int rank(String value) { return "full".equals(value) ? 2 : "sender".equals(value) ? 1 : 0; }
    private BChatPushState() { }
}

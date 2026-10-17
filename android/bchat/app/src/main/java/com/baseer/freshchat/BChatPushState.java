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
        private Delivery(State owner) {
            this.owner = owner; account = owner.account; epoch = owner.epoch;
            presentationSerial = owner.presentationSerial;
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
        SharedPreferences prefs = s.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String scope = null, account = null, token = null, registered = null, installation = null;
        String pendingScope = null, pendingInstallation = null, desired = null, controlUuid = null, controlAccount = null;
        long controlRevision = -1;
        boolean read = true;
        try {
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
        synchronized (ROUTING) {
            if (state != s) { s.loaded.countDown(); return; }
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
            s.ready = true;
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
            if (s.scopeTouched || s.tokenTouched || s.routeCleared || !read || s.savedInstallation == null)
                persistLocked(s, null);
            s.loaded.countDown();
            changedLocked();
        }
    }
    private static void invalidateRouteLocked(State s, boolean preservePrivacyIntent) {
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
        synchronized (ROUTING) {
            // Retraction needs a current verified scope, not a durable delivery route. A same-binding
            // registration write temporarily disables routing but must never defer a rights reset.
            if (scope == null || !s.ready || !Objects.equals(scope.key, s.scope)) return;
            clearPresentationLocked(s);
        }
    }
    public static void verifiedAccount(Context context, AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        State s = current(context);
        synchronized (ROUTING) {
            if (account.key.equals(s.scope)) return;
            invalidateRouteLocked(s, false); s.scope = account.key; s.scopeTouched = true;
            persistLocked(s, null);
        }
    }
    public static void clearAccount(Context context) {
        State s = current(context);
        synchronized (ROUTING) {
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
    /** No preferences/disk work in the gate. The callback may only build/post a notification. */
    static boolean present(Delivery delivery, Presentation presentation) {
        synchronized (ROUTING) {
            State s = state;
            if (delivery == null || s != delivery.owner || !active(s) || s.epoch != delivery.epoch
                    || s.presentationSerial != delivery.presentationSerial
                    || !delivery.account.equals(s.account)) return false;
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

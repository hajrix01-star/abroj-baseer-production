package com.baseer.freshchat;

import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.BChatStorageRepository;
import java.io.File;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** Actual production State/Owner/Port/Index and actual JVM private index files. Explicit
 * preferences/Handler/repository-queue/Android/Gson adapters; reflection observes private
 * State and simulates a process-state reset or a Controller restriction, NOT authentication,
 * Android process death, HTTP, FCM parsing/presentation, OS notification or power loss.
 */
public final class PushOwnerCases {
    static final String ACCOUNT = "00000000-0000-4000-8000-000000000099";
    static final String OTHER = "00000000-0000-4000-8000-000000000098";
    static final String INSTALL = "00000000-0000-4000-8000-000000000077";
    static final String REQUEST = "00000000-0000-4000-8000-000000000001";
    static final String TOKEN_ID = "00000000-0000-4000-8000-000000000002";
    static final String TOKEN = String.join("", Collections.nCopies(40, "T"));
    static final String TOKEN2 = String.join("", Collections.nCopies(40, "U"));
    static File root;
    static int checks, next;
    static final Map<String, Integer> families = new LinkedHashMap<>();
    interface Action { void run() throws Exception; }
    static synchronized void check(boolean okay, String label) {
        ++checks; if (!okay) throw new AssertionError("Push Owner check " + checks + ": " + label);
    }
    static Object field(Object target, String name) throws Exception {
        Field f = (target == null ? BChatPushState.class : target.getClass()).getDeclaredField(name);
        f.setAccessible(true); return f.get(target);
    }
    static Object state() throws Exception { return field(null, "state"); }
    static BChatRoomPreferencesOwner owner() throws Exception { return (BChatRoomPreferencesOwner) field(state(), "roomOwner"); }
    static void noGate(String label) {
        try { check(!Thread.holdsLock(field(null, "ROUTING")), label); }
        catch (Exception failure) { throw new AssertionError(failure); }
    }
    static void workerOnly(String label) { check(Looper.myLooper() != Looper.getMainLooper(), label); noGate("No disk under ROUTING"); }
    static void flush() throws Exception { BChatStorageRepository.drain(); Handler.drain(); }
    static void resetState() throws Exception {
        flush(); Field f = BChatPushState.class.getDeclaredField("state"); f.setAccessible(true); f.set(null, null);
    }
    static void family(String name, Action work) throws Exception {
        int start = checks; work.run(); families.put(name, checks - start);
        System.out.println("FAMILY " + name + " PASS " + (checks - start));
    }
    static final class Pause {
        final CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        void stop() {
            entered.countDown();
            try { if (!release.await(4, TimeUnit.SECONDS)) throw new AssertionError("Fixture pause timeout"); }
            catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
        }
        void reached() throws Exception { check(entered.await(3, TimeUnit.SECONDS), "Worker reached exact fixture boundary"); }
    }
    static final class App extends Context {
        final File files;
        final Prefs prefs = new Prefs();
        final NotificationManager notifications = new NotificationManager();
        final AccountScope scope;
        final Object accountIdentity = new Object(), sessionIdentity = new Object();
        volatile Runnable factoryHook, fileHook;
        boolean failPreferences;
        int fileReads;
        App(boolean seeded) throws Exception {
            scope = new AccountScope("https://push-owner.invalid", "owner-fixture", 11);
            files = new File(root, "private-" + (++next)); Files.createDirectory(files.toPath());
            if (seeded) {
                prefs.memory.put("verified-account-scope", scope.key);
                prefs.memory.put("registered-account-key", ACCOUNT);
                prefs.memory.put("fcm-token", TOKEN); prefs.memory.put("registered-fcm-token", TOKEN);
                prefs.memory.put("installation-id", INSTALL); prefs.disk = new HashMap<>(prefs.memory);
            }
        }
        public Context getApplicationContext() {
            noGate("Factory/application lookup outside ROUTING");
            if (Looper.myLooper() != Looper.getMainLooper()) {
                Runnable hook = factoryHook; factoryHook = null; if (hook != null) hook.run();
            }
            return this;
        }
        public File getFilesDir() {
            workerOnly("Index files only on existing worker"); ++fileReads;
            Runnable hook = fileHook; fileHook = null; if (hook != null) hook.run(); return files;
        }
        public SharedPreferences getSharedPreferences(String name, int mode) {
            workerOnly("Preferences initialized off MAIN");
            if (failPreferences) throw new IllegalStateException("Synthetic preferences failure");
            return prefs;
        }
        @SuppressWarnings("unchecked") public <T> T getSystemService(Class<T> type) { return (T) notifications; }
        String key() { return NotificationPresentation.roomKey(ACCOUNT, 7, 17, 23); }
        File base() { return new File(files, "bchat-room-mute-index/" + scope.key + ".json"); }
        void seedFloor() throws Exception {
            BChatRoomMuteIndex index = new BChatRoomMuteIndex(this, scope.key, ACCOUNT);
            BChatStorageRepository.executor().execute(() -> check(index.put(key(), TOKEN_ID).kind == BChatRoomMuteIndex.Kind.COMMITTED, "Actual index seed committed"));
            BChatStorageRepository.one();
        }
        void start() { check(!BChatPushState.ready(this), "Cold State not ready before worker"); }
        void ready() throws Exception { start(); flush(); check(BChatPushState.ready(this), "Initialization completes"); }
        void publish() throws Exception {
            BChatRoomPreferencesOwner o = owner();
            check(o.publishVerifiedRoutes(o.snapshot(), new BChatRoomPreferencesOwner.VerifiedRoutes(scope,
                    accountIdentity, sessionIdentity, 1, 2, 1, Arrays.asList(7L),
                    Arrays.asList(new BChatRoomPreferencesOwner.RoomSpec(7, 17, 23)))).kind == BChatRoomPreferencesOwner.Kind.PUBLISHED,
                    "Explicit test trusted-context publication, not actual Host/auth");
        }
    }
    static final class Prefs implements SharedPreferences {
        Map<String, Object> memory = new HashMap<>(), disk = new HashMap<>();
        boolean fail;
        public String getString(String key, String fallback) { Object v = memory.get(key); return v == null ? fallback : (String) v; }
        public long getLong(String key, long fallback) { Object v = memory.get(key); return v == null ? fallback : (Long) v; }
        public Editor edit() { return new Edit(); }
        final class Edit implements Editor {
            final Map<String, Object> changes = new HashMap<>();
            public Editor putString(String key, String value) { changes.put(key, value); return this; }
            public Editor putLong(String key, long value) { changes.put(key, value); return this; }
            public Editor remove(String key) { changes.put(key, null); return this; }
            public boolean commit() {
                workerOnly("Preferences commit off MAIN");
                for (Map.Entry<String, Object> change : changes.entrySet())
                    if (change.getValue() == null) memory.remove(change.getKey()); else memory.put(change.getKey(), change.getValue());
                if (!fail) disk = new HashMap<>(memory); return !fail;
            }
        }
    }
    static App fresh(boolean seeded) throws Exception { resetState(); return new App(seeded); }
    static Thread oneAsync(AtomicReference<Throwable> failure) {
        Thread thread = new Thread(() -> { try { BChatStorageRepository.one(); } catch (Throwable t) { failure.set(t); } }, "fixture-lane-driver");
        thread.start(); return thread;
    }
    static void joined(Thread thread, AtomicReference<Throwable> failure) throws Exception {
        thread.join(5000); check(!thread.isAlive() && failure.get() == null, "Existing storage lane completes without deadlock: " + failure.get());
    }
    static void register(App app, AccountScope scope, String account) throws Exception {
        BChatPushState.verifiedAccount(app, scope); flush();
        BChatPushState.Registration request = BChatPushState.registration(app, scope);
        check(request != null, "Current registration request captured before response");
        AtomicBoolean accepted = new AtomicBoolean();
        BChatPushState.registeredAsync(app, request, account, (ok, durable) -> accepted.set(ok && durable));
        check(!BChatPushState.matches(app, account), "Saved route not accepted before current worker attempt");
        flush(); check(accepted.get() && BChatPushState.matches(app, account), "Routing registration independent of index health");
    }
    static boolean roomPresent(App app) {
        return BChatPushState.present(BChatPushState.roomDelivery(app, ACCOUNT, app.key()), mode -> { });
    }
    static void coldReadiness() throws Exception {
        check(BChatPushState.roomRoute(new AccountScope("https://push-owner.invalid", "owner-fixture", 11)) == null, "Pure getter before initialization does not create State");
        App app = fresh(true); Pause pause = new Pause(); app.fileHook = pause::stop; app.start();
        AtomicReference<Throwable> error = new AtomicReference<>(); Thread loader = oneAsync(error); pause.reached();
        check(!BChatPushState.ready(app) && !BChatPushState.awaitReady(app, 3000), "MAIN never waits for cold index");
        CountDownLatch waiting = new CountDownLatch(1), finished = new CountDownLatch(1); AtomicBoolean ready = new AtomicBoolean();
        Thread fcm = new Thread(() -> { waiting.countDown(); ready.set(BChatPushState.awaitReady(app, 3000)); finished.countDown(); }, "fixture-FCM-worker");
        fcm.start(); check(waiting.await(1, TimeUnit.SECONDS) && !finished.await(80, TimeUnit.MILLISECONDS), "Cold worker remains waiting until index attempt completes");
        pause.release.countDown(); joined(loader, error); fcm.join(3000); Handler.drain();
        check(!fcm.isAlive() && ready.get() && BChatPushState.matches(app, ACCOUNT), "Cold first delivery not lost at premature countDown");
        check(owner() != null && owner().snapshot().routes.isEmpty() && roomPresent(app), "Bare index absence permits scoped predicate without fake Binding");
        check(owner().port.health(null).status == BChatRoomMutePort.HealthStatus.UNKNOWN, "Missing Binding is never health READY");
        check(BChatPushState.roomRoute(app.scope) == null, "Preferences-only route is not verified RAM scope");
        int reads = app.fileReads;
        BChatPushState.verifiedAccount(app, app.scope);
        BChatPushState.RoomRoute observed = BChatPushState.roomRoute(app.scope);
        check(observed != null && observed.roomOwner == owner() && observed.frame == owner().snapshot(), "Same-scope verifiedAccount records RAM marker before return");
        check(app.fileReads == reads, "Host getter and marker are RAM-only");
    }
    static void failuresIndependent() throws Exception {
        for (int mode = 0; mode < 4; ++mode) {
            App app = fresh(true); app.seedFloor();
            byte[] bytes = Files.readAllBytes(app.base().toPath());
            if (mode == 0) Files.write(app.base().toPath(), new byte[0]);
            if (mode == 1) Files.write(app.base().toPath(), new byte[]{(byte) 0xc3, (byte) 0x28});
            if (mode == 2) Files.write(app.base().toPath(), new String(bytes, StandardCharsets.UTF_8).replace(ACCOUNT, OTHER).getBytes(StandardCharsets.UTF_8));
            if (mode == 3) app.factoryHook = () -> { throw new IllegalStateException("Synthetic index factory failure"); };
            app.ready();
            check(BChatPushState.matches(app, ACCOUNT), "Index failure does not fail unscoped routing: " + mode);
            check(BChatPushState.present(BChatPushState.delivery(app, ACCOUNT), preview -> { }), "Approved unscoped Delivery unchanged: " + mode);
            check(!roomPresent(app), "Corrupt/failing index remains scoped blocked: " + mode);
            if (mode == 3) app.factoryHook = () -> { throw new IllegalStateException("Synthetic repeated factory failure"); };
            register(app, app.scope, ACCOUNT);
            check(!roomPresent(app), "Registration does not turn index failure into unmute: " + mode);
            check(((CountDownLatch) field(state(), "loaded")).getCount() == 0, "Failure always completes readiness latch");
        }
        App failedPrefs = fresh(true); failedPrefs.failPreferences = true; failedPrefs.ready();
        check(!BChatPushState.matches(failedPrefs, ACCOUNT) && owner() == null, "Preferences failure completes readiness without restoring route");
        App rejectedNotice = fresh(true); rejectedNotice.start(); Handler.rejectNext = true;
        try { BChatStorageRepository.one(); check(false, "Rejected fixture MAIN notice was not reported"); }
        catch (AssertionError expected) { check(expected.getCause() instanceof java.util.concurrent.RejectedExecutionException, "Original queue rejection is not swallowed"); }
        check(((CountDownLatch) field(state(), "loaded")).getCount() == 0 && BChatPushState.ready(rejectedNotice), "Readiness countDown completes even when final change-notice scheduling throws");
    }
    static void tokenLifetime() throws Exception {
        App app = fresh(true); app.seedFloor(); app.ready(); BChatPushState.verifiedAccount(app, app.scope); app.publish();
        BChatRoomPreferencesOwner owner = owner(); BChatRoomMutePort port = owner.port;
        RoomPreferencesController.Binding binding = owner.snapshot().routes.get(17L).binding;
        byte[] before = Files.readAllBytes(app.base().toPath()); BChatPushState.Delivery old = BChatPushState.roomDelivery(app, ACCOUNT, app.key());
        Object generation = field(state(), "bindingGeneration");
        BChatPushState.token(app, TOKEN2);
        check(owner() == owner && owner.port == port && !binding.authority.valid(), "Token rotation preserves single Owner/Port but revokes bindings first");
        check(field(state(), "bindingGeneration") != generation && Boolean.TRUE.equals(field(state(), "needsVerifiedBindings")), "Token changes opaque fence and marker");
        check(!BChatPushState.present(old, mode -> { }) && !owner.snapshot().scopedAvailable, "Old delivery/Frame blocked before re-registration");
        flush(); register(app, app.scope, ACCOUNT);
        check(owner() == owner && !owner.snapshot().scopedAvailable && !roomPresent(app), "Same route registration/index read cannot rearm invalidated Frame");
        check(Arrays.equals(before, Files.readAllBytes(app.base().toPath())), "Token lifetime never clears/replaces durable floor");
        BChatPushState.clearToken(app); flush(); check(owner() == owner && !BChatPushState.matches(app, ACCOUNT), "clearToken retains floor owner with routing inactive");
    }
    static void terminalLifetime() throws Exception {
        App app = fresh(true); app.seedFloor(); app.ready(); BChatPushState.verifiedAccount(app, app.scope); app.publish();
        BChatRoomPreferencesOwner first = owner(); RoomPreferencesController.Binding old = first.snapshot().routes.get(17L).binding;
        byte[] before = Files.readAllBytes(app.base().toPath());
        register(app, app.scope, OTHER);
        check(first.snapshot().revoked && !old.authority.valid() && owner() != first && owner().accountUuid.equals(OTHER), "Different registered UUID terminally revokes old Owner");
        check(!owner().snapshot().scopedAvailable && Arrays.equals(before, Files.readAllBytes(app.base().toPath())), "New UUID cannot inherit ready status or erase old index");
        BChatRoomPreferencesOwner second = owner(); BChatPushState.clearAccount(app);
        check(second.snapshot().revoked && owner() == null && field(state(), "verifiedRAMScope") == null, "Logout revokes and detaches before scope clear");
        flush(); AccountScope another = new AccountScope("https://another.invalid", "other-fixture", 12);
        BChatPushState.verifiedAccount(app, another); flush(); register(app, another, ACCOUNT);
        check(owner() != first && owner() != second && owner().scopeKey.equals(another.key), "Different scope owns independent fixed route");
        check(first.publishVerifiedRoutes(first.snapshot(), null).kind == BChatRoomPreferencesOwner.Kind.REVOKED, "Terminal old Owner never revived by later registration");
    }
    static void preReadyFactoryFence() throws Exception {
        App unverified = fresh(true); Pause noMarker = new Pause(); unverified.factoryHook = noMarker::stop; unverified.start();
        AtomicReference<Throwable> error = new AtomicReference<>(); Thread loader = oneAsync(error); noMarker.reached();
        Object generation = field(state(), "bindingGeneration");
        BChatPushState.contentInvalidated(unverified, unverified.scope);
        check(field(state(), "bindingGeneration") == generation && !((Boolean) field(state(), "needsVerifiedBindings")), "Prefs-only scope cannot claim pre-ready authenticated content invalidation");
        noMarker.release.countDown(); joined(loader, error); Handler.drain();
        check(roomPresent(unverified), "Ignored unverified pre-ready call does not invent a restriction");

        App app = fresh(true); Pause pause = new Pause(); app.factoryHook = pause::stop; app.start();
        error = new AtomicReference<>(); loader = oneAsync(error); pause.reached();
        generation = field(state(), "bindingGeneration");
        BChatPushState.verifiedAccount(app, app.scope); // RAM marker set even though loaded scope already matches.
        BChatPushState.contentInvalidated(app, app.scope);
        check(field(state(), "bindingGeneration") != generation && Boolean.TRUE.equals(field(state(), "needsVerifiedBindings")), "Pre-ready current verified RAM invalidation fenced even with Owner null");
        pause.release.countDown(); joined(loader, error); Handler.drain();
        check(owner() == null && BChatPushState.ready(app), "Stale in-flight factory cannot attach fresh cold Owner");
        check(!BChatPushState.needsRegistration(app, app.scope) && INSTALL.equals(BChatPushState.installationId(app)), "Seeded healthy route does not trigger network registration to repair missing Owner");
        flush(); // Only the existing lane: no register, persist or manual ensure.
        check(owner() != null && !owner().snapshot().scopedAvailable && !roomPresent(app), "Local reconciliation attaches blocked Owner without manual registration/persist/ensure");
        check(Boolean.TRUE.equals(field(state(), "needsVerifiedBindings")), "Registration/index never reset binding marker");

        App before = fresh(true); before.start(); BChatPushState.verifiedAccount(before, before.scope); BChatPushState.contentInvalidated(before, before.scope);
        flush(); register(before, before.scope, ACCOUNT);
        check(!owner().snapshot().scopedAvailable, "Invalidation before any factory survives first Owner construction");
        reconcileCoalescing(); reconcileRejection(); reconcileTerminalKey();
    }
    static void reconcileCoalescing() throws Exception {
        App app = fresh(true); Pause initial = new Pause(); app.factoryHook = initial::stop; app.start();
        AtomicReference<Throwable> error = new AtomicReference<>(); Thread loader = oneAsync(error); initial.reached();
        BChatPushState.verifiedAccount(app, app.scope);
        int queued = BChatStorageRepository.queued;
        BChatStorageRepository.onEnqueue = () -> noGate("Reconcile enqueue occurs only after ROUTING release");
        for (int i = 0; i < 3; ++i) BChatPushState.contentInvalidated(app, app.scope);
        BChatStorageRepository.onEnqueue = null;
        check(BChatStorageRepository.queued == queued + 1 && BChatStorageRepository.pending() == 1, "Three same-key invalidations coalesce to one existing-lane job");
        initial.release.countDown(); joined(loader, error); Handler.drain();
        check(owner() == null && !BChatPushState.needsRegistration(app, app.scope), "Original factory CAS stays strict; route does not need registration");
        Pause second = new Pause(); app.factoryHook = second::stop;
        error = new AtomicReference<>(); Thread firstReconcile = oneAsync(error); second.reached();
        check(field(state(), "roomReconcile") == null, "Job consumes only its token before starting fresh same-key factory");
        BChatStorageRepository.onEnqueue = () -> noGate("Successor reconcile enqueue outside ROUTING");
        BChatPushState.contentInvalidated(app, app.scope); BChatPushState.contentInvalidated(app, app.scope);
        BChatStorageRepository.onEnqueue = null;
        check(BChatStorageRepository.queued == queued + 2 && BChatStorageRepository.pending() == 1, "Content during factory permits exactly one subsequent job");
        second.release.countDown(); joined(firstReconcile, error); Handler.drain();
        check(owner() == null && BChatStorageRepository.pending() == 1, "Stale reconcile factory neither attaches nor self-requeues");
        flush();
        check(owner() != null && !owner().snapshot().scopedAvailable && BChatStorageRepository.pending() == 0
                && BChatStorageRepository.queued == queued + 2, "One successor converges to blocked Owner with no loop or extra dispatch");
        check(!BChatPushState.needsRegistration(app, app.scope) && !roomPresent(app), "Convergence uses no registration/persist/manual ensure and no cold allowance");
    }
    static void reconcileRejection() throws Exception {
        App app = fresh(true); Pause initial = new Pause(); app.factoryHook = initial::stop; app.start();
        AtomicReference<Throwable> error = new AtomicReference<>(); Thread loader = oneAsync(error); initial.reached();
        BChatPushState.verifiedAccount(app, app.scope); int queued = BChatStorageRepository.queued;
        BChatStorageRepository.rejectNext = true;
        BChatStorageRepository.onEnqueue = () -> noGate("Rejected reconcile scheduling still outside ROUTING");
        BChatPushState.contentInvalidated(app, app.scope); BChatStorageRepository.onEnqueue = null;
        check(field(state(), "roomReconcile") == null && BChatStorageRepository.queued == queued, "Scheduling rejection releases only its own token");
        initial.release.countDown(); joined(loader, error); Handler.drain();
        check(owner() == null && !roomPresent(app) && !BChatPushState.needsRegistration(app, app.scope), "Rejected reconcile stays unknown/blocked, not false cold allowance");
        BChatPushState.contentInvalidated(app, app.scope);
        check(field(state(), "roomReconcile") != null && BChatStorageRepository.queued == queued + 1, "Later explicit content request can enqueue after rejection");
        flush(); check(owner() != null && !owner().snapshot().scopedAvailable && field(state(), "roomReconcile") == null, "Next request converges without a leaked rejection token");
    }
    static void reconcileTerminalKey() throws Exception {
        App app = fresh(true); Pause initial = new Pause(); app.factoryHook = initial::stop; app.start();
        AtomicReference<Throwable> error = new AtomicReference<>(); Thread loader = oneAsync(error); initial.reached();
        BChatPushState.verifiedAccount(app, app.scope); BChatPushState.contentInvalidated(app, app.scope);
        Object oldToken = field(state(), "roomReconcile");
        initial.release.countDown(); joined(loader, error); Handler.drain();
        BChatPushState.clearAccount(app);
        AccountScope nextScope = new AccountScope("https://next-owner.invalid", "next-fixture", 19);
        BChatPushState.verifiedAccount(app, nextScope);
        BChatPushState.Registration request = BChatPushState.registration(app, nextScope);
        check(request != null, "Legitimate new-identity registration ticket, not old-route repair");
        BChatPushState.registeredAsync(app, request, OTHER, (ok, durable) -> { });
        BChatPushState.contentInvalidated(app, nextScope);
        Object nextToken = field(state(), "roomReconcile");
        check(nextToken != null && nextToken != oldToken && nextScope.key.equals(field(nextToken, "scope")), "Old terminal key cannot suppress new State/epoch/scope/UUID request");
        BChatStorageRepository.one(); Handler.drain(); // Old-key job was first in this existing lane.
        check(field(state(), "roomReconcile") == nextToken && owner() == null, "Old-key job clears neither newer token nor newer route");
        flush(); check(owner() != null && owner().scopeKey.equals(nextScope.key) && owner().accountUuid.equals(OTHER)
                && !owner().snapshot().scopedAvailable && field(state(), "roomReconcile") == null, "Only new-key reconciliation can install its blocked Owner");
    }
    static void staleWorkers() throws Exception {
        App app = fresh(true); Pause pause = new Pause(); app.factoryHook = pause::stop; app.start();
        AtomicReference<Throwable> error = new AtomicReference<>(); Thread loader = oneAsync(error); pause.reached();
        Object oldState = state();
        Field stateField = BChatPushState.class.getDeclaredField("state"); stateField.setAccessible(true); stateField.set(null, null);
        App nextApp = new App(true); nextApp.prefs.memory.put("registered-account-key", OTHER); nextApp.start();
        pause.release.countDown(); joined(loader, error); flush();
        check(((CountDownLatch) field(oldState, "loaded")).getCount() == 0 && field(oldState, "roomOwner") == null, "Obsolete State worker finishes latch without attaching Owner");
        check(owner() != null && owner().accountUuid.equals(OTHER) && BChatPushState.matches(nextApp, OTHER), "Old State cannot publish into current State");

        App registration = fresh(true); registration.ready(); BChatPushState.verifiedAccount(registration, registration.scope);
        BChatPushState.Registration first = BChatPushState.registration(registration, registration.scope);
        BChatPushState.Registration second = BChatPushState.registration(registration, registration.scope);
        AtomicBoolean rejected = new AtomicBoolean();
        BChatPushState.registeredAsync(registration, first, OTHER, (ok, durable) -> rejected.set(!ok && !durable));
        Handler.drain(); check(rejected.get() && owner().accountUuid.equals(ACCOUNT), "Older registration cannot change Owner UUID");
        BChatRoomPreferencesOwner current = owner();
        BChatPushState.registeredAsync(registration, second, ACCOUNT, (ok, durable) -> { });
        BChatPushState.token(registration, TOKEN2); flush();
        check(owner() == current && !BChatPushState.matches(registration, ACCOUNT) && !current.snapshot().scopedAvailable, "Old saved snapshot/Owner prelude cannot reactivate newer token epoch");
    }
    static void contentVersusPreview() throws Exception {
        App app = fresh(true); app.ready(); BChatPushState.verifiedAccount(app, app.scope); app.publish();
        BChatRoomPreferencesOwner owner = owner(); BChatRoomPreferencesOwner.Frame frame = owner.snapshot();
        RoomPreferencesController.Binding binding = frame.routes.get(17L).binding; Object generation = field(state(), "bindingGeneration");
        BChatPushState.acceptPreviewMode(app, BChatPushState.previewRequest(app, ACCOUNT), "full", 1, (ok, durable) -> { }); flush();
        BChatPushState.beginPreviewChange(app, ACCOUNT, "none", (ticket, durable) -> { }); flush();
        check(owner.snapshot() == frame && binding.authority.valid() && field(state(), "bindingGeneration") == generation, "Preview/presentation-only restriction does not revoke room Authorities");
        AccountScope foreign = new AccountScope("https://foreign.invalid", "wrong", 2);
        BChatPushState.contentInvalidated(app, foreign);
        check(owner.snapshot() == frame && field(state(), "bindingGeneration") == generation, "Foreign content invalidation is no-op");
        BChatPushState.Delivery old = BChatPushState.roomDelivery(app, ACCOUNT, app.key());
        BChatPushState.Registration request = BChatPushState.registration(app, app.scope);
        BChatPushState.registeredAsync(app, request, ACCOUNT, (ok, durable) -> { });
        check(!BChatPushState.matches(app, ACCOUNT), "Registration pending during current rights invalidation");
        BChatPushState.contentInvalidated(app, app.scope);
        check(owner() == owner && !binding.authority.valid() && owner.snapshot() != frame, "Current rights invalidation does not wait for durable delivery route");
        flush(); check(!BChatPushState.present(old, mode -> { }) && !roomPresent(app), "Old callback cannot borrow newly invalidated Frame");
    }
    static RoomPreferencesController.RestrictionTicket restriction(RoomPreferencesController.Binding binding, RoomPreferencesProtocol.Pending pending) throws Exception {
        Class<?> ticket = Class.forName("com.baseer.freshchat.RoomPreferencesController$Ticket");
        Constructor<?> ctor = ticket.getDeclaredConstructor(RoomPreferencesController.Binding.class, long.class); ctor.setAccessible(true);
        Constructor<?> target = RoomPreferencesController.RestrictionTicket.class.getDeclaredConstructor(ticket, RoomPreferencesProtocol.Pending.class, RoomPreferencesController.RestrictionReason.class);
        target.setAccessible(true); return (RoomPreferencesController.RestrictionTicket) target.newInstance(ctor.newInstance(binding, 1L), pending, RoomPreferencesController.RestrictionReason.USER_INTENT);
    }
    static void finalPredicate() throws Exception {
        App app = fresh(true); app.ready();
        check(BChatPushState.roomDelivery(app, OTHER, app.key()) == null && BChatPushState.roomDelivery(app, ACCOUNT, "bad") == null,
                "Room Delivery requires current registered UUID and strict existing key shape");
        BChatPushState.Delivery beforePublication = BChatPushState.roomDelivery(app, ACCOUNT, app.key());
        BChatPushState.verifiedAccount(app, app.scope); app.publish();
        check(!BChatPushState.present(beforePublication, mode -> { }), "Final guard refuses captured old Frame after valid new publication");
        BChatPushState.Delivery current = BChatPushState.roomDelivery(app, ACCOUNT, app.key());
        check(BChatPushState.present(current, mode -> check(Thread.holdsLock(lock()), "Actual final presentation callback holds ROUTING")), "Current bare predicate allows no-floor delivery");
        BChatRoomPreferencesOwner owner = owner(); RoomPreferencesController.Binding binding = owner.snapshot().routes.get(17L).binding;
        JSONObject body = new JSONObject().put("api_version", 2).put("room_id", 17).put("membership_id", 23).put("revision", 1)
                .put("muted_until", JSONObject.NULL).put("mute_forever", false).put("muted", false)
                .put("pinned", false).put("pinned_at", JSONObject.NULL).put("archived", false);
        RoomPreferencesProtocol.Pending pending = RoomPreferencesProtocol.newPending(RoomPreferencesProtocol.freshSnapshot(body, app.scope, 17, 23), REQUEST, null, true, false, false);
        Object admission = owner.port.prepare(restriction(binding, pending));
        check(admission != null && !BChatPushState.present(current, mode -> { }), "Immediate Port RAM floor and final Delivery share exact reentrant ROUTING gate");
        check(!owner.port.currentDurable(admission, binding, pending), "No invented durable admission before actual index commit");
        java.util.List<BChatRoomMutePort.Health> delivered = new java.util.ArrayList<>();
        BChatRoomMutePort.HealthObserver listener = delivered::add;
        Handler.falseNext = true;
        BChatRoomMutePort.Subscription rejected = owner.port.observe(binding, listener);
        check(Boolean.TRUE.equals(field(rejected, "closed")) && Boolean.FALSE.equals(field(rejected, "queued")), "MAIN.post(false) closes failed subscription instead of leaving queued forever");
        Handler.drain(); check(delivered.isEmpty(), "Rejected health notice never fabricates callback/readiness");
        BChatRoomMutePort.Subscription accepted = owner.port.observe(binding, listener);
        Handler.drain();
        check(delivered.size() == 1 && delivered.get(0).status == BChatRoomMutePort.HealthStatus.UNKNOWN && delivered.get(0).effectiveBlocked,
                "New accepted observer sees actual unknown/blocked admission, not false READY");
        flush(); check(owner.port.currentDurable(admission, binding, pending) && !roomPresent(app), "Committed exact floor still suppresses scoped presentation");
        check(delivered.get(delivered.size() - 1).effectiveBlocked, "Persisted health notice cannot release existing floor"); accepted.close();
        BChatPushState.clearAccount(app); flush(); check(!BChatPushState.present(current, mode -> { }), "Old Delivery never crosses terminal account lifetime");
    }
    static Object lock() {
        try { return field(null, "ROUTING"); } catch (Exception failure) { throw new AssertionError(failure); }
    }
    public static void main(String[] args) throws Exception {
        root = new File(args[0]); Looper.getMainLooper(); resetState();
        String selection = args.length > 1 ? args[1] : "all";
        if (selection.equals("factory-reconcile")) family("pre-ready-marker-factory-cas", PushOwnerCases::preReadyFactoryFence);
        else if (selection.equals("health-post")) family("captured-frame-final-predicate", PushOwnerCases::finalPredicate);
        else {
        family("cold-readiness-bare-index", PushOwnerCases::coldReadiness);
        family("failure-unscoped-independence", PushOwnerCases::failuresIndependent);
        family("token-owner-floor-lifetime", PushOwnerCases::tokenLifetime);
        family("terminal-scope-uuid-lifetime", PushOwnerCases::terminalLifetime);
        family("pre-ready-marker-factory-cas", PushOwnerCases::preReadyFactoryFence);
        family("stale-state-registration-workers", PushOwnerCases::staleWorkers);
        family("content-versus-preview", PushOwnerCases::contentVersusPreview);
        family("captured-frame-final-predicate", PushOwnerCases::finalPredicate);
        }
        JSONObject counts = new JSONObject(); for (Map.Entry<String, Integer> family : families.entrySet()) counts.put(family.getKey(), family.getValue());
        JSONObject result = new JSONObject().put("schema", 1).put("assertions", checks).put("families", counts)
                .put("scope", "Actual State/Owner/Port/Index and JVM private index files; declared Android/preferences/queue/Gson/reflection adapters; no Android/HTTP/auth/FCM/Activity/power-loss");
        Files.write(new File(root, "push-owner-results.json").toPath(), result.toString().getBytes(StandardCharsets.UTF_8));
        System.out.println("PASS " + checks + " production PushState room Owner assertions; " + families.size() + " focused families");
    }
}

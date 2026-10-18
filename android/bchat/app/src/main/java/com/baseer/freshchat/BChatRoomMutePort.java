package com.baseer.freshchat;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** DEV114 component only. No Activity, FCM, PushState, notifications or authentication.
 * One account Mirror owns exactly one injected RAM gate. The later application owner must
 * share this Mirror, and enqueue on the SAME existing StorageRepository lane as Controller.
 * RouteSource is a thread-safe verified RAM projection, not ordinary Activity fields.
 */
final class BChatRoomMutePort implements RoomPreferencesController.MutePort {
    enum HealthStatus { UNKNOWN, READY, CLEARING, FAILED }
    enum DurableFloor { UNKNOWN, OFF, ON }
    /** Display/read health only. Not an Admission, authenticated GET or unmute proof. */
    static final class Health {
        final long revision;
        final HealthStatus status;
        final DurableFloor durableFloor;
        final boolean effectiveBlocked;
        private final Mirror owner;
        private final Route route;
        private Health(Mirror owner, Route route, long revision, HealthStatus status,
                DurableFloor floor, boolean blocked) {
            this.owner = owner; this.route = route; this.revision = revision;
            this.status = status; durableFloor = floor; effectiveBlocked = blocked;
        }
    }
    interface HealthObserver { void changed(Health health); }
    static final class Subscription implements AutoCloseable {
        private final WeakReference<BChatRoomMutePort> owner;
        private final WeakReference<HealthObserver> observer;
        private final RoomPreferencesController.Binding binding;
        private final Route route;
        // Access only under the account's existing Mirror.gate.
        private boolean closed, queued;
        private long deliveredRevision = -1;
        private Subscription(BChatRoomMutePort owner, RoomPreferencesController.Binding binding,
                Route route, HealthObserver observer) {
            this.owner = new WeakReference<>(owner); this.binding = binding;
            this.route = route; this.observer = new WeakReference<>(observer);
        }
        public void close() {
            BChatRoomMutePort port = owner.get();
            if (port != null) port.closeSubscription(this);
        }
    }
    interface Value<T> { T get(); }
    interface Gate { <T> T run(Value<T> value); }
    /** Component default/test gate; later ROUTING integration is separately reviewed. */
    static final class MonitorGate implements Gate {
        public synchronized <T> T run(Value<T> value) { return value.get(); }
    }
    static final class Route {
        final RoomPreferencesController.Binding binding;
        final String accountUuid, roomKey;
        final long companyId;
        Route(RoomPreferencesController.Binding binding, String accountUuid, long companyId) {
            if (binding == null || !BChatRoomMuteIndex.uuid(accountUuid)) throw new IllegalArgumentException("Current registered route required");
            this.binding = binding; this.accountUuid = accountUuid; this.companyId = companyId;
            roomKey = NotificationPresentation.roomKey(accountUuid, companyId, binding.roomId, binding.membershipId);
        }
    }
    interface RouteSource {
        /** Called OUTSIDE the RAM gate, on MAIN or worker. Must be an atomic verified mirror.
         * company/registered UUID come from current authorized binding, never names/payload. */
        Route current(RoomPreferencesController.Binding expected);
    }
    static final class Mirror {
        final String scopeKey, accountUuid;
        private final Gate gate;
        private final Map<String, Cell> cells = new HashMap<>();
        private final List<Subscription> subscriptions = new ArrayList<>();
        private boolean known, failed;
        private long healthRevision;
        private Object change = new Object();
        private BChatRoomMuteIndex.Kind loadKind;
        Mirror(String scopeKey, String accountUuid, Gate gate) {
            if (!BChatRoomMuteIndex.hash(scopeKey) || !BChatRoomMuteIndex.uuid(accountUuid) || gate == null)
                throw new IllegalArgumentException("Scoped fixed RAM gate required");
            this.scopeKey = scopeKey; this.accountUuid = accountUuid; this.gate = gate;
        }
    }
    private static final class Cell {
        String indexToken;
        boolean floor, tokenDurable;
        Checkpoint checkpoint;
        Checkpoint clearing;
        Admission admission;
        Cell(String token) { indexToken = token; floor = token != null; tokenDurable = true; }
    }
    /** Immutable actual-dispatch checkpoint. Its token is the only expected token for clear. */
    private static final class Checkpoint {
        final Route route;
        final String expectedIndexToken;
        Checkpoint(Route route, String token) { this.route = route; expectedIndexToken = token; }
    }
    private static final class Admission {
        final RoomPreferencesController.Binding binding;
        final RoomPreferencesProtocol.Pending pending;
        final Checkpoint checkpoint;
        final boolean writeFloor;
        boolean durable; // Only under Mirror.gate, never a generic RPC permission.
        Admission(RoomPreferencesController.RestrictionTicket ticket, Checkpoint checkpoint, boolean writeFloor) {
            binding = ticket.binding; pending = ticket.pending; this.checkpoint = checkpoint; this.writeFloor = writeFloor;
        }
    }
    private final BChatRoomMuteIndex index;
    private final Mirror mirror;
    private final WeakReference<RouteSource> source;
    private final RoomPreferencesController.Scheduler scheduler;

    BChatRoomMutePort(BChatRoomMuteIndex index, Mirror mirror, RouteSource source,
            RoomPreferencesController.Scheduler scheduler) {
        if (index == null || mirror == null || source == null || scheduler == null
                || !index.scopeKey.equals(mirror.scopeKey) || !index.accountUuid.equals(mirror.accountUuid))
            throw new IllegalArgumentException("Same account index/mirror and current ports required");
        this.index = index; this.mirror = mirror; this.source = new WeakReference<>(source); this.scheduler = scheduler;
    }

    /** Explicit cold worker load before controls/scoped-notification admission. No automatic
     * repair or eviction. Once used, this mirror is not silently replaced by a later disk read. */
    BChatRoomMuteIndex.Kind loadColdWorker() {
        if (scheduler.isMain()) throw new IllegalStateException("Cold index load requires worker");
        Object fence = mirror.gate.run(() -> mirror.known || !mirror.cells.isEmpty() ? null : mirror.change);
        if (fence == null) return mirror.gate.run(() -> mirror.known ? mirror.loadKind : BChatRoomMuteIndex.Kind.IO_FAILURE);
        BChatRoomMuteIndex.Result loaded = index.load(); // No RAM gate around disk.
        BChatRoomMuteIndex.Kind result = mirror.gate.run(() -> {
            if (mirror.change != fence) return BChatRoomMuteIndex.Kind.IO_FAILURE;
            if (!loaded.readable()) {
                mirror.known = false; mirror.failed = true; mirror.loadKind = loaded.kind;
                changedLocked(); return loaded.kind;
            }
            for (Map.Entry<String, String> entry : loaded.state.floors.entrySet()) mirror.cells.put(entry.getKey(), new Cell(entry.getValue()));
            mirror.known = true; mirror.failed = false; mirror.loadKind = loaded.kind;
            changedLocked(); return loaded.kind;
        });
        publishHealth(); return result;
    }

    /** Pure RAM observation: in particular, an absent cell is NOT allocated by this read. */
    Health health(RoomPreferencesController.Binding binding) {
        Route current = route(binding); // Host/RouteSource is never called inside Mirror.gate.
        return mirror.gate.run(() -> healthLocked(current));
    }
    boolean isCurrent(Health health, RoomPreferencesController.Binding binding) {
        if (health == null || health.owner != mirror || !sameRoute(route(binding), health.route)) return false;
        return mirror.gate.run(() -> binding.authority.valid() && health.revision == mirror.healthRevision);
    }
    Subscription observe(RoomPreferencesController.Binding binding, HealthObserver observer) {
        if (binding == null || observer == null) throw new IllegalArgumentException("Binding and observer required");
        Subscription subscription = new Subscription(this, binding, route(binding), observer);
        mirror.gate.run(() -> {
            pruneSubscriptionsLocked();
            if (mirror.subscriptions.size() >= BChatRoomMuteIndex.MAX_ENTRIES)
                throw new IllegalStateException("Too many scoped health observers");
            mirror.subscriptions.add(subscription); return null;
        });
        publishHealth(); return subscription;
    }
    private Health healthLocked(Route current) {
        if (current == null || !current.binding.authority.valid())
            return new Health(mirror, current, mirror.healthRevision, HealthStatus.UNKNOWN, DurableFloor.UNKNOWN, true);
        if (!mirror.known) return new Health(mirror, current, mirror.healthRevision,
                mirror.failed ? HealthStatus.FAILED : HealthStatus.UNKNOWN, DurableFloor.UNKNOWN, true);
        Cell cell = mirror.cells.get(current.roomKey);
        if (cell != null && !cell.tokenDurable)
            return new Health(mirror, current, mirror.healthRevision, HealthStatus.UNKNOWN, DurableFloor.UNKNOWN, true);
        boolean floor = cell != null && cell.floor;
        return new Health(mirror, current, mirror.healthRevision,
                cell != null && cell.clearing != null ? HealthStatus.CLEARING : HealthStatus.READY,
                floor ? DurableFloor.ON : DurableFloor.OFF, floor);
    }
    private void changedLocked() {
        mirror.change = new Object(); ++mirror.healthRevision;
    }
    private void pruneSubscriptionsLocked() {
        mirror.subscriptions.removeIf(subscription -> subscription.closed
                || subscription.owner.get() == null || subscription.observer.get() == null);
    }
    private void closeSubscription(Subscription subscription) {
        mirror.gate.run(() -> {
            subscription.closed = true; subscription.queued = false;
            subscription.observer.clear(); mirror.subscriptions.remove(subscription); return null;
        });
    }
    /** Coalesces to one queued MAIN notice per subscription; no scheduler call under the gate. */
    private void publishHealth() {
        List<Subscription> notices = mirror.gate.run(() -> {
            pruneSubscriptionsLocked(); List<Subscription> result = new ArrayList<>();
            for (Subscription subscription : mirror.subscriptions)
                if (!subscription.queued && subscription.deliveredRevision != mirror.healthRevision) {
                    subscription.queued = true; result.add(subscription);
                }
            return result;
        });
        for (Subscription subscription : notices) {
            BChatRoomMutePort port = subscription.owner.get();
            if (port != null) try { port.scheduler.main(() -> port.deliverHealth(subscription)); }
            catch (RuntimeException unavailable) { port.closeSubscription(subscription); }
        }
    }
    private void deliverHealth(Subscription subscription) {
        boolean active = mirror.gate.run(() -> {
            subscription.queued = false;
            return !subscription.closed && mirror.subscriptions.contains(subscription);
        });
        if (!active) return;
        Health value = health(subscription.binding);
        if (!sameRoute(value.route, subscription.route) || !isCurrent(value, subscription.binding)) return;
        HealthObserver observer = mirror.gate.run(() -> {
            if (subscription.closed || !mirror.subscriptions.contains(subscription)
                    || !subscription.binding.authority.valid() || value.revision != mirror.healthRevision
                    || subscription.deliveredRevision == value.revision) return null;
            subscription.deliveredRevision = value.revision; return subscription.observer.get();
        });
        // MAIN view owners also check their current view ticket before rendering.
        if (observer != null) try { observer.changed(value); } catch (RuntimeException unavailable) { }
    }

    /** RAM privacy predicate only, NOT authorization. Wrong route/unknown/malformed is blocked. */
    boolean blocks(String scopeKey, String registeredAccountUuid, String roomKey) {
        if (!mirror.scopeKey.equals(scopeKey) || !mirror.accountUuid.equals(registeredAccountUuid) || !BChatRoomMuteIndex.hash(roomKey)) return true;
        return mirror.gate.run(() -> !mirror.known || mirror.cells.containsKey(roomKey) && mirror.cells.get(roomKey).floor);
    }

    public Object checkpoint(RoomPreferencesController.Binding expected) {
        Route route = route(expected);
        if (route == null) return null;
        Object result = mirror.gate.run(() -> {
            if (!mirror.known || !expected.authority.valid()) return null;
            Cell cell = cell(route.roomKey);
            if (cell == null) return null;
            if (cell.checkpoint == null || !cell.checkpoint.route.binding.same(expected)) {
                cell.checkpoint = new Checkpoint(route, cell.indexToken); cell.admission = null;
                cell.clearing = null; changedLocked();
            }
            return cell.checkpoint;
        });
        publishHealth(); return result;
    }

    public Object prepare(RoomPreferencesController.RestrictionTicket ticket) {
        if (!scheduler.isMain() || ticket == null || !exact(ticket.binding, ticket.pending)) return null;
        Route route = route(ticket.binding);
        if (route == null) return null;
        boolean desiredMute = ticket.pending.muteForever || ticket.pending.mutedUntil != null;
        String newToken = desiredMute ? UUID.randomUUID().toString() : null;
        Admission admission = mirror.gate.run(() -> {
            if (!mirror.known || !ticket.binding.authority.valid()) return null;
            Cell cell = cell(route.roomKey); if (cell == null) return null;
            if (desiredMute) { cell.indexToken = newToken; cell.floor = true; cell.tokenDurable = false; }
            // Every attempt owns a new RAM checkpoint, even if no new floor is appropriate.
            Checkpoint checkpoint = new Checkpoint(route, cell.indexToken); cell.checkpoint = checkpoint;
            Admission admitted = new Admission(ticket, checkpoint, desiredMute || cell.indexToken != null && !cell.tokenDurable);
            cell.admission = admitted; cell.clearing = null; changedLocked(); return admitted;
        });
        publishHealth();
        if (admission != null) try { scheduler.worker(() -> persist(admission)); } // OUTSIDE the gate.
        catch (RuntimeException unavailable) {
            mirror.gate.run(() -> {
                if (matchesLocked(admission)) {
                    mirror.known = false; mirror.failed = true; changedLocked();
                }
                return null;
            });
            publishHealth();
        }
        return admission;
    }

    /** Read-health only for explicit local unsent cancellation. No floor, admission, I/O or
     * release is manufactured. The same opaque checkpoint must remain durable and current. */
    public boolean currentReadHealthy(Object value, RoomPreferencesController.Binding expected) {
        if (!(value instanceof Checkpoint)) return false;
        Checkpoint checkpoint = (Checkpoint) value;
        Route current = route(expected);
        if (!sameRoute(current, checkpoint.route)) return false;
        return mirror.gate.run(() -> {
            Cell cell = mirror.cells.get(checkpoint.route.roomKey);
            return currentCheckpointLocked(checkpoint) && cell.tokenDurable
                    && Objects.equals(cell.indexToken, checkpoint.expectedIndexToken);
        });
    }

    private void persist(Admission admission) {
        Route route = route(admission.binding);
        if (!sameRoute(route, admission.checkpoint.route) || !matches(admission)) return;
        BChatRoomMuteIndex.Result stored = admission.writeFloor
                ? index.put(route.roomKey, admission.checkpoint.expectedIndexToken) : index.load();
        boolean durable = admission.writeFloor ? stored.kind == BChatRoomMuteIndex.Kind.COMMITTED
                : stored.readable() && Objects.equals(stored.state.token(route.roomKey), admission.checkpoint.expectedIndexToken);
        Route after = route(admission.binding);
        mirror.gate.run(() -> {
            if (!matchesLocked(admission) || !sameRoute(after, admission.checkpoint.route)) return null;
            if (!durable) { mirror.known = false; mirror.failed = true; admission.durable = false; changedLocked(); return null; }
            Cell cell = mirror.cells.get(route.roomKey); cell.tokenDurable = true; admission.durable = true;
            changedLocked();
            return null;
        });
        publishHealth();
    }

    public boolean currentDurable(Object value, RoomPreferencesController.Binding expected, RoomPreferencesProtocol.Pending exact) {
        if (!(value instanceof Admission) || !exact(expected, exact)) return false;
        Admission admission = (Admission) value;
        Route current = route(expected);
        return admission.binding == expected && samePending(admission.pending, exact)
                && sameRoute(current, admission.checkpoint.route)
                && mirror.gate.run(() -> admission.durable && matchesLocked(admission));
    }

    public void release(RoomPreferencesController.DurableProof proof) {
        if (!scheduler.isMain() || proof == null || proof.snapshot == null || proof.snapshot.muted
                || proof.storeRevision <= 0 || !(proof.muteCheckpoint instanceof Checkpoint)) return;
        Checkpoint checkpoint = (Checkpoint) proof.muteCheckpoint;
        Route current = route(proof.binding);
        if (!sameRoute(current, checkpoint.route) || !exact(proof.binding, proof.snapshot)
                || checkpoint.expectedIndexToken == null) return;
        boolean queued = mirror.gate.run(() -> {
            if (!currentCheckpointLocked(checkpoint)) return false;
            Cell cell = mirror.cells.get(checkpoint.route.roomKey);
            if (cell.clearing == checkpoint) return false;
            cell.clearing = checkpoint; changedLocked(); return true;
        });
        if (!queued) return;
        publishHealth();
        try { scheduler.worker(() -> {
            Route before = route(proof.binding);
            if (!sameRoute(before, checkpoint.route) || !currentCheckpoint(checkpoint)) return;
            // Expected token is immutable actual-dispatch data, NEVER today's cell/index token.
            BChatRoomMuteIndex.Result cleared = index.clear(checkpoint.route.roomKey, checkpoint.expectedIndexToken);
            Route after = route(proof.binding);
            mirror.gate.run(() -> {
                if (!currentCheckpointLocked(checkpoint) || !sameRoute(after, checkpoint.route)) return null;
                if (cleared.kind != BChatRoomMuteIndex.Kind.COMMITTED) {
                    mirror.known = false; mirror.failed = true; cellClearFailedLocked(checkpoint); return null;
                }
                Cell cell = mirror.cells.get(checkpoint.route.roomKey);
                cell.floor = false; cell.indexToken = null; cell.tokenDurable = true; cell.admission = null;
                cell.clearing = null; cell.checkpoint = new Checkpoint(after, null); changedLocked(); return null;
            });
            publishHealth();
        }); } catch (RuntimeException unavailable) {
            mirror.gate.run(() -> {
                if (currentCheckpointLocked(checkpoint)
                        && mirror.cells.get(checkpoint.route.roomKey).clearing == checkpoint) {
                    mirror.known = false; mirror.failed = true; cellClearFailedLocked(checkpoint);
                }
                return null;
            });
            publishHealth();
        }
    }

    private void cellClearFailedLocked(Checkpoint checkpoint) {
        Cell cell = mirror.cells.get(checkpoint.route.roomKey);
        if (cell != null && cell.clearing == checkpoint) cell.clearing = null;
        changedLocked();
    }

    private Cell cell(String roomKey) { // Only inside Mirror.gate; no active floor eviction.
        Cell cell = mirror.cells.get(roomKey);
        if (cell == null) {
            if (mirror.cells.size() >= BChatRoomMuteIndex.MAX_ENTRIES) {
                mirror.known = false; mirror.failed = true; changedLocked(); return null;
            }
            cell = new Cell(null); mirror.cells.put(roomKey, cell); changedLocked();
        }
        return cell;
    }
    private boolean matches(Admission admission) { return mirror.gate.run(() -> matchesLocked(admission)); }
    private boolean matchesLocked(Admission admission) {
        Cell cell = mirror.cells.get(admission.checkpoint.route.roomKey);
        return mirror.known && admission.binding.authority.valid() && cell != null && cell.admission == admission
                && cell.checkpoint == admission.checkpoint && Objects.equals(cell.indexToken, admission.checkpoint.expectedIndexToken);
    }
    private boolean currentCheckpoint(Checkpoint checkpoint) { return mirror.gate.run(() -> currentCheckpointLocked(checkpoint)); }
    private boolean currentCheckpointLocked(Checkpoint checkpoint) {
        Cell cell = mirror.cells.get(checkpoint.route.roomKey);
        return mirror.known && checkpoint.route.binding.authority.valid() && cell != null && cell.checkpoint == checkpoint;
    }
    private Route route(RoomPreferencesController.Binding expected) {
        if (expected == null || !expected.authority.valid() || !index.scopeKey.equals(expected.account.key)) return null;
        RouteSource port = source.get(); if (port == null) return null;
        try {
            Route route = port.current(expected);
            return route != null && expected.same(route.binding) && index.accountUuid.equals(route.accountUuid) ? route : null;
        } catch (RuntimeException invalid) { return null; }
    }
    private static boolean sameRoute(Route first, Route second) {
        return first != null && second != null && first.binding.same(second.binding)
                && first.companyId == second.companyId && first.accountUuid.equals(second.accountUuid) && first.roomKey.equals(second.roomKey);
    }
    private static boolean exact(RoomPreferencesController.Binding binding, RoomPreferencesProtocol.Pending pending) {
        return binding != null && pending != null && binding.authority.valid()
                && RoomPreferencesProtocol.sameBinding(binding.account, binding.roomId, binding.membershipId,
                        pending.account, pending.roomId, pending.membershipId);
    }
    private static boolean exact(RoomPreferencesController.Binding binding, RoomPreferencesProtocol.Snapshot snapshot) {
        return binding != null && snapshot != null && RoomPreferencesProtocol.sameBinding(binding.account, binding.roomId, binding.membershipId,
                snapshot.account, snapshot.roomId, snapshot.membershipId);
    }
    private static boolean samePending(RoomPreferencesProtocol.Pending first, RoomPreferencesProtocol.Pending second) {
        return first.clientUuid.equals(second.clientUuid) && first.payload.equals(second.payload)
                && RoomPreferencesProtocol.sameBinding(first.account, first.roomId, first.membershipId, second.account, second.roomId, second.membershipId);
    }
}

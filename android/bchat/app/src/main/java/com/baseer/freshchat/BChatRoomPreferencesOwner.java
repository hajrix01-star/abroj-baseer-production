package com.baseer.freshchat;

import com.baseer.freshchat.sync.AccountScope;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** DEV140/141 RAM component only: not authentication, a wire parser, or FCM integration.
 * The later process owner supplies the SAME reentrant ROUTING gate and existing storage lane.
 * Identity objects must be opaque RAM tokens, never Activity/View/Room instances. A verified
 * full-room response uses the Frame captured BEFORE its original authenticated dispatch.
 */
final class BChatRoomPreferencesOwner implements BChatRoomMutePort.RouteSource {
    enum Kind { PUBLISHED, INVALID, UNSUPPORTED, STALE, REVOKED, COLD_LOADED, COLD_UNAVAILABLE }
    enum Reason { TOKEN_ROTATED, RIGHTS_CHANGED, IDENTITY_CHANGED, REPOSITORY_CHANGED }

    /** No caller-supplied Authority. Room IDs are unique across the full account projection. */
    static final class RoomSpec {
        final long companyId, roomId, membershipId;
        RoomSpec(long companyId, long roomId, long membershipId) {
            this.companyId = companyId; this.roomId = roomId; this.membershipId = membershipId;
        }
    }

    /** Trusted-context data, NOT an authentication proof. Copies are bounded and immutable;
     * invalid data is retained only as an invalid marker so a CURRENT publish fails closed.
     * Caller must not substitute a filtered social/archive projection for the full rooms list.
     * authorizedCompanies contains only distinct companies REFERENCED by those <=100 rooms;
     * Host verifies each against its real account allowlist before projecting this set. This
     * bound is not a limit on how many companies the account itself may be authorized to use.
     */
    static final class VerifiedRoutes {
        final AccountScope account;
        final Object accountIdentity, sessionIdentity;
        final long globalGeneration, repositoryGeneration;
        final int contractVersion, cancelContractVersion;
        final List<Long> authorizedCompanies;
        final List<RoomSpec> rooms;
        private final boolean copied;
        VerifiedRoutes(AccountScope account, Object accountIdentity, Object sessionIdentity,
                long global, long repository, int contractVersion, List<Long> authorizedCompanies,
                List<RoomSpec> rooms) {
            this(account, accountIdentity, sessionIdentity, global, repository, contractVersion, 0, authorizedCompanies, rooms);
        }
        VerifiedRoutes(AccountScope account, Object accountIdentity, Object sessionIdentity,
                long global, long repository, int contractVersion, int cancelContractVersion, List<Long> authorizedCompanies,
                List<RoomSpec> rooms) {
            this.account = account; this.accountIdentity = accountIdentity; this.sessionIdentity = sessionIdentity;
            globalGeneration = global; repositoryGeneration = repository; this.contractVersion = contractVersion;
            this.cancelContractVersion = cancelContractVersion == 1 ? 1 : 0;
            List<Long> companies = copy(authorizedCompanies);
            List<RoomSpec> specs = copy(rooms);
            copied = companies != null && specs != null;
            this.authorizedCompanies = companies == null ? Collections.emptyList() : companies;
            this.rooms = specs == null ? Collections.emptyList() : specs;
        }
        private static <T> List<T> copy(List<T> input) {
            if (input == null || input.size() > BChatRoomMuteIndex.MAX_ENTRIES) return null;
            List<T> copy = new ArrayList<>();
            for (T value : input) {
                if (copy.size() == BChatRoomMuteIndex.MAX_ENTRIES) return null;
                copy.add(value);
            }
            return Collections.unmodifiableList(copy);
        }
    }

    /** Immutable bounded routes; Authority is the one intentionally revocable RAM token.
     * Frame identity itself is the opaque generation; no numeric counter/ABA reuse.
     */
    static final class Frame {
        private final BChatRoomPreferencesOwner owner;
        final Map<Long, BChatRoomMutePort.Route> routes;
        final boolean revoked;
        // Initial cold route can consult the index without manufacturing any Binding. An
        // invalidated/invalid current projection cannot be rearmed by a successful disk load.
        final boolean scopedAvailable;
        private Frame(BChatRoomPreferencesOwner owner, Map<Long, BChatRoomMutePort.Route> routes,
                boolean revoked, boolean scopedAvailable) {
            this.owner = owner;
            this.routes = Collections.unmodifiableMap(new LinkedHashMap<>(routes));
            this.revoked = revoked;
            this.scopedAvailable = scopedAvailable;
        }
    }
    static final class PublishResult {
        final Kind kind;
        final Frame frame;
        private PublishResult(Kind kind, Frame frame) { this.kind = kind; this.frame = frame; }
    }
    static final class LoadResult {
        final Kind kind;
        final BChatRoomMuteIndex.Kind storageKind; // Null when no load was admitted.
        final Frame frame;
        private LoadResult(Kind kind, BChatRoomMuteIndex.Kind storageKind, Frame frame) {
            this.kind = kind; this.storageKind = storageKind; this.frame = frame;
        }
    }
    private static final class Prepared {
        final Kind kind;
        final Map<Long, BChatRoomMutePort.Route> routes;
        Prepared(Kind kind, Map<Long, BChatRoomMutePort.Route> routes) { this.kind = kind; this.routes = routes; }
    }

    final String scopeKey, accountUuid;
    final BChatRoomMutePort port;
    private final BChatRoomMuteIndex index;
    private final BChatRoomMutePort.Mirror mirror;
    private final BChatRoomMutePort.Gate gate;
    private final RoomPreferencesController.Scheduler scheduler;
    private Frame frame; // All access under gate, including snapshot/current.

    BChatRoomPreferencesOwner(BChatRoomMuteIndex index, BChatRoomMutePort.Gate gate,
            RoomPreferencesController.Scheduler scheduler) {
        if (index == null || gate == null || scheduler == null)
            throw new IllegalArgumentException("Fixed index, RAM gate and existing scheduler required");
        this.index = index; this.gate = gate; this.scheduler = scheduler;
        scopeKey = index.scopeKey; accountUuid = index.accountUuid;
        mirror = new BChatRoomMutePort.Mirror(scopeKey, accountUuid, gate);
        port = new BChatRoomMutePort(index, mirror, this, scheduler);
        frame = new Frame(this, Collections.emptyMap(), false, true);
    }

    Frame snapshot() { return gate.run(() -> frame); }

    /** RAM lookup only. Caller still owns authentication and the process route lifetime.
     * A normal full refresh can retain this exact Binding in a newer Frame. */
    BChatRoomMutePort.Route currentRoom(long roomId) {
        return gate.run(() -> {
            if (frame.revoked || !frame.scopedAvailable) return null;
            BChatRoomMutePort.Route route = frame.routes.get(roomId);
            return route != null && route.binding.authority.valid() ? route : null;
        });
    }

    /** Same fixed worker-only index, not recovery permission or a new writer/mirror.
     * The recovery manager must recheck its original ticket before/after each I/O. */
    BChatRoomMuteIndex recoveryIndex(Frame expected) {
        return gate.run(() -> rejected(expected) == null ? index : null);
    }

    /** Atomic verified projection for Port; no caller callback or ordinary Activity fields. */
    public BChatRoomMutePort.Route current(RoomPreferencesController.Binding expected) {
        return gate.run(() -> {
            if (frame.revoked || expected == null || !scopeKey.equals(expected.account.key)) return null;
            BChatRoomMutePort.Route route = frame.routes.get(expected.roomId);
            return route != null && route.binding.same(expected) ? route : null;
        });
    }

    PublishResult publishVerifiedRoutes(Frame expected, VerifiedRoutes verified) {
        if (!scheduler.isMain()) throw new IllegalStateException("Verified publication requires MAIN");
        Prepared prepared = prepare(verified); // Copy/validation/hash construction OUTSIDE gate.
        return gate.run(() -> {
            Kind rejected = rejected(expected);
            if (rejected != null) return new PublishResult(rejected, frame);
            Map<Long, BChatRoomMutePort.Route> next = new LinkedHashMap<>();
            if (prepared.kind == Kind.PUBLISHED) {
                for (Map.Entry<Long, BChatRoomMutePort.Route> entry : prepared.routes.entrySet()) {
                    BChatRoomMutePort.Route old = frame.routes.get(entry.getKey());
                    BChatRoomMutePort.Route candidate = entry.getValue();
                    next.put(entry.getKey(), retain(old, candidate) ? old : candidate);
                }
            }
            revokeRemoved(next); // Invalidate BEFORE exposing the replacement Frame.
            frame = new Frame(this, next, false, prepared.kind == Kind.PUBLISHED);
            return new PublishResult(prepared.kind, frame);
        });
    }

    /** RAM-only identity/rights/repository invalidation, not view pause/close. Floors survive.
     * Reason is an allowlisted diagnostic intent, not authority to revive or clear a route.
     */
    Frame invalidateBindings(Frame expected, Reason reason) {
        return gate.run(() -> {
            if (rejected(expected) != null) return frame;
            revokeRemoved(Collections.emptyMap());
            frame = new Frame(this, Collections.emptyMap(), false, false);
            return frame;
        });
    }

    /** Terminal for this fixed scope/registered UUID. Never deletes index or RAM floors. */
    boolean revokeRoute(Frame expected) {
        return gate.run(() -> {
            if (rejected(expected) != null) return false;
            revokeRemoved(Collections.emptyMap());
            frame = new Frame(this, Collections.emptyMap(), true, false);
            return true;
        });
    }

    /** Worker-only cold index load. No synthetic AccountScope, binding or Health.READY.
     * The Port keeps its own mirror fence; a late load cannot republish an old Frame.
     */
    LoadResult loadColdWorker(Frame expected) {
        if (scheduler.isMain()) throw new IllegalStateException("Cold load requires worker");
        Kind before = gate.run(() -> rejected(expected));
        if (before != null) return new LoadResult(before, null, snapshot());
        BChatRoomMuteIndex.Kind storage = port.loadColdWorker(); // I/O/health enqueue outside gate.
        return gate.run(() -> {
            Kind after = rejected(expected);
            if (after != null) return new LoadResult(after, storage, frame);
            boolean loaded = storage == BChatRoomMuteIndex.Kind.ABSENT || storage == BChatRoomMuteIndex.Kind.LOADED;
            return new LoadResult(loaded ? Kind.COLD_LOADED : Kind.COLD_UNAVAILABLE, storage, frame);
        });
    }

    /** Scoped privacy predicate, NOT an authorization or delivery grant. Reentrant gate is
     * intentional: final Owner/Frame check and delegated Port.blocks form one RAM decision.
     */
    boolean blocks(Frame expected, String scopeSHA, String registeredUuid, String roomKey) {
        return gate.run(() -> rejected(expected) != null || !frame.scopedAvailable || !scopeKey.equals(scopeSHA)
                || !accountUuid.equals(registeredUuid) || port.blocks(scopeSHA, registeredUuid, roomKey));
    }

    private Kind rejected(Frame expected) { // gate held
        if (expected == null || expected.owner != this || expected != frame) return Kind.STALE;
        return frame.revoked ? Kind.REVOKED : null;
    }
    private void revokeRemoved(Map<Long, BChatRoomMutePort.Route> next) { // gate held
        for (Map.Entry<Long, BChatRoomMutePort.Route> entry : frame.routes.entrySet())
            if (next.get(entry.getKey()) != entry.getValue()) entry.getValue().binding.authority.invalidate();
    }
    private static boolean retain(BChatRoomMutePort.Route old, BChatRoomMutePort.Route candidate) {
        if (old == null || !old.binding.authority.valid()) return false;
        RoomPreferencesController.Binding a = old.binding, b = candidate.binding;
        return a.account == b.account && a.accountIdentity == b.accountIdentity && a.sessionIdentity == b.sessionIdentity
                && a.globalGeneration == b.globalGeneration && a.repositoryGeneration == b.repositoryGeneration
                && old.companyId == candidate.companyId && a.roomId == b.roomId && a.membershipId == b.membershipId
                && a.contractVersion == b.contractVersion && a.cancelContractVersion == b.cancelContractVersion;
    }
    private Prepared prepare(VerifiedRoutes value) {
        Map<Long, BChatRoomMutePort.Route> routes = new LinkedHashMap<>();
        if (value == null || !value.copied || value.account == null || !scopeKey.equals(value.account.key)
                || value.accountIdentity == null || value.sessionIdentity == null
                || value.globalGeneration < 0 || value.repositoryGeneration < 0)
            return new Prepared(Kind.INVALID, routes);
        if (value.contractVersion != 1) return new Prepared(Kind.UNSUPPORTED, routes);
        Set<Long> companies = new HashSet<>();
        for (Long company : value.authorizedCompanies)
            if (company == null || !id(company) || !companies.add(company)) return new Prepared(Kind.INVALID, routes);
        for (RoomSpec spec : value.rooms) {
            if (spec == null || !id(spec.companyId) || !id(spec.roomId) || !id(spec.membershipId)
                    || !companies.contains(spec.companyId) || routes.containsKey(spec.roomId))
                return new Prepared(Kind.INVALID, Collections.emptyMap());
            RoomPreferencesController.Binding binding = new RoomPreferencesController.Binding(value.account,
                    value.accountIdentity, value.sessionIdentity, new RoomPreferencesController.Authority(),
                    value.globalGeneration, value.repositoryGeneration, spec.roomId, spec.membershipId, value.contractVersion, value.cancelContractVersion);
            routes.put(spec.roomId, new BChatRoomMutePort.Route(binding, accountUuid, spec.companyId));
        }
        return new Prepared(Kind.PUBLISHED, routes);
    }
    private static boolean id(long value) { return value > 0 && value <= Integer.MAX_VALUE; }
}

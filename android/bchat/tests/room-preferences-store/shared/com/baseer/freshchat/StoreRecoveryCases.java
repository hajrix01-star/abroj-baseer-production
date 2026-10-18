package com.baseer.freshchat;

import android.content.Context;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Recovery primitives on real private files. Auth/proof provenance remains Controller-owned;
 * Host/AtomicFile/JSON are declared JVM adapters in this run, not HTTP or new native evidence. */
final class StoreRecoveryCases {
    private static int checks, sequence;
    private static void check(boolean value, String message) { ++checks; if (!value) throw new AssertionError("Recovery Store " + checks + ": " + message); }
    private static RoomPreferencesStore.Result kind(RoomPreferencesStore.Result value, RoomPreferencesStore.Kind expected) {
        check(value.kind == expected, "Expected " + expected + ", got " + value.kind); return value;
    }
    private static final long ROOM = StoreCases.ROOM, MEMBER = StoreCases.MEMBER;
    private static final class Fixture {
        final Context context;
        final RoomPreferencesStore store;
        final RoomPreferencesProtocol.Pending old = StoreCases.pending(ROOM, MEMBER, 1, 801);
        Fixture(StoreCases.Host host, boolean cache) throws Exception {
            context = host.context("recovery-" + (++sequence)); store = new RoomPreferencesStore(context, StoreCases.ACCOUNT);
            if (cache) kind(store.saveSnapshot(StoreCases.fresh(ROOM, MEMBER, 1), 0), RoomPreferencesStore.Kind.COMMITTED);
            kind(store.stage(old, store.load().state.revision), RoomPreferencesStore.Kind.COMMITTED);
            kind(store.markDispatchStarted(old), RoomPreferencesStore.Kind.COMMITTED);
            kind(store.markBlocked(old, "revision_conflict"), RoomPreferencesStore.Kind.COMMITTED);
        }
        long revision() { return store.load().state.revision; }
        RoomPreferencesProtocol.Pending next(long revision, int uuid) throws Exception { return StoreCases.pending(ROOM, MEMBER, revision, uuid); }
        byte[] bytes(StoreCases.Host host) throws Exception { return Files.readAllBytes(StoreCases.file(host, context, StoreCases.ACCOUNT).toPath()); }
    }
    static int run(StoreCases.Host host) throws Exception {
        checks = 0; sequence = 0;
        replace(host); invalid(host); competing(host); limitsAndFailures(host); retire(host); worker(host);
        return checks;
    }
    private static void replace(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, true);
        RoomPreferencesProtocol.Pending other = StoreCases.pending(77, 88, 2, 802);
        kind(f.store.stage(other, f.revision()), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.markBlocked(other, "request_unknown"), RoomPreferencesStore.Kind.COMMITTED);
        RoomPreferencesProtocol.Snapshot fresh = StoreCases.fresh(ROOM, MEMBER, 3);
        RoomPreferencesProtocol.Pending next = f.next(3, 803);
        long before = f.revision();
        RoomPreferencesStore.State state = kind(f.store.replaceExactRejected(f.old, fresh, next, before), RoomPreferencesStore.Kind.COMMITTED).state;
        check(state.revision == before + 1 && state.pending.size() == 2, "One atomic revision replaces old, not cancel then stage");
        RoomPreferencesStore.Operation exact = state.operation(ROOM, MEMBER);
        check(exact.pending.payload.equals(next.payload) && !exact.dispatchStarted && exact.blockedCode.isEmpty(), "New exact UUID/payload starts unsent and unblocked");
        check(state.snapshot(ROOM).revision == 3 && !state.snapshot(ROOM).freshGet, "Actual fresh snapshot saved as nonfresh metadata");
        check(state.operation(77, 88).pending.payload.equals(other.payload) && state.operation(77, 88).blockedCode.equals("request_unknown"), "Unrelated room untouched");
        RoomPreferencesStore.State reload = new RoomPreferencesStore(f.context, StoreCases.ACCOUNT).load().state;
        check(reload.operation(ROOM, MEMBER).pending.payload.equals(next.payload) && reload.revision == before + 1, "Exact replacement survives reload");
        byte[] bytes = f.bytes(host);
        kind(f.store.acknowledge(f.old, StoreCases.ack(f.old, 2, false)), RoomPreferencesStore.Kind.NO_MATCH);
        check(Arrays.equals(bytes, f.bytes(host)), "Late old ACK cannot retire replacement or update cache");
        kind(f.store.replaceExactRejected(f.old, fresh, f.next(3, 804), reload.revision), RoomPreferencesStore.Kind.NO_MATCH);
        kind(f.store.markDispatchStarted(next), RoomPreferencesStore.Kind.COMMITTED);
    }
    private static void invalid(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, true); RoomPreferencesProtocol.Snapshot fresh = StoreCases.fresh(ROOM, MEMBER, 3);
        byte[] before = f.bytes(host); long rev = f.revision();
        kind(f.store.replaceExactRejected(f.old, fresh, f.next(3, 803), rev - 1), RoomPreferencesStore.Kind.CONFLICT);
        kind(f.store.replaceExactRejected(f.old, StoreCases.fresh(ROOM, MEMBER, 1), f.next(1, 803), rev), RoomPreferencesStore.Kind.INVALID);
        kind(f.store.replaceExactRejected(f.old, fresh, f.next(2, 803), rev), RoomPreferencesStore.Kind.INVALID);
        kind(f.store.replaceExactRejected(f.old, fresh, f.next(3, 801), rev), RoomPreferencesStore.Kind.INVALID);
        kind(f.store.replaceExactRejected(f.old, f.store.load().state.snapshot(ROOM), f.next(1, 803), rev), RoomPreferencesStore.Kind.INVALID);
        kind(f.store.replaceExactRejected(f.old, StoreCases.fresh(ROOM, MEMBER + 1, 3), f.next(3, 803), rev), RoomPreferencesStore.Kind.INVALID);
        kind(f.store.replaceExactRejected(StoreCases.pending(ROOM, MEMBER, 1, 899), fresh, f.next(3, 803), rev), RoomPreferencesStore.Kind.NO_MATCH);
        check(Arrays.equals(before, f.bytes(host)), "Validation/CAS failures preserve exact bytes and old payload");
        for (String blocked : new String[]{"request_unknown", "permission_denied", "membership_changed"}) {
            Fixture wrong = new Fixture(host, true); wrong.store.markBlocked(wrong.old, blocked);
            kind(wrong.store.replaceExactRejected(wrong.old, fresh, wrong.next(3, 803), wrong.revision()), RoomPreferencesStore.Kind.BLOCKED);
        }
        Context unstarted = host.context("recovery-unsent"); RoomPreferencesStore unsent = new RoomPreferencesStore(unstarted, StoreCases.ACCOUNT);
        unsent.stage(f.old, 0); unsent.markBlocked(f.old, "revision_conflict");
        kind(unsent.replaceExactRejected(f.old, fresh, f.next(3, 803), 2), RoomPreferencesStore.Kind.BLOCKED);
        Fixture collision = new Fixture(host, true);
        collision.store.stage(StoreCases.pending(99, 100, 1, 803), collision.revision());
        kind(collision.store.replaceExactRejected(collision.old, fresh, collision.next(3, 803), collision.revision()), RoomPreferencesStore.Kind.CONFLICT);
        Fixture higher = new Fixture(host, true); higher.store.saveSnapshot(StoreCases.fresh(ROOM, MEMBER, 9), higher.revision());
        kind(higher.store.replaceExactRejected(higher.old, fresh, higher.next(3, 803), higher.revision()), RoomPreferencesStore.Kind.CONFLICT);
        check(higher.store.load().state.operation(ROOM, MEMBER).pending.payload.equals(higher.old.payload), "Higher cache is not borrowed as fresh expectedRevision");
        Fixture metadata = new Fixture(host, true);
        RoomPreferencesProtocol.Snapshot cached = RoomPreferencesProtocol.freshSnapshot(StoreCases.snapshotBody(ROOM, MEMBER, 3, true, false), StoreCases.ACCOUNT, ROOM, MEMBER);
        metadata.store.saveSnapshot(cached, metadata.revision());
        kind(metadata.store.replaceExactRejected(metadata.old, fresh, metadata.next(3, 803), metadata.revision()), RoomPreferencesStore.Kind.CONFLICT);
        Fixture epoch = new Fixture(host, false); epoch.store.saveSnapshot(StoreCases.fresh(ROOM, MEMBER + 1, 3), epoch.revision());
        kind(epoch.store.replaceExactRejected(epoch.old, fresh, epoch.next(3, 803), epoch.revision()), RoomPreferencesStore.Kind.EPOCH_CONFLICT);
    }
    private static void competing(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, true); long expected = f.revision();
        RoomPreferencesProtocol.Snapshot fresh = StoreCases.fresh(ROOM, MEMBER, 4);
        RoomPreferencesProtocol.Pending a = f.next(4, 805), b = f.next(4, 806);
        RoomPreferencesStore second = new RoomPreferencesStore(f.context, StoreCases.ACCOUNT);
        CountDownLatch ready = new CountDownLatch(2), start = new CountDownLatch(1);
        RoomPreferencesStore.Result[] values = new RoomPreferencesStore.Result[2]; AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread[] threads = new Thread[2];
        for (int i = 0; i < 2; i++) { final int slot = i; threads[i] = new Thread(() -> {
            ready.countDown(); try {
                if (!start.await(5, TimeUnit.SECONDS)) throw new AssertionError("Recovery barrier deadline");
                values[slot] = (slot == 0 ? f.store : second).replaceExactRejected(f.old, fresh, slot == 0 ? a : b, expected);
            } catch (Throwable error) { failure.set(error); }
        }); threads[i].start(); }
        check(ready.await(5, TimeUnit.SECONDS), "Competing recovery workers ready"); start.countDown();
        for (Thread thread : threads) { thread.join(10000); check(!thread.isAlive(), "Competing recovery worker bounded"); }
        if (failure.get() != null) throw new AssertionError(failure.get());
        check(values[0].kind == RoomPreferencesStore.Kind.COMMITTED && values[1].kind == RoomPreferencesStore.Kind.CONFLICT
                || values[1].kind == RoomPreferencesStore.Kind.COMMITTED && values[0].kind == RoomPreferencesStore.Kind.CONFLICT, "One exact CAS replacement wins");
        check(f.store.load().state.pending.size() == 1 && f.revision() == expected + 1, "No double replacement / UUID collision");
    }
    private static void limitsAndFailures(StoreCases.Host host) throws Exception {
        Fixture full = new Fixture(host, true);
        for (int i = 0; i < 19; i++) full.store.stage(StoreCases.pending(100 + i, 200 + i, 1, 900 + i), full.revision());
        kind(full.store.replaceExactRejected(full.old, StoreCases.fresh(ROOM, MEMBER, 2), full.next(2, 803), full.revision()), RoomPreferencesStore.Kind.COMMITTED);
        check(full.store.load().state.pending.size() == 20, "Replacement at full cap does not evict or temporarily exceed 20");
        for (boolean syncFailure : new boolean[]{false, true}) {
            Fixture f = new Fixture(host, true); byte[] before = f.bytes(host);
            RoomPreferencesStore failed = new RoomPreferencesStore(f.context, StoreCases.ACCOUNT,
                    syncFailure ? StoreFaults.ClosedBeforeSync::new : StoreFaults.SilentFinish::new);
            kind(failed.replaceExactRejected(f.old, StoreCases.fresh(ROOM, MEMBER, 3), f.next(3, 803), f.revision()), RoomPreferencesStore.Kind.UNCERTAIN);
            check(Arrays.equals(before, f.bytes(host)) && f.store.load().state.operation(ROOM, MEMBER).dispatchStarted, "Sync/readback uncertainty leaves old durable intent, no grant");
        }
    }
    private static void retire(StoreCases.Host host) throws Exception {
        for (boolean newCache : new boolean[]{false, true}) {
            Fixture f = new Fixture(host, !newCache); long currentMember = MEMBER + 1;
            RoomPreferencesProtocol.Pending nextEpoch = StoreCases.pending(ROOM, currentMember, 7, 808);
            if (newCache) {
                f.store.saveSnapshot(StoreCases.fresh(ROOM, currentMember, 7), f.revision());
                f.store.stage(nextEpoch, f.revision()); f.store.markBlocked(nextEpoch, "request_unknown");
            }
            byte[] before = f.bytes(host); long revision = f.revision();
            kind(f.store.retireObsoleteExact(f.old, MEMBER, revision), RoomPreferencesStore.Kind.INVALID);
            kind(f.store.retireObsoleteExact(f.old, 0, revision), RoomPreferencesStore.Kind.INVALID);
            kind(f.store.retireObsoleteExact(f.old, currentMember, revision - 1), RoomPreferencesStore.Kind.CONFLICT);
            check(Arrays.equals(before, f.bytes(host)), "Invalid/absent proof shape and stale CAS preserve bytes");
            RoomPreferencesStore.State state = kind(f.store.retireObsoleteExact(f.old, currentMember, revision), RoomPreferencesStore.Kind.COMMITTED).state;
            check(state.operation(ROOM, MEMBER) == null && state.revision == revision + 1, "Exact obsolete pending retired atomically");
            if (newCache) check(state.snapshot(ROOM).membershipId == currentMember && state.snapshot(ROOM).revision == 7
                    && state.operation(ROOM, currentMember).pending.payload.equals(nextEpoch.payload)
                    && state.operation(ROOM, currentMember).blockedCode.equals("request_unknown"), "Proven current cache and pending untouched");
            else {
                check(state.snapshot(ROOM) == null, "Matching old cache retired in SAME commit, avoiding new epoch deadlock");
                kind(f.store.saveSnapshot(StoreCases.fresh(ROOM, currentMember, 7), state.revision), RoomPreferencesStore.Kind.COMMITTED);
            }
            before = f.bytes(host);
            kind(f.store.acknowledge(f.old, StoreCases.ack(f.old, 2, false)), RoomPreferencesStore.Kind.NO_MATCH);
            kind(f.store.retireObsoleteExact(f.old, currentMember, f.revision()), RoomPreferencesStore.Kind.NO_MATCH);
            check(Arrays.equals(before, f.bytes(host)), "Late ACK/duplicate retirement neither recreates old cache nor alters current epoch");
        }
        Fixture third = new Fixture(host, false); third.store.saveSnapshot(StoreCases.fresh(ROOM, MEMBER + 2, 8), third.revision());
        kind(third.store.retireObsoleteExact(third.old, MEMBER + 1, third.revision()), RoomPreferencesStore.Kind.EPOCH_CONFLICT);
        check(third.store.load().state.operation(ROOM, MEMBER) != null, "Unexplained third cache epoch not silently cleared");
        Fixture failed = new Fixture(host, true); byte[] before = failed.bytes(host);
        RoomPreferencesStore uncertain = new RoomPreferencesStore(failed.context, StoreCases.ACCOUNT, StoreFaults.SilentFinish::new);
        kind(uncertain.retireObsoleteExact(failed.old, MEMBER + 1, failed.revision()), RoomPreferencesStore.Kind.UNCERTAIN);
        check(Arrays.equals(before, failed.bytes(host)), "Uncertain retirement cannot claim removal");
    }
    private static void worker(StoreCases.Host host) throws Exception {
        Context context = host.context("recovery-main"); RoomPreferencesStore store = new RoomPreferencesStore(context, StoreCases.ACCOUNT);
        host.main(() -> {
            try { store.replaceExactRejected(null, null, null, 0); throw new AssertionError("MAIN replace accepted"); }
            catch (IllegalStateException expected) { check(host.lookups(context) == 0, "Reject recovery before filesDir"); }
            try { store.retireObsoleteExact(null, 2, 0); throw new AssertionError("MAIN retire accepted"); }
            catch (IllegalStateException expected) { check(host.lookups(context) == 0, "Reject retirement before filesDir"); }
        });
    }
    private StoreRecoveryCases() { }
}

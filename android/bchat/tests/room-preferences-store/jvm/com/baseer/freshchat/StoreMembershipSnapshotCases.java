package com.baseer.freshchat;

import android.content.Context;
import android.util.AtomicFile;
import com.baseer.freshchat.sync.AccountScope;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** DEV161/162 feature gap, NOT a v87 regression. Actual Store and JVM private files with
 * existing Android/AtomicFile/Gson-JSON adapters. Member ID/freshGet are inputs, not auth;
 * no FullRoomsProof/Host wiring, HTTP, Android runtime or physical durability claim.
 */
final class StoreMembershipSnapshotCases {
    private static int checks, sequence;
    private static long fullMetadataBytes;
    private static final long ROOM = StoreCases.ROOM, OLD = StoreCases.MEMBER, NEW = OLD + 1;
    private static void check(boolean value, String why) {
        ++checks; if (!value) throw new AssertionError("Membership snapshot " + checks + ": " + why);
    }
    private static RoomPreferencesStore.Result kind(RoomPreferencesStore.Result result, RoomPreferencesStore.Kind expected) {
        check(result.kind == expected, "Expected " + expected + ", got " + result.kind); return result;
    }
    private static final class Fixture {
        final Context context;
        final RoomPreferencesStore store;
        Fixture(StoreCases.Host host, boolean cache) throws Exception {
            context = host.context("membership-snapshot-" + (++sequence));
            store = new RoomPreferencesStore(context, StoreCases.ACCOUNT);
            if (cache) kind(store.saveSnapshot(StoreCases.fresh(ROOM, OLD, 99), 0), RoomPreferencesStore.Kind.COMMITTED);
        }
        long revision() { return store.load().state.revision; }
        RoomPreferencesProtocol.Snapshot old() { return store.load().state.snapshot(ROOM); }
        RoomPreferencesProtocol.Snapshot fresh() throws Exception { return StoreCases.fresh(ROOM, NEW, 1); }
        File file(StoreCases.Host host) { return StoreCases.file(host, context, StoreCases.ACCOUNT); }
        byte[] bytes(StoreCases.Host host) throws Exception { return Files.readAllBytes(file(host).toPath()); }
        RoomPreferencesStore.Result replace(RoomPreferencesProtocol.Snapshot old, RoomPreferencesProtocol.Snapshot fresh, long member, long expected) {
            return store.replaceMembershipSnapshotExact(old, fresh, member, expected);
        }
    }
    static int run(StoreCases.Host host) throws Exception {
        checks = 0; sequence = 0; fullMetadataBytes = 0;
        snapshotOnly(host); validation(host); allPending(host); ordering(host); competing(host); faults(host); bounds(host); worker(host);
        Context results = host.context("membership-snapshot-results");
        JSONObject result = new JSONObject().put("schema", 1).put("assertions", checks)
                .put("max_snapshots", RoomPreferencesStore.MAX_SNAPSHOTS).put("max_pending", RoomPreferencesStore.MAX_PENDING)
                .put("file_limit_bytes", RoomPreferencesStore.MAX_BYTES).put("full_metadata_bytes", fullMetadataBytes)
                .put("scope", "Actual Store/JVM files; declared Android/AtomicFile/Gson-JSON adapters; no auth/HTTP/Android/process/power-loss");
        StoreCases.write(new File(host.files(results), "results.json"), result.toString());
        System.out.println("BOUND snapshot_count=100 pending_count=20 canonical_bytes=" + fullMetadataBytes
                + " file_limit_bytes=" + RoomPreferencesStore.MAX_BYTES + "; oversized read rejected, not a capacity/SLA claim");
        return checks;
    }
    private static void snapshotOnly(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, true); RoomPreferencesProtocol.Snapshot old = f.old(), fresh = f.fresh();
        byte[] before = f.bytes(host);
        // Designed baseline: ordinary save never reassigns a membership. This is not a RED bug.
        kind(f.store.saveSnapshot(fresh, f.revision()), RoomPreferencesStore.Kind.EPOCH_CONFLICT);
        check(Arrays.equals(before, f.bytes(host)), "Ordinary save baseline preserves old epoch");
        long revision = f.revision();
        RoomPreferencesStore.State state = kind(f.replace(old, fresh, NEW, revision), RoomPreferencesStore.Kind.COMMITTED).state;
        check(state.revision == revision + 1 && state.snapshots.size() == 1 && state.pending.isEmpty(), "Snapshot-only replacement is one commit, no invented intent");
        check(state.snapshot(ROOM).membershipId == NEW && state.snapshot(ROOM).revision == 1 && !state.snapshot(ROOM).freshGet,
                "New membership revision may be lower; saved snapshot is never fresh");
        RoomPreferencesStore.State reload = kind(new RoomPreferencesStore(f.context, StoreCases.ACCOUNT).load(), RoomPreferencesStore.Kind.LOADED).state;
        check(reload.snapshot(ROOM).membershipId == NEW && reload.snapshot(ROOM).revision == 1 && !reload.snapshot(ROOM).freshGet, "Exact new epoch survives reload without auth freshness");
        before = f.bytes(host);
        kind(f.replace(old, fresh, NEW, reload.revision), RoomPreferencesStore.Kind.CONFLICT);
        kind(f.replace(reload.snapshot(ROOM), fresh, NEW, reload.revision), RoomPreferencesStore.Kind.INVALID);
        check(Arrays.equals(before, f.bytes(host)), "Duplicate replacement is not artificial COMMITTED/UNCHANGED success");
    }
    private static void validation(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, true); RoomPreferencesProtocol.Snapshot old = f.old(), fresh = f.fresh();
        long revision = f.revision(); byte[] before = f.bytes(host);
        kind(f.replace(null, fresh, NEW, revision), RoomPreferencesStore.Kind.INVALID);
        kind(f.replace(old, null, NEW, revision), RoomPreferencesStore.Kind.INVALID);
        for (long member : new long[]{0, -1, OLD, NEW + 1, 2147483648L, Long.MAX_VALUE})
            kind(f.replace(old, fresh, member, revision), RoomPreferencesStore.Kind.INVALID);
        kind(f.replace(old, StoreCases.fresh(ROOM, OLD, 100), OLD, revision), RoomPreferencesStore.Kind.INVALID);
        kind(f.replace(old, StoreCases.fresh(ROOM + 1, NEW, 1), NEW, revision), RoomPreferencesStore.Kind.INVALID);
        RoomPreferencesProtocol.Snapshot storedFresh = RoomPreferencesProtocol.storedSnapshot(StoreCases.snapshotBody(ROOM, NEW, 1, false, false), StoreCases.ACCOUNT, ROOM, NEW);
        kind(f.replace(old, storedFresh, NEW, revision), RoomPreferencesStore.Kind.INVALID);
        AccountScope foreign = new AccountScope("https://other-store.invalid", "foreign", 9);
        RoomPreferencesProtocol.Snapshot wrongOld = RoomPreferencesProtocol.freshSnapshot(StoreCases.snapshotBody(ROOM, OLD, 99, false, false), foreign, ROOM, OLD);
        RoomPreferencesProtocol.Snapshot wrongFresh = RoomPreferencesProtocol.freshSnapshot(StoreCases.snapshotBody(ROOM, NEW, 1, false, false), foreign, ROOM, NEW);
        kind(f.replace(wrongOld, fresh, NEW, revision), RoomPreferencesStore.Kind.INVALID);
        kind(f.replace(old, wrongFresh, NEW, revision), RoomPreferencesStore.Kind.INVALID);
        kind(f.replace(old, fresh, NEW, revision - 1), RoomPreferencesStore.Kind.CONFLICT);
        kind(f.replace(old, fresh, NEW, Long.MAX_VALUE), RoomPreferencesStore.Kind.CONFLICT);
        RoomPreferencesProtocol.Snapshot changed = RoomPreferencesProtocol.freshSnapshot(StoreCases.snapshotBody(ROOM, OLD, 99, true, true), StoreCases.ACCOUNT, ROOM, OLD);
        kind(f.replace(changed, fresh, NEW, revision), RoomPreferencesStore.Kind.CONFLICT);
        RoomPreferencesProtocol.Snapshot derived = RoomPreferencesProtocol.freshSnapshot(StoreCases.snapshotBody(ROOM, OLD, 99, false, false).put("muted", false), StoreCases.ACCOUNT, ROOM, OLD);
        kind(f.replace(derived, fresh, NEW, revision), RoomPreferencesStore.Kind.CONFLICT);
        check(Arrays.equals(before, f.bytes(host)), "All rejected inputs/CAS, including derived muted mismatch, preserve exact bytes");
        kind(f.store.saveSnapshot(StoreCases.fresh(ROOM, OLD, 100), revision), RoomPreferencesStore.Kind.COMMITTED);
        before = f.bytes(host);
        kind(f.replace(old, fresh, NEW, f.revision()), RoomPreferencesStore.Kind.CONFLICT);
        check(Arrays.equals(before, f.bytes(host)), "Higher actual cache is not borrowed as the expected old snapshot");
        Fixture missing = new Fixture(host, false);
        kind(missing.replace(old, fresh, NEW, 0), RoomPreferencesStore.Kind.NO_MATCH);
        check(!missing.file(host).exists(), "Missing old snapshot is not created or silently reset");
        Fixture third = new Fixture(host, false); third.store.saveSnapshot(StoreCases.fresh(ROOM, NEW + 1, 3), 0);
        before = third.bytes(host);
        kind(third.replace(old, fresh, NEW, third.revision()), RoomPreferencesStore.Kind.CONFLICT);
        check(Arrays.equals(before, third.bytes(host)), "A third membership's actual cache cannot be replaced by an unrelated old CAS");
    }
    private static void preservePending(List<RoomPreferencesStore.Operation> old, List<RoomPreferencesStore.Operation> actual) {
        check(old.size() == actual.size(), "All pending count preserved");
        for (int i = 0; i < old.size(); ++i) {
            RoomPreferencesStore.Operation a = old.get(i), b = actual.get(i);
            check(a.pending.roomId == b.pending.roomId && a.pending.membershipId == b.pending.membershipId
                    && a.pending.clientUuid.equals(b.pending.clientUuid) && a.pending.payload.equals(b.pending.payload)
                    && a.dispatchStarted == b.dispatchStarted && a.blockedCode.equals(b.blockedCode), "Exact pending UUID/payload/started/blocked preserved: " + i);
        }
    }
    private static void allPending(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, false);
        RoomPreferencesProtocol.Pending current = StoreCases.pending(ROOM, NEW, 1, 1201), old = StoreCases.pending(ROOM, OLD, 99, 1202);
        kind(f.store.stage(current, f.revision()), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.markDispatchStarted(current), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.markBlocked(current, "request_unknown"), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.stage(old, f.revision()), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.markDispatchStarted(old), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.markBlocked(old, "revision_conflict"), RoomPreferencesStore.Kind.COMMITTED);
        RoomPreferencesProtocol.Pending other = StoreCases.pending(77, 88, 5, 1203);
        kind(f.store.stage(other, f.revision()), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.markBlocked(other, "membership_changed"), RoomPreferencesStore.Kind.COMMITTED);
        kind(f.store.saveSnapshot(StoreCases.fresh(ROOM, OLD, 99), f.revision()), RoomPreferencesStore.Kind.COMMITTED);
        List<RoomPreferencesStore.Operation> pending = f.store.load().state.pending;
        kind(f.replace(f.old(), f.fresh(), NEW, f.revision()), RoomPreferencesStore.Kind.COMMITTED);
        preservePending(pending, f.store.load().state.pending);
        preservePending(pending, new RoomPreferencesStore(f.context, StoreCases.ACCOUNT).load().state.pending);
    }
    private static void ordering(StoreCases.Host host) throws Exception {
        Fixture ackFirst = new Fixture(host, true);
        RoomPreferencesProtocol.Pending old = StoreCases.pending(ROOM, OLD, 99, 1301);
        ackFirst.store.stage(old, ackFirst.revision()); ackFirst.store.markDispatchStarted(old);
        RoomPreferencesProtocol.Snapshot snapshot = ackFirst.old(); long expected = ackFirst.revision();
        kind(ackFirst.store.acknowledge(old, StoreCases.ack(old, 100, false)), RoomPreferencesStore.Kind.COMMITTED);
        byte[] before = ackFirst.bytes(host);
        kind(ackFirst.replace(snapshot, ackFirst.fresh(), NEW, expected), RoomPreferencesStore.Kind.CONFLICT);
        kind(ackFirst.replace(snapshot, ackFirst.fresh(), NEW, ackFirst.revision()), RoomPreferencesStore.Kind.CONFLICT);
        check(Arrays.equals(before, ackFirst.bytes(host)) && ackFirst.old().membershipId == OLD && ackFirst.old().revision == 100,
                "ACK-first invalidates both store revision and old canonical snapshot CAS");

        Fixture replaceFirst = new Fixture(host, true);
        old = StoreCases.pending(ROOM, OLD, 99, 1302); replaceFirst.store.stage(old, replaceFirst.revision()); replaceFirst.store.markDispatchStarted(old);
        kind(replaceFirst.replace(replaceFirst.old(), replaceFirst.fresh(), NEW, replaceFirst.revision()), RoomPreferencesStore.Kind.COMMITTED);
        before = replaceFirst.bytes(host);
        kind(replaceFirst.store.markDispatchStarted(old), RoomPreferencesStore.Kind.EPOCH_CONFLICT);
        check(Arrays.equals(before, replaceFirst.bytes(host)), "Old mark never dispatches or rewrites new epoch");
        kind(replaceFirst.store.acknowledge(old, StoreCases.ack(old, 100, false)), RoomPreferencesStore.Kind.COMMITTED);
        check(replaceFirst.old().membershipId == NEW && replaceFirst.old().revision == 1 && replaceFirst.store.load().state.pending.isEmpty(), "Replace-first old ACK retires exact intent only, new cache unchanged");
        before = replaceFirst.bytes(host);
        kind(replaceFirst.store.acknowledge(old, StoreCases.ack(old, 101, true)), RoomPreferencesStore.Kind.NO_MATCH);
        check(Arrays.equals(before, replaceFirst.bytes(host)), "Late duplicate ACK cannot reinstall old epoch");

        Fixture retire = new Fixture(host, true); old = StoreCases.pending(ROOM, OLD, 99, 1303);
        retire.store.stage(old, retire.revision()); retire.store.markDispatchStarted(old);
        retire.replace(retire.old(), retire.fresh(), NEW, retire.revision());
        kind(retire.store.retireObsoleteExact(old, NEW, retire.revision()), RoomPreferencesStore.Kind.COMMITTED);
        check(retire.old().membershipId == NEW && retire.old().revision == 1 && retire.store.load().state.pending.isEmpty(), "Existing retirement preserves positively reconciled new cache");
        before = retire.bytes(host);
        kind(retire.store.acknowledge(old, StoreCases.ack(old, 100, false)), RoomPreferencesStore.Kind.NO_MATCH);
        check(Arrays.equals(before, retire.bytes(host)), "Retired old ACK is no match, no new cache mutation");
    }
    private static void competing(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, true); long expected = f.revision(); RoomPreferencesProtocol.Snapshot old = f.old();
        RoomPreferencesStore other = new RoomPreferencesStore(f.context, StoreCases.ACCOUNT);
        CountDownLatch ready = new CountDownLatch(2), start = new CountDownLatch(1);
        RoomPreferencesStore.Result[] results = new RoomPreferencesStore.Result[2]; AtomicReference<Throwable> error = new AtomicReference<>();
        Thread[] workers = new Thread[2];
        for (int i = 0; i < 2; ++i) { final int slot = i;
            workers[i] = new Thread(() -> {
                ready.countDown(); try {
                    if (!start.await(3, TimeUnit.SECONDS)) throw new AssertionError("Snapshot CAS barrier timeout");
                    results[slot] = (slot == 0 ? f.store : other).replaceMembershipSnapshotExact(old, StoreCases.fresh(ROOM, NEW + slot, 1), NEW + slot, expected);
                } catch (Throwable failure) { error.set(failure); }
            }); workers[i].start();
        }
        check(ready.await(3, TimeUnit.SECONDS), "Two actual JVM worker calls ready"); start.countDown();
        for (Thread worker : workers) { worker.join(5000); check(!worker.isAlive(), "Snapshot CAS worker bounded"); }
        if (error.get() != null) throw new AssertionError(error.get());
        check(results[0].kind == RoomPreferencesStore.Kind.COMMITTED && results[1].kind == RoomPreferencesStore.Kind.CONFLICT
                || results[1].kind == RoomPreferencesStore.Kind.COMMITTED && results[0].kind == RoomPreferencesStore.Kind.CONFLICT, "One process-wide FILE_LOCK/CAS winner");
        check(f.revision() == expected + 1 && (f.old().membershipId == NEW || f.old().membershipId == NEW + 1), "Exactly one atomic epoch installed, no double commit");
    }
    private static void faults(StoreCases.Host host) throws Exception {
        for (boolean silent : new boolean[]{true, false}) {
            Fixture f = new Fixture(host, true); byte[] before = f.bytes(host);
            RoomPreferencesStore failed = new RoomPreferencesStore(f.context, StoreCases.ACCOUNT, silent ? StoreFaults.SilentFinish::new : StoreFaults.ClosedBeforeSync::new);
            RoomPreferencesStore.Result result = kind(failed.replaceMembershipSnapshotExact(f.old(), f.fresh(), NEW, f.revision()), RoomPreferencesStore.Kind.UNCERTAIN);
            check(result.state == null && Arrays.equals(before, f.bytes(host)), "Explicit finish/sync fixture cannot report committed; observed old bytes retained");
        }
        Fixture f = new Fixture(host, true); long revision = f.revision();
        RoomPreferencesStore mismatch = new RoomPreferencesStore(f.context, StoreCases.ACCOUNT, base -> new AtomicFile(base) {
            public void finishWrite(FileOutputStream stream) {
                super.finishWrite(stream);
                try { StoreCases.write(base, StoreCases.text(base).replace("\"store_revision\":" + (revision + 1), "\"store_revision\":" + (revision + 2))); }
                catch (Exception failure) { throw new IllegalStateException(failure); }
            }
        });
        RoomPreferencesStore.Result result = kind(mismatch.replaceMembershipSnapshotExact(f.old(), f.fresh(), NEW, revision), RoomPreferencesStore.Kind.UNCERTAIN);
        RoomPreferencesStore.State reload = f.store.load().state;
        check(result.state == null && reload.revision == revision + 2 && reload.snapshot(ROOM).membershipId == NEW,
                "Readback mismatch is UNCERTAIN even when new cache reached disk; no promised rollback");
    }
    private static void bounds(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, false);
        for (int room = 1; room <= RoomPreferencesStore.MAX_SNAPSHOTS; ++room)
            kind(f.store.saveSnapshot(StoreCases.fresh(room, room == ROOM ? OLD : room + 1000, 99), f.revision()), RoomPreferencesStore.Kind.COMMITTED);
        for (int room = 1; room <= RoomPreferencesStore.MAX_PENDING; ++room) {
            RoomPreferencesProtocol.Pending operation = StoreCases.pending(room, room == ROOM ? OLD : room + 1000, 99, 1500 + room);
            kind(f.store.stage(operation, f.revision()), RoomPreferencesStore.Kind.COMMITTED);
            if (room % 2 == 0) kind(f.store.markDispatchStarted(operation), RoomPreferencesStore.Kind.COMMITTED);
            if (room % 3 == 0) kind(f.store.markBlocked(operation, "request_unknown"), RoomPreferencesStore.Kind.COMMITTED);
        }
        List<RoomPreferencesStore.Operation> pending = f.store.load().state.pending;
        RoomPreferencesStore.State replaced = kind(f.replace(f.old(), f.fresh(), NEW, f.revision()), RoomPreferencesStore.Kind.COMMITTED).state;
        check(replaced.snapshots.size() == 100 && replaced.pending.size() == 20, "Replacement works at existing 100/20 limits without adding entries");
        preservePending(pending, new RoomPreferencesStore(f.context, StoreCases.ACCOUNT).load().state.pending);
        fullMetadataBytes = f.file(host).length(); check(fullMetadataBytes <= RoomPreferencesStore.MAX_BYTES, "Observed full metadata remains inside unchanged 256KiB cap");
        byte[] before = f.bytes(host);
        kind(f.store.saveSnapshot(StoreCases.fresh(101, 1101, 1), f.revision()), RoomPreferencesStore.Kind.CAPACITY);
        kind(f.store.stage(StoreCases.pending(101, 1101, 1, 1601), f.revision()), RoomPreferencesStore.Kind.CAPACITY);
        check(Arrays.equals(before, f.bytes(host)), "101st snapshot/21st intent rejected, no silent eviction");
        for (int size : new int[]{RoomPreferencesStore.MAX_BYTES, RoomPreferencesStore.MAX_BYTES + 1}) {
            Fixture raw = new Fixture(host, false); byte[] bytes = new byte[size]; StoreCases.write(raw.file(host), bytes);
            kind(raw.replace(f.old(), StoreCases.fresh(ROOM, NEW + 1, 1), NEW + 1, 1),
                    size == RoomPreferencesStore.MAX_BYTES ? RoomPreferencesStore.Kind.CORRUPT : RoomPreferencesStore.Kind.TOO_LARGE);
            check(Arrays.equals(bytes, raw.bytes(host)), "Raw at/over byte boundary preserved, never reset or written");
        }
        Fixture exhausted = new Fixture(host, true);
        StoreCases.write(exhausted.file(host), StoreCases.text(exhausted.file(host)).replace("\"store_revision\":1", "\"store_revision\":" + Long.MAX_VALUE));
        before = exhausted.bytes(host);
        kind(exhausted.replace(exhausted.old(), exhausted.fresh(), NEW, Long.MAX_VALUE), RoomPreferencesStore.Kind.EXHAUSTED);
        check(Arrays.equals(before, exhausted.bytes(host)), "Store revision never wraps during epoch replacement");
    }
    private static void worker(StoreCases.Host host) throws Exception {
        Fixture f = new Fixture(host, false);
        host.main(() -> {
            try { f.replace(null, null, NEW, 0); throw new AssertionError("MAIN epoch replacement accepted"); }
            catch (IllegalStateException expected) { check(host.lookups(f.context) == 0, "Worker check precedes any filesDir/read"); }
        });
    }
}

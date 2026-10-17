package com.baseer.freshchat;

import android.content.Context;
import com.baseer.freshchat.sync.AccountScope;
import java.io.*;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Same production Store cases for declared JVM adapters and actual Android AtomicFile/JSON. */
final class StoreCases {
    interface Host {
        Context context(String name) throws Exception;
        File files(Context context);
        int lookups(Context context);
        void main(Runnable action) throws Exception;
    }
    static final AccountScope ACCOUNT = new AccountScope("https://c17-store.invalid", "synthetic", 7);
    static final long ROOM = 11, MEMBER = 23;
    static final String PAST = "2000-01-01T00:00:00Z";
    private static int checks;
    private static void check(boolean value, String why) { ++checks; if (!value) throw new AssertionError("Store check " + checks + ": " + why); }
    private static RoomPreferencesStore.Result kind(RoomPreferencesStore.Result value, RoomPreferencesStore.Kind expected) {
        check(value.kind == expected, "Expected " + expected + ", got " + value.kind); return value;
    }
    static JSONObject snapshotBody(long room, long member, long revision, boolean pinned, boolean archived) throws Exception {
        return new JSONObject().put("api_version", 2).put("room_id", room).put("membership_id", member)
                .put("revision", revision).put("muted_until", PAST).put("mute_forever", false).put("muted", true)
                .put("pinned", pinned).put("pinned_at", pinned ? "2026-10-18T12:00:00Z" : JSONObject.NULL).put("archived", archived);
    }
    static RoomPreferencesProtocol.Snapshot fresh(long room, long member, long revision) throws Exception {
        return RoomPreferencesProtocol.freshSnapshot(snapshotBody(room, member, revision, false, false), ACCOUNT, room, member);
    }
    static RoomPreferencesProtocol.Pending pending(long room, long member, long revision, int token) throws Exception {
        return RoomPreferencesProtocol.newPending(fresh(room, member, revision), uuid(token), PAST, false, true, true);
    }
    static String uuid(int value) { return String.format(Locale.ROOT, "00000000-0000-4000-8000-%012x", value); }
    static RoomPreferencesProtocol.Acknowledgement ack(RoomPreferencesProtocol.Pending pending, long revision, boolean replayed) throws Exception {
        return RoomPreferencesProtocol.acknowledgement(200,
                snapshotBody(pending.roomId, pending.membershipId, revision, pending.pinned, pending.archived)
                        .put("client_uuid", pending.clientUuid).put("operation_revision", pending.expectedRevision + 1)
                        .put("replayed", replayed), pending);
    }
    static File file(Host host, Context context, AccountScope scope) { return new File(new File(host.files(context), "bchat-room-preferences"), scope.key + ".json"); }
    static void write(File file, byte[] bytes) throws Exception {
        File parent = file.getParentFile(); if (!parent.isDirectory() && !parent.mkdirs()) throw new IOException("Fixture directory");
        try (FileOutputStream out = new FileOutputStream(file)) { out.write(bytes); out.getFD().sync(); }
    }
    static void write(File file, String text) throws Exception { write(file, text.getBytes(StandardCharsets.UTF_8)); }
    static String text(File file) throws Exception { return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8); }
    private static void mainRejected(Runnable action) { try { action.run(); } catch (IllegalStateException expected) { ++checks; return; } throw new AssertionError("MAIN accepted"); }

    static int run(Host host) throws Exception {
        checks = 0;
        construction(host); lifecycle(host); snapshots(host); concurrency(host); caps(host); corrupt(host); atomic(host); acknowledgements(host); overflow(host);
        return checks;
    }
    static int ambiguousEpoch(Host host) throws Exception {
        checks = 0;
        for (boolean higherAck : new boolean[]{false, true}) {
            Context context = host.context("ambiguous-epoch-" + higherAck); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
            long ackMember = higherAck ? MEMBER + 1 : MEMBER, otherMember = higherAck ? MEMBER : MEMBER + 1;
            RoomPreferencesProtocol.Pending old = pending(ROOM, ackMember, 1, 601), other = pending(ROOM, otherMember, 1, 602);
            kind(store.stage(old, 0), RoomPreferencesStore.Kind.COMMITTED);
            kind(store.markDispatchStarted(old), RoomPreferencesStore.Kind.COMMITTED);
            kind(store.stage(other, 2), RoomPreferencesStore.Kind.COMMITTED);
            if (higherAck) kind(store.markDispatchStarted(other), RoomPreferencesStore.Kind.COMMITTED);
            kind(store.markBlocked(other, "membership_changed"), RoomPreferencesStore.Kind.COMMITTED);
            RoomPreferencesStore.Result settled = kind(store.acknowledge(old, ack(old, 2, false)), RoomPreferencesStore.Kind.COMMITTED);
            check(settled.state.snapshots.isEmpty(), "Ambiguous different pending epoch must not create a cache from old ACK");
            check(settled.state.operation(ROOM, ackMember) == null && settled.state.pending.size() == 1
                    && settled.state.operation(ROOM, otherMember).pending.payload.equals(other.payload)
                    && settled.state.operation(ROOM, otherMember).dispatchStarted == higherAck
                    && settled.state.operation(ROOM, otherMember).blockedCode.equals("membership_changed"),
                    "Settle exact old UUID only; other epoch payload/flags neither authorized nor rewritten");
            RoomPreferencesStore.State reloaded = kind(new RoomPreferencesStore(context, ACCOUNT).load(), RoomPreferencesStore.Kind.LOADED).state;
            check(reloaded.snapshots.isEmpty() && reloaded.pending.size() == 1 && reloaded.operation(ROOM, otherMember).pending.payload.equals(other.payload)
                    && reloaded.operation(ROOM, otherMember).dispatchStarted == higherAck
                    && reloaded.operation(ROOM, otherMember).blockedCode.equals("membership_changed"), "Reload preserves empty cache and other exact operation");
            byte[] before = Files.readAllBytes(file(host, context, ACCOUNT).toPath());
            kind(store.acknowledge(old, ack(old, 99, true)), RoomPreferencesStore.Kind.NO_MATCH);
            check(Arrays.equals(before, Files.readAllBytes(file(host, context, ACCOUNT).toPath())), "Duplicate cannot create deferred old cache");
        }
        return checks;
    }
    private static void construction(Host host) throws Exception {
        Context context = host.context("constructor");
        RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
        check(host.lookups(context) == 0 && !file(host, context, ACCOUNT).exists(), "Constructor has no filesDir lookup or file I/O");
        host.main(() -> {
            mainRejected(store::load);
            mainRejected(() -> store.stage(null, 0));
            mainRejected(() -> store.saveSnapshot(null, 0));
            mainRejected(() -> store.markDispatchStarted(null));
            mainRejected(() -> store.cancelUnsent(null));
            mainRejected(() -> store.markBlocked(null, "unavailable"));
            mainRejected(() -> store.acknowledge(null, null));
        });
        check(host.lookups(context) == 0 && !file(host, context, ACCOUNT).getParentFile().exists(), "MAIN rejection precedes even directory lookup/creation");
        RoomPreferencesStore.State absent = kind(store.load(), RoomPreferencesStore.Kind.ABSENT).state;
        check(absent.revision == 0 && absent.snapshots.isEmpty() && absent.pending.isEmpty(), "True absence only, not authenticated server state");
        check(!file(host, context, ACCOUNT).getParentFile().exists(), "Absent read does not mkdir");
    }
    private static void lifecycle(Host host) throws Exception {
        Context context = host.context("lifecycle"); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
        RoomPreferencesProtocol.Pending pending = pending(ROOM, MEMBER, 1, 1);
        RoomPreferencesStore.Result staged = kind(store.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        check(staged.state.revision == 1 && !staged.state.pending.get(0).dispatchStarted, "Stage commits never-started exact operation");
        check(staged.state.pending.get(0).pending.payload.equals(pending.payload), "Payload bytes retained");
        kind(store.stage(pending, 0), RoomPreferencesStore.Kind.CONFLICT);
        kind(store.stage(pending, 1), RoomPreferencesStore.Kind.UNCHANGED);
        kind(store.acknowledge(pending, ack(pending, 2, false)), RoomPreferencesStore.Kind.INVALID);
        kind(store.markDispatchStarted(pending), RoomPreferencesStore.Kind.COMMITTED);
        kind(store.markDispatchStarted(pending), RoomPreferencesStore.Kind.UNCHANGED);
        kind(store.cancelUnsent(pending), RoomPreferencesStore.Kind.BLOCKED);
        kind(store.markBlocked(pending, "request_unknown"), RoomPreferencesStore.Kind.COMMITTED);
        RoomPreferencesStore.Result repeat = kind(store.stage(pending, 3), RoomPreferencesStore.Kind.UNCHANGED);
        check(repeat.state.pending.get(0).dispatchStarted && repeat.state.pending.get(0).blockedCode.equals("request_unknown"), "Restage preserves unknown+blocked flags");
        kind(store.markDispatchStarted(pending), RoomPreferencesStore.Kind.BLOCKED);
        kind(store.markBlocked(pending, "server raw payload/token/name"), RoomPreferencesStore.Kind.INVALID);
        kind(store.markBlocked(pending, "request_unknown"), RoomPreferencesStore.Kind.UNCHANGED);
        kind(store.markDispatchStarted(pending(ROOM, MEMBER, 1, 2)), RoomPreferencesStore.Kind.NO_MATCH);
        RoomPreferencesProtocol.Pending duplicateUuid = RoomPreferencesProtocol.newPending(fresh(99, 199, 1), pending.clientUuid, PAST, false, true, true);
        kind(store.stage(duplicateUuid, 3), RoomPreferencesStore.Kind.CONFLICT);
        RoomPreferencesProtocol.Pending altered = RoomPreferencesProtocol.newPending(fresh(ROOM, MEMBER, 1), pending.clientUuid, PAST, false, false, true);
        kind(store.markDispatchStarted(altered), RoomPreferencesStore.Kind.NO_MATCH);
        kind(store.cancelUnsent(altered), RoomPreferencesStore.Kind.NO_MATCH);
        kind(store.acknowledge(altered, ack(altered, 2, false)), RoomPreferencesStore.Kind.NO_MATCH);
        RoomPreferencesStore.State reopened = kind(new RoomPreferencesStore(context, ACCOUNT).load(), RoomPreferencesStore.Kind.LOADED).state;
        check(reopened.pending.get(0).dispatchStarted && reopened.pending.get(0).blockedCode.equals("request_unknown")
                && reopened.pending.get(0).pending.payload.equals(pending.payload), "Flags/UUID/payload survive reopen (same process here)");
        RoomPreferencesStore.Result settled = kind(store.acknowledge(pending, ack(pending, 2, false)), RoomPreferencesStore.Kind.COMMITTED);
        check(settled.state.pending.isEmpty() && settled.state.snapshot(ROOM).revision == 2 && !settled.state.snapshot(ROOM).freshGet, "Exact blocked unknown operation can settle, cache remains nonfresh");
        byte[] before = Files.readAllBytes(file(host, context, ACCOUNT).toPath());
        kind(store.acknowledge(pending, ack(pending, 99, true)), RoomPreferencesStore.Kind.NO_MATCH);
        check(Arrays.equals(before, Files.readAllBytes(file(host, context, ACCOUNT).toPath())), "Duplicate settlement cannot update cache");
        try { settled.state.pending.add(null); throw new AssertionError("Mutable state list"); } catch (UnsupportedOperationException expected) { ++checks; }
        try { settled.state.snapshots.clear(); throw new AssertionError("Mutable snapshots"); } catch (UnsupportedOperationException expected) { ++checks; }
        Context cancelContext = host.context("cancel-empty"); RoomPreferencesStore cancel = new RoomPreferencesStore(cancelContext, ACCOUNT);
        kind(cancel.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        kind(cancel.markBlocked(pending, "revision_conflict"), RoomPreferencesStore.Kind.COMMITTED);
        RoomPreferencesStore.Result empty = kind(cancel.cancelUnsent(pending), RoomPreferencesStore.Kind.COMMITTED);
        check(empty.state.pending.isEmpty() && empty.state.revision == 3, "Explicit never-started cancellation retains committed empty envelope");
        kind(cancel.load(), RoomPreferencesStore.Kind.LOADED);
    }
    private static void snapshots(Host host) throws Exception {
        Context context = host.context("snapshots"); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
        kind(store.saveSnapshot(fresh(ROOM, MEMBER, 9), 0), RoomPreferencesStore.Kind.COMMITTED);
        kind(store.saveSnapshot(fresh(ROOM, MEMBER, 8), 1), RoomPreferencesStore.Kind.UNCHANGED);
        kind(store.saveSnapshot(fresh(ROOM, MEMBER, 10), 0), RoomPreferencesStore.Kind.CONFLICT);
        kind(store.saveSnapshot(fresh(ROOM, MEMBER + 1, 10), 1), RoomPreferencesStore.Kind.EPOCH_CONFLICT);
        kind(store.stage(pending(ROOM, MEMBER + 1, 1, 3), 1), RoomPreferencesStore.Kind.EPOCH_CONFLICT);
        RoomPreferencesProtocol.Snapshot expired = RoomPreferencesProtocol.freshSnapshot(
                snapshotBody(ROOM, MEMBER, 9, false, false).put("muted", false), ACCOUNT, ROOM, MEMBER);
        RoomPreferencesStore.Result saved = kind(store.saveSnapshot(expired, 1), RoomPreferencesStore.Kind.COMMITTED);
        check(!saved.state.snapshot(ROOM).muted && !saved.state.snapshot(ROOM).freshGet, "Current GET derived expiry updates, disk snapshot not fresh");
        AccountScope foreign = new AccountScope(ACCOUNT.origin, ACCOUNT.database, 8);
        RoomPreferencesProtocol.Snapshot wrong = RoomPreferencesProtocol.freshSnapshot(snapshotBody(ROOM, MEMBER, 20, false, false), foreign, ROOM, MEMBER);
        kind(store.saveSnapshot(wrong, 2), RoomPreferencesStore.Kind.INVALID);
        RoomPreferencesProtocol.Pending wrongPending = RoomPreferencesProtocol.newPending(wrong, uuid(4), null, false, false, false);
        kind(store.stage(wrongPending, 2), RoomPreferencesStore.Kind.INVALID);
        check(!file(host, context, foreign).exists(), "Foreign input cannot create another account's file");
    }
    private static void concurrency(Host host) throws Exception {
        Context context = host.context("concurrent-cas");
        RoomPreferencesStore first = new RoomPreferencesStore(context, ACCOUNT), second = new RoomPreferencesStore(context, ACCOUNT);
        RoomPreferencesProtocol.Pending a = pending(31, 41, 1, 5), b = pending(32, 42, 1, 6);
        RoomPreferencesStore.Result[] results = pair(() -> first.stage(a, 0), () -> second.stage(b, 0));
        check((results[0].kind == RoomPreferencesStore.Kind.COMMITTED && results[1].kind == RoomPreferencesStore.Kind.CONFLICT)
                || (results[1].kind == RoomPreferencesStore.Kind.COMMITTED && results[0].kind == RoomPreferencesStore.Kind.CONFLICT), "Two instances competing same revision have one winner");
        RoomPreferencesStore.State state = first.load().state;
        kind(first.stage(state.operation(31, 41) == null ? a : b, state.revision), RoomPreferencesStore.Kind.COMMITTED);
        results = pair(() -> first.markDispatchStarted(a), () -> second.markDispatchStarted(b));
        check(results[0].kind == RoomPreferencesStore.Kind.COMMITTED && results[1].kind == RoomPreferencesStore.Kind.COMMITTED, "Different-room exact updates retain each other");
        state = first.load().state;
        check(state.pending.size() == 2 && state.operation(31, 41).dispatchStarted && state.operation(32, 42).dispatchStarted && state.revision == 4,
                "Process-wide lock prevents lost unrelated-room update");
    }
    private interface Work { RoomPreferencesStore.Result run() throws Exception; }
    private static RoomPreferencesStore.Result[] pair(Work first, Work second) throws Exception {
        CountDownLatch ready = new CountDownLatch(2), start = new CountDownLatch(1);
        RoomPreferencesStore.Result[] values = new RoomPreferencesStore.Result[2]; AtomicReference<Throwable> failed = new AtomicReference<>();
        Thread[] threads = new Thread[2]; Work[] work = {first, second};
        for (int index = 0; index < 2; ++index) { final int slot = index;
            threads[index] = new Thread(() -> { ready.countDown(); try {
                if (!start.await(5, TimeUnit.SECONDS)) throw new AssertionError("Start deadline"); values[slot] = work[slot].run();
            } catch (Throwable error) { failed.set(error); } }, "c17-cas-" + index); threads[index].start();
        }
        if (!ready.await(5, TimeUnit.SECONDS)) throw new AssertionError("Workers not ready"); start.countDown();
        for (Thread thread : threads) { thread.join(15000); if (thread.isAlive()) throw new AssertionError("Worker deadline"); }
        if (failed.get() != null) throw new AssertionError(failed.get()); return values;
    }
    private static void caps(Host host) throws Exception {
        Context context = host.context("caps"); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
        for (int index = 1; index <= 100; ++index)
            kind(store.saveSnapshot(fresh(index, index + 1000, 1), index - 1), RoomPreferencesStore.Kind.COMMITTED);
        kind(store.saveSnapshot(fresh(101, 1101, 1), 100), RoomPreferencesStore.Kind.CAPACITY);
        for (int index = 1; index <= 20; ++index)
            kind(store.stage(pending(index, index + 1000, 1, 100 + index), 99 + index), RoomPreferencesStore.Kind.COMMITTED);
        RoomPreferencesProtocol.Pending first = pending(1, 1001, 1, 101);
        kind(store.markDispatchStarted(first), RoomPreferencesStore.Kind.COMMITTED);
        kind(store.markBlocked(first, "request_unknown"), RoomPreferencesStore.Kind.COMMITTED);
        kind(store.stage(pending(21, 1021, 1, 121), 122), RoomPreferencesStore.Kind.CAPACITY);
        check(store.load().state.snapshots.size() == 100 && store.load().state.pending.size() == 20,
                "100 unique rooms/20 operations including blocked+unknown; no eviction");
        check(file(host, context, ACCOUNT).length() <= RoomPreferencesStore.MAX_BYTES, "Valid bounded metadata fits byte cap");
    }
    private static void corrupt(Host host) throws Exception {
        Context prototypeContext = host.context("prototype"); RoomPreferencesStore prototype = new RoomPreferencesStore(prototypeContext, ACCOUNT);
        RoomPreferencesProtocol.Pending pending = pending(ROOM, MEMBER, 1, 7);
        kind(prototype.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        kind(prototype.saveSnapshot(fresh(ROOM, MEMBER, 1), 1), RoomPreferencesStore.Kind.COMMITTED);
        String valid = text(file(host, prototypeContext, ACCOUNT));
        List<byte[]> cases = new ArrayList<>();
        cases.add(new byte[0]); cases.add("{".getBytes(StandardCharsets.UTF_8)); cases.add(new byte[]{(byte) 0xc3, 0x28});
        cases.add((valid + " ").getBytes(StandardCharsets.UTF_8)); cases.add(valid.replace("\"store_revision\":2", "\"store_revision\":0").getBytes(StandardCharsets.UTF_8));
        cases.add(valid.replace("\"store_revision\":2", "\"store_revision\":2.0").getBytes(StandardCharsets.UTF_8));
        JSONObject item = new JSONObject(valid); item.put("scope_key", "0".repeat(64)); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        item = new JSONObject(valid).put("extra", "forbidden"); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        item = new JSONObject(valid); item.remove("pending"); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        for (Object bad : new Object[]{"raw server token", 0, JSONObject.NULL}) {
            item = new JSONObject(valid); ((JSONObject) ((JSONArray) item.opt("pending")).opt(0)).put("blocked_code", bad);
            cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        }
        item = new JSONObject(valid); ((JSONObject) ((JSONArray) item.opt("pending")).opt(0)).put("dispatch_started", "false"); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        item = new JSONObject(valid); ((JSONObject) ((JSONArray) item.opt("pending")).opt(0)).put("payload", " " + pending.payload); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        item = new JSONObject(valid); JSONArray array = (JSONArray) item.opt("pending"); array.put(array.opt(0)); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        item = new JSONObject(valid); array = (JSONArray) item.opt("snapshots"); array.put(array.opt(0)); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        item = new JSONObject(valid); ((JSONObject) ((JSONArray) item.opt("snapshots")).opt(0)).put("freshGet", true); cases.add(item.toString().getBytes(StandardCharsets.UTF_8));
        for (int index = 0; index < cases.size(); ++index) {
            Context context = host.context("corrupt-" + index); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
            File target = file(host, context, ACCOUNT); byte[] bytes = cases.get(index); write(target, bytes);
            kind(store.load(), RoomPreferencesStore.Kind.CORRUPT);
            kind(store.stage(pending, 0), RoomPreferencesStore.Kind.CORRUPT);
            kind(store.saveSnapshot(fresh(ROOM, MEMBER, 1), 0), RoomPreferencesStore.Kind.CORRUPT);
            kind(store.markDispatchStarted(pending), RoomPreferencesStore.Kind.CORRUPT);
            kind(store.cancelUnsent(pending), RoomPreferencesStore.Kind.CORRUPT);
            kind(store.markBlocked(pending, "unavailable"), RoomPreferencesStore.Kind.CORRUPT);
            kind(store.acknowledge(pending, ack(pending, 2, false)), RoomPreferencesStore.Kind.CORRUPT);
            check(Arrays.equals(bytes, Files.readAllBytes(target.toPath())), "Invalid file preserved, no partial recovery/reset");
        }
        Context unsupported = host.context("unsupported"); write(file(host, unsupported, ACCOUNT), valid.replace("\"format_version\":1", "\"format_version\":2"));
        kind(new RoomPreferencesStore(unsupported, ACCOUNT).stage(pending, 0), RoomPreferencesStore.Kind.UNSUPPORTED);
        Context large = host.context("oversize"); write(file(host, large, ACCOUNT), new byte[RoomPreferencesStore.MAX_BYTES + 1]);
        kind(new RoomPreferencesStore(large, ACCOUNT).load(), RoomPreferencesStore.Kind.TOO_LARGE);
        kind(new RoomPreferencesStore(large, ACCOUNT).stage(pending, 0), RoomPreferencesStore.Kind.TOO_LARGE);
        check(file(host, large, ACCOUNT).length() == RoomPreferencesStore.MAX_BYTES + 1, "Overlimit file preserved before parsing/writing");
        Context directory = host.context("not-a-file"); File invalidPath = file(host, directory, ACCOUNT);
        check(invalidPath.mkdirs(), "Owned directory at metadata path fixture");
        kind(new RoomPreferencesStore(directory, ACCOUNT).stage(pending, 0), RoomPreferencesStore.Kind.IO_FAILURE);
        check(invalidPath.isDirectory(), "Unsafe metadata path not overwritten");
    }
    private static void atomic(Host host) throws Exception {
        Context context = host.context("atomic"); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
        RoomPreferencesProtocol.Pending pending = pending(ROOM, MEMBER, 1, 8);
        kind(store.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        File target = file(host, context, ACCOUNT); byte[] original = Files.readAllBytes(target.toPath());
        write(new File(target + ".new"), "partial first attempt");
        kind(store.load(), RoomPreferencesStore.Kind.LOADED);
        check(Arrays.equals(original, Files.readAllBytes(target.toPath())) && !new File(target + ".new").exists(), "Valid base plus partial .new recovers old committed base");
        write(new File(target + ".bak"), original); write(target, "partial base");
        kind(store.load(), RoomPreferencesStore.Kind.LOADED);
        check(Arrays.equals(original, Files.readAllBytes(target.toPath())) && !new File(target + ".bak").exists(), "Native-compatible legacy backup rollback");
        Context backupOnly = host.context("backup-only"); File backup = new File(file(host, backupOnly, ACCOUNT) + ".bak"); write(backup, original);
        kind(new RoomPreferencesStore(backupOnly, ACCOUNT).load(), RoomPreferencesStore.Kind.LOADED);
        check(Arrays.equals(original, Files.readAllBytes(file(host, backupOnly, ACCOUNT).toPath())) && !backup.exists(), "Valid backup alone recovers committed state, not absence");
        write(new File(target + ".bak"), "invalid backup");
        kind(store.load(), RoomPreferencesStore.Kind.CORRUPT);
        check(Arrays.equals(original, Files.readAllBytes(target.toPath())) && text(new File(target + ".bak")).equals("invalid backup"), "Corrupt backup never clobbers healthy base");
        Context orphan = host.context("orphan"); File only = new File(file(host, orphan, ACCOUNT) + ".new"); write(only, original);
        kind(new RoomPreferencesStore(orphan, ACCOUNT).stage(pending, 0), RoomPreferencesStore.Kind.CORRUPT);
        check(only.exists() && Arrays.equals(original, Files.readAllBytes(only.toPath())), "Orphan-only .new is not empty or silently installed");
        Context silent = host.context("silent-finish"); RoomPreferencesStore good = new RoomPreferencesStore(silent, ACCOUNT);
        kind(good.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        byte[] before = Files.readAllBytes(file(host, silent, ACCOUNT).toPath());
        RoomPreferencesStore noCommit = new RoomPreferencesStore(silent, ACCOUNT, StoreFaults.SilentFinish::new);
        kind(noCommit.markDispatchStarted(pending), RoomPreferencesStore.Kind.UNCERTAIN);
        check(!good.load().state.pending.get(0).dispatchStarted && Arrays.equals(before, Files.readAllBytes(file(host, silent, ACCOUNT).toPath())), "Silent finish cannot grant start or change old committed state");
        Context firstSilent = host.context("first-silent"); RoomPreferencesStore first = new RoomPreferencesStore(firstSilent, ACCOUNT, StoreFaults.SilentFinish::new);
        kind(first.stage(pending, 0), RoomPreferencesStore.Kind.UNCERTAIN);
        kind(new RoomPreferencesStore(firstSilent, ACCOUNT).load(), RoomPreferencesStore.Kind.CORRUPT);
        Context sync = host.context("sync-failure"); RoomPreferencesStore synced = new RoomPreferencesStore(sync, ACCOUNT);
        kind(synced.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        kind(new RoomPreferencesStore(sync, ACCOUNT, StoreFaults.ClosedBeforeSync::new).markDispatchStarted(pending), RoomPreferencesStore.Kind.UNCERTAIN);
        check(!synced.load().state.pending.get(0).dispatchStarted, "Throwing FD sync failure retains old flag");
    }
    private static RoomPreferencesProtocol.Acknowledgement forged(RoomPreferencesProtocol.Snapshot snapshot,
            RoomPreferencesProtocol.Pending pending, long operation, boolean replayed) throws Exception {
        Constructor<RoomPreferencesProtocol.Acknowledgement> constructor = RoomPreferencesProtocol.Acknowledgement.class.getDeclaredConstructor(
                RoomPreferencesProtocol.Snapshot.class, RoomPreferencesProtocol.Pending.class, long.class, boolean.class);
        constructor.setAccessible(true); return constructor.newInstance(snapshot, pending, operation, replayed);
    }
    private static void acknowledgements(Host host) throws Exception {
        Context context = host.context("ack-checks"); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
        RoomPreferencesProtocol.Pending pending = pending(ROOM, MEMBER, 1, 9);
        kind(store.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        kind(store.markDispatchStarted(pending), RoomPreferencesStore.Kind.COMMITTED);
        RoomPreferencesProtocol.Snapshot current = RoomPreferencesProtocol.freshSnapshot(snapshotBody(ROOM, MEMBER, 2, true, true), ACCOUNT, ROOM, MEMBER);
        kind(store.acknowledge(pending, forged(current, pending, 3, false)), RoomPreferencesStore.Kind.INVALID);
        kind(store.acknowledge(pending, forged(fresh(ROOM, MEMBER, 1), pending, 2, true)), RoomPreferencesStore.Kind.INVALID);
        RoomPreferencesProtocol.Snapshot higher = RoomPreferencesProtocol.freshSnapshot(snapshotBody(ROOM, MEMBER, 3, true, true), ACCOUNT, ROOM, MEMBER);
        kind(store.acknowledge(pending, forged(higher, pending, 2, false)), RoomPreferencesStore.Kind.INVALID);
        kind(store.acknowledge(pending, forged(current, pending(ROOM, MEMBER, 1, 10), 2, false)), RoomPreferencesStore.Kind.INVALID);
        AccountScope foreign = new AccountScope(ACCOUNT.origin, ACCOUNT.database, 8);
        RoomPreferencesProtocol.Snapshot wrong = RoomPreferencesProtocol.freshSnapshot(snapshotBody(ROOM, MEMBER, 2, true, true), foreign, ROOM, MEMBER);
        kind(store.acknowledge(pending, forged(wrong, pending, 2, false)), RoomPreferencesStore.Kind.INVALID);
        kind(store.saveSnapshot(fresh(ROOM, MEMBER, 9), 2), RoomPreferencesStore.Kind.COMMITTED);
        RoomPreferencesStore.Result settled = kind(store.acknowledge(pending, ack(pending, 2, false)), RoomPreferencesStore.Kind.COMMITTED);
        check(settled.state.snapshot(ROOM).revision == 9 && settled.state.pending.isEmpty(), "Valid old ACK retires UUID without rolling cache back");
        Context epoch = host.context("stale-epoch"); RoomPreferencesStore epochs = new RoomPreferencesStore(epoch, ACCOUNT);
        kind(epochs.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED); kind(epochs.markDispatchStarted(pending), RoomPreferencesStore.Kind.COMMITTED);
        File target = file(host, epoch, ACCOUNT); JSONObject envelope = new JSONObject(text(target));
        ((JSONArray) envelope.opt("snapshots")).put(snapshotBody(ROOM, MEMBER + 1, 50, false, false)); write(target, envelope.toString());
        kind(epochs.markDispatchStarted(pending), RoomPreferencesStore.Kind.EPOCH_CONFLICT);
        RoomPreferencesStore.Result old = kind(epochs.acknowledge(pending, ack(pending, 2, false)), RoomPreferencesStore.Kind.COMMITTED);
        check(old.state.snapshot(ROOM).membershipId == MEMBER + 1 && old.state.snapshot(ROOM).revision == 50 && old.state.pending.isEmpty(), "Old exact ACK cannot replace newer epoch cache");
    }
    private static void overflow(Host host) throws Exception {
        Context context = host.context("overflow"); RoomPreferencesStore store = new RoomPreferencesStore(context, ACCOUNT);
        RoomPreferencesProtocol.Pending pending = pending(ROOM, MEMBER, 1, 11); kind(store.stage(pending, 0), RoomPreferencesStore.Kind.COMMITTED);
        File target = file(host, context, ACCOUNT); String max = text(target).replace("\"store_revision\":1", "\"store_revision\":" + Long.MAX_VALUE); write(target, max);
        kind(store.load(), RoomPreferencesStore.Kind.LOADED);
        kind(store.markDispatchStarted(pending), RoomPreferencesStore.Kind.EXHAUSTED);
        kind(store.cancelUnsent(pending), RoomPreferencesStore.Kind.EXHAUSTED);
        check(text(target).equals(max), "Store revision never wraps or changes bytes on exhaustion");
    }
    private StoreCases() { }
}

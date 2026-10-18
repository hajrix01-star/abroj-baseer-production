package com.baseer.freshchat;

import android.content.Context;
import android.os.Looper;
import android.util.AtomicFile;
import com.baseer.freshchat.sync.AccountScope;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Private metadata durability, not authentication, current membership, a mute effect or HTTP
 * permission. All operations are synchronous WORKER-only; the caller later owns scheduling,
 * current rights/tickets and publishing RAM only after this lock has been released.
 * No constructor disk access, network, ROUTING lock, UI callback or automatic repair/reset.
 * The process-wide lock does not claim inter-process writers or hardware power-loss safety.
 */
final class RoomPreferencesStore {
    static final int MAX_BYTES = 256 * 1024, MAX_SNAPSHOTS = 100, MAX_PENDING = 20;
    private static final Object FILE_LOCK = new Object();
    private static final Set<String> BLOCK_CODES = new HashSet<>(Arrays.asList(
            "revision_conflict", "membership_changed", "permission_denied", "invalid_payload",
            "unavailable", "storage_unavailable", "request_unknown"));
    private static final Set<String> ENVELOPE_KEYS = keys("format_version", "scope_key", "store_revision", "snapshots", "pending");
    private static final Set<String> SNAPSHOT_KEYS = keys("api_version", "room_id", "membership_id", "revision",
            "muted_until", "mute_forever", "muted", "pinned", "pinned_at", "archived");
    private static final Set<String> OPERATION_KEYS = keys("room_id", "payload", "dispatch_started", "blocked_code");

    enum Kind { LOADED, ABSENT, COMMITTED, UNCHANGED, NO_MATCH, CONFLICT, EPOCH_CONFLICT,
        BLOCKED, CAPACITY, INVALID, CORRUPT, UNSUPPORTED, TOO_LARGE, IO_FAILURE, UNCERTAIN, EXHAUSTED }

    static final class Operation {
        final RoomPreferencesProtocol.Pending pending;
        final boolean dispatchStarted;
        final String blockedCode;
        private Operation(RoomPreferencesProtocol.Pending pending, boolean started, String blocked) {
            this.pending = pending; dispatchStarted = started; blockedCode = blocked;
        }
    }
    static final class State {
        final long revision;
        final List<RoomPreferencesProtocol.Snapshot> snapshots;
        final List<Operation> pending;
        private State(long revision, List<RoomPreferencesProtocol.Snapshot> snapshots, List<Operation> pending) {
            this.revision = revision;
            this.snapshots = Collections.unmodifiableList(new ArrayList<>(snapshots));
            this.pending = Collections.unmodifiableList(new ArrayList<>(pending));
        }
        RoomPreferencesProtocol.Snapshot snapshot(long room) {
            for (RoomPreferencesProtocol.Snapshot item : snapshots) if (item.roomId == room) return item;
            return null;
        }
        Operation operation(long room, long membership) {
            for (Operation item : pending) if (item.pending.roomId == room && item.pending.membershipId == membership) return item;
            return null;
        }
    }
    static final class Result {
        final Kind kind;
        /** Null for an unreadable file; ABSENT is not an authenticated unmuted snapshot. */
        final State state;
        private Result(Kind kind, State state) { this.kind = kind; this.state = state; }
        // Deliberately no canDispatch/boolean-success convenience method. Even COMMITTED
        // may describe snapshot storage, cancellation or settlement, never HTTP authority.
    }

    /** Narrow I/O seam for AtomicFile failure tests, never an application/Host callback. */
    interface AtomicFiles { AtomicFile create(File base); }
    private final Context application;
    private final AccountScope account;
    private final AtomicFiles atomicFiles;

    RoomPreferencesStore(Context context, AccountScope account) { this(context, account, AtomicFile::new); }
    RoomPreferencesStore(Context context, AccountScope account, AtomicFiles files) {
        if (context == null || account == null || files == null) throw new IllegalArgumentException("Store context and scope required");
        Context app = context.getApplicationContext();
        if (app == null) throw new IllegalArgumentException("Application context required");
        application = app; this.account = account; atomicFiles = files;
    }

    Result load() {
        worker();
        synchronized (FILE_LOCK) { return read().result; }
    }

    Result stage(RoomPreferencesProtocol.Pending operation, long expectedStoreRevision) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            State state = current.result.state;
            if (!validPending(operation)) return result(Kind.INVALID, state);
            if (expectedStoreRevision != state.revision) return result(Kind.CONFLICT, state);
            Operation same = state.operation(operation.roomId, operation.membershipId);
            if (same != null) return result(exact(same.pending, operation) ? Kind.UNCHANGED : Kind.CONFLICT, state);
            for (Operation item : state.pending)
                if (item.pending.clientUuid.equals(operation.clientUuid)) return result(Kind.CONFLICT, state);
            RoomPreferencesProtocol.Snapshot snapshot = state.snapshot(operation.roomId);
            if (snapshot != null && snapshot.membershipId != operation.membershipId) return result(Kind.EPOCH_CONFLICT, state);
            if (state.pending.size() >= MAX_PENDING) return result(Kind.CAPACITY, state);
            List<Operation> pending = new ArrayList<>(state.pending);
            pending.add(new Operation(operation, false, ""));
            return commit(current, state.snapshots, pending);
        }
    }

    Result saveSnapshot(RoomPreferencesProtocol.Snapshot incoming, long expectedStoreRevision) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            State state = current.result.state;
            if (!validSnapshot(incoming)) return result(Kind.INVALID, state);
            if (expectedStoreRevision != state.revision) return result(Kind.CONFLICT, state);
            RoomPreferencesProtocol.Snapshot old = state.snapshot(incoming.roomId);
            if (old != null && old.membershipId != incoming.membershipId) return result(Kind.EPOCH_CONFLICT, state);
            try {
                RoomPreferencesProtocol.Snapshot selected = RoomPreferencesProtocol.mergeSnapshot(old, incoming);
                if (old != null && snapshotJson(old).equals(snapshotJson(selected))) return result(Kind.UNCHANGED, state);
                if (old == null && state.snapshots.size() >= MAX_SNAPSHOTS) return result(Kind.CAPACITY, state);
                List<RoomPreferencesProtocol.Snapshot> snapshots = new ArrayList<>(state.snapshots);
                snapshots.remove(old); snapshots.add(cached(selected));
                return commit(current, snapshots, state.pending);
            } catch (IllegalArgumentException | JSONException invalid) { return result(Kind.CONFLICT, state); }
        }
    }

    /** Exact metadata-only epoch replacement, NOT authentication/current-membership proof.
     * A future Host must independently own the complete current authenticated rooms result
     * and this new binding's actual GET. Neither provenCurrentMember nor freshGet proves it.
     * No caller is wired here; pending operations and mute/index state are not reconciled.
     */
    Result replaceMembershipSnapshotExact(RoomPreferencesProtocol.Snapshot oldSnapshot,
            RoomPreferencesProtocol.Snapshot freshSnapshot, long provenCurrentMember, long expectedStoreRevision) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            State state = current.result.state;
            if (!validSnapshot(oldSnapshot) || !validSnapshot(freshSnapshot) || !freshSnapshot.freshGet
                    || provenCurrentMember <= 0 || provenCurrentMember > Integer.MAX_VALUE
                    || oldSnapshot.roomId != freshSnapshot.roomId || provenCurrentMember != freshSnapshot.membershipId
                    || oldSnapshot.membershipId == freshSnapshot.membershipId) return result(Kind.INVALID, state);
            if (expectedStoreRevision != state.revision) return result(Kind.CONFLICT, state);
            RoomPreferencesProtocol.Snapshot stored = state.snapshot(oldSnapshot.roomId);
            if (stored == null) return result(Kind.NO_MATCH, state);
            // Full canonical CAS includes derived muted, not only mergeSnapshot metadata.
            if (!snapshotJson(stored).equals(snapshotJson(oldSnapshot))) return result(Kind.CONFLICT, state);
            try {
                List<RoomPreferencesProtocol.Snapshot> snapshots = new ArrayList<>(state.snapshots);
                snapshots.remove(stored); snapshots.add(cached(freshSnapshot));
                // Revisions are per membership: a lower fresh revision across epochs is valid.
                return commit(current, snapshots, state.pending);
            } catch (IllegalArgumentException | JSONException invalid) { return result(Kind.INVALID, state); }
        }
    }

    Result markDispatchStarted(RoomPreferencesProtocol.Pending operation) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            Operation found = matching(current.result.state, operation);
            if (found == null) return result(Kind.NO_MATCH, current.result.state);
            RoomPreferencesProtocol.Snapshot cached = current.result.state.snapshot(found.pending.roomId);
            if (cached != null && cached.membershipId != found.pending.membershipId)
                return result(Kind.EPOCH_CONFLICT, current.result.state);
            if (!found.blockedCode.isEmpty()) return result(Kind.BLOCKED, current.result.state);
            if (found.dispatchStarted) return result(Kind.UNCHANGED, current.result.state);
            return replace(current, found, new Operation(found.pending, true, found.blockedCode));
        }
    }

    Result cancelUnsent(RoomPreferencesProtocol.Pending operation) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            Operation found = matching(current.result.state, operation);
            if (found == null) return result(Kind.NO_MATCH, current.result.state);
            if (found.dispatchStarted) return result(Kind.BLOCKED, current.result.state);
            return replace(current, found, null);
        }
    }

    /** Exact terminal HTTP receipt only; never a GET/marker/clock proof or a mute release.
     * Controller owns authentication and the identity fence at Store entry, as for ACK. */
    Result cancelledExact(RoomPreferencesProtocol.Pending operation, RoomPreferencesProtocol.Cancellation cancellation) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            Operation found = matching(current.result.state, operation);
            if (found == null) return result(Kind.NO_MATCH, current.result.state);
            if (!found.dispatchStarted || cancellation == null || !cancellation.matches(found.pending))
                return result(Kind.INVALID, current.result.state);
            return replace(current, found, null); // Preserve every snapshot and other pending exactly.
        }
    }

    Result markBlocked(RoomPreferencesProtocol.Pending operation, String code) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            if (!BLOCK_CODES.contains(code)) return result(Kind.INVALID, current.result.state);
            Operation found = matching(current.result.state, operation);
            if (found == null) return result(Kind.NO_MATCH, current.result.state);
            if (found.blockedCode.equals(code)) return result(Kind.UNCHANGED, current.result.state);
            return replace(current, found, new Operation(found.pending, found.dispatchStarted, code));
        }
    }

    /** Metadata-only primitive. The Controller must own the original authenticated rejection
     * and the actual current GET; a stored blockedCode is NOT that authority. No HTTP grant. */
    Result replaceExactRejected(RoomPreferencesProtocol.Pending old, RoomPreferencesProtocol.Snapshot fresh,
            RoomPreferencesProtocol.Pending replacement, long expectedStoreRevision) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            State state = current.result.state;
            if (!validPending(old) || !validPending(replacement) || !validSnapshot(fresh) || !fresh.freshGet
                    || !RoomPreferencesProtocol.sameBinding(old.account, old.roomId, old.membershipId,
                            fresh.account, fresh.roomId, fresh.membershipId)
                    || !RoomPreferencesProtocol.sameBinding(old.account, old.roomId, old.membershipId,
                            replacement.account, replacement.roomId, replacement.membershipId)
                    || fresh.revision <= old.expectedRevision || replacement.expectedRevision != fresh.revision
                    || old.clientUuid.equals(replacement.clientUuid)) return result(Kind.INVALID, state);
            if (expectedStoreRevision != state.revision) return result(Kind.CONFLICT, state);
            Operation found = matching(state, old);
            if (found == null) return result(Kind.NO_MATCH, state);
            if (!found.dispatchStarted || !"revision_conflict".equals(found.blockedCode)) return result(Kind.BLOCKED, state);
            for (Operation item : state.pending)
                if (item.pending.clientUuid.equals(replacement.clientUuid)) return result(Kind.CONFLICT, state);
            RoomPreferencesProtocol.Snapshot cached = state.snapshot(old.roomId);
            if (cached != null && cached.membershipId != old.membershipId) return result(Kind.EPOCH_CONFLICT, state);
            // Never select a higher cache then dispatch an intent based on the older GET.
            if (cached != null && cached.revision > fresh.revision) return result(Kind.CONFLICT, state);
            final RoomPreferencesProtocol.Snapshot confirmed;
            try { RoomPreferencesProtocol.mergeSnapshot(cached, fresh); confirmed = cached(fresh); }
            catch (IllegalArgumentException | JSONException invalid) { return result(Kind.CONFLICT, state); }
            if (cached == null && state.snapshots.size() >= MAX_SNAPSHOTS) return result(Kind.CAPACITY, state);
            List<RoomPreferencesProtocol.Snapshot> snapshots = new ArrayList<>(state.snapshots);
            snapshots.remove(cached); snapshots.add(confirmed);
            List<Operation> pending = new ArrayList<>(state.pending);
            pending.remove(found); pending.add(new Operation(replacement, false, ""));
            return commit(current, snapshots, pending);
        }
    }

    /** No caller/proof construction is wired yet. A future owner must positively prove the
     * SAME room's different current membership from a complete authenticated rooms result.
     * Absence, another pending, archive projections and this primitive cannot prove that.
     * Retires local metadata only, never an ACK, message purge or index-floor release. */
    Result retireObsoleteExact(RoomPreferencesProtocol.Pending old, long provenCurrentMember, long expectedStoreRevision) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            State state = current.result.state;
            if (!validPending(old) || provenCurrentMember <= 0 || provenCurrentMember > Integer.MAX_VALUE
                    || provenCurrentMember == old.membershipId) return result(Kind.INVALID, state);
            if (expectedStoreRevision != state.revision) return result(Kind.CONFLICT, state);
            Operation found = matching(state, old);
            if (found == null) return result(Kind.NO_MATCH, state);
            RoomPreferencesProtocol.Snapshot cached = state.snapshot(old.roomId);
            if (cached != null && cached.membershipId != old.membershipId && cached.membershipId != provenCurrentMember)
                return result(Kind.EPOCH_CONFLICT, state);
            List<RoomPreferencesProtocol.Snapshot> snapshots = new ArrayList<>(state.snapshots);
            if (cached != null && cached.membershipId == old.membershipId) snapshots.remove(cached);
            List<Operation> pending = new ArrayList<>(state.pending); pending.remove(found);
            return commit(current, snapshots, pending);
        }
    }

    Result acknowledge(RoomPreferencesProtocol.Pending operation, RoomPreferencesProtocol.Acknowledgement ack) {
        worker();
        synchronized (FILE_LOCK) {
            Read current = read(); if (!current.usable()) return current.result;
            State state = current.result.state;
            Operation found = matching(state, operation);
            // A duplicate/late receipt cannot touch a cache once its exact intent retired.
            if (found == null) return result(Kind.NO_MATCH, state);
            if (!found.dispatchStarted || !validAck(found.pending, ack)) return result(Kind.INVALID, state);
            List<RoomPreferencesProtocol.Snapshot> snapshots = new ArrayList<>(state.snapshots);
            RoomPreferencesProtocol.Snapshot old = state.snapshot(found.pending.roomId);
            boolean ambiguousEpoch = false;
            if (old == null) for (Operation item : state.pending) {
                if (item.pending.roomId == found.pending.roomId && item.pending.membershipId != found.pending.membershipId)
                    ambiguousEpoch = true;
            }
            // Another pending epoch does NOT prove which membership is current/authorized.
            // With no existing cache, merely abstain from installing either epoch's view.
            if (!ambiguousEpoch && (old == null || old.membershipId == found.pending.membershipId)) {
                try {
                    RoomPreferencesProtocol.Snapshot selected = RoomPreferencesProtocol.mergeSnapshot(old, ack.snapshot);
                    if (old == null && snapshots.size() >= MAX_SNAPSHOTS) return result(Kind.CAPACITY, state);
                    snapshots.remove(old); snapshots.add(cached(selected));
                } catch (IllegalArgumentException | JSONException invalid) { return result(Kind.CONFLICT, state); }
            }
            // A separately reconciled newer epoch keeps its cache. This old exact operation
            // may still retire, but can never install/replace that other membership's view.
            List<Operation> pending = new ArrayList<>(state.pending); pending.remove(found);
            return commit(current, snapshots, pending);
        }
    }

    private Result replace(Read current, Operation old, Operation replacement) {
        List<Operation> pending = new ArrayList<>(current.result.state.pending);
        pending.remove(old); if (replacement != null) pending.add(replacement);
        return commit(current, current.result.state.snapshots, pending);
    }

    private Operation matching(State state, RoomPreferencesProtocol.Pending operation) {
        if (!validPending(operation)) return null;
        Operation found = state.operation(operation.roomId, operation.membershipId);
        return found != null && exact(found.pending, operation) ? found : null;
    }
    private boolean validPending(RoomPreferencesProtocol.Pending pending) {
        if (pending == null || !sameAccount(pending.account)) return false;
        try {
            RoomPreferencesProtocol.Pending restored = RoomPreferencesProtocol.restorePending(
                    pending.payloadObject(), account, pending.roomId);
            return exact(pending, restored);
        } catch (IllegalArgumentException invalid) { return false; }
    }
    private boolean validSnapshot(RoomPreferencesProtocol.Snapshot snapshot) {
        if (snapshot == null || !sameAccount(snapshot.account)) return false;
        try { cached(snapshot); return true; }
        catch (IllegalArgumentException | JSONException invalid) { return false; }
    }
    private boolean validAck(RoomPreferencesProtocol.Pending pending, RoomPreferencesProtocol.Acknowledgement ack) {
        if (ack == null || ack.snapshot == null || !sameAccount(ack.snapshot.account)
                || !RoomPreferencesProtocol.sameBinding(pending.account, pending.roomId, pending.membershipId,
                        ack.snapshot.account, ack.snapshot.roomId, ack.snapshot.membershipId)
                || !pending.clientUuid.equals(ack.clientUuid)) return false;
        try {
            JSONObject body = new JSONObject(snapshotJson(ack.snapshot)).put("client_uuid", ack.clientUuid)
                    .put("operation_revision", ack.operationRevision).put("replayed", ack.replayed);
            RoomPreferencesProtocol.acknowledgement(200, body, pending);
            return true;
        } catch (IllegalArgumentException | JSONException invalid) { return false; }
    }
    private boolean sameAccount(AccountScope other) {
        return other != null && account.userId == other.userId
                && account.origin.equals(other.origin) && account.database.equals(other.database);
    }
    private static boolean exact(RoomPreferencesProtocol.Pending first, RoomPreferencesProtocol.Pending second) {
        return RoomPreferencesProtocol.sameBinding(first.account, first.roomId, first.membershipId,
                second.account, second.roomId, second.membershipId) && first.clientUuid.equals(second.clientUuid)
                && first.expectedRevision == second.expectedRevision && first.payload.equals(second.payload);
    }

    private Result commit(Read before, List<RoomPreferencesProtocol.Snapshot> snapshots, List<Operation> pending) {
        State prior = before.result.state;
        if (prior.revision == Long.MAX_VALUE) return result(Kind.EXHAUSTED, prior);
        if (snapshots.size() > MAX_SNAPSHOTS || pending.size() > MAX_PENDING) return result(Kind.CAPACITY, prior);
        List<RoomPreferencesProtocol.Snapshot> sortedSnapshots = new ArrayList<>(snapshots);
        sortedSnapshots.sort(Comparator.comparingLong(value -> value.roomId));
        List<Operation> sortedPending = new ArrayList<>(pending);
        sortedPending.sort(Comparator.comparingLong((Operation value) -> value.pending.roomId)
                .thenComparingLong(value -> value.pending.membershipId));
        State next = new State(prior.revision + 1, sortedSnapshots, sortedPending);
        byte[] bytes = encode(next);
        if (bytes.length > MAX_BYTES) return result(Kind.TOO_LARGE, prior);
        FileOutputStream output = null;
        AtomicFile atomic = null;
        boolean finishStarted = false;
        try {
            Paths paths = paths(true);
            atomic = atomicFiles.create(paths.base);
            output = atomic.startWrite();
            output.write(bytes);
            // AOSP finishWrite can only LOG its sync/close/rename failures. This explicit
            // throwing sync and bounded exact readback are both required for COMMITTED.
            output.getFD().sync();
            finishStarted = true;
            atomic.finishWrite(output); output = null;
            Read after = read();
            if (!after.usable() || after.result.kind != Kind.LOADED || after.result.state.revision != next.revision
                    || !Arrays.equals(bytes, after.bytes)) return result(Kind.UNCERTAIN, null);
            return result(Kind.COMMITTED, after.result.state);
        } catch (IOException | RuntimeException failure) {
            if (!finishStarted && output != null && atomic != null) {
                try { atomic.failWrite(output); } catch (RuntimeException ignored) { }
                output = null;
            }
            return result(Kind.UNCERTAIN, null);
        } finally {
            if (output != null) try { output.close(); } catch (IOException ignored) { }
        }
    }

    private static final class Paths {
        final File base, backup, next;
        Paths(File base) { this.base = base; backup = new File(base + ".bak"); next = new File(base + ".new"); }
    }
    private Paths paths(boolean create) throws IOException {
        File files = application.getFilesDir();
        if (files == null) throw new IOException("Private directory unavailable");
        files = files.getCanonicalFile();
        File directory = new File(files, "bchat-room-preferences");
        if (!directory.getAbsoluteFile().equals(directory.getCanonicalFile())) throw new IOException("Unsafe private directory");
        BasicFileAttributes attributes = attributes(directory);
        if (attributes == null && create) {
            if (!directory.mkdir()) throw new IOException("Private directory unavailable");
            attributes = attributes(directory);
        }
        if (attributes != null && (!attributes.isDirectory() || attributes.isSymbolicLink())) throw new IOException("Unsafe private directory");
        Paths paths = new Paths(new File(directory, account.key + ".json"));
        for (File file : new File[]{paths.base, paths.backup, paths.next}) {
            BasicFileAttributes existing = attributes(file);
            if (existing != null && (!existing.isRegularFile() || existing.isSymbolicLink())) throw new IOException("Unsafe private metadata path");
        }
        return paths;
    }
    private static BasicFileAttributes attributes(File file) throws IOException {
        try { return Files.readAttributes(file.toPath(), BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); }
        catch (NoSuchFileException missing) { return null; }
    }
    private static final class Read {
        final Result result;
        final byte[] bytes;
        Read(Result result, byte[] bytes) { this.result = result; this.bytes = bytes; }
        boolean usable() { return result.kind == Kind.LOADED || result.kind == Kind.ABSENT; }
    }
    private static final class InvalidFile extends Exception {
        final Kind kind;
        InvalidFile(Kind kind) { this.kind = kind; }
    }

    private Read read() {
        try {
            Paths paths = paths(false);
            boolean base = attributes(paths.base) != null, backup = attributes(paths.backup) != null,
                    next = attributes(paths.next) != null;
            if (!base && !backup && !next)
                return new Read(result(Kind.ABSENT, new State(0, Collections.emptyList(), Collections.emptyList())), null);
            if (!base && !backup) return new Read(result(Kind.CORRUPT, null), null); // Preserve an orphan .new.
            // Validate the authoritative candidate BEFORE platform backup recovery can
            // rename it over the base. A corrupt backup never destroys a useful base.
            byte[] candidate;
            try (FileInputStream stream = new FileInputStream(backup ? paths.backup : paths.base)) { candidate = bounded(stream); }
            decode(candidate);
            byte[] recovered;
            try (FileInputStream stream = atomicFiles.create(paths.base).openRead()) { recovered = bounded(stream); }
            State state = decode(recovered);
            if (!Arrays.equals(candidate, recovered)) return new Read(result(Kind.IO_FAILURE, null), null);
            return new Read(result(Kind.LOADED, state), recovered);
        } catch (InvalidFile invalid) { return new Read(result(invalid.kind, null), null); }
        catch (IOException | RuntimeException failure) { return new Read(result(Kind.IO_FAILURE, null), null); }
    }

    private static byte[] bounded(FileInputStream stream) throws IOException, InvalidFile {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        byte[] block = new byte[4096]; int count;
        while ((count = stream.read(block, 0, Math.min(block.length, MAX_BYTES + 1 - buffer.size()))) != -1) {
            if (count == 0) throw new IOException("Metadata stream did not progress");
            buffer.write(block, 0, count);
            if (buffer.size() > MAX_BYTES) throw new InvalidFile(Kind.TOO_LARGE);
        }
        if (buffer.size() == 0) throw new InvalidFile(Kind.CORRUPT);
        return buffer.toByteArray();
    }

    private State decode(byte[] bytes) throws InvalidFile {
        try {
            String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
            JSONObject envelope = new JSONObject(text); exactKeys(envelope, ENVELOPE_KEYS);
            long version = integer(envelope.opt("format_version"), false);
            if (version != 1) throw new InvalidFile(Kind.UNSUPPORTED);
            valid(account.key.equals(envelope.opt("scope_key")));
            long revision = integer(envelope.opt("store_revision"), true);
            Object rawSnapshots = envelope.opt("snapshots"), rawPending = envelope.opt("pending");
            valid(rawSnapshots instanceof JSONArray && rawPending instanceof JSONArray);
            JSONArray snapshotsArray = (JSONArray) rawSnapshots, pendingArray = (JSONArray) rawPending;
            valid(snapshotsArray.length() <= MAX_SNAPSHOTS && pendingArray.length() <= MAX_PENDING);
            List<RoomPreferencesProtocol.Snapshot> snapshots = new ArrayList<>();
            Set<Long> rooms = new HashSet<>(); long previousRoom = 0;
            for (int index = 0; index < snapshotsArray.length(); ++index) {
                valid(snapshotsArray.opt(index) instanceof JSONObject);
                JSONObject item = (JSONObject) snapshotsArray.opt(index); exactKeys(item, SNAPSHOT_KEYS);
                long room = recordId(item.opt("room_id")), member = recordId(item.opt("membership_id"));
                valid(rooms.add(room) && room > previousRoom); previousRoom = room;
                snapshots.add(RoomPreferencesProtocol.storedSnapshot(item, account, room, member));
            }
            List<Operation> pending = new ArrayList<>();
            Set<String> bindings = new HashSet<>(), uuids = new HashSet<>();
            long previousPendingRoom = 0, previousMember = 0;
            for (int index = 0; index < pendingArray.length(); ++index) {
                valid(pendingArray.opt(index) instanceof JSONObject);
                JSONObject item = (JSONObject) pendingArray.opt(index); exactKeys(item, OPERATION_KEYS);
                long room = recordId(item.opt("room_id"));
                Object raw = item.opt("payload"), started = item.opt("dispatch_started"), code = item.opt("blocked_code");
                valid(raw instanceof String && ((String) raw).getBytes(StandardCharsets.UTF_8).length <= RoomPreferencesProtocol.MAX_PAYLOAD_BYTES
                        && started instanceof Boolean && code instanceof String && (((String) code).isEmpty() || BLOCK_CODES.contains(code)));
                RoomPreferencesProtocol.Pending operation = RoomPreferencesProtocol.restorePending(new JSONObject((String) raw), account, room);
                valid(operation.payload.equals(raw) && bindings.add(room + ":" + operation.membershipId) && uuids.add(operation.clientUuid)
                        && (room > previousPendingRoom || room == previousPendingRoom && operation.membershipId > previousMember));
                previousPendingRoom = room; previousMember = operation.membershipId;
                pending.add(new Operation(operation, (Boolean) started, (String) code));
            }
            State state = new State(revision, snapshots, pending);
            valid(Arrays.equals(bytes, encode(state))); // Strict canonical bytes; no duplicate keys/trailing text/coercion.
            return state;
        } catch (CharacterCodingException | JSONException | IllegalArgumentException invalid) {
            throw new InvalidFile(Kind.CORRUPT);
        }
    }

    private byte[] encode(State state) { return encodeScoped(state, account.key); }
    private static byte[] encodeScoped(State state, String scope) {
        StringBuilder json = new StringBuilder("{\"format_version\":1,\"scope_key\":").append(JSONObject.quote(scope))
                .append(",\"store_revision\":").append(state.revision).append(",\"snapshots\":[");
        for (int index = 0; index < state.snapshots.size(); ++index) {
            if (index > 0) json.append(','); json.append(snapshotJson(state.snapshots.get(index)));
        }
        json.append("],\"pending\":[");
        for (int index = 0; index < state.pending.size(); ++index) {
            if (index > 0) json.append(',');
            Operation item = state.pending.get(index);
            json.append("{\"room_id\":").append(item.pending.roomId).append(",\"payload\":")
                    .append(JSONObject.quote(item.pending.payload)).append(",\"dispatch_started\":")
                    .append(item.dispatchStarted).append(",\"blocked_code\":").append(JSONObject.quote(item.blockedCode)).append('}');
        }
        return json.append("]}").toString().getBytes(StandardCharsets.UTF_8);
    }
    private static String snapshotJson(RoomPreferencesProtocol.Snapshot item) {
        return "{\"api_version\":2,\"room_id\":" + item.roomId + ",\"membership_id\":" + item.membershipId
                + ",\"revision\":" + item.revision + ",\"muted_until\":" + quoteNull(item.mutedUntil)
                + ",\"mute_forever\":" + item.muteForever + ",\"muted\":" + item.muted + ",\"pinned\":" + item.pinned
                + ",\"pinned_at\":" + quoteNull(item.pinnedAt) + ",\"archived\":" + item.archived + "}";
    }
    private RoomPreferencesProtocol.Snapshot cached(RoomPreferencesProtocol.Snapshot item) throws JSONException {
        return RoomPreferencesProtocol.storedSnapshot(new JSONObject(snapshotJson(item)), account, item.roomId, item.membershipId);
    }
    private static String quoteNull(String value) { return value == null ? "null" : JSONObject.quote(value); }
    private static Set<String> keys(String... values) { return new HashSet<>(Arrays.asList(values)); }
    private static void exactKeys(JSONObject object, Set<String> keys) throws InvalidFile {
        valid(object.length() == keys.size()); Iterator<String> names = object.keys();
        while (names.hasNext()) valid(keys.contains(names.next()));
    }
    private static long integer(Object value, boolean positive) throws InvalidFile {
        valid((value instanceof Integer || value instanceof Long) && ((Number) value).longValue() >= (positive ? 1 : 0));
        return ((Number) value).longValue();
    }
    private static long recordId(Object value) throws InvalidFile {
        long number = integer(value, true); valid(number <= Integer.MAX_VALUE); return number;
    }
    private static void valid(boolean condition) throws InvalidFile { if (!condition) throw new InvalidFile(Kind.CORRUPT); }
    private static Result result(Kind kind, State state) { return new Result(kind, state); }
    private static void worker() {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Room preferences disk access requires a worker");
    }
}

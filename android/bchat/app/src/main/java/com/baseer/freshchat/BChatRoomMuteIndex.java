package com.baseer.freshchat;

import android.content.Context;
import android.os.Looper;
import android.util.AtomicFile;
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
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Private cold mute-floor metadata, never authentication, server preferences or message data.
 * Worker-only, process-wide serialization. No constructor disk lookup, eviction, expiry,
 * account scanning, repair/reset, notifications, network or callback under the file lock.
 * Separate from RoomPreferencesStore: floor-first/clear-last, not a two-file transaction. */
final class BChatRoomMuteIndex {
    static final int MAX_ENTRIES = 100, MAX_BYTES = 32 * 1024;
    private static final Object FILE_LOCK = new Object();
    private static final String HASH = "[0-9a-f]{64}";
    private static final String UUID = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
    private static final Set<String> KEYS = new HashSet<>(Arrays.asList("format_version", "scope_key", "account_uuid", "revision", "entries"));
    private static final Set<String> ENTRY_KEYS = new HashSet<>(Arrays.asList("room_key", "token"));
    enum Kind { ABSENT, LOADED, COMMITTED, UNCHANGED, NO_MATCH, INVALID, CAPACITY,
        CORRUPT, UNSUPPORTED, ROUTE_MISMATCH, TOO_LARGE, IO_FAILURE, UNCERTAIN, EXHAUSTED, FOREIGN }
    static final class State {
        final long revision;
        final Map<String, String> floors;
        private State(long revision, Map<String, String> floors) {
            this.revision = revision; this.floors = Collections.unmodifiableMap(new TreeMap<>(floors));
        }
        String token(String roomKey) { return floors.get(roomKey); }
    }
    static final class Result {
        final Kind kind;
        final State state;
        private Result(Kind kind, State state) { this.kind = kind; this.state = state; }
        boolean readable() { return kind == Kind.LOADED || kind == Kind.ABSENT; }
    }
    /** Trusted current-room inputs are not proof of authentication or Store freshness. */
    static final class RebindRoom {
        final long company, room, member;
        final boolean requiresFloor;
        private final String candidateFloorToken;
        RebindRoom(long company, long room, long member, boolean requiresFloor) {
            if (!recordId(company) || !recordId(room) || !recordId(member)) throw new IllegalArgumentException("Positive current room IDs required");
            this.company = company; this.room = room; this.member = member; this.requiresFloor = requiresFloor;
            // Construct once outside FILE_LOCK/any caller routing gate. Reuse these
            // exact immutable objects across reorder/retry after an uncertain write.
            candidateFloorToken = requiresFloor ? java.util.UUID.randomUUID().toString() : null;
        }
    }
    static final class SlotEvidence {
        final boolean present;
        final String sha256;
        private SlotEvidence(RawSlot slot) { present = slot.present; sha256 = slot.sha256; }
    }
    static final class ForeignEvidence {
        final String scopeKey, oldAccountUuid, newAccountUuid, bytesSha256, sourceSlot;
        final long revision;
        final Map<String, String> floors;
        final Map<String, SlotEvidence> slots;
        private final BChatRoomMuteIndex owner;
        private final State state;
        private final RawSlots raw;
        private ForeignEvidence(BChatRoomMuteIndex owner, String oldUuid, State state, RawSlots raw) {
            this.owner = owner; scopeKey = owner.scopeKey; newAccountUuid = owner.accountUuid; oldAccountUuid = oldUuid;
            this.state = state; this.raw = raw; revision = state.revision; floors = state.floors;
            sourceSlot = raw.backup.present ? "bak" : "base"; bytesSha256 = raw.source().sha256;
            Map<String, SlotEvidence> captured = new TreeMap<>();
            captured.put("base", new SlotEvidence(raw.base)); captured.put("bak", new SlotEvidence(raw.backup)); captured.put("new", new SlotEvidence(raw.next));
            slots = Collections.unmodifiableMap(captured);
        }
    }
    static final class ForeignResult {
        final Kind kind;
        final ForeignEvidence evidence;
        private ForeignResult(Kind kind, ForeignEvidence evidence) { this.kind = kind; this.evidence = evidence; }
    }
    interface AtomicFiles { AtomicFile create(File base); }
    final String scopeKey, accountUuid;
    private final Context application;
    private final AtomicFiles atomicFiles;

    BChatRoomMuteIndex(Context context, String scopeKey, String accountUuid) {
        this(context, scopeKey, accountUuid, AtomicFile::new);
    }
    BChatRoomMuteIndex(Context context, String scopeKey, String accountUuid, AtomicFiles files) {
        if (context == null || !hash(scopeKey) || !uuid(accountUuid) || files == null)
            throw new IllegalArgumentException("Verified scope/route and application context required");
        Context app = context.getApplicationContext();
        if (app == null) throw new IllegalArgumentException("Application context required");
        application = app; this.scopeKey = scopeKey; this.accountUuid = accountUuid; atomicFiles = files;
    }
    Result load() { worker(); synchronized (FILE_LOCK) { return read().result; } }
    /** No AtomicFile construction/openRead/recovery: all present slots must be complete
     * canonical V1 and share the same foreign route. Partial/orphan .new is not repairable
     * by this primitive; mixed base-current/bak-foreign is rejected without mutation. */
    ForeignResult inspectForeignWorker() {
        worker();
        synchronized (FILE_LOCK) {
            try {
                RawSlots raw = rawSlots();
                if (!raw.any()) return new ForeignResult(Kind.ABSENT, null);
                if (!raw.base.present && !raw.backup.present) return new ForeignResult(Kind.CORRUPT, null);
                String route = null; State selected = null;
                for (RawSlot slot : new RawSlot[]{raw.base, raw.backup, raw.next}) if (slot.present) {
                    String slotRoute = canonicalRoute(slot.bytes); State decoded = decode(slot.bytes, slotRoute);
                    if (route != null && !route.equals(slotRoute)) throw new InvalidFile(Kind.ROUTE_MISMATCH);
                    route = slotRoute; if (slot == raw.source()) selected = decoded;
                }
                if (accountUuid.equals(route)) return new ForeignResult(Kind.NO_MATCH, null);
                return new ForeignResult(Kind.FOREIGN, new ForeignEvidence(this, route, selected, raw));
            } catch (InvalidFile invalid) { return new ForeignResult(invalid.kind, null); }
            catch (IOException | RuntimeException failure) { return new ForeignResult(Kind.IO_FAILURE, null); }
        }
    }
    /** File CAS only. Caller must establish all current GET/Store/binding proofs before
     * this worker call and recheck them before any later RAM/ready publication. */
    Result rebindForeignExact(ForeignEvidence evidence, List<RebindRoom> rooms) {
        worker();
        if (evidence == null || evidence.owner != this || !scopeKey.equals(evidence.scopeKey)
                || !accountUuid.equals(evidence.newAccountUuid) || rooms == null || rooms.size() > MAX_ENTRIES) return result(Kind.INVALID, null);
        final List<RebindRoom> plan;
        try { plan = Collections.unmodifiableList(new ArrayList<>(rooms)); }
        catch (RuntimeException invalid) { return result(Kind.INVALID, null); }
        if (plan.size() > MAX_ENTRIES) return result(Kind.INVALID, null);
        synchronized (FILE_LOCK) {
            try {
                RawSlots current = rawSlots();
                if (!evidence.raw.same(current)) return result(Kind.NO_MATCH, null);
                if (evidence.state.revision == Long.MAX_VALUE) return result(Kind.EXHAUSTED, null);
                Set<Long> roomIds = new HashSet<>(); Set<String> companyMembers = new HashSet<>(), oldKeys = new HashSet<>(), newKeys = new HashSet<>();
                List<String> sources = new ArrayList<>(), destinations = new ArrayList<>();
                for (RebindRoom room : plan) {
                    if (room == null || !recordId(room.company) || !recordId(room.room) || !recordId(room.member)
                            || !roomIds.add(room.room) || !companyMembers.add(room.company + "|" + room.member)
                            || room.requiresFloor && !uuid(room.candidateFloorToken)) return result(Kind.INVALID, null);
                    String oldKey = NotificationPresentation.roomKey(evidence.oldAccountUuid, room.company, room.room, room.member);
                    String newKey = NotificationPresentation.roomKey(accountUuid, room.company, room.room, room.member);
                    if (!oldKeys.add(oldKey) || !newKeys.add(newKey)) return result(Kind.INVALID, null);
                    sources.add(oldKey); destinations.add(newKey);
                }
                // Reject source/destination chains before any remove/insert. With the
                // real SHA256 key these overlaps are not a practical fixture input.
                for (String oldKey : oldKeys) if (newKeys.contains(oldKey)) return result(Kind.INVALID, null);
                Map<String, String> prior = evidence.floors, next = new TreeMap<>(prior);
                for (int index = 0; index < plan.size(); ++index) {
                    RebindRoom room = plan.get(index); String source = sources.get(index), destination = destinations.get(index);
                    String oldToken = prior.get(source), existing = prior.get(destination);
                    if (oldToken != null) {
                        if (existing != null && !oldToken.equals(existing)) return result(Kind.INVALID, null);
                        next.remove(source); next.put(destination, oldToken);
                    } else if (existing == null && room.requiresFloor) next.put(destination, room.candidateFloorToken);
                    // Existing destinations and all unmatched opaque floors remain.
                    // A false GET never removes a floor; this primitive performs no GC.
                }
                if (next.size() > MAX_ENTRIES) return result(Kind.CAPACITY, null);
                Result committed = commit(evidence.state, next);
                return committed.kind == Kind.COMMITTED ? committed : result(committed.kind, null);
            } catch (InvalidFile invalid) { return result(invalid.kind, null); }
            catch (IOException | RuntimeException failure) { return result(Kind.IO_FAILURE, null); }
        }
    }
    Result put(String roomKey, String token) {
        worker();
        if (!hash(roomKey) || !uuid(token)) return result(Kind.INVALID, null);
        synchronized (FILE_LOCK) {
            Read before = read(); if (!before.result.readable()) return before.result;
            State prior = before.result.state;
            if (token.equals(prior.token(roomKey))) return result(Kind.UNCHANGED, prior);
            if (!prior.floors.containsKey(roomKey) && prior.floors.size() >= MAX_ENTRIES) return result(Kind.CAPACITY, prior);
            Map<String, String> next = new TreeMap<>(prior.floors); next.put(roomKey, token);
            return commit(prior, next);
        }
    }
    /** Exact token CAS. Missing/changed is NOT success and never authorizes a RAM clear. */
    Result clear(String roomKey, String expectedToken) {
        worker();
        if (!hash(roomKey) || !uuid(expectedToken)) return result(Kind.INVALID, null);
        synchronized (FILE_LOCK) {
            Read before = read(); if (!before.result.readable()) return before.result;
            State prior = before.result.state;
            if (!expectedToken.equals(prior.token(roomKey))) return result(Kind.NO_MATCH, prior);
            Map<String, String> next = new TreeMap<>(prior.floors); next.remove(roomKey);
            return commit(prior, next);
        }
    }
    private Result commit(State prior, Map<String, String> floors) {
        if (prior.revision == Long.MAX_VALUE) return result(Kind.EXHAUSTED, prior);
        if (floors.size() > MAX_ENTRIES) return result(Kind.CAPACITY, prior);
        State next = new State(prior.revision + 1, floors);
        byte[] bytes = encode(next);
        if (bytes.length > MAX_BYTES) return result(Kind.TOO_LARGE, prior);
        AtomicFile atomic = null; FileOutputStream output = null; boolean finishStarted = false;
        try {
            atomic = atomicFiles.create(paths(true).base);
            output = atomic.startWrite(); output.write(bytes); output.getFD().sync();
            finishStarted = true; atomic.finishWrite(output); output = null;
            Read after = read();
            if (after.result.kind != Kind.LOADED || after.result.state.revision != next.revision
                    || !Arrays.equals(bytes, after.bytes)) return result(Kind.UNCERTAIN, null);
            return result(Kind.COMMITTED, after.result.state);
        } catch (IOException | RuntimeException failure) {
            if (!finishStarted && output != null && atomic != null) {
                try { atomic.failWrite(output); } catch (RuntimeException ignored) { }
                output = null;
            }
            return result(Kind.UNCERTAIN, null);
        } finally { if (output != null) try { output.close(); } catch (IOException ignored) { } }
    }
    private static final class Paths {
        final File base, backup, next;
        Paths(File base) { this.base = base; backup = new File(base + ".bak"); next = new File(base + ".new"); }
    }
    private static final class RawSlot {
        final boolean present;
        final String sha256;
        private final byte[] bytes;
        RawSlot(byte[] bytes) { present = bytes != null; this.bytes = bytes == null ? null : bytes.clone(); sha256 = bytes == null ? null : sha256(bytes); }
        boolean same(RawSlot other) { return present == other.present && java.util.Objects.equals(sha256, other.sha256) && Arrays.equals(bytes, other.bytes); }
    }
    private static final class RawSlots {
        final RawSlot base, backup, next;
        RawSlots(RawSlot base, RawSlot backup, RawSlot next) { this.base = base; this.backup = backup; this.next = next; }
        boolean any() { return base.present || backup.present || next.present; }
        RawSlot source() { return backup.present ? backup : base; }
        boolean same(RawSlots other) { return base.same(other.base) && backup.same(other.backup) && next.same(other.next); }
    }
    private RawSlots rawSlots() throws IOException, InvalidFile {
        Paths paths = paths(false);
        return new RawSlots(rawSlot(paths.base), rawSlot(paths.backup), rawSlot(paths.next));
    }
    private static RawSlot rawSlot(File file) throws IOException, InvalidFile {
        if (attributes(file) == null) return new RawSlot(null);
        try (FileInputStream stream = new FileInputStream(file)) { return new RawSlot(bounded(stream)); }
    }
    private static String sha256(byte[] bytes) {
        try {
            StringBuilder value = new StringBuilder();
            for (byte part : MessageDigest.getInstance("SHA-256").digest(bytes)) value.append("0123456789abcdef".charAt((part & 255) >>> 4)).append("0123456789abcdef".charAt(part & 15));
            return value.toString();
        } catch (NoSuchAlgorithmException unavailable) { throw new IllegalStateException("SHA256 unavailable", unavailable); }
    }
    private Paths paths(boolean create) throws IOException {
        File files = application.getFilesDir();
        if (files == null) throw new IOException("Private directory unavailable");
        files = files.getCanonicalFile(); File directory = new File(files, "bchat-room-mute-index");
        if (!directory.getAbsoluteFile().equals(directory.getCanonicalFile())) throw new IOException("Unsafe private directory");
        BasicFileAttributes item = attributes(directory);
        if (item == null && create) {
            if (!directory.mkdir()) throw new IOException("Private directory unavailable");
            item = attributes(directory);
        }
        if (item != null && (!item.isDirectory() || item.isSymbolicLink())) throw new IOException("Unsafe private directory");
        Paths paths = new Paths(new File(directory, scopeKey + ".json"));
        for (File file : new File[]{paths.base, paths.backup, paths.next}) {
            BasicFileAttributes existing = attributes(file);
            if (existing != null && (!existing.isRegularFile() || existing.isSymbolicLink())) throw new IOException("Unsafe metadata path");
        }
        return paths;
    }
    private static BasicFileAttributes attributes(File file) throws IOException {
        try { return Files.readAttributes(file.toPath(), BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); }
        catch (NoSuchFileException absent) { return null; }
    }
    private static final class Read {
        final Result result; final byte[] bytes;
        Read(Result result, byte[] bytes) { this.result = result; this.bytes = bytes; }
    }
    private static final class InvalidFile extends Exception {
        final Kind kind;
        InvalidFile(Kind kind) { this.kind = kind; }
    }
    private Read read() {
        try {
            Paths paths = paths(false);
            boolean base = attributes(paths.base) != null, backup = attributes(paths.backup) != null, next = attributes(paths.next) != null;
            if (!base && !backup && !next) return new Read(result(Kind.ABSENT, new State(0, Collections.emptyMap())), null);
            if (!base && !backup) return new Read(result(Kind.CORRUPT, null), null);
            if (base && backup) {
                // A late instance A must not recover bak-A over a complete base-B.
                // Preserve ordinary backup recovery for a corrupt/unsupported base;
                // only a fully canonical V1 of this scope can fence the old route.
                String baseRoute = null;
                try (FileInputStream stream = new FileInputStream(paths.base)) {
                    try { baseRoute = canonicalRoute(bounded(stream)); }
                    catch (InvalidFile notCanonical) { /* Existing backup recovery. */ }
                }
                if (baseRoute != null && !accountUuid.equals(baseRoute)) return new Read(result(Kind.ROUTE_MISMATCH, null), null);
            }
            byte[] candidate;
            // A corrupt/route-mismatched backup is rejected BEFORE AtomicFile can overwrite base.
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
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] block = new byte[4096]; int read;
        while ((read = stream.read(block, 0, Math.min(block.length, MAX_BYTES + 1 - bytes.size()))) != -1) {
            if (read == 0) throw new IOException("Metadata stream stalled");
            bytes.write(block, 0, read); if (bytes.size() > MAX_BYTES) throw new InvalidFile(Kind.TOO_LARGE);
        }
        if (bytes.size() == 0) throw new InvalidFile(Kind.CORRUPT);
        return bytes.toByteArray();
    }
    private static JSONObject json(byte[] bytes) throws CharacterCodingException, JSONException {
        return new JSONObject(StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString());
    }
    private State decode(byte[] bytes) throws InvalidFile { return decode(bytes, accountUuid); }
    private String canonicalRoute(byte[] bytes) throws InvalidFile {
        try {
            JSONObject object = json(bytes); keys(object, KEYS);
            if (integer(object.opt("format_version"), false) != 1) throw new InvalidFile(Kind.UNSUPPORTED);
            if (!scopeKey.equals(object.opt("scope_key"))) throw new InvalidFile(Kind.ROUTE_MISMATCH);
            Object candidate = object.opt("account_uuid"); valid(candidate instanceof String && uuid((String) candidate));
            String route = (String) candidate; decode(bytes, route); return route;
        } catch (CharacterCodingException | JSONException | IllegalArgumentException invalid) { throw new InvalidFile(Kind.CORRUPT); }
    }
    private State decode(byte[] bytes, String expectedUuid) throws InvalidFile {
        try {
            JSONObject object = json(bytes); keys(object, KEYS);
            if (integer(object.opt("format_version"), false) != 1) throw new InvalidFile(Kind.UNSUPPORTED);
            if (!scopeKey.equals(object.opt("scope_key")) || !expectedUuid.equals(object.opt("account_uuid")))
                throw new InvalidFile(Kind.ROUTE_MISMATCH);
            long revision = integer(object.opt("revision"), true);
            Object raw = object.opt("entries"); valid(raw instanceof JSONArray);
            JSONArray array = (JSONArray) raw; valid(array.length() <= MAX_ENTRIES);
            Map<String, String> floors = new TreeMap<>(); String previous = "";
            for (int index = 0; index < array.length(); index++) {
                Object item = array.opt(index); valid(item instanceof JSONObject);
                JSONObject entry = (JSONObject) item; keys(entry, ENTRY_KEYS);
                Object room = entry.opt("room_key"), token = entry.opt("token");
                valid(room instanceof String && token instanceof String && hash((String) room) && uuid((String) token));
                valid(((String) room).compareTo(previous) > 0); previous = (String) room;
                floors.put((String) room, (String) token);
            }
            State state = new State(revision, floors); valid(Arrays.equals(bytes, encode(state, expectedUuid))); return state;
        } catch (CharacterCodingException | JSONException | IllegalArgumentException invalid) { throw new InvalidFile(Kind.CORRUPT); }
    }
    private byte[] encode(State state) { return encode(state, accountUuid); }
    private byte[] encode(State state, String uuid) {
        StringBuilder json = new StringBuilder("{\"format_version\":1,\"scope_key\":\"").append(scopeKey)
                .append("\",\"account_uuid\":\"").append(uuid).append("\",\"revision\":").append(state.revision).append(",\"entries\":[");
        boolean first = true;
        for (Map.Entry<String, String> entry : state.floors.entrySet()) {
            if (!first) json.append(','); first = false;
            json.append("{\"room_key\":\"").append(entry.getKey()).append("\",\"token\":\"").append(entry.getValue()).append("\"}");
        }
        return json.append("]}").toString().getBytes(StandardCharsets.UTF_8);
    }
    private static void keys(JSONObject object, Set<String> allowed) throws InvalidFile {
        valid(object.length() == allowed.size()); Iterator<String> keys = object.keys();
        while (keys.hasNext()) valid(allowed.contains(keys.next()));
    }
    private static long integer(Object value, boolean positive) throws InvalidFile {
        valid((value instanceof Integer || value instanceof Long) && ((Number) value).longValue() >= (positive ? 1 : 0));
        return ((Number) value).longValue();
    }
    static boolean hash(String value) { return value != null && value.matches(HASH); }
    static boolean uuid(String value) { return value != null && value.matches(UUID); }
    private static boolean recordId(long value) { return value > 0 && value <= Integer.MAX_VALUE; }
    private static void valid(boolean value) throws InvalidFile { if (!value) throw new InvalidFile(Kind.CORRUPT); }
    private static Result result(Kind kind, State state) { return new Result(kind, state); }
    private static void worker() { if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Index requires worker"); }
}

package com.baseer.freshchat;

import com.baseer.freshchat.sync.AccountScope;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import org.json.JSONObject;

/** Same production value boundary with either declared JVM adapters or Android's real JSON. */
final class RoomPreferencesCases {
    static final AccountScope ACCOUNT = new AccountScope("https://c17.invalid", "synthetic_c17", 7);
    static final String UUID = "00000000-0000-4000-8000-000000000017";
    static final String UNTIL = "2036-02-29T23:59:59Z", PAST = "2000-01-01T00:00:00Z";
    static final long ROOM = 11, MEMBER = 23;
    private static int checks;
    private interface Action { void run() throws Exception; }
    static void check(boolean value, String why) { ++checks; if (!value) throw new AssertionError("C17 check " + checks + ": " + why); }
    static void rejected(Action action, String why) throws Exception {
        try { action.run(); } catch (IllegalArgumentException expected) { ++checks; return; }
        throw new AssertionError("C17 accepted invalid " + why);
    }
    static JSONObject response(long revision, String until, boolean forever, boolean muted,
            boolean pinned, boolean archived) throws Exception {
        return new JSONObject().put("api_version", 2).put("room_id", ROOM).put("membership_id", MEMBER)
                .put("revision", revision).put("muted_until", until == null ? JSONObject.NULL : until)
                .put("mute_forever", forever).put("muted", muted).put("pinned", pinned)
                .put("pinned_at", pinned ? "2026-10-18T12:34:56Z" : JSONObject.NULL).put("archived", archived);
    }
    private static JSONObject defaults() throws Exception { return response(1, null, false, false, false, false); }
    static RoomPreferencesProtocol.Snapshot fresh(JSONObject object) {
        return RoomPreferencesProtocol.freshSnapshot(object, ACCOUNT, ROOM, MEMBER);
    }
    static RoomPreferencesProtocol.Pending pending() throws Exception {
        return RoomPreferencesProtocol.newPending(fresh(defaults()), UUID, null, false, true, true);
    }
    static JSONObject ack(RoomPreferencesProtocol.Pending pending, long revision, boolean replayed) throws Exception {
        return response(revision, pending.mutedUntil, pending.muteForever,
                pending.muteForever || pending.mutedUntil != null, pending.pinned, pending.archived)
                .put("client_uuid", pending.clientUuid).put("operation_revision", pending.expectedRevision + 1)
                .put("replayed", replayed);
    }

    static int run() throws Exception {
        checks = 0;
        advertisement(); snapshots(); operations(); acknowledgements(); monotone(); immutable();
        return checks;
    }

    private static void advertisement() throws Exception {
        check(!RoomPreferencesProtocol.supported(null), "Missing bootstrap unsupported");
        JSONObject body = new JSONObject().put("api_version", 2);
        check(!RoomPreferencesProtocol.supported(body), "Missing optional version unsupported");
        for (Object valid : new Object[]{1, 1L})
            check(RoomPreferencesProtocol.supported(body.put("room_preferences_contract_version", valid)), "Native integer feature one");
        for (Object invalid : new Object[]{JSONObject.NULL, true, "1", 1.0, 1f, (short) 1, BigInteger.ONE, 0, -1, 2, Long.MAX_VALUE})
            check(!RoomPreferencesProtocol.supported(body.put("room_preferences_contract_version", invalid)), "Safe unsupported version type/value");
        body.put("room_preferences_contract_version", 1);
        for (Object invalid : new Object[]{JSONObject.NULL, true, "2", 2.0, 1, 3})
            check(!RoomPreferencesProtocol.supported(body.put("api_version", invalid)), "Invalid bootstrap does not enable feature");
        check(!RoomPreferencesProtocol.supported(body.put("api_version", 2).put("error", JSONObject.NULL)), "Error envelope unsupported");
    }

    private static void snapshots() throws Exception {
        RoomPreferencesProtocol.Snapshot value = fresh(defaults());
        check(value.account == ACCOUNT && value.roomId == ROOM && value.membershipId == MEMBER && value.revision == 1, "External trusted association retained");
        check(value.freshGet && !value.muted && !value.muteForever && value.mutedUntil == null && !value.pinned && value.pinnedAt == null && !value.archived, "Default complete shape");
        check(!RoomPreferencesProtocol.storedSnapshot(defaults(), ACCOUNT, ROOM, MEMBER).freshGet, "Disk metadata never fresh");
        check(fresh(response(3, PAST, false, false, false, true)).mutedUntil.equals(PAST), "Server-expired non-null until allowed");
        check(fresh(response(3, PAST, false, true, false, true)).muted, "No device-clock expiry judgment");
        check(!fresh(response(3, UNTIL, false, false, false, false)).muted, "Server false is authoritative even beyond device date");
        check(fresh(response(Integer.MAX_VALUE, null, true, true, true, true)).revision == Integer.MAX_VALUE, "Read max revision without overflow");
        JSONObject additive = defaults().put("future_addition", new JSONObject().put("any", "ignored safely"));
        check(fresh(additive).revision == 1, "Unknown response additions ignored/not retained");
        rejected(() -> fresh(response(1, UNTIL, true, true, false, false)), "Forever with timed expiry");
        rejected(() -> fresh(response(1, null, true, false, false, false)), "Forever falsely unmuted");
        rejected(() -> fresh(response(1, null, false, true, false, false)), "Muted without any duration");
        rejected(() -> fresh(defaults().put("pinned_at", UNTIL)), "Unpinned with server timestamp");
        rejected(() -> fresh(response(1, null, false, false, true, false).put("pinned_at", JSONObject.NULL)), "Pinned without server timestamp");
        for (String key : new String[]{"api_version", "room_id", "membership_id", "revision", "muted_until", "mute_forever", "muted", "pinned", "pinned_at", "archived"}) {
            JSONObject absent = defaults(); absent.remove(key);
            rejected(() -> fresh(absent), "Missing required " + key);
        }
        for (String key : new String[]{"mute_forever", "muted", "pinned", "archived"})
            for (Object bad : new Object[]{JSONObject.NULL, 0, 1, 1L, "true", "false", new JSONObject()})
                rejected(() -> fresh(defaults().put(key, bad)), "Boolean coercion " + key);
        for (String key : new String[]{"room_id", "membership_id", "revision"}) {
            for (Object bad : new Object[]{JSONObject.NULL, true, "1", 1.0, 1f, (short) 1, BigInteger.ONE,
                    BigDecimal.ONE, 0, -1, (long) Integer.MAX_VALUE + 1, Long.MAX_VALUE})
                rejected(() -> fresh(defaults().put(key, bad)), "Native positive int32 " + key);
        }
        for (Object bad : new Object[]{JSONObject.NULL, true, "2", 2.0, 1, 3})
            rejected(() -> fresh(defaults().put("api_version", bad)), "Exact api two");
        rejected(() -> fresh(defaults().put("room_id", ROOM + 1)), "Wrong room echo");
        rejected(() -> fresh(defaults().put("membership_id", MEMBER + 1)), "Wrong epoch echo");
        rejected(() -> fresh(defaults().put("error", new JSONObject())), "Error envelope");
        rejected(() -> RoomPreferencesProtocol.freshSnapshot(defaults(), null, ROOM, MEMBER), "Missing external account");
        rejected(() -> RoomPreferencesProtocol.freshSnapshot(defaults(), ACCOUNT, 0, MEMBER), "Invalid expected room");
        rejected(() -> RoomPreferencesProtocol.freshSnapshot(defaults(), ACCOUNT, ROOM, 0), "Invalid expected member");
        String[] invalidDates = {"", "2026-02-29T12:00:00Z", "1900-02-29T00:00:00Z", "0000-01-01T00:00:00Z",
                "2026-13-01T00:00:00Z", "2026-00-01T00:00:00Z", "2026-01-00T00:00:00Z", "2026-04-31T00:00:00Z",
                "2026-01-01T24:00:00Z", "2026-01-01T00:60:00Z", "2026-01-01T00:00:60Z", "2026-01-01 00:00:00Z",
                "2026-01-01T00:00:00z", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00.000Z",
                "2026-1-01T00:00:00Z", "２０２６-01-01T00:00:00Z", "2026-01-01T00:00:00Z\n"};
        for (String invalid : invalidDates) {
            rejected(() -> fresh(response(1, invalid, false, false, false, false)), "Strict UTC20 until");
            rejected(() -> fresh(response(1, null, false, false, true, false).put("pinned_at", invalid)), "Strict UTC20 pin");
        }
        for (Object invalid : new Object[]{true, 42, 42L, new JSONObject()}) {
            rejected(() -> fresh(defaults().put("muted_until", invalid)), "Timestamp native type");
            rejected(() -> fresh(defaults().put("pinned_at", invalid)), "Pin timestamp native type");
        }
        for (String valid : new String[]{"0001-01-01T00:00:00Z", "2000-02-29T23:59:59Z", UNTIL, "9999-12-31T23:59:59Z"})
            check(fresh(response(1, valid, false, true, false, false)).mutedUntil.equals(valid), "Gregorian canonical UTC accepted");
        JSONObject mutable = defaults(); RoomPreferencesProtocol.Snapshot before = fresh(mutable);
        mutable.put("revision", 99).put("archived", true);
        check(before.revision == 1 && !before.archived, "No mutable response alias");
    }

    private static void operations() throws Exception {
        RoomPreferencesProtocol.Pending pending = pending();
        check(pending.account == ACCOUNT && pending.roomId == ROOM && pending.membershipId == MEMBER
                && pending.expectedRevision == 1 && pending.clientUuid.equals(UUID), "Exact identity and CAS baseline");
        String canonical = "{\"api_version\":2,\"membership_id\":23,\"client_uuid\":\"" + UUID
                + "\",\"expected_revision\":1,\"muted_until\":null,\"mute_forever\":false,\"pinned\":true,\"archived\":true}";
        check(pending.payload.equals(canonical), "Exact canonical eight-field wire bytes");
        JSONObject object = pending.payloadObject();
        Set<String> keys = new HashSet<>(); Iterator<String> iterator = object.keys();
        while (iterator.hasNext()) keys.add(iterator.next());
        check(keys.equals(new HashSet<>(Arrays.asList("api_version", "membership_id", "client_uuid", "expected_revision",
                "muted_until", "mute_forever", "pinned", "archived"))), "No room/account/secret field added to payload");
        check(object.opt("muted_until") == JSONObject.NULL && object.opt("mute_forever") instanceof Boolean
                && object.opt("pinned") instanceof Boolean && object.opt("archived") instanceof Boolean, "Real null and booleans");
        object.put("pinned", false).put("client_uuid", "changed");
        check(pending.pinned && pending.payload.equals(canonical) && pending.payloadObject().opt("pinned").equals(true), "Payload copy cannot mutate pending");
        check(RoomPreferencesProtocol.restorePending(pending.payloadObject(), ACCOUNT, ROOM).payload.equals(canonical), "Stable operation restore/retry bytes");
        RoomPreferencesProtocol.Snapshot expired = fresh(response(8, PAST, false, false, false, false));
        check(RoomPreferencesProtocol.newPending(expired, UUID, expired.mutedUntil, false, true, false).mutedUntil == null, "Only new intent drops server-confirmed inherited expiry");
        check(RoomPreferencesProtocol.newPending(expired, UUID, UNTIL, false, false, false).mutedUntil.equals(UNTIL), "Explicit different expiry not guessed from device clock");
        RoomPreferencesProtocol.Pending timed = RoomPreferencesProtocol.newPending(fresh(response(8, PAST, false, true, false, false)), UUID, PAST, false, true, false);
        check(timed.mutedUntil.equals(PAST), "Server-muted pending expiry never expires locally");
        check(RoomPreferencesProtocol.restorePending(timed.payloadObject(), ACCOUNT, ROOM).payload.equals(timed.payload), "Restore never normalizes an expired pending until");
        check(RoomPreferencesProtocol.newPending(fresh(defaults()), UUID, null, true, false, false).muteForever, "Explicit forever");
        rejected(() -> RoomPreferencesProtocol.newPending(RoomPreferencesProtocol.storedSnapshot(defaults(), ACCOUNT, ROOM, MEMBER), UUID, null, false, false, false), "New intent from disk-only snapshot");
        rejected(() -> RoomPreferencesProtocol.newPending(null, UUID, null, false, false, false), "New intent without GET");
        rejected(() -> RoomPreferencesProtocol.newPending(fresh(response(Integer.MAX_VALUE, null, false, false, false, false)), UUID, null, false, false, false), "Revision exhaustion");
        rejected(() -> RoomPreferencesProtocol.newPending(fresh(defaults()), UUID, UNTIL, true, false, false), "Contradictory new mute");
        for (String bad : new String[]{"", " " + UUID, UUID + "\n", UUID.toUpperCase().replace("000000000017", "00000000001A"),
                "00000000-0000-1000-8000-000000000017", "00000000-0000-4000-7000-000000000017",
                "00000000000040008000000000000017", "00000000-0000-0000-0000-000000000000", "{00000000-0000-4000-8000-000000000017}"})
            rejected(() -> RoomPreferencesProtocol.newPending(fresh(defaults()), bad, null, false, false, false), "Canonical UUIDv4");
        rejected(() -> RoomPreferencesProtocol.newPending(fresh(defaults()), null, null, false, false, false), "Null UUID");
        for (String key : keys) {
            JSONObject missing = pending.payloadObject(); missing.remove(key);
            rejected(() -> RoomPreferencesProtocol.restorePending(missing, ACCOUNT, ROOM), "Missing pending field " + key);
        }
        rejected(() -> RoomPreferencesProtocol.restorePending(pending.payloadObject().put("room_id", ROOM), ACCOUNT, ROOM), "Extra payload field");
        for (String key : new String[]{"membership_id", "expected_revision"})
            for (Object bad : new Object[]{0, -1, "1", 1.0, true, JSONObject.NULL, (short) 1, BigDecimal.ONE,
                    (long) Integer.MAX_VALUE + 1, Long.MAX_VALUE})
                rejected(() -> RoomPreferencesProtocol.restorePending(pending.payloadObject().put(key, bad), ACCOUNT, ROOM), "Pending integer boundary");
        rejected(() -> RoomPreferencesProtocol.restorePending(pending.payloadObject().put("expected_revision", Integer.MAX_VALUE), ACCOUNT, ROOM), "Pending expected revision cannot overflow");
        for (String key : new String[]{"mute_forever", "pinned", "archived"})
            for (Object bad : new Object[]{JSONObject.NULL, 0, 1, "true"})
                rejected(() -> RoomPreferencesProtocol.restorePending(pending.payloadObject().put(key, bad), ACCOUNT, ROOM), "Pending real boolean");
        for (Object bad : new Object[]{true, JSONObject.NULL, 12, "bad"})
            rejected(() -> RoomPreferencesProtocol.restorePending(pending.payloadObject().put("client_uuid", bad), ACCOUNT, ROOM), "Pending UUID type");
        rejected(() -> RoomPreferencesProtocol.restorePending(pending.payloadObject(), null, ROOM), "Restore external account");
        rejected(() -> RoomPreferencesProtocol.restorePending(pending.payloadObject(), ACCOUNT, 0), "Restore external room");
        check(timed.payload.getBytes(StandardCharsets.UTF_8).length <= RoomPreferencesProtocol.MAX_PAYLOAD_BYTES, "Wire byte bound");
    }

    private static void acknowledgements() throws Exception {
        RoomPreferencesProtocol.Pending pending = pending();
        RoomPreferencesProtocol.Acknowledgement accepted = RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, false), pending);
        check(accepted.operationRevision == 2 && !accepted.replayed && accepted.clientUuid.equals(UUID)
                && accepted.snapshot.revision == 2 && !accepted.snapshot.freshGet, "Exact fresh operation receipt, not fresh GET admission");
        check(RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, true), pending).replayed, "Exact replay");
        JSONObject superseded = ack(pending, 8, true).put("pinned", false).put("pinned_at", JSONObject.NULL).put("archived", false);
        RoomPreferencesProtocol.Acknowledgement replay = RoomPreferencesProtocol.acknowledgement(200, superseded, pending);
        check(replay.snapshot.revision == 8 && !replay.snapshot.pinned && !replay.snapshot.archived
                && replay.operationRevision == 2, "Higher current state settles original UUID without replaying old choice");
        for (int status : new int[]{0, 201, 204, 400, 403, 409, 500})
            rejected(() -> RoomPreferencesProtocol.acknowledgement(status, ack(pending, 2, false), pending), "ACK requires HTTP200");
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200, null, pending), "Missing ACK");
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, false), null), "Missing pending association");
        for (String key : new String[]{"room_id", "membership_id"})
            rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, false).put(key, 99), pending), "ACK exact binding");
        for (Object bad : new Object[]{JSONObject.NULL, "bad", true, 17, "00000000-0000-4000-8000-000000000018"})
            rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, false).put("client_uuid", bad), pending), "ACK exact UUID");
        for (String key : new String[]{"operation_revision", "revision"})
            for (Object bad : new Object[]{JSONObject.NULL, "2", true, 2.0, 0, -1, (long) Integer.MAX_VALUE + 1})
                rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, false).put(key, bad), pending), "ACK native revision");
        for (Object bad : new Object[]{JSONObject.NULL, 1, "true"})
            rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, true).put("replayed", bad), pending), "ACK actual replay flag");
        for (String absent : new String[]{"operation_revision", "client_uuid", "replayed"}) {
            JSONObject missing = ack(pending, 2, false); missing.remove(absent);
            rejected(() -> RoomPreferencesProtocol.acknowledgement(200, missing, pending), "Missing ACK receipt field");
        }
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 3, false), pending), "Non-replayed current must equal operation");
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 1, true), pending), "Current cannot precede operation");
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 3, true).put("operation_revision", 3), pending), "Operation must expected plus one");
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, true).put("archived", false), pending), "At operation revision exact archived payload");
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, false).put("pinned", false).put("pinned_at", JSONObject.NULL), pending), "At operation revision exact pinned payload");
        check(RoomPreferencesProtocol.acknowledgement(200, ack(pending, 2, false).put("future_addition", "safe"), pending).snapshot.pinned, "Additive ACK field ignored");
        RoomPreferencesProtocol.Pending max = RoomPreferencesProtocol.newPending(fresh(response(Integer.MAX_VALUE - 1L,
                null, false, false, false, false)), UUID, null, false, false, false);
        check(RoomPreferencesProtocol.acknowledgement(200, ack(max, Integer.MAX_VALUE, false), max).operationRevision == Integer.MAX_VALUE, "Last nonoverflowing operation accepted");
        RoomPreferencesProtocol.Pending timed = RoomPreferencesProtocol.newPending(fresh(defaults()), UUID, UNTIL, false, false, false);
        check(!RoomPreferencesProtocol.acknowledgement(200, ack(timed, 2, true).put("muted", false), timed).snapshot.muted, "Server expiry can change derived bit at original operation revision");
    }

    private static void monotone() throws Exception {
        RoomPreferencesProtocol.Snapshot latest = fresh(response(9, UNTIL, false, true, true, false));
        RoomPreferencesProtocol.Snapshot old = fresh(response(8, null, false, false, false, true));
        check(RoomPreferencesProtocol.mergeSnapshot(latest, old) == latest, "Older GET cannot roll revision back");
        RoomPreferencesProtocol.Acknowledgement oldReceipt = RoomPreferencesProtocol.acknowledgement(200, ack(pending(), 2, false), pending());
        check(RoomPreferencesProtocol.mergeSnapshot(latest, oldReceipt.snapshot) == latest, "Late valid ACK settles operation without rollback");
        check(RoomPreferencesProtocol.mergeSnapshot(null, old) == old, "First incoming object unchanged");
        RoomPreferencesProtocol.Snapshot disk = RoomPreferencesProtocol.storedSnapshot(response(9, UNTIL, false, false, true, false), ACCOUNT, ROOM, MEMBER);
        check(RoomPreferencesProtocol.mergeSnapshot(latest, disk) == latest, "Stored equal revision cannot replace current observation");
        check(!RoomPreferencesProtocol.mergeSnapshot(null, disk).freshGet, "Merge does not manufacture disk freshness");
        RoomPreferencesProtocol.Snapshot expired = fresh(response(9, UNTIL, false, false, true, false));
        check(RoomPreferencesProtocol.mergeSnapshot(latest, expired) == expired, "Current GET's derived server expiry may change without revision");
        check(RoomPreferencesProtocol.mergeSnapshot(old, latest) == latest, "Higher revision wins");
        RoomPreferencesProtocol.Snapshot higherDisk = RoomPreferencesProtocol.storedSnapshot(response(10, UNTIL, false, false, true, false), ACCOUNT, ROOM, MEMBER);
        check(RoomPreferencesProtocol.mergeSnapshot(latest, higherDisk) == higherDisk && !higherDisk.freshGet, "Higher stored revision is not promoted fresh");
        rejected(() -> RoomPreferencesProtocol.mergeSnapshot(latest, fresh(response(9, UNTIL, false, true, true, true))), "Equal revision contradictory metadata");
        rejected(() -> RoomPreferencesProtocol.mergeSnapshot(latest, null), "Missing incoming snapshot");
        for (AccountScope other : new AccountScope[]{new AccountScope("https://other.invalid", ACCOUNT.database, ACCOUNT.userId),
                new AccountScope(ACCOUNT.origin, "other_database", ACCOUNT.userId), new AccountScope(ACCOUNT.origin, ACCOUNT.database, 8)}) {
            RoomPreferencesProtocol.Snapshot foreign = RoomPreferencesProtocol.freshSnapshot(response(10, null, false, false, false, false), other, ROOM, MEMBER);
            rejected(() -> RoomPreferencesProtocol.mergeSnapshot(latest, foreign), "Cross-account merge");
        }
        JSONObject newEpoch = response(10, null, false, false, false, false).put("membership_id", MEMBER + 1);
        RoomPreferencesProtocol.Snapshot rejoined = RoomPreferencesProtocol.freshSnapshot(newEpoch, ACCOUNT, ROOM, MEMBER + 1);
        rejected(() -> RoomPreferencesProtocol.mergeSnapshot(latest, rejoined), "Rejoin cannot inherit snapshot");
        check(RoomPreferencesProtocol.sameBinding(ACCOUNT, ROOM, MEMBER,
                new AccountScope(ACCOUNT.origin, ACCOUNT.database, ACCOUNT.userId), ROOM, MEMBER), "Equivalent trusted account values, not object identity");
        check(!RoomPreferencesProtocol.sameBinding(ACCOUNT, ROOM, MEMBER, ACCOUNT, ROOM + 1, MEMBER), "Room association differs");
    }

    private static void immutable() {
        for (Class<?> model : new Class<?>[]{RoomPreferencesProtocol.Snapshot.class,
                RoomPreferencesProtocol.Pending.class, RoomPreferencesProtocol.Acknowledgement.class}) {
            check(Modifier.isFinal(model.getModifiers()), "Final value class");
            for (Field field : model.getDeclaredFields()) {
                check(Modifier.isFinal(field.getModifiers()), "Final immutable field " + field.getName());
                check(field.getType() != JSONObject.class, "No mutable JSON retained " + field.getName());
            }
            for (Constructor<?> constructor : model.getDeclaredConstructors())
                if (!constructor.isSynthetic()) // javac target8 adds a compiler-only nested access bridge.
                    check(Modifier.isPrivate(constructor.getModifiers()), "No unvalidated source-level value constructor");
        }
    }
    private RoomPreferencesCases() { }
}

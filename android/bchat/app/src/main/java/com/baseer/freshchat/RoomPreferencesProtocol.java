package com.baseer.freshchat;

import com.baseer.freshchat.sync.AccountScope;
import java.nio.charset.StandardCharsets;
import java.time.DateTimeException;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Objects;
import java.util.Set;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * C17 value/response boundary only: no storage, dispatch, clock, authentication or mute effect.
 * AccountScope is supplied by the already verified caller, NOT echoed by these responses.
 * Its local SHA key is never interpreted as a registered account UUID. Membership is echoed
 * and checked, but the caller must still own the current account/epoch/request ticket.
 */
final class RoomPreferencesProtocol {
    static final long MAX_REVISION = Integer.MAX_VALUE;
    static final int MAX_PAYLOAD_BYTES = 8192;
    private static final Set<String> PAYLOAD_KEYS = new HashSet<>(Arrays.asList(
            "api_version", "membership_id", "client_uuid", "expected_revision",
            "muted_until", "mute_forever", "pinned", "archived"));
    private static final Set<String> CANCELLATION_KEYS = new HashSet<>(Arrays.asList(
            "api_version", "room_id", "membership_id", "client_uuid", "expected_revision", "cancelled"));

    static final class Snapshot {
        final AccountScope account;
        final long roomId, membershipId, revision;
        final String mutedUntil, pinnedAt;
        final boolean muteForever, muted, pinned, archived;
        /** Admission hint, not proof of HTTP/authentication or a currently valid GET ticket. */
        final boolean freshGet;

        private Snapshot(AccountScope account, long room, long membership, long revision,
                String until, boolean forever, boolean muted, boolean pinned, String pinnedAt,
                boolean archived, boolean freshGet) {
            this.account = account; roomId = room; membershipId = membership; this.revision = revision;
            mutedUntil = until; muteForever = forever; this.muted = muted; this.pinned = pinned;
            this.pinnedAt = pinnedAt; this.archived = archived; this.freshGet = freshGet;
        }
    }

    static final class Pending {
        final AccountScope account;
        final long roomId, membershipId, expectedRevision;
        final String clientUuid, mutedUntil;
        final boolean muteForever, pinned, archived;
        /** Fixed-order canonical eight-field JSON, immutable across restore/retry. */
        final String payload;

        private Pending(AccountScope account, long room, long membership, long expected,
                String uuid, String until, boolean forever, boolean pinned, boolean archived) {
            require(account != null && validId(room) && validId(membership)
                    && expected > 0 && expected < MAX_REVISION && validUuid(uuid));
            require(until == null || utc20(until));
            require(!forever || until == null);
            this.account = account; roomId = room; membershipId = membership; expectedRevision = expected;
            clientUuid = uuid; mutedUntil = until; muteForever = forever; this.pinned = pinned; this.archived = archived;
            // All interpolated strings are validated canonical ASCII, so no escaping or
            // platform-dependent JSONObject key order can change the retry bytes.
            payload = "{\"api_version\":2,\"membership_id\":" + membership
                    + ",\"client_uuid\":\"" + uuid + "\",\"expected_revision\":" + expected
                    + ",\"muted_until\":" + (until == null ? "null" : "\"" + until + "\"")
                    + ",\"mute_forever\":" + forever + ",\"pinned\":" + pinned + ",\"archived\":" + archived + "}";
            require(payload.getBytes(StandardCharsets.UTF_8).length <= MAX_PAYLOAD_BYTES);
        }

        /** A new mutable copy; mutations never change this pending operation or its bytes. */
        JSONObject payloadObject() {
            try {
                return new JSONObject().put("api_version", 2).put("membership_id", membershipId)
                        .put("client_uuid", clientUuid).put("expected_revision", expectedRevision)
                        .put("muted_until", mutedUntil == null ? JSONObject.NULL : mutedUntil)
                        .put("mute_forever", muteForever).put("pinned", pinned).put("archived", archived);
            } catch (JSONException impossible) { throw new IllegalStateException("Canonical preference payload unavailable", impossible); }
        }
    }

    static final class Acknowledgement {
        final Snapshot snapshot;
        final String clientUuid;
        final long operationRevision;
        final boolean replayed;
        private Acknowledgement(Snapshot snapshot, Pending pending, long operation, boolean replayed) {
            this.snapshot = snapshot; clientUuid = pending.clientUuid;
            operationRevision = operation; this.replayed = replayed;
        }
    }

    /** Typed terminal receipt, not authentication or a new intent. Keep the exact original
     * immutable request: six wire fields alone must not match another same-UUID payload. */
    static final class Cancellation {
        private final Pending request;
        private Cancellation(Pending request) { this.request = request; }
        boolean matches(Pending pending) {
            return pending != null && sameBinding(request.account, request.roomId, request.membershipId,
                    pending.account, pending.roomId, pending.membershipId)
                    && request.clientUuid.equals(pending.clientUuid) && request.expectedRevision == pending.expectedRevision
                    && request.payload.equals(pending.payload);
        }
    }

    /** Optional advertisement only; never enables auth/rights or validates a bootstrap user. */
    static boolean supported(JSONObject bootstrap) {
        return bootstrap != null && !bootstrap.has("error") && integer(bootstrap.opt("api_version"))
                && ((Number) bootstrap.opt("api_version")).longValue() == 2
                && integer(bootstrap.opt("room_preferences_contract_version"))
                && ((Number) bootstrap.opt("room_preferences_contract_version")).longValue() == 1;
    }

    /** Missing/malformed optional support hides cancellation only, never base C17. */
    static boolean cancelSupported(JSONObject bootstrap) {
        return supported(bootstrap) && integer(bootstrap.opt("room_preferences_cancel_contract_version"))
                && ((Number) bootstrap.opt("room_preferences_cancel_contract_version")).longValue() == 1;
    }

    /** Call only for an authenticated, current-ticket GET. No response can prove freshness itself. */
    static Snapshot freshSnapshot(JSONObject body, AccountScope account, long room, long membership) {
        return snapshot(body, account, room, membership, true);
    }

    /** Stored metadata is never made eligible for a new user intent by parsing it. */
    static Snapshot storedSnapshot(JSONObject body, AccountScope account, long room, long membership) {
        return snapshot(body, account, room, membership, false);
    }

    static Pending newPending(Snapshot fresh, String uuid, String until, boolean forever,
            boolean pinned, boolean archived) {
        require(fresh != null && fresh.freshGet && fresh.revision < MAX_REVISION);
        require(until == null || utc20(until));
        require(!forever || until == null);
        // Only a server-confirmed muted=false can discard the inherited timed expiry in
        // a NEW intent (e.g. pin/archive). A different explicitly selected expiry is not
        // guessed to be expired from the device's clock; the server validates its range.
        if (!forever && !fresh.muted && Objects.equals(until, fresh.mutedUntil)) until = null;
        return new Pending(fresh.account, fresh.roomId, fresh.membershipId, fresh.revision,
                uuid, until, forever, pinned, archived);
    }

    /**
     * Decode a previously committed operation only. This is not new-intent admission and
     * does not normalize expiry or refresh expectedRevision. The store/controller must
     * retain/compare the original canonical payload bytes and current trusted binding.
     */
    static Pending restorePending(JSONObject payload, AccountScope account, long room) {
        require(payload != null && payload.length() == PAYLOAD_KEYS.size());
        Iterator<String> keys = payload.keys();
        while (keys.hasNext()) require(PAYLOAD_KEYS.contains(keys.next()));
        api(payload);
        Object uuid = payload.opt("client_uuid");
        require(uuid instanceof String && validUuid((String) uuid));
        return new Pending(account, room, positive(payload.opt("membership_id")),
                positive(payload.opt("expected_revision")), (String) uuid,
                nullableStamp(payload, "muted_until"), flag(payload, "mute_forever"),
                flag(payload, "pinned"), flag(payload, "archived"));
    }

    static Acknowledgement acknowledgement(int status, JSONObject body, Pending pending) {
        require(status == 200 && pending != null && body != null && !body.has("cancelled"));
        Snapshot current = snapshot(body, pending.account, pending.roomId, pending.membershipId, false);
        require(pending.clientUuid.equals(body.opt("client_uuid")));
        long operation = positive(body.opt("operation_revision"));
        boolean replayed = flag(body, "replayed");
        require(operation == pending.expectedRevision + 1 && current.revision >= operation
                && (replayed || current.revision == operation));
        if (current.revision == operation) {
            // At the operation revision the stored preference fields must be this exact
            // operation. The derived muted bit may already reflect server-side expiry.
            require(Objects.equals(current.mutedUntil, pending.mutedUntil)
                    && current.muteForever == pending.muteForever
                    && current.pinned == pending.pinned && current.archived == pending.archived);
        }
        return new Acknowledgement(current, pending, operation, replayed);
    }

    /** Only the original current authenticated POST callback may supply this input.
     * Presence of cancelled is an exclusive discriminant; malformed cancellation must
     * never fall through to the acknowledgement parser, including a late original POST. */
    static Cancellation cancellation(int status, JSONObject body, Pending pending) {
        require(status == 200 && body != null && pending != null && body.length() == CANCELLATION_KEYS.size());
        Iterator<String> fields = body.keys();
        while (fields.hasNext()) require(CANCELLATION_KEYS.contains(fields.next()));
        api(body);
        require(positive(body.opt("room_id")) == pending.roomId && positive(body.opt("membership_id")) == pending.membershipId
                && pending.clientUuid.equals(body.opt("client_uuid")) && positive(body.opt("expected_revision")) == pending.expectedRevision
                && flag(body, "cancelled"));
        return new Cancellation(pending);
    }

    /**
     * Revision-monotone selection, NOT a storage CAS or a request-order/authorization gate.
     * Returns one original immutable object: it never manufactures/promotes freshness.
     * A later current GET may change derived muted without changing metadata revision.
     * Its timing is the controller's responsibility. Stored values cannot replace an
     * equal-revision current observation; contradictory persistent fields are rejected.
     */
    static Snapshot mergeSnapshot(Snapshot stored, Snapshot incoming) {
        require(incoming != null);
        if (stored == null) return incoming;
        require(sameBinding(stored.account, stored.roomId, stored.membershipId,
                incoming.account, incoming.roomId, incoming.membershipId));
        if (incoming.revision < stored.revision) return stored;
        if (incoming.revision == stored.revision) {
            require(sameMetadata(stored, incoming));
            if (!incoming.freshGet) return stored;
        }
        return incoming;
    }

    static boolean sameBinding(AccountScope first, long firstRoom, long firstMembership,
            AccountScope second, long secondRoom, long secondMembership) {
        return first != null && second != null && first.userId == second.userId
                && first.origin.equals(second.origin) && first.database.equals(second.database)
                && firstRoom == secondRoom && firstMembership == secondMembership;
    }

    private static boolean sameMetadata(Snapshot first, Snapshot second) {
        return first.muteForever == second.muteForever && first.pinned == second.pinned
                && first.archived == second.archived && Objects.equals(first.mutedUntil, second.mutedUntil)
                && Objects.equals(first.pinnedAt, second.pinnedAt);
    }

    private static Snapshot snapshot(JSONObject body, AccountScope account, long room, long membership, boolean fresh) {
        require(account != null && validId(room) && validId(membership));
        api(body);
        require(positive(body.opt("room_id")) == room && positive(body.opt("membership_id")) == membership);
        long revision = positive(body.opt("revision"));
        String until = nullableStamp(body, "muted_until"), pinnedAt = nullableStamp(body, "pinned_at");
        boolean forever = flag(body, "mute_forever"), muted = flag(body, "muted"), pinned = flag(body, "pinned");
        require((!forever || until == null && muted)
                && (forever || until != null || !muted)
                && pinned == (pinnedAt != null));
        return new Snapshot(account, room, membership, revision, until, forever, muted,
                pinned, pinnedAt, flag(body, "archived"), fresh);
    }

    private static void api(JSONObject body) {
        require(body != null && !body.has("error") && integer(body.opt("api_version"))
                && ((Number) body.opt("api_version")).longValue() == 2);
    }
    private static boolean flag(JSONObject body, String key) {
        Object value = body.opt(key); require(value instanceof Boolean); return (Boolean) value;
    }
    private static String nullableStamp(JSONObject body, String key) {
        require(body.has(key));
        Object value = body.opt(key);
        if (value == JSONObject.NULL) return null;
        require(value instanceof String && utc20((String) value));
        return (String) value;
    }
    private static boolean integer(Object value) { return value instanceof Integer || value instanceof Long; }
    private static boolean validId(long value) { return value > 0 && value <= Integer.MAX_VALUE; }
    private static long positive(Object value) {
        require(integer(value) && validId(((Number) value).longValue())); return ((Number) value).longValue();
    }
    private static boolean validUuid(String value) {
        return value != null && value.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
    }
    private static boolean utc20(String value) {
        if (value == null || !value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")) return false;
        try {
            int year = Integer.parseInt(value.substring(0, 4));
            if (year < 1) return false;
            LocalDateTime.of(year, Integer.parseInt(value.substring(5, 7)), Integer.parseInt(value.substring(8, 10)),
                    Integer.parseInt(value.substring(11, 13)), Integer.parseInt(value.substring(14, 16)),
                    Integer.parseInt(value.substring(17, 19)));
            return true;
        } catch (DateTimeException | NumberFormatException invalid) { return false; }
    }
    private static void require(boolean valid) {
        if (!valid) throw new IllegalArgumentException("Invalid personal room preferences contract");
    }
    private RoomPreferencesProtocol() { }
}

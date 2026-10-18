package com.baseer.freshchat;

import java.net.URLEncoder;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.time.DateTimeException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** C18/C19 values only. No account/Activity/Room, mutable JSON, storage, HTTP or authority in
 * these DTOs. The Host MUST associate each query/intent with its original authenticated
 * account/session/company/member/rights and current view ticket. IDs/ACKs cannot prove that.
 * Candidate names are transient selection labels, never part of direct/add intent payloads. */
final class GroupPeopleProtocol {
    static final int MAX_ID = Integer.MAX_VALUE, MAX_PEOPLE = 40, MAX_SELECTED = 49,
            MAX_EVENTS = 30, MAX_PAGE_BYTES = 65536, MAX_METADATA_BYTES = 2048, MAX_INTENT_BYTES = 8192;
    private static final String BASE = "/bchat/api/v2";
    enum Mode { DIRECT, CREATE, ADD }

    static boolean supported(JSONObject bootstrap) {
        return bootstrap != null && !bootstrap.has("error") && number(bootstrap.opt("api_version"), 2)
                && number(bootstrap.opt("group_people_contract_version"), 1);
    }

    static final class CandidateQuery {
        final long companyId, selfUserId, afterUserId;
        final String text;
        CandidateQuery(long company, long self, String text, long after) {
            require(id(company) && id(self) && (after == 0 || id(after)) && text != null);
            require(text.codePointCount(0, text.length()) <= 80 && bytes(text) <= 256);
            for (int i = 0; i < text.length(); i++) require(text.charAt(i) >= 32);
            companyId = company; selfUserId = self; this.text = text; afterUserId = after;
        }
        String path() {
            return BASE + "/social/member-candidates?company_id=" + companyId + "&q=" + escaped(text)
                    + (afterUserId == 0 ? "" : "&after_user_id=" + afterUserId);
        }
    }
    static final class Person {
        final long userId;
        final String name;
        private Person(long id, String name) { userId = id; this.name = name; }
    }
    static final class CandidatePage {
        final CandidateQuery query;
        final List<Person> people;
        /** 0 means no next page locally; it is NEVER emitted as a GET cursor. */
        final long nextAfterUserId;
        private CandidatePage(CandidateQuery query, List<Person> people, long next) {
            this.query = query; this.people = immutable(people); nextAfterUserId = next;
        }
        CandidateQuery nextQuery() {
            require(nextAfterUserId != 0);
            return new CandidateQuery(query.companyId, query.selfUserId, query.text, nextAfterUserId);
        }
    }
    static CandidatePage candidates(JSONObject body, CandidateQuery query) {
        require(query != null); response(body);
        List<Person> people = new ArrayList<>(); JSONArray rows = array(body, "users");
        require(rows.length() <= MAX_PEOPLE); long previous = query.afterUserId;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = object(rows.opt(i)); long user = positive(row.opt("user_id"));
            require(user > previous && user != query.selfUserId); previous = user;
            people.add(new Person(user, displayName(row.opt("name"))));
        }
        long next = nullableId(body, "next_after_user_id");
        // Server may filter every processed row after its scan; an empty progressing page
        // is valid. The cursor is NOT necessarily the ID of the last visible person.
        require(next == 0 || next > query.afterUserId && next >= previous);
        return new CandidatePage(query, people, next);
    }

    static final class Selection {
        final Mode mode;
        final long companyId, selfUserId;
        final List<Person> people;
        final List<Long> excludedUserIds;
        private Selection(Mode mode, long company, long self, List<Person> people, List<Long> excluded) {
            this.mode = mode; companyId = company; selfUserId = self;
            this.people = immutable(people); excludedUserIds = immutable(excluded);
        }
        static Selection empty(Mode mode, long company, long self, List<Long> excluded) {
            require(mode != null && id(company) && id(self) && excluded != null && excluded.size() <= 50);
            List<Long> ids = checkedIds(excluded, 50, true);
            return new Selection(mode, company, self, Collections.emptyList(), ids);
        }
        CandidateQuery query(String text, long after) { return new CandidateQuery(companyId, selfUserId, text, after); }
        Selection toggle(CandidatePage page, long userId) {
            require(page != null && page.query.companyId == companyId && page.query.selfUserId == selfUserId
                    && id(userId) && userId != selfUserId && !excludedUserIds.contains(userId));
            Person selected = null;
            for (Person person : page.people) if (person.userId == userId) selected = person;
            require(selected != null);
            for (Person person : people) if (person.userId == userId) return remove(userId);
            List<Person> next = mode == Mode.DIRECT ? new ArrayList<>() : new ArrayList<>(people);
            require(next.size() < (mode == Mode.DIRECT ? 1 : MAX_SELECTED)); next.add(selected);
            return new Selection(mode, companyId, selfUserId, next, excludedUserIds);
        }
        Selection remove(long userId) {
            require(id(userId)); List<Person> next = new ArrayList<>();
            for (Person person : people) if (person.userId != userId) next.add(person);
            return next.size() == people.size() ? this : new Selection(mode, companyId, selfUserId, next, excludedUserIds);
        }
        /** New company/identity/rights means a NEW empty selection, never a label/ID transfer. */
        List<Long> selectedIds() {
            List<Long> ids = new ArrayList<>(); for (Person person : people) ids.add(person.userId);
            Collections.sort(ids); return immutable(ids);
        }
    }

    static final class Intent {
        final Mode mode;
        final long companyId, selfUserId, roomId, membershipId;
        final String clientUuid, payload;
        final List<Long> userIds;
        private Intent(Mode mode, long company, long self, long room, long member, String uuid,
                List<Long> ids, String name, String description) {
            require(mode != null && id(company) && id(self) && uuid(uuid));
            userIds = checkedIds(ids, mode == Mode.DIRECT ? 1 : MAX_SELECTED, false);
            require(!userIds.contains(self) && (mode != Mode.DIRECT || userIds.size() == 1));
            require(mode == Mode.ADD ? id(room) && id(member) : room == 0 && member == 0);
            if (mode == Mode.CREATE) { groupName(name); if (description != null) groupDescription(description); }
            else require(name == null && description == null);
            this.mode = mode; companyId = company; selfUserId = self; roomId = room; membershipId = member; clientUuid = uuid;
            String prefix = "{\"api_version\":2,";
            if (mode == Mode.DIRECT) payload = prefix + "\"company_id\":" + company + ",\"peer_user_id\":" + userIds.get(0)
                    + ",\"client_uuid\":" + JSONObject.quote(uuid) + "}";
            else if (mode == Mode.ADD) payload = prefix + "\"membership_id\":" + member + ",\"client_uuid\":" + JSONObject.quote(uuid)
                    + ",\"user_ids\":" + idsJson(userIds) + "}";
            else payload = prefix + "\"client_uuid\":" + JSONObject.quote(uuid) + ",\"company_id\":" + company
                    + ",\"name\":" + JSONObject.quote(name) + ",\"member_user_ids\":" + idsJson(userIds)
                    + (description == null ? "" : ",\"description\":" + JSONObject.quote(description)) + "}";
            require(bytes(payload) <= MAX_INTENT_BYTES);
        }
        String path() { return mode == Mode.DIRECT ? BASE + "/direct-rooms" : mode == Mode.CREATE ? BASE + "/rooms" : BASE + "/rooms/" + roomId + "/group/members"; }
    }
    static Intent direct(Selection selection, String uuid) {
        require(selection != null && selection.mode == Mode.DIRECT);
        return intent(selection, uuid, 0, 0, null, null);
    }
    static Intent create(Selection selection, String uuid, String name, String description) {
        require(selection != null && selection.mode == Mode.CREATE);
        return intent(selection, uuid, 0, 0, name, description);
    }
    static Intent add(Selection selection, String uuid, long room, long member) {
        require(selection != null && selection.mode == Mode.ADD);
        return intent(selection, uuid, room, member, null, null);
    }
    private static Intent intent(Selection selection, String uuid, long room, long member, String name, String description) {
        return new Intent(selection.mode, selection.companyId, selection.selfUserId, room, member, uuid, selection.selectedIds(), name, description);
    }

    static final class Acknowledgement {
        final Intent intent;
        final long roomId, membershipId;
        final boolean replayed, created;
        final Person peer;
        final List<Long> addedUserIds;
        private Acknowledgement(Intent intent, long room, long member, boolean replayed, boolean created, Person peer, List<Long> added) {
            this.intent = intent; roomId = room; membershipId = member; this.replayed = replayed;
            this.created = created; this.peer = peer; addedUserIds = immutable(added);
        }
    }
    static Acknowledgement acknowledgement(int status, JSONObject body, Intent intent) {
        require(status == 200 && intent != null); response(body);
        long room = positive(body.opt("room_id")); boolean replayed = flag(body, "replayed");
        if (intent.mode == Mode.ADD) {
            require(room == intent.roomId && intent.clientUuid.equals(body.opt("client_uuid")));
            List<Long> added = jsonIds(array(body, "added_user_ids"), MAX_SELECTED, false);
            require(added.equals(intent.userIds)); // Full set equality; a subset is never success.
            return new Acknowledgement(intent, room, intent.membershipId, replayed, false, null, added);
        }
        long member = positive(body.opt("membership_id"));
        if (intent.mode == Mode.CREATE) {
            // Existing create ACK has NO UUID echo. Original request/ticket binding is external.
            return new Acknowledgement(intent, room, member, replayed, false, null, Collections.emptyList());
        }
        require(intent.clientUuid.equals(body.opt("client_uuid")));
        JSONObject peer = object(body.opt("peer")); long peerId = positive(peer.opt("user_id"));
        require(peerId == intent.userIds.get(0));
        return new Acknowledgement(intent, room, member, replayed, flag(body, "created"),
                new Person(peerId, displayName(peer.opt("name"))), Collections.emptyList());
    }

    enum Action { CREATE("create"), ADD_MEMBER("add_member"), ADD_MEMBERS("add_members"), REMOVE_MEMBER("remove_member"),
        LEAVE("leave"), PROMOTE_ADMIN("promote_admin"), DEMOTE_ADMIN("demote_admin"), RENAME("rename"),
        SET_DESCRIPTION("set_description"), AVATAR("avatar"), RECOVER("recover"), INVOICE_POLICY("invoice_policy");
        final String wire;
        Action(String value) { wire = value; }
        static Action parse(Object raw) {
            require(raw instanceof String); for (Action action : values()) if (action.wire.equals(raw)) return action;
            throw invalid();
        }
    }
    static final class EventsQuery {
        final long roomId, membershipId, beforeId;
        EventsQuery(long room, long member, long before) {
            require(id(room) && id(member) && (before == 0 || id(before)));
            roomId = room; membershipId = member; beforeId = before;
        }
        String path() { return BASE + "/rooms/" + roomId + "/group/events?membership_id=" + membershipId
                + (beforeId == 0 ? "" : "&before_id=" + beforeId); }
    }
    static final class Event {
        final long id, actorUserId;
        /** 0 represents a wire null; never an inferred current/administrative membership. */
        final long actorMembershipId, targetUserId;
        final Action action;
        final String createdAt;
        final List<Long> addedUserIds;
        private Event(long id, long actor, long member, long target, Action action, String stamp, List<Long> added) {
            this.id = id; actorUserId = actor; actorMembershipId = member; targetUserId = target;
            this.action = action; createdAt = stamp; addedUserIds = immutable(added);
        }
    }
    static final class EventsPage {
        final EventsQuery query;
        final String auditStartedAt;
        final List<Event> events;
        final long nextBeforeId;
        private EventsPage(EventsQuery query, String started, List<Event> events, long next) {
            this.query = query; auditStartedAt = started; this.events = immutable(events); nextBeforeId = next;
        }
        EventsQuery nextQuery() { require(nextBeforeId != 0); return new EventsQuery(query.roomId, query.membershipId, nextBeforeId); }
    }
    static EventsPage events(JSONObject body, EventsQuery query) {
        require(query != null); response(body);
        require(positive(body.opt("room_id")) == query.roomId && positive(body.opt("membership_id")) == query.membershipId
                && !flag(body, "historical_actions_backfilled"));
        String started = nullableStamp(body, "audit_started_at"); JSONArray rows = array(body, "events");
        require(rows.length() <= MAX_EVENTS); List<Event> events = new ArrayList<>();
        long previous = query.beforeId == 0 ? (long) MAX_ID + 1 : query.beforeId;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = object(rows.opt(i)); long event = positive(row.opt("id")); require(event < previous); previous = event;
            Action action = Action.parse(row.opt("action")); JSONObject metadata = object(row.opt("metadata")); budget(metadata, MAX_METADATA_BYTES);
            // Render only this typed batch-ID projection or a localized action label, NEVER
            // raw metadata/name/policy JSON. invoice_policy is a label, not financial logic.
            List<Long> added = action == Action.ADD_MEMBERS && metadata.has("user_ids")
                    ? jsonIds(array(metadata, "user_ids"), MAX_SELECTED, false) : Collections.emptyList();
            events.add(new Event(event, positive(row.opt("actor_user_id")), nullableId(row, "actor_membership_id"),
                    nullableId(row, "target_user_id"), action, stamp(row.opt("created_at")), added));
        }
        long next = nullableId(body, "next_before_id");
        require(next == 0 || !events.isEmpty() && next == previous);
        return new EventsPage(query, started, events, next);
    }

    private static List<Long> jsonIds(JSONArray array, int max, boolean empty) {
        List<Long> ids = new ArrayList<>(); require(array.length() <= max);
        for (int i = 0; i < array.length(); i++) ids.add(positive(array.opt(i)));
        return checkedIds(ids, max, empty);
    }
    private static List<Long> checkedIds(List<Long> source, int max, boolean empty) {
        require(source != null && source.size() <= max && (empty || !source.isEmpty()));
        List<Long> ids = new ArrayList<>(); Set<Long> unique = new HashSet<>();
        for (Long id : source) { require(id != null && id(id) && unique.add(id)); ids.add(id); }
        Collections.sort(ids); return immutable(ids);
    }
    private static String idsJson(List<Long> ids) {
        StringBuilder text = new StringBuilder("["); for (Long id : ids) { if (text.length() > 1) text.append(','); text.append(id); }
        return text.append(']').toString();
    }
    private static <T> List<T> immutable(List<T> values) { return Collections.unmodifiableList(new ArrayList<>(values)); }
    private static void response(JSONObject body) { require(body != null && !body.has("error") && number(body.opt("api_version"), 2)); budget(body, MAX_PAGE_BYTES); }
    private static void budget(JSONObject body, int max) { String json = body.toString(); require(json != null && bytes(json) <= max); }
    private static JSONObject object(Object raw) { require(raw instanceof JSONObject); return (JSONObject) raw; }
    private static JSONArray array(JSONObject body, String key) { Object raw = body.opt(key); require(raw instanceof JSONArray); return (JSONArray) raw; }
    private static boolean flag(JSONObject body, String key) { Object raw = body.opt(key); require(raw instanceof Boolean); return (Boolean) raw; }
    private static boolean number(Object raw, long value) { return (raw instanceof Integer || raw instanceof Long) && ((Number) raw).longValue() == value; }
    private static boolean id(long id) { return id > 0 && id <= MAX_ID; }
    private static long positive(Object raw) { require((raw instanceof Integer || raw instanceof Long) && id(((Number) raw).longValue())); return ((Number) raw).longValue(); }
    private static long nullableId(JSONObject body, String key) { require(body.has(key)); return body.opt(key) == JSONObject.NULL ? 0 : positive(body.opt(key)); }
    private static String displayName(Object raw) {
        require(raw instanceof String); String name = (String) raw;
        require(!name.trim().isEmpty() && name.codePointCount(0, name.length()) <= 120 && bytes(name) <= 480);
        for (int i = 0; i < name.length(); i++) require(name.charAt(i) >= 32);
        return name;
    }
    private static void groupName(String name) {
        require(name != null && bytes(name) <= 256 && !blank(name));
        for (int i = 0; i < name.length();) { int code = name.codePointAt(i); require(!control(code)); i += Character.charCount(code); }
    }
    private static void groupDescription(String description) {
        require(bytes(description) <= 1024); String checked = description.replace("\r\n", "\n");
        for (int i = 0; i < checked.length();) { int code = checked.codePointAt(i); require(code == '\n' || !control(code)); i += Character.charCount(code); }
    }
    private static boolean blank(String value) {
        for (int i = 0; i < value.length();) { int code = value.codePointAt(i);
            if (!Character.isWhitespace(code) && !Character.isSpaceChar(code)) return false; i += Character.charCount(code); }
        return true;
    }
    private static boolean control(int code) {
        int kind = Character.getType(code);
        return kind == Character.CONTROL || kind == Character.FORMAT || kind == Character.SURROGATE
                || kind == Character.PRIVATE_USE || kind == Character.UNASSIGNED;
    }
    private static int bytes(String value) {
        try { return StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(value)).remaining(); }
        catch (CharacterCodingException invalid) { throw invalid(); }
    }
    private static String escaped(String value) {
        try { return URLEncoder.encode(value, "UTF-8").replace("+", "%20"); }
        catch (java.io.UnsupportedEncodingException impossible) { throw new IllegalStateException(impossible); }
    }
    private static boolean uuid(String value) { return value != null && value.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"); }
    private static String nullableStamp(JSONObject body, String key) { require(body.has(key)); return body.opt(key) == JSONObject.NULL ? null : stamp(body.opt(key)); }
    private static String stamp(Object raw) {
        require(raw instanceof String); String value = (String) raw;
        require(value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"));
        try { int year = Integer.parseInt(value.substring(0, 4)); require(year > 0);
            LocalDateTime.of(year, Integer.parseInt(value.substring(5, 7)), Integer.parseInt(value.substring(8, 10)),
                    Integer.parseInt(value.substring(11, 13)), Integer.parseInt(value.substring(14, 16)), Integer.parseInt(value.substring(17, 19)));
        } catch (DateTimeException | NumberFormatException invalid) { throw invalid(); }
        return value;
    }
    private static IllegalArgumentException invalid() { return new IllegalArgumentException("Invalid group people contract"); }
    private static void require(boolean valid) { if (!valid) throw invalid(); }
    private GroupPeopleProtocol() { }
}

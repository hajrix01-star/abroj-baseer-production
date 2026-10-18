package com.baseer.freshchat;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/** Semantic JSONObject/JSONArray fixtures use existing declared Gson-backed JVM adapters.
 * No native JSON/parser, Host, auth, storage, HTTP, Activity, notification or device claim. */
public final class GroupPeopleProtocolTest {
    private static int checks;
    private static final String UUID = "abcdef01-2345-4678-89ab-0123456789ab";
    private static final String STAMP = "2026-10-18T12:00:00Z";
    private interface Work { void run() throws Exception; }
    private static void check(boolean value, String message) { ++checks; if (!value) throw new AssertionError("People protocol " + checks + ": " + message); }
    private static void reject(Work action) throws Exception {
        try { action.run(); } catch (IllegalArgumentException expected) { ++checks; return; }
        throw new AssertionError("People protocol " + (checks + 1) + ": invalid value accepted");
    }
    private static void immutable(Work action) throws Exception {
        try { action.run(); } catch (UnsupportedOperationException expected) { ++checks; return; }
        throw new AssertionError("Mutable DTO collection");
    }
    private static JSONObject frame() throws Exception { return new JSONObject().put("api_version", 2); }
    private static JSONObject candidate(long id, String name) throws Exception { return new JSONObject().put("user_id", id).put("name", name); }
    private static JSONObject people(int start, int count, Object next) throws Exception {
        JSONArray list = new JSONArray(); for (int i = 0; i < count; i++) list.put(candidate(start + i, "زميل 👩🏽‍💻 / Same name"));
        return frame().put("users", list).put("next_after_user_id", next);
    }
    private static GroupPeopleProtocol.CandidateQuery query() { return new GroupPeopleProtocol.CandidateQuery(7, 41, "", 0); }
    private static GroupPeopleProtocol.Selection selection(GroupPeopleProtocol.Mode mode, int count) throws Exception {
        GroupPeopleProtocol.Selection selection = GroupPeopleProtocol.Selection.empty(mode, 7, 41, Collections.emptyList());
        int left = count, start = 100;
        while (left > 0) {
            int size = Math.min(left, 40); GroupPeopleProtocol.CandidatePage page = GroupPeopleProtocol.candidates(people(start, size, JSONObject.NULL), selection.query("", 0));
            for (GroupPeopleProtocol.Person person : page.people) selection = selection.toggle(page, person.userId);
            left -= size; start += size;
        }
        return selection;
    }
    private static JSONObject ack(GroupPeopleProtocol.Intent intent) throws Exception {
        JSONObject body = frame().put("room_id", intent.mode == GroupPeopleProtocol.Mode.ADD ? intent.roomId : 17).put("replayed", false);
        if (intent.mode == GroupPeopleProtocol.Mode.ADD) {
            JSONArray ids = new JSONArray(); for (long id : intent.userIds) ids.put(id);
            return body.put("client_uuid", intent.clientUuid).put("added_user_ids", ids);
        }
        body.put("membership_id", 23);
        if (intent.mode == GroupPeopleProtocol.Mode.DIRECT) body.put("created", false).put("client_uuid", intent.clientUuid)
                .put("peer", candidate(intent.userIds.get(0), "زميل 👩🏽‍💻"));
        return body;
    }
    private static JSONObject event(long id, String action) throws Exception {
        return new JSONObject().put("id", id).put("action", action).put("actor_user_id", 51)
                .put("actor_membership_id", JSONObject.NULL).put("target_user_id", JSONObject.NULL)
                .put("metadata", new JSONObject()).put("created_at", STAMP);
    }
    private static JSONObject events(JSONArray rows, Object next) throws Exception {
        return frame().put("room_id", 17).put("membership_id", 23).put("audit_started_at", STAMP)
                .put("historical_actions_backfilled", false).put("events", rows).put("next_before_id", next);
    }
    private static void negotiationAndQueries() throws Exception {
        check(!GroupPeopleProtocol.supported(null), "Absent contract never probes/enables");
        check(GroupPeopleProtocol.supported(frame().put("group_people_contract_version", 1)), "Optional native version1 accepted");
        for (Object bad : new Object[]{"1", true, 1.0, 0, 2, JSONObject.NULL})
            check(!GroupPeopleProtocol.supported(frame().put("group_people_contract_version", bad)), "Wrong optional version/type safe fallback");
        check(!GroupPeopleProtocol.supported(frame().put("group_people_contract_version", 1).put("error", new JSONObject())), "Error response never negotiates");
        check(query().path().equals("/bchat/api/v2/social/member-candidates?company_id=7&q="), "First directory page omits cursor0");
        GroupPeopleProtocol.CandidateQuery escaped = new GroupPeopleProtocol.CandidateQuery(7, 41, "زميل & ?/# +", 4);
        check(escaped.path().contains("%26%20%3F%2F%23%20%2B") && escaped.path().endsWith("&after_user_id=4"), "Only encoded query, no free URL injection");
        check(new GroupPeopleProtocol.EventsQuery(17, 23, 0).path().equals("/bchat/api/v2/rooms/17/group/events?membership_id=23"), "First audit page omits cursor0");
        check(new GroupPeopleProtocol.EventsQuery(17, 23, 200).path().endsWith("&before_id=200"), "Positive before cursor emitted");
        for (long bad : new long[]{-1, Long.MAX_VALUE, (long) Integer.MAX_VALUE + 1}) {
            reject(() -> new GroupPeopleProtocol.CandidateQuery(bad, 41, "", 0));
            reject(() -> new GroupPeopleProtocol.CandidateQuery(7, 41, "", bad));
            reject(() -> new GroupPeopleProtocol.EventsQuery(17, 23, bad));
        }
        reject(() -> new GroupPeopleProtocol.EventsQuery(17, 0, 0));
        reject(() -> new GroupPeopleProtocol.EventsQuery(0, 23, 0));
        reject(() -> new GroupPeopleProtocol.CandidateQuery(7, 0, "", 0));
        for (String bad : new String[]{"a".repeat(81), "😀".repeat(65), "a\nb", "a\tb", "\u0000", "\ud800", "\udc00"})
            reject(() -> new GroupPeopleProtocol.CandidateQuery(7, 41, bad, 0));
        check(new GroupPeopleProtocol.CandidateQuery(7, 41, "😀".repeat(64), 0).text.codePointCount(0, 128) == 64, "Codepoints/256UTF8 boundary, not UTF16 count");
    }
    private static void directory() throws Exception {
        GroupPeopleProtocol.CandidatePage page = GroupPeopleProtocol.candidates(people(100, 40, 180), query());
        check(page.people.size() == 40 && page.nextAfterUserId == 180 && page.nextQuery().afterUserId == 180, "40 rows and processed cursor may exceed last visible ID");
        GroupPeopleProtocol.CandidatePage empty = GroupPeopleProtocol.candidates(people(100, 0, 200), page.nextQuery());
        check(empty.people.isEmpty() && empty.nextQuery().afterUserId == 200, "Filtered empty page with progressing cursor is valid");
        GroupPeopleProtocol.CandidatePage end = GroupPeopleProtocol.candidates(people(100, 0, JSONObject.NULL), query());
        reject(end::nextQuery);
        immutable(() -> page.people.clear());
        for (Object bad : new Object[]{"2", true, 2.0, 1, JSONObject.NULL}) reject(() -> GroupPeopleProtocol.candidates(people(100, 1, JSONObject.NULL).put("api_version", bad), query()));
        for (Object bad : new Object[]{"1", true, 1.0, 0, -1, Long.MAX_VALUE, JSONObject.NULL}) {
            JSONObject row = frame().put("users", new JSONArray().put(new JSONObject().put("user_id", bad).put("name", "A"))).put("next_after_user_id", JSONObject.NULL);
            reject(() -> GroupPeopleProtocol.candidates(row, query()));
        }
        reject(() -> GroupPeopleProtocol.candidates(people(41, 1, JSONObject.NULL), query()));
        reject(() -> GroupPeopleProtocol.candidates(people(100, 41, JSONObject.NULL), query()));
        reject(() -> GroupPeopleProtocol.candidates(people(100, 1, 99), query()));
        reject(() -> GroupPeopleProtocol.candidates(people(100, 0, 180), page.nextQuery()));
        reject(() -> GroupPeopleProtocol.candidates(people(150, 1, JSONObject.NULL), page.nextQuery()));
        reject(() -> GroupPeopleProtocol.candidates(frame().put("users", new JSONArray().put(candidate(101, "A")).put(candidate(100, "B"))).put("next_after_user_id", JSONObject.NULL), query()));
        reject(() -> GroupPeopleProtocol.candidates(frame().put("users", new JSONArray().put(candidate(100, "A")).put(candidate(100, "B"))).put("next_after_user_id", JSONObject.NULL), query()));
        for (String name : new String[]{"", " ", "a\nb", "x".repeat(121), "😀".repeat(121), "\ud800"})
            reject(() -> GroupPeopleProtocol.candidates(frame().put("users", new JSONArray().put(candidate(100, name))).put("next_after_user_id", JSONObject.NULL), query()));
        check(GroupPeopleProtocol.candidates(frame().put("users", new JSONArray().put(candidate(100, "😀".repeat(120)))).put("next_after_user_id", JSONObject.NULL), query()).people.size() == 1, "Supplementary display-name boundary");
        JSONObject tooLarge = people(100, 1, JSONObject.NULL).put("future_field", "x".repeat(65536));
        reject(() -> GroupPeopleProtocol.candidates(tooLarge, query()));
        JSONObject mutable = people(100, 1, JSONObject.NULL); GroupPeopleProtocol.CandidatePage copied = GroupPeopleProtocol.candidates(mutable, query());
        ((JSONObject) ((JSONArray) mutable.opt("users")).opt(0)).put("name", "CHANGED");
        check(!copied.people.get(0).name.equals("CHANGED"), "No mutable source JSONObject retained in page");
        check(GroupPeopleProtocol.candidates(people(100, 1, JSONObject.NULL).put("future", true), query()).people.size() == 1, "Safe additive response keys ignored within budget");
    }
    private static void choicesAndIntents() throws Exception {
        GroupPeopleProtocol.Selection full = selection(GroupPeopleProtocol.Mode.CREATE, 49);
        check(full.people.size() == 49 && full.selectedIds().get(48) == 148, "49 distinct selected peers persist across pages with duplicate names");
        GroupPeopleProtocol.CandidatePage extra = GroupPeopleProtocol.candidates(people(200, 1, JSONObject.NULL), full.query("Other query", 0));
        reject(() -> full.toggle(extra, 200));
        check(full.people.size() == 49 && full.query("new search", 0).afterUserId == 0, "Changing query preserves selection and resets cursor only");
        check(full.remove(100).people.size() == 48 && full.people.size() == 49, "Immutable deselection leaves old instance intact");
        immutable(() -> full.people.clear()); immutable(() -> full.selectedIds().clear());
        List<Long> excluded = new ArrayList<>(Arrays.asList(100L));
        GroupPeopleProtocol.Selection add = GroupPeopleProtocol.Selection.empty(GroupPeopleProtocol.Mode.ADD, 7, 41, excluded); excluded.clear();
        GroupPeopleProtocol.CandidatePage page = GroupPeopleProtocol.candidates(people(100, 3, JSONObject.NULL), query());
        reject(() -> add.toggle(page, 100));
        check(add.excludedUserIds.size() == 1, "Excluded current roster is defensively copied, not authority");
        reject(() -> add.toggle(GroupPeopleProtocol.candidates(people(100, 1, JSONObject.NULL), new GroupPeopleProtocol.CandidateQuery(8, 41, "", 0)), 100));
        reject(() -> add.toggle(GroupPeopleProtocol.candidates(people(100, 1, JSONObject.NULL), new GroupPeopleProtocol.CandidateQuery(7, 42, "", 0)), 100));
        GroupPeopleProtocol.Selection direct = selection(GroupPeopleProtocol.Mode.DIRECT, 1);
        GroupPeopleProtocol.Selection changed = direct.toggle(page, 101);
        check(direct.people.get(0).userId == 100 && changed.people.size() == 1 && changed.people.get(0).userId == 101, "Direct selection is single/radio, old selection immutable");
        reject(() -> GroupPeopleProtocol.direct(changed.remove(101), UUID));
        GroupPeopleProtocol.Intent create = GroupPeopleProtocol.create(full, UUID, "فريق بصير", "تفاصيل\r\nثابتة");
        JSONObject request = new JSONObject(create.payload);
        check(request.length() == 6 && create.path().equals("/bchat/api/v2/rooms") && create.userIds.size() == 49, "Exact create keys use existing route and creator excluded");
        check(request.opt("description").equals("تفاصيل\r\nثابتة"), "No retry-time normalization of original payload");
        String exact = create.payload; full.remove(100); request.put("client_uuid", "MUTATED");
        check(exact.equals(create.payload) && create.clientUuid.equals(UUID) && create.userIds.size() == 49, "UUID/fullpayload fixed independent of selection/JSON copies");
        immutable(() -> create.userIds.clear());
        GroupPeopleProtocol.Intent directIntent = GroupPeopleProtocol.direct(direct, UUID);
        check(new JSONObject(directIntent.payload).length() == 4 && !directIntent.payload.contains("Same name") && directIntent.path().endsWith("/direct-rooms"), "Direct intent is IDs only, no candidate names");
        GroupPeopleProtocol.Intent addIntent = GroupPeopleProtocol.add(selection(GroupPeopleProtocol.Mode.ADD, 2), UUID, 17, 23);
        check(new JSONObject(addIntent.payload).length() == 4 && !addIntent.payload.contains("Same name") && addIntent.path().endsWith("/rooms/17/group/members"), "Batch intent is one exact request, not add_member loop");
        reject(() -> GroupPeopleProtocol.add(selection(GroupPeopleProtocol.Mode.ADD, 2), UUID, 17, 0));
        reject(() -> GroupPeopleProtocol.direct(full, UUID));
        for (String bad : new String[]{UUID.toUpperCase(), "abcdef01-2345-1678-89ab-0123456789ab", "x", ""}) reject(() -> GroupPeopleProtocol.create(full, bad, "Group", null));
        for (String bad : new String[]{"", " ", "\u00a0", "x".repeat(257), "أ".repeat(129), "a\tb", "\ud800", "\ue000", "a\u200db"}) reject(() -> GroupPeopleProtocol.create(full, UUID, bad, null));
        check(GroupPeopleProtocol.create(full, UUID, "أ".repeat(128), null).payload.length() > 0, "256UTF8 group name accepted");
        reject(() -> GroupPeopleProtocol.create(full, UUID, "Group", "x".repeat(1025)));
        reject(() -> GroupPeopleProtocol.create(full, UUID, "Group", "a\tb"));
        check(GroupPeopleProtocol.create(full, UUID, "Group", "x".repeat(1024)).payload.length() > 1024, "1024UTF8 description accepted");
        reject(() -> GroupPeopleProtocol.Selection.empty(GroupPeopleProtocol.Mode.ADD, 7, 41, Arrays.asList(100L, 100L)));
    }
    private static void acknowledgements() throws Exception {
        for (GroupPeopleProtocol.Mode mode : GroupPeopleProtocol.Mode.values()) {
            GroupPeopleProtocol.Selection selected = selection(mode, mode == GroupPeopleProtocol.Mode.DIRECT ? 1 : 3);
            GroupPeopleProtocol.Intent intent = mode == GroupPeopleProtocol.Mode.DIRECT ? GroupPeopleProtocol.direct(selected, UUID)
                    : mode == GroupPeopleProtocol.Mode.CREATE ? GroupPeopleProtocol.create(selected, UUID, "Group", null) : GroupPeopleProtocol.add(selected, UUID, 17, 23);
            for (boolean replayed : new boolean[]{false, true}) {
                JSONObject body = ack(intent).put("replayed", replayed);
                GroupPeopleProtocol.Acknowledgement parsed = GroupPeopleProtocol.acknowledgement(200, body, intent);
                check(parsed.intent == intent && parsed.roomId == 17 && parsed.replayed == replayed, "ACK immutable original-intent association, not auth: " + mode);
            }
            reject(() -> GroupPeopleProtocol.acknowledgement(409, ack(intent), intent));
            reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("replayed", "false"), intent));
            reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("room_id", "17"), intent));
            reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("api_version", 2.0), intent));
            reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("error", new JSONObject()), intent));
            if (mode == GroupPeopleProtocol.Mode.CREATE) {
                check(!ack(intent).has("client_uuid") && GroupPeopleProtocol.acknowledgement(200, ack(intent), intent).membershipId == 23, "Existing create ACK intentionally has no UUID echo");
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("membership_id", JSONObject.NULL), intent));
            } else {
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("client_uuid", UUID.toUpperCase()), intent));
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("client_uuid", JSONObject.NULL), intent));
            }
            if (mode == GroupPeopleProtocol.Mode.DIRECT) {
                check(!GroupPeopleProtocol.acknowledgement(200, ack(intent), intent).created, "Existing pair created=false/replayed=false remains valid");
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("created", 0), intent));
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("peer", candidate(999, "Wrong")), intent));
            } else if (mode == GroupPeopleProtocol.Mode.ADD) {
                check(!ack(intent).has("membership_id") && GroupPeopleProtocol.acknowledgement(200, ack(intent), intent).membershipId == intent.membershipId, "ADD uses original positive member association, not a nonexistent echo");
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("room_id", 18), intent));
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("added_user_ids", new JSONArray().put(100)), intent));
                reject(() -> GroupPeopleProtocol.acknowledgement(200, ack(intent).put("added_user_ids", new JSONArray().put(100).put(100).put(102)), intent));
                check(GroupPeopleProtocol.acknowledgement(200, ack(intent).put("added_user_ids", new JSONArray().put(102).put(100).put(101)), intent).addedUserIds.equals(intent.userIds), "Full set equality, server order need not match request serialization");
            }
        }
    }
    private static void eventPages() throws Exception {
        GroupPeopleProtocol.EventsQuery query = new GroupPeopleProtocol.EventsQuery(17, 23, 100);
        for (GroupPeopleProtocol.Action action : GroupPeopleProtocol.Action.values()) {
            JSONObject row = event(99, action.wire);
            GroupPeopleProtocol.Event parsed = GroupPeopleProtocol.events(events(new JSONArray().put(row), JSONObject.NULL), query).events.get(0);
            check(parsed.action == action && parsed.actorUserId == 51 && parsed.actorMembershipId == 0 && parsed.targetUserId == 0, "12 actions/nullable actor member parsed without inventing actor names/schema");
        }
        JSONObject batch = event(99, "add_members").put("metadata", new JSONObject().put("user_ids", new JSONArray().put(3).put(2)));
        check(GroupPeopleProtocol.events(events(new JSONArray().put(batch), JSONObject.NULL), query).events.get(0).addedUserIds.equals(Arrays.asList(2L, 3L)), "Typed optional IDs projection, no raw metadata");
        JSONObject invoice = event(99, "invoice_policy").put("metadata", new JSONObject().put("before", "off").put("after", "invoice_default").put("future", "PRIVATE_NOT_RENDERED"));
        check(GroupPeopleProtocol.events(events(new JSONArray().put(invoice), JSONObject.NULL), query).events.get(0).addedUserIds.isEmpty(), "invoice_policy is action label only, not financial calculation/permission");
        JSONArray rows = new JSONArray(); for (int i = 99; i >= 70; i--) rows.put(event(i, "rename"));
        GroupPeopleProtocol.EventsPage page = GroupPeopleProtocol.events(events(rows, 70), query);
        check(page.events.size() == 30 && page.nextQuery().beforeId == 70 && page.auditStartedAt.equals(STAMP), "30 descending events, exact last cursor and audit-start scope");
        immutable(() -> page.events.clear()); immutable(() -> page.events.get(0).addedUserIds.clear());
        GroupPeopleProtocol.EventsPage empty = GroupPeopleProtocol.events(events(new JSONArray(), JSONObject.NULL).put("audit_started_at", JSONObject.NULL), query);
        check(empty.events.isEmpty() && empty.auditStartedAt == null, "Empty unknown start is not invented history/backfill"); reject(empty::nextQuery);
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray(), 90), query));
        reject(() -> GroupPeopleProtocol.events(events(rows, 69), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(100, "create")), JSONObject.NULL), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(98, "create")).put(event(99, "rename")), JSONObject.NULL), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(99, "create")).put(event(99, "rename")), JSONObject.NULL), query));
        reject(() -> GroupPeopleProtocol.events(events(rows.put(event(69, "create")), JSONObject.NULL), query));
        for (Object bad : new Object[]{JSONObject.NULL, "23", 23.0, 0, true}) reject(() -> GroupPeopleProtocol.events(events(new JSONArray(), JSONObject.NULL).put("membership_id", bad), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray(), JSONObject.NULL).put("room_id", 18), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray(), JSONObject.NULL).put("historical_actions_backfilled", true), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray(), JSONObject.NULL).put("historical_actions_backfilled", "false"), query));
        for (Object bad : new Object[]{0, "51", true, 51.0, JSONObject.NULL, BigDecimal.ONE}) reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(99, "create").put("actor_user_id", bad)), JSONObject.NULL), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(99, "unknown")), JSONObject.NULL), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(99, "create").put("metadata", "{}")), JSONObject.NULL), query));
        reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(99, "create").put("metadata", new JSONObject().put("x", "x".repeat(2048)))), JSONObject.NULL), query));
        for (String bad : new String[]{"2026-02-29T12:00:00Z", "0000-01-01T00:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T00:00:60Z", "2026-01-01", "2026-01-01T00:00:00+00:00"})
            reject(() -> GroupPeopleProtocol.events(events(new JSONArray().put(event(99, "create").put("created_at", bad)), JSONObject.NULL), query));
        check(GroupPeopleProtocol.events(events(new JSONArray().put(event(99, "create").put("created_at", "2024-02-29T00:00:00Z")), JSONObject.NULL), query).events.size() == 1, "Gregorian leap day accepted without device clock");
        JSONObject mutable = events(new JSONArray().put(event(99, "create")), JSONObject.NULL); GroupPeopleProtocol.EventsPage copied = GroupPeopleProtocol.events(mutable, query);
        ((JSONObject) ((JSONArray) mutable.opt("events")).opt(0)).put("actor_user_id", 999);
        check(copied.events.get(0).actorUserId == 51, "No source JSONObject retained by event DTO");
    }
    private static void dtoShape() {
        for (Class<?> type : new Class<?>[]{GroupPeopleProtocol.CandidateQuery.class, GroupPeopleProtocol.Person.class,
                GroupPeopleProtocol.CandidatePage.class, GroupPeopleProtocol.Selection.class, GroupPeopleProtocol.Intent.class,
                GroupPeopleProtocol.Acknowledgement.class, GroupPeopleProtocol.EventsQuery.class, GroupPeopleProtocol.Event.class, GroupPeopleProtocol.EventsPage.class})
            for (Field field : type.getDeclaredFields()) if (!Modifier.isStatic(field.getModifiers())) {
                check(Modifier.isFinal(field.getModifiers()), "Immutable field " + type.getSimpleName() + "." + field.getName());
                check(field.getType() != JSONObject.class && field.getType() != JSONArray.class && field.getType() != Object.class,
                        "DTO has no mutable JSON/Activity/Room/Object authority carrier");
            }
    }
    public static void main(String[] args) throws Exception {
        negotiationAndQueries(); directory(); choicesAndIntents(); acknowledgements(); eventPages(); dtoShape();
        System.out.println("PASS " + checks + " production GroupPeopleProtocol assertions; semantic JSONObject/Gson JVM adapters only, no nativeJSON/HTTP/auth/storage/Activity/FCM");
    }
}

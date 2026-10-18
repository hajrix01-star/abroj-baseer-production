package com.baseer.freshchat;

import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

/** Protocol behavior on JVM JSON adapters; no Activity, transport or authentication fixture. */
public final class RoomExploreCases {
    static int assertions;
    interface Work { void run() throws Exception; }
    static void check(boolean value) { ++assertions; if (!value) throw new AssertionError("check " + assertions); }
    static void reject(Work work) throws Exception {
        ++assertions;
        try { work.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("accepted invalid input at " + assertions);
    }
    static RoomExploreProtocol.Query search(RoomExploreProtocol.Kind kind, long before) {
        return new RoomExploreProtocol.Query(12, 41, false, kind, "فاتورة kitchen", before);
    }
    static JSONObject message(long id) throws Exception {
        return new JSONObject().put("id", id).put("author_user_id", 8).put("author_name", "أحمد | Ahmed")
                .put("text", "فاتورة kitchen رقم 123").put("created_at", "2026-10-18 10:20:30");
    }
    static JSONObject response(JSONObject... rows) throws Exception {
        JSONArray messages = new JSONArray(); for (JSONObject row : rows) messages.put(row);
        return new JSONObject().put("api_version", 2).put("membership_id", 41)
                .put("messages", messages).put("next_before_id", JSONObject.NULL);
    }
    static JSONObject media(String kind) throws Exception {
        return new JSONObject().put("id", 91).put("kind", kind)
                .put("mime", "image".equals(kind) ? "image/jpeg" : "audio".equals(kind) ? "audio/mp4" : "application/pdf")
                .put("size", 1234).put("name", "عرض-2026.pdf").put("sha256", "a".repeat(64))
                .put("document_type", "other").put("thumbnail_available", !"file".equals(kind));
    }
    public static void main(String[] args) throws Exception {
        check(RoomExploreProtocol.supported(new JSONObject().put("api_version", 2).put("history_search_contract_version", 1)));
        for (Object version : Arrays.asList("1", 1.0, true, JSONObject.NULL, 0, 2))
            check(!RoomExploreProtocol.supported(new JSONObject().put("api_version", 2).put("history_search_contract_version", version)));
        check(!RoomExploreProtocol.supported(new JSONObject().put("api_version", 2)));
        RoomExploreProtocol.Query query = search(RoomExploreProtocol.Kind.ALL, 0);
        check(query.payload().length() == 5);
        check(query.payload().opt("before_id") == JSONObject.NULL);
        check(query.path().equals("/bchat/api/v2/rooms/12/search"));
        check(!query.path().contains("فاتورة"));
        check(((Number) search(RoomExploreProtocol.Kind.FILE, 7).payload().opt("before_id")).longValue() == 7);
        RoomExploreProtocol.Query gallery = new RoomExploreProtocol.Query(12, 41, true, RoomExploreProtocol.Kind.ALL, null, 0);
        check(gallery.path().equals("/bchat/api/v2/rooms/12/media?membership_id=41&kind=all"));
        check(!gallery.path().contains("before_id"));
        check(new RoomExploreProtocol.Query(12, 41, true, RoomExploreProtocol.Kind.IMAGE, null, 9).path().endsWith("&before_id=9"));
        reject(gallery::payload);
        reject(() -> new RoomExploreProtocol.Query(0, 41, false, RoomExploreProtocol.Kind.ALL, "x", 0));
        reject(() -> new RoomExploreProtocol.Query(12, 0, false, RoomExploreProtocol.Kind.ALL, "x", 0));
        reject(() -> new RoomExploreProtocol.Query(12, 41, true, RoomExploreProtocol.Kind.TEXT, null, 0));
        reject(() -> new RoomExploreProtocol.Query(12, 41, false, null, "x", 0));
        reject(() -> new RoomExploreProtocol.Query(12, 41, false, RoomExploreProtocol.Kind.ALL, "x", -1));
        reject(() -> new RoomExploreProtocol.Query(12, 41, false, RoomExploreProtocol.Kind.ALL, "x", 2147483648L));
        check(RoomExploreProtocol.searchText("واحد اثنان three أربعة five ستة seven ثمانية").contains("three"));
        check(RoomExploreProtocol.searchText("x".repeat(128)).length() == 128);
        for (String invalid : new String[]{"", "   ", "\u00a0", "a b c d e f g h i", "x".repeat(129),
                "ع".repeat(65), "line\nbreak", "a\u202eb", "a\u0000b", "x\ud800", "a\ue000b"})
            reject(() -> RoomExploreProtocol.searchText(invalid));
        reject(() -> RoomExploreProtocol.searchText(null));
        JSONObject original = response(message(2), message(4));
        RoomExploreProtocol.Page page = RoomExploreProtocol.page(original, query);
        check(page.roomId == 12 && page.membershipId == 41); // route-bound, no fabricated server echo
        check(page.rows.size() == 2 && page.rows.get(0).id == 2 && page.nextBeforeId == 0);
        ((JSONObject) ((JSONArray) original.opt("messages")).opt(0)).put("text", "changed");
        check(page.rows.get(0).text.equals("فاتورة kitchen رقم 123"));
        try { page.rows.clear(); throw new AssertionError("mutable page"); }
        catch (UnsupportedOperationException expected) { ++assertions; }
        check(RoomExploreProtocol.page(response(), query).rows.isEmpty());
        check(RoomExploreProtocol.page(response(message(2), message(4)).put("next_before_id", 2), search(RoomExploreProtocol.Kind.ALL, 7)).nextBeforeId == 2);
        reject(() -> RoomExploreProtocol.page(response(message(4), message(2)), query));
        reject(() -> RoomExploreProtocol.page(response(message(2), message(2)), query));
        reject(() -> RoomExploreProtocol.page(response(message(7)), search(RoomExploreProtocol.Kind.ALL, 7)));
        reject(() -> RoomExploreProtocol.page(response().put("next_before_id", 2), query));
        reject(() -> RoomExploreProtocol.page(response(message(2), message(4)).put("next_before_id", 4), query));
        reject(() -> RoomExploreProtocol.page(response(message(2)).put("next_before_id", 0), query));
        reject(() -> RoomExploreProtocol.page(response(message(2)).put("membership_id", 42), query));
        reject(() -> RoomExploreProtocol.page(response(message(2)).put("membership_id", "41"), query));
        reject(() -> RoomExploreProtocol.page(response(message(2)).put("api_version", true), query));
        reject(() -> RoomExploreProtocol.page(response(message(2)).put("room_id", 13), query));
        check(RoomExploreProtocol.page(response(message(2)).put("room_id", 12), query).rows.size() == 1);
        reject(() -> RoomExploreProtocol.page(response(message(2).put("id", "2")), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("author_user_id", 2.0)), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("author_name", "")), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("author_name", "a\nb")), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("created_at", "")), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("text", true)), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("text", "")), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("text", "x".repeat(16385))), query));
        reject(() -> RoomExploreProtocol.page(response(message(2)).put("unused_future", "x".repeat(128 * 1024)), query));
        JSONArray tooMany = new JSONArray(); for (int i = 1; i <= 31; ++i) tooMany.put(message(i));
        reject(() -> RoomExploreProtocol.page(response().put("messages", tooMany), query));
        for (String state : new String[]{"sent", "delivered", "read"})
            check(RoomExploreProtocol.page(response(message(2).put("delivery_state", state)), query).rows.size() == 1);
        reject(() -> RoomExploreProtocol.page(response(message(2).put("delivery_state", "unknown")), query));
        check(RoomExploreProtocol.page(response(message(2).put("reply", new JSONObject().put("unavailable", true))), query).rows.size() == 1);
        check(RoomExploreProtocol.page(response(message(2).put("reply", new JSONObject().put("id", 1).put("author_name", "A").put("text", "parent"))), query).rows.size() == 1);
        reject(() -> RoomExploreProtocol.page(response(message(2).put("reply", new JSONObject().put("unavailable", false))), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("reply", new JSONObject().put("id", 2).put("author_name", "A").put("text", "parent"))), query));
        for (RoomExploreProtocol.Kind kind : new RoomExploreProtocol.Kind[]{RoomExploreProtocol.Kind.IMAGE, RoomExploreProtocol.Kind.FILE, RoomExploreProtocol.Kind.AUDIO}) {
            JSONObject data = message(2).put("text", "").put("media", media(kind.wire));
            check(RoomExploreProtocol.page(response(data), search(kind, 0)).rows.get(0).mediaKind.equals(kind.wire));
            check(RoomExploreProtocol.page(response(data), new RoomExploreProtocol.Query(12, 41, true, kind, null, 0)).rows.size() == 1);
            reject(() -> RoomExploreProtocol.page(response(data), search(RoomExploreProtocol.Kind.TEXT, 0)));
        }
        reject(() -> RoomExploreProtocol.page(response(message(2)), gallery));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("media", media("image"))), search(RoomExploreProtocol.Kind.AUDIO, 0)));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("media", media("image").put("size", 5242881))), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("media", media("audio").put("size", 10485761))), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("media", media("file").put("thumbnail_available", true))), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("media", media("file").put("extra", true))), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("media", media("file").put("mime", "text/html"))), query));
        reject(() -> RoomExploreProtocol.page(response(message(2).put("media", media("file").put("sha256", "x".repeat(64)))), query));
        reject(() -> RoomExploreProtocol.page(null, query));
        reject(() -> RoomExploreProtocol.page(response(), null));
        System.out.println("PASS " + assertions + " RoomExploreProtocol assertions; JVM JSON adapters, no HTTP/Activity/authentication");
    }
}

package com.baseer.freshchat;

import com.baseer.freshchat.sync.OutboxPolicy;
import com.baseer.freshchat.sync.BChatConnectedMediaStore;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Read-only route-bound search projection. Not authentication, receipt or media authority. */
final class RoomExploreProtocol {
    static final int MAX_PAGE_BYTES = 128 * 1024;
    enum Kind {
        ALL("all"), TEXT("text"), IMAGE("image"), FILE("file"), AUDIO("audio");
        final String wire;
        Kind(String wire) { this.wire = wire; }
    }
    static final class Query {
        final long roomId, membershipId, beforeId;
        final boolean gallery;
        final Kind kind;
        final String text;
        Query(long room, long member, boolean gallery, Kind kind, String text, long before) {
            requireId(room); requireId(member);
            if (before < 0 || before > OutboxPolicy.MAX_RECORD_ID || kind == null
                    || gallery && kind == Kind.TEXT) throw invalid();
            roomId = room; membershipId = member; this.gallery = gallery;
            this.kind = kind; beforeId = before;
            this.text = gallery ? "" : searchText(text);
        }
        String path() {
            String path = "/bchat/api/v2/rooms/" + roomId;
            if (!gallery) return path + "/search";
            return path + "/media?membership_id=" + membershipId + "&kind=" + kind.wire
                    + (beforeId == 0 ? "" : "&before_id=" + beforeId);
        }
        JSONObject payload() {
            if (gallery) throw invalid();
            try {
                return new JSONObject().put("api_version", 2).put("membership_id", membershipId)
                        .put("q", text).put("kind", kind.wire)
                        .put("before_id", beforeId == 0 ? JSONObject.NULL : beforeId);
            } catch (Exception malformed) { throw invalid(); }
        }
    }
    static final class Row {
        final long id, authorId;
        final String author, text, createdAt, mediaKind, fileName;
        private Row(long id, long authorId, String author, String text, String createdAt,
                String mediaKind, String fileName) {
            this.id = id; this.authorId = authorId; this.author = author; this.text = text;
            this.createdAt = createdAt; this.mediaKind = mediaKind; this.fileName = fileName;
        }
    }
    static final class Page {
        final long roomId, membershipId, nextBeforeId;
        final List<Row> rows;
        private Page(Query query, List<Row> rows, long next) {
            // The existing response intentionally has no room_id; use the dispatched route.
            roomId = query.roomId; membershipId = query.membershipId; nextBeforeId = next;
            this.rows = Collections.unmodifiableList(new ArrayList<>(rows));
        }
    }

    static boolean supported(JSONObject bootstrap) {
        return bootstrap != null && integer(bootstrap.opt("api_version")) == 2
                && integer(bootstrap.opt("history_search_contract_version")) == 1;
    }
    static Page page(JSONObject body, Query query) {
        if (body == null || query == null) throw invalid();
        try {
            String encoded = body.toString();
            if (encoded == null || encoded.getBytes(StandardCharsets.UTF_8).length > MAX_PAGE_BYTES
                    || integer(body.opt("api_version")) != 2
                    || integer(body.opt("membership_id")) != query.membershipId) throw invalid();
            // If a future compatible server adds this echo it must not contradict the route.
            if (body.has("room_id") && integer(body.opt("room_id")) != query.roomId) throw invalid();
            Object raw = body.opt("messages");
            if (!(raw instanceof JSONArray) || ((JSONArray) raw).length() > 30) throw invalid();
            List<Row> rows = new ArrayList<>();
            JSONArray messages = (JSONArray) raw;
            long last = 0;
            for (int i = 0; i < messages.length(); ++i) {
                Object rawRow = messages.opt(i);
                if (!(rawRow instanceof JSONObject)) throw invalid();
                JSONObject item = (JSONObject) rawRow;
                long id = recordId(item.opt("id")), authorId = recordId(item.opt("author_user_id"));
                if (id <= last || query.beforeId > 0 && id >= query.beforeId) throw invalid();
                String author = label(item.opt("author_name"), 160);
                String stamp = label(item.opt("created_at"), 64);
                Object rawText = item.opt("text");
                if (!(rawText instanceof String)) throw invalid();
                String text = (String) rawText, mediaKind = "", fileName = "";
                if (item.has("media")) {
                    Object rawMedia = item.opt("media");
                    if (!(rawMedia instanceof JSONObject)) throw invalid();
                    JSONObject media = (JSONObject) rawMedia;
                    requireMedia(media);
                    mediaKind = (String) media.opt("kind"); fileName = (String) media.opt("name");
                }
                if (mediaKind.isEmpty() || !text.isEmpty()) OutboxPolicy.requireText(text);
                if (query.gallery && mediaKind.isEmpty()
                        || query.kind == Kind.TEXT && !mediaKind.isEmpty()
                        || query.kind != Kind.ALL && query.kind != Kind.TEXT
                            && !query.kind.wire.equals(mediaKind)) throw invalid();
                if (item.has("reply")) requireReply(item.opt("reply"), id);
                if (item.has("delivery_state") && !("sent".equals(item.opt("delivery_state"))
                        || "delivered".equals(item.opt("delivery_state"))
                        || "read".equals(item.opt("delivery_state")))) throw invalid();
                rows.add(new Row(id, authorId, author, text, stamp, mediaKind, fileName)); last = id;
            }
            if (!body.has("next_before_id")) throw invalid();
            Object cursor = body.opt("next_before_id");
            long next = cursor == JSONObject.NULL ? 0 : recordId(cursor);
            if (next > 0 && (rows.isEmpty() || next != rows.get(0).id
                    || query.beforeId > 0 && next >= query.beforeId)) throw invalid();
            return new Page(query, rows, next);
        } catch (Exception malformed) { throw invalid(); }
    }

    static String searchText(String value) {
        if (value == null) throw invalid();
        int words = 0; boolean inWord = false, any = false;
        for (int offset = 0; offset < value.length();) {
            int point = value.codePointAt(offset); offset += Character.charCount(point);
            int category = Character.getType(point);
            if (category == Character.CONTROL || category == Character.FORMAT
                    || category == Character.PRIVATE_USE || category == Character.SURROGATE
                    || category == Character.UNASSIGNED) throw invalid();
            boolean space = Character.isWhitespace(point) || Character.isSpaceChar(point);
            if (!space) { any = true; if (!inWord) ++words; }
            inWord = !space;
        }
        if (!any || words > 8 || value.getBytes(StandardCharsets.UTF_8).length > 128) throw invalid();
        return value;
    }
    private static void requireReply(Object raw, long messageId) {
        if (!(raw instanceof JSONObject)) throw invalid();
        JSONObject reply = (JSONObject) raw;
        Set<String> keys = new HashSet<>(); reply.keys().forEachRemaining(keys::add);
        if (reply.has("unavailable")) {
            if (!(reply.opt("unavailable") instanceof Boolean)) throw invalid();
            ReplyWireContract.requireUnavailable(keys, (Boolean) reply.opt("unavailable"));
        } else {
            Object text = reply.opt("text");
            if (!(text instanceof String)) throw invalid();
            String mediaKind = reply.has("media_kind") && reply.opt("media_kind") != JSONObject.NULL
                    ? label(reply.opt("media_kind"), 16) : null;
            ReplyWireContract.requireAvailable(keys, messageId, recordId(reply.opt("id")),
                    label(reply.opt("author_name"), 160), (String) text, mediaKind);
        }
    }
    private static void requireMedia(JSONObject media) {
        if (media.length() != 8) throw invalid();
        recordId(media.opt("id"));
        String kind = label(media.opt("kind"), 16), mime = label(media.opt("mime"), 160);
        String name = label(media.opt("name"), 160), digest = label(media.opt("sha256"), 64);
        String document = label(media.opt("document_type"), 32);
        long size = integer(media.opt("size"));
        boolean image = "image".equals(kind), audio = "audio".equals(kind), file = "file".equals(kind);
        long maximum = image ? BChatConnectedMediaStore.IMAGE_LIMIT
                : audio ? BChatConnectedMediaStore.AUDIO_LIMIT : file ? BChatConnectedMediaStore.PDF_LIMIT : 0;
        if (size <= 0 || size > maximum || name.getBytes(StandardCharsets.UTF_8).length > 160
                || !digest.matches("[0-9a-f]{64}") || !(media.opt("thumbnail_available") instanceof Boolean)
                || !("other".equals(document) || "invoice".equals(document) || "payment_receipt".equals(document))
                || !(image ? "image/jpeg".equals(mime) || "image/png".equals(mime) || "image/webp".equals(mime)
                    : audio ? "audio/mp4".equals(mime) : file && ("application/pdf".equals(mime)
                        || "application/vnd.openxmlformats-officedocument.wordprocessingml.document".equals(mime)
                        || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet".equals(mime)
                        || "text/plain".equals(mime)))
                || file && Boolean.TRUE.equals(media.opt("thumbnail_available"))) throw invalid();
    }
    private static String label(Object value, int max) {
        if (!(value instanceof String)) throw invalid();
        String text = (String) value;
        if (text.trim().isEmpty() || text.length() > max) throw invalid();
        for (int i = 0; i < text.length(); ++i) if (Character.isISOControl(text.charAt(i))) throw invalid();
        return text;
    }
    private static long integer(Object value) {
        return value instanceof Integer || value instanceof Long ? ((Number) value).longValue() : -1;
    }
    private static long recordId(Object value) { long id = integer(value); requireId(id); return id; }
    private static void requireId(long value) { if (value < 1 || value > OutboxPolicy.MAX_RECORD_ID) throw invalid(); }
    private static IllegalArgumentException invalid() { return new IllegalArgumentException("Unsupported room search response"); }
    private RoomExploreProtocol() { }
}

package com.baseer.freshchat;

import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/** Read-only receipt-detail boundary. IDs bind a verified session; they are not authorization. */
final class ReceiptDetailsProtocol {
    private static final long MAX_ID = 2147483647L;
    private static final DateTimeFormatter UTC = DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss")
            .withResolverStyle(ResolverStyle.STRICT);
    static final class Row {
        final long id, userId;
        final String name, deliveredAt, readAt;
        Row(long id, long userId, String name, String deliveredAt, String readAt) {
            this.id = id; this.userId = userId; this.name = name;
            this.deliveredAt = deliveredAt; this.readAt = readAt;
        }
    }
    static final class Page {
        final String state;
        final long eligible, delivered, read, nextAfterId;
        final boolean hasMore;
        final List<Row> rows;
        Page(String state, long eligible, long delivered, long read, long next, boolean more, List<Row> rows) {
            this.state = state; this.eligible = eligible; this.delivered = delivered; this.read = read;
            nextAfterId = next; hasMore = more; this.rows = Collections.unmodifiableList(rows);
        }
    }
    static String path(long roomId, long messageId, long afterId) {
        require(validId(roomId) && validId(messageId) && afterId >= 0 && afterId <= MAX_ID);
        return "/bchat/api/v2/rooms/" + roomId + "/messages/" + messageId + "/receipts?after_id=" + afterId;
    }
    static Page page(JSONObject body, long roomId, long membershipId, long messageId, long afterId) {
        require(validId(roomId) && validId(membershipId) && validId(messageId) && afterId >= 0 && afterId <= MAX_ID);
        require(body != null && utf8(body.toString()) <= 65536 && !body.has("error"));
        require(number(body.opt("api_version")) == 2 && positive(body.opt("room_id")) == roomId
                && positive(body.opt("membership_id")) == membershipId && positive(body.opt("message_id")) == messageId);
        JSONObject counts = body.optJSONObject("counts");
        require(counts != null);
        long eligible = number(counts.opt("eligible")), delivered = number(counts.opt("delivered")), read = number(counts.opt("read"));
        require(read <= delivered && delivered <= eligible);
        Object state = body.opt("state");
        String expected = eligible > 0 && read == eligible ? "read"
                : eligible > 0 && delivered == eligible ? "delivered" : "sent";
        require(expected.equals(state));
        JSONArray receipts = body.optJSONArray("receipts");
        require(receipts != null && receipts.length() <= 30 && receipts.length() <= eligible
                && body.opt("has_more") instanceof Boolean);
        long previous = afterId;
        List<Row> rows = new ArrayList<>();
        for (int index = 0; index < receipts.length(); index++) {
            JSONObject item = receipts.optJSONObject(index); require(item != null);
            long id = positive(item.opt("id")), user = positive(item.opt("user_id"));
            require(id > previous); previous = id;
            Object value = item.opt("user_name"); require(value instanceof String);
            String name = (String) value;
            require(!name.trim().isEmpty() && name.codePointCount(0, name.length()) <= 120 && utf8(name) <= 256);
            for (int offset = 0; offset < name.length();) {
                int code = name.codePointAt(offset); int kind = Character.getType(code);
                require(kind != Character.CONTROL && kind != Character.FORMAT && kind != Character.SURROGATE
                        && kind != Character.PRIVATE_USE);
                offset += Character.charCount(code);
            }
            String deliveredAt = stamp(item, "delivered_at"), readAt = stamp(item, "read_at");
            require(readAt == null || deliveredAt != null && readAt.compareTo(deliveredAt) >= 0);
            rows.add(new Row(id, user, name, deliveredAt, readAt));
        }
        long next = number(body.opt("next_after_id"));
        boolean more = (Boolean) body.opt("has_more");
        require(rows.isEmpty() ? next == 0 && !more : next == previous);
        return new Page(expected, eligible, delivered, read, next, more, rows);
    }
    private static String stamp(JSONObject item, String key) {
        require(item.has(key)); Object value = item.opt(key);
        if (value == JSONObject.NULL) return null;
        require(value instanceof String && ((String) value).matches("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"));
        try { LocalDateTime.parse((String) value, UTC); }
        catch (java.time.DateTimeException invalid) { throw new IllegalArgumentException("Invalid receipt timestamp"); }
        return (String) value;
    }
    private static int utf8(String value) {
        require(value != null);
        try {
            ByteBuffer result = StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(value));
            return result.remaining();
        } catch (CharacterCodingException invalid) { throw new IllegalArgumentException("Invalid receipt text"); }
    }
    private static long number(Object value) {
        require((value instanceof Integer || value instanceof Long) && ((Number) value).longValue() >= 0
                && ((Number) value).longValue() <= MAX_ID);
        return ((Number) value).longValue();
    }
    private static long positive(Object value) { long result = number(value); require(result > 0); return result; }
    private static boolean validId(long value) { return value > 0 && value <= MAX_ID; }
    private static void require(boolean ok) { if (!ok) throw new IllegalArgumentException("Invalid receipt details response"); }
    private ReceiptDetailsProtocol() { }
}

package com.baseer.freshchat;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Map;

/** Versioned presentation metadata only. These hashes never authorize a room. */
final class NotificationPresentation {
    static final int MAX_DATA_BYTES = 3072;
    static final long MAX_SENT_AT_MS = 253402300799999L;
    private static final String UUID = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
    private static final String HASH = "[0-9a-f]{64}";
    final String account, roomKey, messageKey, senderKey, sender, title, preview;
    final long sentAt;
    final boolean full, group, attachment;

    private NotificationPresentation(Map<String, String> data, long sentAt) {
        account = data.get("account_key"); roomKey = data.get("room_key");
        messageKey = data.get("message_key"); senderKey = data.get("sender_key");
        sender = clean(data.get("sender_name"), 120); title = clean(data.get("conversation_title"), 120);
        preview = clean(data.get("message_preview"), 160);
        this.sentAt = sentAt; full = data.containsKey("conversation_title");
        group = "true".equals(data.get("is_group"));
        attachment = "attachment".equals(data.get("message_preview_kind"));
    }

    /** Null means conservative generic *silent* fallback, not guessed grouping. */
    static NotificationPresentation parse(Map<String, String> data) {
        try {
            if (data == null || !"chat".equals(data.get("kind")) || !"1".equals(data.get("presentation_v"))
                    || !matches(data.get("account_key"), UUID) || !matches(data.get("room_key"), HASH)
                    || !matches(data.get("message_key"), HASH) || !recordId(data.get("event_id"))
                    || envelopeBytes(data) > MAX_DATA_BYTES) return null;
            String time = data.get("sent_at_ms");
            if (!matches(time, "[1-9][0-9]{0,14}")) return null;
            long at = Long.parseLong(time);
            if (at > MAX_SENT_AT_MS) return null;
            boolean sender = data.containsKey("sender_key"), name = data.containsKey("sender_name");
            boolean title = data.containsKey("conversation_title"), group = data.containsKey("is_group");
            boolean text = data.containsKey("message_preview"), attachment = data.containsKey("message_preview_kind");
            if (sender != name || title != group || title && !sender || (text || attachment) && !title
                    || text && attachment || sender && !matches(data.get("sender_key"), HASH)
                    || name && !bounded(data.get("sender_name"), 120)
                    || title && (!bounded(data.get("conversation_title"), 120)
                    || !("true".equals(data.get("is_group")) || "false".equals(data.get("is_group"))))
                    || text && !bounded(data.get("message_preview"), 160)
                    || attachment && !"attachment".equals(data.get("message_preview_kind"))) return null;
            return new NotificationPresentation(data, at);
        } catch (RuntimeException malformed) { return null; }
    }

    static String roomKey(String account, long company, long room, long recipientMembership) {
        return hash("room", scope(account, company, room, recipientMembership));
    }
    static String messageKey(String account, long company, long room, long recipientMembership, long message) {
        return hash("message", scope(account, company, room, recipientMembership) + "|" + id(message));
    }
    static String senderKey(String account, long company, long room, long recipientMembership, long author) {
        return hash("sender", scope(account, company, room, recipientMembership) + "|" + id(author));
    }
    private static String scope(String account, long company, long room, long membership) {
        if (!matches(account, UUID)) throw new IllegalArgumentException("Registered account UUID required");
        return account + "|" + id(company) + "|" + id(room) + "|" + id(membership);
    }
    private static long id(long value) {
        if (value <= 0 || value > Integer.MAX_VALUE) throw new IllegalArgumentException("Positive record ID required");
        return value;
    }
    private static String hash(String kind, String scope) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(
                    ("bchat-pres-v1|" + kind + "|" + scope).getBytes(StandardCharsets.UTF_8));
            StringBuilder value = new StringBuilder(64);
            for (byte item : bytes) value.append(Character.forDigit((item >>> 4) & 15, 16))
                    .append(Character.forDigit(item & 15, 16));
            return value.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static boolean recordId(String value) {
        return matches(value, "[1-9][0-9]{0,9}") && Long.parseLong(value) <= Integer.MAX_VALUE;
    }
    private static boolean matches(String value, String pattern) { return value != null && value.matches(pattern); }
    private static boolean bounded(String value, int points) {
        return value != null && value.codePointCount(0, value.length()) <= points && quotedBytes(value) <= points * 4L + 2;
    }
    /** Exact compact ensure_ascii=false JSON string byte count, including escaping. */
    static long quotedBytes(String value) {
        if (value == null) throw new IllegalArgumentException("String required");
        long count = 2;
        for (int i = 0; i < value.length();) {
            int point = value.codePointAt(i); i += Character.charCount(point);
            if (point >= 0xd800 && point <= 0xdfff) throw new IllegalArgumentException("Unpaired surrogate");
            count += point == '"' || point == '\\' || point == '\b' || point == '\f'
                    || point == '\n' || point == '\r' || point == '\t' ? 2
                    : point < 32 ? 6 : point < 128 ? 1 : point < 2048 ? 2 : point < 65536 ? 3 : 4;
        }
        return count;
    }
    private static long envelopeBytes(Map<String, String> data) {
        if (data.size() > 32) return Long.MAX_VALUE;
        long count = 2;
        boolean first = true;
        for (Map.Entry<String, String> item : data.entrySet()) {
            count += (first ? 0 : 1) + quotedBytes(item.getKey()) + 1 + quotedBytes(item.getValue());
            first = false;
            if (count > MAX_DATA_BYTES) break;
        }
        return count;
    }
    private static String clean(String raw, int maximum) {
        if (raw == null) return "";
        StringBuilder text = new StringBuilder(); int points = 0;
        for (int offset = 0; offset < raw.length() && points < maximum;) {
            int point = raw.codePointAt(offset); offset += Character.charCount(point);
            int kind = Character.getType(point);
            if (kind == Character.CONTROL || kind == Character.FORMAT
                    || kind == Character.SURROGATE || kind == Character.UNASSIGNED) continue;
            if (Character.isWhitespace(point)) {
                if (text.length() > 0 && text.charAt(text.length() - 1) != ' ') { text.append(' '); ++points; }
            } else { text.appendCodePoint(point); ++points; }
        }
        int end = text.length(); while (end > 0 && text.charAt(end - 1) == ' ') --end;
        return text.substring(0, end);
    }
}

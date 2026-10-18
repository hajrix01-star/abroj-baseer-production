package com.baseer.freshchat.sync;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Strict, metadata-only receipt wire. FCM and mere RAM presence cannot create delivery evidence. */
public final class ReceiptDeliveryProtocol {
    public static boolean supported(JSONObject bootstrap) {
        Object version = bootstrap == null ? null : bootstrap.opt("receipt_delivery_contract_version");
        return version instanceof Number && "1".equals(version.toString());
    }
    public static final class Page {
        public final List<ConnectedHistoryCache.ReceiptWork> refs;
        public final long nextAfterId;
        public final boolean hasMore;
        private Page(List<ConnectedHistoryCache.ReceiptWork> refs, long next, boolean more) {
            this.refs = Collections.unmodifiableList(refs); nextAfterId = next; hasMore = more;
        }
    }
    public static Page pending(JSONObject body, long requestedAfter) throws Exception {
        if (body == null || requestedAfter < 0 || body.toString().getBytes(StandardCharsets.UTF_8).length > 65536
                || number(body.get("api_version"), false) != 2 || !(body.get("has_more") instanceof Boolean))
            throw new IllegalArgumentException("Invalid receipt reference envelope");
        JSONArray rows = body.getJSONArray("refs");
        if (rows.length() > 30) throw new IllegalArgumentException("Receipt page too large");
        List<ConnectedHistoryCache.ReceiptWork> refs = new ArrayList<>();
        Set<String> messages = new HashSet<>();
        long last = requestedAfter;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i);
            if (row.length() != 4) throw new IllegalArgumentException("Receipt reference must contain metadata only");
            long receipt = number(row.get("receipt_id"), true);
            ConnectedHistoryCache.ReceiptWork ref = new ConnectedHistoryCache.ReceiptWork(
                    number(row.get("room_id"), true), number(row.get("membership_id"), true),
                    number(row.get("message_id"), true), receipt, "fetch");
            if (receipt <= last || !messages.add(ref.key())) throw new IllegalArgumentException("Invalid receipt order");
            last = receipt; refs.add(ref);
        }
        long next = number(body.get("next_after_id"), false);
        boolean more = body.getBoolean("has_more");
        if ((refs.isEmpty() && (more || next != 0)) || (!refs.isEmpty() && next != last))
            throw new IllegalArgumentException("Invalid receipt page cursor");
        return new Page(refs, next, more);
    }
    public static void acknowledged(JSONObject body, ConnectedHistoryCache.ReceiptWork work) throws Exception {
        if (body == null || number(body.get("api_version"), false) != 2
                || number(body.get("message_id"), true) != work.messageId)
            throw new IllegalArgumentException("Invalid receipt ACK");
        timestamp(body.get("delivered_at"));
        Object read = body.opt("read_at");
        if ("read".equals(work.kind)) timestamp(read);
        else if (read != null && read != JSONObject.NULL) timestamp(read);
        number(body.get("unread_count"), false); number(body.get("last_message_id"), false);
        if (!(body.get("replayed") instanceof Boolean)) throw new IllegalArgumentException("Invalid receipt replay flag");
    }
    public static long number(Object value, boolean positive) {
        if (!(value instanceof Number) || !value.toString().matches(positive ? "[1-9][0-9]*" : "(?:0|[1-9][0-9]*)"))
            throw new IllegalArgumentException("Invalid receipt integer");
        long number = ((Number)value).longValue();
        if (number < (positive ? 1 : 0) || number > OutboxPolicy.MAX_RECORD_ID)
            throw new IllegalArgumentException("Receipt integer outside bound");
        return number;
    }
    private static void timestamp(Object value) {
        if (!(value instanceof String) || !((String)value).matches("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"))
            throw new IllegalArgumentException("Invalid receipt timestamp");
        try { LocalDateTime.parse(((String)value).replace(' ', 'T'), DateTimeFormatter.ISO_LOCAL_DATE_TIME); }
        catch (java.time.DateTimeException invalid) { throw new IllegalArgumentException("Invalid receipt timestamp", invalid); }
    }
    private ReceiptDeliveryProtocol() { }
}

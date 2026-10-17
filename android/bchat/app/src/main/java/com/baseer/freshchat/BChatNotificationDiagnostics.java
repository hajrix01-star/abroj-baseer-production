package com.baseer.freshchat;

import android.content.Context;
import android.content.SharedPreferences;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Local test-push receipts only. Never message delivery/read ACKs or evidence of hearing a sound. */
final class BChatNotificationDiagnostics {
    static final int MAX_TESTS = 32;
    static final long MAX_AGE_MILLIS = 7L * 24 * 60 * 60 * 1000;
    private static final String PREFS = "bchat-notification-diagnostics-v1";
    private static final Object LOCK = new Object();
    static final class Receipt {
        final String accountKey, eventId, diagnosticUuid, outcome;
        final long receivedAt, displayedAt;
        Receipt(String account, String event, String uuid, long received, long displayed, String outcome) {
            accountKey = account; eventId = event; diagnosticUuid = uuid;
            receivedAt = received; displayedAt = displayed; this.outcome = outcome;
        }
        String encode() { return accountKey + "|" + eventId + "|" + diagnosticUuid + "|"
                + receivedAt + "|" + displayedAt + "|" + outcome; }
    }
    private BChatNotificationDiagnostics() { }
    static boolean valid(String account, String event, String uuid) {
        if (uuid == null || !uuid.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")) return false;
        try { BChatNotificationLedger.key(account, "diagnostic", event); return true; }
        catch (IllegalArgumentException invalid) { return false; }
    }
    static Receipt read(Context context, String account, String event, String uuid, long now) {
        if (!BChatPushState.matches(context, account) || !valid(account, event, uuid)) return null;
        synchronized (LOCK) {
            for (Receipt item : entries(context, now))
                if (item.accountKey.equals(account) && item.eventId.equals(event) && item.diagnosticUuid.equals(uuid)) return item;
            return null;
        }
    }
    /** FCM worker thread; received is recorded before checking presentation permission. */
    static boolean record(Context context, String account, String event, String uuid, String outcome, long now) {
        if (!BChatPushState.matches(context, account) || !valid(account, event, uuid) || now < 0
                || !validOutcome(outcome)) return false;
        synchronized (LOCK) {
            List<Receipt> values = entries(context, now);
            Receipt prior = null;
            for (Receipt item : values) if (item.accountKey.equals(account) && item.eventId.equals(event)
                    && item.diagnosticUuid.equals(uuid)) { prior = item; break; }
            if (prior != null) values.remove(prior);
            long received = prior == null ? now : prior.receivedAt;
            long displayed = prior == null ? 0 : prior.displayedAt;
            if ("displayed".equals(outcome) && displayed == 0) displayed = now;
            String state = displayed > 0 ? "displayed" : "received".equals(outcome) && prior != null ? prior.outcome : outcome;
            values.add(new Receipt(account, event, uuid, received, displayed, state));
            Collections.sort(values, Comparator.comparingLong(item -> item.receivedAt));
            while (values.size() > MAX_TESTS) values.remove(0);
            Set<String> encoded = new HashSet<>();
            for (Receipt item : values) encoded.add(item.encode());
            return prefs(context).edit().putStringSet("receipts", encoded).commit();
        }
    }
    private static boolean validOutcome(String outcome) {
        return "received".equals(outcome) || "displayed".equals(outcome) || "permission_denied".equals(outcome)
                || "channel_blocked".equals(outcome) || "presentation_failed".equals(outcome);
    }
    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
    private static List<Receipt> entries(Context context, long now) {
        List<Receipt> result = new ArrayList<>();
        Set<String> stored;
        try { stored = prefs(context).getStringSet("receipts", Collections.emptySet()); }
        catch (ClassCastException invalid) { return result; }
        if (stored == null) return result;
        for (String encoded : new HashSet<>(stored)) {
            if (encoded == null || encoded.length() > 200) continue;
            String[] parts = encoded.split("\\|", -1);
            if (parts.length != 6 || !valid(parts[0], parts[1], parts[2]) || !validOutcome(parts[5])) continue;
            try {
                long received = Long.parseLong(parts[3]), displayed = Long.parseLong(parts[4]);
                if (received < 0 || displayed < 0 || now >= received && now - received > MAX_AGE_MILLIS) continue;
                if ("displayed".equals(parts[5]) != (displayed > 0)) continue;
                result.add(new Receipt(parts[0], parts[1], parts[2], received, displayed, parts[5]));
            } catch (NumberFormatException invalid) { /* One corrupt receipt does not hide other tests. */ }
        }
        return result;
    }
}

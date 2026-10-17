package com.baseer.freshchat;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Bounded presentation receipts, never authentication or chat-read receipts.
 * Contains only opaque account/event IDs and time, no tokens, names or message text.
 */
final class BChatNotificationLedger {
    static final int MAX_EVENTS = 512;
    static final long MAX_AGE_MILLIS = 7L * 24 * 60 * 60 * 1000;
    private static final String PREFS = "bchat-presented-events-v1";
    private static final String EVENTS = "shown";
    private static final String SOUND_CLAIMS = "sound-claims-v1";
    private static final Object LOCK = new Object();

    private BChatNotificationLedger() { }

    static String key(String account, String kind, String event) {
        if (account == null || !account.matches(
                "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
                || !("chat".equals(kind) || "task".equals(kind) || "order".equals(kind) || "diagnostic".equals(kind))
                || event == null || !event.matches("[1-9][0-9]{0,18}"))
            throw new IllegalArgumentException("Invalid notification identity");
        return account + ":" + kind + ":" + event;
    }

    static boolean contains(Context context, String key, long now) {
        synchronized (LOCK) {
            for (Record item : read(context, now))
                if (item.key.equals(key)) return true;
            return false;
        }
    }

    /** Call only after NotificationManager accepted notify; a failed presentation is not retired. */
    static boolean recordShown(Context context, String key, long now) {
        synchronized (LOCK) {
            List<Record> entries = read(context, now);
            entries.removeIf(item -> item.key.equals(key));
            entries.add(new Record(key, now));
            Collections.sort(entries, Comparator.comparingLong(item -> item.at));
            while (entries.size() > MAX_EVENTS) entries.remove(0);
            Set<String> stored = new HashSet<>();
            for (Record item : entries) stored.add(item.key + "|" + item.at);
            return prefs(context).edit().putStringSet(EVENTS, stored).commit();
        }
    }

    /**
     * Worker-only durable reservation BEFORE any audible effect. The route may
     * subsequently become silent, never switch to a second audible route. No
     * claim is evicted to admit a newer sound; full/corrupt/unwritable is quiet.
     * A crash after this commit may lose a tone, not replay it after restart.
     */
    static boolean claimSound(Context context, String account, String messageKey,
                              long sentAt, long now, String route) {
        if (account == null || !account.matches(
                "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
                || messageKey == null || !messageKey.matches("[0-9a-f]{64}")
                || !("system".equals(route) || "soft".equals(route) || "silent".equals(route))
                || now < 0 || sentAt <= 0 || sentAt > 253402300799999L
                || sentAt > now && sentAt - now > 300000L
                || now >= sentAt && now - sentAt > MAX_AGE_MILLIS) return false;
        synchronized (LOCK) {
            try {
                Set<String> raw = prefs(context).getStringSet(SOUND_CLAIMS, Collections.emptySet());
                if (raw == null || raw.size() > MAX_EVENTS) return false;
                Set<String> retained = new HashSet<>();
                String wanted = account + ":" + messageKey;
                boolean seen = false;
                for (String encoded : new HashSet<>(raw)) {
                    if (encoded == null) return false;
                    String[] parts = encoded.split("\\|", -1);
                    if (parts.length != 3 || !parts[0].matches(
                            "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}:[0-9a-f]{64}")
                            || !parts[1].matches("[0-9]{1,15}")
                            || !("system".equals(parts[2]) || "soft".equals(parts[2]) || "silent".equals(parts[2])))
                        return false;
                    long at = Long.parseLong(parts[1]);
                    if (at > 253402300799999L) return false;
                    // Backward wall-clock movement cannot free an unexpired claim.
                    if (now >= at && now - at > MAX_AGE_MILLIS) continue;
                    retained.add(encoded);
                    if (parts[0].equals(wanted)) seen = true;
                }
                if (seen || retained.size() >= MAX_EVENTS) return false;
                retained.add(wanted + "|" + now + "|" + route);
                return prefs(context).edit().putStringSet(SOUND_CLAIMS, retained).commit();
            } catch (RuntimeException storageUnavailable) {
                return false;
            }
        }
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static List<Record> read(Context context, long now) {
        List<Record> result = new ArrayList<>();
        Set<String> stored;
        try { stored = prefs(context).getStringSet(EVENTS, Collections.emptySet()); }
        catch (ClassCastException invalid) { return result; }
        if (stored == null) return result;
        // Never mutate the set owned by SharedPreferences.
        for (String encoded : new HashSet<>(stored)) {
            if (encoded == null || encoded.length() > 100) continue;
            int separator = encoded.lastIndexOf('|');
            if (separator < 1) continue;
            try {
                String key = encoded.substring(0, separator);
                String[] parts = key.split(":", -1);
                if (parts.length != 3 || !key.equals(key(parts[0], parts[1], parts[2]))) continue;
                long at = Long.parseLong(encoded.substring(separator + 1));
                // A backwards wall-clock adjustment does not invalidate a recent ID.
                if (at < 0 || now >= at && now - at > MAX_AGE_MILLIS) continue;
                result.add(new Record(key, at));
            } catch (IllegalArgumentException invalid) { /* Ignore malformed local receipt only. */ }
        }
        return result;
    }

    private static final class Record {
        final String key;
        final long at;
        Record(String key, long at) { this.key = key; this.at = at; }
    }
}

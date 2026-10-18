package com.baseer.freshchat;

import android.app.NotificationManager;
import android.service.notification.StatusBarNotification;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/** Retracts owned business presentation only, never a transfer/service or demo notification. */
final class BChatNotificationPresentationReset {
    private static final String ACCOUNT = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
    static final int MAX_KNOWN = 512;
    private static final Object LOCK = new Object();
    // Metadata only. Android may not expose a just-enqueued notify in its active-row scan yet.
    private static final LinkedHashMap<String, Integer> KNOWN = new LinkedHashMap<>();

    static boolean owned(String tag, int id) {
        if (tag == null) return false;
        return id == 0 && (tag.matches(ACCOUNT + ":(?:chat|task|order|diagnostic):[1-9][0-9]{0,18}")
                || tag.matches(ACCOUNT + ":bchat-room:[0-9a-f]{64}"))
                || id == 1 && tag.matches(ACCOUNT + ":bchat-summary");
    }

    /**
     * Call immediately before notify, inside the final authenticated presentation gates.
     * A refused admission MUST NOT notify or retire a shown receipt. Lock order ends here:
     * routing -> channel -> conversation -> this metadata lock, never the reverse.
     */
    static boolean posting(NotificationManager manager, String tag, int id) {
        if (manager == null || !owned(tag, id)) return false;
        synchronized (LOCK) {
            if (!KNOWN.containsKey(tag) && KNOWN.size() >= MAX_KNOWN) {
                Map.Entry<String, Integer> oldest = KNOWN.entrySet().iterator().next();
                try { manager.cancel(oldest.getKey(), oldest.getValue()); }
                catch (RuntimeException unavailable) { return false; }
                KNOWN.remove(oldest.getKey()); // Forget only after queuing its exact cancellation.
            }
            KNOWN.remove(tag);
            KNOWN.put(tag, id);
            return true;
        }
    }

    /** Best-effort OS retraction. The caller has already invalidated all RAM snapshots. */
    static void cancel(NotificationManager manager) {
        if (manager == null) return;
        synchronized (LOCK) {
            Iterator<Map.Entry<String, Integer>> pending = KNOWN.entrySet().iterator();
            while (pending.hasNext()) {
                Map.Entry<String, Integer> row = pending.next();
                try {
                    manager.cancel(row.getKey(), row.getValue());
                    pending.remove();
                } catch (RuntimeException unavailable) { /* Retain the key for a later reset. */ }
            }
        }
        try {
            // Prior-process rows have no RAM key. The scan remains necessary, but does not
            // guarantee retraction of a previous process's still-invisible queued Binder post.
            StatusBarNotification[] rows = manager.getActiveNotifications();
            if (rows == null) return;
            for (StatusBarNotification row : rows) {
                if (row == null || !owned(row.getTag(), row.getId())) continue;
                try { manager.cancel(row.getTag(), row.getId()); }
                catch (RuntimeException unavailable) { /* Do not broaden cancellation to unrelated rows. */ }
            }
        } catch (RuntimeException unavailable) {
            // No cancelAll fallback: it could remove an active C09 transfer notification.
        }
    }

    private BChatNotificationPresentationReset() { }
}

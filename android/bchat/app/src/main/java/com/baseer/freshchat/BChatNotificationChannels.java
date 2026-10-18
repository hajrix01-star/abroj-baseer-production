package com.baseer.freshchat;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Looper;

import java.util.Map;

/** Device-wide routing preference, not notification permission or authenticated account state.
 * Platform reads/creation and preference commits are worker-only. The final presentation gate is RAM-only.
 */
public final class BChatNotificationChannels {
    public static final String LEGACY = "bchat-events-v3";
    public static final String CHAT = "bchat-chat-v1";
    public static final String TASKS = "bchat-tasks-v1";
    public static final String ORDERS = "bchat-orders-v1";
    private static final String PREFS = "bchat-notification-channels-v1", SEPARATED = "separated";
    /** No caller may acquire PushState.ROUTING while holding either lock here. */
    private static final Object UPDATE = new Object(), STATE = new Object();
    private static Snapshot current = new Snapshot(false, false, 0);
    private static SharedPreferences preferences;

    public static final class Snapshot {
        public final boolean known, separated;
        public final long revision;
        private Snapshot(boolean known, boolean separated, long revision) {
            this.known = known; this.separated = separated; this.revision = revision;
        }
    }
    public static final class Names {
        public final String chat, tasks, orders;
        public Names(String chat, String tasks, String orders) {
            this.chat = name(chat); this.tasks = name(tasks); this.orders = name(orders);
        }
        private static String name(String value) {
            if (value == null || value.trim().isEmpty() || value.length() > 128
                    || value.indexOf('\n') >= 0 || value.indexOf('\r') >= 0)
                throw new IllegalArgumentException("A localized channel name is required");
            return value;
        }
    }
    public static final class Result {
        public final boolean accepted, changed;
        public final String code;
        public final Snapshot state;
        private Result(boolean accepted, boolean changed, String code, Snapshot state) {
            this.accepted = accepted; this.changed = changed; this.code = code; this.state = state;
        }
    }
    public static final class Selection {
        public final String channelId;
        /** False requires a generic QUIET presentation, even for task/order/diagnostic events. */
        public final boolean known;
        public final long revision;
        private final Snapshot owner;
        private Selection(Snapshot owner, String id, boolean validKind) {
            this.owner = owner; channelId = id; known = owner.known && validKind; revision = owner.revision;
        }
    }

    /** RAM only. Unknown is not an assertion that notifications are enabled or disabled. */
    public static Snapshot state() { synchronized (STATE) { return current; } }

    /** Initialize once off main; failed reads may be retried. Known committed RAM is never reloaded after a failed edit. */
    public static Snapshot load(Context context) {
        worker();
        synchronized (UPDATE) { return loadLocked(context); }
    }
    private static Snapshot loadLocked(Context context) {
        Snapshot before = state();
        if (before.known) return before;
        try {
            SharedPreferences prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            Map<String, ?> values = prefs.getAll();
            if (values == null || values.size() > 1 || values.size() == 1 && !values.containsKey(SEPARATED))
                return before;
            Object stored = values.get(SEPARATED);
            if (values.containsKey(SEPARATED) && !(stored instanceof Boolean)) return before;
            boolean separated = Boolean.TRUE.equals(stored);
            synchronized (STATE) {
                preferences = prefs;
                current = new Snapshot(true, separated, before.revision + 1);
                return current;
            }
        } catch (RuntimeException unavailable) { return before; }
    }

    /** Explicit UI choice only. Root owns confirmation text, account/session UI fencing and quiet rebuild. */
    public static Result setSeparated(Context context, boolean separated, Names names) {
        worker();
        synchronized (UPDATE) {
            Snapshot before = loadLocked(context);
            if (!before.known) return result(false, false, "storage_unavailable", before);
            if (before.separated == separated) return result(true, false, "ok", before);
            if (separated) {
                if (names == null) throw new IllegalArgumentException("Localized channel names required");
                try {
                    NotificationManager manager = context.getApplicationContext().getSystemService(NotificationManager.class);
                    if (manager == null) return result(false, false, "channel_unavailable", before);
                    NotificationChannel baseline = manager.getNotificationChannel(LEGACY);
                    if (baseline == null) return result(false, false, "baseline_missing", before);
                    int importance = baseline.getImportance();
                    if (importance < NotificationManager.IMPORTANCE_NONE || importance > NotificationManager.IMPORTANCE_HIGH)
                        return result(false, false, "channel_unavailable", before);
                    String[] ids = {CHAT, TASKS, ORDERS}, labels = {names.chat, names.tasks, names.orders};
                    for (int i = 0; i < ids.length; i++) {
                        // No setters, renaming, reconfiguration or deletion for a channel that already exists.
                        if (manager.getNotificationChannel(ids[i]) == null)
                            manager.createNotificationChannel(copyBaseline(baseline, ids[i], labels[i]));
                    }
                    for (String id : ids) if (manager.getNotificationChannel(id) == null)
                        return result(false, false, "channel_unavailable", before);
                } catch (RuntimeException unavailable) { return result(false, false, "channel_unavailable", before); }
            }
            boolean saved;
            try { saved = preferences.edit().putBoolean(SEPARATED, separated).commit(); }
            catch (RuntimeException unavailable) { saved = false; }
            // SharedPreferences may already have changed its in-process map even when commit returned false.
            // Retain the previous immutable route and never reload that uncommitted map in this process.
            if (!saved) return result(false, false, "commit_failed", before);
            synchronized (STATE) {
                current = new Snapshot(true, separated, before.revision + 1);
                return result(true, true, "ok", current);
            }
        }
    }

    private static NotificationChannel copyBaseline(NotificationChannel source, String id, String name) {
        NotificationChannel copy = new NotificationChannel(id, name, source.getImportance());
        copy.setSound(source.getSound(), source.getAudioAttributes());
        long[] pattern = source.getVibrationPattern();
        copy.setVibrationPattern(pattern == null ? null : pattern.clone());
        if (Build.VERSION.SDK_INT >= 35) Api35.vibration(source, copy);
        copy.enableVibration(source.shouldVibrate()); // Setters can implicitly enable it; the observed mute wins.
        copy.setShowBadge(source.canShowBadge());
        copy.enableLights(source.shouldShowLights()); copy.setLightColor(source.getLightColor());
        copy.setLockscreenVisibility(source.getLockscreenVisibility() == Notification.VISIBILITY_SECRET
                ? Notification.VISIBILITY_SECRET : Notification.VISIBILITY_PRIVATE);
        copy.setBypassDnd(false); // Never request DND access or inherit a bypass into a new channel.
        return copy;
    }
    private static final class Api35 {
        static void vibration(NotificationChannel source, NotificationChannel target) {
            target.setVibrationEffect(source.getVibrationEffect());
        }
    }
    public static Selection resolve(String kind) {
        synchronized (STATE) {
            boolean valid = "chat".equals(kind) || "task".equals(kind) || "order".equals(kind) || "diagnostic".equals(kind);
            String id = LEGACY;
            if (current.known && current.separated) {
                if ("chat".equals(kind)) id = CHAT;
                else if ("task".equals(kind)) id = TASKS;
                else if ("order".equals(kind)) id = ORDERS;
            }
            return new Selection(current, id, valid);
        }
    }
    /** Atomic check+notify, not check-then-notify. Caller lock order is PushState.ROUTING → STATE only.
     * The action may build/post one already-selected notification, never read disk/create channels/change routing.
     */
    public static boolean present(Selection selection, Runnable action) {
        if (selection == null || action == null) return false;
        synchronized (STATE) {
            if (selection.owner != current) return false;
            action.run(); return true;
        }
    }
    private static Result result(boolean accepted, boolean changed, String code, Snapshot state) {
        return new Result(accepted, changed, code, state);
    }
    private static void worker() {
        if (Looper.myLooper() == Looper.getMainLooper())
            throw new IllegalStateException("Channel storage/platform work must run off main");
    }
    private BChatNotificationChannels() { }
}

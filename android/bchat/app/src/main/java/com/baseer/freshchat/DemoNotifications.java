package com.baseer.freshchat;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;

/** Local, user-triggered demo only. No receiver, alarm, service, network, FCM, or restart replay. */
final class DemoNotifications {
    static final String CATEGORY = LocalSettingsPolicy.CONVERSATIONS;
    static String channelId(Context context) { return new LocalSettings(context).channel(CATEGORY); }
    static final String OPEN_ACTION = "com.baseer.freshchat.OPEN_LOCAL_TEST";
    static final String COMPANY = "notification_company";
    static final String CONVERSATION = "notification_conversation";
    private static final int NOTIFICATION_ID = 701;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static Runnable pending;
    private static int lastResult = R.string.ui_031;
    private static int lastBlocker;

    static NotificationManager manager(Context context) {
        return (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
    }

    static void ensureChannel(Context context) {
        NotificationManager manager = manager(context);
        NotificationChannel existing = manager.getNotificationChannel(channelId(context));
        if (existing != null) {
            existing.setName(AppLocale.s(context, R.string.ui_032));
            existing.setDescription(AppLocale.s(context, R.string.ui_033));
            manager.createNotificationChannel(existing);
            return;
        }
        LocalSettings settings = new LocalSettings(context);
        NotificationChannel channel = new NotificationChannel(channelId(context),
                AppLocale.s(context, R.string.ui_032), NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription(AppLocale.s(context, R.string.ui_033));
        channel.setSound(settings.sound(CATEGORY) ? RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION) : null,
                new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        channel.setVibrationPattern(new long[] {0, 160, 80, 160});
        // Android setVibrationPattern(nonempty) enables vibration; apply the choice last.
        channel.enableVibration(settings.vibration(CATEGORY));
        channel.setLockscreenVisibility(settings.hideLockscreen() ? Notification.VISIBILITY_SECRET : Notification.VISIBILITY_PRIVATE);
        manager.createNotificationChannel(channel);
    }

    static boolean permissionGranted(Context context) {
        return Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED;
    }

    /** Null means posting is allowed; it does not guarantee a sound or heads-up alert. */
    static String postingBlocker(Context context) {
        int blocker = postingBlockerId(context);
        return blocker == 0 ? null : AppLocale.s(context, blocker);
    }

    private static int postingBlockerId(Context context) {
        if (!permissionGranted(context)) return R.string.ui_034;
        if (!manager(context).areNotificationsEnabled()) return R.string.ui_035;
        NotificationChannel channel = manager(context).getNotificationChannel(channelId(context));
        if (channel != null && channel.getImportance() == NotificationManager.IMPORTANCE_NONE)
            return R.string.ui_036;
        return 0;
    }

    static String soundHint(Context context) {
        NotificationChannel channel = manager(context).getNotificationChannel(channelId(context));
        if (channel != null && (channel.getSound() == null || channel.getImportance() < NotificationManager.IMPORTANCE_DEFAULT))
            return AppLocale.s(context, R.string.ui_037);
        return AppLocale.s(context, R.string.ui_038);
    }

    static String status(Context context) {
        return lastBlocker == 0 ? AppLocale.s(context, lastResult)
                : AppLocale.s(context, lastResult, AppLocale.s(context, lastBlocker));
    }
    private static String result(Context context, int message) { lastResult = message; lastBlocker = 0; return status(context); }
    static boolean hasPending() { return pending != null; }

    static void cancel(Context context) {
        if (pending != null) MAIN.removeCallbacks(pending);
        pending = null;
        manager(context).cancel(NOTIFICATION_ID);
        result(context, R.string.ui_039);
    }

    static String start(Context context, NotificationDemoPolicy.Target target) {
        // Every newer explicit test replaces the earlier pending test, even if muted/blocked.
        if (pending != null) MAIN.removeCallbacks(pending);
        pending = null;
        ensureChannel(context);
        if (new LocalSettings(context).mute(target.companyId, target.conversationId)) return result(context, R.string.ui_040);
        int blocker = postingBlockerId(context);
        if (blocker != 0) return result(context, blocker);
        Context app = context.getApplicationContext();
        if (target.delayMillis == NotificationDemoPolicy.IMMEDIATE) return post(app, target);
        pending = () -> {
            pending = null;
            post(app, target);
        };
        MAIN.postDelayed(pending, target.delayMillis);
        return result(context, R.string.ui_041);
    }

    private static String post(Context context, NotificationDemoPolicy.Target target) {
        context = AppLocale.wrap(context);
        if (new LocalSettings(context).mute(target.companyId, target.conversationId)) return result(context, R.string.ui_042);
        ensureChannel(context);
        int blocker = postingBlockerId(context);
        if (blocker != 0) { lastResult = R.string.notification_not_posted; lastBlocker = blocker; return status(context); }
        Intent open = new Intent(context, MainActivity.class)
                .setAction(OPEN_ACTION)
                .setData(new Uri.Builder().scheme("baseer-demo").authority("local-test")
                        .appendPath(target.companyId).appendPath(target.conversationId).build())
                .putExtra(COMPANY, target.companyId).putExtra(CONVERSATION, target.conversationId)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent tap = PendingIntent.getActivity(context, NOTIFICATION_ID, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(context, channelId(context))
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(AppLocale.s(context, R.string.ui_044))
                .setContentText(AppLocale.s(context, R.string.ui_045))
                .setStyle(new Notification.BigTextStyle().bigText(AppLocale.s(context, R.string.ui_046)))
                .setCategory(Notification.CATEGORY_STATUS)
                .setVisibility(new LocalSettings(context).hideLockscreen() ? Notification.VISIBILITY_SECRET : Notification.VISIBILITY_PRIVATE)
                .setLocalOnly(true).setAutoCancel(true).setOnlyAlertOnce(false)
                .setContentIntent(tap).build();
        try {
            manager(context).notify(NOTIFICATION_ID, notification);
            return result(context, R.string.ui_047);
        } catch (SecurityException denied) {
            return result(context, R.string.ui_048);
        }
    }

    /** Rename existing channels and refresh a visible demo silently; never replay a test. */
    static void refreshLanguage(Context source) {
        Context context = AppLocale.wrap(source.getApplicationContext());
        NotificationManager manager = manager(context);
        for (NotificationChannel channel : manager.getNotificationChannels()) {
            if (!channel.getId().startsWith("bchat_local_v2_" + CATEGORY + "_")) continue;
            channel.setName(AppLocale.s(context, R.string.ui_032));
            channel.setDescription(AppLocale.s(context, R.string.ui_033));
            manager.createNotificationChannel(channel);
        }
        if (!permissionGranted(context)) return;
        for (android.service.notification.StatusBarNotification visible : manager.getActiveNotifications()) {
            if (visible.getId() != NOTIFICATION_ID) continue;
            Notification updated = Notification.Builder.recoverBuilder(context, visible.getNotification())
                    .setContentTitle(AppLocale.s(context, R.string.ui_044))
                    .setContentText(AppLocale.s(context, R.string.ui_045))
                    .setStyle(new Notification.BigTextStyle().bigText(AppLocale.s(context, R.string.ui_046)))
                    .setOnlyAlertOnce(true).build();
            try { manager.notify(NOTIFICATION_ID, updated); } catch (SecurityException denied) { }
        }
    }

    static Intent settings(Context context, boolean channel) {
        channel = channel && permissionGranted(context) && manager(context).areNotificationsEnabled();
        Intent intent = new Intent(channel ? Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS
                : Settings.ACTION_APP_NOTIFICATION_SETTINGS);
        intent.putExtra(Settings.EXTRA_APP_PACKAGE, context.getPackageName());
        if (channel) intent.putExtra(Settings.EXTRA_CHANNEL_ID, channelId(context));
        return intent;
    }
}

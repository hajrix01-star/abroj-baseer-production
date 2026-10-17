package com.baseer.freshchat;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.media.AudioAttributes;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.provider.Settings;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/** Optional FCM source, excluded from builds without google-services.json. */
public final class BChatFirebaseMessagingService extends FirebaseMessagingService {
    // Android preserves a channel's sound choice.  A new ID is required to
    // repair installs whose older v2 channel was created silently.
    private static final String CHANNEL = "bchat-events-v3";

    @Override public void onNewToken(String token) {
        BChatPushState.token(this, token);
        // The authenticated activity observes the pending token and registers it with Odoo.
    }

    @Override public void onMessageReceived(RemoteMessage message) {
        if (!BChatPushState.awaitReady(this, 3000)) return;
        Map<String, String> data = message.getData();
        String account = data.get("account_key");
        String kind = data.get("kind");
        String event = data.get("event_id");
        boolean diagnostic = "diagnostic".equals(kind);
        String diagnosticUuid = diagnostic ? data.get("diagnostic_uuid") : null;
        if (!BChatPushState.matches(this, account)
                || !("chat".equals(kind) || "task".equals(kind) || "order".equals(kind) || diagnostic)
                || event == null || !event.matches("[1-9][0-9]{0,18}")) return;
        if (diagnostic && !BChatNotificationDiagnostics.valid(account, event, diagnosticUuid)) return;
        BChatPushState.Delivery delivery = BChatPushState.delivery(this, account);
        if (delivery == null) return;
        if (diagnostic) BChatNotificationDiagnostics.record(this, account, event, diagnosticUuid,
                "received", System.currentTimeMillis());
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            if (diagnostic) BChatNotificationDiagnostics.record(this, account, event, diagnosticUuid,
                    "permission_denied", System.currentTimeMillis());
            return;
        }

        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) return;
        String presentationKey = BChatNotificationLedger.key(account, kind, event);
        if (BChatNotificationLedger.contains(this, presentationKey, System.currentTimeMillis())) return;
        ensureChannel(manager);
        NotificationChannel channel = manager.getNotificationChannel(CHANNEL);
        if (!manager.areNotificationsEnabled() || channel != null && channel.getImportance() == NotificationManager.IMPORTANCE_NONE) {
            if (diagnostic) BChatNotificationDiagnostics.record(this, account, event, diagnosticUuid,
                    "channel_blocked", System.currentTimeMillis());
            return;
        }
        Intent intent = new Intent(this, OdooIdentityActivity.class);
        intent.setAction(Intent.ACTION_VIEW);
        intent.setData(android.net.Uri.parse("bchat://notification/" + account + "/" + kind + "/" + event));
        intent.putExtra(BChatPushState.EXTRA_ACCOUNT_KEY, account);
        intent.putExtra(BChatPushState.EXTRA_KIND, kind);
        intent.putExtra(BChatPushState.EXTRA_EVENT_ID, event);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        // Extras select a candidate only. The authenticated endpoint rechecks current access.
        PendingIntent open = PendingIntent.getActivity(this, (account + ":" + kind + ":" + event).hashCode(),
                intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        int textId = "chat".equals(kind) ? R.string.bchat_push_chat
                : "task".equals(kind) ? R.string.bchat_push_task
                : diagnostic ? R.string.bchat_push_diagnostic : R.string.bchat_push_order;
        // A tag avoids hash collisions, and onlyAlertOnce also protects the short
        // crash window after notify but before the durable presentation receipt.
        try {
            boolean posted = BChatPushState.present(delivery, mode -> {
                String sender = "chat".equals(kind) && !"none".equals(mode) ? notificationText(data.get("sender_name"), 120) : "";
                String preview = "chat".equals(kind) && "full".equals(mode) ? notificationText(data.get("message_preview"), 160) : "";
                if ("chat".equals(kind) && "full".equals(mode) && preview.isEmpty()
                        && "attachment".equals(data.get("message_preview_kind")))
                    preview = getString(R.string.bchat_push_attachment);
                Notification publicView = new Notification.Builder(this, CHANNEL)
                        .setSmallIcon(R.drawable.ic_notification).setContentTitle("BChat")
                        .setContentText(getString(textId)).setVisibility(Notification.VISIBILITY_PUBLIC).build();
                Notification.Builder builder = new Notification.Builder(this, CHANNEL)
                        .setSmallIcon(R.drawable.ic_notification)
                        .setContentTitle(sender.isEmpty() ? "BChat" : sender)
                        .setContentText(preview.isEmpty() ? getString(textId) : preview)
                        .setContentIntent(open).setAutoCancel(true).setOnlyAlertOnce(true)
                        .setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(publicView)
                        .setCategory("chat".equals(kind) ? Notification.CATEGORY_MESSAGE : Notification.CATEGORY_REMINDER);
                if (!preview.isEmpty()) builder.setStyle(new Notification.BigTextStyle().bigText(preview));
                // The final account/intent ceiling check and notify share the same short RAM lock.
                manager.notify(presentationKey, 0, builder.build());
            });
            if (!posted) return;
            if (diagnostic) BChatNotificationDiagnostics.record(this, account, event, diagnosticUuid,
                    "displayed", System.currentTimeMillis());
            BChatNotificationLedger.recordShown(this, presentationKey, System.currentTimeMillis());
        } catch (SecurityException revoked) {
            // Android permission may have changed since the check above. Do not retire the event.
            if (diagnostic) BChatNotificationDiagnostics.record(this, account, event, diagnosticUuid,
                    "presentation_failed", System.currentTimeMillis());
        }
    }

    private void ensureChannel(NotificationManager manager) {
        NotificationChannel channel = new NotificationChannel(CHANNEL, "BChat",
                NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription(getString(R.string.bchat_push_channel_description));
        channel.enableVibration(true);
        channel.setVibrationPattern(new long[]{0, 160, 100, 160});
        channel.setSound(Settings.System.DEFAULT_NOTIFICATION_URI,
                new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION).build());
        channel.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);
        manager.createNotificationChannel(channel);
    }

    /** Do not let a malformed push create bidi/control tricks or split surrogate pairs. */
    private static String notificationText(String raw, int maximum) {
        if (raw == null || raw.isEmpty()) return "";
        StringBuilder clean = new StringBuilder();
        for (int offset = 0; offset < raw.length() && clean.codePointCount(0, clean.length()) < maximum;) {
            int point = raw.codePointAt(offset);
            offset += Character.charCount(point);
            int type = Character.getType(point);
            if (type == Character.CONTROL || type == Character.FORMAT
                    || type == Character.SURROGATE || type == Character.UNASSIGNED) continue;
            if (Character.isWhitespace(point)) {
                if (clean.length() > 0 && clean.charAt(clean.length() - 1) != ' ') clean.append(' ');
            } else clean.appendCodePoint(point);
        }
        int last = clean.length();
        while (last > 0 && clean.charAt(last - 1) == ' ') last--;
        return clean.substring(0, last);
    }
}

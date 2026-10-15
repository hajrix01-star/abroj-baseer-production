package com.baseer.freshchat;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/** Optional FCM source, excluded from builds without google-services.json. */
public final class BChatFirebaseMessagingService extends FirebaseMessagingService {
    private static final String CHANNEL = "bchat-events-v2";

    @Override public void onNewToken(String token) {
        BChatPushState.token(this, token);
        // The authenticated activity observes the pending token and registers it with Odoo.
    }

    @Override public void onMessageReceived(RemoteMessage message) {
        Map<String, String> data = message.getData();
        String account = data.get("account_key");
        String kind = data.get("kind");
        String event = data.get("event_id");
        if (!BChatPushState.matches(this, account)
                || !("chat".equals(kind) || "task".equals(kind) || "order".equals(kind))
                || event == null || !event.matches("[1-9][0-9]{0,18}")) return;
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) return;

        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) return;
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "BChat",
                NotificationManager.IMPORTANCE_HIGH));
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
                : "task".equals(kind) ? R.string.bchat_push_task : R.string.bchat_push_order;
        Notification shown = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle("BChat")
                .setContentText(getString(textId))
                .setContentIntent(open)
                .setAutoCancel(true)
                .setVisibility(Notification.VISIBILITY_SECRET)
                .build();
        manager.notify((kind + ":" + event).hashCode(), shown);
    }
}

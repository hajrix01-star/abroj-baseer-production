package com.baseer.freshchat;

import android.app.Notification;
import android.app.Person;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.drawable.Icon;
import android.os.Build;
import java.util.HashMap;
import java.util.Map;

/**
 * Renders an already privacy-projected, immutable RAM window. Never posts a notification.
 * The caller still owns the current account/privacy/channel gates, public generic version,
 * small brand icon, intent and alert flags. A snapshot is not an authorization capability.
 *
 * Each call constructs a NEW Builder: a downgrade must never reuse a rich Builder or its
 * style extras. Only this factory owns its private title/text/style; callers must not later
 * replace those with an unprojected frame. No avatar lookup, disk/network, URI, shortcut,
 * remote input or sound belongs here. MessagingStyle alone does not grant a Conversations
 * section, bubbles or priority-conversation eligibility.
 */
final class BChatMessagingNotificationStyle {
    static final int INITIALS_SIZE = 64;
    private static final String BRAND = "BChat";

    static Notification.Builder create(Context context, String channelId,
            BChatNotificationConversations.Conversation conversation) {
        Notification.Builder builder = new Notification.Builder(context, channelId)
                .setContentTitle(BRAND).setContentText(context.getString(R.string.bchat_push_chat));
        if (!named(conversation)) return builder;

        boolean full = "full".equals(conversation.mode);
        BChatNotificationConversations.Message latest = conversation.messages.get(conversation.messages.size() - 1);
        builder.setContentTitle(full && !conversation.title.isEmpty() ? conversation.title : sender(latest))
                .setContentText(body(context, latest, full)).setWhen(latest.sentAt);
        if (Build.VERSION.SDK_INT >= 28) {
            Api28.apply(context, builder, conversation, full);
        } else {
            legacy(context, builder, conversation, full);
        }
        return builder;
    }

    private static boolean named(BChatNotificationConversations.Conversation value) {
        return value != null && ("sender".equals(value.mode) || "full".equals(value.mode))
                && !value.messages.isEmpty()
                && value.messages.size() <= BChatNotificationConversations.MAX_MESSAGES;
    }

    private static String sender(BChatNotificationConversations.Message message) {
        return message.sender.isEmpty() ? BRAND : message.sender;
    }

    private static String body(Context context, BChatNotificationConversations.Message message, boolean full) {
        if (!full) return context.getString(R.string.bchat_push_chat);
        if (message.attachment) return context.getString(R.string.bchat_push_attachment);
        return message.text.isEmpty() ? context.getString(R.string.bchat_push_chat) : message.text;
    }

    @SuppressWarnings("deprecation")
    private static void legacy(Context context, Notification.Builder builder,
            BChatNotificationConversations.Conversation conversation, boolean full) {
        Notification.MessagingStyle style = new Notification.MessagingStyle((CharSequence) BRAND);
        // API26/27 infer group status from a non-null conversation title. Do not label a
        // sender-only frame or a named direct conversation as a group on that platform.
        if (full && conversation.group) style.setConversationTitle(
                conversation.title.isEmpty() ? BRAND : conversation.title);
        for (BChatNotificationConversations.Message message : conversation.messages) {
            style.addMessage(body(context, message, full), message.sentAt, (CharSequence) sender(message));
        }
        builder.setStyle(style);
    }

    /** Keep all API28 Person references off the API26/27 execution path. */
    private static final class Api28 {
        static void apply(Context context, Notification.Builder builder,
                BChatNotificationConversations.Conversation conversation, boolean full) {
            Notification.MessagingStyle style = new Notification.MessagingStyle(
                    new Person.Builder().setName(BRAND).build())
                    .setGroupConversation(full && conversation.group);
            if (full && !conversation.title.isEmpty()) style.setConversationTitle(conversation.title);
            // At most five derived icons per construction. This map is local, not an avatar
            // cache; neither sender names nor bitmaps survive in an application registry.
            Map<String, Person> people = new HashMap<>();
            for (BChatNotificationConversations.Message message : conversation.messages) {
                Person person = people.get(message.senderKey);
                if (person == null) {
                    String name = sender(message);
                    person = new Person.Builder().setName(name).setKey(message.senderKey)
                            .setIcon(Icon.createWithBitmap(initials(context, name))).build();
                    people.put(message.senderKey, person);
                }
                style.addMessage(body(context, message, full), message.sentAt, person);
            }
            builder.setStyle(style);
        }

        private static Bitmap initials(Context context, String name) {
            Bitmap bitmap = Bitmap.createBitmap(INITIALS_SIZE, INITIALS_SIZE, Bitmap.Config.ARGB_8888);
            Canvas canvas = new Canvas(bitmap);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            // The same context-resolved semantic accent resource used by UiPalette.
            paint.setColor(context.getColor(R.color.bchat_accent));
            canvas.drawCircle(INITIALS_SIZE / 2f, INITIALS_SIZE / 2f, INITIALS_SIZE / 2f, paint);
            paint.setColor(Color.WHITE);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setTextSize(INITIALS_SIZE / 2f);
            String text = AvatarInitials.of(name);
            float width = paint.measureText(text), maximum = INITIALS_SIZE * .75f;
            if (width > maximum) paint.setTextSize(paint.getTextSize() * maximum / width);
            float baseline = INITIALS_SIZE / 2f - (paint.ascent() + paint.descent()) / 2f;
            canvas.drawText(text, INITIALS_SIZE / 2f, baseline, paint);
            // The Person Icon owns this bitmap; recycling it would invalidate the built
            // Notification before the caller serializes it to Android.
            return bitmap;
        }
    }

    private BChatMessagingNotificationStyle() { }
}

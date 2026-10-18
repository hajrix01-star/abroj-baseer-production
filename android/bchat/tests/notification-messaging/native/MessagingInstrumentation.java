package com.baseer.freshchat;

import android.app.Instrumentation;
import android.app.Notification;
import android.app.Person;
import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.os.Bundle;
import android.os.Parcel;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Actual SDK35 Builder/Person/Canvas/Icon/Parcel. Never notifies or creates a channel. */
public final class MessagingInstrumentation extends Instrumentation {
    private int checks, cases;
    private final JSONArray results = new JSONArray();
    private void check(boolean value, String why) {
        ++checks; if (!value) throw new AssertionError("Check " + checks + ": " + why);
    }
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context base = getContext();
            if (!"com.baseer.bchat.notification.messaging.test".equals(base.getPackageName()))
                throw new IllegalStateException("Refusing non-test package");
            check(Build.VERSION.SDK_INT == 35, "Evidence is explicitly Android35");
            for (String language : new String[]{"ar", "en"}) {
                for (boolean dark : new boolean[]{false, true}) {
                    Configuration config = new Configuration(base.getResources().getConfiguration());
                    config.setLocale(new Locale(language));
                    config.uiMode = (config.uiMode & ~Configuration.UI_MODE_NIGHT_MASK)
                            | (dark ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
                    Context context = base.createConfigurationContext(config);
                    matrix(context, language + "/" + (dark ? "dark" : "light"));
                }
            }
            JSONObject evidence = new JSONObject().put("schema", 1).put("passed", true)
                    .put("sdk", Build.VERSION.SDK_INT).put("assertions", checks).put("cases", cases)
                    .put("configurations", 4).put("samples", results)
                    .put("scope", "Actual SDK35 built/parcelled Notification and Person bitmap; no notification posted, no channel/audio/FCM/OEM/API26 runtime/product Activity");
            try (FileOutputStream out = new FileOutputStream(new File(base.getFilesDir(), "messaging-results.json"))) {
                out.write(evidence.toString(2).getBytes(StandardCharsets.UTF_8));
            }
            result.putString("stream", "PASS " + checks + " actual Android35 MessagingStyle assertions; "
                    + cases + " construction cases across 4 configurations; no notify/audio/FCM/OEM\n");
            finish(0, result);
        } catch (Throwable failure) {
            result.putString("stream", "FAIL " + failure + " " + Arrays.toString(failure.getStackTrace()) + "\n");
            finish(1, result);
        }
    }

    private void matrix(Context context, String config) throws Exception {
        for (String available : new String[]{"none", "sender", "full"}) {
            for (String ceiling : new String[]{"none", "sender", "full"}) {
                BChatNotificationConversations.Conversation input = MessagingCases.conversation(
                        available, ceiling, true, 7, true, true, false);
                namedOrGeneric(context, input, config + "/" + available + "/" + ceiling);
            }
        }
        namedOrGeneric(context, MessagingCases.conversation("full", "full", false, 1, false, false, false), config + "/direct");
        namedOrGeneric(context, MessagingCases.conversation("full", "full", true, 1, false, false, true), config + "/empty-name");
        namedOrGeneric(context, null, config + "/invalid-generic");
        // A previously rich Builder remains separate; no downgrade shares style or extras.
        Notification.Builder rich = BChatMessagingNotificationStyle.create(context, "test-channel",
                MessagingCases.conversation("full", "full", true, 2, true, false, false));
        Notification.Builder generic = BChatMessagingNotificationStyle.create(context, "test-channel",
                MessagingCases.conversation("full", "none", true, 2, true, false, false));
        check(rich != generic && rich.getStyle() != null && generic.getStyle() == null, "Construction-level freshness");
        check(!generic.getExtras().containsKey(Notification.EXTRA_MESSAGES), "Fresh downgrade has no old messages");
    }

    private void namedOrGeneric(Context context, BChatNotificationConversations.Conversation input, String label) throws Exception {
        ++cases;
        Notification.Builder builder = BChatMessagingNotificationStyle.create(context, "test-channel", input);
        Notification notification = builder.setSmallIcon(R.drawable.ic_notification).build();
        check("test-channel".equals(notification.getChannelId()), "Channel is caller-owned");
        check(notification.getSmallIcon().getResId() == R.drawable.ic_notification, "Unchanged brand icon");
        check(notification.sound == null && notification.vibrate == null && notification.defaults == 0, "No audio mutation");
        check(notification.actions == null || notification.actions.length == 0, "No RemoteInput/actions");
        check(notification.getShortcutId() == null && notification.getBubbleMetadata() == null, "No shortcut/bubble eligibility claim");
        check(notification.getLargeIcon() == null, "No fetched/private avatar");
        check(notification.contentIntent == null && notification.fullScreenIntent == null, "Intent is caller-owned");
        check(!notification.extras.containsKey(Notification.EXTRA_PEOPLE_LIST), "No additional people registry");
        // Android Parcel is exercised, not an object-map approximation of framework extras.
        Parcel parcel = Parcel.obtain();
        Notification restored;
        try {
            notification.writeToParcel(parcel, 0); parcel.setDataPosition(0);
            restored = Notification.CREATOR.createFromParcel(parcel);
        } finally { parcel.recycle(); }
        check(restored.getChannelId().equals(notification.getChannelId()), "Parcel channel roundtrip");
        boolean named = input != null && !"none".equals(input.mode);
        if (!named) {
            check(builder.getStyle() == null, "None/invalid is not MessagingStyle");
            for (String key : new String[]{Notification.EXTRA_MESSAGES, Notification.EXTRA_HISTORIC_MESSAGES,
                    Notification.EXTRA_MESSAGING_PERSON, Notification.EXTRA_CONVERSATION_TITLE,
                    Notification.EXTRA_IS_GROUP_CONVERSATION, Notification.EXTRA_PEOPLE_LIST})
                check(!restored.extras.containsKey(key), "Generic excludes " + key);
            check("BChat".contentEquals(restored.extras.getCharSequence(Notification.EXTRA_TITLE)), "Generic brand only");
            check(context.getString(R.string.bchat_push_chat).contentEquals(restored.extras.getCharSequence(Notification.EXTRA_TEXT)), "Generic localized body only");
        } else {
            boolean full = "full".equals(input.mode);
            Notification.MessagingStyle style = (Notification.MessagingStyle) builder.getStyle();
            check(style != null && "BChat".contentEquals(style.getUser().getName()), "Generic self Person");
            check(style.getUser().getKey() == null && style.getUser().getUri() == null && style.getUser().getIcon() == null, "Self contains no account profile");
            check(style.isGroupConversation() == (full && input.group), "Group is full only");
            check(style.getConversationTitle() == null ? !full : full && input.title.contentEquals(style.getConversationTitle()), "Title is full only");
            Person self = restored.extras.getParcelable(Notification.EXTRA_MESSAGING_PERSON, Person.class);
            check(self != null && "BChat".contentEquals(self.getName()), "Parcel stores generic self Person");
            check(restored.extras.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION) == (full && input.group), "Parcel group flag");
            List<Notification.MessagingStyle.Message> messages = Notification.MessagingStyle.Message.getMessagesFromBundleArray(
                    restored.extras.getParcelableArray(Notification.EXTRA_MESSAGES));
            check(messages.size() == input.messages.size() && messages.size() <= 5, "Bounded native message window");
            check(style.getHistoricMessages().isEmpty(), "No hidden historic/private messages");
            String previousKey = null;
            for (int i = 0; i < messages.size(); ++i) {
                BChatNotificationConversations.Message expected = input.messages.get(i);
                Notification.MessagingStyle.Message actual = messages.get(i);
                String text = !full ? context.getString(R.string.bchat_push_chat) : expected.attachment
                        ? context.getString(R.string.bchat_push_attachment) : expected.text.isEmpty()
                        ? context.getString(R.string.bchat_push_chat) : expected.text;
                check(text.contentEquals(actual.getText()), "Allowed localized body " + i);
                check(expected.sentAt == actual.getTimestamp(), "Canonical timestamp not retry/current time " + i);
                check(actual.getDataMimeType() == null && actual.getDataUri() == null, "Attachment is text only, no URI " + i);
                Person person = actual.getSenderPerson();
                check(person != null && expected.senderKey.equals(person.getKey()), "Stable sender hash not display-name identity " + i);
                check((expected.sender.isEmpty() ? "BChat" : expected.sender).contentEquals(person.getName()), "Allowed sender name " + i);
                check(person.getUri() == null && !person.isBot() && !person.isImportant(), "No external identity/importance " + i);
                Icon icon = person.getIcon();
                check(icon != null && icon.getType() == Icon.TYPE_BITMAP, "Derived bitmap only " + i);
                Drawable drawable = icon.loadDrawable(context);
                check(drawable instanceof BitmapDrawable, "Actual native Icon resolves " + i);
                Bitmap bitmap = ((BitmapDrawable) drawable).getBitmap();
                check(bitmap.getWidth() == 64 && bitmap.getHeight() == 64 && !bitmap.isRecycled(), "Fixed live bitmap " + i);
                check(Color.alpha(bitmap.getPixel(0, 0)) == 0, "Round initials background " + i);
                check(bitmap.getPixel(32, 5) == context.getColor(R.color.bchat_accent), "Context semantic brand color " + i);
                if (previousKey != null && expected.sender.equals(input.messages.get(i - 1).sender))
                    check(!previousKey.equals(person.getKey()), "Same display names retain distinct sender keys");
                previousKey = person.getKey();
            }
        }
        results.put(new JSONObject().put("case", label).put("messages", named ? input.messages.size() : 0)
                .put("mode", input == null ? "invalid" : input.mode).put("passed", true));
    }
}

package com.baseer.freshchat;

import android.app.Notification;
import android.content.Context;
import android.os.Build;

/** Production factory exercised with explicit API sentinels; not an API26 device claim. */
public final class LegacyMessagingHarness {
    private static int checks;
    private static void check(boolean value, String why) {
        ++checks; if (!value) throw new AssertionError("Check " + checks + ": " + why);
    }
    public static void main(String[] args) {
        Context context = new Context();
        for (int api : new int[]{26, 27}) {
            Build.VERSION.SDK_INT = api;
            for (String available : new String[]{"none", "sender", "full"}) {
                for (String ceiling : new String[]{"none", "sender", "full"}) {
                    BChatNotificationConversations.Conversation input = MessagingCases.conversation(
                            available, ceiling, true, 7, true, true, false);
                    Notification.Builder builder = BChatMessagingNotificationStyle.create(context, "caller-channel", input);
                    check(builder.channel.equals("caller-channel"), "Caller channel retained");
                    if ("none".equals(input.mode)) {
                        check(builder.style == null && builder.title.equals("BChat")
                                && builder.text.equals("New message in BChat"), "Generic has no style/name/title/text");
                    } else {
                        boolean full = "full".equals(input.mode);
                        check(builder.style.user.equals("BChat"), "Generic self name");
                        check(full ? MessagingCases.TITLE.contentEquals(builder.style.title) : builder.style.title == null,
                                "Only full group gets legacy title/group inference");
                        check(builder.style.messages.size() == 5, "Five-message window");
                        for (int i = 0; i < builder.style.messages.size(); ++i) {
                            BChatNotificationConversations.Message expected = input.messages.get(i);
                            Notification.MessagingStyle.Message actual = builder.style.messages.get(i);
                            String text = !full ? "New message in BChat" : expected.attachment
                                    ? "Sent an attachment" : expected.text;
                            check(text.contentEquals(actual.text), "Projection body");
                            check(expected.sender.contentEquals(actual.sender), "Safe CharSequence sender");
                            check(expected.sentAt == actual.at, "Canonical timestamp");
                        }
                    }
                    check(builder != BChatMessagingNotificationStyle.create(context, "caller-channel", input), "Fresh Builder every call");
                }
            }
            Notification.Builder direct = BChatMessagingNotificationStyle.create(context, "x",
                    MessagingCases.conversation("full", "full", false, 1, false, false, false));
            check(direct.style.title == null, "Legacy direct message never inferred as group");
            Notification.Builder empty = BChatMessagingNotificationStyle.create(context, "x",
                    MessagingCases.conversation("sender", "sender", false, 1, false, false, true));
            check(empty.style.messages.get(0).sender.equals("BChat"), "Empty safe name uses brand fallback");
            Notification.Builder invalid = BChatMessagingNotificationStyle.create(context, "x", null);
            check(invalid.style == null && invalid.text.equals("New message in BChat"), "Invalid snapshot generic only");
        }
        System.out.println("PASS " + checks + " production renderer assertions with explicit API26/27 boundary adapters; no actual API26/27 runtime");
    }
}

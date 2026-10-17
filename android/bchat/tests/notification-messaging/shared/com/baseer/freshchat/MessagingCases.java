package com.baseer.freshchat;

import java.util.HashMap;
import java.util.Map;

/** Test input only. Both parser and bounded immutable projection are production classes. */
final class MessagingCases {
    static final String ACCOUNT = "00000000-0000-4000-8000-000000000001";
    static final String NAME = "سارة Same Sender";
    static final String TITLE = "فريق Private Team";
    static final String TEXT = "نص Private Preview ";
    static final long BASE_TIME = 1729200000000L;

    static BChatNotificationConversations.Conversation conversation(String available, String ceiling,
            boolean group, int count, boolean sameNames, boolean attachmentLast, boolean emptyName) {
        BChatNotificationConversations.reset();
        BChatNotificationConversations.Conversation result = null;
        for (int i = 1; i <= count; ++i) {
            Map<String, String> data = new HashMap<>();
            data.put("kind", "chat"); data.put("account_key", ACCOUNT);
            data.put("event_id", String.valueOf(i)); data.put("presentation_v", "1");
            data.put("room_key", NotificationPresentation.roomKey(ACCOUNT, 7, 19, 23));
            data.put("message_key", NotificationPresentation.messageKey(ACCOUNT, 7, 19, 23, i));
            data.put("sent_at_ms", String.valueOf(BASE_TIME + i));
            if (!"none".equals(available)) {
                data.put("sender_key", NotificationPresentation.senderKey(ACCOUNT, 7, 19, 23, 100 + i % 2));
                data.put("sender_name", emptyName ? "" : sameNames ? NAME : NAME + i % 2);
            }
            if ("full".equals(available)) {
                data.put("conversation_title", TITLE); data.put("is_group", String.valueOf(group));
                if (attachmentLast && i == count) data.put("message_preview_kind", "attachment");
                else data.put("message_preview", TEXT + i);
            }
            NotificationPresentation frame = NotificationPresentation.parse(data);
            if (frame == null) throw new AssertionError("Malformed test frame " + i);
            result = BChatNotificationConversations.append(frame, ceiling).conversation;
        }
        return result;
    }
    private MessagingCases() { }
}

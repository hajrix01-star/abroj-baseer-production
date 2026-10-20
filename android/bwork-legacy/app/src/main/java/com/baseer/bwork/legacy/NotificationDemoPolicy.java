package com.baseer.bwork.legacy;

/** Pure policy for an explicit, one-shot local notification test. It does not schedule anything. */
public final class NotificationDemoPolicy {
    public static final int IMMEDIATE = 0;
    public static final int DELAYED = 10000;
    private NotificationDemoPolicy() { }

    public static Target target(ChatStore store, String companyId, String conversationId, int delayMillis) {
        if (delayMillis != IMMEDIATE && delayMillis != DELAYED) {
            throw new IllegalArgumentException("Only immediate or ten-second demo tests are supported");
        }
        ChatStore.Company company = store.company(companyId);
        ChatStore.Conversation conversation = store.conversation(companyId, conversationId);
        return new Target(company.id, company.name, conversation.id, conversation.title, delayMillis);
    }

    public static boolean needsRuntimePermission(int androidApi, boolean granted) {
        return androidApi >= 33 && !granted;
    }

    public static final class Target {
        public final String companyId, companyName, conversationId, conversationTitle;
        public final int delayMillis;
        private Target(String companyId, String companyName, String conversationId,
                       String conversationTitle, int delayMillis) {
            this.companyId = companyId;
            this.companyName = companyName;
            this.conversationId = conversationId;
            this.conversationTitle = conversationTitle;
            this.delayMillis = delayMillis;
        }
    }
}

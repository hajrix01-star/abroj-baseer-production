package com.baseer.bwork.legacy;

/** Keys remain scoped to both company and chat; local choices do not grant server permissions. */
public final class LocalSettingsPolicy {
    public static final String CONVERSATIONS = "conversations", PURCHASES = "purchases", TASKS = "tasks";
    public static void category(String value) {
        if (!CONVERSATIONS.equals(value) && !PURCHASES.equals(value) && !TASKS.equals(value)) throw new IllegalArgumentException("Unknown category");
    }
    public static String muteKey(String company, String chat) {
        if (company == null || company.isEmpty() || chat == null || chat.isEmpty()) throw new IllegalArgumentException("Scope required");
        return "mute:" + company.length() + ":" + company + ":" + chat;
    }
    public static String channel(String category, boolean sound, boolean vibration, boolean hidden) {
        category(category);
        return "bwork_local_v2_" + category + "_" + (sound ? "s" : "q") + (vibration ? "v" : "n") + (hidden ? "h" : "p");
    }
}

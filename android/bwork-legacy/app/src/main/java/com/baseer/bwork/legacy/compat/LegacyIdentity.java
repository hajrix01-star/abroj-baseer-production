package com.baseer.bwork.legacy.compat;
/** Bounded compatibility projection of mobile/bwork/compatibility/identities.json.
 * These are installed data/intent/serialization identities, never a second engine. */
public final class LegacyIdentity {
    private LegacyIdentity() { }
    public static final String PUSH = "bchat-push-v1";
    public static final String SETTINGS = "bchat-local-settings-v1";
    public static final String EDITOR_RECOVERY = "bchat-editor-recovery-v1";
    public static final String CHANGE_CURSOR = "bchat-change-cursor-v1";
    public static final String EMPLOYEE_AUTH = "bchat-employee-auth-v1";
    public static final String TASK_PENDING = "bchat-task-create-pending-v1";
    public static final String ORDER_PENDING = "bchat-order-create-pending-v1";
    public static final String ORDER_COMPANY = "bchat-order-company-v1";
    public static final String RECEIPT_PENDING = "bchat-receipt-confirm-pending-v1";
    public static final String RECEIPT_SHARE = "bchat-receipt-share-pending-v1";
    public static final String GROUP_PENDING = "bchat-group-create-pending-v1";
    public static final String PERMISSIONS = "bchat-permissions-v1";
    public static final String ORDER_PERMISSIONS = "bchat-order-permissions-v1";
    public static final String TEXT_OUTBOX = "bchat-v2-text-outbox.db";
    public static final String HISTORY = "bchat-v2-history-v1.db";
    public static final String MEDIA_DIRECTORY = "bchat-v2-media";
    public static final String MEDIA_READ_DIRECTORY = "bchat-v2-media-read";
    public static final String OUTBOX = "bchat-authenticated-outbox.db";
    public static final String TASKS = "bchat-v2-tasks-v1.db";
    public static final String PUSH_EVENT = "com.baseer.bchat.PUSH_EVENT_ID";
    public static final String PUSH_ACCOUNT = "com.baseer.bchat.PUSH_ACCOUNT_KEY";
    public static final String PUSH_KIND = "com.baseer.bchat.PUSH_KIND";
    public static final String SERIALIZATION_DOMAIN = "com.baseer.freshchat.ChatStore$";
    public static final String CANONICAL_DOMAIN = "com.baseer.bwork.legacy.ChatStore$";
    public static String canonicalClass(String name) {
        return name.startsWith(SERIALIZATION_DOMAIN) ? CANONICAL_DOMAIN + name.substring(SERIALIZATION_DOMAIN.length()) : name;
    }
    public static String wireClass(String name) {
        return name.startsWith(CANONICAL_DOMAIN) ? SERIALIZATION_DOMAIN + name.substring(CANONICAL_DOMAIN.length()) : name;
    }
    public static String wireType(String name) {
        return name.replace(CANONICAL_DOMAIN.replace('.', '/'), SERIALIZATION_DOMAIN.replace('.', '/'));
    }
}

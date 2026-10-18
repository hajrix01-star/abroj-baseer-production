package com.baseer.freshchat;

import com.baseer.freshchat.sync.AccountScope;
import org.json.JSONObject;

/** Response-object boundary checks, not HTTP, Android JSON parsing or FCM delivery. */
public final class NotificationSettingsProtocolTest {
    private static int checks;
    private interface Invalid { void run() throws Exception; }
    private static void check(boolean value) { if (!value) throw new AssertionError("notification protocol"); ++checks; }
    private static void rejected(Invalid action) throws Exception {
        try { action.run(); } catch (IllegalArgumentException expected) { ++checks; return; }
        throw new AssertionError("invalid notification response accepted");
    }
    private static JSONObject binding(String account, String installation) throws Exception {
        return new JSONObject().put("api_version", 2).put("account_key", account)
                .put("installation_id", installation).put("registration_active", true);
    }
    private static JSONObject preferences(String account, String installation) throws Exception {
        return binding(account, installation).put("preview_mode", "none").put("revision", 21);
    }
    private static JSONObject test(String account, String installation, String uuid) throws Exception {
        return binding(account, installation).put("configuration_ready", true)
                .put("test", new JSONObject().put("event_id", 17).put("diagnostic_uuid", uuid)
                        .put("state", "pending").put("provider_accepted_at", JSONObject.NULL));
    }
    static void run(AccountScope scope, String account, String installation, BChatPushState.PreviewControl control) throws Exception {
        JSONObject bootstrap = new JSONObject().put("api_version", 2).put("user_id", scope.userId).put("database", scope.database);
        check(!NotificationSettingsProtocol.capabilities(bootstrap, scope).preferences);
        bootstrap.put("notification_preferences_version", 1).put("notification_diagnostics_version", 1);
        check(NotificationSettingsProtocol.capabilities(bootstrap, scope).preferences
                && NotificationSettingsProtocol.capabilities(bootstrap, scope).diagnostics);
        bootstrap.put("notification_preferences_version", 2);
        check(!NotificationSettingsProtocol.capabilities(bootstrap, scope).preferences);
        for (Object invalid : new Object[]{2.0, true, "2", JSONObject.NULL})
            rejected(() -> NotificationSettingsProtocol.capabilities(bootstrap.put("api_version", invalid), scope));
        bootstrap.put("api_version", 2).put("user_id", scope.userId + 1);
        rejected(() -> NotificationSettingsProtocol.capabilities(bootstrap, scope));
        bootstrap.put("user_id", scope.userId).put("database", "different_database");
        rejected(() -> NotificationSettingsProtocol.capabilities(bootstrap, scope));
        check(NotificationSettingsProtocol.preferences(preferences(account, installation), account, installation).revision == 21);
        for (Object invalid : new Object[]{0, -1, 2.0, true, "21", JSONObject.NULL, (long) Integer.MAX_VALUE})
            rejected(() -> NotificationSettingsProtocol.preferences(
                    preferences(account, installation).put("revision", invalid), account, installation));
        rejected(() -> NotificationSettingsProtocol.preferences(
                preferences(account, installation).put("account_key", "00000000-0000-4000-8000-000000000099"), account, installation));
        rejected(() -> NotificationSettingsProtocol.preferences(
                preferences(account, installation).put("installation_id", "00000000-0000-4000-8000-000000000099"), account, installation));
        rejected(() -> NotificationSettingsProtocol.preferences(
                preferences(account, installation).put("registration_active", false), account, installation));
        rejected(() -> NotificationSettingsProtocol.preferences(
                preferences(account, installation).put("preview_mode", "unrestricted"), account, installation));
        JSONObject accepted = preferences(account, installation).put("client_uuid", control.clientUuid)
                .put("operation_revision", control.expectedRevision + 1).put("replayed", false);
        check(NotificationSettingsProtocol.accepted(accepted, control).mode.equals(control.mode));
        accepted.put("replayed", true);
        check(NotificationSettingsProtocol.accepted(accepted, control).revision == 21);
        rejected(() -> NotificationSettingsProtocol.accepted(accepted.put("operation_revision", 22), control));
        accepted.put("operation_revision", 21);
        rejected(() -> NotificationSettingsProtocol.accepted(accepted.put("client_uuid", installation), control));
        accepted.put("client_uuid", control.clientUuid);
        rejected(() -> NotificationSettingsProtocol.accepted(accepted.put("preview_mode", "full"), control));
        accepted.put("preview_mode", control.mode);
        rejected(() -> NotificationSettingsProtocol.accepted(accepted.put("replayed", "true"), control));
        accepted.put("replayed", true).put("revision", 22).put("preview_mode", "full");
        check(NotificationSettingsProtocol.accepted(accepted, control).revision == 22);
        rejected(() -> NotificationSettingsProtocol.accepted(accepted.put("replayed", false), control));
        accepted.put("replayed", true).put("revision", 21);
        rejected(() -> NotificationSettingsProtocol.accepted(accepted, control));
        String uuid = "00000000-0000-4000-8000-000000000088";
        check(!NotificationSettingsProtocol.test(test(account, installation, uuid), account, installation, uuid, 0).providerAccepted);
        JSONObject delivered = test(account, installation, uuid);
        delivered.getJSONObject("test").put("state", "sent").put("provider_accepted_at", "2026-10-17T12:30:00Z");
        check(NotificationSettingsProtocol.test(delivered, account, installation, uuid, 17).providerAccepted);
        rejected(() -> NotificationSettingsProtocol.test(delivered, account, installation, uuid, 18));
        delivered.getJSONObject("test").put("provider_accepted_at", JSONObject.NULL);
        rejected(() -> NotificationSettingsProtocol.test(delivered, account, installation, uuid, 17));
        delivered.getJSONObject("test").put("provider_accepted_at", "2026-99-99T99:99:99Z");
        rejected(() -> NotificationSettingsProtocol.test(delivered, account, installation, uuid, 17));
        for (Object invalid : new Object[]{true, 17, "visible", JSONObject.NULL}) {
            JSONObject invalidState = test(account, installation, uuid);
            invalidState.getJSONObject("test").put("state", invalid);
            rejected(() -> NotificationSettingsProtocol.test(invalidState, account, installation, uuid, 17));
        }
        JSONObject quota = new JSONObject().put("api_version", 2).put("error",
                new JSONObject().put("code", "rate_limited").put("retry_after_seconds", 60));
        check(NotificationSettingsProtocol.retryAfter(quota) == 60);
        for (Object invalid : new Object[]{0, -1, 60.0, "60", true, JSONObject.NULL}) {
            quota.getJSONObject("error").put("retry_after_seconds", invalid);
            check(NotificationSettingsProtocol.retryAfter(quota) == 0);
        }
        quota.getJSONObject("error").put("code", "private detail with spaces");
        check(NotificationSettingsProtocol.errorCode(quota) == null);
        System.out.println("PASS " + checks + " notification response-object checks; declared JSONObject adapter, not HTTP/parser/FCM");
    }
    private NotificationSettingsProtocolTest() { }
}

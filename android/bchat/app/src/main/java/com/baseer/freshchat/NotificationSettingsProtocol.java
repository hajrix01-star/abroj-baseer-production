package com.baseer.freshchat;

import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.OutboxPolicy;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONObject;

/** Strict settings response boundary. Routing IDs are not authentication. */
final class NotificationSettingsProtocol {
    static final String PREFERENCES = "/bchat/api/v2/notifications/preferences";
    static final String TEST = "/bchat/api/v2/notifications/test";
    private static final Set<String> TEST_STATES = new HashSet<>(Arrays.asList(
            "pending", "retry", "configuration", "sent", "discarded", "failed"));

    static final class Capabilities {
        final boolean preferences, diagnostics;
        Capabilities(boolean preferences, boolean diagnostics) {
            this.preferences = preferences; this.diagnostics = diagnostics;
        }
    }
    static final class Preferences {
        final String mode;
        final long revision;
        Preferences(String mode, long revision) { this.mode = mode; this.revision = revision; }
    }
    static final class TestResult {
        final long eventId;
        final String diagnosticUuid, state;
        final boolean configurationReady, providerAccepted;
        TestResult(long event, String uuid, String state, boolean configured, boolean accepted) {
            eventId = event; diagnosticUuid = uuid; this.state = state;
            configurationReady = configured; providerAccepted = accepted;
        }
    }

    static Capabilities capabilities(JSONObject body, AccountScope account) {
        api(body);
        require(account != null && positive(body.opt("user_id")) == account.userId
                && account.database.equals(body.opt("database")));
        return new Capabilities(version(body, "notification_preferences_version"),
                version(body, "notification_diagnostics_version"));
    }
    private static boolean version(JSONObject body, String key) {
        if (!body.has(key)) return false;
        return integer(body.opt(key)) && ((Number) body.opt(key)).longValue() == 1;
    }
    static Preferences preferences(JSONObject body, String account, String installation) {
        binding(body, account, installation);
        Object mode = body.opt("preview_mode");
        require(mode instanceof String && ("none".equals(mode) || "sender".equals(mode) || "full".equals(mode)));
        long revision = positive(body.opt("revision"));
        require(revision < Integer.MAX_VALUE);
        return new Preferences((String) mode, revision);
    }
    static Preferences accepted(JSONObject body, BChatPushState.PreviewControl request) {
        require(request != null);
        Preferences result = preferences(body, request.accountKey, request.installationId);
        long operationRevision = positive(body.opt("operation_revision"));
        require(request.clientUuid.equals(body.opt("client_uuid")) && body.opt("replayed") instanceof Boolean
                && operationRevision == request.expectedRevision + 1 && result.revision >= operationRevision
                && (result.revision == operationRevision ? result.mode.equals(request.mode) : Boolean.TRUE.equals(body.opt("replayed"))));
        return result;
    }
    static TestResult test(JSONObject body, String account, String installation, String uuid, long eventId) {
        binding(body, account, installation);
        require(validUuid(uuid) && body.opt("configuration_ready") instanceof Boolean);
        JSONObject test = body.optJSONObject("test");
        require(test != null && uuid.equals(test.opt("diagnostic_uuid")));
        long receivedId = positive(test.opt("event_id"));
        require(eventId == 0 || eventId == receivedId);
        Object state = test.opt("state");
        require(state instanceof String && TEST_STATES.contains(state));
        Object accepted = test.opt("provider_accepted_at");
        require(test.has("provider_accepted_at") && (accepted == JSONObject.NULL || stamp(accepted)));
        require("sent".equals(state) == (accepted != JSONObject.NULL));
        return new TestResult(receivedId, uuid, (String) state,
                (Boolean) body.opt("configuration_ready"), accepted != JSONObject.NULL);
    }
    static String errorCode(JSONObject body) {
        if (body == null || !integer(body.opt("api_version")) || ((Number) body.opt("api_version")).longValue() != 2)
            return null;
        JSONObject error = body.optJSONObject("error");
        Object code = error == null ? null : error.opt("code");
        return code instanceof String && ((String) code).matches("[a-z_]{1,64}") ? (String) code : null;
    }
    static long retryAfter(JSONObject body) {
        if (!"rate_limited".equals(errorCode(body))) return 0;
        try { return positive(body.getJSONObject("error").opt("retry_after_seconds")); }
        catch (Exception invalid) { return 0; }
    }
    private static void binding(JSONObject body, String account, String installation) {
        api(body);
        require(validUuid(account) && validUuid(installation) && account.equals(body.opt("account_key"))
                && installation.equals(body.opt("installation_id")) && Boolean.TRUE.equals(body.opt("registration_active")));
    }
    private static void api(JSONObject body) {
        require(body != null && integer(body.opt("api_version"))
                && ((Number) body.opt("api_version")).longValue() == 2 && !body.has("error"));
    }
    private static boolean stamp(Object value) {
        if (!(value instanceof String) || !((String) value).matches(
                "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")) return false;
        try { java.time.Instant.parse((String) value); return true; }
        catch (java.time.format.DateTimeParseException invalid) { return false; }
    }
    private static boolean integer(Object value) { return value instanceof Integer || value instanceof Long; }
    private static long positive(Object value) {
        require(integer(value) && ((Number) value).longValue() > 0
                && ((Number) value).longValue() <= OutboxPolicy.MAX_RECORD_ID);
        return ((Number) value).longValue();
    }
    private static boolean validUuid(String value) {
        return value != null && value.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
    }
    private static void require(boolean ok) { if (!ok) throw new IllegalArgumentException("Invalid notification settings response"); }
    private NotificationSettingsProtocol() { }
}

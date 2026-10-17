package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Bundle;
import android.view.WindowManager;
import android.widget.TextView;
import com.baseer.freshchat.sync.AccountScope;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.json.JSONObject;

/** Actual Android host Activity; intentionally not OdooIdentityActivity or a network/FCM test. */
public final class NotificationSettingsTestActivity extends Activity {
    static final AccountScope ACCOUNT = new AccountScope("https://notification-settings.invalid", "isolated_notifications", 7);
    static final String ACCOUNT_KEY = "51f11a36-e86d-4ce0-844e-3c82503f08b8";
    static String language = "ar";
    static boolean dark, supported = true;
    static float scale = 1;
    BChatNotificationSettingsPanel panel;
    FakeHost host;

    @Override protected void attachBaseContext(Context base) {
        Configuration config = new Configuration(base.getResources().getConfiguration());
        Locale locale = Locale.forLanguageTag(language);
        config.setLocale(locale); config.setLayoutDirection(locale);
        config.fontScale = scale;
        config.uiMode = (config.uiMode & ~Configuration.UI_MODE_NIGHT_MASK)
                | (dark ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
        // Only this test Activity: 320px emulator -> approximately 360 logical dp. No wm mutation.
        config.densityDpi = Math.round(base.getResources().getDisplayMetrics().widthPixels * 160f / 360f);
        config.screenWidthDp = 360; config.smallestScreenWidthDp = 360;
        super.attachBaseContext(base.createConfigurationContext(config));
    }
    @Override public void onCreate(Bundle state) {
        setTheme(ChatAppearance.themeResource(this)); super.onCreate(state);
        TextView root = new TextView(this); root.setText("Isolated notification settings component test");
        root.setBackgroundColor(UiPalette.canvas(this)); setContentView(root);
        NotificationChannel quiet = new NotificationChannel("bchat-events-v3", "Isolated quiet channel",
                NotificationManager.IMPORTANCE_LOW);
        quiet.setSound(null, null);
        getSystemService(NotificationManager.class).createNotificationChannel(quiet);
        host = new FakeHost(this, supported);
        panel = new BChatNotificationSettingsPanel(this, host); panel.show();
        AlertDialog dialog = NotificationSettingsInstrumentation.field(panel, "dialog", AlertDialog.class);
        dialog.getWindow().setLayout(getResources().getDisplayMetrics().widthPixels, WindowManager.LayoutParams.WRAP_CONTENT);
    }
    @Override protected void onPause() { if (panel != null) panel.pause(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (panel != null) panel.resume(); }
    @Override protected void onDestroy() { if (panel != null) panel.dismiss(); super.onDestroy(); }

    /** All HTTP-shaped replies below are explicit fakes. Android JSON/preferences/dialog are production. */
    static final class FakeHost implements BChatNotificationSettingsPanel.Host {
        final Activity activity;
        final boolean supported;
        final List<JSONObject> posts = new ArrayList<>();
        String mode = "full", diagnosticUuid;
        long revision = 1;
        int bootstrapCalls, preferenceCalls, testCalls, statusCalls, registerCalls;
        boolean loseNextAck, holdNextAck;
        BChatNotificationSettingsPanel.Reply heldReply;
        JSONObject heldBody;
        FakeHost(Activity activity, boolean supported) { this.activity = activity; this.supported = supported; }
        public AccountScope account() { return ACCOUNT; }
        public boolean current(AccountScope value) { return value != null && ACCOUNT.key.equals(value.key); }
        public boolean bootstrap(BChatNotificationSettingsPanel.Reply reply) {
            bootstrapCalls++;
            JSONObject response = json().put("api_version", 2).put("user_id", ACCOUNT.userId).put("database", ACCOUNT.database).value;
            if (supported) put(response, "notification_preferences_version", 1, "notification_diagnostics_version", 1);
            reply.complete(200, response); return true;
        }
        JSONObject preferences() {
            return json().put("api_version", 2).put("account_key", ACCOUNT_KEY)
                    .put("installation_id", BChatPushState.installationId(activity)).put("registration_active", true)
                    .put("preview_mode", mode).put("revision", revision).value;
        }
        public boolean preferences(String installation, BChatNotificationSettingsPanel.Reply reply) {
            preferenceCalls++; reply.complete(200, preferences()); return true;
        }
        public boolean setPreferences(JSONObject payload, BChatNotificationSettingsPanel.Reply reply) {
            try { posts.add(new JSONObject(payload.toString())); }
            catch (Exception error) { throw new AssertionError(error); }
            boolean replay = payload.optLong("expected_revision") != revision;
            if (!replay) { mode = payload.optString("preview_mode"); revision++; }
            JSONObject response = preferences();
            put(response, "client_uuid", payload.optString("client_uuid"), "operation_revision", payload.optLong("expected_revision") + 1,
                    "replayed", replay);
            if (holdNextAck) { holdNextAck = false; heldReply = reply; heldBody = response; }
            else if (loseNextAck) { loseNextAck = false; reply.complete(0, null); }
            else reply.complete(200, response);
            return true;
        }
        JSONObject diagnostic() {
            JSONObject response = preferences();
            put(response, "configuration_ready", true, "replayed", false, "test", json().put("event_id", 901)
                    .put("diagnostic_uuid", diagnosticUuid).put("state", "sent")
                    .put("provider_accepted_at", "2026-10-17T12:00:00Z").value);
            return response;
        }
        public boolean test(JSONObject payload, BChatNotificationSettingsPanel.Reply reply) {
            testCalls++; diagnosticUuid = payload.optString("client_uuid"); reply.complete(200, diagnostic()); return true;
        }
        public boolean testStatus(long event, String installation, BChatNotificationSettingsPanel.Reply reply) {
            statusCalls++; reply.complete(200, diagnostic()); return true;
        }
        public void registerPush() { registerCalls++; }
        public void requestPermission() { /* No system mutation from fake host. */ }
        public void openSystemSettings(boolean channel) { /* No navigation outside test package. */ }
    }
    private static Builder json() { return new Builder(); }
    private static void put(JSONObject object, Object... pairs) {
        try { for (int index = 0; index < pairs.length; index += 2) object.put((String) pairs[index], pairs[index + 1]); }
        catch (Exception error) { throw new AssertionError(error); }
    }
    private static final class Builder {
        final JSONObject value = new JSONObject();
        Builder put(String key, Object item) { NotificationSettingsTestActivity.put(value, key, item); return this; }
    }
}

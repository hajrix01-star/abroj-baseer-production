package com.baseer.freshchat;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;
import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.BChatStorageRepository;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;
import org.json.JSONObject;

/** A bounded, foreground-only settings view. Never creates messages/tasks or message ACKs. */
final class BChatNotificationSettingsPanel implements SharedPreferences.OnSharedPreferenceChangeListener {
    interface Reply { void complete(int status, JSONObject body); }
    interface Host {
        AccountScope account();
        boolean current(AccountScope scope);
        boolean bootstrap(Reply callback);
        boolean preferences(String installation, Reply callback);
        boolean setPreferences(JSONObject payload, Reply callback);
        boolean test(JSONObject payload, Reply callback);
        boolean testStatus(long eventId, String installation, Reply callback);
        void registerPush();
        void requestPermission();
        void openSystemSettings(boolean channel);
    }
    private static final String CHANNEL = "bchat-events-v3";
    private final Activity activity;
    private final Host host;
    private final AccountScope scope;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final TextView deviceStatus, serverStatus, privacyStatus, testStatus, notice;
    private final Button refresh, retry, runTest, permission;
    private final RadioGroup modes;
    private final AlertDialog dialog;
    private String accountKey, installation, testUuid;
    private long testEventId, lastCheckAt;
    private int generation, pollAttempts;
    private boolean paused, closed, busy, drawing, readingLocal;
    private NotificationSettingsProtocol.Capabilities capabilities;
    private NotificationSettingsProtocol.Preferences serverPreferences;
    private BChatPushState.PreviewRequest preferenceSnapshot;
    private NotificationSettingsProtocol.TestResult test;
    private BChatNotificationDiagnostics.Receipt localReceipt;
    private final Runnable poll = this::pollTest;

    BChatNotificationSettingsPanel(Activity activity, Host host) {
        this.activity = activity; this.host = host; scope = host.account();
        LinearLayout content = column(0);
        content.setPadding(Ui.dp(activity, 20), Ui.dp(activity, 8), Ui.dp(activity, 20), Ui.dp(activity, 8));
        LinearLayout device = section(content, R.string.notification_device_section);
        deviceStatus = body(device);
        permission = action(device, R.string.bchat_notifications_enable, () -> host.requestPermission());
        action(device, R.string.bchat_notifications_manage, () -> host.openSystemSettings(false));
        action(device, R.string.notification_channel_settings, () -> host.openSystemSettings(true));
        LinearLayout server = section(content, R.string.notification_server_section);
        serverStatus = body(server);
        refresh = action(server, R.string.notification_refresh, this::refresh);
        LinearLayout privacy = section(content, R.string.notification_privacy_section);
        privacyStatus = body(privacy);
        modes = new RadioGroup(activity);
        modes.setOrientation(LinearLayout.VERTICAL);
        modes.setLayoutDirection(AppLocale.direction(activity));
        String[] values = {"none", "sender", "full"};
        int[] labels = {R.string.notification_preview_none, R.string.notification_preview_sender, R.string.notification_preview_full};
        for (int i = 0; i < values.length; i++) {
            RadioButton radio = new RadioButton(activity);
            radio.setId(View.generateViewId()); radio.setTag(values[i]); radio.setText(labels[i]);
            radio.setTextSize(Ui.CHAT_BODY_SP); radio.setSingleLine(false);
            radio.setTextColor(UiPalette.foreground(activity, Ui.INK));
            radio.setTextDirection(AppLocale.textDirection(activity)); radio.setLayoutDirection(AppLocale.direction(activity));
            radio.setMinHeight(Ui.dp(activity, Ui.ACTION_TOUCH_DP));
            radio.setPaddingRelative(Ui.dp(activity, 8), Ui.dp(activity, 8), Ui.dp(activity, 8), Ui.dp(activity, 8));
            modes.addView(radio, new RadioGroup.LayoutParams(-1, -2));
        }
        privacy.addView(modes, new LinearLayout.LayoutParams(-1, -2));
        modes.setOnCheckedChangeListener((group, checked) -> {
            if (drawing) return;
            View radio = group.findViewById(checked);
            if (radio != null && radio.getTag() instanceof String) choose((String) radio.getTag());
        });
        retry = action(privacy, R.string.notification_retry_choice, this::retryChoice);
        LinearLayout diagnostic = section(content, R.string.notification_test_section);
        testStatus = body(diagnostic);
        runTest = action(diagnostic, R.string.notification_test_start, this::startTest);
        notice = body(content);
        notice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        ScrollView scroll = new ScrollView(activity);
        scroll.setFillViewport(false); scroll.addView(content);
        dialog = new AlertDialog.Builder(activity).setTitle(R.string.bchat_notifications)
                .setView(scroll).setNegativeButton(R.string.task_close, null).create();
        dialog.setOnDismissListener(ignored -> close());
    }
    void show() {
        if (scope == null || !host.current(scope)) return;
        dialog.show(); BChatPushState.observe(activity, this);
        host.registerPush(); draw(); refresh();
    }
    void pause() { paused = true; main.removeCallbacks(poll); }
    void resume() {
        if (closed) return;
        paused = false;
        if (!current()) { dialog.dismiss(); return; }
        draw(); readLocal();
        if (testEventId > 0 && pollAttempts < 10) schedulePoll();
    }
    void dismiss() { dialog.dismiss(); close(); }
    private void close() {
        if (closed) return;
        closed = true; ++generation; main.removeCallbacks(poll);
        BChatPushState.stopObserving(activity, this);
    }
    private boolean current() { return !closed && dialog.isShowing() && host.current(scope); }
    private boolean visible(int expected) { return current() && !paused && expected == generation; }
    private boolean bindingCurrent(String key, String install) {
        return BChatPushState.matches(activity, key) && install != null && install.equals(BChatPushState.installationId(activity));
    }
    @Override public void onSharedPreferenceChanged(SharedPreferences ignored, String key) {
        if (!current()) { if (!closed) dialog.dismiss(); return; }
        draw();
    }
    private void refresh() {
        refresh(false);
    }
    private void refresh(boolean preserveNotice) {
        if (!current() || paused || busy) return;
        if (!preserveNotice) notice.setText("");
        host.registerPush();
        accountKey = BChatPushState.accountKey(activity); installation = BChatPushState.installationId(activity);
        if (!bindingCurrent(accountKey, installation)) { notice(R.string.notification_registration_pending); draw(); return; }
        busy = true; int request = ++generation; main.removeCallbacks(poll); pollAttempts = 0;
        capabilities = null; serverPreferences = null; preferenceSnapshot = null;
        draw();
        boolean started = host.bootstrap((status, body) -> {
            if (!visible(request)) { busy = false; return; }
            try {
                if (status != 200) throw new IllegalArgumentException();
                capabilities = NotificationSettingsProtocol.capabilities(body, scope);
                lastCheckAt = System.currentTimeMillis(); busy = false;
                if (capabilities.preferences) loadPreferences(request, preserveNotice);
                else { notice(R.string.notification_unsupported); draw(); readLocal(); schedulePoll(); }
            } catch (Exception invalid) { busy = false; notice(R.string.notification_check_unknown); draw(); }
        });
        if (!started) { busy = false; notice(R.string.notification_service_busy); draw(); }
    }
    private void loadPreferences(int request, boolean preserveNotice) {
        final String key = accountKey, install = installation;
        BChatPushState.PreviewRequest snapshot = BChatPushState.previewRequest(activity, key);
        if (snapshot == null || !visible(request) || !bindingCurrent(key, install)) { draw(); return; }
        busy = true; draw();
        boolean started = host.preferences(install, (status, body) -> {
            if (!visible(request) || !bindingCurrent(key, install)) { busy = false; return; }
            busy = false;
            try {
                if (status != 200 || !BChatPushState.currentPreviewRequest(snapshot)) throw new IllegalArgumentException();
                serverPreferences = NotificationSettingsProtocol.preferences(body, key, install);
                preferenceSnapshot = snapshot; lastCheckAt = System.currentTimeMillis();
                BChatPushState.acceptPreviewMode(activity, snapshot, serverPreferences.mode, serverPreferences.revision,
                        (accepted, durable) -> { if (visible(request)) draw(); });
                if (!preserveNotice) notice.setText("");
            } catch (Exception invalid) { notice(R.string.notification_check_unknown); }
            draw(); readLocal(); schedulePoll();
        });
        if (!started) { busy = false; notice(R.string.notification_service_busy); draw(); }
    }
    private void choose(String mode) {
        if (!current() || paused || busy || serverPreferences == null || preferenceSnapshot == null
                || capabilities == null || !capabilities.preferences) { draw(); return; }
        busy = true; notice(R.string.notification_saving_choice); draw();
        BChatPushState.beginPreviewControl(activity, preferenceSnapshot, mode, serverPreferences.revision,
                (ticket, durable) -> {
                    if (ticket == null || !durable) {
                        busy = false; if (current()) { notice(R.string.notification_choice_disk_failed); draw(); } return;
                    }
                    sendChoice(ticket);
                });
    }
    private void retryChoice() {
        if (!current() || paused || busy || capabilities == null || !capabilities.preferences
                || serverPreferences == null || !bindingCurrent(accountKey, installation)) return;
        busy = true; notice(R.string.notification_saving_choice); draw();
        BChatPushState.retryPreviewControl(activity, accountKey, (ticket, durable) -> {
            if (ticket == null || !durable) {
                busy = false; if (current()) { notice(R.string.notification_choice_disk_failed); draw(); } return;
            }
            sendChoice(ticket);
        });
    }
    private void sendChoice(BChatPushState.PreviewControl ticket) {
        // The durable operation survives dismissal. An authenticated matching ACK may settle
        // it even when its view is gone; a pause never starts a new HTTP request.
        if (!current() || paused || !BChatPushState.currentPreviewControl(ticket)) {
            busy = false; if (current()) draw(); return;
        }
        try {
            JSONObject payload = new JSONObject().put("api_version", 2).put("installation_id", ticket.installationId)
                    .put("account_key", ticket.accountKey).put("client_uuid", ticket.clientUuid)
                    .put("expected_revision", ticket.expectedRevision).put("preview_mode", ticket.mode);
            boolean started = host.setPreferences(payload, (status, body) -> {
                if (status == 200) {
                    try {
                        NotificationSettingsProtocol.Preferences accepted = NotificationSettingsProtocol.accepted(body, ticket);
                        boolean superseded = accepted.revision > ticket.expectedRevision + 1;
                        BChatPushState.acceptPreviewControl(activity, ticket, accepted.mode, accepted.revision,
                                ticket.expectedRevision + 1, Boolean.TRUE.equals(body.opt("replayed")), (ok, durable) -> {
                                    busy = false;
                                    if (!current()) return;
                                    notice(ok && durable ? superseded ? R.string.notification_choice_superseded
                                            : R.string.notification_choice_saved : R.string.notification_choice_unconfirmed);
                                    serverPreferences = null; preferenceSnapshot = null;
                                    if (!paused) refresh(true); else draw();
                                });
                        return;
                    } catch (Exception invalid) { /* Preserve the operation when the response is not authoritative. */ }
                } else if (status == 409 && "revision_conflict".equals(NotificationSettingsProtocol.errorCode(body))) {
                    BChatPushState.rejectPreviewControl(activity, ticket, (ok, durable) -> {
                        busy = false;
                        if (!current()) return;
                        notice(R.string.notification_choice_conflict);
                        serverPreferences = null; preferenceSnapshot = null;
                        if (!paused) refresh(true); else draw();
                    });
                    return;
                }
                busy = false;
                if (current()) { notice(R.string.notification_choice_unconfirmed); draw(); }
            });
            if (!started) { busy = false; notice(R.string.notification_service_busy); draw(); }
        } catch (Exception invalid) { busy = false; notice(R.string.notification_choice_unconfirmed); draw(); }
    }
    private void startTest() {
        if (!current() || paused || busy || capabilities == null || !capabilities.diagnostics
                || !bindingCurrent(accountKey, installation)) return;
        if (testEventId > 0 && test != null && !test.providerAccepted
                && !("failed".equals(test.state) || "discarded".equals(test.state))) {
            pollAttempts = 0; pollTest(); return;
        }
        // Preserve an unknown attempt's UUID. A new explicit completed test gets a new one.
        if (testUuid == null || testEventId > 0) testUuid = UUID.randomUUID().toString();
        testEventId = 0; test = null; localReceipt = null;
        String key = accountKey, install = installation, uuid = testUuid;
        busy = true; int request = generation; draw();
        try {
            JSONObject payload = new JSONObject().put("api_version", 2).put("account_key", key)
                    .put("installation_id", install).put("client_uuid", uuid);
            boolean started = host.test(payload, (status, body) -> {
                busy = false;
                if (!visible(request) || !bindingCurrent(key, install)) return;
                if (status == 429) {
                    long wait = NotificationSettingsProtocol.retryAfter(body);
                    notice.setText(wait > 0 ? activity.getString(R.string.notification_test_wait, Long.toString(wait))
                            : activity.getString(R.string.notification_check_unknown));
                    draw(); return;
                }
                try {
                    if (status != 200 || body == null || !(body.opt("replayed") instanceof Boolean)) throw new IllegalArgumentException();
                    test = NotificationSettingsProtocol.test(body, key, install, uuid, 0);
                    testEventId = test.eventId; lastCheckAt = System.currentTimeMillis(); pollAttempts = 0;
                    notice.setText(""); draw(); readLocal(); schedulePoll();
                } catch (Exception invalid) { notice(R.string.notification_test_unconfirmed); draw(); }
            });
            if (!started) { busy = false; notice(R.string.notification_service_busy); draw(); }
        } catch (Exception invalid) { busy = false; notice(R.string.notification_test_unconfirmed); draw(); }
    }
    private void schedulePoll() {
        main.removeCallbacks(poll);
        if (current() && !paused && testEventId > 0 && pollAttempts < 10) main.postDelayed(poll, 3000);
    }
    private void pollTest() {
        if (!current() || paused || testEventId <= 0 || pollAttempts >= 10) return;
        ++pollAttempts;
        if (busy) { schedulePoll(); return; }
        String key = accountKey, install = installation, uuid = testUuid;
        long event = testEventId; int request = generation;
        if (!bindingCurrent(key, install)) return;
        busy = true;
        boolean started = host.testStatus(event, install, (status, body) -> {
            busy = false;
            if (!visible(request) || testEventId != event || !bindingCurrent(key, install)) return;
            try {
                if (status != 200) throw new IllegalArgumentException();
                test = NotificationSettingsProtocol.test(body, key, install, uuid, event);
                lastCheckAt = System.currentTimeMillis();
            } catch (Exception invalid) { notice(R.string.notification_check_unknown); }
            draw(); readLocal(); schedulePoll();
        });
        if (!started) { busy = false; schedulePoll(); }
    }
    private void readLocal() {
        if (!current() || paused || testEventId <= 0 || readingLocal) return;
        String key = accountKey, uuid = testUuid; long event = testEventId; int request = generation;
        readingLocal = true;
        BChatStorageRepository.executor().execute(() -> {
            BChatNotificationDiagnostics.Receipt found = null;
            try { found = BChatNotificationDiagnostics.read(
                    activity.getApplicationContext(), key, Long.toString(event), uuid, System.currentTimeMillis()); }
            catch (RuntimeException unavailable) { /* Unknown, not proof of failed device delivery. */ }
            final BChatNotificationDiagnostics.Receipt received = found;
            main.post(() -> {
                readingLocal = false;
                if (!visible(request) || testEventId != event || !bindingCurrent(key, installation)) return;
                localReceipt = received; draw();
            });
        });
    }
    private void draw() {
        if (!current()) return;
        boolean granted = Build.VERSION.SDK_INT < 33 || activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED;
        NotificationManager manager = activity.getSystemService(NotificationManager.class);
        boolean appEnabled = manager != null && manager.areNotificationsEnabled();
        NotificationChannel channel = manager == null ? null : manager.getNotificationChannel(CHANNEL);
        int channelStatus = channel == null ? R.string.notification_unknown
                : channel.getImportance() == NotificationManager.IMPORTANCE_NONE ? R.string.notification_blocked
                : channel.getImportance() < NotificationManager.IMPORTANCE_DEFAULT || channel.getSound() == null
                ? R.string.notification_quiet : R.string.notification_allowed;
        deviceStatus.setText(row(R.string.notification_permission, granted ? R.string.notification_allowed : R.string.notification_blocked)
                + "\n" + row(R.string.notification_app_display, appEnabled ? R.string.notification_allowed : R.string.notification_blocked)
                + "\n" + row(R.string.notification_channel, channelStatus));
        permission.setVisibility(granted ? View.GONE : View.VISIBLE);
        boolean registered = BChatPushState.accountKey(activity) != null && BChatPushState.installationId(activity) != null;
        String checked = lastCheckAt == 0 ? activity.getString(R.string.notification_not_checked)
                : new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date(lastCheckAt));
        serverStatus.setText(row(R.string.notification_registration,
                registered ? R.string.notification_registered : R.string.notification_registration_pending)
                + "\n" + row(R.string.notification_server_registration,
                serverPreferences != null || test != null ? R.string.notification_registration_confirmed : R.string.notification_unknown)
                + "\n" + activity.getString(R.string.notification_last_check, checked));
        BChatPushState.PreviewControl pending = BChatPushState.pendingPreviewControl(activity, accountKey);
        String selected = pending != null ? pending.mode : serverPreferences == null
                ? BChatPushState.previewMode(activity, accountKey) : serverPreferences.mode;
        boolean editable = !busy && !paused && capabilities != null && capabilities.preferences
                && serverPreferences != null && preferenceSnapshot != null && pending == null
                && bindingCurrent(accountKey, installation) && BChatPushState.currentPreviewRequest(preferenceSnapshot);
        drawing = true;
        for (int i = 0; i < modes.getChildCount(); i++) {
            RadioButton radio = (RadioButton) modes.getChildAt(i);
            radio.setEnabled(editable); radio.setChecked(selected.equals(radio.getTag()));
        }
        drawing = false;
        privacyStatus.setText(pending != null ? activity.getString(R.string.notification_privacy_pending)
                : activity.getString(R.string.notification_local_preview, activity.getString(modeLabel(BChatPushState.previewMode(activity, accountKey))))
                + (serverPreferences == null ? "" : "\n" + activity.getString(R.string.notification_server_preview,
                activity.getString(modeLabel(serverPreferences.mode)))));
        retry.setVisibility(pending == null ? View.GONE : View.VISIBLE);
        retry.setEnabled(!busy && !paused && serverPreferences != null);
        refresh.setEnabled(!busy && !paused);
        runTest.setEnabled(!busy && !paused && registered && capabilities != null && capabilities.diagnostics);
        runTest.setText(testEventId > 0 && test != null && !test.providerAccepted
                && !("failed".equals(test.state) || "discarded".equals(test.state))
                ? R.string.notification_test_refresh : testUuid != null && testEventId == 0
                ? R.string.notification_test_retry : R.string.notification_test_start);
        int provider = test == null ? R.string.notification_unknown
                : test.providerAccepted ? R.string.notification_provider_accepted
                : !test.configurationReady ? R.string.notification_provider_not_ready
                : "failed".equals(test.state) || "discarded".equals(test.state)
                ? R.string.notification_provider_failed : R.string.notification_provider_pending;
        testStatus.setText(row(R.string.notification_provider, provider)
                + "\n" + row(R.string.notification_callback, localReceipt == null
                ? R.string.notification_unknown : R.string.notification_received)
                + "\n" + row(R.string.notification_display_request, localReceipt == null
                ? R.string.notification_unknown : localReceipt.displayedAt > 0
                ? R.string.notification_display_accepted : R.string.notification_display_not_accepted)
                + "\n" + activity.getString(R.string.notification_test_note));
    }
    private int modeLabel(String mode) {
        return "full".equals(mode) ? R.string.notification_preview_full
                : "sender".equals(mode) ? R.string.notification_preview_sender : R.string.notification_preview_none;
    }
    private String row(int label, int state) { return activity.getString(R.string.notification_status_row,
            activity.getString(label), activity.getString(state)); }
    private void notice(int text) { notice.setText(text); }
    private LinearLayout column(int padding) {
        LinearLayout result = new LinearLayout(activity); result.setOrientation(LinearLayout.VERTICAL);
        result.setLayoutDirection(AppLocale.direction(activity));
        result.setPadding(Ui.dp(activity, padding), Ui.dp(activity, padding), Ui.dp(activity, padding), Ui.dp(activity, padding));
        return result;
    }
    private LinearLayout section(LinearLayout parent, int title) {
        LinearLayout card = column(14); card.setBackground(Ui.outline(Ui.SURFACE, Ui.LINE, 14, activity));
        LinearLayout.LayoutParams space = new LinearLayout.LayoutParams(-1, -2); space.bottomMargin = Ui.dp(activity, 12);
        parent.addView(card, space);
        TextView heading = Ui.text(activity, activity.getString(title), 16, Ui.INK, true);
        card.addView(heading, new LinearLayout.LayoutParams(-1, -2)); return card;
    }
    private TextView body(LinearLayout parent) {
        TextView text = Ui.text(activity, "", 14, Ui.MUTED, false);
        text.setPadding(0, Ui.dp(activity, 8), 0, Ui.dp(activity, 8));
        text.setLineSpacing(Ui.dp(activity, 3), 1f); parent.addView(text, new LinearLayout.LayoutParams(-1, -2)); return text;
    }
    private Button action(LinearLayout parent, int label, Runnable action) {
        Button button = new Button(activity); button.setText(label); Ui.styleAction(button, Ui.ActionTone.SECONDARY);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2); layout.topMargin = Ui.dp(activity, 6);
        parent.addView(button, layout); button.setOnClickListener(ignored -> action.run()); return button;
    }
}

package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.Bundle;
import android.os.SystemClock;
import android.text.Layout;
import android.view.View;
import android.view.ViewGroup;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Button;
import android.widget.RadioButton;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real Android35 component/lifecycle/persistence checks with an explicitly fake server host. */
public final class NotificationSettingsInstrumentation extends Instrumentation {
    private final List<String> failures = new ArrayList<>();
    private final JSONArray renders = new JSONArray(), journeys = new JSONArray();
    private int assertions;
    private NotificationSettingsTestActivity activity;

    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments == null || !"true".equals(arguments.getString("disposable")))
            throw new IllegalArgumentException("Explicit disposable test package required");
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            check(getTargetContext().getPackageName().equals("com.baseer.bchat.notification.settings.test"), "test package isolation");
            check(android.os.Build.VERSION.SDK_INT == 35, "Android35 runtime");
            bind();
            for (String language : new String[]{"ar", "en"})
                for (boolean dark : new boolean[]{false, true})
                    for (float scale : new float[]{1f, 2f}) render(language, dark, scale);
            journey("unsupported_is_not_offline", this::unsupported);
            journey("quiet_is_not_blocked", this::quiet);
            journey("privacy_lost_ack_same_uuid_revision", this::privacyRetry);
            journey("provider_acceptance_without_callback_is_unknown", this::acceptedUnknown);
            journey("pause_stops_polling", this::pauseStopsPolling);
            journey("dismiss_stops_polling", this::dismissStopsPolling);
            journey("late_privacy_ack_settles_after_dismiss", this::lateAck);
        } catch (Throwable error) { failures.add("Harness: " + error); }
        finally { close(); }
        try {
            JSONObject evidence = new JSONObject().put("schema", 1).put("android_api", android.os.Build.VERSION.SDK_INT)
                    .put("package", getTargetContext().getPackageName()).put("assertions", assertions)
                    .put("renders", renders).put("journeys", journeys).put("failures", new JSONArray(failures))
                    .put("scope", "Actual test Activity/Dialog/native JSONObject/SharedPreferences; fake Host HTTP replies; executor-only adapter; no FCM/HTTP/SQLite/product-Activity claim")
                    .put("passed", failures.isEmpty());
            write("notification-settings-results.json", evidence.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Throwable error) { failures.add("Evidence: " + error); }
        String message = failures.isEmpty() ? "PASS 8 actual Android notification settings renders and 7 focused journeys; " + assertions + " assertions"
                : "FAIL notification settings: " + failures;
        result.putString("stream", message + "\n");
        finish(failures.isEmpty() ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
    }

    private void bind() throws Exception {
        Context context = getTargetContext();
        // Only this standalone package's private fixture preferences, never the product package.
        check(context.getSharedPreferences("bchat-notification-diagnostics-v1", 0).edit().clear().commit(), "clear test diagnostics fixture");
        check(BChatPushState.awaitReady(context, 3000), "PushState real preferences initialized");
        BChatPushState.clearAccount(context);
        BChatPushState.verifiedAccount(context, NotificationSettingsTestActivity.ACCOUNT);
        BChatPushState.token(context, "isolated-notification-test-token-abcdefghijklmnopqrstuvwxyz0123456789");
        waitFor(() -> BChatPushState.installationId(context) != null, "installation durable");
        CountDownLatch registered = new CountDownLatch(1);
        final boolean[] valid = {false};
        BChatPushState.registeredAsync(context, BChatPushState.registration(context, NotificationSettingsTestActivity.ACCOUNT),
                NotificationSettingsTestActivity.ACCOUNT_KEY, (ok, durable) -> { valid[0] = Boolean.TRUE.equals(ok) && durable; registered.countDown(); });
        require(registered.await(5, TimeUnit.SECONDS), "registration callback deadline");
        check(valid[0] && BChatPushState.matches(context, NotificationSettingsTestActivity.ACCOUNT_KEY), "registered route committed");
    }
    private NotificationSettingsTestActivity open(String language, boolean dark, float scale, boolean supported) throws Exception {
        close();
        require(new LocalSettings(getTargetContext()).language(language), "test language committed");
        NotificationSettingsTestActivity.language = language;
        NotificationSettingsTestActivity.dark = dark;
        NotificationSettingsTestActivity.scale = scale;
        NotificationSettingsTestActivity.supported = supported;
        Intent intent = new Intent(getTargetContext(), NotificationSettingsTestActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity = (NotificationSettingsTestActivity) startActivitySync(intent);
        waitForIdleSync();
        waitFor(() -> !field(activity.panel, "busy", Boolean.class), "panel refresh settles");
        return activity;
    }
    private void close() {
        if (activity == null) return;
        NotificationSettingsTestActivity previous = activity;
        runOnMainSync(() -> { previous.panel.dismiss(); previous.finish(); });
        waitForIdleSync(); activity = null;
    }
    private void render(String language, boolean dark, float scale) {
        String name = "notification-settings-" + language + "-" + (dark ? "dark" : "light") + "-" + scale;
        int before = failures.size();
        try {
            NotificationSettingsTestActivity current = open(language, dark, scale, true);
            // A fresh full GET has a real asynchronous SharedPreferences commit.
            waitFor(() -> field(current.panel, "modes", android.widget.RadioGroup.class).getChildAt(0).isEnabled(), "privacy editable");
            runOnMainSync(() -> {
                AlertDialog dialog = field(current.panel, "dialog", AlertDialog.class);
                View decor = dialog.getWindow().getDecorView();
                ScrollView scroll = findScroll(decor);
                check(scroll != null, name + ": bounded ScrollView exists");
                float logicalWidth = decor.getWidth() / current.getResources().getDisplayMetrics().density;
                check(Math.abs(logicalWidth - 360) <= 2, name + ": width360dp actual=" + logicalWidth);
                check(Math.abs(current.getResources().getConfiguration().fontScale - scale) < .01, name + ": font scale");
                check(ChatAppearance.dark(current) == dark, name + ": actual themed context");
                check(current.getResources().getConfiguration().getLocales().get(0).getLanguage().equals(language), name + ": actual locale");
                inspect(decor, decor, name);
                Button close = dialog.getButton(AlertDialog.BUTTON_NEGATIVE);
                check(close != null && close.getHeight() >= Ui.dp(current, 48), name + ": close touch >=48dp");
                check(close != null && close.isClickable() && close.isEnabled() && close.getText().length() > 0,
                        name + ": close labeled and actionable");
                capture(decor, name + "-top.png");
                if (scroll != null) {
                    check(scroll.canScrollVertically(1), name + ": content can scroll to all settings");
                    scroll.fullScroll(View.FOCUS_DOWN);
                }
            });
            waitForIdleSync();
            waitFor(() -> !findScroll(field(current.panel, "dialog", AlertDialog.class).getWindow().getDecorView()).canScrollVertically(1),
                    name + ": native animated fullScroll reaches bottom", 2000);
            runOnMainSync(() -> {
                AlertDialog dialog = field(current.panel, "dialog", AlertDialog.class);
                capture(dialog.getWindow().getDecorView(), name + "-bottom.png");
                ScrollView scroll = findScroll(dialog.getWindow().getDecorView());
                check(scroll != null && !scroll.canScrollVertically(1), name + ": bottom reachable");
                try { renders.put(new JSONObject().put("case", name).put("language", language).put("dark", dark)
                        .put("font_scale", scale).put("logical_width_dp", dialog.getWindow().getDecorView().getWidth()
                                / current.getResources().getDisplayMetrics().density)
                        .put("density_dpi", current.getResources().getConfiguration().densityDpi)
                        .put("passed", failures.size() == before).put("frames", new JSONArray(new String[]{name + "-top.png", name + "-bottom.png"}))); }
                catch (Exception invalid) { throw new AssertionError(invalid); }
            });
        } catch (Throwable error) { failures.add(name + ": " + error); }
        finally { close(); }
    }
    private void inspect(View view, View decor, String label) {
        if (view.getVisibility() == View.GONE) return;
        if (view instanceof TextView && ((TextView) view).getText().length() > 0) {
            TextView text = (TextView) view;
            int[] origin = new int[2], point = new int[2];
            decor.getLocationOnScreen(origin); text.getLocationOnScreen(point);
            check(point[0] >= origin[0] - 1 && point[0] + text.getWidth() <= origin[0] + decor.getWidth() + 1,
                    label + ": horizontal bounds for " + text.getText());
            Layout layout = text.getLayout();
            if (layout != null) {
                for (int line = 0; line < layout.getLineCount(); line++) {
                    check(layout.getEllipsisCount(line) == 0, label + ": no text ellipsis for " + text.getText());
                    // getLineWidth includes invisible trailing wrap spaces; getLineMax is visible glyph width.
                    check(layout.getLineMax(line) <= layout.getWidth() + 2,
                            label + ": visible text width=" + layout.getLineMax(line) + "/" + layout.getWidth() + " for " + text.getText());
                }
                check(layout.getHeight() + text.getCompoundPaddingTop() + text.getCompoundPaddingBottom() <= text.getHeight() + 2,
                        label + ": text vertical layout for " + text.getText());
            }
        }
        if (view instanceof Button) {
            Button button = (Button) view;
            check(button.getHeight() >= Ui.dp(activity, 48), label + ": action touch>=48dp " + button.getText());
            AccessibilityNodeInfo info = button.createAccessibilityNodeInfo();
            check(info.getText() != null && info.getText().length() > 0 && info.isClickable(), label + ": accessible action label");
            if (button instanceof RadioButton) {
                check(info.isCheckable() && "android.widget.RadioButton".contentEquals(info.getClassName()), label + ": radio semantics");
                check(button.getLayoutDirection() == AppLocale.direction(activity), label + ": actual RTL/LTR radio layout");
            }
            info.recycle();
        }
        if (view instanceof ViewGroup) for (int index = 0; index < ((ViewGroup) view).getChildCount(); index++)
            inspect(((ViewGroup) view).getChildAt(index), decor, label);
    }
    private void unsupported() throws Exception {
        NotificationSettingsTestActivity current = open("ar", false, 1, false);
        runOnMainSync(() -> {
            String notice = field(current.panel, "notice", TextView.class).getText().toString();
            check(notice.equals(current.getString(R.string.notification_unsupported)), "unsupported notice, not offline");
            check(current.host.preferenceCalls == 0, "unsupported does not dispatch preferences");
            check(!field(current.panel, "runTest", Button.class).isEnabled(), "unsupported test disabled");
        });
    }
    private void quiet() throws Exception {
        NotificationSettingsTestActivity current = open("en", false, 1, true);
        runOnMainSync(() -> {
            String text = field(current.panel, "deviceStatus", TextView.class).getText().toString();
            String quiet = current.getString(R.string.notification_status_row, current.getString(R.string.notification_channel), current.getString(R.string.notification_quiet));
            String blocked = current.getString(R.string.notification_status_row, current.getString(R.string.notification_channel), current.getString(R.string.notification_blocked));
            check(text.contains(quiet) && !text.contains(blocked), "actual quiet channel is not blocked");
        });
    }
    private void privacyRetry() throws Exception {
        NotificationSettingsTestActivity current = open("en", false, 1, true);
        waitFor(() -> "full".equals(BChatPushState.previewMode(current, NotificationSettingsTestActivity.ACCOUNT_KEY)), "initial full server preference accepted");
        current.host.loseNextAck = true;
        clickMode(current, "none");
        waitFor(() -> current.host.posts.size() == 1 && !field(current.panel, "busy", Boolean.class), "lost ACK received as unknown");
        BChatPushState.PreviewControl pending = BChatPushState.pendingPreviewControl(current, NotificationSettingsTestActivity.ACCOUNT_KEY);
        check(pending != null, "unknown privacy outcome keeps durable intent");
        check("none".equals(BChatPushState.previewMode(current, NotificationSettingsTestActivity.ACCOUNT_KEY)), "restrictive none effective before HTTP ACK");
        check(pending != null && pending.clientUuid.equals(current.getSharedPreferences("bchat-push-v1", 0).getString("preview-control-uuid", null)), "pending UUID exists in real preferences");
        runOnMainSync(() -> check(field(current.panel, "retry", Button.class).performClick(), "explicit retry click"));
        waitFor(() -> current.host.posts.size() == 2 && BChatPushState.pendingPreviewControl(current, NotificationSettingsTestActivity.ACCOUNT_KEY) == null
                        && !current.getSharedPreferences("bchat-push-v1", 0).contains("preview-control-uuid"),
                "retry ACK settles intent");
        JSONObject first = current.host.posts.get(0), second = current.host.posts.get(1);
        check(first.optString("client_uuid").equals(second.optString("client_uuid")), "retry exact UUID");
        check(first.optLong("expected_revision") == second.optLong("expected_revision"), "retry exact expected revision");
        check(first.toString().equals(second.toString()), "retry identical JSON payload");
        check(!current.getSharedPreferences("bchat-push-v1", 0).contains("preview-control-uuid"), "accepted ACK clears persisted intent");
    }
    private void acceptedUnknown() throws Exception {
        NotificationSettingsTestActivity current = open("en", false, 1, true);
        startTest(current);
        waitFor(() -> !field(current.panel, "readingLocal", Boolean.class), "local ledger read completes");
        runOnMainSync(() -> {
            String text = field(current.panel, "testStatus", TextView.class).getText().toString();
            check(text.contains(current.getString(R.string.notification_provider_accepted)), "provider acceptance separately labeled");
            check(text.contains(row(current, R.string.notification_callback, R.string.notification_unknown)), "no callback stays unknown");
            check(text.contains(row(current, R.string.notification_display_request, R.string.notification_unknown)), "no display evidence stays unknown");
            check(field(current.panel, "localReceipt", BChatNotificationDiagnostics.Receipt.class) == null, "actual receipt store has no fabricated callback");
        });
    }
    private void pauseStopsPolling() throws Exception {
        NotificationSettingsTestActivity current = open("ar", false, 1, true);
        startTest(current);
        runOnMainSync(() -> callActivityOnPause(current));
        int calls = current.host.statusCalls;
        SystemClock.sleep(3300); waitForIdleSync();
        check(current.host.statusCalls == calls, "actual host Activity.onPause stops delayed poll");
        runOnMainSync(() -> callActivityOnResume(current));
        waitFor(() -> current.host.statusCalls > calls, "resume schedules new foreground poll", 4500);
    }
    private void dismissStopsPolling() throws Exception {
        NotificationSettingsTestActivity current = open("en", true, 1, true);
        startTest(current);
        runOnMainSync(() -> field(current.panel, "dialog", AlertDialog.class).getButton(AlertDialog.BUTTON_NEGATIVE).performClick());
        int calls = current.host.statusCalls;
        SystemClock.sleep(3300); waitForIdleSync();
        check(current.host.statusCalls == calls && field(current.panel, "closed", Boolean.class), "actual dismiss stops delayed poll");
    }
    private void lateAck() throws Exception {
        NotificationSettingsTestActivity current = open("en", false, 1, true);
        // Explicit fake GET from a newer server revision; no server-side operation is really sent.
        current.host.revision = 3; current.host.mode = "full";
        runOnMainSync(() -> field(current.panel, "refresh", Button.class).performClick());
        waitFor(() -> "full".equals(BChatPushState.previewMode(current, NotificationSettingsTestActivity.ACCOUNT_KEY)), "fresh full revision3 accepted");
        current.host.holdNextAck = true;
        clickMode(current, "none");
        waitFor(() -> current.host.heldReply != null, "privacy request dispatched after durable intent");
        check(BChatPushState.pendingPreviewControl(current, NotificationSettingsTestActivity.ACCOUNT_KEY) != null, "held ACK keeps intent");
        runOnMainSync(() -> current.panel.dismiss());
        runOnMainSync(() -> current.host.heldReply.complete(200, current.host.heldBody));
        waitFor(() -> BChatPushState.pendingPreviewControl(current, NotificationSettingsTestActivity.ACCOUNT_KEY) == null
                        && !current.getSharedPreferences("bchat-push-v1", 0).contains("preview-control-uuid"),
                "late ACK settles closed-panel intent and real preference commit");
        check("none".equals(BChatPushState.previewMode(current, NotificationSettingsTestActivity.ACCOUNT_KEY)), "late ACK keeps restrictive none");
        check(!current.getSharedPreferences("bchat-push-v1", 0).contains("preview-control-uuid"), "late ACK persisted cleanup");
        check(field(current.panel, "closed", Boolean.class), "late ACK never reopens dismissed panel");
    }
    private void startTest(NotificationSettingsTestActivity current) throws Exception {
        runOnMainSync(() -> check(field(current.panel, "runTest", Button.class).performClick(), "test click"));
        waitFor(() -> current.host.testCalls == 1 && field(current.panel, "testEventId", Long.class) == 901L, "fake provider accepted diagnostic");
    }
    private void clickMode(NotificationSettingsTestActivity current, String mode) throws Exception {
        android.widget.RadioGroup group = field(current.panel, "modes", android.widget.RadioGroup.class);
        waitFor(() -> group.getChildAt(0).isEnabled(), "radio editable before explicit selection");
        runOnMainSync(() -> {
            RadioButton chosen = group.findViewWithTag(mode);
            check(chosen != null && chosen.isEnabled(), "radio choice available " + mode);
            if (chosen != null) chosen.performClick();
        });
        // choose() redraws the old server choice while busy before its durable ticket becomes sendable.
        waitFor(() -> mode.equals(BChatPushState.previewMode(current, NotificationSettingsTestActivity.ACCOUNT_KEY)),
                "radio explicit restrictive choice applied");
    }
    private String row(Context context, int label, int value) {
        return context.getString(R.string.notification_status_row, context.getString(label), context.getString(value));
    }
    private void journey(String name, Checked task) {
        int before = failures.size();
        try { task.run(); }
        catch (Throwable error) { failures.add(name + ": " + error); }
        finally { close(); }
        try { journeys.put(new JSONObject().put("case", name).put("passed", failures.size() == before)); }
        catch (Exception error) { throw new AssertionError(error); }
    }
    private void waitFor(BooleanSupplier condition, String label) throws Exception { waitFor(condition, label, 5000); }
    private void waitFor(BooleanSupplier condition, String label, long timeout) throws Exception {
        long until = SystemClock.uptimeMillis() + timeout;
        while (SystemClock.uptimeMillis() < until) {
            final boolean[] ready = {false};
            runOnMainSync(() -> ready[0] = condition.getAsBoolean());
            if (ready[0]) return;
            SystemClock.sleep(20);
        }
        throw new AssertionError("Deadline: " + label);
    }
    private void check(boolean value, String label) { assertions++; if (!value) failures.add(label); }
    private void require(boolean value, String label) { check(value, label); if (!value) throw new AssertionError(label); }
    private ScrollView findScroll(View root) {
        if (root.getVisibility() == View.GONE) return null; // AlertDialog has an unused hidden message ScrollView.
        if (root instanceof ScrollView) return (ScrollView) root;
        if (root instanceof ViewGroup) for (int index = 0; index < ((ViewGroup) root).getChildCount(); index++) {
            ScrollView found = findScroll(((ViewGroup) root).getChildAt(index)); if (found != null) return found;
        }
        return null;
    }
    private void capture(View actualDecor, String name) {
        Bitmap bitmap = Bitmap.createBitmap(actualDecor.getWidth(), actualDecor.getHeight(), Bitmap.Config.ARGB_8888);
        actualDecor.draw(new Canvas(bitmap));
        try (FileOutputStream stream = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) {
            if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)) throw new AssertionError("PNG encode");
        } catch (Exception error) { throw new AssertionError(error); }
        finally { bitmap.recycle(); }
    }
    private void write(String name, byte[] contents) throws Exception {
        try (FileOutputStream stream = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) { stream.write(contents); }
    }
    static <T> T field(Object owner, String name, Class<T> type) {
        try { Field field = owner.getClass().getDeclaredField(name); field.setAccessible(true); return type.cast(field.get(owner)); }
        catch (Exception error) { throw new AssertionError("Inspect production field " + name, error); }
    }
    private interface Checked { void run() throws Exception; }
}

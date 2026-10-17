package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Instrumentation;
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
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import com.baseer.freshchat.sync.AccountScope;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BooleanSupplier;
import org.json.JSONArray;
import org.json.JSONObject;

/** Android35 Dialog/JSONObject/Activity checks; all session/network replies are explicit fake Host data. */
public final class ReceiptDetailsInstrumentation extends Instrumentation {
    private final List<String> failures = new ArrayList<>();
    private final JSONArray renders = new JSONArray(), journeys = new JSONArray();
    private int assertions, protocolAccepts, protocolRejects;
    private ReceiptDetailsTestActivity activity;
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments == null || !"true".equals(arguments.getString("disposable")))
            throw new IllegalArgumentException("Explicit disposable test package required");
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            check(getTargetContext().getPackageName().equals("com.baseer.bchat.receipt.details.test"), "isolated test package");
            check(android.os.Build.VERSION.SDK_INT == 35, "Android35 runtime");
            journey("strict_native_json_acceptance", this::protocolValid);
            journey("strict_native_json_rejection", this::protocolInvalid);
            for (String language : new String[]{"ar", "en"})
                for (boolean dark : new boolean[]{false, true})
                    for (float scale : new float[]{1f, 2f}) render(language, dark, scale);
            journey("bounded_pagination_authoritative_counts_refresh", this::pagination);
            journey("manual_only_no_polling", this::noPolling);
            journey("pause_rejects_late_callback_until_manual_refresh", this::pause);
            journey("dismiss_rejects_late_callback", this::dismiss);
            journey("account_epoch_generation_fences", this::binding);
            journey("denied_malformed_and_dispatch_failure", this::failures);
            journey("background_callback_marshalled_to_main", this::background);
        } catch (Throwable error) { failures.add("Harness: " + error); }
        finally { close(); }
        try {
            JSONObject proof = new JSONObject().put("schema", 1).put("android_api", android.os.Build.VERSION.SDK_INT)
                    .put("package", getTargetContext().getPackageName()).put("assertions", assertions)
                    .put("protocol_acceptances", protocolAccepts).put("protocol_rejections", protocolRejects)
                    .put("renders", renders).put("journeys", journeys).put("failures", new JSONArray(failures))
                    .put("scope", "Actual native Activity/Dialog/JSONObject/SharedPreferences locale; fake session Host; no real HTTP/ACK/FCM/SQLite/product Activity or device-delivery claim")
                    .put("passed", failures.isEmpty());
            write("receipt-details-results.json", proof.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Throwable error) { failures.add("Evidence: " + error); }
        result.putString("stream", (failures.isEmpty() ? "PASS 8 actual Android receipt detail renders and 9 focused journeys; "
                + assertions + " assertions" : "FAIL receipt details: " + failures) + "\n");
        finish(failures.isEmpty() ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
    }
    private ReceiptDetailsProtocol.Page parse(JSONObject body, long after) {
        return ReceiptDetailsProtocol.page(body, 11, 22, 33, after);
    }
    private void accepts(JSONObject body, String label) { parse(body, 0); protocolAccepts++; check(true, label); }
    private void rejects(JSONObject body, String label) {
        try { parse(body, 0); check(false, "must reject: " + label); }
        catch (IllegalArgumentException expected) { protocolRejects++; check(true, label); }
    }
    private JSONObject fresh() { return ReceiptDetailsTestActivity.response(0, 3, true); }
    private void protocolValid() throws Exception {
        ReceiptDetailsProtocol.Page page = parse(fresh(), 0);
        check(page.rows.size() == 3 && page.eligible == 100 && page.delivered == 80 && page.read == 20, "full counts not page counts");
        check(page.rows.get(0).readAt.equals(page.rows.get(0).deliveredAt), "same-second read/delivery accepted");
        check(page.rows.get(1).name.equals("User") && page.rows.get(2).deliveredAt == null, "server fallback and unknown valid");
        accepts(fresh(), "sent response");
        JSONObject delivered = fresh().put("state", "delivered"); delivered.getJSONObject("counts").put("delivered", 100);
        accepts(delivered, "all eligible delivered");
        JSONObject read = delivered.put("state", "read"); read.getJSONObject("counts").put("read", 100);
        accepts(read, "all eligible read");
        JSONObject empty = ReceiptDetailsTestActivity.response(0, 0, false);
        empty.getJSONObject("counts").put("eligible", 0).put("delivered", 0).put("read", 0);
        accepts(empty, "zero eligible sent not read");
        JSONObject unicode = fresh(); unicode.getJSONArray("receipts").getJSONObject(0).put("user_name", repeat("ع", 120));
        accepts(unicode, "120 code points and <=256 UTF8");
        check(ReceiptDetailsProtocol.path(11, 33, 103).equals("/bchat/api/v2/rooms/11/messages/33/receipts?after_id=103"), "canonical read-only GET route");
        check(parse(ReceiptDetailsTestActivity.response(103, 2, false), 103).nextAfterId == 105, "next cursor parsed exactly");
        try { page.rows.clear(); check(false, "immutable page rows"); } catch (UnsupportedOperationException expected) { check(true, "immutable page rows"); }
    }
    private void protocolInvalid() throws Exception {
        for (String key : new String[]{"api_version", "room_id", "membership_id", "message_id"}) {
            for (Object value : new Object[]{"2", true, 2.0, 0, -1, JSONObject.NULL, 2147483648L})
                rejects(fresh().put(key, value), key + " strict type/bounds " + value);
            JSONObject missing = fresh(); missing.remove(key); rejects(missing, "missing " + key);
        }
        for (String key : new String[]{"eligible", "delivered", "read"})
            for (Object value : new Object[]{"1", false, 1.0, -1, JSONObject.NULL, 2147483648L}) {
                JSONObject invalid = fresh(); invalid.getJSONObject("counts").put(key, value); rejects(invalid, "count " + key + " " + value);
            }
        JSONObject invalid = fresh(); invalid.getJSONObject("counts").put("read", 81); rejects(invalid, "read exceeds delivered");
        invalid = fresh(); invalid.getJSONObject("counts").put("delivered", 101); rejects(invalid, "delivered exceeds eligible");
        for (Object value : new Object[]{"read", "delivered", "unknown", true, JSONObject.NULL}) rejects(fresh().put("state", value), "state consistency " + value);
        for (Object value : new Object[]{1, "true", JSONObject.NULL}) rejects(fresh().put("has_more", value), "has_more native bool");
        for (Object value : new Object[]{0, 102, 104, true, 103.0, "103"}) rejects(fresh().put("next_after_id", value), "cursor exact native last");
        invalid = ReceiptDetailsTestActivity.response(0, 31, true); rejects(invalid, "page <=30");
        invalid = fresh(); invalid.put("receipts", JSONObject.NULL); rejects(invalid, "array required");
        invalid = fresh(); invalid.getJSONArray("receipts").put(1, JSONObject.NULL); rejects(invalid, "row object required");
        for (Object value : new Object[]{0, -1, true, "101", 101.0, 2147483648L}) {
            invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(0).put("id", value); rejects(invalid, "receipt id " + value);
            invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(0).put("user_id", value); rejects(invalid, "user id " + value);
        }
        invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(1).put("id", 101); rejects(invalid, "duplicate/nonascending ids");
        for (Object value : new Object[]{"", "   ", repeat("a", 121), repeat("ع", 120) + "ع", repeat("漢", 86), "bad\nname", "bad\u2066name", "bad\uD800", true}) {
            invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(0).put("user_name", value); rejects(invalid, "name type/length/UTF8/control");
        }
        for (Object value : new Object[]{true, "2026-02-30 01:02:03", "2026-10-18T01:02:03Z", "2026-10-18 24:00:00", "2026-10-18 01:02:03Z", "garbage"}) {
            invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(0).put("delivered_at", value); rejects(invalid, "strict UTC timestamp " + value);
        }
        invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(0).put("delivered_at", JSONObject.NULL); rejects(invalid, "read requires delivered");
        invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(0).put("read_at", "2026-10-18 01:02:02"); rejects(invalid, "read cannot precede delivery");
        invalid = fresh(); invalid.getJSONArray("receipts").getJSONObject(0).remove("read_at"); rejects(invalid, "timestamp field required even null");
        invalid = ReceiptDetailsTestActivity.response(0, 0, false).put("has_more", true); rejects(invalid, "empty cannot have more");
        rejects(fresh().put("extra", repeat("ع", 32768)), "full response UTF8 <=64KiB");
        rejects(fresh().put("error", new JSONObject()), "error envelope rejected");
        try { parse(ReceiptDetailsTestActivity.response(100, 3, true), 101); check(false, "row after cursor required"); }
        catch (IllegalArgumentException expected) { protocolRejects++; check(true, "rows strictly after requested cursor"); }
    }
    private ReceiptDetailsTestActivity open(String language, boolean dark, float scale) throws Exception {
        close();
        require(new LocalSettings(getTargetContext()).language(language), "test-only language preference committed");
        ReceiptDetailsTestActivity.language = language; ReceiptDetailsTestActivity.dark = dark; ReceiptDetailsTestActivity.scale = scale;
        activity = (ReceiptDetailsTestActivity) startActivitySync(new Intent(getTargetContext(), ReceiptDetailsTestActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitFor(() -> !field(activity.panel, "busy", Boolean.class), "initial GET settles"); waitForIdleSync(); return activity;
    }
    private void render(String language, boolean dark, float scale) {
        String name = "receipt-details-" + language + "-" + (dark ? "dark" : "light") + "-" + scale;
        int before = failures.size();
        try {
            ReceiptDetailsTestActivity current = open(language, dark, scale);
            runOnMainSync(() -> {
                AlertDialog dialog = field(current.panel, "dialog", AlertDialog.class); View decor = dialog.getWindow().getDecorView();
                ScrollView scroll = field(current.panel, "scroll", ScrollView.class);
                float dp = decor.getWidth() / current.getResources().getDisplayMetrics().density;
                check(Math.abs(dp - 360) <= 2, name + ": width360dp actual=" + dp);
                check(Math.abs(current.getResources().getConfiguration().fontScale - scale) < .01, name + ": font scale");
                check(ChatAppearance.dark(current) == dark, name + ": actual theme");
                check(AppLocale.rtl(current) == language.equals("ar"), name + ": actual locale direction");
                check(field(current.panel, "rows", LinearLayout.class).getLayoutDirection() == AppLocale.direction(current), name + ": rows RTL/LTR");
                inspect(decor, decor, name);
                Button close = dialog.getButton(AlertDialog.BUTTON_NEGATIVE);
                check(close.getHeight() >= Ui.dp(current, 48) && close.isEnabled(), name + ": close accessible48dp");
                capture(decor, name + "-top.png");
                check(scroll.canScrollVertically(1), name + ": bounded vertical scrolling"); scroll.fullScroll(View.FOCUS_DOWN);
            });
            waitFor(() -> !field(current.panel, "scroll", ScrollView.class).canScrollVertically(1), "bottom reachable", 2500);
            runOnMainSync(() -> {
                AlertDialog dialog = field(current.panel, "dialog", AlertDialog.class);
                capture(dialog.getWindow().getDecorView(), name + "-bottom.png");
                try { renders.put(new JSONObject().put("case", name).put("language", language).put("dark", dark)
                        .put("font_scale", scale).put("density_dpi", current.getResources().getConfiguration().densityDpi)
                        .put("logical_width_dp", dialog.getWindow().getDecorView().getWidth() / current.getResources().getDisplayMetrics().density)
                        .put("frames", new JSONArray(new String[]{name + "-top.png", name + "-bottom.png"}))
                        .put("passed", failures.size() == before)); }
                catch (Exception invalid) { throw new AssertionError(invalid); }
            });
        } catch (Throwable invalid) { failures.add(name + ": " + invalid); }
        finally { close(); }
    }
    private void inspect(View view, View decor, String label) {
        if (view.getVisibility() == View.GONE) return;
        if (view instanceof TextView && ((TextView) view).getText().length() > 0) {
            TextView text = (TextView) view; int[] origin = new int[2], point = new int[2];
            decor.getLocationOnScreen(origin); text.getLocationOnScreen(point);
            check(point[0] >= origin[0] - 1 && point[0] + text.getWidth() <= origin[0] + decor.getWidth() + 1, label + ": horizontal bounds");
            Layout layout = text.getLayout();
            if (layout != null) {
                for (int line = 0; line < layout.getLineCount(); line++) {
                    check(layout.getEllipsisCount(line) == 0, label + ": no ellipsis");
                    check(layout.getLineMax(line) <= layout.getWidth() + 2, label + ": no horizontal glyph clipping " + text.getText());
                }
                check(layout.getHeight() + text.getCompoundPaddingTop() + text.getCompoundPaddingBottom() <= text.getHeight() + 2, label + ": no vertical clipping");
            }
        }
        if (view instanceof Button) {
            Button button = (Button) view;
            check(button.getHeight() >= Ui.dp(activity, 48), label + ": action48dp");
            check(button.getLayoutDirection() == AppLocale.direction(activity), label + ": action layout direction");
            AccessibilityNodeInfo info = button.createAccessibilityNodeInfo();
            check(info.getText() != null && info.getText().length() > 0 && info.isClickable(), label + ": accessible action text"); info.recycle();
        }
        if (view instanceof ViewGroup) for (int index = 0; index < ((ViewGroup) view).getChildCount(); index++)
            inspect(((ViewGroup) view).getChildAt(index), decor, label);
    }
    private void pagination() throws Exception {
        ReceiptDetailsTestActivity current = open("ar", false, 1);
        runOnMainSync(() -> { current.host.firstCount = 30; click("refresh"); }); settle();
        runOnMainSync(() -> {
            check(field(current.panel, "rows", LinearLayout.class).getChildCount() == 30, "first page30 only");
            check(field(current.panel, "summary", TextView.class).getText().toString().contains("100"), "authoritative100 not30");
            click("next");
        }); settle();
        runOnMainSync(() -> {
            check(field(current.panel, "rows", LinearLayout.class).getChildCount() == 2, "next page replaces not accumulates");
            check(current.host.afterIds.get(current.host.afterIds.size() - 1) == 130, "next exact prior cursor");
            check(field(current.panel, "next", Button.class).getVisibility() == View.GONE, "last page hides next"); click("refresh");
        }); settle();
        runOnMainSync(() -> check(current.host.afterIds.get(current.host.afterIds.size() - 1) == 0, "refresh reset0"));
    }
    private void noPolling() throws Exception {
        ReceiptDetailsTestActivity current = open("en", false, 1); int calls = current.host.afterIds.size();
        SystemClock.sleep(350); waitForIdleSync();
        runOnMainSync(() -> check(current.host.afterIds.size() == calls, "no automatic polling or ACK dispatch"));
    }
    private void pause() throws Exception {
        ReceiptDetailsTestActivity current = open("ar", true, 1);
        runOnMainSync(() -> { current.host.hold = true; click("refresh"); callActivityOnPause(current); });
        int calls = current.host.afterIds.size();
        runOnMainSync(() -> { current.host.heldReply.complete(200, current.host.heldBody); click("refresh"); }); waitForIdleSync();
        runOnMainSync(() -> {
            check(current.host.afterIds.size() == calls, "pause prevents request");
            check(field(current.panel, "notice", TextView.class).getText().toString().equals(current.getString(R.string.receipt_details_unconfirmed)), "late paused callback ignored; no indefinite loading");
            callActivityOnResume(current);
            check(current.host.afterIds.size() == calls, "resume has no automatic HTTP");
            current.host.hold = false; click("refresh");
        }); settle();
        runOnMainSync(() -> check(current.host.afterIds.size() == calls + 1, "manual refresh after resume"));
    }
    private void dismiss() throws Exception {
        ReceiptDetailsTestActivity current = open("en", true, 1);
        runOnMainSync(() -> { current.host.hold = true; click("refresh"); current.panel.dismiss();
            current.host.heldReply.complete(200, current.host.heldBody); }); waitForIdleSync();
        runOnMainSync(() -> {
            check(!field(current.panel, "dialog", AlertDialog.class).isShowing(), "dialog remains closed");
            check(field(current.panel, "rows", LinearLayout.class).getChildCount() == 0, "closed rows cleared and late callback ignored");
        });
    }
    private void binding() throws Exception {
        for (int mode = 0; mode < 5; mode++) {
            ReceiptDetailsTestActivity current = open("en", false, 1); final int variant = mode;
            runOnMainSync(() -> {
                current.host.hold = true; click("refresh");
                if (variant == 0) current.host.account = new AccountScope("https://receipt-details.invalid", "isolated_receipts", 8);
                if (variant == 1) current.host.member++;
                if (variant == 2) current.host.generation++;
                if (variant == 3) current.host.room++;
                if (variant == 4) current.host.message++;
                current.host.heldReply.complete(200, current.host.heldBody);
            }); waitForIdleSync();
            runOnMainSync(() -> {
                check(!field(current.panel, "dialog", AlertDialog.class).isShowing(), "binding change closes " + variant);
                check(field(current.panel, "rows", LinearLayout.class).getChildCount() == 0, "no late crossbinding rows " + variant);
                int before = current.host.afterIds.size(); click("refresh");
                check(current.host.afterIds.size() == before, "no new crossbinding HTTP " + variant);
            });
        }
    }
    private void failures() throws Exception {
        ReceiptDetailsTestActivity current = open("ar", false, 1);
        runOnMainSync(() -> { current.host.override = fresh(); try { current.host.override.put("membership_id", 99); }
            catch (Exception impossible) { throw new AssertionError(impossible); } click("refresh"); }); settle();
        runOnMainSync(() -> {
            check(field(current.panel, "notice", TextView.class).getText().toString().equals(current.getString(R.string.receipt_details_unconfirmed)), "malformed does not render new state");
            current.host.status = 403; click("refresh");
        }); settle();
        runOnMainSync(() -> {
            check(field(current.panel, "rows", LinearLayout.class).getChildCount() == 0, "server denial clears prior page");
            check(field(current.panel, "notice", TextView.class).getText().toString().equals(current.getString(R.string.receipt_details_unavailable)), "denial not offline");
            current.host.dispatch = false; click("refresh");
            check(!field(current.panel, "busy", Boolean.class), "dispatch rejection settles busy");
        });
    }
    private void background() throws Exception {
        ReceiptDetailsTestActivity current = open("en", false, 1);
        runOnMainSync(() -> { current.host.background = true; click("refresh"); }); settle();
        runOnMainSync(() -> check(field(current.panel, "rows", LinearLayout.class).getChildCount() == 3, "background response renders safely on main"));
    }
    private void click(String field) { field(activity.panel, field, Button.class).performClick(); }
    private void settle() throws Exception { waitFor(() -> !field(activity.panel, "busy", Boolean.class), "GET settles"); waitForIdleSync(); }
    private void close() {
        if (activity == null) return; ReceiptDetailsTestActivity previous = activity;
        runOnMainSync(() -> { previous.panel.dismiss(); previous.finish(); }); waitForIdleSync(); activity = null;
    }
    private interface Journey { void run() throws Exception; }
    private void journey(String name, Journey action) {
        int before = failures.size();
        try { action.run(); } catch (Throwable invalid) { failures.add(name + ": " + invalid); }
        try { journeys.put(new JSONObject().put("case", name).put("passed", failures.size() == before)); }
        catch (Exception invalid) { throw new AssertionError(invalid); }
        close();
    }
    private void check(boolean ok, String label) { assertions++; if (!ok) failures.add(label); }
    private void require(boolean ok, String label) { check(ok, label); if (!ok) throw new AssertionError(label); }
    private void waitFor(BooleanSupplier predicate, String label) throws Exception { waitFor(predicate, label, 3000); }
    private void waitFor(BooleanSupplier predicate, String label, long timeout) throws Exception {
        long deadline = SystemClock.uptimeMillis() + timeout;
        while (SystemClock.uptimeMillis() < deadline) {
            final boolean[] ready = {false}; runOnMainSync(() -> ready[0] = predicate.getAsBoolean());
            if (ready[0]) return; SystemClock.sleep(20);
        }
        throw new AssertionError("Deadline: " + label);
    }
    private void capture(View decor, String name) {
        Bitmap frame = Bitmap.createBitmap(decor.getWidth(), decor.getHeight(), Bitmap.Config.ARGB_8888);
        decor.draw(new Canvas(frame));
        try (FileOutputStream stream = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) {
            require(frame.compress(Bitmap.CompressFormat.PNG, 100, stream), "native Dialog-decor capture");
        } catch (Exception invalid) { throw new AssertionError(invalid); }
        finally { frame.recycle(); }
    }
    private void write(String name, byte[] bytes) throws Exception {
        try (FileOutputStream stream = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) { stream.write(bytes); }
    }
    static <T> T field(Object target, String name, Class<T> type) {
        try { Field member = target.getClass().getDeclaredField(name); member.setAccessible(true); return type.cast(member.get(target)); }
        catch (Exception invalid) { throw new AssertionError(invalid); }
    }
    private String repeat(String value, int count) { StringBuilder result = new StringBuilder(); for (int index = 0; index < count; index++) result.append(value); return result.toString(); }
}

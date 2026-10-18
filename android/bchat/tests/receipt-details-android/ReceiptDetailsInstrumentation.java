package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Instrumentation;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.text.Layout;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewTreeObserver;
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
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import org.json.JSONArray;
import org.json.JSONObject;

/** Android35 Dialog/JSONObject/Activity checks; all session/network replies are explicit fake Host data. */
public final class ReceiptDetailsInstrumentation extends Instrumentation {
    private final List<String> failures = new ArrayList<>();
    private final JSONArray renders = new JSONArray(), journeys = new JSONArray(), timeGeometryTrace = new JSONArray(), timeMiddleTrace = new JSONArray();
    private int assertions, protocolAccepts, protocolRejects;
    private boolean displayTimeOnly, displayTimeMiddleOnly;
    private ReceiptDetailsTestActivity activity;
    @Override public void runOnMainSync(Runnable action) {
        Throwable[] failure = {null};
        super.runOnMainSync(() -> { try { action.run(); } catch (Throwable error) { failure[0] = error; } });
        if (failure[0] != null) throw new AssertionError("Synchronous fixture MAIN action failed", failure[0]);
    }
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments == null || !"true".equals(arguments.getString("disposable")))
            throw new IllegalArgumentException("Explicit disposable test package required");
        String selection = arguments.getString("selection", "all");
        if (!selection.equals("all") && !selection.equals("display-time") && !selection.equals("display-time-middle")) throw new IllegalArgumentException("Bounded receipt selection required");
        displayTimeMiddleOnly = selection.equals("display-time-middle");
        displayTimeOnly = selection.equals("display-time") || displayTimeMiddleOnly;
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            check(getTargetContext().getPackageName().equals("com.baseer.bchat.receipt.details.test"), "isolated test package");
            check(android.os.Build.VERSION.SDK_INT == 35, "Android35 runtime");
            if (displayTimeMiddleOnly) {
                renderTimeMiddle("ar"); renderTimeMiddle("en");
            } else if (displayTimeOnly) {
                render("ar", true, 2f); render("en", true, 2f);
            } else {
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
            }
        } catch (Throwable error) { failures.add("Harness: " + error); }
        finally { close(); }
        try {
            JSONObject proof = new JSONObject().put("schema", 1).put("android_api", android.os.Build.VERSION.SDK_INT)
                    .put("package", getTargetContext().getPackageName()).put("assertions", assertions)
                    .put("protocol_acceptances", protocolAccepts).put("protocol_rejections", protocolRejects)
                    .put("renders", renders).put("journeys", journeys).put("failures", new JSONArray(failures))
                    .put("selection", displayTimeMiddleOnly ? "display-time-middle" : displayTimeOnly ? "display-time" : "all")
                    .put("time_geometry_trace", timeGeometryTrace)
                    .put("time_middle_trace", timeMiddleTrace)
                    .put("scope", displayTimeMiddleOnly ? "Two supplemental actual timestamp TextView/native ScrollView/preDraw/Layout visibility renders; same fake GET data and same 320dp dark font2 Context. Supplemental Canvas frames, not OS screenshots. No top/bottom/old journeys/protocol suite/auth/HTTP/ACK/FCM/SQLite/product Activity/phone/performance claim."
                            : "Actual native Activity/Dialog/JSONObject/SharedPreferences locale; fake session Host; no real HTTP/ACK/FCM/SQLite/product Activity or device-delivery claim")
                    .put("passed", failures.isEmpty());
            write("receipt-details-results.json", proof.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Throwable error) { failures.add("Evidence: " + error); }
        result.putString("stream", (failures.isEmpty() ? (displayTimeMiddleOnly ? "PASS 2 supplemental Android receipt middle renders; " : displayTimeOnly ? "PASS 2 actual Android receipt time renders; " : "PASS 8 actual Android receipt detail renders and 9 focused journeys; ")
                + assertions + " assertions" : "FAIL receipt details: " + failures) + "\n");
        finish(failures.isEmpty() ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
    }
    private void renderTimeMiddle(String language) {
        String name = "receipt-details-" + language + "-dark-2.0-middle"; int before = failures.size();
        try {
            ReceiptDetailsTestActivity current = open(language, true, 2f); AlertDialog dialog = field(current.panel, "dialog", AlertDialog.class);
            awaitDraw(dialog); final TextView[] target = new TextView[1]; final JSONObject[] measured = new JSONObject[1];
            runOnMainSync(() -> {
                View decor = dialog.getWindow().getDecorView(); ScrollView scroll = field(current.panel, "scroll", ScrollView.class);
                check(Math.abs(decor.getWidth() / current.getResources().getDisplayMetrics().density - 320) <= 2, name + ": same actual320dp Dialog");
                check(current.getResources().getConfiguration().fontScale == 2f && current.getResources().getConfiguration().getLocales().get(0).getLanguage().equals(language)
                        && ChatAppearance.dark(current) && AppLocale.rtl(current) == language.equals("ar"), name + ": same actual AR/EN dark font2");
                target[0] = firstTimeText(field(current.panel, "rows", LinearLayout.class)); require(target[0] != null, "First actual existing receipt timestamp TextView after GET");
                JSONObject initial = middleGeometry(target[0], scroll, decor, language, "before_native_scroll"); timeMiddleTrace.put(initial);
                require(target[0].getWidth() > 0 && target[0].getHeight() > 0 && target[0].getHeight() <= scroll.getHeight() - scroll.getPaddingTop() - scroll.getPaddingBottom(),
                        "Actual timestamp must fit unchanged scroll viewport; no resize or partial-visibility fallback");
                boolean requested = target[0].requestRectangleOnScreen(new Rect(0, 0, target[0].getWidth(), target[0].getHeight()), false);
                try { initial.put("native_request_rectangle_scrolled", requested); } catch (Exception error) { throw new AssertionError(error); }
            });
            try {
                waitFor(() -> { Rect visible = new Rect(); return target[0].getLocalVisibleRect(visible) && visible.equals(new Rect(0, 0, target[0].getWidth(), target[0].getHeight())); }, "First actual timestamp fully visible after native rectangle request", 3000);
                awaitDraw(dialog);
            } finally {
                runOnMainSync(() -> { measured[0] = middleGeometry(target[0], field(current.panel, "scroll", ScrollView.class), dialog.getWindow().getDecorView(), language, "after_native_scroll_and_preDraw"); timeMiddleTrace.put(measured[0]); });
            }
            runOnMainSync(() -> {
                requireMiddleVisible(measured[0]); inspect(target[0], dialog.getWindow().getDecorView(), name);
                capture(dialog.getWindow().getDecorView(), name + ".png");
                try { renders.put(new JSONObject().put("case", name).put("language", language).put("locale_actual", current.getResources().getConfiguration().getLocales().get(0).toLanguageTag()).put("dark", ChatAppearance.dark(current))
                        .put("font_scale", current.getResources().getConfiguration().fontScale).put("logical_width_dp", dialog.getWindow().getDecorView().getWidth() / current.getResources().getDisplayMetrics().density)
                        .put("frames", new JSONArray().put(name + ".png")).put("middle_geometry", measured[0]).put("passed", failures.size() == before)); }
                catch (Exception error) { throw new AssertionError(error); }
            });
        } catch (Throwable error) { failures.add(name + ": " + error); }
        finally { close(); }
    }
    private TextView firstTimeText(View view) {
        if (view instanceof TextView && ((TextView)view).getText().toString().contains("\u20662026-10-18 · 01:02:03 UTC\u2069")) return (TextView)view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); ++i) { TextView found = firstTimeText(((ViewGroup)view).getChildAt(i)); if (found != null) return found; }
        return null;
    }
    private JSONObject middleGeometry(TextView target, ScrollView scroll, View decor, String language, String phase) {
        try {
            Rect local = new Rect(), global = new Rect(), frame = new Rect(); android.graphics.Point globalOffset = new android.graphics.Point();
            boolean localVisible = target.getLocalVisibleRect(local), globalVisible = target.getGlobalVisibleRect(global, globalOffset);
            int[] point = new int[2], rootPoint = new int[2], decorPoint = new int[2], windowPoint = new int[2]; target.getLocationOnScreen(point); target.getRootView().getLocationOnScreen(rootPoint); decor.getLocationOnScreen(decorPoint); target.getLocationInWindow(windowPoint); decor.getWindowVisibleDisplayFrame(frame);
            Rect full = new Rect(point[0], point[1], point[0] + target.getWidth(), point[1] + target.getHeight()), clipped = new Rect(local); clipped.offset(point[0], point[1]);
            boolean identity = true; JSONArray ancestors = new JSONArray(); View current = target;
            while (true) {
                boolean currentIdentity = current.getMatrix().isIdentity(); identity &= currentIdentity; int[] at = new int[2]; current.getLocationOnScreen(at);
                ancestors.put(new JSONObject().put("class", current.getClass().getName()).put("matrix_identity", currentIdentity).put("matrix", current.getMatrix().toShortString())
                        .put("location_screen", new JSONArray().put(at[0]).put(at[1])).put("size", new JSONArray().put(current.getWidth()).put(current.getHeight()))
                        .put("scroll", new JSONArray().put(current.getScrollX()).put(current.getScrollY())).put("padding", new JSONArray().put(current.getPaddingLeft()).put(current.getPaddingTop()).put(current.getPaddingRight()).put(current.getPaddingBottom())));
                android.view.ViewParent parent = current.getParent(); if (!(parent instanceof View)) break; current = (View)parent;
            }
            Layout layout = target.getLayout(); JSONArray lineWidths = new JSONArray(), ellipses = new JSONArray();
            if (layout != null) for (int i = 0; i < layout.getLineCount(); ++i) { lineWidths.put(layout.getLineMax(i)); ellipses.put(layout.getEllipsisCount(i)); }
            return new JSONObject().put("phase", phase).put("language", language).put("actual_text", target.getText().toString()).put("target_size_px", new JSONArray().put(target.getWidth()).put(target.getHeight()))
                    .put("scroll_inner_height", scroll.getHeight() - scroll.getPaddingTop() - scroll.getPaddingBottom()).put("local_visible", localVisible).put("local_visible_rect", rect(local))
                    .put("raw_global_visible", globalVisible).put("raw_global_rect_root_space", rect(global)).put("global_offset_root_space", new JSONArray().put(globalOffset.x).put(globalOffset.y))
                    .put("location_screen", new JSONArray().put(point[0]).put(point[1])).put("location_window", new JSONArray().put(windowPoint[0]).put(windowPoint[1]))
                    .put("root_location_screen", new JSONArray().put(rootPoint[0]).put(rootPoint[1])).put("decor_location_screen", new JSONArray().put(decorPoint[0]).put(decorPoint[1]))
                    .put("full_rect_screen", rect(full)).put("clipped_rect_screen", rect(clipped)).put("visible_frame_screen", rect(frame)).put("transform_identity", identity).put("view_ancestors", ancestors)
                    .put("layout_present", layout != null).put("line_count", layout == null ? 0 : layout.getLineCount()).put("line_max_px", lineWidths).put("line_ellipsis_counts", ellipses)
                    .put("layout_width", layout == null ? 0 : layout.getWidth()).put("layout_height", layout == null ? 0 : layout.getHeight()).put("compound_padding_top", target.getCompoundPaddingTop()).put("compound_padding_bottom", target.getCompoundPaddingBottom())
                    .put("max_lines", target.getMaxLines()).put("ellipsize_is_null", target.getEllipsize() == null).put("shown", target.isShown()).put("attached", target.isAttachedToWindow());
        } catch (Exception error) { throw new AssertionError(error); }
    }
    private void requireMiddleVisible(JSONObject measured) {
        try {
            int width = measured.getJSONArray("target_size_px").getInt(0), height = measured.getJSONArray("target_size_px").getInt(1);
            Rect local = measuredRect(measured.getJSONObject("local_visible_rect")), full = measuredRect(measured.getJSONObject("full_rect_screen")), clipped = measuredRect(measured.getJSONObject("clipped_rect_screen")), frame = measuredRect(measured.getJSONObject("visible_frame_screen"));
            require(measured.getString("actual_text").contains("\u20662026-10-18 · 01:02:03 UTC\u2069") && !measured.getString("actual_text").contains("2026-10-18 01:02:03"), "Exact actual isolated timestamp, no replacement fixture date");
            require(measured.getBoolean("transform_identity") && measured.getBoolean("local_visible") && measured.getBoolean("shown") && measured.getBoolean("attached")
                    && width > 0 && height > 0 && local.equals(new Rect(0, 0, width, height)) && full.equals(clipped) && frame.contains(full), "Actual entire timestamp TextView visible in one screen coordinate system, no OR/shift/resize");
            require(measured.getBoolean("layout_present") && measured.getBoolean("ellipsize_is_null") && measured.getInt("max_lines") > 1 && measured.getInt("line_count") > 0, "Actual timestamp multiline Layout exists without ellipsis policy");
            for (int i = 0; i < measured.getInt("line_count"); ++i) require(measured.getJSONArray("line_ellipsis_counts").getInt(i) == 0 && measured.getJSONArray("line_max_px").getDouble(i) <= measured.getInt("layout_width") + 2, "Every actual timestamp line readable without horizontal glyph clipping");
            require(measured.getInt("layout_height") + measured.getInt("compound_padding_top") + measured.getInt("compound_padding_bottom") <= height + 2, "All timestamp lines fit its unchanged actual TextView height");
        } catch (Exception error) { throw new AssertionError(error); }
    }
    private Rect measuredRect(JSONObject value) throws Exception { return new Rect(value.getInt("left"), value.getInt("top"), value.getInt("right"), value.getInt("bottom")); }
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
        ReceiptDetailsTestActivity.language = language; ReceiptDetailsTestActivity.dark = dark; ReceiptDetailsTestActivity.scale = scale; ReceiptDetailsTestActivity.viewportDp = displayTimeOnly ? 320 : 360;
        activity = (ReceiptDetailsTestActivity) startActivitySync(new Intent(getTargetContext(), ReceiptDetailsTestActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitFor(() -> !field(activity.panel, "busy", Boolean.class), "initial GET settles"); waitForIdleSync(); return activity;
    }
    private void render(String language, boolean dark, float scale) {
        String name = "receipt-details-" + language + "-" + (dark ? "dark" : "light") + "-" + scale;
        int before = failures.size();
        try {
            ReceiptDetailsTestActivity current = open(language, dark, scale);
            if (displayTimeOnly) awaitDraw(field(current.panel, "dialog", AlertDialog.class));
            final JSONObject[] displayGeometry = new JSONObject[2];
            runOnMainSync(() -> {
                AlertDialog dialog = field(current.panel, "dialog", AlertDialog.class); View decor = dialog.getWindow().getDecorView();
                ScrollView scroll = field(current.panel, "scroll", ScrollView.class);
                float dp = decor.getWidth() / current.getResources().getDisplayMetrics().density;
                check(Math.abs(dp - (displayTimeOnly ? 320 : 360)) <= 2, name + ": actual configured Dialog width=" + dp);
                check(Math.abs(current.getResources().getConfiguration().fontScale - scale) < .01, name + ": font scale");
                check(ChatAppearance.dark(current) == dark, name + ": actual theme");
                check(AppLocale.rtl(current) == language.equals("ar"), name + ": actual locale direction");
                check(field(current.panel, "rows", LinearLayout.class).getLayoutDirection() == AppLocale.direction(current), name + ": rows RTL/LTR");
                inspect(decor, decor, name);
                Button close = dialog.getButton(AlertDialog.BUTTON_NEGATIVE);
                check(close.getHeight() >= Ui.dp(current, 48) && close.isEnabled(), name + ": close accessible48dp");
                capture(decor, name + "-top.png");
                if (displayTimeOnly) displayGeometry[0] = timeGeometry(decor, false);
                check(scroll.canScrollVertically(1), name + ": bounded vertical scrolling"); scroll.fullScroll(View.FOCUS_DOWN);
            });
            waitFor(() -> !field(current.panel, "scroll", ScrollView.class).canScrollVertically(1), "bottom reachable", 2500);
            if (displayTimeOnly) awaitDraw(field(current.panel, "dialog", AlertDialog.class));
            runOnMainSync(() -> {
                AlertDialog dialog = field(current.panel, "dialog", AlertDialog.class);
                if (displayTimeOnly) { inspect(dialog.getWindow().getDecorView(), dialog.getWindow().getDecorView(), name + "-bottom"); displayGeometry[1] = timeGeometry(dialog.getWindow().getDecorView(), true); }
                capture(dialog.getWindow().getDecorView(), name + "-bottom.png");
                try { renders.put(new JSONObject().put("case", name).put("language", language).put("dark", dark)
                        .put("font_scale", scale).put("density_dpi", current.getResources().getConfiguration().densityDpi)
                        .put("logical_width_dp", dialog.getWindow().getDecorView().getWidth() / current.getResources().getDisplayMetrics().density)
                        .put("time_geometry_top", displayGeometry[0] == null ? JSONObject.NULL : displayGeometry[0]).put("time_geometry_bottom", displayGeometry[1] == null ? JSONObject.NULL : displayGeometry[1])
                        .put("frames", new JSONArray(new String[]{name + "-top.png", name + "-bottom.png"}))
                        .put("passed", failures.size() == before)); }
                catch (Exception invalid) { throw new AssertionError(invalid); }
            });
        } catch (Throwable invalid) { failures.add(name + ": " + invalid); }
        finally { close(); }
    }
    private JSONObject timeGeometry(View decor, boolean bottom) {
        try {
            JSONArray timestamps = new JSONArray(); collectTimeGeometry(decor, timestamps);
            require(timestamps.length() == 2, "Actual receipt timestamp TextViews rendered, including both same-second states");
            require(!textTree(decor).contains("2026-10-18 01:02:03"), "Actual receipt text no longer exposes raw wire spacing");
            require(textTree(decor).contains(activity.getString(R.string.receipt_details_not_confirmed)), "Null receipt keeps existing localized fallback");
            Button footer = field(activity.panel, "refresh", Button.class); Rect local = new Rect(), global = new Rect(), frame = new Rect();
            boolean localVisible = footer.getLocalVisibleRect(local); android.graphics.Point globalOffset = new android.graphics.Point(); boolean globalVisible = footer.getGlobalVisibleRect(global, globalOffset);
            int[] point = new int[2], rootPoint = new int[2], decorPoint = new int[2], windowPoint = new int[2]; footer.getLocationOnScreen(point); footer.getRootView().getLocationOnScreen(rootPoint); decor.getLocationOnScreen(decorPoint); footer.getLocationInWindow(windowPoint); decor.getWindowVisibleDisplayFrame(frame);
            Rect full = new Rect(point[0], point[1], point[0] + footer.getWidth(), point[1] + footer.getHeight()), clipped = new Rect(local); clipped.offset(point[0], point[1]);
            boolean identity = true; JSONArray ancestors = new JSONArray(); View current = footer;
            while (true) {
                boolean currentIdentity = current.getMatrix().isIdentity(); identity &= currentIdentity; int[] at = new int[2]; current.getLocationOnScreen(at);
                ancestors.put(new JSONObject().put("class", current.getClass().getName()).put("matrix_identity", currentIdentity).put("matrix", current.getMatrix().toShortString())
                        .put("location_screen", new JSONArray().put(at[0]).put(at[1])).put("size", new JSONArray().put(current.getWidth()).put(current.getHeight()))
                        .put("scroll", new JSONArray().put(current.getScrollX()).put(current.getScrollY())).put("padding", new JSONArray().put(current.getPaddingLeft()).put(current.getPaddingTop()).put(current.getPaddingRight()).put(current.getPaddingBottom())));
                android.view.ViewParent parent = current.getParent(); if (!(parent instanceof View)) break; current = (View)parent;
            }
            JSONObject measured = new JSONObject().put("phase", bottom ? "bottom" : "top").put("language", activity.getResources().getConfiguration().getLocales().get(0).toLanguageTag())
                    .put("timestamp_textviews", timestamps).put("footer_global_visible", globalVisible).put("footer_local_visible", localVisible).put("footer_transform_identity", identity)
                    .put("footer_transform_assumption", "All footer-to-root View matrices are identity; local visible rect is offset by actual getLocationOnScreen. No compositor-transform claim or expected shift.")
                    .put("footer_local_visible_rect", rect(local)).put("footer_raw_global_rect_root_space", rect(global)).put("footer_global_offset_root_space", new JSONArray().put(globalOffset.x).put(globalOffset.y))
                    .put("footer_location_screen", new JSONArray().put(point[0]).put(point[1])).put("footer_location_window", new JSONArray().put(windowPoint[0]).put(windowPoint[1]))
                    .put("footer_root_location_screen", new JSONArray().put(rootPoint[0]).put(rootPoint[1])).put("dialog_decor_location_screen", new JSONArray().put(decorPoint[0]).put(decorPoint[1]))
                    .put("footer_visible_frame_screen", rect(frame)).put("footer_view_ancestors", ancestors).put("footer_full", rect(full)).put("footer_clipped", rect(clipped));
            timeGeometryTrace.put(measured); // Preserve raw measurements even if the footer assertion fails.
            if (bottom) require(identity && localVisible && footer.getWidth() > 0 && footer.getHeight() >= Ui.dp(activity, 48)
                    && local.equals(new Rect(0, 0, footer.getWidth(), footer.getHeight())) && clipped.equals(full) && frame.contains(full), "Actual refresh footer fully reachable in one screen coordinate system, no transform/inset compensation");
            return measured;
        } catch (Exception error) { throw new AssertionError(error); }
    }
    private void collectTimeGeometry(View view, JSONArray rows) throws Exception {
        if (view instanceof TextView && ((TextView)view).getText().toString().contains("\u20662026-10-18 · 01:02:03 UTC\u2069")) {
            TextView text = (TextView)view; Layout layout = text.getLayout(); require(layout != null && text.getMaxLines() > 1 && text.getEllipsize() == null, "Actual multiline timestamp layout, no ellipsis policy");
            int[] point = new int[2]; text.getLocationOnScreen(point); Rect visible = new Rect(); boolean shown = text.getGlobalVisibleRect(visible); JSONArray lines = new JSONArray();
            for (int i = 0; i < layout.getLineCount(); ++i) { require(layout.getEllipsisCount(i) == 0 && layout.getLineMax(i) <= layout.getWidth() + 2, "Actual timestamp glyphs not horizontally clipped"); lines.put(layout.getLineMax(i)); }
            require(layout.getHeight() + text.getCompoundPaddingTop() + text.getCompoundPaddingBottom() <= text.getHeight() + 2, "Actual timestamp layout not vertically clipped");
            rows.put(new JSONObject().put("text", text.getText().toString()).put("line_count", layout.getLineCount()).put("line_max_px", lines).put("layout_width", layout.getWidth()).put("layout_height", layout.getHeight()).put("view_height", text.getHeight())
                    .put("compound_padding_top", text.getCompoundPaddingTop()).put("compound_padding_bottom", text.getCompoundPaddingBottom())
                    .put("full", rect(new Rect(point[0], point[1], point[0] + text.getWidth(), point[1] + text.getHeight()))).put("global_visible", shown).put("clipped", rect(visible)));
        }
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); ++i) collectTimeGeometry(((ViewGroup)view).getChildAt(i), rows);
    }
    private JSONObject rect(Rect value) throws Exception { return new JSONObject().put("left", value.left).put("top", value.top).put("right", value.right).put("bottom", value.bottom); }
    private String textTree(View view) { StringBuilder text = new StringBuilder(); if (view instanceof TextView) text.append(((TextView)view).getText()); if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); ++i) text.append(textTree(((ViewGroup)view).getChildAt(i))); return text.toString(); }
    private void awaitDraw(AlertDialog dialog) throws Exception {
        CountDownLatch drawn = new CountDownLatch(1);
        runOnMainSync(() -> { View decor = dialog.getWindow().getDecorView(); decor.getViewTreeObserver().addOnPreDrawListener(new ViewTreeObserver.OnPreDrawListener() {
            public boolean onPreDraw() { if (decor.isAttachedToWindow() && decor.getWidth() > 0 && decor.getHeight() > 0) { decor.getViewTreeObserver().removeOnPreDrawListener(this); drawn.countDown(); } return true; }
        }); decor.requestLayout(); decor.postInvalidateOnAnimation(); }); require(drawn.await(3, TimeUnit.SECONDS), "Actual receipt preDraw and positive layout before measurement"); waitForIdleSync();
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

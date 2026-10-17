package com.baseer.freshchat;

import android.app.Activity;
import android.app.Dialog;
import android.app.Instrumentation;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

public final class CartSheetInstrumentation extends Instrumentation {
    private int checks;
    private final JSONArray renders = new JSONArray();
    private final List<String> failures = new ArrayList<>();
    private CartSheetTestActivity activity;
    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        if (args == null || !"true".equals(args.getString("disposable"))) throw new IllegalArgumentException("Test-only package required");
        start();
    }
    @Override public void onStart() {
        try {
            check("com.baseer.bchat.cart.sheet.test".equals(getTargetContext().getPackageName()), "isolated package");
            check(android.os.Build.VERSION.SDK_INT == 35, "Android35 actual runtime");
            for (String language : new String[]{"ar", "en"})
                for (boolean dark : new boolean[]{false, true})
                    for (float scale : new float[]{1f, 2f}) render(language, dark, scale);
        } catch (Throwable error) { failures.add(error.toString()); }
        finally { close(); }
        Bundle result = new Bundle();
        try {
            JSONObject evidence = new JSONObject().put("schema", 1).put("passed", failures.isEmpty())
                    .put("assertions", checks).put("renders", renders).put("failures", new JSONArray(failures))
                    .put("scope", "Actual Android35 Dialog/ScrollView/production cart line and quantity components, 20 synthetic products, AR/EN light/dark font1/2 and native IME. Fake action/quote/editor Host; no product Activity, amount math, financial API, order creation or device/OEM acceptance");
            write("cart-sheet-results.json", evidence.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Throwable error) { failures.add(error.toString()); }
        result.putString("stream", (failures.isEmpty() ? "PASS " + checks + " actual Android cart presentation checks" : "FAIL " + failures) + "\n");
        finish(failures.isEmpty() ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
    }
    private void render(String language, boolean dark, float scale) throws Exception {
        CartSheetTestActivity.language = language; CartSheetTestActivity.dark = dark; CartSheetTestActivity.scale = scale;
        check(new LocalSettings(getTargetContext()).language(language), "fixture locale durable");
        activity = (CartSheetTestActivity) startActivitySync(new Intent(getTargetContext(), CartSheetTestActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitForIdleSync();
        String name = "cart-" + language + "-" + (dark ? "dark" : "light") + "-" + scale;
        Dialog dialog = field(activity.sheet, "dialog", Dialog.class);
        View root = dialog.getWindow().getDecorView();
        ScrollView scroll = find(root, ScrollView.class);
        check(dialog.isShowing() && scroll != null && scroll.getHeight() > 0, "visible scroll viewport");
        check(activity.steppers.size() == 20, "twenty actual cart components");
        runOnMainSync(() -> {
            for (View stepper : activity.steppers) {
                check(stepper.getWidth() > 0 && stepper.getMeasuredHeight() >= Ui.dp(activity, 48), "stepper measurable 48dp");
                List<TextView> texts = all(stepper, TextView.class);
                check(texts.size() == 3, "three quantity actions");
                for (TextView text : texts) {
                    check(text.getWidth() >= Ui.dp(activity, 48) && text.getHeight() >= Ui.dp(activity, 48), "action target 48dp");
                    check(text.getLayout() != null && text.getLayout().getLineEnd(text.getLineCount() - 1) == text.length(), "whole quantity/action visible in layout");
                    check(text.getEllipsize() == null, "expanded quantity not ellipsized");
                    Rect child = new Rect(); text.getHitRect(child);
                    check(child.left >= 0 && child.right <= stepper.getWidth(), "no horizontal overflow");
                }
            }
        });
        capture(root, name + "-top.png");
        runOnMainSync(() -> scroll.fullScroll(View.FOCUS_DOWN)); waitForIdleSync();
        Button submit = button(root, activity.getString(R.string.order_submit));
        Button more = button(root, activity.getString(R.string.order_add_more));
        check(submit != null && more != null, "two full-width actions");
        waitVisible(submit, more);
        check(visible(submit) && visible(more), "bottom actions reachable after scroll");
        capture(root, name + "-bottom.png");
        runOnMainSync(() -> { activity.sheet.setSubmitEnabled(false); submit.performClick(); });
        check(activity.submitted == 0 && activity.sheet.isShowing(), "disabled action no submission");
        runOnMainSync(() -> { activity.sheet.setSubmitEnabled(true); });
        if ("ar".equals(language) && !dark && scale == 2f) {
            runOnMainSync(() -> { scroll.fullScroll(View.FOCUS_UP); }); waitForIdleSync();
            waitVisible(activity.steppers.get(0));
            runOnMainSync(() -> ((TextView) activity.steppers.get(0).getChildAt(2)).performClick());
            waitForIdleSync();
            boolean ime = false;
            for (int attempt = 0; attempt < 25 && !ime; ++attempt) {
                final boolean[] shown = {false};
                runOnMainSync(() -> {
                    WindowInsets insets = activity.editorInput.getRootWindowInsets();
                    shown[0] = insets != null && insets.isVisible(WindowInsets.Type.ime());
                });
                ime = shown[0]; if (!ime) SystemClock.sleep(80);
            }
            check(ime && activity.edited == 1, "native numeric IME observed via real edit action");
            runOnMainSync(() -> activity.editor.dismiss()); waitForIdleSync();
            runOnMainSync(() -> scroll.fullScroll(View.FOCUS_DOWN)); waitForIdleSync();
            waitVisible(submit);
            check(visible(submit), "submit accessible after IME dismissal");
        }
        runOnMainSync(submit::performClick); waitForIdleSync();
        check(activity.submitted == 1 && activity.dismissed == 1 && !dialog.isShowing(), "one callback and dismissal");
        renders.put(new JSONObject().put("name", name).put("products", 20).put("width", root.getWidth())
                .put("height", root.getHeight()).put("font_scale", scale));
        close();
    }
    private boolean visible(View view) { Rect rect = new Rect(); return view.getGlobalVisibleRect(rect) && rect.height() >= view.getHeight() - 1; }
    private void waitVisible(View... views) {
        for (int attempt = 0; attempt < 50; ++attempt) {
            final boolean[] ready = {true};
            runOnMainSync(() -> { for (View view : views) ready[0] &= visible(view); });
            if (ready[0]) return;
            SystemClock.sleep(40); waitForIdleSync();
        }
        StringBuilder detail = new StringBuilder("visibility timeout");
        runOnMainSync(() -> { for (View view : views) { Rect rect = new Rect(); view.getGlobalVisibleRect(rect); detail.append(' ').append(view.getClass().getSimpleName()).append(':').append(rect).append(" height=").append(view.getHeight()); } });
        throw new AssertionError(detail.toString());
    }
    private void capture(View root, String name) throws Exception {
        final Bitmap[] bitmap = {null};
        runOnMainSync(() -> { bitmap[0] = Bitmap.createBitmap(root.getWidth(), root.getHeight(), Bitmap.Config.ARGB_8888); root.draw(new Canvas(bitmap[0])); });
        try (FileOutputStream output = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) { bitmap[0].compress(Bitmap.CompressFormat.PNG, 100, output); }
        bitmap[0].recycle();
    }
    private void close() {
        if (activity == null) return;
        runOnMainSync(() -> { if (activity.editor != null) activity.editor.dismiss(); activity.sheet.dismiss(); activity.finish(); });
        waitForIdleSync(); activity = null;
    }
    private void write(String name, byte[] bytes) throws Exception { try (FileOutputStream out = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) { out.write(bytes); } }
    private void check(boolean condition, String label) { ++checks; if (!condition) throw new AssertionError(label); }
    private static <T> T field(Object target, String name, Class<T> type) throws Exception { Field field = target.getClass().getDeclaredField(name); field.setAccessible(true); return type.cast(field.get(target)); }
    private static <T> List<T> all(View root, Class<T> type) { List<T> values = new ArrayList<>(); if (type.isInstance(root)) values.add(type.cast(root)); if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) root).getChildCount(); i++) values.addAll(all(((ViewGroup) root).getChildAt(i), type)); return values; }
    private static <T> T find(View root, Class<T> type) { List<T> values = all(root, type); return values.isEmpty() ? null : values.get(0); }
    private static Button button(View root, String label) { for (Button button : all(root, Button.class)) if (label.contentEquals(button.getText())) return button; return null; }
}

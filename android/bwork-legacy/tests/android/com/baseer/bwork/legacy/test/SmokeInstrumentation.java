// Original Baseer offline demo. No network transport or real recipient data.
package com.baseer.bwork.legacy.test;

import android.app.*;
import android.content.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.util.*;

/**
 * Android device UI smoke checks. Explicitly run only on a disposable emulator test install.
 */
public final class SmokeInstrumentation extends Instrumentation {
    Activity activity;
    ArrayList<String> results = new ArrayList<>();
    Throwable failure;

    public void onCreate(Bundle args) {
        super.onCreate(args);
        start();
    }

    public void onStart() {
        Bundle out = new Bundle(); boolean passed = false;
        android.content.SharedPreferences preferences = getTargetContext().getSharedPreferences(com.baseer.bwork.legacy.compat.LegacyIdentity.SETTINGS, Context.MODE_PRIVATE);
        String previousLanguage = preferences.getString("interface-language", null);
        try {
            if (!preferences.edit().putString("interface-language", "ar").commit()) throw new AssertionError("Could not select Arabic test locale");
            runTests(); passed = true;
            out.putString("stream", "\nPASS " + results.size() + " Android UI checks\n" + String.join("\n", results) + "\n");
        } catch (Throwable e) {
            out.putString("stream", "\nFAILED after " + results.size() + " checks: " + android.util.Log.getStackTraceString(e) + "\n" + String.join("\n", results));
        } finally {
            android.content.SharedPreferences.Editor restore = preferences.edit();
            if (previousLanguage == null) restore.remove("interface-language"); else restore.putString("interface-language", previousLanguage);
            if (!restore.commit()) { passed = false; out.putString("restore_failure", "Could not restore original language preference"); }
            if (activity != null) try { ui(() -> activity.finish()); } catch (Throwable ignored) { }
        }
        finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, out);
    }

    String label(String key, Object... arguments) {
        int resource = activity.getResources().getIdentifier(key, "string", activity.getPackageName());
        if (resource == 0) throw new AssertionError("Missing resource: " + key);
        return arguments.length == 0 ? activity.getString(resource) : activity.getString(resource, arguments);
    }

    void ui(Runnable r) {
        failure = null;
        runOnMainSync(()->{
            try {
                r.run();
            } catch (Throwable t) {
                failure = t;
            }
        });
        if (failure != null) throw new RuntimeException(failure);
        waitForIdleSync();
        SystemClock.sleep(120);
    }

    void check(boolean ok, String name) {
        if (!ok) throw new AssertionError(name);
        results.add("PASS " + name);
    }

    View find(View root, java.util.function.Predicate<View> p) {
        if (p.test(root)) return root;
        if (root instanceof ViewGroup) {
            ViewGroup g = (ViewGroup)root;
            for (int i = 0; i < g.getChildCount(); i++) {
                View v = find(g.getChildAt(i), p);
                if (v != null) return v;
            }
        }
        return null;
    }

    View decor() {
        return activity.getWindow().getDecorView();
    }

    View text(String label) {
        return find(decor(), (v)->v instanceof TextView && ((TextView)v).getText().toString().equals(label));
    }

    EditText composer() {
        return (EditText)find(decor(), (v)->v instanceof EditText && "\u0627\u0643\u062a\u0628 \u0631\u0633\u0627\u0644\u0629".contentEquals(((EditText)v).getHint()));
    }

    void clickText(String label) {
        ui(()->{
            View v = text(label);
            if (v == null) throw new AssertionError("Missing text: " + label);
            View child = v;
            android.view.ViewParent parent = v.getParent();
            while (parent instanceof View) {
                if (parent instanceof ListView) {
                    ListView list = (ListView)parent;
                    int pos = list.getPositionForView(v);
                    list.performItemClick(child, pos, list.getAdapter().getItemId(pos));
                    return;
                }
                if (child.isClickable()) {
                    child.performClick();
                    return;
                }
                child = (View)parent;
                parent = parent.getParent();
            }
            throw new AssertionError("Unclickable: " + label);
        });
    }

    void back() {
        ui(()->activity.onBackPressed());
    }

    void launch(Intent i) {
        i.setComponent(new ComponentName("com.baseer.bchat.preview", "com.baseer.bwork.legacy.MainActivity"));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity = startActivitySync(i);
        waitForIdleSync();
        enterDemoIfPresent();
        SystemClock.sleep(250);
    }

    Object field(Object target, String name) {
        try {
            java.lang.reflect.Field field = target.getClass().getDeclaredField(name);
            field.setAccessible(true);
            return field.get(target);
        } catch (ReflectiveOperationException failure) { throw new AssertionError(failure); }
    }

    Object invoke(Object target, String name, Class<?>[] types, Object... values) {
        try {
            java.lang.reflect.Method method = target.getClass().getDeclaredMethod(name, types);
            method.setAccessible(true);
            return method.invoke(target, values);
        } catch (ReflectiveOperationException failure) { throw new AssertionError(failure); }
    }

    PopupWindow menuWindow() { return (PopupWindow)field(field(activity, "overflowMenu"), "popup"); }
    LinearLayout menuRows() { return (LinearLayout)field(field(activity, "overflowMenu"), "rows"); }
    String screen() { return (String)field(activity, "screen"); }

    void bottomNavigationChecks(String selected) {
        ui(() -> {
            LinearLayout root = (LinearLayout)field(activity, "root");
            LinearLayout tabs = (LinearLayout)root.findViewWithTag("bwork-bottom-navigation");
            check(tabs != null && tabs.getChildCount() == 3, "Exactly three bottom navigation destinations on " + selected);
            check(tabs.getParent() == root && root.getChildAt(root.getChildCount() - 1) == tabs,
                    "Navigation is the last root sibling, outside scroll content on " + selected);
            check(tabs.getBottom() == root.getHeight() - root.getPaddingBottom(), "Navigation rests at the content bottom on " + selected);
            View content = null;
            for (int index = 0; index < root.getChildCount(); index++) {
                View child = root.getChildAt(index);
                if (child instanceof ListView || child instanceof ScrollView) content = child;
            }
            check(content != null && content.getBottom() <= tabs.getTop(), "Scroll content cannot overlap bottom navigation on " + selected);
            LinearLayout.LayoutParams size = (LinearLayout.LayoutParams)content.getLayoutParams();
            check(size.height == 0 && size.weight == 1, "Main content occupies remaining space on " + selected);
            android.graphics.Rect visible = new android.graphics.Rect(); decor().getWindowVisibleDisplayFrame(visible);
            int[] location = new int[2]; tabs.getLocationOnScreen(location);
            check(location[1] + tabs.getHeight() <= visible.bottom, "Bottom navigation stays above system navigation on " + selected);
            String[] destinations = {"list", "orders", "tasks"};
            String[] labels = {label("ui_065"), label("ui_066"), label("ui_067")};
            for (int index = 0; index < destinations.length; index++) {
                TextView tab = (TextView)tabs.getChildAt(index);
                check(("bwork-section-" + destinations[index]).equals(tab.getTag()) && labels[index].contentEquals(tab.getText()),
                        "Localized destination order " + destinations[index]);
                check(tab.isSelected() == destinations[index].equals(selected), "Correct selected destination " + destinations[index]);
                check(tab.getHeight() >= Math.round(48 * activity.getResources().getDisplayMetrics().density), "48dp destination target " + destinations[index]);
            }
            check(tabs.getLayoutDirection() == root.getLayoutDirection(), "Bottom navigation follows interface direction");
            check(tabs.getChildAt(0).getLeft() > tabs.getChildAt(2).getLeft(), "Arabic destinations run right to left");
        });
    }

    void noBottomNavigation(String context) {
        ui(() -> check(decor().findViewWithTag("bwork-bottom-navigation") == null, "No main navigation inside " + context));
    }

    void openOverflow() {
        ui(() -> {
            View anchor = find(decor(), view -> "bwork-overflow".equals(view.getTag()));
            if (anchor == null) throw new AssertionError("Missing overflow anchor");
            anchor.performClick();
        });
    }

    // Actual Android execution is required. Source compilation is not a visual pass.
    void menuChecks() {
        openOverflow();
        final PopupWindow[] first = new PopupWindow[1];
        final View[] oldSettings = new View[1];
        ui(() -> {
            first[0] = menuWindow();
            check(first[0] != null && first[0].isShowing(), "Main overflow opens a PopupWindow");
            check(menuRows().getChildCount() == 7, "Main menu contains seven scoped rows, no modal heading");
            float density = activity.getResources().getDisplayMetrics().density;
            for (int index = 0; index < menuRows().getChildCount(); index++)
                check(menuRows().getChildAt(index).getHeight() >= Math.round(48 * density), "Menu row " + index + " is at least 48dp");
            check(!menuRows().getChildAt(3).isEnabled() && !menuRows().getChildAt(4).isEnabled(), "Backend-only main items are disabled");
            check(!menuRows().getChildAt(3).performClick(), "Disabled shift has no click action");
            WindowManager.LayoutParams layout = (WindowManager.LayoutParams)first[0].getContentView().getRootView().getLayoutParams();
            check((layout.flags & WindowManager.LayoutParams.FLAG_DIM_BEHIND) == 0, "Overflow has no modal dim layer");
            android.graphics.Rect visible = new android.graphics.Rect();
            decor().getWindowVisibleDisplayFrame(visible);
            check(first[0].getWidth() <= Math.round(288 * density) && first[0].getWidth() < visible.width(), "Menu width stays compact and inside window");
            View anchor = find(decor(), view -> "bwork-overflow".equals(view.getTag()));
            check(menuRows().getLayoutDirection() == anchor.getLayoutDirection(), "Menu inherits toolbar direction");
            oldSettings[0] = menuRows().getChildAt(5);
            menuRows().getChildAt(0).performClick();
        });
        ui(() -> {
            check(menuWindow() == first[0] && first[0].isShowing(), "Filter choices replace rows in the same popup");
            check(menuRows().getChildCount() == 5, "Filter page has back plus four choices");
            oldSettings[0].performClick();
            check("list".equals(screen()) && menuWindow() == first[0], "Callback from replaced page cannot navigate");
            menuRows().getChildAt(1).performClick();
        });
        ui(() -> check(menuWindow() == null && "all".equals(field(activity, "filter")), "Selecting filter closes popup and updates inbox"));
        openOverflow();
        back();
        ui(() -> check(menuWindow() == null && "list".equals(screen()), "Back closes overflow before navigating"));
        openOverflow();
        ui(() -> first[0] = menuWindow());
        openOverflow();
        ui(() -> {
            check(!first[0].isShowing() && menuWindow() != first[0], "Repeated open replaces rather than stacks menus");
            oldSettings[0] = menuRows().getChildAt(5);
            invoke(activity, "showModule", new Class<?>[]{String.class}, "tasks");
            check(menuWindow() == null, "Navigation dismisses original menu");
            oldSettings[0].performClick();
            check("tasks".equals(screen()), "Stale toolbar action cannot replace newer screen");
        });
        openOverflow();
        ui(() -> check(menuRows().getChildCount() == 6, "Tasks menu excludes inbox-only filter"));
        ui(() -> {
            callActivityOnPause(activity);
            check(menuWindow() == null, "Pause dismisses overflow");
            callActivityOnResume(activity);
            invoke(activity, "showList", new Class<?>[]{});
        });
    }

    void chatMenuChecks() {
        final String co = (String)field(activity, "companyId"), cv = (String)field(activity, "conversationId");
        final Object settings = field(activity, "settings");
        final Class<?>[] muteTypes = {String.class, String.class};
        final boolean before = (Boolean)invoke(settings, "mute", muteTypes, co, cv);
        openOverflow();
        ui(() -> {
            check(menuRows().getChildCount() == 8, "Chat/group overflow uses eight contextual rows");
            check(!menuRows().getChildAt(5).isEnabled() && !menuRows().getChildAt(6).isEnabled(), "Linked work remains disabled before backend");
            View staleMute = menuRows().getChildAt(4);
            invoke(activity, "showList", new Class<?>[]{});
            staleMute.performClick();
            check(before == (Boolean)invoke(settings, "mute", muteTypes, co, cv), "Detached chat action cannot mutate captured chat");
            invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, co, cv);
        });
    }

    void runTests() {
        launch(new Intent(Intent.ACTION_MAIN));
        ui(() -> {
            View brand = find(decor(), v -> "BWorkWordmarkView".equals(v.getClass().getSimpleName()));
            check(brand != null && "BWork".contentEquals(brand.getContentDescription())
                    && brand.isShown() && brand.getWidth() > 0 && brand.getHeight() > 0,
                    "BWork inbox starts with a visible accessible original-image/vector wordmark");
        });
        ui(()->check(text("المحادثات") != null && text("طلبات الشراء") != null && text("المهام") != null, "Three primary sections"));
        bottomNavigationChecks("list");
        menuChecks();
        clickText("طلبات الشراء");
        bottomNavigationChecks("orders");
        ui(()->check(text(label("preview_reference", "PO-DEMO-01")) != null, "Orders are explicitly synthetic previews"));
        ui(()->check(text("إنشاء طلب · غير متاح بعد") != null && !text("إنشاء طلب · غير متاح بعد").isEnabled(), "Real purchase creation disabled"));
        clickText("المهام");
        bottomNavigationChecks("tasks");
        ui(()->check(text(label("preview_reference", "TASK-DEMO-01")) != null, "Tasks are explicitly synthetic previews"));
        ui(()->check(text("إنشاء مهمة · غير متاح بعد") != null && !text("إنشاء مهمة · غير متاح بعد").isEnabled(), "Real task creation disabled"));
        clickText("المحادثات");
        bottomNavigationChecks("list");
        ui(() -> invoke(activity, "showSettings", new Class<?>[]{}));
        noBottomNavigation("settings");
        back();
        bottomNavigationChecks("list");

        clickText("\u0641\u0631\u064a\u0642 \u0627\u0644\u0639\u0645\u0644\u064a\u0627\u062a");
        ui(()->check(composer() != null, "Dedicated chat screen and composer"));
        noBottomNavigation("chat");
        chatMenuChecks();
        ui(()->composer().setText("\u0645\u0633\u0648\u062f\u0629 \u0623\u0644\u0641 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631"));
        back();
        bottomNavigationChecks("list");
        clickText("\u0633\u0627\u0631\u0629 \u0627\u0644\u062a\u062c\u0631\u064a\u0628\u064a\u0629");
        ui(()->check(composer().getText().toString().isEmpty(), "Different conversation has no leaked draft"));
        ui(()->composer().setText("\u0645\u0633\u0648\u062f\u0629 \u0628\u0627\u0621 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631"));
        back();
        clickText("\u0641\u0631\u064a\u0642 \u0627\u0644\u0639\u0645\u0644\u064a\u0627\u062a");
        ui(()->check(composer().getText().toString().equals("\u0645\u0633\u0648\u062f\u0629 \u0623\u0644\u0641 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631"), "Back retains original draft"));
        ui(()->{
            View send = find(decor(), (v)->"\u062d\u0641\u0638 \u0627\u0644\u0631\u0633\u0627\u0644\u0629 \u0645\u062d\u0644\u064a\u064b\u0627".equals(String.valueOf(v.getContentDescription())));
            send.performClick();
        });
        ui(()->check(composer().getText().toString().isEmpty(), "Send clears its own draft"));
        ui(()->check(text("\u0645\u0633\u0648\u062f\u0629 \u0623\u0644\u0641 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631") != null, "Sent text appears in local history"));
        back();
        clickText("\u0633\u0627\u0631\u0629 \u0627\u0644\u062a\u062c\u0631\u064a\u0628\u064a\u0629");
        ui(()->check(composer().getText().toString().equals("\u0645\u0633\u0648\u062f\u0629 \u0628\u0627\u0621 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631"), "Send preserved the other draft"));
        back();
        launch(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "\u0645\u0634\u0627\u0631\u0643\u0629 \u0646\u0635\u064a\u0629 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631"));
        ui(()->check(text("\u0625\u0631\u0633\u0627\u0644 \u0625\u0644\u0649\u2026") != null, "External SEND opens explicit recipient picker"));
        noBottomNavigation("share recipient picker");
        clickText("\u0633\u0627\u0631\u0629 \u0627\u0644\u062a\u062c\u0631\u064a\u0628\u064a\u0629");
        ui(()->check(text("\u0645\u0639\u0627\u064a\u0646\u0629 \u0642\u0628\u0644 \u0627\u0644\u0625\u0631\u0633\u0627\u0644") != null, "Recipient selection opens preview"));
        noBottomNavigation("share preview");
        ui(()->check(text("\u0627\u0644\u0645\u0633\u062a\u0644\u0645 \u0627\u0644\u0645\u062d\u062f\u062f") != null, "Preview labels explicit recipient"));
        back();
        ui(()->check(text("\u0625\u0631\u0633\u0627\u0644 \u0625\u0644\u0649\u2026") != null, "Back from preview returns to picker without sending"));
        clickText("\u0633\u0627\u0631\u0629 \u0627\u0644\u062a\u062c\u0631\u064a\u0628\u064a\u0629");
        clickText("\u0625\u0631\u0633\u0627\u0644 \u0625\u0644\u0649 \u0633\u0627\u0631\u0629 \u0627\u0644\u062a\u062c\u0631\u064a\u0628\u064a\u0629");
        ui(()->check(composer().getText().toString().equals("\u0645\u0633\u0648\u062f\u0629 \u0628\u0627\u0621 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631"), "Share send preserves target conversation draft"));
        ui(()->check(text("\u0645\u0634\u0627\u0631\u0643\u0629 \u0646\u0635\u064a\u0629 \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631") != null, "Explicit share send appears in chosen chat"));
        back();
        clickText("\u0641\u0631\u064a\u0642 \u0627\u0644\u0639\u0645\u0644\u064a\u0627\u062a");
        ui(()->{
            ScrollView sc = (ScrollView)find(decor(), (v)->v instanceof ScrollView);
            sc.fullScroll(View.FOCUS_UP);
        });
        clickText("\u0639\u0631\u0636 \u0631\u0633\u0627\u0626\u0644 \u0623\u0642\u062f\u0645");
        ui(()->check(composer() != null, "History pagination keeps chat usable"));
    }

    private void enterDemoIfPresent() {
        ui(() -> {
            View entry = activity.getWindow().getDecorView().findViewWithTag("bwork-explore-demo");
            if (entry != null && !entry.performClick()) throw new AssertionError("Demo entry was not clickable");
        });
    }
}

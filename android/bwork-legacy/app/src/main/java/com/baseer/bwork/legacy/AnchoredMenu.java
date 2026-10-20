// Original Baseer offline demo. No network transport or real recipient data.
package com.baseer.bwork.legacy;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Rect;
import android.os.Build;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.List;

/** A single, scrollable overflow surface attached to its original toolbar button. */
final class AnchoredMenu {
    interface Scope { boolean isCurrent(); }

    static final class Entry {
        final String label;
        final String iconKind;
        final Runnable action;
        final boolean keepOpen, selected;

        private Entry(String label, String iconKind, Runnable action, boolean keepOpen, boolean selected) {
            this.label = label; this.iconKind = iconKind; this.action = action;
            this.keepOpen = keepOpen; this.selected = selected;
        }
        static Entry action(String label, Runnable action) { return new Entry(label, null, action, false, false); }
        static Entry action(String label, String iconKind, Runnable action) { return new Entry(label, iconKind, action, false, false); }
        static Entry page(String label, Runnable action) { return new Entry(label, null, action, true, false); }
        static Entry page(String label, String iconKind, Runnable action) { return new Entry(label, iconKind, action, true, false); }
        static Entry choice(String label, boolean selected, Runnable action) { return new Entry(label, null, action, false, selected); }
        static Entry choice(String label, String iconKind, boolean selected, Runnable action) {
            return new Entry(label, iconKind, action, false, selected);
        }
        static Entry disabled(String label) { return new Entry(label, null, null, false, false); }
    }

    private final Activity activity;
    private PopupWindow popup;
    private View anchor;
    private Scope scope;
    private ScrollView scroll;
    private LinearLayout rows;
    private View.OnAttachStateChangeListener anchorListener;
    private int pageRevision;

    AnchoredMenu(Activity activity) { this.activity = activity; }

    void show(View source, String title, Scope expected, List<Entry> entries) {
        dismiss();
        if (source == null || !source.isAttachedToWindow() || !source.isShown()
                || activity.isFinishing() || activity.isDestroyed() || !expected.isCurrent()) return;
        anchor = source; scope = expected;
        rows = Ui.column(activity);
        rows.setLayoutDirection(source.getLayoutDirection());
        rows.setPadding(0, Ui.dp(activity, 4), 0, Ui.dp(activity, 4));
        scroll = new ScrollView(activity);
        scroll.setLayoutDirection(source.getLayoutDirection());
        scroll.setFillViewport(false);
        scroll.setVerticalScrollBarEnabled(true);
        scroll.setOverScrollMode(View.OVER_SCROLL_NEVER);
        scroll.addView(rows, new ViewGroup.LayoutParams(-1, -2));
        final PopupWindow window = new PopupWindow(scroll, -2, -2, true);
        popup = window;
        window.setBackgroundDrawable(Ui.bg(Color.WHITE, 12, activity));
        window.setElevation(Ui.dp(activity, 8));
        window.setOutsideTouchable(true);
        window.setTouchable(true);
        window.setClippingEnabled(true);
        window.setInputMethodMode(PopupWindow.INPUT_METHOD_NEEDED);
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        anchorListener = new View.OnAttachStateChangeListener() {
            @Override public void onViewAttachedToWindow(View view) { }
            @Override public void onViewDetachedFromWindow(View view) { if (popup == window) dismiss(); }
        };
        source.addOnAttachStateChangeListener(anchorListener);
        window.setOnDismissListener(() -> { if (popup == window) clear(); });
        render(title, entries);
        if (!sizeToWindow()) { dismiss(); return; }
        // END is the overflow edge: left in this RTL UI, right for an LTR anchor.
        // PopupWindow handles viewport clamping/above-anchor placement without modal dimming.
        try { window.showAsDropDown(source, 0, Ui.dp(activity, 4), Gravity.END); }
        catch (WindowManager.BadTokenException | IllegalStateException staleWindow) { dismiss(); }
    }

    /** Replaces rows inside the same window, rather than opening a dialog or a second popup. */
    void replace(String title, List<Entry> entries) {
        if (!isCurrent()) { dismiss(); return; }
        render(title, entries);
        if (!sizeToWindow()) { dismiss(); return; }
        popup.update(anchor, 0, Ui.dp(activity, 4), popup.getWidth(), popup.getHeight());
        scroll.scrollTo(0, 0);
    }

    boolean dismiss() {
        PopupWindow previous = popup;
        if (previous == null) return false;
        previous.dismiss();
        if (popup == previous) clear();
        return true;
    }

    private void clear() {
        if (anchor != null && anchorListener != null) anchor.removeOnAttachStateChangeListener(anchorListener);
        pageRevision++;
        popup = null; anchor = null; scope = null; rows = null; scroll = null; anchorListener = null;
    }

    private boolean isCurrent() {
        return popup != null && anchor != null && anchor.isAttachedToWindow() && anchor.isShown()
                && !activity.isFinishing() && !activity.isDestroyed() && scope != null && scope.isCurrent();
    }

    private void render(String title, List<Entry> entries) {
        final PopupWindow window = popup;
        final int revision = ++pageRevision;
        rows.removeAllViews();
        if (Build.VERSION.SDK_INT >= 28) scroll.setAccessibilityPaneTitle(title);
        for (Entry entry : entries) {
            LinearLayout row = Ui.row(activity);
            row.setLayoutDirection(anchor.getLayoutDirection());
            row.setMinimumHeight(Ui.dp(activity, 48));
            row.setPaddingRelative(Ui.dp(activity, 12), Ui.dp(activity, 10), Ui.dp(activity, 12), Ui.dp(activity, 10));
            if (entry.iconKind != null) {
                FrameLayout badge = new FrameLayout(activity);
                badge.setBackground(Ui.bg(Ui.LIME, 11, activity));
                badge.addView(new Ui.Icon(activity, entry.iconKind, Ui.GREEN),
                        new FrameLayout.LayoutParams(Ui.dp(activity, 18), Ui.dp(activity, 18), Gravity.CENTER));
                LinearLayout.LayoutParams badgeSize = new LinearLayout.LayoutParams(
                        Ui.dp(activity, 34), Ui.dp(activity, 34));
                badgeSize.setMarginEnd(Ui.dp(activity, 10));
                row.addView(badge, badgeSize);
            }
            TextView label = Ui.text(activity, entry.label, 15, entry.action == null ? Ui.MUTED : Ui.INK, false);
            label.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
            // Use the anchor direction for alignment; the text itself may contain brand names/numbers.
            label.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
            label.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START);
            label.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            row.addView(label, new LinearLayout.LayoutParams(0, -2, 1));
            if (entry.selected) {
                TextView check = Ui.text(activity, "✓", 17, Ui.GREEN, true);
                check.setGravity(Gravity.CENTER);
                check.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                row.addView(check, new LinearLayout.LayoutParams(Ui.dp(activity, 24), -2));
            }
            row.setSelected(entry.selected);
            if (entry.selected) row.setBackground(Ui.bg(Ui.LIME, 10, activity));
            row.setContentDescription(entry.selected ? activity.getString(R.string.menu_item_selected, entry.label) : entry.label);
            row.setEnabled(entry.action != null);
            row.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
            row.setAccessibilityDelegate(new View.AccessibilityDelegate() {
                @Override public void onInitializeAccessibilityNodeInfo(View host, AccessibilityNodeInfo info) {
                    super.onInitializeAccessibilityNodeInfo(host, info);
                    info.setClassName("android.widget.Button");
                }
            });
            if (entry.action != null) {
                Ui.clickable(row);
                row.setOnClickListener(view -> {
                    if (popup != window || revision != pageRevision) return;
                    if (!isCurrent()) { dismiss(); return; }
                    if (!entry.keepOpen) dismiss();
                    entry.action.run();
                });
            }
            rows.addView(row, new LinearLayout.LayoutParams(-1, -2));
        }
    }

    private boolean sizeToWindow() {
        if (!isCurrent()) return false;
        Rect visible = new Rect();
        anchor.getWindowVisibleDisplayFrame(visible);
        int width = Math.min(Ui.dp(activity, 288), visible.width() - Ui.dp(activity, 16));
        int height = Math.min(visible.height() - Ui.dp(activity, 8), popup.getMaxAvailableHeight(anchor, Ui.dp(activity, 4)));
        if (width <= 0 || height <= 0) return false;
        scroll.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.AT_MOST));
        popup.setWidth(width);
        popup.setHeight(Math.min(height, scroll.getMeasuredHeight()));
        return true;
    }
}

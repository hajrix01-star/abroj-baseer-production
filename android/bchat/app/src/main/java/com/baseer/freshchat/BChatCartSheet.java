package com.baseer.freshchat;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.function.Consumer;

/** Cart presentation only. The caller still owns all quantities, quotes and submission checks. */
final class BChatCartSheet {
    private final Activity activity;
    private final Dialog dialog;
    private final Button submit;

    BChatCartSheet(Activity activity, LinearLayout content, Runnable submitAction, Consumer<BChatCartSheet> dismissed) {
        this.activity = activity;
        dialog = new Dialog(activity);
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        dialog.setTitle(R.string.order_cart);
        LinearLayout root = Ui.column(activity);
        root.setBackground(Ui.bg(UiPalette.surface(activity), 20, activity));
        root.setPadding(0, Ui.dp(activity, 8), 0, 0);
        LinearLayout heading = Ui.row(activity);
        heading.setGravity(Gravity.CENTER_VERTICAL);
        heading.setPaddingRelative(Ui.dp(activity, 16), 0, Ui.dp(activity, 8), 0);
        TextView title = Ui.text(activity, activity.getString(R.string.order_cart), 20,
                UiPalette.ink(activity), true);
        if (android.os.Build.VERSION.SDK_INT >= 28) title.setAccessibilityHeading(true);
        heading.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        View close = Ui.iconButton(activity, "close", activity.getString(R.string.task_close));
        close.setOnClickListener(ignored -> dismiss());
        heading.addView(close, new LinearLayout.LayoutParams(Ui.dp(activity, 48), Ui.dp(activity, 48)));
        root.addView(heading, new LinearLayout.LayoutParams(-1, -2));

        // One scroll surface owns the options, every line, server quote and actions. No
        // fixed item-height estimate or horizontal dialog button bar can hide the bottom
        // of a large-font cart, including a resized window while another editor has IME.
        submit = action(content, R.string.order_submit, Ui.ActionTone.PRIMARY, () -> {
            if (!submitEnabled()) return;
            dismiss();
            submitAction.run();
        });
        action(content, R.string.order_add_more, Ui.ActionTone.SECONDARY, this::dismiss);
        content.setPadding(content.getPaddingLeft(), content.getPaddingTop(),
                content.getPaddingRight(), Math.max(content.getPaddingBottom(), Ui.dp(activity, 16)));
        ScrollView scroll = new ScrollView(activity);
        scroll.setFillViewport(false);
        scroll.setClipToPadding(false);
        scroll.addView(content, new ScrollView.LayoutParams(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        dialog.setContentView(root);
        dialog.setOnDismissListener(ignored -> dismissed.accept(this));
    }

    static View line(Activity activity, String productName, String option, View quantity, Runnable removeAction) {
        LinearLayout row = Ui.column(activity);
        Ui.pad(row, 10, 9);
        row.setBackground(Ui.outline(UiPalette.surface(activity), UiPalette.line(activity), 12, activity));
        LinearLayout heading = Ui.row(activity);
        TextView product = Ui.text(activity, productName, 15, UiPalette.ink(activity), true);
        product.setMaxLines(Integer.MAX_VALUE);
        product.setEllipsize(null);
        heading.addView(product, new LinearLayout.LayoutParams(0, -2, 1));
        View remove = Ui.iconButton(activity, "close", activity.getString(R.string.order_remove) + " " + productName);
        remove.setOnClickListener(ignored -> removeAction.run());
        heading.addView(remove, new LinearLayout.LayoutParams(Ui.dp(activity, 48), Ui.dp(activity, 48)));
        row.addView(heading, new LinearLayout.LayoutParams(-1, -2));
        if (option != null && !option.isEmpty())
            row.addView(Ui.text(activity, option, 12, UiPalette.muted(activity), false),
                    new LinearLayout.LayoutParams(-1, -2));
        row.addView(quantity, new LinearLayout.LayoutParams(-1, -2));
        return row;
    }

    private Button action(LinearLayout content, int label, Ui.ActionTone tone, Runnable action) {
        Button button = new Button(activity);
        button.setText(label);
        Ui.styleAction(button, tone);
        button.setSingleLine(false);
        button.setMaxLines(Integer.MAX_VALUE);
        button.setEllipsize(null);
        LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(-1, -2);
        size.topMargin = Ui.dp(activity, 10);
        content.addView(button, size);
        button.setOnClickListener(ignored -> action.run());
        return button;
    }

    void show() {
        if (activity.isFinishing() || activity.isDestroyed()) return;
        dialog.show();
        Window window = dialog.getWindow();
        if (window != null) {
            window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            window.setGravity(Gravity.BOTTOM);
            window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            int width = Ui.dp(activity, activity.getResources().getConfiguration().screenWidthDp);
            window.setLayout(Math.min(width, Ui.dp(activity, 560)), WindowManager.LayoutParams.MATCH_PARENT);
        }
    }
    void setSubmitEnabled(boolean enabled) { submit.setEnabled(enabled); }
    private boolean submitEnabled() { return dialog.isShowing() && submit.isEnabled(); }
    boolean isShowing() { return dialog.isShowing(); }
    void dismiss() { dialog.dismiss(); }
}

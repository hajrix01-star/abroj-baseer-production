package com.baseer.freshchat;

import android.content.Context;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Raw quantity display/actions only; arithmetic and validation remain with the existing owner. */
final class OrderQuantityStepper {
    static LinearLayout create(Context context, String quantity, String product, boolean expanded,
            Runnable decrease, Runnable edit, Runnable increase) {
        LinearLayout row = Ui.row(context);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setBackground(Ui.outline(UiPalette.surface(context), UiPalette.line(context), 12, context));
        row.setClipToOutline(true);
        int actionHeight = expanded ? -2 : Ui.dp(context, 48);
        row.addView(action(context, "−", 19, R.string.order_decrease, product, decrease),
                new LinearLayout.LayoutParams(Ui.dp(context, 48), actionHeight));
        divider(context, row);
        TextView value = action(context, quantity, 14, R.string.order_change_quantity, product, edit);
        value.setContentDescription(context.getString(R.string.order_change_quantity) + " " + product + ": " + quantity);
        value.setSingleLine(!expanded);
        if (expanded) {
            value.setMaxLines(Integer.MAX_VALUE);
            value.setEllipsize(null);
        } else value.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE);
        row.addView(value, expanded ? new LinearLayout.LayoutParams(0, -2, 1)
                : new LinearLayout.LayoutParams(Ui.dp(context, 56), Ui.dp(context, 48)));
        divider(context, row);
        row.addView(action(context, "+", 19, R.string.order_increase, product, increase),
                new LinearLayout.LayoutParams(Ui.dp(context, 48), actionHeight));
        return row;
    }
    private static TextView action(Context context, String label, int sp, int description,
            String product, Runnable action) {
        TextView view = Ui.text(context, label, sp, UiPalette.accent(context), true);
        view.setGravity(Gravity.CENTER);
        view.setMinWidth(Ui.dp(context, 48));
        view.setMinHeight(Ui.dp(context, 48));
        view.setContentDescription(context.getString(description) + " " + product);
        Ui.clickable(view);
        view.setOnClickListener(ignored -> action.run());
        return view;
    }
    private static void divider(Context context, LinearLayout row) {
        View divider = new View(context);
        divider.setBackgroundColor(UiPalette.line(context));
        LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(Ui.dp(context, 1), Ui.dp(context, 24));
        size.gravity = Gravity.CENTER_VERTICAL;
        row.addView(divider, size);
    }
    private OrderQuantityStepper() { }
}

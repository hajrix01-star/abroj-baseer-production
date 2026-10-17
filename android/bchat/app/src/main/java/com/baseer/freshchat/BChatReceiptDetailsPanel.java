package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import com.baseer.freshchat.sync.AccountScope;
import java.util.Locale;
import org.json.JSONObject;

/** Sender-only server facts, one bounded page. This view never ACKs, polls or mutates a message. */
final class BChatReceiptDetailsPanel {
    interface Reply { void complete(int status, JSONObject body); }
    interface Host {
        AccountScope account();
        boolean current(AccountScope scope, long roomId, long membershipId, long messageId, long generation);
        /** GET through the existing authenticated session; the Host rechecks binding before dispatch. */
        boolean load(long afterId, Reply reply);
    }
    private final Activity activity;
    private final Host host;
    private final AccountScope scope;
    private final long roomId, membershipId, messageId, bindingGeneration;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AlertDialog dialog;
    private final TextView summary, notice;
    private final LinearLayout rows;
    private final ScrollView scroll;
    private final Button refresh, next;
    private ReceiptDetailsProtocol.Page page;
    private long requestSerial;
    private boolean closed, paused, busy, shown;

    BChatReceiptDetailsPanel(Activity activity, Host host, AccountScope scope,
                             long roomId, long membershipId, long messageId, long generation) {
        ReceiptDetailsProtocol.path(roomId, messageId, 0);
        if (scope == null || membershipId <= 0 || membershipId > 2147483647L) throw new IllegalArgumentException("Verified receipt binding required");
        this.activity = activity; this.host = host; this.scope = scope;
        this.roomId = roomId; this.membershipId = membershipId; this.messageId = messageId; bindingGeneration = generation;
        LinearLayout content = Ui.column(activity);
        content.setPadding(Ui.dp(activity, 20), Ui.dp(activity, 8), Ui.dp(activity, 20), Ui.dp(activity, 12));
        summary = body(content, true);
        TextView note = body(content, false); note.setText(R.string.receipt_details_scope_note);
        rows = Ui.column(activity); content.addView(rows, new LinearLayout.LayoutParams(-1, -2));
        notice = body(content, false); notice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        refresh = action(content, R.string.receipt_details_refresh, () -> load(0));
        next = action(content, R.string.receipt_details_next, () -> {
            if (page != null && page.hasMore) load(page.nextAfterId);
        });
        scroll = new ScrollView(activity); scroll.setFillViewport(false); scroll.addView(content);
        dialog = new AlertDialog.Builder(activity).setTitle(R.string.receipt_details_title).setView(scroll)
                .setNegativeButton(R.string.receipt_details_close, null).create();
        dialog.setOnDismissListener(ignored -> close());
    }
    void show() {
        if (closed || shown || !bound()) return;
        shown = true; dialog.show();
        Ui.styleAction(dialog.getButton(AlertDialog.BUTTON_NEGATIVE), Ui.ActionTone.TEXT);
        draw(); load(0);
    }
    void pause() {
        paused = true; ++requestSerial;
        if (busy && !closed) notice.setText(R.string.receipt_details_unconfirmed);
        busy = false; drawActions();
    }
    /** Resume never initiates HTTP; refresh is an explicit user action. */
    void resume() {
        if (closed) return;
        if (!bound()) { dismiss(); return; }
        paused = false; drawActions();
    }
    void dismiss() { dialog.dismiss(); close(); }
    private void close() {
        if (closed) return;
        closed = true; ++requestSerial; busy = false; page = null;
        rows.removeAllViews(); summary.setText(""); notice.setText("");
    }
    private boolean bound() {
        AccountScope current = host.account();
        return current != null && scope.key.equals(current.key)
                && host.current(scope, roomId, membershipId, messageId, bindingGeneration);
    }
    private boolean visible(long serial) {
        if (closed) return false;
        if (!bound()) { dismiss(); return false; }
        return !paused && shown && dialog.isShowing() && serial == requestSerial;
    }
    private void load(long after) {
        if (!visible(requestSerial) || busy) return;
        busy = true; final long serial = ++requestSerial;
        notice.setText(R.string.receipt_details_loading); drawActions();
        boolean started;
        try {
            started = host.load(after, (status, body) -> main.post(() -> {
                if (!visible(serial)) return;
                busy = false;
                try {
                    if (status != 200) throw new IllegalArgumentException("Receipt detail not confirmed");
                    page = ReceiptDetailsProtocol.page(body, roomId, membershipId, messageId, after);
                    notice.setText(""); draw(); scroll.scrollTo(0, 0);
                } catch (IllegalArgumentException invalid) {
                    boolean denied = status == 403 || status == 404 || status == 409;
                    if (denied) { page = null; draw(); }
                    notice.setText(denied ? R.string.receipt_details_unavailable : R.string.receipt_details_unconfirmed);
                    drawActions();
                }
            }));
        } catch (RuntimeException unavailable) { started = false; }
        if (!started && visible(serial)) {
            ++requestSerial; busy = false; notice.setText(R.string.receipt_details_unconfirmed); drawActions();
        }
    }
    private void draw() {
        rows.removeAllViews();
        if (page == null) summary.setText(R.string.receipt_details_unknown);
        else {
            int state = "read".equals(page.state) ? R.string.receipt_details_state_read
                    : "delivered".equals(page.state) ? R.string.receipt_details_state_delivered : R.string.receipt_details_state_sent;
            // These are authoritative full counts, never derived from the current page.
            summary.setText(activity.getString(state) + "\n" + activity.getString(R.string.receipt_details_counts,
                    digits(page.eligible), digits(page.delivered), digits(page.read)));
            if (page.rows.isEmpty()) body(rows, false).setText(R.string.receipt_details_empty);
            for (ReceiptDetailsProtocol.Row row : page.rows) {
                LinearLayout card = Ui.column(activity);
                card.setPadding(Ui.dp(activity, 12), Ui.dp(activity, 10), Ui.dp(activity, 12), Ui.dp(activity, 10));
                card.setBackground(Ui.outline(Ui.SURFACE, Ui.LINE, 12, activity));
                LinearLayout.LayoutParams spacing = new LinearLayout.LayoutParams(-1, -2); spacing.bottomMargin = Ui.dp(activity, 10);
                rows.addView(card, spacing);
                body(card, true).setText(row.name);
                body(card, false).setText(activity.getString(R.string.receipt_details_delivered,
                        row.deliveredAt == null ? activity.getString(R.string.receipt_details_not_confirmed) : utc(row.deliveredAt))
                        + "\n" + activity.getString(R.string.receipt_details_read,
                        row.readAt == null ? activity.getString(R.string.receipt_details_not_confirmed) : utc(row.readAt)));
            }
        }
        drawActions();
    }
    private String utc(String value) { return "\u2066" + value + " UTC\u2069"; }
    private String digits(long value) { return "\u2066" + String.format(Locale.ROOT, "%d", value) + "\u2069"; }
    private void drawActions() {
        refresh.setEnabled(!closed && !paused && !busy);
        next.setEnabled(!closed && !paused && !busy && page != null && page.hasMore);
        next.setVisibility(page != null && page.hasMore ? View.VISIBLE : View.GONE);
    }
    private TextView body(LinearLayout parent, boolean strong) {
        TextView text = Ui.text(activity, "", strong ? 16 : 14, strong ? Ui.INK : Ui.MUTED, strong);
        text.setPadding(0, Ui.dp(activity, 6), 0, Ui.dp(activity, 6));
        text.setLineSpacing(Ui.dp(activity, 2), 1f); parent.addView(text, new LinearLayout.LayoutParams(-1, -2)); return text;
    }
    private Button action(LinearLayout parent, int label, Runnable work) {
        Button button = new Button(activity); button.setText(label); Ui.styleAction(button, Ui.ActionTone.SECONDARY);
        button.setSingleLine(false); button.setMaxLines(Integer.MAX_VALUE); button.setEllipsize(null);
        LinearLayout.LayoutParams margin = new LinearLayout.LayoutParams(-1, -2); margin.topMargin = Ui.dp(activity, 6);
        parent.addView(button, margin); button.setOnClickListener(ignored -> work.run()); return button;
    }
}

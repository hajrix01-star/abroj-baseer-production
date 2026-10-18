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
import java.lang.ref.WeakReference;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** One read-only C19 page. No request/write/ACK/polling port or arbitrary admin membership.
 * Host captures current verified account/session/generations/company/room/member/rights and
 * fresh can_manage. Owner MUST dismiss before that binding changes; no new authority here.
 * Roster labels may only come from the same current authorized group-detail binding. */
final class BChatGroupEventsPanel {
    interface Reply { void complete(int status, JSONObject body); }
    interface Host {
        boolean current(long roomId, long membershipId);
        /** MAIN adapter to the existing GET only. Final binding check is Host-owned. */
        boolean load(GroupPeopleProtocol.EventsQuery query, Reply reply);
    }
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private final Activity activity;
    private final WeakReference<Host> host;
    private final long roomId, membershipId;
    private final Map<Long, String> roster = new HashMap<>();
    private final AlertDialog dialog;
    private final ScrollView scroll;
    private final LinearLayout rows;
    private final TextView summary, notice;
    private final Button refresh, older;
    private GroupPeopleProtocol.EventsPage page;
    private long requestSerial;
    private boolean closed, paused, shown, busy;

    BChatGroupEventsPanel(Activity activity, Host host, long roomId, long membershipId, Map<Long, String> currentRoster) {
        mainThread(); new GroupPeopleProtocol.EventsQuery(roomId, membershipId, 0);
        if (activity == null || host == null || currentRoster == null || currentRoster.size() > 50)
            throw new IllegalArgumentException("Current group events ports required");
        this.activity = activity; this.host = new WeakReference<>(host); this.roomId = roomId; this.membershipId = membershipId;
        for (Map.Entry<Long, String> entry : currentRoster.entrySet()) {
            Long id = entry.getKey(); String name = entry.getValue();
            if (id != null && id > 0 && id <= GroupPeopleProtocol.MAX_ID && name != null && !name.trim().isEmpty()) roster.put(id, name);
        }
        LinearLayout content = Ui.column(activity); content.setLayoutDirection(AppLocale.direction(activity));
        content.setBackgroundColor(UiPalette.background(activity, Ui.LIGHT)); Ui.pad(content, 16, 10);
        summary = text(content, true); text(content, false).setText(R.string.bchat_group_event_scope_note);
        rows = Ui.column(activity); content.addView(rows, full());
        notice = text(content, false); notice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        refresh = action(content, R.string.bchat_group_event_refresh, () -> load(new GroupPeopleProtocol.EventsQuery(roomId, membershipId, 0)));
        older = action(content, R.string.bchat_group_event_older, () -> { if (page != null && page.nextBeforeId != 0) load(page.nextQuery()); });
        scroll = new ScrollView(activity); scroll.addView(content);
        dialog = new AlertDialog.Builder(activity).setTitle(R.string.bchat_group_event_title).setView(scroll)
                .setNegativeButton(R.string.bchat_group_event_close, null).create();
        dialog.setOnDismissListener(ignored -> close());
    }
    void show() {
        mainThread(); if (closed || shown) return; if (!bound()) { close(); return; }
        shown = true; dialog.show(); Ui.decorateDialog(dialog); draw(); load(new GroupPeopleProtocol.EventsQuery(roomId, membershipId, 0));
    }
    void pause() { mainThread(); if (closed) return; paused = true; ++requestSerial; busy = false; page = null;
        rows.removeAllViews(); summary.setText(""); notice.setText(R.string.bchat_group_event_unconfirmed); drawActions(); }
    /** Explicit refresh is required after resume; no polling or background request. */
    void resume() { mainThread(); if (closed) return; if (!bound()) { dismiss(); return; } paused = false; draw(); }
    void dismiss() { mainThread(); dialog.dismiss(); close(); }
    private void close() {
        if (closed) return; closed = true; ++requestSerial; busy = false; page = null; roster.clear();
        rows.removeAllViews(); summary.setText(""); notice.setText(""); host.clear();
    }
    private boolean bound() {
        Host port = host.get();
        try { return !activity.isFinishing() && !activity.isDestroyed() && port != null && port.current(roomId, membershipId); }
        catch (RuntimeException unavailable) { return false; }
    }
    private boolean visible(long serial) {
        if (closed) return false; if (!bound()) { dismiss(); return false; }
        return shown && !paused && dialog.isShowing() && serial == requestSerial;
    }
    private void load(GroupPeopleProtocol.EventsQuery query) {
        if (!visible(requestSerial) || busy) return; busy = true; final long serial = ++requestSerial;
        notice.setText(R.string.bchat_group_event_loading); drawActions();
        WeakReference<BChatGroupEventsPanel> weak = new WeakReference<>(this); AtomicBoolean once = new AtomicBoolean();
        Reply reply = (status, body) -> { if (once.compareAndSet(false, true)) MAIN.post(() -> {
            BChatGroupEventsPanel panel = weak.get(); if (panel != null) panel.receive(serial, query, status, body);
        }); };
        boolean accepted; Host port = host.get();
        try { accepted = port != null && port.load(query, reply); } catch (RuntimeException unavailable) { accepted = false; }
        if (!accepted && once.compareAndSet(false, true)) receive(serial, query, 0, null);
    }
    private void receive(long serial, GroupPeopleProtocol.EventsQuery query, int status, JSONObject body) {
        if (!visible(serial)) return; busy = false;
        try {
            if (status != 200) throw new IllegalArgumentException(); page = GroupPeopleProtocol.events(body, query); notice.setText("");
        } catch (IllegalArgumentException invalid) {
            page = null; notice.setText(status == 401 || status == 403 || status == 404 || status == 409
                    ? R.string.bchat_group_event_unavailable : R.string.bchat_group_event_unconfirmed);
        }
        draw(); scroll.scrollTo(0, 0);
    }
    private void draw() {
        if (closed || paused) return; rows.removeAllViews();
        String started = page == null ? null : BChatDisplayTime.groupEvent(page.auditStartedAt);
        summary.setText(started == null ? activity.getString(R.string.bchat_group_event_start_unknown)
                : activity.getString(R.string.bchat_group_event_started, started));
        if (page == null) text(rows, false).setText(R.string.bchat_group_event_unknown_page);
        else if (page.events.isEmpty()) text(rows, false).setText(R.string.bchat_group_event_empty);
        else for (GroupPeopleProtocol.Event event : page.events) {
            LinearLayout card = Ui.column(activity); Ui.pad(card, 12, 10); card.setBackground(Ui.outline(Ui.SURFACE, Ui.LINE, 12, activity));
            LinearLayout.LayoutParams margin = full(); margin.bottomMargin = Ui.dp(activity, 10); rows.addView(card, margin);
            text(card, true).setText(actionLabel(event.action));
            text(card, false).setText(activity.getString(R.string.bchat_group_event_actor, label(event.actorUserId)));
            if (event.targetUserId != 0) text(card, false).setText(activity.getString(R.string.bchat_group_event_target, label(event.targetUserId)));
            if (!event.addedUserIds.isEmpty()) {
                StringBuilder labels = new StringBuilder();
                for (long id : event.addedUserIds) { if (labels.length() > 0) labels.append('\n'); labels.append(label(id)); }
                text(card, false).setText(activity.getString(R.string.bchat_group_event_targets, labels.toString()));
            }
            text(card, false).setText(utc(event.createdAt));
        }
        drawActions();
    }
    private String label(long id) {
        String name = roster.get(id);
        return name == null ? activity.getString(R.string.bchat_group_event_user_id, digits(id)) : AppLocale.name(activity, name) + " (" + digits(id) + ")";
    }
    private int actionLabel(GroupPeopleProtocol.Action action) {
        switch (action) {
            case CREATE: return R.string.bchat_group_event_create;
            case ADD_MEMBER: return R.string.bchat_group_event_add_member;
            case ADD_MEMBERS: return R.string.bchat_group_event_add_members;
            case REMOVE_MEMBER: return R.string.bchat_group_event_remove_member;
            case LEAVE: return R.string.bchat_group_event_leave;
            case PROMOTE_ADMIN: return R.string.bchat_group_event_promote_admin;
            case DEMOTE_ADMIN: return R.string.bchat_group_event_demote_admin;
            case RENAME: return R.string.bchat_group_event_rename;
            case SET_DESCRIPTION: return R.string.bchat_group_event_description;
            case AVATAR: return R.string.bchat_group_event_avatar;
            case RECOVER: return R.string.bchat_group_event_recover;
            case INVOICE_POLICY: return R.string.bchat_group_event_invoice_policy;
            default: throw new IllegalArgumentException("Unknown group event label");
        }
    }
    private void drawActions() {
        refresh.setEnabled(!closed && !paused && !busy);
        older.setVisibility(page != null && page.nextBeforeId != 0 ? View.VISIBLE : View.GONE);
        older.setEnabled(!closed && !paused && !busy && page != null && page.nextBeforeId != 0);
    }
    private TextView text(LinearLayout parent, boolean strong) {
        TextView text = Ui.text(activity, "", strong ? 16 : 14, strong ? Ui.INK : Ui.MUTED, strong);
        text.setPadding(0, Ui.dp(activity, 6), 0, Ui.dp(activity, 6)); parent.addView(text, full()); return text;
    }
    private Button action(LinearLayout parent, int label, Runnable work) {
        Button button = new Button(activity); button.setText(label); Ui.styleAction(button, Ui.ActionTone.SECONDARY);
        button.setSingleLine(false); button.setMaxLines(Integer.MAX_VALUE); button.setEllipsize(null);
        parent.addView(button, full()); button.setOnClickListener(view -> work.run()); return button;
    }
    private static LinearLayout.LayoutParams full() { return new LinearLayout.LayoutParams(-1, -2); }
    private static String digits(long value) { return "\u2066" + String.format(Locale.ROOT, "%d", value) + "\u2069"; }
    private String utc(String value) {
        String display = BChatDisplayTime.groupEvent(value);
        return display == null ? activity.getString(R.string.bchat_group_event_unconfirmed) : display;
    }
    private static void mainThread() { if (Looper.myLooper() != Looper.getMainLooper()) throw new IllegalStateException("Group events UI requires MAIN"); }
}

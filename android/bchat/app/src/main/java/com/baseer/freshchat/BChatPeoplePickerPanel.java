package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.ScrollView;
import android.widget.TextView;
import java.lang.ref.WeakReference;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** C18/C19 native selection only. No auth/transport/storage implementation or Activity hook.
 * The owner must dismiss BEFORE changing identity/rights/company/room and call pause/resume.
 * Host.current is its captured verified RAM binding (account/session/global/repository,
 * company and, for ADD, room/member/fresh can_manage), never authority derived from a name.
 * Host owns durable exact intents, final dispatch gates and settlement even after UI closes. */
final class BChatPeoplePickerPanel {
    interface Reply { void complete(int status, JSONObject body); }
    interface Host {
        boolean current(long companyId, long roomId, long membershipId);
        /** MAIN-only adapters to existing routes, not blocking I/O. Recheck current at dispatch. */
        boolean candidates(GroupPeopleProtocol.CandidateQuery query, Reply reply);
        /** Only explicit confirmation calls this. Later Host must persist exact intent before
         * HTTP, retain unknowns, and settle against original ticket/intent off MAIN.
         * The Panel's response display is NOT proof of storage, current rooms or permission. */
        boolean request(GroupPeopleProtocol.Intent intent, Reply reply);
    }
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private final Activity activity;
    private final WeakReference<Host> host;
    private final long companyId, selfUserId, roomId, membershipId;
    private final GroupPeopleProtocol.Mode mode;
    private final AlertDialog dialog;
    private AlertDialog confirmation;
    private final ScrollView scroll;
    private final LinearLayout selectedRows, rows;
    private final TextView selectedCount, notice;
    private final EditText search, name, description;
    private final Button searchAction, next, review, retry;
    private GroupPeopleProtocol.Selection selection;
    private GroupPeopleProtocol.CandidatePage page;
    private GroupPeopleProtocol.Intent pending;
    private long requestSerial, editRevision;
    private boolean closed, paused, shown, busy, unknown, blocked, confirmed;

    BChatPeoplePickerPanel(Activity activity, Host host, GroupPeopleProtocol.Selection initial,
            long roomId, long membershipId) { this(activity, host, initial, roomId, membershipId, null); }

    /** Existing Intent is an externally owned immutable pending operation, NOT a disk restore
     * or an authenticated grant. The owner must refuse new work while its journal is unknown. */
    BChatPeoplePickerPanel(Activity activity, Host host, GroupPeopleProtocol.Selection initial,
            long roomId, long membershipId, GroupPeopleProtocol.Intent existing) {
        mainThread();
        if (activity == null || host == null || initial == null) throw new IllegalArgumentException("Current people ports required");
        if (initial.mode == GroupPeopleProtocol.Mode.ADD) new GroupPeopleProtocol.EventsQuery(roomId, membershipId, 0);
        else if (roomId != 0 || membershipId != 0) throw new IllegalArgumentException("No room before creation");
        if (existing != null && (existing.mode != initial.mode || existing.companyId != initial.companyId
                || existing.selfUserId != initial.selfUserId || existing.roomId != roomId || existing.membershipId != membershipId))
            throw new IllegalArgumentException("Exact pending people scope required");
        this.activity = activity; this.host = new WeakReference<>(host); selection = initial; mode = initial.mode;
        companyId = initial.companyId; selfUserId = initial.selfUserId; this.roomId = roomId; this.membershipId = membershipId;
        pending = existing; unknown = existing != null;
        LinearLayout content = Ui.column(activity); content.setLayoutDirection(AppLocale.direction(activity));
        content.setBackgroundColor(UiPalette.background(activity, Ui.LIGHT)); Ui.pad(content, 16, 10);
        text(content, false).setText(R.string.bchat_people_scope_note);
        if (mode == GroupPeopleProtocol.Mode.CREATE) {
            name = field(content, R.string.bchat_people_name, true);
            description = field(content, R.string.bchat_people_description, false);
        } else { name = null; description = null; }
        selectedCount = text(content, true);
        selectedRows = Ui.column(activity); content.addView(selectedRows, full());
        search = field(content, R.string.bchat_people_search_label, true);
        search.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        searchAction = action(content, R.string.bchat_people_search, () -> search());
        search.setOnEditorActionListener((view, action, event) -> {
            if (action != EditorInfo.IME_ACTION_SEARCH) return false; search(); return true;
        });
        rows = Ui.column(activity); content.addView(rows, full());
        next = action(content, R.string.bchat_people_next, () -> { if (page != null && page.nextAfterUserId != 0) load(page.nextQuery()); });
        notice = text(content, false); notice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        review = action(content, R.string.bchat_people_review, () -> review());
        retry = action(content, R.string.bchat_people_retry, () -> { if (pending != null && unknown && !blocked) confirm(pending, true); });
        scroll = new ScrollView(activity); scroll.setFillViewport(false); scroll.addView(content);
        int title = mode == GroupPeopleProtocol.Mode.DIRECT ? R.string.bchat_people_direct_title
                : mode == GroupPeopleProtocol.Mode.CREATE ? R.string.bchat_people_create_title : R.string.bchat_people_add_title;
        dialog = new AlertDialog.Builder(activity).setTitle(title).setView(scroll)
                .setNegativeButton(R.string.bchat_people_close, null).create();
        dialog.setOnDismissListener(ignored -> close());
    }
    void show() {
        mainThread(); if (closed || shown) return; if (!bound()) { close(); return; }
        shown = true; dialog.show(); Ui.decorateDialog(dialog);
        if (dialog.getWindow() != null) dialog.getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        draw();
        if (pending == null) search(); else notice.setText(R.string.bchat_people_unknown);
    }
    void pause() {
        mainThread(); if (closed) return; paused = true; ++requestSerial; busy = false; page = null;
        if (pending != null && !confirmed) unknown = true;
        dismissConfirmation(); rows.removeAllViews(); selectedRows.removeAllViews(); selectedCount.setText(""); drawActions();
    }
    /** No automatic GET/POST/retry on resume. */
    void resume() {
        mainThread(); if (closed) return; if (!bound()) { dismiss(); return; }
        paused = false; draw(); if (pending != null && !confirmed) notice.setText(R.string.bchat_people_unknown);
    }
    void dismiss() { mainThread(); dialog.dismiss(); close(); }
    private void close() {
        if (closed) return; closed = true; ++requestSerial; busy = false; dismissConfirmation();
        page = null; pending = null; selection = null; rows.removeAllViews(); selectedRows.removeAllViews();
        selectedCount.setText(""); notice.setText(""); search.setText("");
        if (name != null) { name.setText(""); description.setText(""); } host.clear();
    }
    private boolean bound() {
        Host port = host.get();
        try { return !activity.isFinishing() && !activity.isDestroyed() && port != null && port.current(companyId, roomId, membershipId); }
        catch (RuntimeException unavailable) { return false; }
    }
    private boolean visible(long serial) {
        if (closed) return false;
        if (!bound()) { dismiss(); return false; }
        return shown && !paused && dialog.isShowing() && serial == requestSerial;
    }
    private boolean editable() { return pending == null && !confirmed && !busy && !paused && !closed && !blocked; }
    private void search() {
        if (!visible(requestSerial) || !editable()) return;
        try { load(selection.query(search.getText().toString(), 0)); }
        catch (IllegalArgumentException invalid) { notice.setText(R.string.bchat_people_search_invalid); }
    }
    private void load(GroupPeopleProtocol.CandidateQuery query) {
        if (!visible(requestSerial) || !editable()) return;
        busy = true; page = null; rows.removeAllViews(); final long serial = ++requestSerial;
        notice.setText(R.string.bchat_people_loading); drawActions();
        WeakReference<BChatPeoplePickerPanel> weak = new WeakReference<>(this); AtomicBoolean once = new AtomicBoolean();
        Reply reply = (status, body) -> { if (once.compareAndSet(false, true)) MAIN.post(() -> {
            BChatPeoplePickerPanel panel = weak.get(); if (panel != null) panel.receiveCandidates(serial, query, status, body);
        }); };
        boolean accepted; Host port = host.get();
        try { accepted = port != null && port.candidates(query, reply); } catch (RuntimeException unavailable) { accepted = false; }
        if (!accepted && once.compareAndSet(false, true)) receiveCandidates(serial, query, 0, null);
    }
    private void receiveCandidates(long serial, GroupPeopleProtocol.CandidateQuery query, int status, JSONObject body) {
        if (!visible(serial)) return; busy = false;
        try {
            if (status != 200) throw new IllegalArgumentException();
            GroupPeopleProtocol.CandidatePage received = GroupPeopleProtocol.candidates(body, query);
            if (!query.text.equals(search.getText().toString())) {
                // Typing during a read never starts another read or relabels its results.
                // Keep the independent selection/intent and require an explicit new search.
                page = null; notice.setText(R.string.bchat_people_search_changed);
            } else {
                page = received;
                notice.setText(page.people.isEmpty() && page.nextAfterUserId != 0 ? R.string.bchat_people_filtered_page : R.string.bchat_people_ready);
            }
        } catch (IllegalArgumentException invalid) {
            page = null; notice.setText(denied(status) ? R.string.bchat_people_unavailable : R.string.bchat_people_load_failed);
            if (denied(status)) { blocked = true; selection = GroupPeopleProtocol.Selection.empty(mode, companyId, selfUserId, java.util.Collections.emptyList()); }
        }
        draw(); scroll.scrollTo(0, 0);
    }
    private void review() {
        if (!visible(requestSerial) || !editable() || blocked || selection.people.isEmpty()) return;
        try {
            String uuid = UUID.randomUUID().toString();
            GroupPeopleProtocol.Intent intent = mode == GroupPeopleProtocol.Mode.DIRECT ? GroupPeopleProtocol.direct(selection, uuid)
                    : mode == GroupPeopleProtocol.Mode.CREATE ? GroupPeopleProtocol.create(selection, uuid, name.getText().toString(), description.getText().toString())
                    : GroupPeopleProtocol.add(selection, uuid, roomId, membershipId);
            confirm(intent, false);
        } catch (IllegalArgumentException invalid) { notice.setText(R.string.bchat_people_choice_invalid); }
    }
    private void confirm(GroupPeopleProtocol.Intent intent, boolean retrying) {
        if (!visible(requestSerial) || busy || blocked || confirmed || confirmation != null
                || retrying && (pending != intent || !unknown) || !retrying && pending != null) return;
        final long serial = requestSerial, edit = editRevision;
        LinearLayout content = Ui.column(activity); Ui.pad(content, 16, 10);
        text(content, false).setText(retrying ? R.string.bchat_people_retry_note : R.string.bchat_people_confirm_note);
        if (mode == GroupPeopleProtocol.Mode.CREATE) {
            // Review the frozen intent itself, including explicit retry, never edited fields.
            try {
                JSONObject frozen = new JSONObject(intent.payload);
                text(content, true).setText((String) frozen.opt("name"));
                Object details = frozen.opt("description"); if (details instanceof String && !((String) details).isEmpty()) text(content, false).setText((String) details);
            } catch (org.json.JSONException invalid) { notice.setText(R.string.bchat_people_choice_invalid); return; }
        }
        for (long id : intent.userIds) text(content, false).setText(label(id));
        ScrollView reviewScroll = new ScrollView(activity); reviewScroll.addView(content);
        AlertDialog reviewDialog = new AlertDialog.Builder(activity).setTitle(R.string.bchat_people_confirm_title).setView(reviewScroll)
                .setPositiveButton(retrying ? R.string.bchat_people_retry : R.string.bchat_people_confirm, null)
                .setNegativeButton(R.string.bchat_people_cancel, null).create();
        confirmation = reviewDialog;
        reviewDialog.setOnDismissListener(ignored -> { if (confirmation == reviewDialog) confirmation = null; });
        reviewDialog.setOnShowListener(ignored -> {
            Ui.decorateDialog(reviewDialog);
            reviewDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
                if (!visible(serial) || edit != editRevision || busy || blocked || confirmed
                        || retrying && pending != intent || !retrying && pending != null) { reviewDialog.dismiss(); return; }
                reviewDialog.dismiss(); dispatch(intent);
            });
        });
        reviewDialog.show();
    }
    private void dispatch(GroupPeopleProtocol.Intent intent) {
        if (!visible(requestSerial) || busy || blocked || confirmed || pending != null && pending != intent) return;
        pending = intent; unknown = false; busy = true; final long serial = ++requestSerial;
        notice.setText(R.string.bchat_people_requesting); drawActions();
        WeakReference<BChatPeoplePickerPanel> weak = new WeakReference<>(this); AtomicBoolean once = new AtomicBoolean();
        Reply reply = (status, body) -> { if (once.compareAndSet(false, true)) MAIN.post(() -> {
            BChatPeoplePickerPanel panel = weak.get(); if (panel != null) panel.receiveRequest(serial, intent, status, body);
        }); };
        boolean accepted; Host port = host.get();
        try { accepted = port != null && port.request(intent, reply); } catch (RuntimeException unavailable) { accepted = false; }
        if (!accepted && once.compareAndSet(false, true)) receiveRequest(serial, intent, 0, null);
    }
    private void receiveRequest(long serial, GroupPeopleProtocol.Intent intent, int status, JSONObject body) {
        if (!visible(serial) || pending != intent) return; busy = false;
        try {
            GroupPeopleProtocol.acknowledgement(status, body, intent); confirmed = true; unknown = false;
            notice.setText(R.string.bchat_people_response_confirmed);
        } catch (IllegalArgumentException invalid) {
            unknown = true; blocked = denied(status);
            notice.setText(blocked ? R.string.bchat_people_request_blocked : R.string.bchat_people_unknown);
        }
        drawActions();
    }
    private void draw() {
        if (closed || paused || selection == null) return;
        selectedRows.removeAllViews(); rows.removeAllViews();
        java.util.List<Long> selected = pending == null ? selection.selectedIds() : pending.userIds;
        selectedCount.setText(activity.getString(R.string.bchat_people_selected_count, digits(selected.size())));
        for (long id : selected) {
            LinearLayout line = Ui.row(activity); line.setBackground(Ui.outline(Ui.SURFACE, Ui.LINE, 10, activity));
            TextView label = Ui.text(activity, label(id), 15, Ui.INK, false);
            line.addView(label, new LinearLayout.LayoutParams(0, -2, 1));
            Button remove = new Button(activity); remove.setText(R.string.bchat_people_remove); Ui.styleAction(remove, Ui.ActionTone.TEXT);
            remove.setContentDescription(activity.getString(R.string.bchat_people_remove_named, label(id)));
            remove.setTag("people-remove-" + id); remove.setEnabled(editable() && !blocked);
            line.addView(remove, new LinearLayout.LayoutParams(-2, -2));
            remove.setOnClickListener(view -> { if (!visible(requestSerial) || !editable() || blocked) return;
                selection = selection.remove(id); ++editRevision; draw(); });
            selectedRows.addView(line, full());
        }
        if (page == null) text(rows, false).setText(R.string.bchat_people_unknown_page);
        else if (page.people.isEmpty()) text(rows, false).setText(R.string.bchat_people_empty);
        else for (GroupPeopleProtocol.Person person : page.people) {
            CompoundButton row = mode == GroupPeopleProtocol.Mode.DIRECT ? new RadioButton(activity) : new CheckBox(activity);
            row.setText(AppLocale.name(activity, person.name) + "\n" + activity.getString(R.string.bchat_people_user_id, digits(person.userId)));
            row.setTextColor(UiPalette.ink(activity)); row.setTextSize(15); row.setSingleLine(false); row.setMaxLines(Integer.MAX_VALUE); row.setEllipsize(null);
            row.setMinHeight(Ui.dp(activity, 48)); row.setMinimumHeight(Ui.dp(activity, 48)); Ui.pad(row, 8, 6);
            row.setTextDirection(AppLocale.textDirection(activity)); row.setTag("people-choice-" + person.userId);
            row.setChecked(selected.contains(person.userId)); row.setEnabled(editable() && !blocked && !selection.excludedUserIds.contains(person.userId));
            row.setOnClickListener(view -> {
                if (!visible(requestSerial) || !editable() || blocked) return;
                try { selection = selection.toggle(page, person.userId); ++editRevision; notice.setText(R.string.bchat_people_ready); }
                catch (IllegalArgumentException limit) { notice.setText(R.string.bchat_people_limit); }
                draw();
            });
            rows.addView(row, full());
        }
        drawActions();
    }
    private String label(long id) {
        if (selection != null) for (GroupPeopleProtocol.Person person : selection.people) if (person.userId == id)
            return AppLocale.name(activity, person.name) + " (" + digits(id) + ")";
        return activity.getString(R.string.bchat_people_user_id, digits(id));
    }
    private void drawActions() {
        boolean edit = editable() && !blocked;
        // Disabling the focused editor during a candidate GET drops native IME focus.
        // Leave typing available only before any mutation; every dispatch still uses !busy.
        search.setEnabled(pending == null && !confirmed && !paused && !closed && !blocked);
        searchAction.setEnabled(edit);
        if (name != null) { name.setEnabled(edit); description.setEnabled(edit); }
        review.setEnabled(edit && selection != null && !selection.people.isEmpty());
        next.setVisibility(page != null && page.nextAfterUserId != 0 ? View.VISIBLE : View.GONE);
        next.setEnabled(edit && page != null && page.nextAfterUserId != 0);
        retry.setVisibility(unknown && pending != null && !confirmed ? View.VISIBLE : View.GONE);
        retry.setEnabled(!closed && !paused && !busy && !blocked && unknown && pending != null && !confirmed);
        // Re-rendering rows while dispatching is unnecessary, but every old control must stop.
        setChildrenEnabled(selectedRows, edit); setChildrenEnabled(rows, edit);
    }
    private static void setChildrenEnabled(LinearLayout parent, boolean enabled) {
        for (int i = 0; i < parent.getChildCount(); i++) {
            View child = parent.getChildAt(i);
            if (child instanceof LinearLayout) {
                LinearLayout line = (LinearLayout) child;
                for (int j = 0; j < line.getChildCount(); j++) if (line.getChildAt(j) instanceof Button) line.getChildAt(j).setEnabled(enabled);
            } else if (child instanceof CompoundButton && !enabled) child.setEnabled(false);
        }
    }
    private void dismissConfirmation() { AlertDialog current = confirmation; confirmation = null; if (current != null) current.dismiss(); }
    private EditText field(LinearLayout parent, int label, boolean single) {
        text(parent, true).setText(label); EditText field = new EditText(activity);
        field.setTextSize(16); field.setTextColor(UiPalette.ink(activity)); field.setSingleLine(single); field.setMinHeight(Ui.dp(activity, 48));
        field.setTextDirection(AppLocale.textDirection(activity)); if (!single) { field.setMinLines(2); field.setMaxLines(Integer.MAX_VALUE); }
        field.setContentDescription(activity.getString(label)); parent.addView(field, full());
        field.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence value, int start, int count, int after) { }
            public void onTextChanged(CharSequence value, int start, int before, int count) { ++editRevision; }
            public void afterTextChanged(Editable value) { }
        }); return field;
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
    private static boolean denied(int status) { return status == 401 || status == 403 || status == 404 || status == 409; }
    private static void mainThread() { if (Looper.myLooper() != Looper.getMainLooper()) throw new IllegalStateException("People UI requires MAIN"); }
}

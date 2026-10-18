package com.baseer.freshchat;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import com.baseer.freshchat.sync.AccountScope;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONObject;

/** One bounded read-only page; forms and navigation share its adaptive scroll surface. */
final class BChatRoomExplorePanel {
    interface Reply { void complete(int status, JSONObject body); }
    interface Host {
        AccountScope account();
        /** MAIN only: current account object/session/room/recipient epoch/company/rights. */
        boolean current(AccountScope scope, long room, long membership, long generation);
        boolean supported();
        boolean mediaAllowed();
        /** Existing authenticated session; Host must repeat current() before dispatch. */
        boolean read(RoomExploreProtocol.Query query, Reply reply);
        /** Canonical navigation only; search rows never authorize media/receipt actions. */
        void openMessage(long id);
        String timeLabel(String utcStamp);
    }
    private final Activity activity;
    private final Host host;
    private final AccountScope scope;
    private final long roomId, membershipId, generation;
    private final boolean gallery, canMedia;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Dialog dialog;
    private final RecyclerView list;
    private final Rows adapter = new Rows();
    private final LinearLayout form, footer;
    private final EditText input;
    private final TextView notice;
    private final Button search, retry, older, previous, first;
    private final List<Button> filters = new ArrayList<>();
    private final List<RoomExploreProtocol.Kind> filterKinds = new ArrayList<>();
    private final ArrayDeque<Long> back = new ArrayDeque<>();
    private RoomExploreProtocol.Kind kind = RoomExploreProtocol.Kind.ALL;
    private RoomExploreProtocol.Query attempted, displayedQuery;
    private RoomExploreProtocol.Page page;
    private int attemptedDirection;
    private long serial;
    private boolean busy, closed, shown;
    private Runnable delayed, timeout;

    BChatRoomExplorePanel(Activity activity, Host host, AccountScope scope,
            long room, long membership, long generation, boolean gallery) {
        new RoomExploreProtocol.Query(room, membership, true, RoomExploreProtocol.Kind.ALL, null, 0);
        if (host == null || scope == null) throw new IllegalArgumentException("Current room binding required");
        this.activity = activity; this.host = host; this.scope = scope; roomId = room;
        membershipId = membership; this.generation = generation; this.gallery = gallery;
        canMedia = host.mediaAllowed();
        dialog = new Dialog(activity); dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        dialog.setTitle(gallery ? R.string.explore_media_title : R.string.explore_search_title);
        LinearLayout root = Ui.column(activity);
        root.setBackground(Ui.bg(UiPalette.surface(activity), 18, activity));
        LinearLayout heading = Ui.row(activity); Ui.pad(heading, 12, 8);
        TextView title = Ui.text(activity, activity.getString(gallery
                ? R.string.explore_media_title : R.string.explore_search_title), 20, Ui.INK, true);
        if (Build.VERSION.SDK_INT >= 28) title.setAccessibilityHeading(true);
        heading.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        View close = Ui.iconButton(activity, "close", activity.getString(R.string.task_close));
        close.setOnClickListener(ignored -> dismiss());
        heading.addView(close, new LinearLayout.LayoutParams(Ui.dp(activity, 48), Ui.dp(activity, 48)));
        root.addView(heading, new LinearLayout.LayoutParams(-1, -2));
        form = Ui.column(activity); Ui.pad(form, 16, 4);
        input = new EditText(activity); input.setTextSize(16); input.setSingleLine(true);
        input.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        input.setTextColor(UiPalette.ink(activity)); input.setHintTextColor(UiPalette.muted(activity));
        input.setBackground(Ui.outline(Ui.SURFACE, Ui.LINE, 12, activity));
        input.setHint(canMedia ? R.string.explore_query_hint : R.string.explore_query_text_hint);
        Ui.pad(input, 12, 10); input.setMinHeight(Ui.dp(activity, 48));
        form.addView(input, new LinearLayout.LayoutParams(-1, -2));
        search = action(form, R.string.explore_search, Ui.ActionTone.PRIMARY, this::newQuery);
        input.setOnEditorActionListener((view, action, event) -> {
            if (action != EditorInfo.IME_ACTION_SEARCH) return false;
            newQuery(); return true;
        });
        input.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) {
                if (!busy && !closed) {
                    attempted = null; displayedQuery = null; page = null; back.clear();
                    noticeText(R.string.explore_start); adapter.notifyDataSetChanged(); drawActions();
                }
            }
            @Override public void afterTextChanged(Editable text) { }
        });
        input.setVisibility(gallery ? View.GONE : View.VISIBLE);
        search.setVisibility(gallery ? View.GONE : View.VISIBLE);
        LinearLayout chips = Ui.row(activity);
        addFilter(chips, RoomExploreProtocol.Kind.ALL, R.string.explore_all);
        if (!gallery) addFilter(chips, RoomExploreProtocol.Kind.TEXT, R.string.explore_text);
        if (canMedia) {
            addFilter(chips, RoomExploreProtocol.Kind.IMAGE, R.string.explore_images);
            addFilter(chips, RoomExploreProtocol.Kind.FILE, R.string.explore_files);
            addFilter(chips, RoomExploreProtocol.Kind.AUDIO, R.string.explore_audio);
        }
        HorizontalScrollView strip = new HorizontalScrollView(activity);
        strip.setHorizontalScrollBarEnabled(false); strip.addView(chips);
        form.addView(strip, new LinearLayout.LayoutParams(-1, -2));
        TextView note = Ui.text(activity, activity.getString(R.string.explore_scope_note), 12, Ui.MUTED, false);
        form.addView(note, new LinearLayout.LayoutParams(-1, -2));
        notice = Ui.text(activity, "", 14, Ui.MUTED, false); Ui.pad(notice, 0, 8);
        notice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        form.addView(notice, new LinearLayout.LayoutParams(-1, -2));
        retry = action(form, R.string.explore_retry, Ui.ActionTone.SECONDARY, () -> {
            if (attempted != null) load(attempted, attemptedDirection);
        });
        footer = Ui.column(activity); Ui.pad(footer, 16, 8);
        older = action(footer, R.string.explore_older, Ui.ActionTone.SECONDARY, () -> {
            if (page != null && page.nextBeforeId > 0) load(query(page.nextBeforeId), 1);
        });
        previous = action(footer, R.string.explore_previous, Ui.ActionTone.SECONDARY, () -> {
            if (!back.isEmpty()) load(query(back.peekLast()), -1);
        });
        first = action(footer, R.string.explore_first, Ui.ActionTone.TEXT, () -> load(query(0), 2));
        list = new RecyclerView(activity); list.setLayoutManager(new LinearLayoutManager(activity));
        list.setItemAnimator(null); list.setAdapter(adapter); list.setClipToPadding(false);
        root.addView(list, new LinearLayout.LayoutParams(-1, 0, 1));
        dialog.setContentView(root); dialog.setOnDismissListener(ignored -> close());
    }
    void show() {
        if (closed || shown || !bound()) return;
        shown = true; dialog.show();
        Window window = dialog.getWindow();
        if (window != null) {
            window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            window.setGravity(Gravity.BOTTOM);
            window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            window.setLayout(Math.min(activity.getResources().getDisplayMetrics().widthPixels, Ui.dp(activity, 560)), -1);
        }
        if (!host.supported()) noticeText(R.string.explore_unsupported);
        else if (gallery && !canMedia) noticeText(R.string.explore_unavailable);
        else if (gallery) load(query(0), 2);
        else noticeText(R.string.explore_start);
        drawActions();
    }
    /** Host closes on pause/rights or identity changes. No automatic HTTP on resume. */
    void dismiss() { dialog.dismiss(); close(); }
    private void close() {
        if (closed) return;
        closed = true; ++serial; busy = false; clearTimers();
        page = null; attempted = null; displayedQuery = null; back.clear();
        input.setText(""); notice.setText(""); list.setAdapter(null); list.getRecycledViewPool().clear();
    }
    private boolean bound() {
        return scope == host.account() && host.current(scope, roomId, membershipId, generation);
    }
    private boolean visible(long request) {
        if (closed) return false;
        if (!bound()) { dismiss(); return false; }
        return shown && dialog.isShowing() && serial == request;
    }
    private RoomExploreProtocol.Query query(long before) {
        return new RoomExploreProtocol.Query(roomId, membershipId, gallery, kind, input.getText().toString(), before);
    }
    private void newQuery() {
        if (busy || !visible(serial)) return;
        try {
            RoomExploreProtocol.Query next = query(0);
            InputMethodManager keyboard = (InputMethodManager) activity.getSystemService(Activity.INPUT_METHOD_SERVICE);
            if (keyboard != null) keyboard.hideSoftInputFromWindow(input.getWindowToken(), 0);
            input.clearFocus(); load(next, 2);
        } catch (IllegalArgumentException invalid) { noticeText(R.string.explore_invalid_query); }
    }
    /** direction changes cursor history only after a validated page, never on failed reads. */
    private void load(RoomExploreProtocol.Query next, int direction) {
        if (busy || !visible(serial) || !host.supported() || gallery && !canMedia) return;
        final long request = ++serial;
        final RoomExploreProtocol.Query prior = displayedQuery;
        attempted = next; attemptedDirection = direction; busy = true; page = null; notice.setText("");
        adapter.notifyDataSetChanged(); drawActions(); clearTimers();
        delayed = () -> { if (visible(request) && busy) noticeText(gallery
                ? R.string.explore_loading_media : R.string.explore_loading_search); };
        main.postDelayed(delayed, 200);
        timeout = () -> {
            if (!visible(request) || !busy) return;
            ++serial; busy = false; clearTimers(); noticeText(R.string.explore_unconfirmed); drawActions();
        };
        main.postDelayed(timeout, 25000);
        boolean started;
        try {
            started = host.read(next, (status, response) -> main.post(() -> {
                if (!visible(request) || !busy) return; // A duplicate callback cannot mutate cursor history twice.
                clearTimers(); busy = false;
                try {
                    if (status != 200) throw new IllegalArgumentException("Read not confirmed");
                    RoomExploreProtocol.Page received = RoomExploreProtocol.page(response, next);
                    if (direction == 2) back.clear();
                    else if (direction > 0 && prior != null) {
                        if (back.size() == 30) back.removeFirst(); back.addLast(prior.beforeId);
                    } else if (direction < 0 && !back.isEmpty()) back.removeLast();
                    displayedQuery = next; page = received;
                    noticeText(received.rows.isEmpty() ? gallery ? R.string.explore_empty_media
                            : R.string.explore_empty_search : 0);
                    adapter.notifyDataSetChanged(); list.scrollToPosition(0);
                } catch (IllegalArgumentException invalid) {
                    boolean denied = status == 401 || status == 403 || status == 404 || status == 409;
                    if (denied) { attempted = null; displayedQuery = null; back.clear(); }
                    noticeText(denied ? R.string.explore_unavailable : R.string.explore_unconfirmed);
                }
                drawActions();
            }));
        } catch (RuntimeException unavailable) { started = false; }
        if (!started && visible(request)) {
            ++serial; busy = false; clearTimers(); noticeText(R.string.explore_unconfirmed); drawActions();
        }
    }
    private void clearTimers() {
        if (delayed != null) main.removeCallbacks(delayed);
        if (timeout != null) main.removeCallbacks(timeout);
        delayed = null; timeout = null;
    }
    private void noticeText(int message) { if (notice != null) notice.setText(message == 0 ? "" : activity.getString(message)); }
    private void drawActions() {
        boolean enabled = !closed && !busy && host.supported() && (!gallery || canMedia);
        input.setEnabled(enabled); search.setEnabled(enabled);
        for (int i = 0; i < filters.size(); ++i) {
            filters.get(i).setEnabled(enabled);
            Ui.styleAction(filters.get(i), filterKinds.get(i) == kind ? Ui.ActionTone.PRIMARY : Ui.ActionTone.SECONDARY);
        }
        retry.setVisibility(!busy && attempted != null && page == null ? View.VISIBLE : View.GONE);
        retry.setEnabled(enabled);
        older.setVisibility(page != null && page.nextBeforeId > 0 ? View.VISIBLE : View.GONE);
        previous.setVisibility(!back.isEmpty() ? View.VISIBLE : View.GONE);
        first.setVisibility(displayedQuery != null && displayedQuery.beforeId > 0 ? View.VISIBLE : View.GONE);
        older.setEnabled(enabled); previous.setEnabled(enabled); first.setEnabled(enabled);
    }
    private void addFilter(LinearLayout parent, RoomExploreProtocol.Kind value, int label) {
        Button button = action(parent, label, Ui.ActionTone.SECONDARY, () -> {
            if (busy || kind == value || !visible(serial)) return;
            kind = value; page = null; attempted = null; displayedQuery = null; back.clear();
            adapter.notifyDataSetChanged(); drawActions();
            if (gallery || !input.getText().toString().trim().isEmpty()) newQuery();
            else noticeText(R.string.explore_start);
        });
        button.setLayoutParams(new LinearLayout.LayoutParams(-2, -2));
        filters.add(button); filterKinds.add(value);
    }
    private Button action(LinearLayout parent, int text, Ui.ActionTone tone, Runnable action) {
        Button button = new Button(activity); button.setText(text); button.setSingleLine(false);
        button.setMaxLines(Integer.MAX_VALUE); button.setEllipsize(null); button.setMinHeight(Ui.dp(activity, 48));
        Ui.styleAction(button, tone); button.setOnClickListener(ignored -> action.run());
        parent.addView(button, new LinearLayout.LayoutParams(-1, -2)); return button;
    }
    private void attach(FrameLayout holder, View view) {
        if (view.getParent() == holder) return;
        if (view.getParent() instanceof ViewGroup) ((ViewGroup) view.getParent()).removeView(view);
        holder.removeAllViews(); holder.addView(view, new FrameLayout.LayoutParams(-1, -2));
    }
    private final class Rows extends RecyclerView.Adapter<RecyclerView.ViewHolder> {
        Rows() { setHasStableIds(true); }
        private List<RoomExploreProtocol.Row> results() { return page == null ? Collections.emptyList() : page.rows; }
        @Override public int getItemCount() { return results().size() + 2; }
        @Override public int getItemViewType(int position) { return position == 0 ? 0 : position == getItemCount() - 1 ? 2 : 1; }
        @Override public long getItemId(int position) { return position == 0 ? Long.MIN_VALUE
                : position == getItemCount() - 1 ? Long.MIN_VALUE + 1 : row(position).id; }
        private RoomExploreProtocol.Row row(int position) { return results().get(results().size() - position); }
        @NonNull @Override public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int type) {
            if (type != 1) {
                FrameLayout frame = new FrameLayout(activity);
                frame.setLayoutParams(new RecyclerView.LayoutParams(-1, -2));
                return new RecyclerView.ViewHolder(frame) { };
            }
            return new ResultHolder();
        }
        @Override public void onBindViewHolder(@NonNull RecyclerView.ViewHolder holder, int position) {
            if (closed || !bound()) {
                holder.itemView.setVisibility(View.INVISIBLE);
                main.post(BChatRoomExplorePanel.this::dismiss);
                return;
            }
            holder.itemView.setVisibility(View.VISIBLE);
            if (getItemViewType(position) != 1) {
                attach((FrameLayout) holder.itemView, position == 0 ? form : footer); return;
            }
            ((ResultHolder) holder).bind(row(position));
        }
        @Override public void onViewRecycled(@NonNull RecyclerView.ViewHolder holder) {
            if (holder instanceof ResultHolder) ((ResultHolder) holder).scrub();
        }
    }
    private final class ResultHolder extends RecyclerView.ViewHolder {
        final TextView author, preview, file, time;
        long id;
        ResultHolder() {
            super(Ui.column(activity)); LinearLayout card = (LinearLayout) itemView;
            Ui.pad(card, 16, 12); card.setBackground(Ui.bg(Ui.SURFACE, 0, activity));
            card.setLayoutParams(new RecyclerView.LayoutParams(-1, -2)); card.setMinimumHeight(Ui.dp(activity, 64));
            author = Ui.text(activity, "", 15, Ui.INK, true);
            preview = Ui.text(activity, "", 16, Ui.INK, false); preview.setMaxLines(3);
            preview.setEllipsize(android.text.TextUtils.TruncateAt.END);
            file = Ui.text(activity, "", 13, Ui.GREEN, false); file.setMaxLines(2);
            file.setEllipsize(android.text.TextUtils.TruncateAt.END);
            time = Ui.text(activity, "", 12, Ui.MUTED, false);
            for (TextView line : new TextView[]{author, preview, file, time})
                card.addView(line, new LinearLayout.LayoutParams(-1, -2));
            card.addView(Ui.line(activity), new LinearLayout.LayoutParams(-1, Ui.dp(activity, 1)));
            Ui.clickable(card); card.setOnClickListener(ignored -> {
                int position = getBindingAdapterPosition();
                if (!busy && visible(serial) && position > 0 && position < adapter.getItemCount() - 1
                        && id == adapter.getItemId(position)) { long target = id; dismiss(); host.openMessage(target); }
            });
        }
        void bind(RoomExploreProtocol.Row row) {
            itemView.setEnabled(true); id = row.id; author.setText(row.author); preview.setText(row.text);
            preview.setVisibility(row.text.isEmpty() ? View.GONE : View.VISIBLE);
            file.setText(canMedia ? row.fileName : activity.getString(R.string.explore_file));
            file.setVisibility(row.mediaKind.isEmpty() ? View.GONE : View.VISIBLE);
            time.setText(host.timeLabel(row.createdAt));
            itemView.setContentDescription(activity.getString(R.string.explore_open_message)
                    + ", " + row.author + ", " + excerpt(row.text) + (canMedia ? ", " + row.fileName : ""));
        }
        void scrub() {
            id = 0; author.setText(""); preview.setText(""); file.setText(""); time.setText("");
            itemView.setContentDescription(null); itemView.setEnabled(false);
        }
    }
    private static String excerpt(String value) {
        return value.codePointCount(0, value.length()) <= 240 ? value
                : value.substring(0, value.offsetByCodePoints(0, 240)) + "…";
    }
}

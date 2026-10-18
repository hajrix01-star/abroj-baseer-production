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
import android.view.WindowInsets;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
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

/** Actual SDK35 native Dialog/Activity/JSON. Account/rights/company/journal/HTTP are FAKE
 * Host inputs; no real auth, storage, backend, product Activity, FCM, audio or device claim. */
public final class GroupPeopleInstrumentation extends Instrumentation {
    private final List<String> failures = new ArrayList<>();
    private final JSONArray renders = new JSONArray(), journeys = new JSONArray(), imeTrace = new JSONArray();
    private int assertions, nativeJsonChecks;
    private boolean failuresOnly, imeFixOnly, imeOnly;
    private JSONObject footerGeometry;
    private GroupPeopleTestActivity activity;
    private interface Journey { void run() throws Exception; }
    /** Instrumentation assertions must be reported by journey(), not crash the app MAIN.
     * This catches only this fixture's synchronous actions, never production async work. */
    @Override public void runOnMainSync(Runnable action) {
        Throwable[] failure = {null};
        super.runOnMainSync(() -> { try { action.run(); } catch (Throwable error) { failure[0] = error; } });
        if (failure[0] != null) throw new AssertionError("Synchronous fixture MAIN action failed", failure[0]);
    }
    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        if (args == null || !"true".equals(args.getString("disposable"))) throw new IllegalArgumentException("Explicit isolated test package required");
        failuresOnly = "failures".equals(args.getString("selection"));
        imeFixOnly = "ime-fix".equals(args.getString("selection"));
        imeOnly = "ime-only".equals(args.getString("selection"));
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            require(getTargetContext().getPackageName().equals("com.baseer.bchat.group.people.test"), "Exact isolated package");
            require(android.os.Build.VERSION.SDK_INT == 35, "Actual API35 runtime");
            if (imeFixOnly || imeOnly) {
                journey("native_ime_visible_editor_search_font2_footer_reachable", this::nativeIme);
                if (imeFixOnly) {
                journey("candidate_edit_stale_page_explicit_search_and_denial_priority", this::staleCandidateEdit);
                journey("pending_and_unknown_search_disabled_exact_intent", this::pendingDisabled);
                }
            } else {
            if (!failuresOnly) {
                journey("actual_native_json_shapes", this::nativeJson);
                for (String language : new String[]{"ar", "en"}) for (boolean dark : new boolean[]{false, true}) for (float scale : new float[]{1, 2}) {
                    render(language, dark, scale, "picker"); render(language, dark, scale, "events");
                }
            }
            journey("explicit_confirmation_no_request_on_open_select_render", this::confirmation);
            if (!failuresOnly) journey("selection49_across_pages_search_limit", this::selection49);
            journey("filtered_empty_progress_and_single_direct_selection", this::filteredAndDirect);
            journey("unknown_exact_retry_pause_no_automatic_request", this::unknownRetry);
            journey("add_ack_fullset_or_unknown_never_subset_success", this::fullSet);
            if (!failuresOnly) {
                journey("close_pause_latest_request_and_binding_fences", this::fences);
                journey("events_bounded_pagination_refresh_no_rawmetadata_or_write", this::eventJourney);
                journey("events_denied_epoch_and_background_callback", this::eventFailures);
                journey("people_background_callback_on_main", this::background);
            }
            journey("native_ime_visible_editor_search_font2_footer_reachable", this::nativeIme);
            }
        } catch (Throwable error) { failures.add("Harness: " + error); }
        finally { close(); }
        try {
            JSONObject evidence = new JSONObject().put("schema", 1).put("passed", failures.isEmpty())
                    .put("android_api", android.os.Build.VERSION.SDK_INT).put("package", getTargetContext().getPackageName())
                    .put("assertions", assertions).put("native_json_checks", nativeJsonChecks).put("renders", renders).put("journeys", journeys)
                    .put("selection", imeOnly ? "ime-only" : imeFixOnly ? "ime-fix" : failuresOnly ? "failures" : "all").put("ime_trace", imeTrace)
                    .put("footer_geometry", footerGeometry == null ? JSONObject.NULL : footerGeometry)
                    .put("failures", new JSONArray(failures)).put("scope", "Actual native Activity/Dialog/JSON/locale/IME visibility; programmatic View input and native InputConnection editor action, not physical typing; fake Host/account/rights/HTTP/journal. No actual auth/storage/backend/Activity hook/FCM/audio/phone claim");
            write("group-people-results.json", evidence.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Throwable error) { failures.add("Evidence: " + error); }
        result.putString("stream", (failures.isEmpty() ? (imeOnly ? "PASS 1 focused native IME geometry journey; " : imeFixOnly ? "PASS 3 focused native IME/stale-edit/pending journeys; " : failuresOnly ? "PASS 5 focused native confirmation/IME journeys; " : "PASS 16 native panel renders across 8 configurations and 11 focused journeys; ") + assertions + " assertions"
                : "FAIL group people component: " + failures) + "\n");
        finish(failures.isEmpty() ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
    }
    private GroupPeopleTestActivity open(String language, boolean dark, float scale, String surface, GroupPeopleProtocol.Mode mode) throws Exception {
        close(); require(new LocalSettings(getTargetContext()).language(language), "Test-only locale preference commit");
        GroupPeopleTestActivity.language = language; GroupPeopleTestActivity.dark = dark; GroupPeopleTestActivity.scale = scale;
        GroupPeopleTestActivity.surface = surface; GroupPeopleTestActivity.mode = mode;
        activity = (GroupPeopleTestActivity) startActivitySync(new Intent(getTargetContext(), GroupPeopleTestActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        settle(); return activity;
    }
    private GroupPeopleTestActivity picker(GroupPeopleProtocol.Mode mode) throws Exception { return open("ar", false, 1, "picker", mode); }
    private Object panel() { return activity.panel(); }
    private void fillCreate() {
        field(panel(), "name", EditText.class).setText("فريق بصير Operations");
        field(panel(), "description", EditText.class).setText("وصف طويل لاختبار الالتفاف وإتاحة القراءة.\nA clear bounded group description.");
    }
    private void choose(long id) { View choice = tag(field(panel(), "rows", LinearLayout.class), "people-choice-" + id); require(choice != null, "Actual candidate view exists " + id); choice.performClick(); }
    private void click(String name) { field(panel(), name, Button.class).performClick(); }
    private void confirmPositive() {
        Button positive = field(panel(), "confirmation", AlertDialog.class).getButton(AlertDialog.BUTTON_POSITIVE);
        Rect visible = new Rect();
        require(positive.getWidth() > 0 && positive.getHeight() >= Ui.dp(activity, 48)
                && positive.getGlobalVisibleRect(visible) && visible.height() >= positive.getHeight() - 1,
                "Actual laid-out positive confirmation button before programmatic click");
        positive.performClick();
    }
    private void render(String language, boolean dark, float scale, String surface) {
        String label = (surface.equals("picker") ? "people-picker" : "group-events") + "-" + language + "-" + (dark ? "dark" : "light") + "-" + scale;
        int before = failures.size();
        try {
            GroupPeopleTestActivity current = open(language, dark, scale, surface, GroupPeopleProtocol.Mode.CREATE);
            runOnMainSync(() -> { if (surface.equals("picker")) { fillCreate(); choose(100); choose(101); } });
            awaitDraw(field(panel(), "dialog", AlertDialog.class));
            runOnMainSync(() -> {
                AlertDialog dialog = field(panel(), "dialog", AlertDialog.class); View decor = dialog.getWindow().getDecorView();
                float width = decor.getWidth() / current.getResources().getDisplayMetrics().density;
                check(current.getResources().getConfiguration().screenWidthDp == 360, label + " actual360dp viewport");
                check(Math.abs(width - 328) <= 2, label + " production328dp Dialog width, not fixture-widened");
                check(Math.abs(current.getResources().getConfiguration().fontScale - scale) < .01, label + " actual fontScale");
                check(ChatAppearance.dark(current) == dark && AppLocale.rtl(current) == language.equals("ar"), label + " locale/theme");
                inspect(decor, decor, label); capture(decor, label + "-top.png");
                field(panel(), "scroll", ScrollView.class).fullScroll(View.FOCUS_DOWN);
            });
            waitFor(() -> !field(panel(), "scroll", ScrollView.class).canScrollVertically(1), "Reach bottom", 3000);
            awaitDraw(field(panel(), "dialog", AlertDialog.class));
            runOnMainSync(() -> {
                AlertDialog dialog = field(panel(), "dialog", AlertDialog.class); capture(dialog.getWindow().getDecorView(), label + "-bottom.png");
                if (surface.equals("picker") && scale == 2) click("review");
            });
            if (surface.equals("picker") && scale == 2) awaitDraw(field(panel(), "confirmation", AlertDialog.class));
            runOnMainSync(() -> {
                if (surface.equals("picker") && scale == 2) {
                    AlertDialog confirmation = field(panel(), "confirmation", AlertDialog.class);
                    require(confirmation != null && confirmation.isShowing(), "Actual confirmation dialog");
                    inspect(confirmation.getWindow().getDecorView(), confirmation.getWindow().getDecorView(), "confirmation-" + label);
                    capture(confirmation.getWindow().getDecorView(), "people-confirm-" + language + "-" + (dark ? "dark" : "light") + "-2.0.png");
                    check(current.peopleHost.requests.isEmpty(), "Rendering confirmation never dispatches");
                }
                try { renders.put(new JSONObject().put("case", label).put("language", language).put("dark", dark).put("font_scale", scale)
                        .put("surface", surface).put("passed", failures.size() == before)); } catch (Exception invalid) { throw new AssertionError(invalid); }
            });
        } catch (Throwable error) { failures.add(label + ": " + error); }
        finally { close(); }
    }
    private void nativeJson() throws Exception {
        GroupPeopleProtocol.CandidateQuery query = new GroupPeopleProtocol.CandidateQuery(7, 41, "ع & ?", 0);
        check(!query.path().contains("after_user_id=0") && query.path().contains("%26"), "Native query encoding/cursor0"); nativeJsonChecks++;
        GroupPeopleProtocol.CandidatePage empty = GroupPeopleProtocol.candidates(new JSONObject("{\"api_version\":2,\"users\":[],\"next_after_user_id\":80}"), query);
        check(empty.people.isEmpty() && empty.nextQuery().afterUserId == 80, "Native filtered-empty progress"); nativeJsonChecks++;
        for (String raw : new String[]{"{\"api_version\":2.0,\"users\":[],\"next_after_user_id\":null}", "{\"api_version\":\"2\",\"users\":[],\"next_after_user_id\":null}",
                "{\"api_version\":2,\"users\":[],\"next_after_user_id\":0}"}) {
            try { GroupPeopleProtocol.candidates(new JSONObject(raw), query); check(false, "Native bad numeric shape rejected"); }
            catch (IllegalArgumentException expected) { check(true, "Native strict numeric type"); nativeJsonChecks++; }
        }
        JSONObject events = GroupPeopleTestActivity.eventPage(new GroupPeopleProtocol.EventsQuery(17, 23, 0), 12);
        check(GroupPeopleProtocol.events(events, new GroupPeopleProtocol.EventsQuery(17, 23, 0)).events.get(0).actorMembershipId == 0, "Native null actor membership valid"); nativeJsonChecks++;
        events.put("membership_id", JSONObject.NULL);
        try { GroupPeopleProtocol.events(events, new GroupPeopleProtocol.EventsQuery(17, 23, 0)); check(false, "Null viewer membership rejected"); }
        catch (IllegalArgumentException expected) { check(true, "Native top member positive only"); nativeJsonChecks++; }
    }
    private void confirmation() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.CREATE);
        runOnMainSync(() -> {
            require(current.peopleHost.requests.isEmpty(), "Open only GET"); fillCreate(); choose(100); choose(101);
            check(current.peopleHost.requests.isEmpty(), "Input/select only RAM"); click("review");
        });
        awaitDraw(field(panel(), "confirmation", AlertDialog.class));
        runOnMainSync(() -> {
            check(current.peopleHost.requests.isEmpty(), "Review does not request");
            field(panel(), "confirmation", AlertDialog.class).getButton(AlertDialog.BUTTON_NEGATIVE).performClick();
            check(current.peopleHost.requests.isEmpty(), "Cancel confirmation no request");
        });
        // Dialog.OnDismissListener is queued on MAIN. A real next click arrives only
        // after that boundary; do not request a new review inside the cancel action.
        waitFor(() -> field(panel(), "confirmation", AlertDialog.class) == null, "Canceled confirmation dismissal observed", 3000);
        waitForIdleSync(); runOnMainSync(() -> click("review"));
        awaitDraw(field(panel(), "confirmation", AlertDialog.class)); runOnMainSync(this::confirmPositive); settle();
        runOnMainSync(() -> check(current.peopleHost.requests.size() == 1 && field(panel(), "confirmed", Boolean.class), "Only explicit confirm accepts original create ACK without UUID echo"));
    }
    private void selection49() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.CREATE);
        runOnMainSync(() -> { fillCreate(); for (long id = 100; id < 140; id++) choose(id); click("next"); }); settle();
        runOnMainSync(() -> {
            for (long id = 140; id < 149; id++) choose(id);
            check(field(panel(), "selection", GroupPeopleProtocol.Selection.class).people.size() == 49, "49 selected across actual two pages");
            int requests = current.peopleHost.queries.size(); field(panel(), "search", EditText.class).setText("more");
            check(current.peopleHost.queries.size() == requests, "Typing does not search"); click("searchAction");
        }); settle();
        runOnMainSync(() -> {
            choose(200); check(field(panel(), "selection", GroupPeopleProtocol.Selection.class).people.size() == 49, "50th choice refused, no lost old choices");
            check(current.peopleHost.queries.get(current.peopleHost.queries.size() - 1).afterUserId == 0, "New explicit search resets0");
            check(current.peopleHost.requests.isEmpty(), "No batch request until confirmation");
        });
    }
    private void filteredAndDirect() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.DIRECT);
        runOnMainSync(() -> { choose(100); choose(101); check(field(panel(), "selection", GroupPeopleProtocol.Selection.class).people.size() == 1, "Direct is single selection");
            field(panel(), "search", EditText.class).setText("filtered"); click("searchAction"); }); settle();
        runOnMainSync(() -> {
            check(field(panel(), "page", GroupPeopleProtocol.CandidatePage.class).people.isEmpty() && field(panel(), "next", Button.class).isEnabled(), "Filtered empty page still has explicit next"); click("next");
        }); settle();
        runOnMainSync(() -> {
            check(current.peopleHost.queries.get(current.peopleHost.queries.size() - 1).afterUserId == 400, "Filtered cursor propagated, no automatic scan");
            click("review");
        });
        awaitDraw(field(panel(), "confirmation", AlertDialog.class)); runOnMainSync(this::confirmPositive); settle();
        runOnMainSync(() -> check(field(panel(), "confirmed", Boolean.class) && !GroupPeopleTestActivity.acknowledgement(current.peopleHost.requests.get(0), false).optBoolean("created"), "Existing pair false/false accepted"));
    }
    private void unknownRetry() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.DIRECT);
        runOnMainSync(() -> { choose(100); current.peopleHost.holdRequests = true; click("review"); });
        awaitDraw(field(panel(), "confirmation", AlertDialog.class));
        runOnMainSync(() -> { confirmPositive(); callActivityOnPause(current); });
        GroupPeopleProtocol.Intent original = current.peopleHost.requests.get(0);
        runOnMainSync(() -> {
            current.peopleHost.requestReplies.get(0).complete(200, current.peopleHost.requestBodies.get(0)); callActivityOnResume(current);
            check(!field(panel(), "confirmed", Boolean.class) && field(panel(), "unknown", Boolean.class), "Paused ACK cannot draw/settle Panel");
            check(current.peopleHost.requests.size() == 1, "Resume no auto retry"); current.peopleHost.holdRequests = false; click("retry");
        });
        awaitDraw(field(panel(), "confirmation", AlertDialog.class)); runOnMainSync(this::confirmPositive); settle();
        runOnMainSync(() -> check(current.peopleHost.requests.size() == 2 && current.peopleHost.requests.get(1) == original
                && current.peopleHost.requests.get(1).payload.equals(original.payload), "Explicit retry uses exact same immutable UUID/payload, no new decision"));
    }
    private void fullSet() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.ADD);
        runOnMainSync(() -> { choose(100); choose(101); current.peopleHost.holdRequests = true; click("review"); });
        awaitDraw(field(panel(), "confirmation", AlertDialog.class)); runOnMainSync(this::confirmPositive);
        GroupPeopleProtocol.Intent intent = current.peopleHost.requests.get(0);
        JSONObject subset = GroupPeopleTestActivity.acknowledgement(intent, false).put("added_user_ids", new JSONArray().put(100));
        runOnMainSync(() -> current.peopleHost.requestReplies.get(0).complete(200, subset)); settle();
        runOnMainSync(() -> {
            check(field(panel(), "unknown", Boolean.class) && !field(panel(), "confirmed", Boolean.class), "Subset never reports partial success");
            check(field(panel(), "pending", GroupPeopleProtocol.Intent.class) == intent && intent.userIds.size() == 2, "Full selection/intent preserved");
            current.peopleHost.requestStatus = 409; current.peopleHost.holdRequests = false; click("retry");
        });
        awaitDraw(field(panel(), "confirmation", AlertDialog.class)); runOnMainSync(this::confirmPositive); settle();
        runOnMainSync(() -> check(field(panel(), "blocked", Boolean.class) && !field(panel(), "retry", Button.class).isEnabled(), "Definitive refusal does not auto retry/delete/create new intent"));
    }
    private void fences() throws Exception {
        for (int i = 0; i < 7; i++) {
            GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.ADD); final int variant = i;
            runOnMainSync(() -> {
                current.peopleHost.holdCandidates = true; click("searchAction");
                if (variant == 0) current.peopleHost.account++;
                if (variant == 1) current.peopleHost.session++;
                if (variant == 2) current.peopleHost.global++;
                if (variant == 3) current.peopleHost.repository++;
                if (variant == 4) current.peopleHost.company++;
                if (variant == 5) current.peopleHost.member++;
                if (variant == 6) current.peopleHost.active = false;
                int last = current.peopleHost.candidateReplies.size() - 1;
                current.peopleHost.candidateReplies.get(last).complete(200, current.peopleHost.candidateBodies.get(last));
            }); waitForIdleSync();
            runOnMainSync(() -> check(field(panel(), "closed", Boolean.class) && field(panel(), "selection", GroupPeopleProtocol.Selection.class) == null
                    && field(panel(), "rows", LinearLayout.class).getChildCount() == 0, "Captured binding change wipes UI/no cross-scope callback " + variant));
        }
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.DIRECT);
        runOnMainSync(() -> { current.peopleHost.holdCandidates = true; click("searchAction"); current.picker.dismiss();
            int last = current.peopleHost.candidateReplies.size() - 1; current.peopleHost.candidateReplies.get(last).complete(200, current.peopleHost.candidateBodies.get(last)); }); waitForIdleSync();
        runOnMainSync(() -> check(field(panel(), "closed", Boolean.class) && !field(panel(), "dialog", AlertDialog.class).isShowing(), "Dismissed Panel never reopens from old callback"));
    }
    private void eventJourney() throws Exception {
        GroupPeopleTestActivity current = open("en", true, 1, "events", GroupPeopleProtocol.Mode.CREATE);
        runOnMainSync(() -> {
            check(!textTree(field(panel(), "dialog", AlertDialog.class).getWindow().getDecorView()).contains("PRIVATE_METADATA_NOT_RENDERED"), "No raw metadata rendered");
            current.eventsHost.firstCount = 30; click("refresh");
        }); settle();
        runOnMainSync(() -> { check(field(panel(), "rows", LinearLayout.class).getChildCount() == 30, "Audit one page30 only"); click("older"); }); settle();
        runOnMainSync(() -> {
            check(field(panel(), "rows", LinearLayout.class).getChildCount() == 2 && current.eventsHost.queries.get(2).beforeId == 121, "Older page replaces, exact before cursor");
            click("refresh");
        }); settle();
        int count = current.eventsHost.queries.size(); SystemClock.sleep(250); waitForIdleSync();
        runOnMainSync(() -> {
            check(current.eventsHost.queries.get(current.eventsHost.queries.size() - 1).beforeId == 0, "Manual audit refresh resets0");
            check(current.eventsHost.queries.size() == count, "No polling in observed250ms window");
            for (java.lang.reflect.Method method : BChatGroupEventsPanel.Host.class.getDeclaredMethods()) check(method.getName().equals("current") || method.getName().equals("load"), "Read-only Host has no write/ACK surface");
        });
    }
    private void eventFailures() throws Exception {
        GroupPeopleTestActivity current = open("ar", false, 1, "events", GroupPeopleProtocol.Mode.CREATE);
        JSONObject wrong = GroupPeopleTestActivity.eventPage(new GroupPeopleProtocol.EventsQuery(17, 23, 0), 1).put("membership_id", JSONObject.NULL);
        runOnMainSync(() -> { current.eventsHost.override = wrong; click("refresh"); }); settle();
        runOnMainSync(() -> { check(field(panel(), "page", GroupPeopleProtocol.EventsPage.class) == null, "Null viewer member does not render"); current.eventsHost.override = null; current.eventsHost.status = 403; click("refresh"); }); settle();
        runOnMainSync(() -> { check(field(panel(), "page", GroupPeopleProtocol.EventsPage.class) == null, "Denial clears page"); current.eventsHost.status = 200; current.eventsHost.background = true; click("refresh"); }); settle();
        runOnMainSync(() -> { check(field(panel(), "page", GroupPeopleProtocol.EventsPage.class) != null, "Background callback marshalled to MAIN");
            current.eventsHost.hold = true; click("refresh"); current.eventsHost.member++;
            int last = current.eventsHost.replies.size() - 1; current.eventsHost.replies.get(last).complete(200, current.eventsHost.bodies.get(last)); }); waitForIdleSync();
        runOnMainSync(() -> check(field(panel(), "closed", Boolean.class) && field(panel(), "roster", java.util.Map.class).isEmpty(), "Epoch invalidation wipes labels and drops callback"));
    }
    private void background() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.DIRECT);
        runOnMainSync(() -> { current.peopleHost.background = true; click("searchAction"); }); settle();
        runOnMainSync(() -> check(field(panel(), "page", GroupPeopleProtocol.CandidatePage.class).people.size() == 40, "People background response draws on MAIN"));
    }
    private void nativeIme() throws Exception {
        GroupPeopleTestActivity current = open("en", false, 2, "picker", GroupPeopleProtocol.Mode.DIRECT);
        int initialQueries = current.peopleHost.queries.size();
        runOnMainSync(() -> {
            EditText input = field(panel(), "search", EditText.class); input.requestFocus();
            input.requestRectangleOnScreen(new Rect(0, 0, input.getWidth(), input.getHeight()), true);
            input.setText("more");
            ((InputMethodManager) current.getSystemService(Activity.INPUT_METHOD_SERVICE)).showSoftInput(input, InputMethodManager.SHOW_IMPLICIT);
            check(current.peopleHost.queries.size() == initialQueries && current.peopleHost.requests.isEmpty(), "Focus/programmatic typing has no GET/POST");
        });
        waitFor(() -> imeVisible(), "Real native IME WindowInsets visible", 4000);
        awaitDraw(field(panel(), "dialog", AlertDialog.class));
        runOnMainSync(() -> {
            traceIme("before_editor_action");
            capture(field(panel(), "dialog", AlertDialog.class).getWindow().getDecorView(), "people-ime-en-light-2.0-form.png");
            // Actual native input connection/editor action, injected programmatically. This
            // is not a physical keyboard/user typing or a fake IME visibility flag.
            InputConnection connection = field(panel(), "search", EditText.class).onCreateInputConnection(new EditorInfo());
            require(connection != null && connection.performEditorAction(EditorInfo.IME_ACTION_SEARCH), "Native IME_ACTION_SEARCH accepted");
            traceIme("after_editor_action_loading_before_callback");
        }); settle();
        awaitDraw(field(panel(), "dialog", AlertDialog.class));
        runOnMainSync(() -> {
            traceIme("after_read_callback_and_preDraw");
            check(current.peopleHost.queries.size() == initialQueries + 1 && current.peopleHost.requests.isEmpty(), "Editor search dispatches exactly one read and zero mutation");
            check(current.peopleHost.queries.get(initialQueries).text.equals("more"), "Editor action uses current search text");
            traceIme("before_focus_preserving_scrollTo");
            ScrollView scroll = field(panel(), "scroll", ScrollView.class);
            // fullScroll(FOCUS_DOWN) changes focus to the footer and can dismiss IME;
            // scrollTo models scrolling while retaining the current editor focus.
            scroll.scrollTo(0, Math.max(0, scroll.getChildAt(0).getHeight() - scroll.getHeight() + scroll.getPaddingTop() + scroll.getPaddingBottom()));
        });
        waitFor(() -> !field(panel(), "scroll", ScrollView.class).canScrollVertically(1), "IME footer scroll reaches bottom", 3000);
        awaitDraw(field(panel(), "dialog", AlertDialog.class));
        runOnMainSync(() -> {
            AlertDialog dialog = field(panel(), "dialog", AlertDialog.class); View decor = dialog.getWindow().getDecorView();
            Button footer = field(panel(), "review", Button.class); Rect localVisible = new Rect(), frame = new Rect();
            decor.getWindowVisibleDisplayFrame(frame);
            traceIme("after_focus_preserving_scrollTo_and_preDraw");
            check(imeVisible(), "IME stays visible while reaching footer");
            boolean clippedVisible = footer.getLocalVisibleRect(localVisible), identity = identityViewMatrices(footer);
            int[] at = new int[2], rootAt = new int[2]; footer.getLocationOnScreen(at); decor.getLocationOnScreen(rootAt);
            Rect fullScreen = new Rect(at[0], at[1], at[0] + footer.getWidth(), at[1] + footer.getHeight());
            Rect clippedScreen = new Rect(localVisible); clippedScreen.offset(at[0], at[1]);
            try { footerGeometry = new JSONObject().put("transform_identity", identity)
                    .put("transform_assumption", "Footer and View-ancestor 2D matrices are identity; local visible rect is offset by getLocationOnScreen. No screen compositor transform measurement")
                    .put("target_size_px", new JSONArray().put(footer.getWidth()).put(footer.getHeight()))
                    .put("local_visible", clippedVisible).put("local_visible_rect", rect(localVisible))
                    .put("full_rect_screen", rect(fullScreen)).put("clipped_rect_screen", rect(clippedScreen))
                    .put("visible_frame_screen", rect(frame)).put("root_location_screen", new JSONArray().put(rootAt[0]).put(rootAt[1])); }
            catch (Exception invalid) { throw new AssertionError(invalid); }
            check(identity, "Only compare screen rectangles with identity View transforms");
            if (identity) check(footer.getHeight() >= Ui.dp(current, 48) && footer.getWidth() > 0 && clippedVisible
                    && localVisible.left <= 0 && localVisible.top <= 0 && localVisible.right >= footer.getWidth()
                    && localVisible.bottom >= footer.getHeight() && frame.contains(fullScreen), "Actual full footer remains reachable above native IME");
            capture(decor, "people-ime-en-light-2.0-footer.png");
        });
    }
    private static JSONArray rect(Rect value) { return new JSONArray().put(value.left).put(value.top).put(value.right).put(value.bottom); }
    private static boolean identityViewMatrices(View target) {
        View current = target;
        while (true) {
            if (!current.getMatrix().isIdentity()) return false;
            android.view.ViewParent parent = current.getParent(); if (!(parent instanceof View)) return true;
            current = (View) parent;
        }
    }
    private boolean imeVisible() {
        WindowInsets insets = field(panel(), "dialog", AlertDialog.class).getWindow().getDecorView().getRootWindowInsets();
        return insets != null && insets.isVisible(WindowInsets.Type.ime());
    }
    private void traceIme(String step) {
        View decor = field(panel(), "dialog", AlertDialog.class).getWindow().getDecorView();
        WindowInsets insets = decor.getRootWindowInsets(); EditText input = field(panel(), "search", EditText.class);
        View focus = decor.findFocus(); ScrollView scroll = field(panel(), "scroll", ScrollView.class);
        try { imeTrace.put(new JSONObject().put("step", step).put("ime_visible", insets != null && insets.isVisible(WindowInsets.Type.ime()))
                .put("ime_bottom_px", insets == null ? 0 : insets.getInsets(WindowInsets.Type.ime()).bottom)
                .put("input_enabled", input.isEnabled()).put("input_focused", input.hasFocus())
                .put("focus_class", focus == null ? JSONObject.NULL : focus.getClass().getName())
                .put("decor_height_px", decor.getHeight()).put("scroll_height_px", scroll.getHeight()).put("scroll_y_px", scroll.getScrollY())); }
        catch (Exception invalid) { throw new AssertionError(invalid); }
    }
    private void staleCandidateEdit() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.DIRECT);
        runOnMainSync(() -> {
            choose(100); current.peopleHost.holdCandidates = true;
            field(panel(), "search", EditText.class).setText("old"); click("searchAction");
        });
        GroupPeopleProtocol.Selection selected = field(panel(), "selection", GroupPeopleProtocol.Selection.class);
        int reads = current.peopleHost.queries.size();
        runOnMainSync(() -> {
            check(field(panel(), "busy", Boolean.class) && field(panel(), "search", EditText.class).isEnabled()
                    && !field(panel(), "searchAction", Button.class).isEnabled(), "Read allows typing, not another button dispatch");
            field(panel(), "search", EditText.class).setText("new");
            field(panel(), "search", EditText.class).onEditorAction(EditorInfo.IME_ACTION_SEARCH); click("searchAction");
            check(current.peopleHost.queries.size() == reads, "Busy IME/button cannot submit edited search");
            current.peopleHost.candidateReplies.get(reads - 1).complete(200, current.peopleHost.candidateBodies.get(reads - 1));
        }); settle();
        runOnMainSync(() -> {
            check(field(panel(), "page", GroupPeopleProtocol.CandidatePage.class) == null && tag(field(panel(), "rows", LinearLayout.class), "people-choice-100") == null,
                    "Old query is not rendered under edited search text");
            check(field(panel(), "selection", GroupPeopleProtocol.Selection.class) == selected && selected.selectedIds().contains(100L), "Stale query never drops selection");
            check(field(panel(), "pending", GroupPeopleProtocol.Intent.class) == null && field(panel(), "next", Button.class).getVisibility() == View.GONE, "Stale page cannot supply next cursor or create intent");
            check(field(panel(), "search", EditText.class).getText().toString().equals("new")
                    && field(panel(), "notice", TextView.class).getText().toString().equals(current.getString(R.string.bchat_people_search_changed)), "Typed query preserved with explicit-search explanation");
            check(current.peopleHost.queries.size() == reads && current.peopleHost.requests.isEmpty(), "No automatic new search/mutation");
            current.peopleHost.holdCandidates = false; click("searchAction");
        }); settle();
        runOnMainSync(() -> {
            check(current.peopleHost.queries.size() == reads + 1 && field(panel(), "page", GroupPeopleProtocol.CandidatePage.class).query.text.equals("new"), "Only explicit next search renders matching current text");
            check(field(panel(), "selection", GroupPeopleProtocol.Selection.class) == selected, "Explicit search keeps same immutable selection");
            current.peopleHost.holdCandidates = true; click("searchAction");
            field(panel(), "search", EditText.class).setText("denied-edit");
            int last = current.peopleHost.candidateReplies.size() - 1; current.peopleHost.candidateReplies.get(last).complete(403, current.peopleHost.candidateBodies.get(last));
        }); settle();
        runOnMainSync(() -> check(field(panel(), "blocked", Boolean.class) && field(panel(), "selection", GroupPeopleProtocol.Selection.class).people.isEmpty()
                && field(panel(), "notice", TextView.class).getText().toString().equals(current.getString(R.string.bchat_people_unavailable)), "Denied reply still fail-closes before query mismatch"));
        GroupPeopleTestActivity malformed = picker(GroupPeopleProtocol.Mode.DIRECT);
        runOnMainSync(() -> { malformed.peopleHost.holdCandidates = true; click("searchAction"); field(panel(), "search", EditText.class).setText("changed"); });
        JSONObject invalid = new JSONObject(malformed.peopleHost.candidateBodies.get(1).toString()).put("api_version", 2.0);
        runOnMainSync(() -> malformed.peopleHost.candidateReplies.get(1).complete(200, invalid)); settle();
        runOnMainSync(() -> check(field(panel(), "page", GroupPeopleProtocol.CandidatePage.class) == null
                && field(panel(), "notice", TextView.class).getText().toString().equals(malformed.getString(R.string.bchat_people_load_failed)), "Strict wire parse precedes stale-query explanation"));
    }
    private void pendingDisabled() throws Exception {
        GroupPeopleTestActivity current = picker(GroupPeopleProtocol.Mode.DIRECT);
        runOnMainSync(() -> { choose(100); current.peopleHost.holdRequests = true; click("review"); });
        awaitDraw(field(panel(), "confirmation", AlertDialog.class)); runOnMainSync(this::confirmPositive);
        GroupPeopleProtocol.Intent exact = current.peopleHost.requests.get(0); int reads = current.peopleHost.queries.size();
        runOnMainSync(() -> {
            check(!field(panel(), "search", EditText.class).isEnabled() && !field(panel(), "searchAction", Button.class).isEnabled(), "Mutation busy does not gain editable search");
            field(panel(), "search", EditText.class).onEditorAction(EditorInfo.IME_ACTION_SEARCH); click("searchAction");
            check(current.peopleHost.queries.size() == reads, "Mutation cannot admit a candidate GET");
            current.peopleHost.requestReplies.get(0).complete(503, null);
        }); settle();
        runOnMainSync(() -> {
            check(field(panel(), "unknown", Boolean.class) && field(panel(), "pending", GroupPeopleProtocol.Intent.class) == exact
                    && exact.payload.equals(current.peopleHost.requests.get(0).payload), "Unknown preserves exact immutable operation");
            check(!field(panel(), "search", EditText.class).isEnabled(), "Unknown operation keeps search disabled");
            field(panel(), "search", EditText.class).onEditorAction(EditorInfo.IME_ACTION_SEARCH); click("searchAction");
            check(current.peopleHost.queries.size() == reads && current.peopleHost.requests.size() == 1, "Unknown creates no read or second mutation");
            callActivityOnPause(current); callActivityOnResume(current);
            check(!field(panel(), "search", EditText.class).isEnabled() && field(panel(), "pending", GroupPeopleProtocol.Intent.class) == exact, "Pause/resume does not unlock pending operation");
        });
    }
    private void inspect(View view, View decor, String label) {
        if (view.getVisibility() != View.VISIBLE) return;
        if (view instanceof TextView && ((TextView) view).getText().length() > 0) {
            TextView text = (TextView) view; int[] origin = new int[2], point = new int[2]; decor.getLocationOnScreen(origin); text.getLocationOnScreen(point);
            check(point[0] >= origin[0] - 1 && point[0] + text.getWidth() <= origin[0] + decor.getWidth() + 1, label + " horizontal bounds");
            Layout layout = text.getLayout(); if (layout != null) {
                for (int i = 0; i < layout.getLineCount(); i++) { check(layout.getEllipsisCount(i) == 0, label + " no ellipsis"); check(layout.getLineMax(i) <= layout.getWidth() + 2, label + " no horizontal text clip"); }
                check(layout.getHeight() + text.getCompoundPaddingTop() + text.getCompoundPaddingBottom() <= text.getHeight() + 2, label + " no vertical text clip");
            }
        }
        if (view instanceof Button) {
            check(view.getHeight() >= Ui.dp(activity, 48), label + " action48dp");
            AccessibilityNodeInfo node = view.createAccessibilityNodeInfo();
            check(node.getText() != null && node.getText().length() > 0 && node.isClickable(), label + " accessible native action"); node.recycle();
        }
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) view).getChildCount(); i++) inspect(((ViewGroup) view).getChildAt(i), decor, label);
    }
    private static View tag(View root, String value) {
        if (value.equals(root.getTag())) return root;
        if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) root).getChildCount(); i++) { View found = tag(((ViewGroup) root).getChildAt(i), value); if (found != null) return found; }
        return null;
    }
    private static String textTree(View root) {
        StringBuilder text = new StringBuilder(); if (root instanceof TextView) text.append(((TextView) root).getText());
        if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) root).getChildCount(); i++) text.append(textTree(((ViewGroup) root).getChildAt(i))); return text.toString();
    }
    private void settle() throws Exception { waitFor(() -> !field(panel(), "busy", Boolean.class), "Component response settles", 3000); waitForIdleSync(); }
    private void awaitDraw(AlertDialog dialog) throws Exception {
        CountDownLatch drawn = new CountDownLatch(1);
        runOnMainSync(() -> {
            require(dialog != null && dialog.isShowing(), "Actual visible Dialog before capture");
            View decor = dialog.getWindow().getDecorView();
            decor.getViewTreeObserver().addOnPreDrawListener(new ViewTreeObserver.OnPreDrawListener() {
                @Override public boolean onPreDraw() {
                    if (decor.getWidth() > 0 && decor.getHeight() > 0 && decor.isAttachedToWindow()) {
                        decor.getViewTreeObserver().removeOnPreDrawListener(this); drawn.countDown();
                    }
                    return true;
                }
            });
            decor.requestLayout(); decor.postInvalidateOnAnimation();
        });
        require(drawn.await(3, TimeUnit.SECONDS), "Actual positive geometry and preDraw before capture");
        waitForIdleSync();
    }
    private void waitFor(BooleanSupplier predicate, String label, long timeout) throws Exception {
        long deadline = SystemClock.uptimeMillis() + timeout;
        while (SystemClock.uptimeMillis() < deadline) { boolean[] ready = {false}; runOnMainSync(() -> ready[0] = predicate.getAsBoolean()); if (ready[0]) return; SystemClock.sleep(20); }
        throw new AssertionError("Deadline: " + label);
    }
    private void journey(String label, Journey work) {
        int before = failures.size(); try { work.run(); } catch (Throwable error) { failures.add(label + ": " + error); }
        try { journeys.put(new JSONObject().put("case", label).put("passed", failures.size() == before)); } catch (Exception invalid) { throw new AssertionError(invalid); } close();
    }
    private void close() {
        if (activity == null) return; GroupPeopleTestActivity previous = activity;
        runOnMainSync(() -> { if (previous.picker != null) previous.picker.dismiss(); if (previous.events != null) previous.events.dismiss(); previous.finish(); }); waitForIdleSync(); activity = null;
    }
    private void check(boolean value, String message) { assertions++; if (!value) failures.add(message); }
    private void require(boolean value, String message) { check(value, message); if (!value) throw new AssertionError(message); }
    private void capture(View decor, String name) {
        Bitmap bitmap = Bitmap.createBitmap(decor.getWidth(), decor.getHeight(), Bitmap.Config.ARGB_8888); decor.draw(new Canvas(bitmap));
        try (FileOutputStream output = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) { require(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output), "Actual Dialog-decor capture"); }
        catch (Exception invalid) { throw new AssertionError(invalid); } finally { bitmap.recycle(); }
    }
    private void write(String name, byte[] bytes) throws Exception { try (FileOutputStream output = new FileOutputStream(new File(getTargetContext().getFilesDir(), name))) { output.write(bytes); } }
    static <T> T field(Object target, String name, Class<T> type) {
        try { Field field = target.getClass().getDeclaredField(name); field.setAccessible(true); return type.cast(field.get(target)); }
        catch (Exception invalid) { throw new AssertionError(invalid); }
    }
}

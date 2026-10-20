package com.baseer.bwork.legacy.test;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.*;
import android.content.*;
import android.content.res.Configuration;
import android.graphics.*;
import android.os.*;
import android.provider.Settings;
import android.text.BidiFormatter;
import android.view.*;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.*;
import com.baseer.bwork.legacy.ChatStore;
import com.baseer.bwork.legacy.R;
import java.io.*;
import java.lang.reflect.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;

/** Synthetic state and actual attached Activity windows. No global idle wait or detached layout. */
public final class EntryLayoutInstrumentation extends Instrumentation {
    private static final String APP_PACKAGE = "com.baseer.bchat.preview";
    private static final String PACKAGE = "com.baseer.bwork.legacy", MAIN = PACKAGE + ".MainActivity";
    private static final String DRAFT = "Synthetic draft العربية / English 100%";
    private volatile Activity activity;
    private Application application;
    private Class<?> activityType, settingsType;
    private boolean priorProcessSession;
    private ChatStore store;
    private Object originalProcessStore;
    private UiFixtureGuard fixtureGuard;
    private final Map<String,String> priorReadMarkers = new LinkedHashMap<>();
    private File state, originalState, imageFile;
    private byte[] originalDigest, imageDigest;
    private boolean originalExisted, disposable, screenshots, aborted, selectedStore;
    private int failures, assertions, cases;
    private String company, conversation, reply;
    private String expectedDraft = DRAFT;
    private SharedPreferences preferences, previewPreferences;
    private Map<String, ?> priorPreferences, priorPreview;
    private Configuration priorConfiguration;
    private final List<File> owned = new ArrayList<>();
    private final List<String> results = new ArrayList<>();
    private final Map<String, ChatStore.Conversation> changedConversations = new LinkedHashMap<>();
    private final Application.ActivityLifecycleCallbacks lifecycle = new Application.ActivityLifecycleCallbacks() {
        public void onActivityCreated(Activity a, Bundle b) { }
        public void onActivityStarted(Activity a) { }
        public void onActivityResumed(Activity a) { if (MAIN.equals(a.getClass().getName())) activity = a; }
        public void onActivityPaused(Activity a) { }
        public void onActivityStopped(Activity a) { }
        public void onActivitySaveInstanceState(Activity a, Bundle b) { }
        public void onActivityDestroyed(Activity a) { }
    };
    private static final class Blocked extends RuntimeException { Blocked(String text) { super(text); } }
    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        disposable = args != null && "true".equals(args.getString("disposable"));
        screenshots = args != null && "true".equals(args.getString("screenshots"));
        start();
    }
    @Override public void onStart() {
        boolean completed = false;
        try {
            require(disposable, "Explicit disposable-install permission (-e disposable true)");
            runChecks(); completed = true;
        } catch (Throwable error) { failures++; report((error instanceof Blocked ? "BLOCKED " : "ERROR ") + causes(error)); }
        finally { teardown(); }
        Bundle out = new Bundle();
        boolean passed = completed && failures == 0;
        out.putString("stream", "\n" + (passed ? "PASS" : "FAILED") + " native entry/layout: " + cases + " rendered configurations, "
                + assertions + " checks, " + failures + " failures\n" + String.join("\n", results) + "\n");
        if (!passed) out.putString("failure", failures + " checks failed or blocked");
        finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, out);
    }
    private void report(String text) {
        results.add(text); android.util.Log.i("BWorkEntryLayout", text);
        Bundle status = new Bundle(); status.putString("stream", text + "\n"); sendStatus(0, status);
    }
    private void check(boolean okay, String label) { assertions++; if (!okay) failures++; report((okay ? "PASS " : "FAIL ") + label); }
    private void require(boolean okay, String label) { assertions++; if (!okay) throw new AssertionError(label); report("PASS " + label); }
    private static String causes(Throwable error) {
        StringBuilder s = new StringBuilder();
        for (int i = 0; error != null && i < 8; i++, error = error.getCause()) {
            if (s.length() > 0) s.append(" <- "); s.append(error.getClass().getSimpleName()).append(": ").append(error.getMessage());
        }
        return s.toString();
    }
    private void ui(Runnable work) {
        if (aborted) throw new Blocked("UI action already aborted; no further UI mutation");
        Handler handler = new Handler(Looper.getMainLooper()); CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>(); AtomicInteger gate = new AtomicInteger();
        Runnable task = () -> {
            if (!gate.compareAndSet(0, 1)) { latch.countDown(); return; }
            try { work.run(); } catch (Throwable failure) { error.set(failure); }
            finally { gate.set(2); latch.countDown(); }
        };
        if (!handler.post(task)) { aborted = true; throw new Blocked("Main handler rejected action"); }
        try {
            if (!latch.await(30000, TimeUnit.MILLISECONDS)) {
                aborted = true; boolean cancelled = gate.compareAndSet(0, 3); handler.removeCallbacks(task);
                throw new Blocked("Main-thread deadline, queued action cancelled=" + cancelled + "; no cleanup while action may be running");
            }
        } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); aborted = true; throw new Blocked("Interrupted UI handoff"); }
        if (error.get() != null) throw new AssertionError("UI operation", error.get());
    }
    private boolean onUi(BooleanSupplier condition) { boolean[] result = {false}; ui(() -> result[0] = condition.getAsBoolean()); return result[0]; }
    private boolean waitUntil(BooleanSupplier condition, long millis) {
        long end = SystemClock.elapsedRealtime() + millis;
        while (SystemClock.elapsedRealtime() < end) { if (onUi(condition)) return true; SystemClock.sleep(60); }
        return onUi(condition);
    }
    private static Object field(Object object, String name) {
        try { Field f = object.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(object); }
        catch (ReflectiveOperationException failure) { throw new AssertionError(name, failure); }
    }
    private static void set(Object object, String name, Object value) {
        try { Field f = object.getClass().getDeclaredField(name); f.setAccessible(true); f.set(object, value); }
        catch (ReflectiveOperationException failure) { throw new AssertionError(name, failure); }
    }
    private static Object invoke(Object object, String name, Class<?>[] types, Object... args) {
        try { Method m = object.getClass().getDeclaredMethod(name, types); m.setAccessible(true); return m.invoke(object, args); }
        catch (ReflectiveOperationException failure) { throw new AssertionError(name, failure); }
    }
    private void call(String name) { invoke(activity, name, new Class<?>[0]); }
    private Object staticField(String name) throws Exception { Field f = activityType.getDeclaredField(name); f.setAccessible(true); return f.get(null); }
    private boolean processSession(boolean value, boolean write) {
        try { Field f = settingsType.getDeclaredField("processDemoSession"); f.setAccessible(true); boolean old = f.getBoolean(null); if (write) f.setBoolean(null, value); return old; }
        catch (ReflectiveOperationException error) { throw new AssertionError("processDemoSession", error); }
    }
    private boolean demoActive() { return Boolean.TRUE.equals(invoke(field(activity, "settings"), "demoSessionActive", new Class<?>[0])); }
    private int countClass(View view, String simpleName) {
        int count = simpleName.equals(view.getClass().getSimpleName()) ? 1 : 0;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) count += countClass(((ViewGroup)view).getChildAt(i), simpleName);
        return count;
    }
    private void processStore(Object value) {
        try { Field f = activityType.getDeclaredField("processStore"); f.setAccessible(true); f.set(null, value); }
        catch (ReflectiveOperationException failure) { throw new AssertionError("processStore", failure); }
    }
    private Intent mainIntent() { return new Intent(Intent.ACTION_MAIN).setComponent(new ComponentName(APP_PACKAGE, MAIN)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); }
    private void launch() {
        ActivityMonitor monitor = addMonitor(MAIN, null, false);
        try {
            ui(() -> getTargetContext().startActivity(mainIntent()));
            Activity opened = monitor.waitForActivityWithTimeout(45000);
            if (opened == null) { aborted = true; throw new Blocked("Activity launch deadline"); }
            activity = opened;
        } finally { removeMonitor(monitor); }
        resumed();
    }
    private void resumed() {
        if (!waitUntil(() -> activity != null && Boolean.TRUE.equals(field(activity, "menuHostActive")) && !Boolean.TRUE.equals(field(activity, "initializing")), 45000)) {
            aborted = true; throw new Blocked("Activity resume deadline");
        }
        require(field(activity, "store") == store, "Activity uses only isolated synthetic ChatStore");
        frames();
    }
    private void closeActivity() {
        Activity old = activity; if (old == null) return; ui(old::finish);
        long end = SystemClock.elapsedRealtime() + 8000;
        while (!old.isDestroyed() && SystemClock.elapsedRealtime() < end) SystemClock.sleep(50);
        if (!old.isDestroyed()) { aborted = true; throw new Blocked("Activity close deadline"); }
        activity = null;
    }
    private View root() { return (View)field(activity, "root"); }
    private View tag(String name) { return root().findViewWithTag(name); }
    private String screen() { return (String)field(activity, "screen"); }
    private int dp(float value) { return (int)(activity.getResources().getDisplayMetrics().density * value + .5f); }
    private void clickTag(String name) { ui(() -> { View v = tag(name); require(v != null && v.isEnabled() && v.performClick(), "Native click " + name); }); frames(); }
    private void frames() {
        CountDownLatch done = new CountDownLatch(1); AtomicInteger left = new AtomicInteger(3);
        ui(() -> Choreographer.getInstance().postFrameCallback(new Choreographer.FrameCallback() {
            public void doFrame(long time) { if (left.get() <= 0) return; if (left.decrementAndGet() == 0) done.countDown(); else Choreographer.getInstance().postFrameCallback(this); }
        }));
        try { if (!done.await(8000, TimeUnit.MILLISECONDS)) { left.set(0); throw new Blocked("Frame presentation deadline"); } }
        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new Blocked("Interrupted frame wait"); }
        SystemClock.sleep(160);
    }
    private void runChecks() throws Exception {
        Context context = getTargetContext(); fixtureGuard = new UiFixtureGuard(context); activityType = context.getClassLoader().loadClass(MAIN);
        originalProcessStore = staticField("processStore");
        settingsType = context.getClassLoader().loadClass(PACKAGE + ".LocalSettings");
        priorProcessSession = processSession(false, true);
        originalState = new File(context.getFilesDir(), "chat-state-v1.bin"); originalExisted = originalState.exists();
        originalDigest = originalExisted ? digest(originalState) : null;
        preferences = context.getSharedPreferences(com.baseer.bwork.legacy.compat.LegacyIdentity.SETTINGS, Context.MODE_PRIVATE);
        previewPreferences = context.getSharedPreferences("share-preview", Context.MODE_PRIVATE);
        priorPreferences = new HashMap<>(preferences.getAll()); priorPreview = new HashMap<>(previewPreferences.getAll());
        require(preferences.edit().remove("demo-entry-active").remove("remember-demo-entry").putString("interface-language", "ar").commit(), "Absent entry preference and Arabic selected");
        require(previewPreferences.edit().clear().commit(), "Synthetic preview preferences isolated");
        state = new File(context.getFilesDir(), "entry-layout-" + UUID.randomUUID() + ".bin");
        owned.add(state); owned.add(new File(state + ".bak")); owned.add(new File(state + ".tmp"));
        store = new ChatStore(state); company = store.companies().get(0).id; conversation = store.conversations(company).get(0).id;
        reply = store.lastMessage(company, conversation).id;
        makeDraftFixture(context);
        fixtureGuard.install(store); selectedStore = true;
        application = (Application)context.getApplicationContext(); application.registerActivityLifecycleCallbacks(lifecycle);
        AccessibilityServiceInfo info = getUiAutomation().getServiceInfo(); info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS; getUiAutomation().setServiceInfo(info);
        launch(); priorConfiguration = new Configuration(activity.getResources().getConfiguration());
        require(activity.getPackageManager().getPackageInfo(APP_PACKAGE, 0).versionCode >= 8, "Installed candidate supports entry/layout v8+");
        report("INFO API=" + Build.VERSION.SDK_INT + " version=" + activity.getPackageManager().getPackageInfo(APP_PACKAGE, 0).versionName
                + " time12_24=" + Settings.System.getString(context.getContentResolver(), Settings.System.TIME_12_24));
        entryChecks("ar"); captureEntry("ar"); verifyDraft("initial missing-preference entry with populated synthetic store");
        ui(() -> { CheckBox remember = (CheckBox)tag("bwork-entry-remember"); remember.performClick(); require(remember.isChecked(), "Pending remember choice selected before language switch"); });
        languageDialog("en", true);
        ui(() -> { CheckBox remember = (CheckBox)tag("bwork-entry-remember"); check(remember.isChecked(), "Pending remember choice survives entry language recreation");
            remember.performClick(); require(!remember.isChecked(), "Remember choice explicitly returned to unchecked for process-only flow"); });
        entryChecks("en"); captureEntry("en");
        clickTag("bwork-explore-demo"); check(onUi(() -> "list".equals(screen()) && demoActive()) && !preferences.getBoolean("demo-entry-active", true)
                && !preferences.getBoolean("remember-demo-entry", true), "Unchecked demo entry starts process-only session without persistent entry");
        ui(() -> {
            invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation);
            expectedDraft = DRAFT + " latest";
            ((EditText)field(activity, "composer")).setText(expectedDraft); call("hideKeyboard"); call("showSettings");
        });
        require(waitUntil(() -> "settings".equals(screen()) && !Boolean.TRUE.equals(field(activity, "navigationSaving")), 20000), "Draft durably saves before Settings navigation");
        languageDialog("ar", false); check(onUi(() -> "settings".equals(screen())), "Settings screen survives language recreation");
        verifyDraft("settings language recreation");
        logout(false); check(onUi(() -> "settings".equals(screen()) && demoActive()), "Exit cancellation leaves process demo and Settings intact");
        logout(true); entryChecks("ar"); verifyDraft("confirmed exit"); capture("entry-after-exit");
        closeActivity(); fixtureGuard.drain(); store = new ChatStore(state); fixtureGuard.install(store); launch();
        check(onUi(() -> "entry".equals(screen())) && !preferences.getBoolean("demo-entry-active", true), "Fresh Activity relaunch remains at entry");
        verifyDraft("disk reload at entry"); clickTag("bwork-explore-demo"); verifyDraft("explicit re-entry");
        signedOutShare();
        attachedLayouts();
        report("SCOPE Current device 12/24-hour preference is verified against DateFormat; the suite does not mutate system clock settings. No real authentication, backend, audible output, microphone capture or OS process-death claim.");
    }
    private void makeDraftFixture(Context context) throws Exception {
        File folder = new File(context.getFilesDir(), "attachments"); if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("Cannot make synthetic attachment directory");
        imageFile = new File(folder, UUID.randomUUID() + ".png"); owned.add(imageFile);
        Bitmap image = Bitmap.createBitmap(40, 30, Bitmap.Config.ARGB_8888); image.eraseColor(Color.rgb(40, 120, 200));
        try (FileOutputStream out = new FileOutputStream(imageFile)) { require(image.compress(Bitmap.CompressFormat.PNG, 100, out), "Generated fixture PNG"); } finally { image.recycle(); }
        imageDigest = digest(imageFile);
        ChatStore.Attachment fixture = new ChatStore.Attachment(imageFile.getCanonicalPath(), "synthetic-entry.png", "image/png", imageFile.length());
        store.setDraft(company, conversation, DRAFT, Collections.singletonList(fixture)); store.setReplyTarget(company, conversation, reply);
    }
    private void verifyDraft(String label) throws Exception {
        ChatStore.Draft draft = store.draft(company, conversation);
        check(expectedDraft.equals(draft.text) && reply.equals(draft.replyToMessageId)
                && draft.attachments.size() == 1 && imageFile.getCanonicalPath().equals(draft.attachments.get(0).path)
                && imageFile.exists() && Arrays.equals(imageDigest, digest(imageFile)), "Draft text/reply/attachment SHA-256 retained: " + label);
    }
    private int countEdits(View view) {
        int n = view instanceof EditText ? 1 : 0;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) n += countEdits(((ViewGroup)view).getChildAt(i));
        return n;
    }
    private void entryChecks(String language) {
        ui(() -> {
            check("entry".equals(screen()) && countEdits(root()) == 0, language + " entry has no editable credential controls");
            View user = tag("bwork-username-preview"), password = tag("bwork-password-preview"), mark = tag("bwork-entry-mark");
            check(tag("bwork-real-login-disabled") == null && user instanceof TextView && password instanceof TextView,
                    language + " compact credential shell is read-only with no second sign-in action");
            check(countClass(root(), "EntryMarkView") == 1 && countClass(root(), "BWorkWordmarkView") == 0 && mark != null,
                    language + " entry contains exactly one original-B mark and no Chat wordmark");
            View parent = (View)mark.getParent();
            float centeredX = bounds(parent).left + mark.getLeft() + mark.getWidth() / 2f;
            check(Math.abs(centeredX - bounds(root()).exactCenterX()) <= 1, language + " single B mark is horizontally centered around its motion pivot");
            Bitmap original = (Bitmap)field(mark, "original"); BitmapFactory.Options markOptions = new BitmapFactory.Options(); markOptions.inScaled = false;
            Bitmap expectedMark = BitmapFactory.decodeResource(activity.getResources(), R.drawable.baseer_mark_b, markOptions);
            check(expectedMark != null && original.sameAs(expectedMark), language + " entry reuses exact original B bitmap pixels");
            if (expectedMark != null) expectedMark.recycle();
            CheckBox remember = (CheckBox)tag("bwork-entry-remember");
            check(remember != null && !remember.isChecked() && !preferences.getBoolean("remember-demo-entry", false), language + " remember-me defaults unchecked");
            check(findText(root(), activity.getString(R.string.entry_minimal_notice)) != null, language + " one brief truthful demo notice is present");
            check(!preferences.getBoolean("demo-entry-active", false) && !demoActive(), language + " entry does not grant a session");
            TextView value = (TextView)password; View eye = tag("bwork-password-eye");
            check("••••••••".contentEquals(value.getText()), language + " sample starts hidden");
            eye.performClick(); check(activity.getString(R.string.entry_password_sample).contentEquals(value.getText()), language + " eye reveals only static sample");
            check(activity.getString(R.string.entry_hide_example).contentEquals(eye.getContentDescription()), language + " eye hide accessibility label");
            eye.performClick(); check("••••••••".contentEquals(value.getText()), language + " eye hides sample again");
            check(field(activity, "entryMotion") == null && Math.abs(mark.getRotationY()) < .01f && Math.abs(mark.getRotation()) < .01f, language + " eye interaction stops and resets B animation");
        });
    }
    private void languageDialog(String language, boolean entry) {
        Activity before = activity;
        if (entry) clickTag("bwork-entry-language"); else ui(() -> call("showLanguageSettings"));
        int label = "en".equals(language) ? R.string.language_english : R.string.language_arabic;
        clickDialogChoice("en".equals(language) ? 1 : 0);
        clickDialogButton(android.R.id.button1);
        require(waitUntil(() -> activity != before && language.equals(activity.getResources().getConfiguration().getLocales().get(0).getLanguage())
                && Boolean.TRUE.equals(field(activity, "menuHostActive")) && !Boolean.TRUE.equals(field(activity, "initializing")), 45000), "Language dialog Apply recreates Activity in " + language);
        check(language.equals(preferences.getString("interface-language", "")), "Language preference committed: " + language);
        check(onUi(() -> root().getLayoutDirection() == ("ar".equals(language) ? View.LAYOUT_DIRECTION_RTL : View.LAYOUT_DIRECTION_LTR)), "Root direction matches " + language);
        frames();
    }
    @SuppressWarnings("unchecked") private List<View> processWindowRoots() {
        try {
            if (Build.VERSION.SDK_INT >= 29) return (List<View>)Class.forName("android.view.inspector.WindowInspector")
                    .getMethod("getGlobalWindowViews").invoke(null);
            Class<?> type = Class.forName("android.view.WindowManagerGlobal");
            Object manager = type.getDeclaredMethod("getInstance").invoke(null);
            Field roots = type.getDeclaredField("mViews"); roots.setAccessible(true);
            return new ArrayList<>((List<View>)roots.get(manager));
        } catch (ReflectiveOperationException error) { throw new AssertionError("Native process window inspection", error); }
    }
    private View dialogRoot() {
        for (View view : processWindowRoots()) if (view != activity.getWindow().getDecorView() && view.isAttachedToWindow()
                && view.findViewById(android.R.id.button1) != null) return view;
        return null;
    }
    private ListView dialogList(View view) {
        if (view instanceof ListView) return (ListView)view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            ListView child = dialogList(((ViewGroup)view).getChildAt(i)); if (child != null) return child;
        }
        return null;
    }
    private void clickDialogChoice(int position) {
        require(waitUntil(() -> dialogRoot() != null && dialogList(dialogRoot()) != null, 10000), "Native language dialog list is attached");
        frames();
        ui(() -> {
            ListView list = dialogList(dialogRoot()); View choice = list.getChildAt(position - list.getFirstVisiblePosition());
            require(choice != null && choice.isAttachedToWindow() && list.performItemClick(choice, position, list.getAdapter().getItemId(position)),
                    "Native language dialog choice clicked: " + position);
        }); frames();
    }
    private void clickDialogButton(int id) {
        require(waitUntil(() -> dialogRoot() != null && dialogRoot().findViewById(id).isEnabled(), 10000), "Native dialog button attached");
        ui(() -> { View button = dialogRoot().findViewById(id); require(button.performClick(), "Native dialog button clicked: " + ((TextView)button).getText()); });
        frames();
    }
    private ScrollView entryScroll(View view) {
        if (view instanceof ScrollView) return (ScrollView)view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            ScrollView child = entryScroll(((ViewGroup)view).getChildAt(i)); if (child != null) return child;
        }
        return null;
    }
    private void captureEntry(String language) throws Exception {
        ui(() -> activity.getWindow().setLayout(dp(360), WindowManager.LayoutParams.MATCH_PARENT));
        require(waitUntil(() -> root().getWidth() == dp(360), 10000), "Entry is actually rendered at 360dp: " + language);
        frames(); capture("entry-" + language + "-360dp-top");
        ui(() -> { ScrollView scroll = entryScroll(root()); require(scroll != null, "Actual entry ScrollView present"); scroll.fullScroll(View.FOCUS_DOWN); });
        frames();
        ui(() -> {
            Rect viewport = bounds(entryScroll(root()));
            check(viewport.contains(bounds(tag("bwork-password-preview"))) && viewport.contains(bounds(tag("bwork-entry-remember")))
                    && viewport.contains(bounds(tag("bwork-explore-demo"))),
                    "Scrolled entry shows read-only password, remember choice and demo action: " + language);
        });
        capture("entry-" + language + "-360dp-credentials");
        ui(() -> entryScroll(root()).fullScroll(View.FOCUS_UP)); frames();
    }
    private void logout(boolean confirm) {
        ui(() -> call("confirmLogout"));
        String label = activity.getString(confirm ? R.string.demo_logout : R.string.ui_109);
        clickDialogButton(confirm ? android.R.id.button1 : android.R.id.button2);
        if (confirm) {
            require(waitUntil(() -> "entry".equals(screen()), 10000), "Exit confirmation returns to entry");
            ui(() -> {
                check(field(activity, "voiceRecorder") == null, "Exit leaves no unfinished recorder");
                check(field(activity, "permissionTestCompany") == null && field(activity, "micPermissionCompany") == null, "Exit clears deferred permission targets");
            });
            try {
                Class<?> notifications = activity.getClassLoader().loadClass(PACKAGE + ".DemoNotifications");
                Method pending = notifications.getDeclaredMethod("hasPending"); pending.setAccessible(true);
                check(!((Boolean)pending.invoke(null)), "Exit leaves no scheduled demo notification");
            } catch (ReflectiveOperationException error) { throw new AssertionError("Notification cancellation state", error); }
        }
    }
    private void signedOutShare() throws Exception {
        logout(true);
        final String shared = "Synthetic external share العربية / English";
        Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, shared)
                .setComponent(new ComponentName(APP_PACKAGE, MAIN)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        ui(() -> getTargetContext().startActivity(share));
        require(waitUntil(() -> field(activity, "deferredEntryIntent") instanceof Intent, 10000), "Signed-out ACTION_SEND saved as deferred intent");
        check(store.pendingShare() == null && onUi(() -> "entry".equals(screen())), "Share has not entered demo or staged content before Explore");
        ui(() -> activity.startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
        SystemClock.sleep(300); ui(() -> getTargetContext().startActivity(mainIntent())); resumed();
        check(onUi(() -> shared.equals(((Intent)field(activity, "deferredEntryIntent")).getStringExtra(Intent.EXTRA_TEXT))), "Home then ACTION_MAIN preserves deferred share");
        languageDialog("en", true);
        check(onUi(() -> "entry".equals(screen()) && shared.equals(((Intent)field(activity, "deferredEntryIntent")).getStringExtra(Intent.EXTRA_TEXT))), "Entry language recreation saves and restores deferred share Bundle");
        clickTag("bwork-explore-demo");
        require(waitUntil(() -> "picker".equals(screen()) && store.pendingShare() != null, 10000), "Explore resumes signed-out share at recipient picker");
        check(shared.equals(store.pendingShare().text), "Deferred share content is unchanged");
        chooseRecipient();
        final String edited = shared + " edited preview";
        ui(() -> ((EditText)field(activity, "previewCaption")).setText(edited));
        require(waitUntil(() -> {
            ChatStore.PendingShare saved = store.pendingShare();
            return "preview".equals(screen()) && saved != null && saved.previewEdited && edited.equals(saved.text);
        }, 20000), "Edited share durably saves while preview stays open");
        fixtureGuard.drain();
        ChatStore.PendingShare savedBeforeLanguage = new ChatStore(state).pendingShare();
        check(savedBeforeLanguage != null && savedBeforeLanguage.previewEdited && edited.equals(savedBeforeLanguage.text),
                "Edited share caption survives isolated disk reload before language recreation");
        languageDialog("ar", false);
        check(onUi(() -> "preview".equals(screen()) && edited.contentEquals(((EditText)field(activity, "previewCaption")).getText())), "Edited share preview survives locale recreation");
        capture("share-preview-recreated");
        String pendingId = store.pendingShare().id; logout(true); verifyDraft("exit from pending share preview");
        ChatStore.PendingShare savedAfterExit = store.pendingShare();
        check(savedAfterExit != null && pendingId.equals(savedAfterExit.id) && savedAfterExit.previewEdited && edited.equals(savedAfterExit.text),
                "Exit preserves durable pending share identity and edited preview");
        clickTag("bwork-explore-demo"); require(onUi(() -> "picker".equals(screen())), "Re-entry returns to pending-share picker");
        chooseRecipient(); check(onUi(() -> edited.contentEquals(((EditText)field(activity, "previewCaption")).getText())), "Choosing recipient restores saved edited preview");
        // Cancel only this invocation's synthetic pending share before layout checks.
        ui(() -> { try { store.cancelPendingShare(pendingId); call("clearPreview"); call("showList"); }
            catch (IOException error) { throw new AssertionError(error); } });
    }
    private void chooseRecipient() {
        final int[] position = {-1};
        ui(() -> {
            ListView list = (ListView)field(activity, "recipientList");
            for (int i = 0; i < list.getAdapter().getCount(); i++) if (list.getAdapter().getItem(i) instanceof ChatStore.Recipient) { position[0] = i; break; }
            require(position[0] >= 0, "Synthetic recipient present"); list.setSelection(position[0]);
        }); frames();
        ui(() -> {
            ListView list = (ListView)field(activity, "recipientList"); View row = list.getChildAt(position[0] - list.getFirstVisiblePosition());
            require(row != null && row.isAttachedToWindow() && list.performItemClick(row, position[0], list.getAdapter().getItemId(position[0])), "Actual attached recipient row selected");
        }); frames(); require(onUi(() -> "preview".equals(screen())), "Recipient opens actual share preview");
    }
    @SuppressWarnings("unchecked") private Map<String, ChatStore.Conversation> conversationMap() {
        return (Map<String, ChatStore.Conversation>)field(field(store, "state"), "conversations");
    }
    private void installGeometryFixtures(String language) throws Exception {
        fixtureGuard.drain();
        Map<String, ChatStore.Conversation> all = conversationMap();
        if (changedConversations.isEmpty()) {
            changedConversations.putAll(all);
            priorReadMarkers.putAll((Map<String,String>)field(field(store,"state"),"readMarkers"));
        }
        Constructor<ChatStore.Conversation> ctor = ChatStore.Conversation.class.getDeclaredConstructor(String.class, String.class,
                String.class, String.class, String.class, int.class, int.class); ctor.setAccessible(true);
        int index = 0;
        for (ChatStore.Conversation original : changedConversations.values()) {
            String title = "ar".equals(language) ? (index % 2 == 0 ? "Alex" : "Alexandra Example Long Company Team Name 123")
                    : (index % 2 == 0 ? "علي" : "مجموعة المحادثة التجريبية ذات الاسم الطويل جدًا لاختبار التخطيط");
            all.put(original.id, ctor.newInstance(original.id, original.companyId, title, original.subtitle, original.kind, 123, original.avatarHue));
            index++;
        }
        // These constructor-built synthetic values are only used in memory by the actual adapter.
        // No modified seed metadata is saved; original objects are restored before disk writes/teardown.
        ui(() -> ((Map<?,?>)field(field(store,"state"),"readMarkers")).clear());
    }
    @SuppressWarnings("unchecked") private void restoreGeometryFixtures() { if (store != null && !changedConversations.isEmpty()) { conversationMap().putAll(changedConversations); changedConversations.clear(); Map<String,String> markers=(Map<String,String>)field(field(store,"state"),"readMarkers");markers.clear();markers.putAll(priorReadMarkers);priorReadMarkers.clear(); } }
    private void attachedLayouts() throws Exception {
        ui(() -> call("showList"));
        WindowManager.LayoutParams priorWindow = new WindowManager.LayoutParams();
        ui(() -> priorWindow.copyFrom(activity.getWindow().getAttributes()));
        try {
            for (String language : new String[]{"ar", "en"}) {
                require(preferences.edit().putString("interface-language", language).commit(), "Geometry locale selected: " + language);
                installGeometryFixtures(language);
                for (int width : new int[]{360, 320}) for (float font : new float[]{1f, 2f}) {
                    final String label = language + "-" + width + "dp-font" + (int)(100 * font);
                    ui(() -> {
                        Configuration configuration = new Configuration(priorConfiguration);
                        Locale locale = Locale.forLanguageTag(language); configuration.setLocale(locale); configuration.setLayoutDirection(locale); configuration.fontScale = font;
                        activity.getResources().updateConfiguration(configuration, activity.getResources().getDisplayMetrics());
                        set(activity, "listQuery", ""); set(activity, "inboxSearchExpanded", false);
                        activity.getWindow().setLayout(dp(width), WindowManager.LayoutParams.MATCH_PARENT); call("showList");
                    });
                    require(waitUntil(() -> root().isAttachedToWindow() && root().getWidth() == dp(width) && root().getHeight() > dp(250), 10000),
                            "Actual attached Activity window rendered at " + label);
                    frames();
                    final Rect[] brand = {null};
                    ui(() -> {
                        check(Math.abs(activity.getResources().getConfiguration().fontScale - font) < .01f, label + " applied font scale");
                        brand[0] = bounds(tag("bwork-wordmark"));
                        navigationGeometry("list", label); rowGeometry(label, language); companyOrder(label);
                    });
                    capture(label + "-chats");
                    renderedCompanyHeaders(label);
                    ui(() -> { ((ListView)field(activity, "inbox")).setSelection(0); call("toggleInboxSearch"); call("hideKeyboard"); }); frames();
                    ui(() -> {
                        check(brand[0].equals(bounds(tag("bwork-wordmark"))), label + " search preserves exact logo coordinates");
                        check(((View)field(activity, "inboxSearchBar")).getVisibility() == View.VISIBLE, label + " search rendered"); navigationGeometry("list", label + "-search");
                    }); capture(label + "-search");
                    for (String section : new String[]{"orders", "tasks", "list"}) {
                        clickTag("bwork-section-" + section);
                        ui(() -> {
                            check(section.equals(screen()) && brand[0].equals(bounds(tag("bwork-wordmark"))), label + " " + section + " preserves exact logo coordinates");
                            navigationGeometry(section, label + "-" + section);
                        });
                        if (!"list".equals(section)) capture(label + "-" + section);
                    }
                    cases++;
                }
            }
        } finally {
            if (!aborted) ui(() -> {
                restoreGeometryFixtures();
                activity.getResources().updateConfiguration(priorConfiguration, activity.getResources().getDisplayMetrics());
                activity.getWindow().setAttributes(priorWindow); call("showList");
            });
        }
    }
    private Rect bounds(View view) {
        if (view == null) throw new AssertionError("Missing view for geometry");
        int[] xy = new int[2]; view.getLocationOnScreen(xy); return new Rect(xy[0], xy[1], xy[0] + view.getWidth(), xy[1] + view.getHeight());
    }
    private void textFits(TextView view, String label, boolean allowEllipsis) {
        android.text.Layout layout = view.getLayout();
        check(layout != null && view.getWidth() > 0 && view.getHeight() > 0, label + " has nonzero native text bounds");
        if (layout == null) return;
        int width = view.getWidth() - view.getCompoundPaddingLeft() - view.getCompoundPaddingRight();
        int height = view.getHeight() - view.getCompoundPaddingTop() - view.getCompoundPaddingBottom();
        boolean fit = layout.getHeight() <= height + 1;
        for (int i = 0; i < layout.getLineCount(); i++) {
            // Single-line TextView can use a 1,048,576px Layout and scroll its viewport.
            // Its onDraw canvas is translated by -scrollX; compare actual visible glyph coordinates.
            fit &= layout.getLineLeft(i) - view.getScrollX() >= -1
                    && layout.getLineRight(i) - view.getScrollX() <= width + 1;
            if (!allowEllipsis) fit &= layout.getEllipsisCount(i) == 0;
        }
        check(fit, label + " glyph bounds fit (view=" + view.getWidth() + "x" + view.getHeight() + ", layout=" + layout.getWidth() + "x" + layout.getHeight()
                + ", scrollX=" + view.getScrollX() + ", visibleGlyphs=" + (layout.getLineLeft(0) - view.getScrollX()) + ".." + (layout.getLineRight(0) - view.getScrollX()) + ")");
    }
    private void navigationGeometry(String section, String label) {
        View brand = tag("bwork-wordmark"), toolbar = tag("bwork-main-toolbar");
        LinearLayout tabs = (LinearLayout)tag("bwork-bottom-navigation");
        require(brand != null && toolbar != null && tabs != null, label + " real toolbar and bottom navigation exist");
        Rect rootBounds = bounds(root()), logo = bounds(brand), top = bounds(toolbar), footer = bounds(tabs);
        check(rootBounds.contains(logo) && top.contains(logo) && brand.getLayoutDirection() == View.LAYOUT_DIRECTION_LTR,
                label + " logo stays inside toolbar without mirroring");
        boolean rtl = root().getLayoutDirection() == View.LAYOUT_DIRECTION_RTL;
        check(Math.abs((rtl ? top.right - toolbar.getPaddingRight() - logo.right : logo.left - top.left - toolbar.getPaddingLeft())) <= 1,
                label + " logo is at logical start");
        check(footer.bottom == rootBounds.bottom - root().getPaddingBottom() && rootBounds.contains(footer), label + " navigation remains fully on-screen at bottom");
        check(tabs.getChildCount() == 3, label + " three native bottom labels");
        String[] ids = {"list", "orders", "tasks"};
        for (int i = 0; i < 3; i++) {
            TextView tab = (TextView)tabs.getChildAt(i); textFits(tab, label + " " + ids[i], false);
            check(tab.isSelected() == ids[i].equals(section) && footer.contains(bounds(tab)), label + " " + ids[i] + " selected state and bounds");
        }
        check((tabs.getChildAt(0).getLeft() > tabs.getChildAt(2).getLeft()) == rtl, label + " bottom destination order matches interface direction");
        report("GEOMETRY " + label + " root=" + rootBounds.toShortString() + " logo=" + logo.toShortString() + " footer=" + footer.toShortString());
    }
    private void rowGeometry(String label, String language) {
        ListView list = (ListView)field(activity, "inbox"); int seen = 0;
        Rect listBounds = bounds(list);
        for (int i = 0; i < list.getChildCount(); i++) {
            View row = list.getChildAt(i); int position = list.getFirstVisiblePosition() + i;
            Object model = list.getAdapter().getItem(position); if (!(model instanceof ChatStore.Conversation)) continue;
            Rect rowBounds = bounds(row); if (rowBounds.top < listBounds.top || rowBounds.bottom > listBounds.bottom) continue;
            ChatStore.Conversation conversation = (ChatStore.Conversation)model;
            TextView name = (TextView)row.findViewWithTag("bwork-conversation-name");
            TextView time = (TextView)row.findViewWithTag("bwork-conversation-time");
            TextView badge = (TextView)row.findViewWithTag("bwork-unread-badge");
            View metadata = row.findViewWithTag("bwork-conversation-metadata");
            View avatar = ((ViewGroup)((ViewGroup)row).getChildAt(0)).getChildAt(0);
            require(name != null && time != null && badge != null, label + " actual list row contains name/time/unread");
            Rect n = bounds(name), a = bounds(avatar), m = bounds(metadata), t = bounds(time), b = bounds(badge);
            check(rowBounds.contains(n) && rowBounds.contains(a) && rowBounds.contains(m) && !Rect.intersects(n, m) && !Rect.intersects(n, a),
                    label + " name, avatar and metadata have separate in-row bounds");
            check(!Rect.intersects(t, b) && m.contains(t) && m.contains(b), label + " time and unread occupy distinct metadata bounds");
            check(conversation.title.contentEquals(name.getText()) && "99+".contentEquals(badge.getText()), label + " opposite-script name unchanged and unread capped 99+");
            boolean rtl = "ar".equals(language);
            check(rtl ? n.right <= a.left && m.right <= n.left : a.right <= n.left && n.right <= m.left, label + " text remains beside avatar in interface order");
            check(name.getTextAlignment() == View.TEXT_ALIGNMENT_VIEW_START && name.getWidth() > dp(16), label + " name has readable logical-start area");
            textFits(time, label + " time", false); textFits(badge, label + " unread 99+", false);
            // Text layout's glyph edge, rather than just its TextView box, must align toward the avatar.
            android.text.Layout text = name.getLayout();
            if (text != null && text.getEllipsisCount(0) == 0) {
                float rawEdge = rtl ? text.getLineRight(0) : text.getLineLeft(0);
                float edge = rawEdge - name.getScrollX();
                float expected = rtl ? name.getWidth() - name.getCompoundPaddingLeft() - name.getCompoundPaddingRight() : 0;
                check(Math.abs(edge - expected) <= 2, label + " opposite-script glyph edge stays next to avatar"
                        + " (raw=" + rawEdge + ", scrollX=" + name.getScrollX() + ", visible=" + edge + ", expected=" + expected + ")");
            }
            ChatStore.Message last = store.lastMessage(conversation.companyId, conversation.id);
            String expected = BidiFormatter.getInstance(rtl).unicodeWrap(android.text.format.DateFormat.getTimeFormat(activity).format(new Date(last.createdAt)));
            check(expected.contentEquals(time.getText()), label + " rendered timestamp obeys device DateFormat preference");
            report("GEOMETRY " + label + " row=" + conversation.id + " name=" + n.toShortString() + " avatar=" + a.toShortString()
                    + " time=" + t.toShortString() + " unread=" + b.toShortString());
            seen++;
        }
        check(seen >= 2, label + " at least two complete actual list rows inspected: " + seen);
    }
    private void companyOrder(String label) {
        ListAdapter adapter = ((ListView)field(activity, "inbox")).getAdapter(); String company = null; int headers = 0; boolean ordered = true;
        for (int i = 0; i < adapter.getCount(); i++) {
            Object item = adapter.getItem(i);
            if (item instanceof ChatStore.Company) { company = ((ChatStore.Company)item).id; headers++; }
            else if (item instanceof ChatStore.Conversation) ordered &= ((ChatStore.Conversation)item).companyId.equals(company);
        }
        check(ordered && headers == store.companies().size(), label + " every company header precedes only its own chats in actual adapter");
    }
    private void renderedCompanyHeaders(String label) {
        final List<Integer> indices = new ArrayList<>();
        ui(() -> { ListAdapter adapter = ((ListView)field(activity, "inbox")).getAdapter();
            for (int i = 0; i < adapter.getCount(); i++) if (adapter.getItem(i) instanceof ChatStore.Company) indices.add(i); });
        for (int position : indices) {
            ui(() -> ((ListView)field(activity, "inbox")).setSelection(position)); frames();
            ui(() -> {
                ListView list = (ListView)field(activity, "inbox"); int childIndex = position - list.getFirstVisiblePosition();
                View header = list.getChildAt(childIndex), chat = list.getChildAt(childIndex + 1);
                require(header != null && chat != null && header.isAttachedToWindow() && chat.isAttachedToWindow(), label + " company header and own chat actually rendered");
                ChatStore.Company company = (ChatStore.Company)list.getAdapter().getItem(position);
                ChatStore.Conversation conversation = (ChatStore.Conversation)list.getAdapter().getItem(position + 1);
                check(company.id.equals(conversation.companyId) && bounds(header).bottom <= bounds(chat).top
                        && findText(header, company.name) != null, label + " on-screen company header above its own chat: " + company.id);
            });
        }
        ui(() -> ((ListView)field(activity, "inbox")).setSelection(0)); frames();
    }
    private TextView findText(View view, String text) {
        if (view instanceof TextView && text.contentEquals(((TextView)view).getText())) return (TextView)view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            TextView found = findText(((ViewGroup)view).getChildAt(i), text); if (found != null) return found;
        }
        return null;
    }
    private void capture(String label) throws Exception {
        if (!screenshots) return; frames(); SystemClock.sleep(400);
        Bitmap image = getUiAutomation().takeScreenshot(); require(image != null, "Actual display screenshot captured: " + label);
        try {
            File directory = activity.getExternalFilesDir("entry-layout-screenshots");
            require(directory != null && (directory.isDirectory() || directory.mkdirs()), "External synthetic screenshot directory available");
            File file = new File(directory, label + "-api" + Build.VERSION.SDK_INT + "-v8.png");
            try (FileOutputStream output = new FileOutputStream(file)) { require(image.compress(Bitmap.CompressFormat.PNG, 100, output), "Actual screenshot encoded: " + label); }
            report("SCREENSHOT " + file.getAbsolutePath());
        } finally { image.recycle(); }
    }
    private static byte[] digest(File file) throws Exception {
        MessageDigest sha = MessageDigest.getInstance("SHA-256"); byte[] buffer = new byte[8192];
        try (InputStream input = new FileInputStream(file)) { for (int n; (n = input.read(buffer)) >= 0;) sha.update(buffer, 0, n); }
        return sha.digest();
    }
    @SuppressWarnings("unchecked") private void restorePreferences(SharedPreferences target, Map<String, ?> previous) {
        if (target == null || previous == null) return;
        SharedPreferences.Editor edit = target.edit().clear();
        for (Map.Entry<String, ?> entry : previous.entrySet()) {
            String key = entry.getKey(); Object value = entry.getValue();
            if (value instanceof String) edit.putString(key, (String)value);
            else if (value instanceof Boolean) edit.putBoolean(key, (Boolean)value);
            else if (value instanceof Integer) edit.putInt(key, (Integer)value);
            else if (value instanceof Long) edit.putLong(key, (Long)value);
            else if (value instanceof Float) edit.putFloat(key, (Float)value);
            else if (value instanceof Set) edit.putStringSet(key, new HashSet<>((Set<String>)value));
            else throw new AssertionError("Unsupported preference type " + key);
        }
        check(edit.commit() && target.getAll().equals(previous), "Prior preference snapshot restored exactly");
    }
    private void teardown() {
        if (aborted) { report("BLOCKED No teardown after in-flight UI timeout; disposable guest may retain only synthetic fixtures"); return; }
        try {
            if (selectedStore) ui(this::restoreGeometryFixtures);
            if (activity != null) {
                if (priorConfiguration != null) ui(() -> activity.getResources().updateConfiguration(priorConfiguration, activity.getResources().getDisplayMetrics()));
                closeActivity();
            }
            if (application != null) application.unregisterActivityLifecycleCallbacks(lifecycle);
            if (fixtureGuard != null) fixtureGuard.drain();
            if (selectedStore) processStore(originalProcessStore);
            if (settingsType != null) processSession(priorProcessSession, true);
            restorePreferences(preferences, priorPreferences); restorePreferences(previewPreferences, priorPreview);
            if (originalState != null) check(originalExisted ? originalState.isFile() && Arrays.equals(originalDigest, digest(originalState)) : !originalState.exists(),
                    "Normal chat-state snapshot existence and SHA-256 unchanged");
            for (File file : owned) if (file.exists()) check(file.delete(), "Removed only invocation-owned fixture " + file.getName());
            if (fixtureGuard != null) { fixtureGuard.restore(true); fixtureGuard.verifyOriginals(); check(true,"All preexisting private-file SHA-256 and preference maps preserved"); }
        } catch (Throwable error) { failures++; report("ERROR teardown " + causes(error)); }
    }
}

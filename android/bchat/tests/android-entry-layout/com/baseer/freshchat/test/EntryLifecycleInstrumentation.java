package com.baseer.freshchat.test;

import android.animation.*;
import android.app.*;
import android.content.*;
import android.graphics.Bitmap;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.baseer.freshchat.ChatStore;
import java.io.*;
import java.lang.reflect.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;

/** Actual entry motion and explicitly staged cross-process remembering; disposable synthetic state only. */
public final class EntryLifecycleInstrumentation extends Instrumentation {
    private static final String APP_PACKAGE = "com.baseer.bchat.preview";
    private static final String PKG = "com.baseer.freshchat", MAIN = PKG + ".MainActivity";
    private UiFixtureGuard fixtureGuard;
    private Activity activity; private Class<?> activityType, settingsType; private ChatStore store;
    private Object originalStore; private boolean originalProcessSession, aborted, screenshots, disposable, finishedSequence;
    private SharedPreferences preferences, previewPreferences; private Checkpoint checkpoint; private File checkpointFile;
    private boolean priorTouchMode, touchModeCaptured;
    private String stage, motion; private final List<String> results = new ArrayList<>();
    private static final class Checkpoint implements Serializable {
        private static final long serialVersionUID = 1L;
        String marker = "BChat disposable entry lifecycle v2", stateName, company, conversation, draft;
        HashMap<String, Object> preferences, preview, recovery;
        HashMap<String,String> originalFiles;
        boolean normalExisted, originalProcess; byte[] normalHash; int nextStage, priorPid;
    }
    @Override public void onCreate(Bundle args) {
        super.onCreate(args); disposable = args != null && "true".equals(args.getString("disposable"));
        screenshots = args != null && "true".equals(args.getString("screenshots"));
        stage = args == null ? "motion" : args.getString("stage", "motion"); motion = args == null ? "enabled" : args.getString("motion", "enabled"); start();
    }
    @Override public void onStart() {
        boolean passed = false;
        try {
            need(disposable, "Explicit disposable installation required"); initialize();
            if ("motion".equals(stage)) runMotion(); else runProcessStage(); passed = true;
        } catch (Throwable failure) { report("ERROR " + android.util.Log.getStackTraceString(failure)); }
        finally {
            if (!aborted) try {
                closeActivity(); if (touchModeCaptured) setInTouchMode(priorTouchMode);
                if (fixtureGuard != null) fixtureGuard.restore(false);
                if ("motion".equals(stage) || finishedSequence) restoreCheckpoint();
                else if (checkpoint != null) report("PENDING Cross-process sequence intentionally retains only synthetic snapshot and entry preferences; run the next documented stage or stage=restore.");
            } catch (Throwable cleanup) { passed = false; report("ERROR cleanup " + cleanup); }
            else report("BLOCKED No cleanup races an in-flight UI action; use disposable guest recovery.");
        }
        Bundle out = new Bundle(); out.putString("stream", "\n" + (passed ? "PASS" : "FAILED") + " entry lifecycle stage=" + stage + "\n" + String.join("\n", results) + "\n");
        if (!passed) out.putString("failure", "Entry lifecycle stage failed or blocked"); finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, out);
    }
    private void report(String text) { results.add(text); android.util.Log.i("BChatEntryLifecycle", text); Bundle b = new Bundle(); b.putString("stream", text + "\n"); sendStatus(0, b); }
    private void need(boolean okay, String label) { if (!okay) throw new AssertionError(label); report("PASS " + label); }
    private static Object field(Object o, String name) {
        try { Field f = o.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(o); } catch (ReflectiveOperationException e) { throw new AssertionError(name, e); }
    }
    private static Object staticField(Class<?> type, String name) {
        try { Field f = type.getDeclaredField(name); f.setAccessible(true); return f.get(null); } catch (ReflectiveOperationException e) { throw new AssertionError(name, e); }
    }
    private static void setStatic(Class<?> type, String name, Object value) {
        try { Field f = type.getDeclaredField(name); f.setAccessible(true); f.set(null, value); } catch (ReflectiveOperationException e) { throw new AssertionError(name, e); }
    }
    private static Object invoke(Object o, String name, Class<?>[] types, Object... values) {
        try { Method m = o.getClass().getDeclaredMethod(name, types); m.setAccessible(true); return m.invoke(o, values); } catch (ReflectiveOperationException e) { throw new AssertionError(name, e); }
    }
    private void ui(Runnable action) {
        if (aborted) throw new AssertionError("Already aborted");
        Handler handler = new Handler(Looper.getMainLooper()); CountDownLatch done = new CountDownLatch(1); AtomicInteger gate = new AtomicInteger(); AtomicReference<Throwable> failed = new AtomicReference<>();
        Runnable task = () -> { if (!gate.compareAndSet(0, 1)) { done.countDown(); return; } try { action.run(); } catch (Throwable t) { failed.set(t); } finally { gate.set(2); done.countDown(); } };
        if (!handler.post(task)) { aborted = true; throw new AssertionError("Main handler rejected action"); }
        try { if (!done.await(30000, TimeUnit.MILLISECONDS)) { aborted = true; gate.compareAndSet(0, 3); handler.removeCallbacks(task); throw new AssertionError("BLOCKED main-thread deadline"); } }
        catch (InterruptedException e) { aborted = true; Thread.currentThread().interrupt(); throw new AssertionError(e); }
        if (failed.get() != null) throw new AssertionError("UI action", failed.get());
    }
    private boolean waitUntil(BooleanSupplier condition, long timeout) {
        long end = SystemClock.elapsedRealtime() + timeout; boolean[] okay = {false};
        do { ui(() -> okay[0] = condition.getAsBoolean()); if (okay[0]) return true; SystemClock.sleep(35); } while (SystemClock.elapsedRealtime() < end); return false;
    }
    private Intent mainIntent() { return new Intent(Intent.ACTION_MAIN).setComponent(new ComponentName(APP_PACKAGE, MAIN)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); }
    private View tag(String tag) { return activity.getWindow().getDecorView().findViewWithTag(tag); }
    private String screen() { return (String)field(activity, "screen"); }
    private boolean processActive() { return Boolean.TRUE.equals(staticField(settingsType, "processDemoSession")); }
    private void launch() {
        ActivityMonitor monitor = addMonitor(MAIN, null, false);
        try { ui(() -> getTargetContext().startActivity(mainIntent())); activity = monitor.waitForActivityWithTimeout(45000); }
        finally { removeMonitor(monitor); }
        need(activity != null && waitUntil(() -> Boolean.TRUE.equals(field(activity, "menuHostActive")) && !Boolean.TRUE.equals(field(activity,"initializing")), 45000), "Actual target launch/resume");
        need(field(activity, "store") == store, "Only synthetic store is active");
    }
    private void recreate() {
        Activity old = activity; ActivityMonitor monitor = addMonitor(MAIN, null, false);
        try { ui(old::recreate); activity = monitor.waitForActivityWithTimeout(45000); } finally { removeMonitor(monitor); }
        need(activity != null && activity != old && waitUntil(() -> Boolean.TRUE.equals(field(activity, "menuHostActive")) && !Boolean.TRUE.equals(field(activity,"initializing")), 45000), "Actual unrelated Activity recreation completed");
    }
    private void closeActivity() {
        if (activity == null) return; Activity old = activity; ui(old::finish); long end = SystemClock.elapsedRealtime() + 8000;
        while (!old.isDestroyed() && SystemClock.elapsedRealtime() < end) SystemClock.sleep(40);
        if (!old.isDestroyed()) { aborted = true; throw new AssertionError("Activity close deadline"); } activity = null;
    }
    private void initialize() throws Exception {
        Context context = getTargetContext(); fixtureGuard = new UiFixtureGuard(context); activityType = context.getClassLoader().loadClass(MAIN); settingsType = context.getClassLoader().loadClass(PKG + ".LocalSettings");
        originalStore = staticField(activityType, "processStore"); originalProcessSession = processActive();
        preferences = context.getSharedPreferences("bchat-local-settings-v1", Context.MODE_PRIVATE); previewPreferences = context.getSharedPreferences("share-preview", Context.MODE_PRIVATE);
        checkpointFile = new File(context.getFilesDir(), "synthetic-entry-session-checkpoint.bin");
        report("INFO PID=" + android.os.Process.myPid() + " animatorEnabled=" + ValueAnimator.areAnimatorsEnabled() + " stage=" + stage);
    }
    @SuppressWarnings("unchecked") private Checkpoint freshCheckpoint() throws Exception {
        need(!checkpointFile.exists(), "No unfinished staged sequence is overwritten");
        Context context = getTargetContext(); File normal = new File(context.getFilesDir(), "chat-state-v1.bin");
        Checkpoint c = new Checkpoint(); c.preferences = new HashMap<>((Map<String, Object>)preferences.getAll()); c.preview = new HashMap<>((Map<String, Object>)previewPreferences.getAll());
        c.originalFiles = UiFixtureGuard.hashFiles(context.getFilesDir());
        c.recovery = UiFixtureGuard.copyPrefs(context.getSharedPreferences("bchat-editor-recovery-v1",0));
        c.normalExisted = normal.exists(); c.normalHash = c.normalExisted ? digest(normal) : null; c.originalProcess = originalProcessSession;
        c.stateName = "entry-session-" + UUID.randomUUID() + ".bin"; store = new ChatStore(new File(context.getFilesDir(), c.stateName));
        c.company = store.companies().get(0).id; c.conversation = store.conversations(c.company).get(0).id; c.draft = "Synthetic process draft " + UUID.randomUUID();
        store.setDraft(c.company, c.conversation, c.draft, Collections.emptyList()); return c;
    }
    private void prepareEntry() {
        need(preferences.edit().remove("demo-entry-active").remove("remember-demo-entry").putString("interface-language", "ar").commit(), "Entry/remember defaults reset only for synthetic test");
        setStatic(settingsType, "processDemoSession", false); try { fixtureGuard.install(store); } catch (Exception failure) { throw new AssertionError(failure); }
    }
    private void runMotion() throws Exception {
        need("enabled".equals(motion) || "disabled".equals(motion), "Motion expectation is explicit");
        checkpoint = freshCheckpoint(); prepareEntry(); launch();
        priorTouchMode = activity.getWindow().getDecorView().isInTouchMode(); touchModeCaptured = true;
        boolean enabled = "enabled".equals(motion); need(ValueAnimator.areAnimatorsEnabled() == enabled, "Device animator setting matches requested " + motion + " test");
        if (enabled) {
            ObjectAnimator first = awaitMotion();
            ui(() -> { Set<String> properties = new HashSet<>(); for (PropertyValuesHolder value : first.getValues()) properties.add(value.getPropertyName());
                need(first.getDuration() == 950 && first.getRepeatCount() == 0 && properties.equals(new HashSet<>(Arrays.asList("rotationY", "rotation"))), "One brief 950ms two-axis intro, no repetition");
                need(Math.abs(tag("bchat-entry-mark").getRotationY()) <= 14.01f && Math.abs(tag("bchat-entry-mark").getRotation()) <= 3.01f,
                        "Native tilt/roll remain within fourteen/three-degree bounds");
                need(tag("bchat-entry-language").requestFocusFromTouch(), "Framework focus moves to real language control"); });
            need(waitUntil(() -> field(activity, "entryMotion") == null && Math.abs(tag("bchat-entry-mark").getRotationY()) < .01f && Math.abs(tag("bchat-entry-mark").getRotation()) < .01f, 2000), "Actual focus change cancels and resets intro");
            need(!first.isRunning(), "Original animator is stopped on focus change");
            recreate(); noMotion("Unrelated recreation does not replay intro"); capture("entry-motion-focus-recreate");
            // requestFocusFromTouch intentionally leaves touch mode for the real focus test.
            // Restore the original input mode before testing a separate fresh launch.
            setInTouchMode(priorTouchMode); closeActivity(); launch(); ObjectAnimator windowMotion = awaitMotion();
            final AlertDialog[] focusDialog = {null};
            ui(() -> focusDialog[0] = new AlertDialog.Builder(activity).setMessage("Synthetic window-focus interruption").setPositiveButton("Close", null).show());
            need(waitUntil(() -> !activity.hasWindowFocus() && !Boolean.TRUE.equals(field(activity, "entryWindowFocused")), 10000), "Real attached dialog removes Activity window focus");
            ui(() -> need(Boolean.TRUE.equals(field(activity, "menuHostActive")) && field(activity, "entryMotion") == null && !windowMotion.isRunning(),
                    "Window focus loss stops active intro without requiring Activity pause"));
            ui(() -> need(focusDialog[0].getButton(AlertDialog.BUTTON_POSITIVE).performClick(), "Actual synthetic focus dialog dismissed"));
            need(waitUntil(() -> activity.hasWindowFocus() && Boolean.TRUE.equals(field(activity, "entryWindowFocused")), 10000), "Activity window focus returns");
            noMotion("Window focus return does not replay intro"); capture("entry-motion-after-window-focus");
            closeActivity(); launch(); ObjectAnimator touchMotion = awaitMotion();
            final int[] point = new int[2];
            ui(() -> { View mark = tag("bchat-entry-mark"); mark.getLocationOnScreen(point); point[0] += mark.getWidth() / 2; point[1] += mark.getHeight() / 2; });
            long downTime = SystemClock.uptimeMillis();
            try {
                pointer(downTime, MotionEvent.ACTION_DOWN, point[0], point[1]);
                need(waitUntil(() -> field(activity, "entryMotion") == null && !touchMotion.isRunning(), 2000), "Actual injected touch-down cancels active intro");
                pointer(downTime, MotionEvent.ACTION_MOVE, point[0], point[1] - 48);
            } finally { pointer(downTime, MotionEvent.ACTION_UP, point[0], point[1] - 48); }
            noMotion("Touch-down/scroll-start gesture leaves both rotations stopped"); capture("entry-motion-after-touch");
            closeActivity(); launch(); ObjectAnimator second = awaitMotion();
            ui(() -> activity.startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
            need(waitUntil(() -> !Boolean.TRUE.equals(field(activity, "menuHostActive")), 15000), "Actual Home transition pauses entry");
            need(field(activity, "entryMotion") == null && !second.isRunning(), "Lifecycle pause stops actual active animator");
            ui(() -> getTargetContext().startActivity(mainIntent())); need(waitUntil(() -> Boolean.TRUE.equals(field(activity, "menuHostActive")), 15000), "Entry resumes after Home");
            noMotion("Returning from Home does not restart stopped intro"); capture("entry-motion-after-home");
        } else {
            need(waitUntil(() -> Boolean.TRUE.equals(field(activity, "entryMotionPlayed")), 2000), "Reduced-motion entry records intro as handled");
            noMotion("Reduced-motion setting skips animation and leaves logo still"); recreate(); noMotion("Reduced-motion recreation remains still"); capture("entry-reduced-motion");
        }
        observerCleanupCheck();
        need(checkpoint.draft.equals(store.draft(checkpoint.company, checkpoint.conversation).text), "Motion/lifecycle checks preserve synthetic draft");
    }
    /** Read-only observer inspection only. Never changes hidden-API policy or registration lists. */
    private static List<?> observerList(Object observer, String fieldName) throws ReflectiveOperationException {
        Field field = observer.getClass().getDeclaredField(fieldName); field.setAccessible(true); Object list = field.get(observer);
        if (list == null) return Collections.emptyList();
        if (list instanceof List) return new ArrayList<>((List<?>)list);
        // Android's ViewTreeObserver.CopyOnWriteArray stores its actual registrations in mData.
        Field data = list.getClass().getDeclaredField("mData"); data.setAccessible(true); Object values = data.get(list);
        if (values == null) return Collections.emptyList();
        if (!(values instanceof List)) throw new ReflectiveOperationException("Unsupported observer registry shape");
        return new ArrayList<>((List<?>)values);
    }
    private static List<Object> appCallbacks(List<?> all) {
        List<Object> own = new ArrayList<>(); for (Object callback : all) if (callback != null && callback.getClass().getName().startsWith(PKG + ".MainActivity")) own.add(callback); return own;
    }
    private static boolean containsIdentity(List<?> all, Object target) { for (Object value : all) if (value == target) return true; return false; }
    private void observerCleanupCheck() {
        final View retired = (View)field(activity, "root"); final ViewTreeObserver observer = retired.getViewTreeObserver();
        final List<Object> focus = new ArrayList<>(), layout = new ArrayList<>(); final String[] blocked = {null};
        ui(() -> {
            try { focus.addAll(appCallbacks(observerList(observer, "mOnGlobalFocusListeners"))); layout.addAll(appCallbacks(observerList(observer, "mOnGlobalLayoutListeners"))); }
            catch (ReflectiveOperationException | SecurityException unavailable) { blocked[0] = unavailable.getClass().getSimpleName() + ": " + unavailable.getMessage(); }
        });
        if (blocked[0] == null) need(focus.size() == 1 && layout.size() == 1, "Current attached entry registers exactly one app focus and one layout callback");
        ui(() -> need(tag("bchat-explore-demo").performClick(), "Actual demo navigation detaches entry root"));
        need(waitUntil(() -> !retired.isAttachedToWindow() && "list".equals(screen()), 10000), "Retired entry root is actually detached");
        if (blocked[0] != null) { report("SCOPE Direct observer-list inspection unavailable: " + blocked[0] + "; no hidden-API/security settings changed. Native detachment and source cleanup assertions remain separate evidence."); return; }
        ui(() -> {
            try {
                need(observer.isAlive(), "The original shared window observer remains alive after entry detaches");
                List<?> currentFocus = observerList(observer, "mOnGlobalFocusListeners"), currentLayout = observerList(observer, "mOnGlobalLayoutListeners");
                for (Object callback : focus) need(!containsIdentity(currentFocus, callback), "Retired entry focus callback removed from the still-live shared observer");
                for (Object callback : layout) need(!containsIdentity(currentLayout, callback), "Retired entry layout callback removed from the still-live shared observer");
            } catch (ReflectiveOperationException | SecurityException unavailable) {
                report("SCOPE Post-detach registry inspection unavailable: " + unavailable.getClass().getSimpleName() + "; removal is not claimed by this runtime check.");
            }
        });
    }
    private void pointer(long downTime, int action, float x, float y) {
        MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, x, y, 0);
        event.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);
        try { sendPointerSync(event); } finally { event.recycle(); }
    }
    private ObjectAnimator awaitMotion() {
        need(waitUntil(() -> field(activity, "entryMotion") instanceof ObjectAnimator && ((ObjectAnimator)field(activity, "entryMotion")).isRunning()
                && (Math.abs(tag("bchat-entry-mark").getRotationY()) > .05f || Math.abs(tag("bchat-entry-mark").getRotation()) > .05f), 4000), "Actual intro animator observed running on fresh entry");
        return (ObjectAnimator)field(activity, "entryMotion");
    }
    private void noMotion(String label) {
        for (int i = 0; i < 8; i++) { ui(() -> need(field(activity, "entryMotion") == null && Boolean.TRUE.equals(field(activity, "entryMotionPlayed"))
                && Math.abs(tag("bchat-entry-mark").getRotationY()) < .01f && Math.abs(tag("bchat-entry-mark").getRotation()) < .01f, label)); SystemClock.sleep(150); }
    }
    private void saveCheckpoint() throws IOException {
        try (ObjectOutputStream output = new ObjectOutputStream(new FileOutputStream(checkpointFile))) { output.writeObject(checkpoint); }
    }
    private void loadCheckpoint() throws Exception {
        need(checkpointFile.isFile(), "An existing synthetic staged checkpoint is required");
        try (ObjectInputStream input = new ObjectInputStream(new FileInputStream(checkpointFile))) { checkpoint = (Checkpoint)input.readObject(); }
        need("BChat disposable entry lifecycle v2".equals(checkpoint.marker) && checkpoint.stateName.matches("entry-session-[a-f0-9-]{36}\\.bin"), "Staged fixture identity validated");
        store = new ChatStore(new File(getTargetContext().getFilesDir(), checkpoint.stateName));
    }
    private void runProcessStage() throws Exception {
        if ("restore".equals(stage)) { loadCheckpoint(); finishedSequence = true; return; }
        int number;
        try { number = Integer.parseInt(stage); } catch (NumberFormatException error) { throw new AssertionError("stage must be motion, 0, 1, 2, 3 or restore"); }
        if (number == 0) {
            checkpoint = freshCheckpoint(); saveCheckpoint(); prepareEntry(); launch();
            need("entry".equals(screen()) && !((CheckBox)tag("bchat-entry-remember")).isChecked(), "Fresh process begins with remember-me unchecked");
            clickDemo(); need(processActive() && !preferences.getBoolean("demo-entry-active", true) && !preferences.getBoolean("remember-demo-entry", true), "Unchecked entry is active in process only");
            recreate(); need("list".equals(screen()) && processActive(), "Unchecked demo survives same-process Activity recreation");
        } else {
            loadCheckpoint(); need(number == checkpoint.nextStage, "Expected next process stage " + number);
            need(android.os.Process.myPid() != checkpoint.priorPid && !processActive(), "Real new process PID and naturally reset process session");
            fixtureGuard.install(store); launch();
            if (number == 1) {
                need("entry".equals(screen()) && !((CheckBox)tag("bchat-entry-remember")).isChecked(), "Unchecked demo returns to entry after real process restart");
                ui(() -> { CheckBox remember = (CheckBox)tag("bchat-entry-remember"); need(remember.isEnabled() && remember.isAttachedToWindow(), "Actual remember-me checkbox is available"); remember.performClick(); need(remember.isChecked(), "Actual remember-me checkbox selected"); });
                clickDemo(); need(processActive() && preferences.getBoolean("demo-entry-active", false) && preferences.getBoolean("remember-demo-entry", false), "Checked entry persists the explicit remember choice");
            } else if (number == 2) {
                need("list".equals(screen()) && preferences.getBoolean("demo-entry-active", false), "Remembered demo survives actual process restart");
                ui(() -> invoke(activity, "confirmLogout", new Class<?>[0])); clickPositive();
                need(waitUntil(() -> "entry".equals(screen()), 10000) && !processActive() && !preferences.getBoolean("demo-entry-active", true), "Explicit exit clears both session paths");
                need(((CheckBox)tag("bchat-entry-remember")).isChecked(), "Exit preserves remember-me choice without keeping a session");
            } else if (number == 3) {
                need("entry".equals(screen()) && !processActive() && !preferences.getBoolean("demo-entry-active", true)
                        && ((CheckBox)tag("bchat-entry-remember")).isChecked(), "Explicit exit remains signed out after another actual process restart");
                finishedSequence = true;
            } else throw new AssertionError("Unsupported stage " + number);
        }
        need(checkpoint.draft.equals(store.draft(checkpoint.company, checkpoint.conversation).text), "Exact synthetic draft preserved through process stage " + number);
        capture("entry-process-stage-" + number);
        if (!finishedSequence) { checkpoint.nextStage = number + 1; checkpoint.priorPid = android.os.Process.myPid(); saveCheckpoint(); report("NEXT Force-stop only disposable com.baseer.freshchat, then run stage=" + checkpoint.nextStage); }
    }
    private void clickDemo() { ui(() -> need(tag("bchat-explore-demo").performClick(), "Actual demo-entry button clicked")); need(waitUntil(() -> "list".equals(screen()), 10000), "Demo list rendered"); }
    @SuppressWarnings("unchecked") private List<View> roots() {
        try { if (Build.VERSION.SDK_INT >= 29) return (List<View>)Class.forName("android.view.inspector.WindowInspector").getMethod("getGlobalWindowViews").invoke(null);
            Class<?> type = Class.forName("android.view.WindowManagerGlobal"); Object instance = type.getDeclaredMethod("getInstance").invoke(null); Field f = type.getDeclaredField("mViews"); f.setAccessible(true); return new ArrayList<>((List<View>)f.get(instance)); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private View positive() { for (View root : roots()) if (root != activity.getWindow().getDecorView() && root.isAttachedToWindow()) { View button = root.findViewById(android.R.id.button1); if (button != null) return button; } return null; }
    private void clickPositive() { need(waitUntil(() -> positive() != null, 10000), "Native exit confirmation attached"); ui(() -> need(positive().performClick(), "Native exit confirmation clicked")); }
    private void capture(String label) throws Exception {
        if (!screenshots) return; SystemClock.sleep(600); Bitmap image = getUiAutomation().takeScreenshot(); need(image != null, "Actual lifecycle screenshot available");
        try { File dir = activity.getExternalFilesDir("entry-lifecycle-screenshots"); need(dir != null && (dir.isDirectory() || dir.mkdirs()), "Synthetic screenshot directory");
            File output = new File(dir, label + "-api" + Build.VERSION.SDK_INT + ".png"); try (FileOutputStream out = new FileOutputStream(output)) { need(image.compress(Bitmap.CompressFormat.PNG, 100, out), "Lifecycle screenshot written"); } report("SCREENSHOT " + output.getAbsolutePath()); }
        finally { image.recycle(); }
    }
    private static byte[] digest(File file) throws Exception { MessageDigest digest = MessageDigest.getInstance("SHA-256"); try (InputStream in = new FileInputStream(file)) { byte[] b = new byte[8192]; for (int n; (n = in.read(b)) >= 0;) digest.update(b, 0, n); } return digest.digest(); }
    @SuppressWarnings("unchecked") private void restore(SharedPreferences target, Map<String, Object> values) {
        SharedPreferences.Editor edit = target.edit().clear();
        for (Map.Entry<String, Object> entry : values.entrySet()) { String k = entry.getKey(); Object v = entry.getValue();
            if (v instanceof String) edit.putString(k, (String)v); else if (v instanceof Boolean) edit.putBoolean(k, (Boolean)v); else if (v instanceof Integer) edit.putInt(k, (Integer)v);
            else if (v instanceof Long) edit.putLong(k, (Long)v); else if (v instanceof Float) edit.putFloat(k, (Float)v); else if (v instanceof Set) edit.putStringSet(k, new HashSet<>((Set<String>)v)); }
        need(edit.commit() && target.getAll().equals(values), "Prior preference map restored exactly");
    }
    private void restoreCheckpoint() throws Exception {
        if (checkpoint == null) return; restore(preferences, checkpoint.preferences); restore(previewPreferences, checkpoint.preview);
        restore(getTargetContext().getSharedPreferences("bchat-editor-recovery-v1",0), checkpoint.recovery);
        setStatic(settingsType, "processDemoSession", checkpoint.originalProcess);
        UiFixtureGuard.verifyHashes(getTargetContext().getFilesDir(),checkpoint.originalFiles);
        need(true,"All preexisting private-file SHA-256 preserved across staged processes");
        File normal = new File(getTargetContext().getFilesDir(), "chat-state-v1.bin");
        need(checkpoint.normalExisted ? normal.isFile() && Arrays.equals(checkpoint.normalHash, digest(normal)) : !normal.exists(), "Normal chat-state snapshot unchanged");
        for (String suffix : new String[]{"", ".bak", ".tmp", ".last-good", ".lock"}) { File file = new File(getTargetContext().getFilesDir(), checkpoint.stateName + suffix); if (file.exists()) need(file.delete(), "Removed only staged synthetic state " + file.getName()); }
        if (checkpointFile.exists()) need(checkpointFile.delete(), "Removed completed synthetic checkpoint");
    }
}

package com.baseer.bwork.legacy.test;

import android.app.*;
import android.content.*;
import android.graphics.Bitmap;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.baseer.bwork.legacy.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;

/** Narrow real external-grant/active-media exit acceptance; synthetic disposable installs only. */
public final class EntryBoundaryInstrumentation extends Instrumentation {
    private static final String APP_PACKAGE = "com.baseer.bchat.preview";
    private static final String PKG = "com.baseer.bwork.legacy", MAIN = PKG + ".MainActivity", TEST = PKG + ".entryboundarytest";
    private UiFixtureGuard fixtureGuard;
    private Activity activity; private Class<?> activityType, settingsType; private boolean priorProcessSession; private ChatStore store; private Object priorStore;
    private SharedPreferences preferences, previewPreferences; private Map<String, ?> priorPreferences, priorPreview;
    private File normal, state; private byte[] normalHash; private boolean normalExisted, disposable, recording, screenshots, aborted, selected;
    private String company, conversation, sourceToken; private int failures;
    private final List<File> owned = new ArrayList<>(); private final List<String> results = new ArrayList<>();
    @Override public void onCreate(Bundle args) {
        super.onCreate(args); disposable = args != null && "true".equals(args.getString("disposable"));
        recording = args != null && "true".equals(args.getString("recording")); screenshots = args != null && "true".equals(args.getString("screenshots")); start();
    }
    @Override public void onStart() {
        boolean complete = false;
        try { need(disposable, "Explicit disposable installation required"); runChecks(); complete = true; }
        catch (Throwable error) { failures++; report("ERROR " + android.util.Log.getStackTraceString(error)); }
        finally { cleanup(); }
        boolean passed = complete && failures == 0; Bundle result = new Bundle();
        result.putString("stream", "\n" + (passed ? "PASS" : "FAILED") + " entry boundaries\n" + String.join("\n", results) + "\n");
        if (!passed) result.putString("failure", failures + " failed/blocked boundary checks"); finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
    }
    private void report(String message) { results.add(message); android.util.Log.i("BWorkEntryBoundary", message); Bundle b = new Bundle(); b.putString("stream", message + "\n"); sendStatus(0, b); }
    private void need(boolean okay, String label) { if (!okay) throw new AssertionError(label); report("PASS " + label); }
    private void check(boolean okay, String label) { if (!okay) failures++; report((okay ? "PASS " : "FAIL ") + label); }
    private static Object field(Object o, String name) {
        try { Field f = o.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(o); }
        catch (ReflectiveOperationException error) { throw new AssertionError(name, error); }
    }
    private static Object invoke(Object o, String name, Class<?>[] types, Object... args) {
        try { Method m = o.getClass().getDeclaredMethod(name, types); m.setAccessible(true); return m.invoke(o, args); }
        catch (ReflectiveOperationException error) { throw new AssertionError(name, error); }
    }
    private Object call(String name) { return invoke(activity, name, new Class<?>[0]); }
    private Object processStore(Object value, boolean write) {
        try { Field f = activityType.getDeclaredField("processStore"); f.setAccessible(true); Object old = f.get(null); if (write) f.set(null, value); return old; }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private void ui(Runnable action) {
        if (aborted) throw new AssertionError("No further UI work after timeout");
        Handler handler = new Handler(Looper.getMainLooper()); CountDownLatch done = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>(); AtomicInteger gate = new AtomicInteger();
        Runnable task = () -> { if (!gate.compareAndSet(0, 1)) { done.countDown(); return; }
            try { action.run(); } catch (Throwable error) { failure.set(error); } finally { gate.set(2); done.countDown(); } };
        if (!handler.post(task)) { aborted = true; throw new AssertionError("Main Handler rejected action"); }
        try { if (!done.await(30000, TimeUnit.MILLISECONDS)) { aborted = true; gate.compareAndSet(0, 3); handler.removeCallbacks(task); throw new AssertionError("BLOCKED main-thread deadline; no cleanup racing in-flight work"); } }
        catch (InterruptedException error) { aborted = true; Thread.currentThread().interrupt(); throw new AssertionError(error); }
        if (failure.get() != null) throw new AssertionError("UI boundary action", failure.get());
    }
    private boolean waitUntil(BooleanSupplier check, long millis) {
        long end = SystemClock.elapsedRealtime() + millis; boolean[] okay = {false};
        do { ui(() -> okay[0] = check.getAsBoolean()); if (okay[0]) return true; SystemClock.sleep(80); } while (SystemClock.elapsedRealtime() < end);
        return false;
    }
    private Intent mainIntent() { return new Intent(Intent.ACTION_MAIN).setComponent(new ComponentName(APP_PACKAGE, MAIN)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); }
    private void launch() {
        ActivityMonitor monitor = addMonitor(MAIN, null, false);
        try { ui(() -> getTargetContext().startActivity(mainIntent())); activity = monitor.waitForActivityWithTimeout(45000); }
        finally { removeMonitor(monitor); }
        need(activity != null, "Activity launch completed"); resumed();
    }
    private void resumed() { need(waitUntil(() -> Boolean.TRUE.equals(field(activity, "menuHostActive")) && !Boolean.TRUE.equals(field(activity,"initializing")), 45000), "Target Activity resumed"); need(field(activity, "store") == store, "Only isolated ChatStore selected"); }
    private void runChecks() throws Exception {
        Context context = getTargetContext(); fixtureGuard = new UiFixtureGuard(context); activityType = context.getClassLoader().loadClass(MAIN);
        settingsType = context.getClassLoader().loadClass(PKG + ".LocalSettings");
        Field session = settingsType.getDeclaredField("processDemoSession"); session.setAccessible(true); priorProcessSession = session.getBoolean(null); session.setBoolean(null, false);
        normal = new File(context.getFilesDir(), "chat-state-v1.bin"); normalExisted = normal.exists(); normalHash = normalExisted ? digest(normal) : null;
        preferences = context.getSharedPreferences(com.baseer.bwork.legacy.compat.LegacyIdentity.SETTINGS, Context.MODE_PRIVATE); priorPreferences = new HashMap<>(preferences.getAll());
        previewPreferences = context.getSharedPreferences("share-preview", Context.MODE_PRIVATE); priorPreview = new HashMap<>(previewPreferences.getAll());
        need(preferences.edit().putBoolean("demo-entry-active", false).putBoolean("remember-demo-entry", false).putString("interface-language", "ar").commit(), "Synthetic entry preference prepared");
        need(previewPreferences.edit().clear().commit(), "Synthetic share-preview preferences prepared");
        state = new File(context.getFilesDir(), "entry-boundary-" + UUID.randomUUID() + ".bin"); owned.add(state); owned.add(new File(state + ".bak")); owned.add(new File(state + ".tmp"));
        store = new ChatStore(state); company = store.companies().get(0).id; conversation = store.conversations(company).get(0).id;
        priorStore = processStore(null, false); fixtureGuard.install(store); selected = true; launch();
        externalFileGrant(); activePlaybackExit();
        if (recording) activeRecordingExit(); else report("SCOPE Virtual active recording exit was not requested; run -e recording true on an authorized emulator with existing RECORD_AUDIO permission.");
    }
    private void externalFileGrant() throws Exception {
        sourceToken = UUID.randomUUID() + ".png";
        Intent source = new Intent().setComponent(new ComponentName(TEST, SyntheticShareActivity.class.getName()))
                .putExtra(SyntheticShareActivity.TOKEN, sourceToken).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        ui(() -> getTargetContext().startActivity(source));
        need(waitUntil(() -> field(activity, "deferredEntryIntent") instanceof Intent
                && ((Intent)field(activity, "deferredEntryIntent")).getParcelableExtra(Intent.EXTRA_STREAM) != null, 15000), "Separate-UID source delivers signed-out PNG ACTION_SEND with URI");
        Intent deferred = (Intent)field(activity, "deferredEntryIntent");
        final Uri uri = deferred.getParcelableExtra(Intent.EXTRA_STREAM); String expectedHash = deferred.getStringExtra(SyntheticShareActivity.SHA);
        need(expectedHash != null && (deferred.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION) != 0
                && deferred.getClipData() != null && uri.equals(deferred.getClipData().getItemAt(0).getUri()), "Actual source read grant and ClipData preserved");
        need(store.pendingShare() == null && "entry".equals(field(activity, "screen")), "File remains deferred before Explore");
        ui(() -> activity.startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
        SystemClock.sleep(350); ui(() -> getTargetContext().startActivity(mainIntent())); resumed();
        need(uri.equals(((Intent)field(activity, "deferredEntryIntent")).getParcelableExtra(Intent.EXTRA_STREAM)), "Home/MAIN preserves external file URI");
        ActivityMonitor monitor = addMonitor(MAIN, null, false); Activity previous = activity;
        try { ui(() -> invoke(previous, "applyLanguage", new Class<?>[]{String.class}, "en")); activity = monitor.waitForActivityWithTimeout(45000); }
        finally { removeMonitor(monitor); }
        need(activity != null && activity != previous, "Entry language recreation completed"); resumed();
        deferred = (Intent)field(activity, "deferredEntryIntent");
        need(deferred != null && uri.equals(deferred.getParcelableExtra(Intent.EXTRA_STREAM)) && "entry".equals(field(activity, "screen")), "Bundle keeps the granted URI after recreation");
        ui(() -> { View explore = activity.getWindow().getDecorView().findViewWithTag("bwork-explore-demo"); need(explore != null && explore.performClick(), "Explicit Explore after deferred file"); });
        need(waitUntil(() -> store.pendingShare() != null && "picker".equals(field(activity, "screen")), 15000), "Granted PNG imported only after Explore");
        ChatStore.PendingShare pending = store.pendingShare(); need(pending.attachments.size() == 1, "Exactly one generated external image imported");
        ChatStore.Attachment image = pending.attachments.get(0); File imported = new File(image.path); owned.add(imported);
        need(imported.isFile() && expectedHash.equals(hex(digest(imported))), "External PNG original SHA-256 survives Home/recreation/deferred import");
        ui(() -> {
            ListView list = (ListView)field(activity, "recipientList"); int at = -1;
            for (int i = 0; i < list.getAdapter().getCount(); i++) if (list.getAdapter().getItem(i) instanceof ChatStore.Recipient) { at = i; break; }
            need(at >= 0, "Synthetic recipient exists"); list.performItemClick(list.getChildAt(at - list.getFirstVisiblePosition()), at, list.getAdapter().getItemId(at));
        });
        need(waitUntil(() -> "preview".equals(field(activity, "screen")), 10000), "Actual external-image preview opens"); capture("external-file-preview");
        ui(() -> { try { store.cancelPendingShare(pending.id); call("clearPreview"); call("showList"); } catch (IOException error) { throw new AssertionError(error); } });
        cleanSource();
    }
    private void cleanSource() {
        if (sourceToken == null) return;
        Intent cleanup = new Intent("cleanup").setComponent(new ComponentName(TEST, SyntheticShareActivity.class.getName()))
                .putExtra(SyntheticShareActivity.TOKEN, sourceToken).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        ui(() -> getTargetContext().startActivity(cleanup)); SystemClock.sleep(500); ui(() -> getTargetContext().startActivity(mainIntent())); resumed(); sourceToken = null;
    }
    private void activePlaybackExit() throws Exception {
        ChatStore.Attachment wav = makeWav(); File file = new File(wav.path); byte[] hash = digest(file);
        store.setDraft(company, conversation, "Synthetic playback preserved on exit", Collections.singletonList(wav));
        ui(() -> invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation));
        need(waitUntil(() -> findVoice((View)field(activity, "attachmentTray"), wav.id) != null, 10000), "Real draft contains generated WAV control");
        Object player = field(activity, "audioPlayback");
        ui(() -> ((View)field(findVoice((View)field(activity, "attachmentTray"), wav.id), "play")).performClick());
        need(waitUntil(() -> {
            PlaybackState state = (PlaybackState)field(player, "state"); MediaPlayer nativePlayer = (MediaPlayer)field(player, "player");
            return state.phase() == PlaybackState.Phase.PLAYING && nativePlayer != null && nativePlayer.getCurrentPosition() > 150;
        }, 12000), "Native playback actually advances before exit");
        capture("playing-before-exit"); ui(() -> call("confirmLogout"));
        need(waitUntil(() -> dialogButton(android.R.id.button1) != null, 10000), "Exit dialog is visible during active playback");
        ui(() -> need(((PlaybackState)field(player, "state")).phase() == PlaybackState.Phase.PLAYING, "Playback remains active immediately before confirmed exit"));
        clickPositive();
        need(waitUntil(() -> "entry".equals(field(activity, "screen")), 10000), "Confirmed playback exit opens entry");
        ui(() -> check(field(player, "player") == null && ((PlaybackState)field(player, "state")).phase() == PlaybackState.Phase.IDLE
                && field(player, "focus") == null, "Exit releases native player, resets state and abandons audio focus"));
        check(file.exists() && Arrays.equals(hash, digest(file)) && store.draft(company, conversation).attachments.size() == 1, "Exit preserves completed WAV draft and original SHA-256");
        capture("entry-after-playing-exit");
        ui(() -> activity.getWindow().getDecorView().findViewWithTag("bwork-explore-demo").performClick());
    }
    private void activeRecordingExit() throws Exception {
        need("ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE), "Recording restricted to disposable emulator hardware");
        need(activity.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED,
                "Existing virtual-emulator RECORD_AUDIO grant required; no permission changes");
        ChatStore.Draft before = store.draft(company, conversation);
        ui(() -> { invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation);
            invoke(activity, "startVoice", new Class<?>[]{String.class, String.class, boolean.class}, company, conversation, true); });
        Object recorder = field(activity, "voiceRecorder");
        need(recorder != null && Boolean.TRUE.equals(invoke(recorder, "isRecording", new Class<?>[0])), "Actual virtual MediaRecorder is active");
        File partial = (File)field(recorder, "recordingFile"); need(partial != null, "Active recorder owns a synthetic unfinished file"); owned.add(partial);
        capture("unfinished-recording-before-exit"); ui(() -> call("confirmLogout"));
        need(waitUntil(() -> dialogButton(android.R.id.button1) != null, 10000), "Exit dialog visible during unfinished recording");
        ui(() -> need(field(activity, "voiceRecorder") == recorder && Boolean.TRUE.equals(invoke(recorder, "isRecording", new Class<?>[0])),
                "Recorder is still active immediately before confirmed exit"));
        clickPositive(); need(waitUntil(() -> "entry".equals(field(activity, "screen")), 10000), "Confirmed recording exit opens entry");
        check(field(activity, "voiceRecorder") == null && !Boolean.TRUE.equals(invoke(recorder, "isRecording", new Class<?>[0])) && !partial.exists(),
                "Exit cancels actual recorder and deletes only unfinished recording bytes");
        ChatStore.Draft after = store.draft(company, conversation);
        check(before.text.equals(after.text) && before.attachments.size() == after.attachments.size()
                && before.attachments.get(0).id.equals(after.attachments.get(0).id), "Recording cancellation preserves the earlier completed draft attachment");
        capture("entry-after-recording-exit");
    }
    private View findVoice(View view, String id) {
        if (view == null) return null;
        if ("VoicePlayerView".equals(view.getClass().getSimpleName()) && id.equals(((ChatStore.Attachment)field(view, "file")).id)) return view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) { View found = findVoice(((ViewGroup)view).getChildAt(i), id); if (found != null) return found; }
        return null;
    }
    @SuppressWarnings("unchecked") private List<View> roots() {
        try {
            if (Build.VERSION.SDK_INT >= 29) return (List<View>)Class.forName("android.view.inspector.WindowInspector").getMethod("getGlobalWindowViews").invoke(null);
            Class<?> type = Class.forName("android.view.WindowManagerGlobal"); Object manager = type.getDeclaredMethod("getInstance").invoke(null);
            Field f = type.getDeclaredField("mViews"); f.setAccessible(true); return new ArrayList<>((List<View>)f.get(manager));
        } catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private View dialogButton(int id) { for (View root : roots()) if (root != activity.getWindow().getDecorView() && root.isAttachedToWindow()) { View button = root.findViewById(id); if (button != null) return button; } return null; }
    private void clickPositive() { ui(() -> { View button = dialogButton(android.R.id.button1); need(button != null && button.isEnabled() && button.performClick(), "Native positive exit button clicked"); }); }
    private ChatStore.Attachment makeWav() throws IOException {
        File directory = new File(activity.getFilesDir(), "attachments"); if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Synthetic attachment directory");
        File file = new File(directory, UUID.randomUUID() + ".wav"); owned.add(file); int rate = 16000, samples = rate * 30, bytes = samples * 2;
        ByteBuffer header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        header.put(new byte[]{'R','I','F','F'}).putInt(bytes + 36).put(new byte[]{'W','A','V','E','f','m','t',' '}).putInt(16)
                .putShort((short)1).putShort((short)1).putInt(rate).putInt(rate * 2).putShort((short)2).putShort((short)16).put(new byte[]{'d','a','t','a'}).putInt(bytes);
        try (OutputStream out = new BufferedOutputStream(new FileOutputStream(file))) {
            out.write(header.array()); for (int i = 0; i < samples; i++) { short value = (short)(Math.sin(2 * Math.PI * 440 * i / rate) * 1200); out.write(value & 255); out.write((value >> 8) & 255); }
        }
        return new ChatStore.Attachment(file.getCanonicalPath(), "synthetic-exit.wav", "audio/wav", file.length());
    }
    private static byte[] digest(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) { byte[] buffer = new byte[4096]; for (int n; (n = in.read(buffer)) >= 0;) digest.update(buffer, 0, n); }
        return digest.digest();
    }
    private static String hex(byte[] bytes) { StringBuilder text = new StringBuilder(); for (byte b : bytes) text.append(String.format(Locale.ROOT, "%02x", b & 255)); return text.toString(); }
    private void capture(String label) throws Exception {
        if (!screenshots) return; SystemClock.sleep(800); Bitmap image = getUiAutomation().takeScreenshot(); need(image != null, "Actual boundary screenshot: " + label);
        try { File dir = activity.getExternalFilesDir("entry-boundary-screenshots"); need(dir != null && (dir.isDirectory() || dir.mkdirs()), "External screenshot directory");
            File output = new File(dir, label + "-api" + Build.VERSION.SDK_INT + ".png"); try (FileOutputStream stream = new FileOutputStream(output)) { need(image.compress(Bitmap.CompressFormat.PNG, 100, stream), "Screenshot written"); } report("SCREENSHOT " + output.getAbsolutePath()); }
        finally { image.recycle(); }
    }
    @SuppressWarnings("unchecked") private void restore(SharedPreferences p, Map<String, ?> old) {
        if (p == null || old == null) return; SharedPreferences.Editor edit = p.edit().clear();
        for (Map.Entry<String, ?> entry : old.entrySet()) { Object v = entry.getValue(); String k = entry.getKey();
            if (v instanceof String) edit.putString(k, (String)v); else if (v instanceof Boolean) edit.putBoolean(k, (Boolean)v); else if (v instanceof Integer) edit.putInt(k, (Integer)v);
            else if (v instanceof Long) edit.putLong(k, (Long)v); else if (v instanceof Float) edit.putFloat(k, (Float)v); else if (v instanceof Set) edit.putStringSet(k, new HashSet<>((Set<String>)v)); }
        check(edit.commit() && p.getAll().equals(old), "Original preference map restored exactly");
    }
    private void cleanup() {
        if (aborted) { report("BLOCKED no fixture removal or state restoration after main-thread timeout"); return; }
        try {
            if (sourceToken != null && activity != null) cleanSource();
            if (activity != null) { Activity old = activity; ui(old::finish); long until = SystemClock.elapsedRealtime() + 8000;
                while (!old.isDestroyed() && SystemClock.elapsedRealtime() < until) SystemClock.sleep(60); need(old.isDestroyed(), "Target destroyed before restoring store"); }
            if (fixtureGuard != null) fixtureGuard.drain();
            if (selected) processStore(priorStore, true);
            if (settingsType != null) { Field session = settingsType.getDeclaredField("processDemoSession"); session.setAccessible(true); session.setBoolean(null, priorProcessSession); }
            restore(preferences, priorPreferences); restore(previewPreferences, priorPreview);
            if (normal != null) check(normalExisted ? normal.isFile() && Arrays.equals(normalHash, digest(normal)) : !normal.exists(), "Normal ChatStore snapshot unchanged");
            for (File file : owned) if (file.exists()) check(file.delete(), "Removed only owned fixture " + file.getName());
            if (fixtureGuard != null) { fixtureGuard.restore(true); fixtureGuard.verifyOriginals(); check(true,"All preexisting private-file SHA-256 and preferences preserved"); }
        } catch (Throwable error) { failures++; report("ERROR cleanup " + error); }
    }
}

package com.baseer.freshchat.test;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.BitmapDrawable;
import android.media.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.baseer.freshchat.AttachmentSupport;
import com.baseer.freshchat.ChatStore;
import com.baseer.freshchat.PlaybackState;
import java.io.*;
import java.lang.reflect.*;
import java.nio.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;

/** Synthetic fixtures only. Exercises MainActivity's real insertion, cleanup, send and navigation. */
public final class AttachmentRetentionInstrumentation extends Instrumentation {
    private Activity activity;
    private ChatStore isolated;
    private Class<?> activityType;
    private String company, conversation;
    private File stateFile, originalState;
    private byte[] originalDigest;
    private Object player, waves;
    private boolean disposable, isolatedSelected, screenshots, recording;
    private volatile boolean uiAborted;
    private int failures;
    private int appVersionCode;
    private final List<File> created = new ArrayList<>();
    private final List<String> results = new ArrayList<>();
    private final List<ChatStore.Attachment> fixtures = new ArrayList<>();
    private final Map<String, byte[]> hashes = new HashMap<>();
    private final int sampleRate = 44_100, durationMs = 4_000;
    private static final long UI_TIMEOUT_MS = 30_000, LAUNCH_TIMEOUT_MS = 45_000;
    private static final long VIRTUAL_RECORDING_MS = 8_000;
    private static final class HarnessBlocked extends RuntimeException {
        HarnessBlocked(String reason) { super(reason); }
    }

    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        disposable = args != null && "true".equals(args.getString("disposable"));
        screenshots = args != null && "true".equals(args.getString("screenshots"));
        recording = args != null && "true".equals(args.getString("recording"));
        start();
    }
    @Override public void onStart() {
        Bundle out = new Bundle(); boolean completed = false;
        try {
            if (!disposable) throw new IllegalStateException("Refusing: disposable emulator/test install requires -e disposable true");
            runChecks(); completed = true;
        } catch (Throwable error) {
            failures++; report((error instanceof HarnessBlocked ? "BLOCKED " : "ERROR ") + causeSummary(error));
        } finally {
            // Never restore the normal store while a test composer can still receive lifecycle callbacks.
            if (activity != null && isolatedSelected && !uiAborted) try { closeActivity(); }
            catch (Throwable error) { failures++; report("ERROR test teardown " + causeSummary(error)); }
            if (originalState != null && originalDigest != null) try {
                check(originalState.isFile() && Arrays.equals(originalDigest, digest(originalState)),
                        "Original chat-state snapshot bytes were never changed");
            } catch (Throwable error) { failures++; report("ERROR original snapshot verification " + causeSummary(error)); }
            // Only files created and owned by this invocation are removed.
            if (uiAborted) report("BLOCKED UI handoff aborted; no further app actions or fixture deletion. In-flight synthetic work may require disposable guest reset.");
            else for (File file : created) if (file.exists() && !file.delete()) report("WARN synthetic fixture cleanup could not remove " + file.getName());
        }
        boolean passed = completed && failures == 0;
        out.putString("failure", passed ? "" : failures + " retention/device check(s) failed");
        out.putString("stream", "\n" + (passed ? "PASS" : "FAILED") + " attachment retention production-flow suite\n"
                + String.join("\n", results) + "\n");
        finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, out);
    }
    private void report(String text) {
        results.add(text); android.util.Log.i("BChatRetentionTest", text);
        Bundle update = new Bundle(); update.putString("stream", text + "\n"); sendStatus(0, update);
    }
    private void check(boolean condition, String label) {
        if (!condition) failures++;
        report((condition ? "PASS " : "FAIL ") + label);
    }
    private void require(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
        report("PASS " + label);
    }
    private static String causeSummary(Throwable error) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; error != null && i < 6; i++, error = error.getCause()) {
            if (out.length() > 0) out.append(" <- ");
            out.append(error.getClass().getSimpleName()).append(": ").append(error.getMessage());
        }
        return out.toString();
    }
    private void ui(Runnable action) {
        if (uiAborted) throw new HarnessBlocked("Main-thread handoff was already aborted");
        Handler handler = new Handler(Looper.getMainLooper());
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        AtomicInteger gate = new AtomicInteger(0); // queued=0, running=1, complete=2, cancelled=3
        Runnable delivery = () -> {
            if (uiAborted || !gate.compareAndSet(0, 1)) { done.countDown(); return; }
            try { action.run(); } catch (Throwable error) { failure.set(error); }
            finally { gate.set(2); done.countDown(); }
        };
        if (!handler.post(delivery)) { uiAborted = true; throw new HarnessBlocked("Main handler rejected the test action"); }
        boolean finished;
        try { finished = done.await(UI_TIMEOUT_MS, TimeUnit.MILLISECONDS); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); finished = false; }
        if (!finished) {
            uiAborted = true;
            boolean cancelled = gate.compareAndSet(0, 3);
            handler.removeCallbacks(delivery);
            StringBuilder stack = new StringBuilder();
            StackTraceElement[] frames = Looper.getMainLooper().getThread().getStackTrace();
            for (int i = 0; i < Math.min(16, frames.length); i++) stack.append("\n  at ").append(frames[i]);
            throw new HarnessBlocked("Main-thread action exceeded " + UI_TIMEOUT_MS + " ms; "
                    + (cancelled ? "queued action cancelled before execution" : "action was already in flight; test aborts without further mutations")
                    + "; main-thread stack:" + stack);
        }
        if (failure.get() != null) throw new AssertionError("UI operation failed", failure.get());
    }
    private boolean onUi(BooleanSupplier condition) {
        boolean[] answer = {false}; ui(() -> answer[0] = condition.getAsBoolean()); return answer[0];
    }
    private boolean waitUntil(BooleanSupplier condition, long millis) {
        long until = SystemClock.elapsedRealtime() + millis;
        while (SystemClock.elapsedRealtime() < until) {
            if (onUi(condition)) return true;
            SystemClock.sleep(60);
        }
        return onUi(condition);
    }
    private static Object field(Object object, String name) {
        try { Field f = object.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(object); }
        catch (ReflectiveOperationException error) { throw new AssertionError("Field " + name, error); }
    }
    private static void setField(Object object, String name, Object value) {
        try { Field f = object.getClass().getDeclaredField(name); f.setAccessible(true); f.set(object, value); }
        catch (ReflectiveOperationException error) { throw new AssertionError("Set field " + name, error); }
    }
    private void selectProcessStore(ChatStore store) {
        try { Field f = activityType.getDeclaredField("processStore"); f.setAccessible(true); f.set(null, store); }
        catch (ReflectiveOperationException error) { throw new AssertionError("Select isolated process store", error); }
    }
    private static Object invoke(Object object, String name, Class<?>[] types, Object... args) {
        try { Method m = object.getClass().getDeclaredMethod(name, types); m.setAccessible(true); return m.invoke(object, args); }
        catch (ReflectiveOperationException error) { throw new AssertionError("Invoke " + name, error); }
    }
    private Activity launch() {
        String target = "com.baseer.freshchat.MainActivity";
        ActivityMonitor monitor = addMonitor(target, null, false);
        try {
            Intent intent = new Intent(Intent.ACTION_MAIN)
                    .setComponent(new ComponentName("com.baseer.bchat.preview", target)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ui(() -> getTargetContext().startActivity(intent));
            Activity launched = monitor.waitForActivityWithTimeout(LAUNCH_TIMEOUT_MS);
            if (launched == null) { uiAborted = true; throw new HarnessBlocked("Activity launch exceeded " + LAUNCH_TIMEOUT_MS + " ms"); }
            return launched;
        } finally { removeMonitor(monitor); }
    }
    private void runChecks() throws Exception {
        activity = launch(); activityType = activity.getClass();
        awaitResumed("Initial");
        enterDemoIfPresent();
        ChatStore original = (ChatStore)field(activity, "store");
        File attachmentDir = new File(activity.getFilesDir(), "attachments");
        File[] existing = attachmentDir.listFiles();
        require((existing == null || existing.length == 0) && original.attachmentPaths().isEmpty(),
                "Fresh disposable installation has no pre-existing attachment bytes or references");
        originalState = new File(activity.getFilesDir(), "chat-state-v1.bin");
        originalDigest = digest(originalState);
        appVersionCode = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0).versionCode;
        report("INFO API=" + Build.VERSION.SDK_INT + " targetSdk=" + activity.getApplicationInfo().targetSdkVersion
                + " appVersionCode=" + appVersionCode);
        report("INFO APP_ROOT_ABSOLUTE=" + activity.getFilesDir().getAbsolutePath());
        report("INFO APP_ROOT_CANONICAL=" + activity.getFilesDir().getCanonicalPath());
        stateFile = new File(activity.getFilesDir(), "retention-regression-" + UUID.randomUUID() + ".bin");
        created.add(stateFile); created.add(new File(stateFile.getPath() + ".bak")); created.add(new File(stateFile.getPath() + ".tmp"));
        isolated = new ChatStore(stateFile);
        company = isolated.companies().get(0).id; conversation = isolated.conversations(company).get(0).id;
        ui(() -> {
            setField(activity, "store", isolated); selectProcessStore(isolated); isolatedSelected = true;
            invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation);
        });
        player = field(activity, "audioPlayback"); waves = field(activity, "audioWaveforms");
        runFixture(generatedImage(false));
        runFixture(generatedImage(true));
        runFixture(createWav());
        runFixture(createAac());
        if (recording && appVersionCode >= 7) realVirtualRecorderFlow();
        else report("INFO Real virtual MediaRecorder flow was not requested for this candidate run");
        reopenFromDisk();
        for (ChatStore.Attachment fixture : fixtures) verifySource(fixture, "Activity reopen from isolated disk snapshot");
        // Fresh Activity has no previous image/waveform caches. Test the source again after disk reload.
        for (ChatStore.Attachment fixture : fixtures) if (new File(fixture.path).isFile()) {
            if (fixture.mime.startsWith("image/")) verifyNativeImage(fixture, "after reopen");
            else verifyAudio(fixture, (View)field(activity, "history"), "after reopen");
        }
        cachedWaveformWithMissingSource();
        if (appVersionCode >= 7) missingImageAndExportLocalization();
        else report("INFO Missing-image localization assertions apply to candidate versionCode 7+, not frozen baseline");
    }
    private void runFixture(ChatStore.Attachment fixture) throws Exception {
        fixtures.add(fixture); hashes.put(fixture.id, digest(new File(fixture.path)));
        File listed = new File(new File(activity.getFilesDir(), "attachments"), new File(fixture.path).getName());
        report("INFO " + fixture.name + " reference=" + fixture.path + " listing=" + listed.getAbsolutePath()
                + " canonicalEquals=" + listed.getCanonicalPath().equals(fixture.path)
                + " lexicalEquals=" + listed.getAbsolutePath().equals(fixture.path));
        final boolean[] added = {false};
        ui(() -> added[0] = (boolean)invoke(activity, "addFilesToDraft",
                new Class<?>[]{String.class, String.class, List.class}, company, conversation, Collections.singletonList(fixture)));
        check(added[0], fixture.name + " real addFilesToDraft accepted fixture");
        check(isolated.attachmentPaths().contains(fixture.path), fixture.name + " live store retains canonical reference");
        report("INFO " + fixture.name + " OLD_CLEANUP_LEXICAL_MATCH=" + isolated.attachmentPaths().contains(listed.getAbsolutePath()));
        boolean alive = verifySource(fixture, "immediately after real addFilesToDraft cleanup");
        if (fixture.mime.startsWith("audio/")) verifyAudio(fixture, (View)field(activity, "attachmentTray"), "draft");
        else if (alive) { verifyNativeImage(fixture, "draft"); verifyVisibleImage(fixture, (View)field(activity, "attachmentTray"), "draft"); }
        ui(() -> invoke(activity, "sendDraft", new Class<?>[0]));
        ChatStore.Message sent = isolated.lastMessage(company, conversation);
        check(sent != null && sent.attachments.size() == 1 && sent.attachments.get(0).id.equals(fixture.id),
                fixture.name + " actual sendDraft transfers attachment to local message");
        SystemClock.sleep(550); // Real text watcher schedules persistDraft and cleanup at 350 ms.
        ui(() -> invoke(activity, "persistDraft", new Class<?>[0]));
        alive = verifySource(fixture, "after send and delayed/explicit persistDraft cleanup");
        if (fixture.mime.startsWith("audio/")) verifyAudio(fixture, (View)field(activity, "history"), "sent message");
        else if (alive) {
            verifyVisibleImage(fixture, (View)field(activity, "history"), "sent message");
            verifyFullImageInspector(fixture);
        }
        if ("image/png".equals(fixture.mime)) observeChatLayoutQuiescence();
        ui(() -> { invoke(activity, "showList", new Class<?>[0]);
            invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation); });
        verifySource(fixture, "after actual list/chat navigation");
    }
    private void observeChatLayoutQuiescence() {
        final View chatRoot = (View)field(activity, "root");
        final int[] counts = {0, 0};
        final int originalHeight = chatRoot.getLayoutParams().height;
        View.OnLayoutChangeListener listener = (view, l, t, r, b, ol, ot, or, ob) -> {
            counts[0]++;
            if (l == ol && t == ot && r == or && b == ob) counts[1]++;
        };
        ui(() -> { chatRoot.addOnLayoutChangeListener(listener); chatRoot.requestLayout(); });
        try {
            observeLayoutWindow(chatRoot, counts, "after real PNG send");
            if (appVersionCode >= 7) {
                for (int heightDp : new int[]{280, 420}) {
                    ui(() -> {
                        ViewGroup.LayoutParams params = chatRoot.getLayoutParams();
                        params.height = Math.round(heightDp * activity.getResources().getDisplayMetrics().density);
                        chatRoot.setLayoutParams(params);
                    });
                    observeLayoutWindow(chatRoot, counts, "after actual root resize to " + heightDp + "dp");
                    check(onUi(() -> ((EditText)field(activity, "composer")).getMaxLines() == (heightDp < 300 ? 1 : 2)),
                            "Composer maxLines matches actual " + heightDp + "dp resize threshold");
                }
                ui(() -> { ViewGroup.LayoutParams params = chatRoot.getLayoutParams(); params.height = originalHeight; chatRoot.setLayoutParams(params); });
                observeLayoutWindow(chatRoot, counts, "after restoring original root height");
            }
        } finally {
            if (!uiAborted) ui(() -> { chatRoot.removeOnLayoutChangeListener(listener);
                ViewGroup.LayoutParams params = chatRoot.getLayoutParams();
                if (params.height != originalHeight) { params.height = originalHeight; chatRoot.setLayoutParams(params); } });
        }
    }
    private void observeLayoutWindow(View chatRoot, int[] counts, String label) {
        SystemClock.sleep(700);
        final int[] before = {0, 0}, after = {0, 0};
        ui(() -> { before[0] = counts[0]; before[1] = counts[1]; });
        long settleDeadline = SystemClock.elapsedRealtime() + 4000;
        while (SystemClock.elapsedRealtime() < settleDeadline) {
            SystemClock.sleep(500);
            ui(() -> { after[0] = counts[0]; after[1] = counts[1]; });
            if (after[0] == before[0]) break;
            before[0] = after[0]; before[1] = after[1];
        }
        ui(() -> { before[0] = counts[0]; before[1] = counts[1]; });
        SystemClock.sleep(800);
        ui(() -> { after[0] = counts[0]; after[1] = counts[1]; });
        report("INFO LAYOUT " + label + " total=" + before[0] + "->" + after[0]
                + " unchangedBounds=" + before[1] + "->" + after[1]
                + " measured=" + chatRoot.getWidth() + "x" + chatRoot.getHeight());
        if (appVersionCode >= 7) check(before[0] > 0 && before[0] == after[0], "Root layout stops growing over quiet interval " + label);
        else report("INFO Frozen baseline layout growth is recorded; existing retention failures remain failures");
    }
    private void blockedRecording(String detail) {
        failures++;
        report("BLOCKED requested virtual MediaRecorder flow: " + detail + "; this is not a recording pass");
    }
    private void realVirtualRecorderFlow() throws Exception {
        if (!("ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE))) {
            blockedRecording("Refusing capture outside the explicitly disposable emulator hardware"); return;
        }
        if (activity.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            blockedRecording("RECORD_AUDIO was not pre-granted in the disposable guest"); return;
        }
        report("INFO Starting actual MainActivity recorder against virtual emulator microphone for bounded "
                + VIRTUAL_RECORDING_MS + " ms input; no host microphone setup or app validity-threshold change");
        ui(() -> invoke(activity, "startVoice", new Class<?>[]{String.class, String.class, boolean.class}, company, conversation, true));
        Object recorder = field(activity, "voiceRecorder");
        if (recorder == null || !(boolean)invoke(recorder, "isRecording", new Class<?>[0])) {
            blockedRecording("Native virtual microphone/MediaRecorder did not start"); return;
        }
        File recordingFile = (File)field(recorder, "recordingFile");
        if (recordingFile != null) created.add(recordingFile);
        SystemClock.sleep(VIRTUAL_RECORDING_MS);
        if (field(activity, "voiceRecorder") != recorder) {
            blockedRecording("Virtual recording was interrupted before explicit finish"); return;
        }
        ui(() -> invoke(activity, "finishVoice", new Class<?>[]{boolean.class}, true));
        List<ChatStore.Attachment> draft = isolated.draft(company, conversation).attachments;
        if (draft.size() != 1 || !draft.get(0).mime.startsWith("audio/")) {
            blockedRecording("Virtual recorder did not produce a validated saved AAC draft"); return;
        }
        ChatStore.Attachment fixture = draft.get(0);
        fixtures.add(fixture);
        if (new File(fixture.path).isFile()) hashes.put(fixture.id, digest(new File(fixture.path)));
        check(field(activity, "voiceRecorder") == null, "Actual recorder finish releases the virtual microphone before preview");
        verifySource(fixture, "after actual MediaRecorder finish/save");
        verifyAudio(fixture, (View)field(activity, "attachmentTray"), "recorded draft");
        ui(() -> invoke(activity, "sendDraft", new Class<?>[0]));
        ChatStore.Message sent = isolated.lastMessage(company, conversation);
        check(sent != null && sent.attachments.size() == 1 && sent.attachments.get(0).id.equals(fixture.id),
                "Actual recorded AAC is sent through production sendDraft");
        SystemClock.sleep(550); ui(() -> invoke(activity, "persistDraft", new Class<?>[0]));
        verifySource(fixture, "after actual recorder/send/persist cycle");
        verifyAudio(fixture, (View)field(activity, "history"), "sent message");
        ui(() -> { invoke(activity, "showList", new Class<?>[0]);
            invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation); });
        verifySource(fixture, "after actual recorded-message list/chat navigation");
        report("INFO Recorder fixture joins normal navigation/reopen/hash/native-playback checks; silence from virtual input is not speaker acceptance");
    }
    private boolean verifySource(ChatStore.Attachment fixture, String stage) throws Exception {
        File source = new File(fixture.path); boolean present = source.isFile();
        check(present, fixture.name + " source exists " + stage);
        if (present) check(source.length() == fixture.size && Arrays.equals(hashes.get(fixture.id), digest(source)),
                fixture.name + " original length and SHA-256 unchanged " + stage);
        return present;
    }
    private View find(View root, String simpleName, String id) {
        if (root == null) return null;
        if (root.getClass().getSimpleName().equals(simpleName)) {
            ChatStore.Attachment attachment = (ChatStore.Attachment)field(root, "file");
            if (attachment.id.equals(id)) return root;
        }
        if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)root).getChildCount(); i++) {
            View found = find(((ViewGroup)root).getChildAt(i), simpleName, id); if (found != null) return found;
        }
        return null;
    }
    private void verifyVisibleImage(ChatStore.Attachment fixture, View root, String stage) {
        final View[] preview = {null};
        ui(() -> { preview[0] = find(root, "ImagePreviewView", fixture.id);
            if (root == field(activity, "history")) ((ScrollView)field(activity, "messageScroll")).fullScroll(View.FOCUS_DOWN); });
        check(preview[0] != null, fixture.name + " real " + stage + " contains image preview view");
        if (preview[0] == null) return;
        boolean decoded = waitUntil(() -> ((ImageView)field(preview[0], "image")).getDrawable() instanceof BitmapDrawable, 8000);
        check(decoded, fixture.name + " real " + stage + " displays decoded bitmap");
        if (decoded) check(onUi(() -> preview[0].getWidth() > 0 && preview[0].getHeight() > 0), fixture.name + " " + stage + " preview has visible geometry");
        if (decoded && "sent message".equals(stage)) capture("sent-" + fixture.mime.substring(fixture.mime.indexOf('/') + 1));
    }
    private void verifyNativeImage(ChatStore.Attachment fixture, String stage) throws Exception {
        Class<?> type = Class.forName("com.baseer.freshchat.ImagePreviews", true, activity.getClassLoader());
        Method decode = type.getDeclaredMethod("decode", Context.class, ChatStore.Attachment.class, int.class); decode.setAccessible(true);
        Bitmap bitmap = (Bitmap)decode.invoke(null, activity, fixture, 650);
        check(bitmap != null && bitmap.getWidth() > 0 && bitmap.getHeight() > 0,
                fixture.name + " real platform photo decode succeeds " + stage);
        if (bitmap != null) bitmap.recycle();
    }
    @SuppressWarnings("unchecked")
    private List<View> processWindowRoots() {
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                Class<?> inspector = Class.forName("android.view.inspector.WindowInspector");
                return (List<View>)inspector.getMethod("getGlobalWindowViews").invoke(null);
            }
            // API 26/27 predate WindowInspector and hidden-API enforcement. Read only this
            // instrumentation process's existing roots; never change framework/security state.
            Class<?> managerType = Class.forName("android.view.WindowManagerGlobal");
            Object manager = managerType.getDeclaredMethod("getInstance").invoke(null);
            Field views = managerType.getDeclaredField("mViews"); views.setAccessible(true);
            return new ArrayList<>((List<View>)views.get(manager));
        } catch (ReflectiveOperationException unavailable) { throw new AssertionError("Test process window inspection unavailable", unavailable); }
    }
    private void verifyFullImageInspector(ChatStore.Attachment fixture) throws Exception {
        final View[] dialogRoot = {null}, preview = {null};
        ui(() -> invoke(activity, "inspectAttachment", new Class<?>[]{ChatStore.Attachment.class}, fixture));
        boolean shown = waitUntil(() -> {
            for (View root : processWindowRoots()) {
                if (root == activity.getWindow().getDecorView() || !root.isAttachedToWindow()) continue;
                View found = find(root, "ImagePreviewView", fixture.id);
                if (found != null) { dialogRoot[0] = root; preview[0] = found; return true; }
            }
            return false;
        }, 8000);
        check(shown, fixture.name + " real inspectAttachment opens its own full-image dialog window");
        if (!shown) return;
        boolean decoded = waitUntil(() -> ((ImageView)field(preview[0], "image")).getDrawable() instanceof BitmapDrawable, 10000);
        check(decoded, fixture.name + " real full-image inspection dialog displays decoded pixels");
        check(onUi(() -> ((ImageView)field(preview[0], "image")).getScaleType() == ImageView.ScaleType.FIT_CENTER
                && (int)field(preview[0], "target") == 1400 && preview[0].getWidth() > 0 && preview[0].getHeight() > 0),
                fixture.name + " full inspection uses 1400px target, FIT_CENTER and visible geometry");
        if (decoded) capture("full-preview-" + fixture.mime.substring(fixture.mime.indexOf('/') + 1));
        ui(() -> {
            View close = dialogRoot[0].findViewById(android.R.id.button1);
            if (close == null) throw new AssertionError("Normal full-image dialog close button missing");
            close.performClick();
        });
        check(waitUntil(() -> !dialogRoot[0].isAttachedToWindow(), 8000), fixture.name + " full-image dialog closes through its normal positive button");
        check(onUi(() -> "chat".equals(field(activity, "screen"))), fixture.name + " closing inspector leaves the actual chat active");
        verifySource(fixture, "after actual full-image inspection and dismissal");
    }
    private void verifyAudio(ChatStore.Attachment fixture, View root, String stage) {
        final View[] voice = {null};
        ui(() -> { voice[0] = find(root, "VoicePlayerView", fixture.id);
            if (voice[0] != null) ((View)field(voice[0], "play")).performClick(); });
        check(voice[0] != null, fixture.name + " actual " + stage + " contains voice control");
        if (voice[0] == null) return;
        boolean advanced = waitUntil(() -> {
            PlaybackState state = (PlaybackState)field(player, "state");
            MediaPlayer nativePlayer = (MediaPlayer)field(player, "player");
            return state.phase() == PlaybackState.Phase.PLAYING && state.position() > 150
                    && nativePlayer != null && nativePlayer.getCurrentPosition() > 150;
        }, new File(fixture.path).isFile() ? 8000 : 300);
        check(advanced, fixture.name + " native MediaPlayer advances in " + stage);
        if (advanced && "sent message".equals(stage)) capture((fixture.name.startsWith("voice-") ? "playing-recorded-" : "playing-")
                + fixture.mime.substring(fixture.mime.indexOf('/') + 1));
        final String[] diagnostic = {""}; ui(() -> diagnostic[0] = (String)invoke(player, "diagnosticSummary", new Class<?>[0]));
        if (!advanced) {
            final String[] safeState = {""}; ui(() -> safeState[0] = safePlaybackState(voice[0]));
            report("INFO " + fixture.name + " failed playback state " + safeState[0]);
            report("INFO " + fixture.name + " safe playback diagnostics " + diagnostic[0].replace('\n', ';'));
        }
        if (!new File(fixture.path).isFile()) check(onUi(() -> missingCode().equals(viewFailureCode(voice[0]))),
                fixture.name + " missing source is specifically diagnosed " + missingCode());
        ui(() -> invoke(player, "stop", new Class<?>[0]));
    }
    private String safePlaybackState(View voice) {
        PlaybackState state = (PlaybackState)field(player, "state");
        MediaPlayer nativePlayer = (MediaPlayer)field(player, "player");
        Object selectedTarget = field(player, "target");
        String nativePosition = "absent", nativePlaying = "absent";
        if (nativePlayer != null) {
            // Do not make a diagnostic getter put an unprepared native player into Error.
            if (state.phase() == PlaybackState.Phase.PLAYING || state.phase() == PlaybackState.Phase.PAUSED
                    || state.phase() == PlaybackState.Phase.COMPLETE) {
                try { nativePosition = String.valueOf(nativePlayer.getCurrentPosition()); }
                catch (RuntimeException failure) { nativePosition = "error:" + failure.getClass().getSimpleName(); }
                try { nativePlaying = String.valueOf(nativePlayer.isPlaying()); }
                catch (RuntimeException failure) { nativePlaying = "error:" + failure.getClass().getSimpleName(); }
            } else { nativePosition = "not_queried_unprepared"; nativePlaying = "not_queried_unprepared"; }
        }
        return "phase=" + state.phase() + " token=" + state.token() + " playerPresent=" + (nativePlayer != null)
                + " duration=" + state.duration() + " modelPosition=" + state.position()
                + " nativeCurrentPosition=" + nativePosition + " nativeIsPlaying=" + nativePlaying
                + " targetPresent=" + (selectedTarget != null) + " targetIsControl=" + (selectedTarget == voice)
                + " targetAttached=" + (selectedTarget instanceof View && ((View)selectedTarget).isAttachedToWindow())
                + " targetDetachedFlag=" + field(player, "targetDetached")
                + " controlAttached=" + voice.isAttachedToWindow() + " controlShown=" + voice.isShown()
                + " controlHasParent=" + (voice.getParent() != null)
                + " activityResumed=" + field(activity, "menuHostActive")
                + " activityWindowFocus=" + activity.hasWindowFocus()
                + " activityFinishing=" + activity.isFinishing() + " activityDestroyed=" + activity.isDestroyed();
    }
    private void closeActivity() {
        Activity closing = activity; ui(closing::finish);
        long deadline = SystemClock.elapsedRealtime() + 8000;
        while (!closing.isDestroyed() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50);
        if (!closing.isDestroyed()) { uiAborted = true; throw new HarnessBlocked("Activity teardown timed out"); }
        activity = null;
    }
    private void reopenFromDisk() throws Exception {
        closeActivity(); isolated = new ChatStore(stateFile); selectProcessStore(isolated);
        activity = launch();
        awaitResumed("Reopened");
        require(field(activity, "store") == isolated, "Reopened Activity uses the reloaded isolated snapshot only");
        ui(() -> invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation));
        player = field(activity, "audioPlayback"); waves = field(activity, "audioWaveforms");
        check(isolated.draft(company, conversation).attachments.isEmpty(), "Actual sent attachments are no longer in the draft after reopen");
        for (ChatStore.Attachment fixture : fixtures) check(isolated.attachmentPaths().contains(fixture.path),
                fixture.name + " persisted message retains source reference after reopen");
    }
    private void awaitResumed(String label) {
        if (!waitUntil(() -> (boolean)field(activity, "menuHostActive"), LAUNCH_TIMEOUT_MS)) {
            uiAborted = true; throw new HarnessBlocked(label + " Activity did not reach resumed state within " + LAUNCH_TIMEOUT_MS + " ms");
        }
        report("PASS " + label + " Activity reached resumed state");
    }
    private void cachedWaveformWithMissingSource() throws Exception {
        ChatStore.Attachment fixture = createWav();
        final View[] voice = {null};
        Class<?> type = Class.forName("com.baseer.freshchat.VoicePlayerView", true, activity.getClassLoader());
        Constructor<?> constructor = type.getDeclaredConstructor(Context.class, ChatStore.Attachment.class,
                player.getClass(), waves.getClass(), Runnable.class, boolean.class); constructor.setAccessible(true);
        ui(() -> {
            try { voice[0] = (View)constructor.newInstance(activity, fixture, player, waves, null, false); }
            catch (ReflectiveOperationException error) { throw new AssertionError("Synthetic voice control construction", error); }
            LinearLayout host = new LinearLayout(activity); host.setOrientation(LinearLayout.VERTICAL);
            host.addView(voice[0]); activity.setContentView(host); });
        boolean analyzed = waitUntil(() -> {
            Object cached = ((Map<?,?>)field(waves, "cache")).get(fixture.id + ":" + fixture.size);
            return cached != null && field(cached, "peaks") != null;
        }, 15000);
        check(analyzed, "Synthetic missing-source control initially has real cached PCM peaks");
        require(new File(fixture.path).delete(), "Only the explicit synthetic missing-source fixture is removed");
        ui(() -> ((View)field(voice[0], "play")).performClick());
        check(onUi(() -> missingCode().equals(viewFailureCode(voice[0]))),
                "Cached real waveform cannot conceal missing source at playback; " + missingCode() + " is visible");
        ui(() -> invoke(player, "stop", new Class<?>[0]));
    }
    private String missingCode() { return appVersionCode >= 7 ? "BP-SOURCE-MISSING" : "BP-SOURCE-IO"; }
    private String viewFailureCode(View voice) {
        Object event = field(voice, "playbackFailure");
        return event == null ? "" : (String)invoke(event, "code", new Class<?>[0]);
    }
    private void missingImageAndExportLocalization() throws Exception {
        // The preceding intentional audio failure emits a long Toast. Let that test-only
        // overlay expire before collecting either localized missing-image evidence frame.
        if (screenshots) SystemClock.sleep(4000);
        ChatStore.Attachment fixture = generatedImage(false);
        require(new File(fixture.path).delete(), "Only the explicit synthetic missing-image fixture is removed");
        int missingResource = activity.getResources().getIdentifier("image_original_missing", "string", activity.getPackageName());
        require(missingResource != 0, "Fixed-version missing-original localized resource exists");
        Class<?> localeType = Class.forName("com.baseer.freshchat.AppLocale", true, activity.getClassLoader());
        Method withLanguage = localeType.getDeclaredMethod("withLanguage", Context.class, String.class); withLanguage.setAccessible(true);
        Method errorMessage = localeType.getDeclaredMethod("error", Context.class, String.class); errorMessage.setAccessible(true);
        Object previews = field(activity, "imagePreviews");
        Class<?> viewType = Class.forName("com.baseer.freshchat.ImagePreviewView", true, activity.getClassLoader());
        Constructor<?> constructor = viewType.getDeclaredConstructor(Context.class, ChatStore.Attachment.class,
                previews.getClass(), int.class, boolean.class); constructor.setAccessible(true);
        SharedPreferences preferences = activity.getSharedPreferences("bchat-local-settings-v1", Context.MODE_PRIVATE);
        String languageKey = "interface-language";
        boolean hadLanguage = preferences.contains(languageKey); String originalLanguage = preferences.getString(languageKey, null);
        try {
            for (String language : new String[]{"ar", "en"}) {
                require(preferences.edit().putString(languageKey, language).commit(), "Temporary synthetic-test language selected: " + language);
                Context localized = (Context)withLanguage.invoke(null, activity, language);
                String expected = localized.getString(missingResource);
                final View[] preview = {null};
                ui(() -> {
                    try { preview[0] = (View)constructor.newInstance(localized, fixture, previews, 650, false); }
                    catch (ReflectiveOperationException error) { throw new AssertionError("Localized missing image control", error); }
                    LinearLayout host = new LinearLayout(activity); host.setOrientation(LinearLayout.VERTICAL);
                    host.addView(preview[0], new LinearLayout.LayoutParams(320, 220)); activity.setContentView(host);
                });
                boolean missingShown = waitUntil(() -> expected.contentEquals(((TextView)field(preview[0], "status")).getText()), 10000);
                check(missingShown, language + " real missing-image preview displays the localized original-missing label");
                if (missingShown) capture("missing-image-" + language);
                check(onUi(() -> preview[0].getContentDescription() != null
                        && preview[0].getContentDescription().toString().contains(expected)
                        && ((ImageView)field(preview[0], "image")).getDrawable() == null),
                        language + " missing-image accessibility states the original is absent, without a bitmap");
                String exportCode = "";
                try { AttachmentSupport.requirePrivateFile(activity, fixture); }
                catch (IOException missing) { exportCode = missing.getMessage(); }
                check("ATTACHMENT_SOURCE_MISSING".equals(exportCode), language + " export source validation returns the typed missing-original code");
                String translated = (String)errorMessage.invoke(null, localized, exportCode);
                check(expected.equals(translated), language + " AppLocale.error maps export missing-original code to its exact localized resource");
            }
        } finally {
            SharedPreferences.Editor restore = preferences.edit();
            if (hadLanguage) restore.putString(languageKey, originalLanguage); else restore.remove(languageKey);
            check(restore.commit(), "Temporary localization preference restored after synthetic checks");
        }
    }
    private File newPrivate(String extension) throws IOException {
        File directory = new File(activity.getFilesDir().getCanonicalFile(), "attachments");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Synthetic directory unavailable");
        File file = new File(directory, UUID.randomUUID().toString() + extension); created.add(file); return file;
    }
    private void capture(String label) {
        if (!screenshots) return;
        Bitmap screenshot = null;
        try {
            CountDownLatch frames = new CountDownLatch(1);
            AtomicInteger remainingFrames = new AtomicInteger(3);
            ui(() -> {
                for (View root : processWindowRoots()) if (root.isAttachedToWindow()) root.invalidate();
                Choreographer.getInstance().postFrameCallback(new Choreographer.FrameCallback() {
                    public void doFrame(long time) {
                        if (remainingFrames.get() <= 0) return;
                        if (remainingFrames.decrementAndGet() == 0) frames.countDown();
                        else Choreographer.getInstance().postFrameCallback(this);
                    }
                });
            });
            if (!frames.await(5000, TimeUnit.MILLISECONDS)) {
                remainingFrames.set(0); throw new IOException("Bounded screenshot frame-presentation wait expired");
            }
            // Choreographer callbacks precede surface presentation. Allow the newly shown
            // dialog/locale frame and its window transition to reach SurfaceFlinger.
            SystemClock.sleep(650);
            screenshot = getUiAutomation().takeScreenshot();
            if (screenshot == null) throw new IOException("UiAutomation screenshot was unavailable");
            File directory = activity.getExternalFilesDir("retention-test-screenshots");
            if (directory == null) {
                directory = new File(activity.getFilesDir(), "retention-test-screenshots");
                report("INFO External screenshot storage unavailable; using private synthetic-test fallback " + directory.getAbsolutePath());
            }
            if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Synthetic screenshot directory unavailable");
            File output = new File(directory, label + "-api" + Build.VERSION.SDK_INT + "-v" + appVersionCode + ".png");
            try (FileOutputStream stream = new FileOutputStream(output)) {
                if (!screenshot.compress(Bitmap.CompressFormat.PNG, 100, stream)) throw new IOException("Synthetic screenshot encode failed");
            }
            // Deliberately retained for permitted extraction; this directory contains only synthetic test screens.
            report("SCREENSHOT " + output.getAbsolutePath());
        } catch (Throwable error) { check(false, "Requested synthetic screenshot " + label + ": " + causeSummary(error)); }
        finally { if (screenshot != null) screenshot.recycle(); }
    }
    private ChatStore.Attachment attachment(File file, String mime) throws IOException {
        String type = mime.substring(mime.indexOf('/') + 1);
        return new ChatStore.Attachment(UUID.randomUUID().toString(), file.getCanonicalPath(), "synthetic-retention-" + type, mime, file.length());
    }
    private ChatStore.Attachment generatedImage(boolean jpeg) throws IOException {
        File file = newPrivate(jpeg ? ".jpg" : ".png");
        Bitmap bitmap = Bitmap.createBitmap(640, 360, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap); canvas.drawColor(Color.rgb(30, 80, 160));
        Paint paint = new Paint(); paint.setColor(Color.rgb(230, 90, 40)); canvas.drawRect(40, 40, 280, 320, paint);
        paint.setColor(Color.rgb(30, 210, 110)); canvas.drawCircle(450, 180, 120, paint);
        try (FileOutputStream output = new FileOutputStream(file)) {
            if (!bitmap.compress(jpeg ? Bitmap.CompressFormat.JPEG : Bitmap.CompressFormat.PNG, 90, output)) throw new IOException("Synthetic image encode failed");
            output.getFD().sync();
        } finally { bitmap.recycle(); }
        return attachment(file, jpeg ? "image/jpeg" : "image/png");
    }
    private static byte[] digest(File file) throws Exception {
        MessageDigest sha = MessageDigest.getInstance("SHA-256"); byte[] buffer = new byte[32768];
        try (InputStream input = new FileInputStream(file)) { int read; while ((read = input.read(buffer)) != -1) sha.update(buffer, 0, read); }
        return sha.digest();
    }
    private ChatStore.Attachment createWav() throws IOException {
        File file = newPrivate(".bin"); int samples = sampleRate * durationMs / 1000, bytes = samples * 2;
        ByteBuffer header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        header.put(new byte[]{'R','I','F','F'}).putInt(bytes+36).put(new byte[]{'W','A','V','E','f','m','t',' '})
                .putInt(16).putShort((short)1).putShort((short)1).putInt(sampleRate).putInt(sampleRate*2)
                .putShort((short)2).putShort((short)16).put(new byte[]{'d','a','t','a'}).putInt(bytes);
        try (OutputStream output = new BufferedOutputStream(new FileOutputStream(file))) {
            output.write(header.array());
            for (int i=0; i<samples; i++) { int value = sample(i); output.write(value & 255); output.write((value >> 8) & 255); }
        }
        return attachment(file, "audio/wav");
    }
    private short sample(int index) { return (short)(Math.sin(2*Math.PI*440*index/sampleRate) * 2000); }
    private ChatStore.Attachment createAac() throws IOException {
        File file = newPrivate(".m4a"); MediaCodec encoder = null; MediaMuxer muxer = null; boolean muxing = false;
        try {
            MediaFormat format = MediaFormat.createAudioFormat("audio/mp4a-latm", sampleRate, 1);
            format.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC);
            format.setInteger(MediaFormat.KEY_BIT_RATE, 64_000); format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 4096);
            encoder = MediaCodec.createEncoderByType("audio/mp4a-latm"); encoder.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE); encoder.start();
            muxer = new MediaMuxer(file.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            int written = 0, total = sampleRate * durationMs / 1000, track = -1; boolean inputDone = false, outputDone = false;
            long deadline = SystemClock.elapsedRealtime() + 15_000; MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputDone && SystemClock.elapsedRealtime() < deadline) {
                if (!inputDone) {
                    int index = encoder.dequeueInputBuffer(10_000);
                    if (index >= 0) {
                        ByteBuffer input = encoder.getInputBuffer(index); input.clear(); input.order(ByteOrder.LITTLE_ENDIAN);
                        int count = Math.min(input.remaining()/2, total-written), before = written;
                        for (int i=0; i<count; i++) input.putShort(sample(written++));
                        inputDone = written == total;
                        encoder.queueInputBuffer(index, 0, count*2, before*1_000_000L/sampleRate, inputDone ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0);
                    }
                }
                int index = encoder.dequeueOutputBuffer(info, 10_000);
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) { track = muxer.addTrack(encoder.getOutputFormat()); muxer.start(); muxing = true; }
                else if (index >= 0) {
                    ByteBuffer output = encoder.getOutputBuffer(index);
                    if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        if (!muxing) throw new IOException("Encoder output before format");
                        output.position(info.offset); output.limit(info.offset+info.size); muxer.writeSampleData(track, output, info);
                    }
                    outputDone = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0; encoder.releaseOutputBuffer(index, false);
                }
            }
            if (!outputDone) throw new IOException("Synthetic AAC encoding timed out");
        } finally {
            if (encoder != null) { try { encoder.stop(); } finally { encoder.release(); } }
            if (muxer != null) { try { if (muxing) muxer.stop(); } finally { muxer.release(); } }
        }
        return attachment(file, "audio/mp4");
    }

    private void enterDemoIfPresent() {
        ui(() -> {
            View entry = activity.getWindow().getDecorView().findViewWithTag("bchat-explore-demo");
            if (entry != null && !entry.performClick()) throw new AssertionError("Demo entry was not clickable");
        });
    }
}

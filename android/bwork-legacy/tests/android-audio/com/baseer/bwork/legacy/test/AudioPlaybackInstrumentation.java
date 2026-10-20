package com.baseer.bwork.legacy.test;

import android.app.*;
import android.content.*;
import android.media.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.baseer.bwork.legacy.ChatStore;
import com.baseer.bwork.legacy.PlaybackState;
import java.io.*;
import java.lang.reflect.*;
import java.nio.*;
import java.util.*;
import java.util.function.BooleanSupplier;

/** Device-only. Creates synthetic tones, never reads or records microphone audio. */
public final class AudioPlaybackInstrumentation extends Instrumentation {
    private Activity activity;
    private Object player, waves;
    private LinearLayout host;
    private final List<File> created = new ArrayList<>();
    private final List<String> results = new ArrayList<>();
    private Throwable uiFailure;
    private Class<?> targetClass, viewClass;
    private final int sampleRate = 44_100, durationMs = 4_000;

    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        Bundle out = new Bundle(); boolean passed = false;
        try { runChecks(); passed = true; }
        catch (Throwable failure) { out.putString("failure", failure.getClass().getSimpleName() + ": " + failure.getMessage()); }
        finally {
            if (activity != null) try { ui(() -> { if (player != null) invoke(player, "stop", new Class<?>[0]); activity.finish(); }); } catch (Throwable ignored) { }
            for (File file : created) if (file.exists()) file.delete();
        }
        out.putString("stream", "\n" + (passed ? "PASS " : "FAILED after ") + results.size() + " local audio checks\n"
                + String.join("\n", results) + "\n" + out.getString("failure", "") + "\n");
        finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, out);
    }
    private void ui(Runnable action) {
        uiFailure = null;
        runOnMainSync(() -> { try { action.run(); } catch (Throwable failure) { uiFailure = failure; } });
        if (uiFailure != null) throw new AssertionError("UI operation failed", uiFailure);
        waitForIdleSync();
    }
    private void check(boolean value, String label) {
        if (!value) throw new AssertionError(label);
        results.add("PASS " + label);
    }
    private static Object field(Object owner, String name) {
        try { Field field = owner.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(owner); }
        catch (ReflectiveOperationException failure) { throw new AssertionError("Missing field " + name, failure); }
    }
    private static Object invoke(Object owner, String method, Class<?>[] types, Object... args) {
        try { Method call = owner.getClass().getDeclaredMethod(method, types); call.setAccessible(true); return call.invoke(owner, args); }
        catch (ReflectiveOperationException failure) { throw new AssertionError("Operation failed " + method, failure); }
    }
    private PlaybackState state() { return (PlaybackState)field(player, "state"); }
    private boolean onUi(BooleanSupplier condition) { final boolean[] value = {false}; ui(() -> value[0] = condition.getAsBoolean()); return value[0]; }
    private void await(BooleanSupplier condition, long timeout, String label) {
        long end = SystemClock.elapsedRealtime() + timeout;
        while (SystemClock.elapsedRealtime() < end) {
            if (onUi(condition)) { check(true, label); return; }
            SystemClock.sleep(60);
        }
        final String[] codes = {""}; ui(() -> codes[0] = (String)invoke(player, "diagnosticSummary", new Class<?>[0]));
        throw new AssertionError(label + "; safe diagnostics: " + codes[0]);
    }
    private View voice(ChatStore.Attachment file, boolean compact) {
        try {
            Constructor<?> constructor = viewClass.getDeclaredConstructor(Context.class, ChatStore.Attachment.class,
                    player.getClass(), waves.getClass(), Runnable.class, boolean.class);
            constructor.setAccessible(true);
            return (View)constructor.newInstance(activity, file, player, waves, null, compact);
        } catch (ReflectiveOperationException failure) { throw new AssertionError("Voice view construction", failure); }
    }
    private void click(View voice) { ((View)field(voice, "play")).performClick(); }
    private void runChecks() throws Exception {
        Intent launch = new Intent(Intent.ACTION_MAIN).setComponent(new ComponentName("com.baseer.bchat.preview", "com.baseer.bwork.legacy.MainActivity"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity = startActivitySync(launch); waitForIdleSync();
        enterDemoIfPresent();
        player = field(activity, "audioPlayback"); waves = field(activity, "audioWaveforms");
        targetClass = Class.forName("com.baseer.bwork.legacy.AudioPlayback$Target", true, activity.getClassLoader());
        viewClass = Class.forName("com.baseer.bwork.legacy.VoicePlayerView", true, activity.getClassLoader());
        ui(() -> { host = new LinearLayout(activity); host.setOrientation(LinearLayout.VERTICAL); activity.setContentView(host); });
        ChatStore.Attachment wav = createWav();
        ChatStore.Attachment aac = createAac();
        check(new File(wav.path).isFile() && new File(aac.path).isFile(), "Synthetic WAV and AAC/M4A created inside private attachment storage");
        final View[] first = {null}, second = {null};
        ui(() -> { first[0] = voice(wav, false); second[0] = voice(aac, false); host.addView(first[0]); host.addView(second[0]); click(first[0]); });
        await(() -> state().phase() == PlaybackState.Phase.PLAYING && state().position() > 200, 8_000, "Private descriptor WAV prepares, starts and advances");
        final Object[] nativePlayer = {null}; final long[] token = {0};
        ui(() -> {
            nativePlayer[0] = field(player, "player"); token[0] = state().token();
            host.removeView(first[0]); first[0] = voice(wav, true); host.addView(first[0], 0);
            check(field(player, "player") == nativePlayer[0] && state().token() == token[0], "Compact reflow transfers same native player and generation");
        });
        await(() -> state().phase() == PlaybackState.Phase.PLAYING, 1_000, "Reattached control remains playing");
        ui(() -> click(first[0]));
        check(onUi(() -> state().phase() == PlaybackState.Phase.PAUSED), "Explicit pause reaches paused state");
        ui(() -> invoke(player, "seek", new Class<?>[]{targetClass, int.class}, first[0], 1_500));
        await(() -> state().phase() == PlaybackState.Phase.PAUSED && state().position() == 1_500
                && Math.abs(((MediaPlayer)field(player, "player")).getCurrentPosition() - 1_500) < 250, 2_000, "Paused seek changes actual decoder position without autoplay");
        ui(() -> click(first[0]));
        await(() -> state().phase() == PlaybackState.Phase.PLAYING && state().position() >= 1_500, 2_000, "Resume retains seek position");
        ui(() -> {
            invoke(player, "changeSpeed", new Class<?>[]{targetClass}, first[0]);
            check(state().phase() == PlaybackState.Phase.PLAYING && (state().speed() == 1f || state().speed() == 1.5f), "Speed applies or safely retains supported speed");
            invoke(player, "focusChanged", new Class<?>[]{long.class, int.class}, (long)field(player, "focusGeneration"), AudioManager.AUDIOFOCUS_LOSS_TRANSIENT);
            check(state().phase() == PlaybackState.Phase.PAUSED, "Injected transient focus loss pauses native playback");
        });
        SystemClock.sleep(250);
        check(onUi(() -> state().phase() == PlaybackState.Phase.PAUSED), "Focus loss does not auto-resume");
        ui(() -> click(second[0]));
        await(() -> aac.id.equals(state().clip()) && state().phase() == PlaybackState.Phase.PLAYING && state().position() > 150, 8_000, "Generated AAC/M4A prepares and advances after switching clips");
        check(onUi(() -> "▶".contentEquals(((TextView)field(first[0], "play")).getText())), "Switch resets previous view play control");
        ui(() -> {
            Object current = field(player, "player");
            invoke(player, "prepared", new Class<?>[]{MediaPlayer.class, long.class}, nativePlayer[0], token[0]);
            check(field(player, "player") == current && aac.id.equals(state().clip()), "Stale prepared callback cannot replace new clip");
            invoke(player, "seek", new Class<?>[]{targetClass, int.class}, second[0], Math.max(0, state().duration() - 250));
        });
        await(() -> state().phase() == PlaybackState.Phase.COMPLETE, 3_000, "Native completion reaches complete state");
        ui(() -> click(second[0]));
        await(() -> state().phase() == PlaybackState.Phase.PLAYING && state().position() < 2_000, 2_000, "Completed clip replays from the beginning");
        ui(() -> host.removeView(second[0]));
        await(() -> state().phase() == PlaybackState.Phase.IDLE && field(player, "player") == null, 2_000, "Unreplaced detach releases native player");
        ui(() -> { host.addView(second[0]); click(second[0]); click(second[0]); });
        SystemClock.sleep(400);
        check(onUi(() -> state().phase() == PlaybackState.Phase.IDLE && field(player, "player") == null), "Cancel during async prepare never restarts from stale callback");
        ui(() -> click(first[0]));
        await(() -> state().phase() == PlaybackState.Phase.PLAYING, 8_000, "Playback available after prepare cancellation");
        ui(() -> callActivityOnPause(activity));
        check(onUi(() -> state().phase() == PlaybackState.Phase.IDLE && field(player, "player") == null), "MainActivity.onPause releases foreground playback");
        ui(() -> callActivityOnResume(activity));
        testDraftAndSend(aac);
        ChatStore.Attachment wrongSize = new ChatStore.Attachment(wav.id, wav.path, wav.name, wav.mime, wav.size + 1);
        ui(() -> {
            invoke(player, "toggle", new Class<?>[]{ChatStore.Attachment.class, targetClass}, wrongSize, first[0]);
            String diagnostic = (String)invoke(player, "diagnosticSummary", new Class<?>[0]);
            check(state().phase() == PlaybackState.Phase.IDLE && diagnostic.contains("BP-SOURCE-IO"), "Source-integrity rejection has its own code and creates no native player");
        });
        ChatStore.Attachment corrupt = createInvalid();
        final View[] invalid = {null};
        ui(() -> { invalid[0] = voice(corrupt, false); host.addView(invalid[0]); click(invalid[0]); });
        await(() -> field(invalid[0], "playbackFailure") != null && state().phase() == PlaybackState.Phase.IDLE, 17_000, "Invalid bytes report bounded failure and release native player");
        ui(() -> {
            String diagnostic = (String)invoke(player, "diagnosticSummary", new Class<?>[0]);
            check(diagnostic.contains("BP-") && !diagnostic.contains("/data/") && !diagnostic.contains(corrupt.name), "Failure diagnostics include stage but no private file identity");
            click(first[0]);
        });
        await(() -> state().phase() == PlaybackState.Phase.PLAYING, 8_000, "Playable file succeeds after invalid-file failure");
    }
    private File newPrivate(String extension) throws IOException {
        File directory = new File(activity.getFilesDir(), "attachments");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Private test directory unavailable");
        File file = new File(directory, UUID.randomUUID().toString() + extension); created.add(file); return file;
    }
    private ChatStore.Attachment attachment(File file, String mime) throws IOException {
        return new ChatStore.Attachment(UUID.randomUUID().toString(), file.getCanonicalPath(), "synthetic-audio-test", mime, file.length());
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
    private ChatStore.Attachment createInvalid() throws IOException {
        File file = newPrivate(".bin"); try (FileOutputStream output = new FileOutputStream(file)) { output.write(new byte[]{1,2,3,4,5,6,7,8}); }
        return attachment(file, "audio/mp4");
    }
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
    private void testDraftAndSend(ChatStore.Attachment audio) throws IOException {
        File stateFile = new File(activity.getFilesDir(), "audio-regression-" + UUID.randomUUID() + ".bin"); created.add(stateFile); created.add(new File(stateFile.getPath() + ".bak")); created.add(new File(stateFile.getPath() + ".tmp"));
        ChatStore isolated = new ChatStore(stateFile);
        String company = isolated.companies().get(0).id, conversation = isolated.conversations(company).get(0).id;
        isolated.setDraft(company, conversation, "", Collections.singletonList(audio));
        isolated = new ChatStore(stateFile);
        check(isolated.draft(company, conversation).attachments.get(0).path.equals(audio.path), "Saved draft reload retains original private AAC source");
        ChatStore.Message sent = isolated.send(company, conversation);
        isolated = new ChatStore(stateFile);
        check(isolated.message(company, conversation, sent.id).attachments.get(0).path.equals(audio.path)
                && isolated.draft(company, conversation).attachments.isEmpty(), "Local send and reload preserve original audio attachment");
    }

    private void enterDemoIfPresent() {
        ui(() -> {
            View entry = activity.getWindow().getDecorView().findViewWithTag("bwork-explore-demo");
            if (entry != null && !entry.performClick()) throw new AssertionError("Demo entry was not clickable");
        });
    }
}

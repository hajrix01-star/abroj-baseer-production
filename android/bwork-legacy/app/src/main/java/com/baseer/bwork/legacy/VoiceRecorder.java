package com.baseer.bwork.legacy;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.MediaMetadataRetriever;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import java.io.File;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;

/**
 * One foreground, user-started recording at a time. The caller requests RECORD_AUDIO only
 * after a microphone tap, calls start only after grant, and MUST cancel on Activity.onPause.
 * This helper never requests permissions, starts a service, resumes recording, or sends a
 * message. A finished Attachment must be explicitly added to the caller's original draft.
 */
public final class VoiceRecorder {
    public static final int MAX_DURATION_MS = 120_000;
    public static final int MIN_DURATION_MS = 750;
    public static final int AUDIO_BIT_RATE = 64_000;
    public static final long MAX_RECORDING_BYTES = 2L * 1024L * 1024L;

    public interface Listener {
        /** The recorder has stopped. Call finish() once to claim the resulting attachment. */
        void onLimitReached();
        /** The recorder has stopped, released the microphone, and discarded its output. */
        void onError(String message);
    }

    private final Context application;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private MediaRecorder recorder;
    private File recordingFile;
    private String recordingId;
    private long startedAt;
    private long generation;
    private ChatStore.Attachment readyAttachment;
    private Runnable deadline;

    public VoiceRecorder(Context context, Listener listener) {
        if (context == null || context.getApplicationContext() == null || listener == null) {
            throw new IllegalArgumentException("Application context and listener are required");
        }
        this.application = context.getApplicationContext();
        this.listener = listener;
    }

    /** Explicit start only; denial is an error and never triggers another permission prompt. */
    public synchronized void start() throws IOException {
        if (recorder != null || readyAttachment != null) {
            throw new IOException("أنه التسجيل الحالي أو ألغِه أولًا");
        }
        if (application.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            throw new IOException("يلزم السماح بالميكروفون لبدء تسجيل صوتي");
        }
        final long token = ++generation;
        recordingId = UUID.randomUUID().toString();
        recordingFile = AttachmentSupport.createPrivateFile(application, recordingId, ".m4a");
        try {
            recorder = createRecorder(application);
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            recorder.setAudioChannels(1);
            recorder.setAudioSamplingRate(44_100);
            recorder.setAudioEncodingBitRate(AUDIO_BIT_RATE);
            recorder.setMaxDuration(MAX_DURATION_MS);
            recorder.setMaxFileSize(MAX_RECORDING_BYTES);
            recorder.setOutputFile(recordingFile.getAbsolutePath());
            recorder.setOnInfoListener((source, what, extra) -> {
                if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED
                        || what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_FILESIZE_REACHED) {
                    handleLimit(token, source, true);
                }
            });
            recorder.setOnErrorListener((source, what, extra) -> handleError(token, source));
            recorder.prepare();
            recorder.start();
            startedAt = SystemClock.elapsedRealtime();
            deadline = () -> handleLimit(token, null, false);
            main.postDelayed(deadline, MAX_DURATION_MS);
        } catch (IOException | RuntimeException failure) {
            discardLocked();
            throw new IOException("تعذّر بدء التسجيل. تأكد من إذن الميكروفون وتوفّره", failure);
        }
    }

    /** Stops and releases before returning. A returned file now belongs to the caller. */
    public synchronized ChatStore.Attachment finish() throws IOException {
        if (readyAttachment != null) {
            ChatStore.Attachment result = readyAttachment;
            readyAttachment = null;
            ++generation;
            return result;
        }
        if (recorder == null) throw new IOException("لا يوجد تسجيل صوتي جارٍ");
        ++generation;
        try {
            return finishLocked(false);
        } catch (IOException | RuntimeException failure) {
            discardLocked();
            if (failure instanceof IOException) throw (IOException) failure;
            throw new IOException("تعذّر حفظ التسجيل الصوتي؛ أعد المحاولة", failure);
        }
    }

    /** Idempotent; releases the microphone and deletes every unclaimed recording. */
    public synchronized void cancel() {
        ++generation;
        discardLocked();
    }

    public synchronized boolean isRecording() { return recorder != null; }

    public synchronized long elapsedMillis() {
        return recorder == null ? 0L : Math.min(MAX_DURATION_MS,
                Math.max(0L, SystemClock.elapsedRealtime() - startedAt));
    }

    /** Actual peak amplitude since the last poll, never a synthetic level. */
    public synchronized float amplitude() {
        if (recorder == null) return 0f;
        try { return Math.min(1f, recorder.getMaxAmplitude() / 32768f); }
        catch (RuntimeException unavailable) { return 0f; }
    }

    private void handleLimit(long token, MediaRecorder source, boolean nativeLimit) {
        String failure = null;
        synchronized (this) {
            if (token != generation || recorder == null || (source != null && source != recorder)) return;
            try {
                readyAttachment = finishLocked(nativeLimit);
            } catch (IOException | RuntimeException problem) {
                discardLocked();
                failure = "تعذّر حفظ التسجيل عند بلوغ الحد؛ أعد المحاولة";
            }
        }
        final String error = failure;
        main.post(() -> {
            synchronized (VoiceRecorder.this) {
                // A pause/cancel, manual finish, or a new session suppresses stale callbacks.
                if (generation != token) return;
                if (error == null && readyAttachment == null) return;
            }
            if (error == null) listener.onLimitReached();
            else listener.onError(error);
        });
    }

    private void handleError(long token, MediaRecorder source) {
        synchronized (this) {
            if (generation != token || recorder != source) return;
            discardLocked();
        }
        main.post(() -> {
            synchronized (VoiceRecorder.this) {
                if (generation != token) return;
            }
            listener.onError("توقف التسجيل بسبب خطأ في الميكروفون؛ لم يُحفظ المقطع");
        });
    }

    private ChatStore.Attachment finishLocked(boolean nativeLimit) throws IOException {
        removeDeadline();
        MediaRecorder current = recorder;
        File file = recordingFile;
        String id = recordingId;
        long elapsed = SystemClock.elapsedRealtime() - startedAt;
        RuntimeException stopFailure = null;
        try {
            detachListeners(current);
            current.stop();
        } catch (RuntimeException problem) {
            stopFailure = problem;
        } finally {
            release(current);
            recorder = null;
        }
        try {
            if (elapsed < MIN_DURATION_MS) throw new IOException("المقطع قصير جدًا؛ سجّل ثانية واحدة على الأقل");
            // A native maximum-duration event may arrive just after Android stopped itself.
            // That event or its concurrent duration deadline can recover a stop() error, but
            // only from a validated audio file after all recorder resources are released.
            if (stopFailure != null && !nativeLimit && elapsed < MAX_DURATION_MS) {
                throw new IOException("تعذّر إنهاء التسجيل الصوتي", stopFailure);
            }
            if (file == null || !file.isFile() || file.length() <= 0
                    || file.length() > MAX_RECORDING_BYTES) {
                throw new IOException("الملف الصوتي غير صالح");
            }
            validateAudio(file);
            String name = "voice-" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT)
                    .format(new Date()) + ".m4a";
            ChatStore.Attachment result = new ChatStore.Attachment(id,
                    file.getCanonicalPath(), name, "audio/mp4", file.length());
            recordingFile = null;
            recordingId = null;
            startedAt = 0;
            return result;
        } catch (IOException | RuntimeException failure) {
            AttachmentSupport.deleteIncomplete(file);
            recordingFile = null;
            recordingId = null;
            startedAt = 0;
            if (failure instanceof IOException) throw (IOException) failure;
            throw new IOException("الملف الصوتي غير صالح", failure);
        }
    }

    private static void validateAudio(File file) throws IOException {
        MediaMetadataRetriever metadata = new MediaMetadataRetriever();
        try {
            metadata.setDataSource(file.getAbsolutePath());
            String duration = metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
            String audio = metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO);
            long durationMs = duration == null ? 0 : Long.parseLong(duration);
            if (!"yes".equals(audio) || durationMs < MIN_DURATION_MS
                    || durationMs > MAX_DURATION_MS + 1500L) {
                throw new IOException("المقطع قصير جدًا أو غير صالح");
            }
        } catch (RuntimeException invalid) {
            throw new IOException("تعذّر قراءة التسجيل الصوتي", invalid);
        } finally {
            try { metadata.release(); } catch (IOException | RuntimeException ignored) { }
        }
    }

    private void discardLocked() {
        removeDeadline();
        if (recorder != null) {
            detachListeners(recorder);
            // reset() ends capture even if stop() would fail for an extremely short clip.
            try { recorder.reset(); } catch (RuntimeException ignored) { }
            release(recorder);
            recorder = null;
        }
        AttachmentSupport.deleteIncomplete(recordingFile);
        recordingFile = null;
        recordingId = null;
        startedAt = 0;
        if (readyAttachment != null) {
            AttachmentSupport.deleteIncomplete(new File(readyAttachment.path));
            readyAttachment = null;
        }
    }

    private void removeDeadline() {
        if (deadline != null) main.removeCallbacks(deadline);
        deadline = null;
    }

    private static void detachListeners(MediaRecorder value) {
        try { value.setOnInfoListener(null); } catch (RuntimeException ignored) { }
        try { value.setOnErrorListener(null); } catch (RuntimeException ignored) { }
    }

    private static void release(MediaRecorder value) {
        if (value != null) try { value.release(); } catch (RuntimeException ignored) { }
    }

    @SuppressWarnings("deprecation")
    private static MediaRecorder createRecorder(Context application) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) return new MediaRecorder(application);
        return new MediaRecorder();
    }
}

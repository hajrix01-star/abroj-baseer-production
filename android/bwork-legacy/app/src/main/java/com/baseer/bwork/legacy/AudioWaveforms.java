package com.baseer.bwork.legacy;

import android.content.Context;
import android.media.*;
import android.os.*;
import java.io.*;
import java.nio.*;
import java.util.*;
import java.util.concurrent.*;

/** Read-only, bounded, local PCM analysis. Unsupported/long clips retain a plain seek bar. */
final class AudioWaveforms {
    static final class Result {
        final int duration; final float[] peaks; final boolean busy;
        Result(int duration, float[] peaks) { this(duration, peaks, false); }
        Result(int duration, float[] peaks, boolean busy) { this.duration = duration; this.peaks = peaks; this.busy = busy; }
    }
    interface Ready { void show(Result result); }
    interface Request { void cancel(); }
    private static final Request COMPLETE = () -> { };
    private static final class Job {
        final List<Ready> listeners = new ArrayList<>();
        Future<?> task;
    }
    private final Context context;
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<>(8));
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Map<String, Result> cache = new LinkedHashMap<String, Result>(32, .75f, true) {
        protected boolean removeEldestEntry(Map.Entry<String, Result> entry) { return size() > 32; }
    };
    private final Map<String, Job> pending = new HashMap<>();
    private boolean closed;
    AudioWaveforms(Context context) { this.context = context.getApplicationContext(); }
    Request load(ChatStore.Attachment file, Ready callback) {
        File source;
        try { source = AttachmentSupport.requirePrivateFile(context, file); }
        catch (IOException | RuntimeException unavailable) {
            callback.show(new Result(0, null));
            return COMPLETE;
        }
        return load(source, file.id + ":" + file.size, callback);
    }
    /** Connected-chat audio is already checksum-verified in private cache before decoding. */
    Request load(File source, String contentKey, Ready callback) {
        if (closed) return COMPLETE;
        String key = contentKey;
        Result saved = cache.get(key); if (saved != null) { callback.show(saved); return COMPLETE; }
        Job existing = pending.get(key);
        if (existing != null) {
            if (existing.listeners.size() >= 32) { callback.show(new Result(0, null, true)); return COMPLETE; }
            existing.listeners.add(callback); return () -> cancel(key, existing, callback);
        }
        if (pending.size() >= 8) { callback.show(new Result(0, null, true)); return COMPLETE; }
        Job job = new Job(); job.listeners.add(callback); pending.put(key, job);
        try {
            job.task = worker.submit(() -> {
                Result result;
                try { result = decode(source); }
                catch (IOException | RuntimeException unsupported) { result = new Result(0, null); }
                Result ready = result;
                main.post(() -> {
                    // A canceled job may finish after a new request for the same attachment.
                    if (closed || pending.get(key) != job) return;
                    pending.remove(key); cache.put(key, ready);
                    for (Ready listener : new ArrayList<>(job.listeners)) listener.show(ready);
                    job.listeners.clear();
                });
            });
        } catch (RejectedExecutionException unavailable) {
            pending.remove(key); job.listeners.clear(); callback.show(new Result(0, null, true)); return COMPLETE;
        }
        return () -> cancel(key, job, callback);
    }
    private void cancel(String key, Job job, Ready callback) {
        job.listeners.remove(callback);
        if (!job.listeners.isEmpty() || pending.get(key) != job) return;
        pending.remove(key);
        if (job.task != null) { job.task.cancel(true); if (job.task instanceof Runnable) worker.remove((Runnable)job.task); }
    }
    void close() {
        closed = true;
        for (Job job : pending.values()) { job.listeners.clear(); if (job.task != null) job.task.cancel(true); }
        pending.clear(); cache.clear(); worker.shutdownNow();
    }
    private static Result decode(File source) throws IOException {
        MediaExtractor extractor = new MediaExtractor(); MediaCodec decoder = null;
        int duration = 0;
        try {
            try (FileInputStream inputFile = new FileInputStream(source)) {
                extractor.setDataSource(inputFile.getFD(), 0, source.length());
            }
            MediaFormat input = null;
            for (int i = 0; i < extractor.getTrackCount(); i++) {
                MediaFormat candidate = extractor.getTrackFormat(i);
                String mime = candidate.getString(MediaFormat.KEY_MIME);
                if (mime != null && mime.startsWith("audio/")) { input = candidate; extractor.selectTrack(i); break; }
            }
            if (input == null || !input.containsKey(MediaFormat.KEY_DURATION)) return new Result(0, null);
            long durationUs = input.getLong(MediaFormat.KEY_DURATION);
            duration = (int)Math.min(Integer.MAX_VALUE, durationUs / 1000);
            // Decode bounded media only. Do not present a partial waveform as the whole clip.
            if (duration <= 0 || duration > 600_000) return new Result(duration, null);
            decoder = MediaCodec.createDecoderByType(input.getString(MediaFormat.KEY_MIME));
            decoder.configure(input, null, null, 0); decoder.start();
            WaveformSamples samples = new WaveformSamples(72, durationUs);
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            boolean inputDone = false, outputDone = false;
            int sampleRate = input.getInteger(MediaFormat.KEY_SAMPLE_RATE);
            int channels = input.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
            int encoding = AudioFormat.ENCODING_PCM_16BIT;
            long deadline = SystemClock.elapsedRealtime() + 20_000;
            while (!outputDone) {
                if (Thread.currentThread().isInterrupted() || SystemClock.elapsedRealtime() > deadline) return new Result(duration, null);
                if (!inputDone) {
                    int index = decoder.dequeueInputBuffer(5000);
                    if (index >= 0) {
                        ByteBuffer data = decoder.getInputBuffer(index);
                        if (data == null) throw new IOException("Missing decoder input");
                        data.clear(); int size = extractor.readSampleData(data, 0);
                        if (size < 0) { decoder.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputDone = true; }
                        else { decoder.queueInputBuffer(index, 0, size, extractor.getSampleTime(), 0); extractor.advance(); }
                    }
                }
                int index = decoder.dequeueOutputBuffer(info, 5000);
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat output = decoder.getOutputFormat();
                    sampleRate = output.getInteger(MediaFormat.KEY_SAMPLE_RATE); channels = output.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    encoding = output.containsKey(MediaFormat.KEY_PCM_ENCODING) ? output.getInteger(MediaFormat.KEY_PCM_ENCODING) : AudioFormat.ENCODING_PCM_16BIT;
                    if (sampleRate <= 0 || channels <= 0 || (encoding != AudioFormat.ENCODING_PCM_16BIT && encoding != AudioFormat.ENCODING_PCM_FLOAT)) return new Result(duration, null);
                } else if (index >= 0) {
                    ByteBuffer pcm = decoder.getOutputBuffer(index);
                    if (pcm != null && info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        pcm.position(info.offset); pcm.limit(info.offset + info.size); pcm.order(ByteOrder.nativeOrder());
                        int bytes = encoding == AudioFormat.ENCODING_PCM_FLOAT ? 4 : 2; long count = 0;
                        while (pcm.remaining() >= bytes) {
                            float amplitude = encoding == AudioFormat.ENCODING_PCM_FLOAT ? pcm.getFloat() : pcm.getShort() / 32768f;
                            samples.add(info.presentationTimeUs + (count / channels) * 1_000_000L / sampleRate, amplitude); count++;
                        }
                    }
                    outputDone = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    decoder.releaseOutputBuffer(index, false);
                }
            }
            return new Result(duration, samples.hasSamples() ? samples.peaks() : null);
        } catch (IOException | RuntimeException unsupported) { return new Result(duration, null); }
        finally {
            if (decoder != null) { try { decoder.stop(); } catch (RuntimeException ignored) { } try { decoder.release(); } catch (RuntimeException ignored) { } }
            try { extractor.release(); } catch (RuntimeException ignored) { }
        }
    }
}

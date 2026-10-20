package com.baseer.bwork.feedback;

import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.net.Uri;
import android.os.SystemClock;
import com.facebook.react.bridge.Arguments;
import com.facebook.react.bridge.LifecycleEventListener;
import com.facebook.react.bridge.Promise;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.bridge.ReactContextBaseJavaModule;
import com.facebook.react.bridge.ReactMethod;
import com.facebook.react.bridge.WritableArray;
import com.facebook.react.bridge.WritableMap;
import com.facebook.react.common.LifecycleState;
import java.io.File;
import java.nio.ByteBuffer;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Private-file-only, bounded/off-main-thread analysis; no network or stored waveform. */
public final class BWorkWaveformModule extends ReactContextBaseJavaModule implements LifecycleEventListener {
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(2));
    private final ConcurrentHashMap<String, Job> jobs = new ConcurrentHashMap<>();
    private volatile boolean dead;
    private final class Job implements Runnable {
        final String id, uri; final Promise promise; final AtomicBoolean cancelled = new AtomicBoolean();
        Job(String id, String uri, Promise promise) { this.id = id; this.uri = uri; this.promise = promise; }
        void check(long deadline) {
            if (dead || cancelled.get() || getReactApplicationContext().getLifecycleState() != LifecycleState.RESUMED) throw new IllegalStateException("cancelled");
            if (SystemClock.elapsedRealtime() > deadline) throw new IllegalStateException("analysis_timeout");
        }
        @Override public void run() {
            MediaExtractor extractor = null; MediaCodec codec = null;
            try {
                final long deadline = SystemClock.elapsedRealtime() + 15000;
                check(deadline);
                Uri parsed = Uri.parse(uri);
                if (!"file".equals(parsed.getScheme()) || parsed.getQuery() != null || parsed.getFragment() != null || parsed.getAuthority() != null && !parsed.getAuthority().isEmpty()) throw new IllegalArgumentException("private_file_required");
                final File root = new File(getReactApplicationContext().getFilesDir(), "__BWORK_MEDIA_DIRECTORY__").getCanonicalFile();
                final File file = new File(parsed.getPath()).getCanonicalFile();
                if (!file.getPath().startsWith(root.getPath() + File.separator) || !file.isFile() || !file.getName().matches("media-[1-9][0-9]*\\.m4a") || file.length() <= 0 || file.length() > 10 * 1024 * 1024) throw new IllegalArgumentException("private_file_required");
                extractor = new MediaExtractor(); extractor.setDataSource(file.getPath());
                MediaFormat format = null;
                for (int i = 0; i < extractor.getTrackCount(); i++) {
                    MediaFormat candidate = extractor.getTrackFormat(i);
                    if (candidate.getString(MediaFormat.KEY_MIME).startsWith("audio/")) { format = candidate; extractor.selectTrack(i); break; }
                }
                if (format == null || !format.containsKey(MediaFormat.KEY_DURATION)) throw new IllegalArgumentException("audio_missing");
                long durationUs = format.getLong(MediaFormat.KEY_DURATION);
                PeakEnvelope envelope = new PeakEnvelope(durationUs);
                int rate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE), channels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT), encoding = 2;
                codec = MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME));
                codec.configure(format, null, null, 0); codec.start();
                boolean inputDone = false, outputDone = false;
                MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
                while (!outputDone) {
                    check(deadline);
                    if (!inputDone) {
                        int input = codec.dequeueInputBuffer(10000);
                        if (input >= 0) {
                            ByteBuffer buffer = codec.getInputBuffer(input);
                            if (buffer == null) throw new IllegalStateException("decoder_input");
                            int size = extractor.readSampleData(buffer, 0);
                            if (size < 0) { codec.queueInputBuffer(input, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputDone = true; }
                            else { codec.queueInputBuffer(input, 0, size, extractor.getSampleTime(), 0); extractor.advance(); }
                        }
                    }
                    int output = codec.dequeueOutputBuffer(info, 10000);
                    if (output == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                        MediaFormat decoded = codec.getOutputFormat();
                        rate = decoded.getInteger(MediaFormat.KEY_SAMPLE_RATE); channels = decoded.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                        encoding = decoded.containsKey(MediaFormat.KEY_PCM_ENCODING) ? decoded.getInteger(MediaFormat.KEY_PCM_ENCODING) : 2;
                    } else if (output >= 0) {
                        try {
                            if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                                ByteBuffer buffer = codec.getOutputBuffer(output);
                                if (buffer == null || info.offset < 0 || info.size < 0 || info.offset + (long) info.size > buffer.capacity()) throw new IllegalStateException("decoder_output");
                                buffer.position(info.offset); buffer.limit(info.offset + info.size);
                                envelope.accept(buffer.slice(), info.presentationTimeUs, rate, channels, encoding);
                            }
                        } finally { codec.releaseOutputBuffer(output, false); }
                        outputDone = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    }
                }
                check(deadline);
                WritableArray peaks = Arguments.createArray(); for (double peak : envelope.finish()) peaks.pushDouble(peak);
                WritableMap result = Arguments.createMap(); result.putDouble("durationMs", durationUs / 1000.0); result.putArray("peaks", peaks);
                promise.resolve(result);
            } catch (Exception unavailable) { promise.reject("waveform_unavailable", "Local audio analysis unavailable"); }
            finally {
                if (codec != null) { try { codec.stop(); } catch (RuntimeException ignored) {} try { codec.release(); } catch (RuntimeException ignored) {} }
                if (extractor != null) { try { extractor.release(); } catch (RuntimeException ignored) {} } jobs.remove(id, this);
            }
        }
    }
    public BWorkWaveformModule(ReactApplicationContext context) { super(context); context.addLifecycleEventListener(this); }
    @Override public String getName() { return "BWorkWaveform"; }
    @ReactMethod public synchronized void analyze(String uri, String id, Promise promise) {
        if (dead || uri == null || uri.length() > 1024 || id == null || !id.matches("[A-Za-z0-9-]{1,96}") || jobs.size() >= 3) { promise.reject("waveform_unavailable", "Analysis busy"); return; }
        Job job = new Job(id, uri, promise);
        if (jobs.putIfAbsent(id, job) != null) { promise.reject("waveform_unavailable", "Duplicate analysis"); return; }
        try { worker.execute(job); } catch (RuntimeException busy) { jobs.remove(id, job); promise.reject("waveform_unavailable", "Analysis busy"); }
    }
    @ReactMethod public void cancel(String id) {
        if (id == null) return;
        Job job = jobs.get(id); if (job == null) return; job.cancelled.set(true);
        if (worker.remove(job)) { jobs.remove(id, job); job.promise.reject("waveform_unavailable", "Analysis cancelled"); }
    }
    private void cancelAll() { for (String id : jobs.keySet()) cancel(id); }
    @Override public void onHostResume() {}
    @Override public void onHostPause() { cancelAll(); }
    @Override public void onHostDestroy() { cancelAll(); }
    @Override public void invalidate() { dead = true; cancelAll(); worker.shutdownNow(); getReactApplicationContext().removeLifecycleEventListener(this); super.invalidate(); }
}

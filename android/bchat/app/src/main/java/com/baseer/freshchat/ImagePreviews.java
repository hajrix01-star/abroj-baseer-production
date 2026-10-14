package com.baseer.freshchat;

import android.content.Context;
import android.graphics.*;
import android.media.ExifInterface;
import android.os.*;
import android.util.LruCache;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;

/** Bounded, read-only native image decoding. All file access and decoding runs off the UI thread. */
final class ImagePreviews {
    static final int MAX_PENDING = 32;
    static final int CACHE_BYTES = 16 * 1024 * 1024;
    static final int MAX_BITMAP_BYTES = 8 * 1024 * 1024;
    static final class Result {
        final Bitmap bitmap;
        final boolean busy;
        final boolean sourceMissing;
        Result(Bitmap bitmap, boolean busy) { this(bitmap, busy, false); }
        Result(Bitmap bitmap, boolean busy, boolean sourceMissing) {
            this.bitmap = bitmap; this.busy = busy; this.sourceMissing = sourceMissing;
        }
    }
    interface Ready { void show(Result result); }
    static final class SourceInfo {
        final int width, height, orientation, displayWidth, displayHeight;
        SourceInfo(int width, int height, int orientation) {
            this.width = width; this.height = height; this.orientation = orientation;
            boolean swapped = orientation >= ExifInterface.ORIENTATION_TRANSPOSE && orientation <= ExifInterface.ORIENTATION_ROTATE_270;
            displayWidth = swapped ? height : width; displayHeight = swapped ? width : height;
        }
        Matrix orientationMatrix() {
            Matrix matrix = new Matrix();
            switch (orientation) {
                case ExifInterface.ORIENTATION_FLIP_HORIZONTAL: matrix.setScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_180: matrix.setRotate(180); break;
                case ExifInterface.ORIENTATION_FLIP_VERTICAL: matrix.setScale(1, -1); break;
                case ExifInterface.ORIENTATION_TRANSPOSE: matrix.setRotate(90); matrix.postScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_90: matrix.setRotate(90); break;
                case ExifInterface.ORIENTATION_TRANSVERSE: matrix.setRotate(-90); matrix.postScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_270: matrix.setRotate(-90); break;
                default: break;
            }
            RectF bounds = new RectF(0, 0, width, height); matrix.mapRect(bounds);
            matrix.postTranslate(-bounds.left, -bounds.top); return matrix;
        }
    }
    static final class DetailResult {
        final SourceInfo info; final Bitmap bitmap; final Rect region; final boolean busy;
        DetailResult(SourceInfo info, Bitmap bitmap, Rect region, boolean busy) {
            this.info = info; this.bitmap = bitmap; this.region = region; this.busy = busy;
        }
    }
    interface DetailReady { void show(DetailResult result); }
    private static final class DetailJob { Future<?> task; boolean cancelled; }
    private final Set<DetailJob> detailPending = new HashSet<>();
    interface Request { void cancel(); }
    private static final Request COMPLETE = () -> { };
    private static final class Job {
        final ArrayList<Ready> listeners = new ArrayList<>();
        Future<?> task;
    }
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
            new ArrayBlockingQueue<>(MAX_PENDING));
    private final Map<String, Job> pending = new HashMap<>();
    private final LruCache<String, Result> cache = new LruCache<String, Result>(CACHE_BYTES) {
        @Override protected int sizeOf(String key, Result result) {
            // Include a minimum entry cost so unsupported/corrupt files cannot grow a vast negative cache.
            return 4096 + (result.bitmap == null ? 0 : result.bitmap.getAllocationByteCount());
        }
    };
    private volatile boolean closed;

    ImagePreviews(Context context) { this.context = context.getApplicationContext(); }

    /** Called on the main thread; callbacks run there too. Cache entries never own/recycle displayed pixels. */
    Request load(ChatStore.Attachment file, int maxEdge, Ready callback) {
        if (closed) { callback.show(new Result(null, false)); return COMPLETE; }
        if (file == null || !file.mime.startsWith("image/")) { callback.show(new Result(null, false)); return COMPLETE; }
        int target = ImagePreviewPolicy.checkedTarget(maxEdge);
        String key = file.id + ":" + file.path + ":" + file.size + ":" + file.mime + ":" + target;
        Result saved = cache.get(key);
        if (saved != null) { callback.show(saved); return COMPLETE; }
        Job existing = pending.get(key);
        if (existing != null) {
            if (existing.listeners.size() >= MAX_PENDING) { callback.show(new Result(null, true)); return COMPLETE; }
            existing.listeners.add(callback); return () -> cancel(key, existing, callback);
        }
        if (pending.size() + detailPending.size() >= MAX_PENDING) { callback.show(new Result(null, true)); return COMPLETE; }
        Job job = new Job(); job.listeners.add(callback); pending.put(key, job);
        try {
            job.task = worker.submit(() -> {
                Bitmap bitmap = null;
                boolean sourceMissing = false;
                try {
                    if (!closed && !Thread.currentThread().isInterrupted()) bitmap = decode(context, file, target);
                } catch (AttachmentSupport.SourceUnavailableException unavailable) {
                    sourceMissing = unavailable.reason == AttachmentSupport.SourceUnavailableException.Reason.MISSING;
                } catch (IOException | RuntimeException | OutOfMemoryError unavailable) { /* No claim that missing bytes still exist. */ }
                Result ready = new Result(bitmap, false, sourceMissing);
                main.post(() -> {
                    // A detached/rebound request can finish after a newer generation for this same file.
                    if (closed || pending.get(key) != job) {
                        if (ready.bitmap != null) ready.bitmap.recycle();
                        return;
                    }
                    pending.remove(key); cache.put(key, ready);
                    for (Ready listener : new ArrayList<>(job.listeners)) listener.show(ready);
                    job.listeners.clear();
                });
            });
        } catch (RejectedExecutionException unavailable) {
            pending.remove(key); job.listeners.clear(); callback.show(new Result(null, true)); return COMPLETE;
        }
        return () -> cancel(key, job, callback);
    }

    private void cancel(String key, Job job, Ready callback) {
        job.listeners.remove(callback);
        if (!job.listeners.isEmpty() || pending.get(key) != job) return;
        pending.remove(key);
        if (job.task != null) {
            job.task.cancel(true);
            if (job.task instanceof Runnable) worker.remove((Runnable)job.task);
        }
    }

    void close() {
        closed = true;
        for (DetailJob job : detailPending) { job.cancelled = true; if (job.task != null) job.task.cancel(true); }
        detailPending.clear();
        for (Job job : pending.values()) { job.listeners.clear(); if (job.task != null) job.task.cancel(true); }
        pending.clear(); cache.evictAll(); worker.shutdownNow();
    }

    /** One bounded original-resolution viewport tile per inspector; no retained native decoder. */
    Request loadDetail(ChatStore.Attachment file, Rect region, int sample, DetailReady callback) {
        if (closed) { callback.show(new DetailResult(null, null, null, false)); return COMPLETE; }
        if (pending.size() + detailPending.size() >= MAX_PENDING) {
            callback.show(new DetailResult(null, null, null, true)); return COMPLETE;
        }
        DetailJob job = new DetailJob(); detailPending.add(job);
        final Rect requested = region == null ? null : new Rect(region);
        try {
            job.task = worker.submit(() -> {
                DetailResult result;
                try { result = decodeDetail(context, file, requested, sample); }
                catch (IOException | RuntimeException | OutOfMemoryError unsupported) { result = new DetailResult(null, null, null, false); }
                final DetailResult ready = result;
                main.post(() -> {
                    detailPending.remove(job);
                    if (closed || job.cancelled) { if (ready.bitmap != null) ready.bitmap.recycle(); return; }
                    callback.show(ready);
                });
            });
        } catch (RejectedExecutionException busy) {
            detailPending.remove(job); callback.show(new DetailResult(null, null, null, true)); return COMPLETE;
        }
        return () -> {
            job.cancelled = true; detailPending.remove(job);
            if (job.task != null) { job.task.cancel(true); if (job.task instanceof Runnable) worker.remove((Runnable)job.task); }
        };
    }

    static DetailResult decodeDetail(Context context, ChatStore.Attachment file, Rect region, int sample) throws IOException {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Detail decode must run off main");
        if (file == null || !file.mime.startsWith("image/") || Thread.currentThread().isInterrupted()) throw new IOException("Cancelled detail preview");
        File source = AttachmentSupport.requirePrivateFile(context, file);
        BitmapFactory.Options bounds = new BitmapFactory.Options(); bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(source.getPath(), bounds);
        if (!ImagePreviewPolicy.validSource(bounds.outWidth, bounds.outHeight)) throw new IOException("Invalid image bounds");
        int orientation = ExifInterface.ORIENTATION_NORMAL;
        try { orientation = new ExifInterface(source.getPath()).getAttributeInt(ExifInterface.TAG_ORIENTATION, orientation); }
        catch (IOException unsupportedExif) { /* The raster may have no EXIF metadata. */ }
        SourceInfo info = new SourceInfo(bounds.outWidth, bounds.outHeight, orientation);
        if (region == null) return new DetailResult(info, null, null, false);
        if (region.isEmpty() || region.left < 0 || region.top < 0 || region.right > info.width || region.bottom > info.height)
            throw new IOException("Invalid detail region");
        int minimumSample = ImagePreviewPolicy.sampleSize(region.width(), region.height(), ImagePreviewPolicy.MAX_EDGE);
        int requestedSample = Integer.highestOneBit(Math.max(1, Math.min(sample, 131072)));
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = Math.max(minimumSample, requestedSample);
        options.inScaled = false; options.inPreferredConfig = Bitmap.Config.ARGB_8888;
        BitmapRegionDecoder decoder = null;
        try {
            if (Thread.currentThread().isInterrupted()) throw new IOException("Cancelled detail preview");
            decoder = BitmapRegionDecoder.newInstance(source.getPath(), false);
            if (decoder == null) throw new IOException("Detail codec unavailable");
            Bitmap bitmap = decoder.decodeRegion(region, options);
            if (bitmap == null) throw new IOException("Detail codec unavailable");
            if (bitmap.getWidth() > ImagePreviewPolicy.MAX_EDGE || bitmap.getHeight() > ImagePreviewPolicy.MAX_EDGE
                    || bitmap.getAllocationByteCount() > MAX_BITMAP_BYTES || Thread.currentThread().isInterrupted()) {
                bitmap.recycle(); throw new IOException("Detail exceeds limits or cancelled");
            }
            return new DetailResult(info, bitmap, new Rect(region), false);
        } finally { if (decoder != null) decoder.recycle(); }
    }

    static Bitmap decode(Context context, ChatStore.Attachment attachment, int maxEdge) throws IOException {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Decode must run off the UI thread");
        if (attachment == null || !attachment.mime.startsWith("image/")) throw new IOException("Not an image attachment");
        File file = AttachmentSupport.requirePrivateFile(context, attachment);
        if (file.length() < 1 || Thread.currentThread().isInterrupted()) throw new IOException("Empty or cancelled preview");
        int target = ImagePreviewPolicy.checkedTarget(maxEdge);
        Bitmap bitmap = Build.VERSION.SDK_INT >= 28 ? Modern.decode(file, target) : decodeLegacy(file, target);
        if (bitmap == null) throw new IOException("Image codec unavailable");
        if (bitmap.getWidth() > target || bitmap.getHeight() > target
                || bitmap.getAllocationByteCount() > MAX_BITMAP_BYTES || Thread.currentThread().isInterrupted()) {
            bitmap.recycle(); throw new IOException("Preview exceeds limits or was cancelled");
        }
        return bitmap;
    }

    /** API 28 native decoder honors orientation and the device's actual HEIF/HEIC codec support. */
    private static final class Modern {
        @android.annotation.TargetApi(28)
        static Bitmap decode(File file, int target) throws IOException {
            return ImageDecoder.decodeBitmap(ImageDecoder.createSource(file), (decoder, info, source) -> {
                int[] size = ImagePreviewPolicy.fit(info.getSize().getWidth(), info.getSize().getHeight(), target);
                decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE);
                decoder.setTargetColorSpace(ColorSpace.get(ColorSpace.Named.SRGB));
                decoder.setTargetSize(size[0], size[1]);
                decoder.setOnPartialImageListener(error -> false);
            });
        }
    }

    /** API 26/27 fallback: header bounds first, sampled allocation, then EXIF on sampled pixels only. */
    static Bitmap decodeLegacy(File file, int target) throws IOException {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Decode must run off the UI thread");
        BitmapFactory.Options options = new BitmapFactory.Options(); options.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(file.getPath(), options);
        options.inSampleSize = ImagePreviewPolicy.sampleSize(options.outWidth, options.outHeight, target);
        options.inJustDecodeBounds = false; options.inScaled = false; options.inPreferredConfig = Bitmap.Config.ARGB_8888;
        Bitmap bitmap = BitmapFactory.decodeFile(file.getPath(), options);
        if (bitmap == null) throw new IOException("Image codec unavailable");
        try {
            int orientation = ExifInterface.ORIENTATION_NORMAL;
            try { orientation = new ExifInterface(file.getPath()).getAttributeInt(ExifInterface.TAG_ORIENTATION, orientation); }
            catch (IOException unsupportedExif) { /* Some otherwise supported formats have no EXIF reader. */ }
            Matrix matrix = new Matrix();
            switch (orientation) {
                case ExifInterface.ORIENTATION_FLIP_HORIZONTAL: matrix.setScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_180: matrix.setRotate(180); break;
                case ExifInterface.ORIENTATION_FLIP_VERTICAL: matrix.setScale(1, -1); break;
                case ExifInterface.ORIENTATION_TRANSPOSE: matrix.setRotate(90); matrix.postScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_90: matrix.setRotate(90); break;
                case ExifInterface.ORIENTATION_TRANSVERSE: matrix.setRotate(-90); matrix.postScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_270: matrix.setRotate(-90); break;
                default: break;
            }
            if (!matrix.isIdentity()) {
                Bitmap oriented = Bitmap.createBitmap(bitmap, 0, 0, bitmap.getWidth(), bitmap.getHeight(), matrix, true);
                if (oriented != bitmap) bitmap.recycle();
                bitmap = oriented;
            }
            return bitmap;
        } catch (RuntimeException | OutOfMemoryError failure) { bitmap.recycle(); throw failure; }
    }
}

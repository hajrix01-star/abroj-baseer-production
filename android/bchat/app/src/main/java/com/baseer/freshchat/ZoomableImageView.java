package com.baseer.freshchat;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.GestureDetector;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.widget.ImageView;
import java.io.File;
import java.util.function.BooleanSupplier;

/** A single-image, bounded viewer. The caller owns the bitmap and its lifetime. */
final class ZoomableImageView extends ImageView {
    private static final float MAX_ZOOM = 6f;
    private final Matrix display = new Matrix();
    private final Matrix inverse = new Matrix();
    // View-owned scratch transforms: drawing must not allocate per frame.
    private final Matrix detailOrientation = new Matrix();
    private final Matrix sourceTransform = new Matrix();
    private final Matrix tileTransform = new Matrix();
    private final RectF bounds = new RectF();
    private final float[] point = new float[2];
    private final ScaleGestureDetector pinch;
    private final GestureDetector gestures;
    private Bitmap bitmap;
    private float zoom = 1f;
    private float degrees;
    private float centerX;
    private float centerY;
    private float lastX;
    private float lastY;
    private float lastAngle;
    private boolean tracking;
    private boolean rotating;
    private ImagePreviews details;
    private File detailFile;
    private BooleanSupplier originalAllowed;
    private ImagePreviews.SourceInfo detailInfo;
    private ImagePreviews.Request detailRequest;
    private Bitmap detailBitmap;
    private Rect detailRegion;
    private int detailSample;
    private long detailGeneration;
    private boolean detailInFlight, overviewSuppressed;
    private final Paint detailPaint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Runnable detailRefresh = this::refreshDetail;

    ZoomableImageView(Context context) { this(context, null); }

    ZoomableImageView(Context context, AttributeSet attributes) {
        super(context, attributes);
        setScaleType(ScaleType.MATRIX);
        pinch = new ScaleGestureDetector(context, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override public boolean onScale(ScaleGestureDetector detector) {
                zoomBy(detector.getScaleFactor(), detector.getFocusX(), detector.getFocusY());
                return true;
            }
        });
        gestures = new GestureDetector(context, new GestureDetector.SimpleOnGestureListener() {
            @Override public boolean onDown(MotionEvent event) { return true; }
            @Override public boolean onDoubleTap(MotionEvent event) { resetToFit(); return true; }
            @Override public boolean onSingleTapUp(MotionEvent event) { performClick(); return true; }
        });
    }

    @Override public void setImageBitmap(Bitmap value) {
        clearDetailSource();
        originalAllowed = null;
        overviewSuppressed = false;
        bitmap = value;
        super.setImageBitmap(value);
        resetToFit();
    }

    /** Optional original-resolution tiles. The overview remains bounded and caller-owned. */
    void setConnectedDetailSource(ImagePreviews decoder, File source, BooleanSupplier currentDownloadRights) {
        clearDetailSource();
        if (decoder == null || source == null || currentDownloadRights == null)
            throw new IllegalArgumentException("Authorized detail source required");
        details = decoder; detailFile = source; originalAllowed = currentDownloadRights;
        overviewSuppressed = !currentDownloadRights.getAsBoolean();
        scheduleDetail();
    }

    void clearDetailSource() {
        ++detailGeneration;
        removeCallbacks(detailRefresh);
        if (detailRequest != null) detailRequest.cancel();
        detailRequest = null; detailInFlight = false;
        // The original bitmap may survive detach. Its account/right fence must survive too.
        details = null; detailFile = null; detailInfo = null;
        clearTile();
    }

    private void clearTile() {
        Bitmap old = detailBitmap; detailBitmap = null; detailRegion = null; detailSample = 0;
        if (old != null) old.recycle();
        invalidate();
    }

    private boolean canShowDetail() {
        return details != null && detailFile != null && originalAllowed != null && originalAllowed.getAsBoolean();
    }

    private void scheduleDetail() {
        removeCallbacks(detailRefresh);
        if (details != null && isAttachedToWindow()) postDelayed(detailRefresh, 90);
    }

    private Matrix sourceToView() {
        sourceTransform.set(detailOrientation);
        sourceTransform.postScale(bitmap.getWidth() / (float)detailInfo.displayWidth,
                bitmap.getHeight() / (float)detailInfo.displayHeight);
        sourceTransform.postConcat(display);
        return sourceTransform;
    }

    private void refreshDetail() {
        if (!canShowDetail() || bitmap == null || !isAttachedToWindow()) { clearTile(); return; }
        if (detailInfo == null) {
            if (detailInFlight) return;
            long generation = ++detailGeneration;
            detailInFlight = true;
            ImagePreviews.Request submitted = details.loadConnectedDetail(detailFile, null, 1, ready -> {
                if (generation != detailGeneration || !canShowDetail() || !isAttachedToWindow()) {
                    if (ready.bitmap != null) ready.bitmap.recycle(); return;
                }
                detailRequest = null; detailInFlight = false;
                detailInfo = ready.info;
                if (detailInfo != null) detailOrientation.set(detailInfo.orientationMatrix());
                if (ready.busy || detailInfo != null) scheduleDetail();
            });
            if (detailInFlight) detailRequest = submitted;
            return;
        }
        if (zoom <= 1.05f) {
            if (detailRequest != null) detailRequest.cancel();
            detailRequest = null; detailInFlight = false; ++detailGeneration;
            clearTile(); return;
        }
        Matrix source = sourceToView(), inverted = new Matrix();
        if (!source.invert(inverted)) return;
        RectF visible = new RectF(0, 0, getWidth(), getHeight());
        inverted.mapRect(visible);
        if (!visible.intersect(0, 0, detailInfo.width, detailInfo.height)) { clearTile(); return; }
        Rect wanted = new Rect(Math.max(0, (int)Math.floor(visible.left)), Math.max(0, (int)Math.floor(visible.top)),
                Math.min(detailInfo.width, (int)Math.ceil(visible.right)),
                Math.min(detailInfo.height, (int)Math.ceil(visible.bottom)));
        if (wanted.isEmpty()) return;
        float[] values = new float[9]; source.getValues(values);
        float scale = (float)Math.hypot(values[Matrix.MSCALE_X], values[Matrix.MSKEW_Y]);
        int sample = ImagePreviewPolicy.detailSample(wanted.width(), wanted.height(), scale);
        if (detailRegion != null && detailRegion.contains(wanted) && detailSample <= sample) return;
        if (detailRequest != null) detailRequest.cancel();
        long generation = ++detailGeneration;
        detailInFlight = true;
        ImagePreviews.Request submitted = details.loadConnectedDetail(detailFile, wanted, sample, ready -> {
            if (generation != detailGeneration || !canShowDetail() || !isAttachedToWindow()) {
                if (ready.bitmap != null) ready.bitmap.recycle(); return;
            }
            detailRequest = null; detailInFlight = false;
            if (ready.busy) { scheduleDetail(); return; }
            clearTile();
            detailBitmap = ready.bitmap; detailRegion = ready.region; detailSample = sample;
            invalidate();
        });
        if (detailInFlight) detailRequest = submitted;
    }

    @Override protected void onDraw(Canvas canvas) {
        // A current permission fence is checked at draw as well as at asynchronous completion.
        if (originalAllowed != null && !originalAllowed.getAsBoolean()) {
            if (!overviewSuppressed) { overviewSuppressed = true; clearDetailSource(); }
            return;
        }
        if (overviewSuppressed) return;
        super.onDraw(canvas);
        if (detailBitmap == null || detailRegion == null || detailInfo == null || bitmap == null) return;
        tileTransform.setScale(detailRegion.width() / (float)detailBitmap.getWidth(),
                detailRegion.height() / (float)detailBitmap.getHeight());
        tileTransform.postTranslate(detailRegion.left, detailRegion.top);
        tileTransform.postConcat(sourceToView());
        int saved = canvas.save();
        canvas.clipRect(0, 0, getWidth(), getHeight());
        canvas.drawBitmap(detailBitmap, tileTransform, detailPaint);
        canvas.restoreToCount(saved);
    }

    @Override protected void onAttachedToWindow() { super.onAttachedToWindow(); scheduleDetail(); }
    @Override protected void onDetachedFromWindow() { clearDetailSource(); super.onDetachedFromWindow(); }

    /** Restores the original upright image, fitted entirely inside this view. */
    void resetToFit() {
        zoom = 1f;
        degrees = 0f;
        centerX = getWidth() / 2f;
        centerY = getHeight() / 2f;
        updateMatrix();
    }

    /** Clockwise quarter-turn; the rotated image is fitted so none of it is cropped. */
    void rotateBy90() {
        if (bitmap == null) return;
        degrees = (degrees + 90f) % 360f;
        zoom = 1f;
        centerX = getWidth() / 2f;
        centerY = getHeight() / 2f;
        updateMatrix();
    }

    void zoomBy(float factor, float focusX, float focusY) {
        if (!Float.isFinite(factor) || factor <= 0) return;
        transform(Math.max(1f, Math.min(MAX_ZOOM, zoom * factor)), degrees, focusX, focusY);
    }

    private float fitScale() {
        if (bitmap == null || bitmap.getWidth() == 0 || bitmap.getHeight() == 0
                || getWidth() == 0 || getHeight() == 0) return 1f;
        double radians = Math.toRadians(degrees);
        float cosine = (float)Math.abs(Math.cos(radians));
        float sine = (float)Math.abs(Math.sin(radians));
        float projectedWidth = bitmap.getWidth() * cosine + bitmap.getHeight() * sine;
        float projectedHeight = bitmap.getWidth() * sine + bitmap.getHeight() * cosine;
        return Math.min(getWidth() / projectedWidth, getHeight() / projectedHeight);
    }

    private void buildMatrix() {
        display.reset();
        if (bitmap == null) return;
        display.setTranslate(-bitmap.getWidth() / 2f, -bitmap.getHeight() / 2f);
        float scale = fitScale() * zoom;
        display.postScale(scale, scale);
        display.postRotate(degrees);
        display.postTranslate(centerX, centerY);
    }

    private void updateMatrix() {
        if (bitmap == null) { setImageMatrix(display); return; }
        buildMatrix();
        bounds.set(0f, 0f, bitmap.getWidth(), bitmap.getHeight());
        display.mapRect(bounds);
        float shiftX = bounds.width() <= getWidth()
                ? getWidth() / 2f - bounds.centerX()
                : bounds.left > 0f ? -bounds.left : bounds.right < getWidth() ? getWidth() - bounds.right : 0f;
        float shiftY = bounds.height() <= getHeight()
                ? getHeight() / 2f - bounds.centerY()
                : bounds.top > 0f ? -bounds.top : bounds.bottom < getHeight() ? getHeight() - bounds.bottom : 0f;
        centerX += shiftX;
        centerY += shiftY;
        display.postTranslate(shiftX, shiftY);
        setImageMatrix(display);
        scheduleDetail();
    }

    /** Keeps the bitmap point under the gesture focus stationary while scaling/rotating. */
    private void transform(float nextZoom, float nextDegrees, float focusX, float focusY) {
        if (bitmap == null || getWidth() == 0 || getHeight() == 0) return;
        point[0] = focusX;
        point[1] = focusY;
        if (!display.invert(inverse)) return;
        inverse.mapPoints(point);
        zoom = nextZoom;
        degrees = (nextDegrees % 360f + 360f) % 360f;
        buildMatrix();
        display.mapPoints(point);
        centerX += focusX - point[0];
        centerY += focusY - point[1];
        updateMatrix();
    }

    @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        // Keep the user's zoom and rotation, but recenter and re-fit the new viewport.
        centerX = width / 2f;
        centerY = height / 2f;
        updateMatrix();
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        if (bitmap == null) return super.onTouchEvent(event);
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN && getParent() != null)
            getParent().requestDisallowInterceptTouchEvent(true);
        pinch.onTouchEvent(event);
        if (event.getPointerCount() == 1) gestures.onTouchEvent(event);
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN
                || action == MotionEvent.ACTION_POINTER_UP) {
            // Re-anchor after a finger count change; never interpret it as a giant pan/rotation.
            int remaining = event.getPointerCount() - (action == MotionEvent.ACTION_POINTER_UP ? 1 : 0);
            if (remaining >= 2) {
                int first = -1;
                int second = -1;
                for (int index = 0; index < event.getPointerCount(); index++) {
                    if (action == MotionEvent.ACTION_POINTER_UP && index == event.getActionIndex()) continue;
                    if (first < 0) first = index;
                    else { second = index; break; }
                }
                anchorPair(event, first, second);
                rotating = true;
            } else if (remaining == 1) {
                int index = action == MotionEvent.ACTION_POINTER_UP && event.getActionIndex() == 0 ? 1 : 0;
                lastX = event.getX(index);
                lastY = event.getY(index);
                rotating = false;
            }
            tracking = true;
        } else if (action == MotionEvent.ACTION_MOVE && tracking) {
            if (event.getPointerCount() >= 2) {
                float x = (event.getX(0) + event.getX(1)) / 2f;
                float y = (event.getY(0) + event.getY(1)) / 2f;
                float angle = angle(event, 0, 1);
                if (!rotating) { anchorPair(event, 0, 1); rotating = true; }
                else {
                    centerX += x - lastX;
                    centerY += y - lastY;
                    updateMatrix();
                    float delta = angle - lastAngle;
                    if (delta > 180f) delta -= 360f;
                    else if (delta < -180f) delta += 360f;
                    if (Float.isFinite(delta)) transform(zoom, degrees + delta, x, y);
                    lastX = x;
                    lastY = y;
                    lastAngle = angle;
                }
            } else if (!pinch.isInProgress()) {
                centerX += event.getX() - lastX;
                centerY += event.getY() - lastY;
                lastX = event.getX();
                lastY = event.getY();
                updateMatrix();
            }
        } else if (action == MotionEvent.ACTION_CANCEL || action == MotionEvent.ACTION_UP) {
            tracking = false;
            rotating = false;
            if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
        }
        return true;
    }

    private void anchorPair(MotionEvent event, int first, int second) {
        lastX = (event.getX(first) + event.getX(second)) / 2f;
        lastY = (event.getY(first) + event.getY(second)) / 2f;
        lastAngle = angle(event, first, second);
    }

    private static float angle(MotionEvent event, int first, int second) {
        return (float)Math.toDegrees(Math.atan2(event.getY(second) - event.getY(first),
                event.getX(second) - event.getX(first)));
    }

    @Override public boolean performClick() { super.performClick(); return true; }
}

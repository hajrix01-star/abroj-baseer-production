package com.baseer.bwork.legacy;

import android.content.Context;
import android.graphics.*;
import android.view.*;
import android.widget.*;
import static com.baseer.bwork.legacy.Ui.*;

/** Explicitly sized preview; pixels are loaded only while on screen, and never set after detach/rebind. */
final class ImagePreviewView extends FrameLayout {
    private final ImageView image;
    private final TextView status;
    private final TextView detailStatus;
    private final LinearLayout detailControls;
    private final ImagePreviews previews;
    private final int target;
    private final boolean compact;
    private final Rect visible = new Rect();
    private ChatStore.Attachment file;
    private ImagePreviews.Request request;
    private int generation;
    private boolean previewRequested;
    private long loadStartedAt;
    private final Runnable previewDeadline = this::previewTimedOut;
    private final Runnable refresh = this::refreshVisibility;
    private final ViewTreeObserver.OnScrollChangedListener scroll = this::refreshVisibility;
    private final ViewTreeObserver.OnGlobalLayoutListener layout = this::refreshVisibility;

    ImagePreviewView(Context context, ChatStore.Attachment file, ImagePreviews previews, int target, boolean compact) {
        super(context); this.previews = previews; this.target = target; this.compact = compact;
        setBackground(bg(Ui.LINE, 12, context)); setClipToOutline(true);
        boolean inspector = !compact && target >= ImagePreviewPolicy.MAX_EDGE;
        image = inspector ? new DetailImageView(context) : new ImageView(context);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        image.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        FrameLayout.LayoutParams pixels = new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT);
        if (inspector) pixels.bottomMargin = dp(context, 88);
        addView(image, pixels);
        if (inspector) {
            detailControls = new LinearLayout(context); detailControls.setOrientation(LinearLayout.VERTICAL);
            detailStatus = text(context, context.getString(R.string.media_zoom_help), 10, MUTED, false);
            detailStatus.setGravity(Gravity.CENTER); pad(detailStatus, 6, 2);
            detailControls.addView(detailStatus, new LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, dp(context, 40)));
            LinearLayout buttons = new LinearLayout(context);
            int[] titles = {R.string.media_zoom_out, R.string.media_zoom_fit, R.string.media_zoom_in};
            for (int index = 0; index < titles.length; index++) {
                final int action = index;
                Button button = new Button(context); button.setText(titles[index]); button.setTextSize(10);
                button.setPadding(0, 0, 0, 0); button.setMinWidth(0); button.setMinimumWidth(0);
                button.setOnClickListener(v -> {
                    DetailImageView detail = (DetailImageView)image;
                    if (action == 1) detail.fit();
                    else detail.zoom(action == 0 ? .5f : 2f, detail.getWidth()/2f, detail.getHeight()/2f);
                });
                buttons.addView(button, new LinearLayout.LayoutParams(0, dp(context, 48), 1));
            }
            detailControls.addView(buttons);
            addView(detailControls, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, dp(context, 88), Gravity.BOTTOM));
            detailControls.setVisibility(GONE);
        } else { detailControls = null; detailStatus = null; }
        status = text(context, "", compact ? 10 : 12, MUTED, false); status.setGravity(Gravity.CENTER);
        pad(status, compact ? 2 : 12, compact ? 2 : 10);
        status.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        addView(status, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
        bind(file);
    }

    void bind(ChatStore.Attachment attachment) {
        clearRequest(); file = attachment; showWaiting();
        setContentDescription(getContext().getString(R.string.preview_file, AppLocale.name(getContext(), file.name)));
        if (isAttachedToWindow()) post(refresh);
    }

    private void showWaiting() {
        if (image instanceof DetailImageView) ((DetailImageView)image).reset();
        if (detailControls != null) detailControls.setVisibility(GONE);
        image.setImageDrawable(null); status.setText(compact ? "…" : getContext().getString(R.string.image_preview_loading));
        status.setVisibility(VISIBLE);
    }

    private void previewTimedOut() {
        if (loadStartedAt == 0) return;
        clearRequest(); previewRequested = true;
        image.setImageDrawable(null); status.setText(R.string.media_preview_timeout); status.setVisibility(VISIBLE);
    }

    private boolean visibleNow() {
        return isAttachedToWindow() && getWindowVisibility() == VISIBLE && isShown() && getWidth() > 0 && getHeight() > 0
                && getGlobalVisibleRect(visible) && visible.width() > 0 && visible.height() > 0;
    }

    private void refreshVisibility() {
        if (!visibleNow()) {
            if (previewRequested) { clearRequest(); showWaiting(); }
            return;
        }
        if (previewRequested) return;
        previewRequested = true; final int token = ++generation;
        if (loadStartedAt == 0) {
            loadStartedAt = android.os.SystemClock.elapsedRealtime(); postDelayed(previewDeadline, 15_000);
        }
        request = previews.load(file, target, result -> {
            if (token != generation || !isAttachedToWindow()) return;
            if (result.busy) {
                previewRequested = false;
                removeCallbacks(refresh); postDelayed(refresh, 150);
            } else if (result.bitmap != null) {
                removeCallbacks(previewDeadline); loadStartedAt = 0;
                image.setImageBitmap(result.bitmap); status.setVisibility(GONE);
                if (image instanceof DetailImageView) {
                    detailControls.setVisibility(VISIBLE); ((DetailImageView)image).start(result.bitmap);
                }
            } else {
                removeCallbacks(previewDeadline); loadStartedAt = 0;
                image.setImageDrawable(null);
                int failureText = result.sourceMissing ? R.string.image_original_missing : R.string.ui_308;
                status.setText(compact ? "!" : getContext().getString(failureText)); status.setVisibility(VISIBLE);
                setContentDescription(getContext().getString(R.string.preview_file, AppLocale.name(getContext(), file.name))
                        + ". " + getContext().getString(failureText));
            }
        });
    }

    private void clearRequest() {
        ++generation; previewRequested = false; removeCallbacks(refresh);
        removeCallbacks(previewDeadline); loadStartedAt = 0;
        if (request != null) request.cancel(); request = null;
    }

    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        getViewTreeObserver().addOnScrollChangedListener(scroll); getViewTreeObserver().addOnGlobalLayoutListener(layout);
        post(refresh);
    }

    @Override protected void onDetachedFromWindow() {
        if (getViewTreeObserver().isAlive()) {
            getViewTreeObserver().removeOnScrollChangedListener(scroll); getViewTreeObserver().removeOnGlobalLayoutListener(layout);
        }
        clearRequest(); showWaiting();
        super.onDetachedFromWindow();
    }

    @Override protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(visibility);
        // This callback can occur during construction before the child views exist.
        if (image == null || status == null) return;
        if (visibility != VISIBLE) { clearRequest(); showWaiting(); }
        else if (isAttachedToWindow()) post(refresh);
    }

    @Override protected void onVisibilityChanged(View changedView, int visibility) {
        super.onVisibilityChanged(changedView, visibility);
        if (image == null || status == null) return;
        if (visibility != VISIBLE || !isShown()) { clearRequest(); showWaiting(); }
        else if (isAttachedToWindow()) post(refresh);
    }
    /** Inspector-only zoom/pan, a cheap overview plus one bounded original-resolution viewport tile. */
    private final class DetailImageView extends ImageView {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
        private final Matrix orientation = new Matrix(), display = new Matrix();
        private final Matrix sourceMatrix = new Matrix(), inverse = new Matrix();
        private final RectF overviewBounds = new RectF(), tileBounds = new RectF(), viewport = new RectF();
        private final ScaleGestureDetector pinch;
        private final GestureDetector gestures;
        private ImagePreviews.SourceInfo info;
        private Bitmap overview, tile;
        private Rect tileRegion, requestedRegion;
        private int tileSample, requestedSample;
        private float scale = 1, minimum = 1, offsetX, offsetY;
        private ImagePreviews.Request detailRequest;
        private int detailGeneration;
        private Runnable deadline, tileRetry;
        private final Runnable refreshTile = this::requestTile;

        DetailImageView(Context context) {
            super(context);
            pinch = new ScaleGestureDetector(context, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
                @Override public boolean onScale(ScaleGestureDetector detector) {
                    zoom(detector.getScaleFactor(), detector.getFocusX(), detector.getFocusY()); return true;
                }
            });
            gestures = new GestureDetector(context, new GestureDetector.SimpleOnGestureListener() {
                @Override public boolean onDown(MotionEvent event) { return true; }
                @Override public boolean onDoubleTap(MotionEvent event) {
                    if (info != null) {
                        if (scale > minimum * 1.1f) fit();
                        else zoom(Math.max(1f, minimum * 2f) / scale, event.getX(), event.getY());
                    }
                    return true;
                }
                @Override public boolean onScroll(MotionEvent first, MotionEvent current, float dx, float dy) {
                    if (info == null || pinch.isInProgress()) return false;
                    offsetX -= dx; offsetY -= dy; changed(); return true;
                }
                @Override public boolean onSingleTapUp(MotionEvent event) { performClick(); return true; }
            });
            setContentDescription(context.getString(R.string.media_zoom_help));
        }
        void start(Bitmap bitmap) {
            reset(); overview = bitmap; detailStatus.setText(R.string.image_preview_loading);
            final int token = ++detailGeneration; setDeadline(token); requestInfo(token);
        }
        private void requestInfo(int token) {
            if (token != detailGeneration || !isAttachedToWindow()) return;
            detailRequest = previews.loadDetail(file, null, 1, result -> {
                if (token != detailGeneration || !isAttachedToWindow()) return;
                detailRequest = null;
                if (result.busy) { postDelayed(() -> requestInfo(token), 150); return; }
                clearDeadline();
                if (result.info == null) { detailStatus.setText(R.string.media_detail_unavailable); return; }
                detailStatus.setText(R.string.media_zoom_help); info = result.info;
                orientation.set(info.orientationMatrix()); overviewBounds.set(0, 0, info.displayWidth, info.displayHeight); fit();
            });
        }
        void reset() {
            removeCallbacks(refreshTile); cancelDetailWork();
            if (tile != null) tile.recycle(); tile = null; tileRegion = null;
            overview = null; info = null; tileSample = 0;
            orientation.reset(); display.reset(); overviewBounds.setEmpty(); tileBounds.setEmpty();
            scale = minimum = 1; offsetX = offsetY = 0; setScaleType(ScaleType.FIT_CENTER); setImageMatrix(display);
        }
        private void setDeadline(int token) {
            clearDeadline();
            deadline = () -> {
                if (token != detailGeneration) return;
                ++detailGeneration;
                if (tileRetry != null) removeCallbacks(tileRetry); tileRetry = null;
                if (detailRequest != null) detailRequest.cancel(); detailRequest = null;
                deadline = null; detailStatus.setText(R.string.media_preview_timeout);
            };
            postDelayed(deadline, 15_000);
        }
        private void clearDeadline() { if (deadline != null) removeCallbacks(deadline); deadline = null; }
        private void cancelDetailWork() {
            ++detailGeneration; clearDeadline();
            if (tileRetry != null) removeCallbacks(tileRetry); tileRetry = null;
            if (detailRequest != null) detailRequest.cancel(); detailRequest = null;
            requestedRegion = null; requestedSample = 0;
        }
        void fit() {
            if (info == null || getWidth() < 1 || getHeight() < 1) return;
            minimum = Math.min(getWidth()/(float)info.displayWidth, getHeight()/(float)info.displayHeight);
            scale = minimum; offsetX = 0; offsetY = 0; changed();
        }
        void zoom(float factor, float focusX, float focusY) {
            if (info == null || !Float.isFinite(factor) || factor <= 0) return;
            float next = Math.max(minimum, Math.min(Math.max(2f, minimum), scale * factor));
            float ratio = next/scale;
            offsetX = focusX - (focusX-offsetX)*ratio; offsetY = focusY - (focusY-offsetY)*ratio;
            scale = next; changed();
        }
        private void changed() {
            if (info == null) return;
            float width = info.displayWidth*scale, height = info.displayHeight*scale;
            offsetX = width <= getWidth() ? (getWidth()-width)/2 : Math.max(getWidth()-width, Math.min(0, offsetX));
            offsetY = height <= getHeight() ? (getHeight()-height)/2 : Math.max(getHeight()-height, Math.min(0, offsetY));
            display.reset();
            if (overview != null) display.setScale(info.displayWidth*scale/overview.getWidth(), info.displayHeight*scale/overview.getHeight());
            display.postTranslate(offsetX, offsetY); setScaleType(ScaleType.MATRIX); setImageMatrix(display);
            invalidate(); removeCallbacks(refreshTile); postDelayed(refreshTile, 70);
        }
        private Matrix sourceToView() {
            sourceMatrix.set(orientation); sourceMatrix.postScale(scale, scale); sourceMatrix.postTranslate(offsetX, offsetY); return sourceMatrix;
        }
        private void requestTile() {
            if (info == null || overview == null || !isAttachedToWindow()) return;
            if (scale <= Math.min(overview.getWidth()/(float)info.displayWidth, overview.getHeight()/(float)info.displayHeight)) {
                if (requestedRegion != null) cancelDetailWork(); detailStatus.setText(R.string.media_zoom_help); return;
            }
            if (!sourceToView().invert(inverse)) return;
            viewport.set(0, 0, getWidth(), getHeight()); inverse.mapRect(viewport);
            Rect region = new Rect(Math.max(0, (int)Math.floor(viewport.left)), Math.max(0, (int)Math.floor(viewport.top)),
                    Math.min(info.width, (int)Math.ceil(viewport.right)), Math.min(info.height, (int)Math.ceil(viewport.bottom)));
            if (region.isEmpty()) return;
            int sample = ImagePreviewPolicy.detailSample(region.width(), region.height(), scale);
            if (region.equals(tileRegion) && sample == tileSample) {
                if (requestedRegion != null) cancelDetailWork(); detailStatus.setText(R.string.media_zoom_help); return;
            }
            // Same viewport redraws/busy retries cannot extend its overall 15-second budget.
            if (region.equals(requestedRegion) && sample == requestedSample) return;
            cancelDetailWork(); requestedRegion = region; requestedSample = sample;
            final int token = detailGeneration; setDeadline(token); requestTileAttempt(token, region, sample);
        }
        private void requestTileAttempt(int token, Rect region, int sample) {
            if (token != detailGeneration || !isAttachedToWindow()) return;
            tileRetry = null;
            detailRequest = previews.loadDetail(file, region, sample, result -> {
                if (token != detailGeneration || !isAttachedToWindow()) { if (result.bitmap != null) result.bitmap.recycle(); return; }
                detailRequest = null;
                if (result.busy) {
                    tileRetry = () -> requestTileAttempt(token, region, sample); postDelayed(tileRetry, 200); return;
                }
                clearDeadline();
                if (result.bitmap == null) { detailStatus.setText(R.string.media_detail_unavailable); return; }
                Bitmap previous = tile; tile = result.bitmap; tileRegion = result.region; tileSample = sample; tileBounds.set(tileRegion);
                detailStatus.setText(R.string.media_zoom_help); invalidate(); if (previous != null) previous.recycle();
            });
        }
        @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
            super.onSizeChanged(width, height, oldWidth, oldHeight); if (info != null) fit();
        }
        @Override protected void onDraw(Canvas canvas) {
            if (info == null || overview == null) { super.onDraw(canvas); return; }
            int saved = canvas.save(); canvas.translate(offsetX, offsetY); canvas.scale(scale, scale);
            canvas.drawBitmap(overview, null, overviewBounds, paint);
            if (tile != null && tileRegion != null) { canvas.concat(orientation); canvas.drawBitmap(tile, null, tileBounds, paint); }
            canvas.restoreToCount(saved);
        }
        @Override public boolean onTouchEvent(MotionEvent event) {
            if (info == null) return super.onTouchEvent(event);
            if (event.getActionMasked() == MotionEvent.ACTION_DOWN) getParent().requestDisallowInterceptTouchEvent(true);
            pinch.onTouchEvent(event); gestures.onTouchEvent(event);
            if (event.getActionMasked() == MotionEvent.ACTION_UP || event.getActionMasked() == MotionEvent.ACTION_CANCEL)
                getParent().requestDisallowInterceptTouchEvent(false);
            return true;
        }
        @Override public boolean performClick() { super.performClick(); return true; }
    }
}

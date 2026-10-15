package com.baseer.freshchat;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.pdf.PdfRenderer;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.view.Gravity;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.TextView;
import java.io.IOException;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import static com.baseer.freshchat.Ui.*;

/** Read-only first-page preview. Native parsing never blocks the Activity thread. */
final class PdfPreviewView extends FrameLayout {
    // A native PDF call cannot be forcibly interrupted safely in-process. Bound shared work and fence late results.
    private static final ThreadPoolExecutor WORKER = new ThreadPoolExecutor(1, 1, 30, TimeUnit.SECONDS, new ArrayBlockingQueue<>(4));
    static { WORKER.allowCoreThreadTimeOut(true); }
    private static final long DEADLINE_MS = 15_000;
    private final ChatStore.Attachment file;
    private final Context application;
    private final ImageView image;
    private final TextView status;
    private Future<?> request;
    private Bitmap displayed;
    private int generation;
    private boolean started;
    private Runnable deadline;

    PdfPreviewView(Context context, ChatStore.Attachment file) {
        super(context); this.file = file; application = context.getApplicationContext();
        image = new ImageView(context); image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        image.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        LayoutParams pixels = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT);
        pixels.bottomMargin = dp(context, 48); addView(image, pixels);
        status = text(context, context.getString(R.string.media_pdf_loading), 12, MUTED, false);
        status.setGravity(Gravity.CENTER); pad(status, 8, 8);
        addView(status, new LayoutParams(LayoutParams.MATCH_PARENT, dp(context, 48), Gravity.BOTTOM));
        setContentDescription(context.getString(R.string.preview_file, AppLocale.name(context, file.name)));
    }
    @Override protected void onAttachedToWindow() { super.onAttachedToWindow(); start(); }
    private void start() {
        if (started || !isAttachedToWindow() || getWindowVisibility() != VISIBLE || !isShown()) return;
        started = true; final int token = ++generation; status.setText(R.string.media_pdf_loading);
        deadline = () -> {
            if (token != generation || !isAttachedToWindow()) return;
            cancel(); status.setText(R.string.media_preview_timeout);
        };
        postDelayed(deadline, DEADLINE_MS);
        try {
            request = WORKER.submit(() -> {
                Preview preview;
                try { preview = render(application, file); }
                catch (AttachmentSupport.SourceUnavailableException missing) {
                    preview = new Preview(null, 0, missing.reason == AttachmentSupport.SourceUnavailableException.Reason.MISSING);
                } catch (IOException | RuntimeException | OutOfMemoryError unavailable) { preview = new Preview(null, 0, false); }
                final Preview ready = preview;
                new android.os.Handler(Looper.getMainLooper()).post(() -> {
                    if (token != generation || !isAttachedToWindow()) { if (ready.bitmap != null) ready.bitmap.recycle(); return; }
                    if (deadline != null) removeCallbacks(deadline); deadline = null; request = null;
                    displayed = ready.bitmap; image.setImageBitmap(displayed);
                    status.setText(displayed != null ? getContext().getString(R.string.media_pdf_first_page, ready.pages)
                            : getContext().getString(ready.missing ? R.string.image_original_missing : R.string.media_pdf_unavailable));
                });
            });
        } catch (RejectedExecutionException busy) { cancel(); status.setText(R.string.media_preview_timeout); }
    }
    private void cancel() {
        ++generation; if (deadline != null) removeCallbacks(deadline); deadline = null;
        if (request != null) { request.cancel(true); if (request instanceof Runnable) WORKER.remove((Runnable)request); }
        request = null;
    }
    private void clearDisplay() {
        cancel(); started = false; image.setImageDrawable(null);
        if (displayed != null) displayed.recycle(); displayed = null;
    }
    @Override protected void onDetachedFromWindow() { clearDisplay(); super.onDetachedFromWindow(); }
    @Override protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(visibility);
        if (image == null || status == null) return;
        if (visibility != VISIBLE) clearDisplay(); else start();
    }
    @Override protected void onVisibilityChanged(android.view.View changedView, int visibility) {
        super.onVisibilityChanged(changedView, visibility);
        if (image == null || status == null) return;
        if (visibility != VISIBLE || !isShown()) clearDisplay(); else start();
    }
    static final class Preview {
        final Bitmap bitmap; final int pages; final boolean missing;
        Preview(Bitmap bitmap, int pages, boolean missing) { this.bitmap = bitmap; this.pages = pages; this.missing = missing; }
    }
    static Preview render(Context context, ChatStore.Attachment file) throws IOException {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("PDF decode must run off main");
        if (Thread.currentThread().isInterrupted()) throw new IOException("Cancelled PDF preview");
        try (ParcelFileDescriptor descriptor = ParcelFileDescriptor.open(AttachmentSupport.requirePrivateFile(context, file), ParcelFileDescriptor.MODE_READ_ONLY);
             PdfRenderer renderer = new PdfRenderer(descriptor)) {
            int count = renderer.getPageCount();
            if (count < 1 || Thread.currentThread().isInterrupted()) throw new IOException("Empty or cancelled PDF preview");
            try (PdfRenderer.Page page = renderer.openPage(0)) {
                if (!ImagePreviewPolicy.validSource(page.getWidth(), page.getHeight())) throw new IOException("Invalid PDF bounds");
                int[] dimensions = ImagePreviewPolicy.fit(page.getWidth(), page.getHeight(), 1400);
                Bitmap bitmap = Bitmap.createBitmap(dimensions[0], dimensions[1], Bitmap.Config.ARGB_8888);
                try {
                    bitmap.eraseColor(Color.WHITE); page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                    if (Thread.currentThread().isInterrupted()) throw new IOException("Cancelled PDF preview");
                    return new Preview(bitmap, count, false);
                } catch (IOException | RuntimeException | OutOfMemoryError failure) { bitmap.recycle(); throw failure; }
            }
        }
    }
}

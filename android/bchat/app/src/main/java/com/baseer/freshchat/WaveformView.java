package com.baseer.freshchat;

import android.content.Context;
import android.graphics.*;
import android.view.View;

/** Display only measured peaks. A silent sample is flat; absent samples draw no bars. */
final class WaveformView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private float[] peaks = new float[0];
    private float progress;
    WaveformView(Context context) { super(context); setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO); }
    void samples(float[] values) { peaks = values == null ? new float[0] : values.clone(); invalidate(); }
    void progress(float value) { progress = Math.max(0f, Math.min(1f, value)); invalidate(); }
    void append(float value) {
        if (peaks.length != 60) peaks = new float[60];
        System.arraycopy(peaks, 1, peaks, 0, peaks.length - 1); peaks[peaks.length - 1] = Math.max(0f, Math.min(1f, value)); invalidate();
    }
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas); float middle = getHeight() / 2f;
        paint.setColor(Ui.LINE); paint.setStrokeWidth(Ui.dp(getContext(), 1)); canvas.drawLine(0, middle, getWidth(), middle, paint);
        if (peaks.length == 0) return;
        float step = getWidth() / (float)peaks.length; paint.setStrokeWidth(Math.max(1f, step * .55f)); paint.setStrokeCap(Paint.Cap.ROUND);
        for (int i = 0; i < peaks.length; i++) {
            // sqrt improves quiet-speech readability without inventing a nonzero amplitude.
            float height = (float)Math.sqrt(peaks[i]) * Math.max(0f, middle - Ui.dp(getContext(), 2));
            if (height == 0f) continue;
            paint.setColor(i / (float)peaks.length <= progress ? Ui.GREEN : Ui.MUTED);
            canvas.drawLine(step * (i + .5f), middle - height, step * (i + .5f), middle + height, paint);
        }
    }
}

package com.baseer.freshchat;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.view.View;

/** One original B bitmap with a restrained alpha shadow; no 3D engine or replacement logo. */
final class EntryMarkView extends View {
    private final Bitmap original;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final RectF destination = new RectF();
    private static final Rect SOURCE = new Rect(14, 5, 113, 123);
    EntryMarkView(Context context) {
        super(context);
        BitmapFactory.Options options = new BitmapFactory.Options(); options.inScaled = false;
        original = BitmapFactory.decodeResource(getResources(), R.drawable.baseer_mark_b, options);
        setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        setCameraDistance(Ui.dp(context, 6000));
        setLayoutDirection(LAYOUT_DIRECTION_LTR);
        setTag("bchat-entry-mark"); setContentDescription("BChat");
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float scale = Math.min((getWidth() - Ui.dp(getContext(), 32)) / 99f, (getHeight() - Ui.dp(getContext(), 22)) / 118f);
        if (scale <= 0) return;
        float width = 99 * scale, height = 118 * scale;
        float left = (getWidth() - width) / 2f, top = (getHeight() - height) / 2f - Ui.dp(getContext(), 2);
        paint.setShadowLayer(Ui.dp(getContext(), 4), Ui.dp(getContext(), 2), Ui.dp(getContext(), 4), 0x28000000);
        destination.set(left, top, left + width, top + height);
        canvas.drawBitmap(original, SOURCE, destination, paint);
    }
}

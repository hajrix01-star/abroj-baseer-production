package com.baseer.bwork.legacy;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;
import android.view.View;

/** One proportional, font-independent BWork mark in both interface languages. */
public final class BWorkWordmarkView extends View {
    // The original PNG's alpha bounds. Crop only transparent padding, never recolor the B.
    private static final Rect B_SOURCE = new Rect(14, 5, 113, 123);
    static final float B_HEIGHT = 229f;
    static final float B_WIDTH = 99f * B_HEIGHT / 118f;
    static final float CHAT_GAP = 6f;
    static final float CHAT_TOP = 21f;
    static final int CHAT_WIDTH = 659;
    static final int CHAT_HEIGHT = 212;
    static final float DESIGN_WIDTH = B_WIDTH + CHAT_GAP + CHAT_WIDTH;
    static final float DESIGN_HEIGHT = 233f;
    static final float ART_HEIGHT_DP = 32f;
    private float artHeightDp = ART_HEIGHT_DP;

    private final Bitmap originalB;
    private final Drawable chat;
    private final Paint bitmapPaint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final RectF bDestination = new RectF(0f, 0f, B_WIDTH, B_HEIGHT);

    public BWorkWordmarkView(Context context) {
        super(context);
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inScaled = false;
        originalB = BitmapFactory.decodeResource(getResources(), R.drawable.baseer_mark_b, options);
        chat = context.getDrawable(R.drawable.bwork_chat_wordmark).mutate();
        chat.setBounds(0, 0, CHAT_WIDTH, CHAT_HEIGHT);
        setLayoutDirection(LAYOUT_DIRECTION_LTR);
        setContentDescription("BWork");
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);
        setTag("bwork-wordmark");
    }

    /** Keep the login brand full-sized while allowing a compact in-app toolbar mark. */
    public void setArtHeightDp(float heightDp) {
        artHeightDp = Math.max(16f, heightDp);
        requestLayout();
        invalidate();
    }

    private float preferredHeight() {
        return artHeightDp * getResources().getDisplayMetrics().density;
    }

    @Override protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = (int) Math.ceil(preferredHeight() * DESIGN_WIDTH / DESIGN_HEIGHT)
                + getPaddingLeft() + getPaddingRight();
        int height = (int) Math.ceil(preferredHeight()) + getPaddingTop() + getPaddingBottom();
        setMeasuredDimension(resolveSize(width, widthMeasureSpec), resolveSize(height, heightMeasureSpec));
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float availableWidth = getWidth() - getPaddingLeft() - getPaddingRight();
        float availableHeight = getHeight() - getPaddingTop() - getPaddingBottom();
        if (availableWidth <= 0f || availableHeight <= 0f) return;
        // One uniform scale for both components; no text metrics, font scaling or RTL mirroring.
        float scale = Math.min(preferredHeight() / DESIGN_HEIGHT,
                Math.min(availableWidth / DESIGN_WIDTH, availableHeight / DESIGN_HEIGHT));
        int save = canvas.save();
        canvas.translate(getPaddingLeft(), getPaddingTop() + (availableHeight - DESIGN_HEIGHT * scale) / 2f);
        canvas.scale(scale, scale);
        canvas.drawBitmap(originalB, B_SOURCE, bDestination, bitmapPaint);
        canvas.translate(B_WIDTH + CHAT_GAP, CHAT_TOP);
        chat.draw(canvas);
        canvas.restoreToCount(save);
    }
}

package com.baseer.freshchat;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.view.View;

/** Renders the supplied vector BChat mark without tinting, recoloring, or bitmap scaling. */
final class EntryMarkView extends View {
    private final Drawable original;

    EntryMarkView(Context context) {
        super(context);
        original = context.getDrawable(R.drawable.bchat_mark_hq);
        if (original == null) throw new IllegalStateException("BChat mark resource is unavailable");
        setLayoutDirection(LAYOUT_DIRECTION_LTR);
        setTag("bchat-entry-mark"); setContentDescription("BChat");
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (getWidth() <= 0 || getHeight() <= 0) return;
        original.setBounds(0, 0, getWidth(), getHeight());
        original.draw(canvas);
    }
}

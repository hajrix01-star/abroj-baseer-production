package com.baseer.freshchat;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;

/** Login-only presentation of the canonical B mark with one quiet ambient shadow. */
final class LoginBrandView extends FrameLayout {
    private final EntryMarkView mark;
    private final ShadowView shadow;

    LoginBrandView(Context context) {
        super(context);
        setClipChildren(false);
        setClipToPadding(false);
        setTag("bchat-login-brand");
        setContentDescription("BChat");
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);

        shadow = new ShadowView(context);
        LayoutParams shadowSize = new LayoutParams(Ui.dp(context, 96), Ui.dp(context, 12),
                Gravity.CENTER_HORIZONTAL | Gravity.BOTTOM);
        shadowSize.bottomMargin = Ui.dp(context, 9);
        addView(shadow, shadowSize);

        mark = new EntryMarkView(context);
        mark.setDrawShadow(false);
        mark.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        mark.setTranslationZ(Ui.dp(context, 2));
        LayoutParams markSize = new LayoutParams(Ui.dp(context, 140), Ui.dp(context, 140),
                Gravity.CENTER_HORIZONTAL | Gravity.TOP);
        markSize.topMargin = Ui.dp(context, 2);
        addView(mark, markSize);
        shadow.setAlpha(.22f);
    }

    private static final class ShadowView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        ShadowView(Context context) { super(context); setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO); }
        @Override protected void onDraw(Canvas canvas) {
            float radius = getWidth() / 2f;
            paint.setShader(new RadialGradient(getWidth() / 2f, getHeight() / 2f, radius,
                    new int[]{Color.argb(55, 10, 60, 99), Color.TRANSPARENT},
                    new float[]{0f, 1f}, Shader.TileMode.CLAMP));
            canvas.drawOval(0f, 0f, getWidth(), getHeight(), paint);
            paint.setShader(null);
        }
    }
}

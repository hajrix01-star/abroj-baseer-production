package com.baseer.freshchat;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.Gravity;
import android.view.View;
import android.view.animation.PathInterpolator;
import android.widget.FrameLayout;

/** Login-only presentation of the canonical B mark. The identity asset is never recolored or replaced. */
final class LoginBrandView extends FrameLayout {
    private static final long FLOAT_CYCLE_MILLIS = 2600L;
    private final EntryMarkView mark;
    private final ShadowView shadow;
    private ValueAnimator floatAnimator;

    LoginBrandView(Context context) {
        super(context);
        setClipChildren(false);
        setClipToPadding(false);
        setTag("bchat-login-brand");
        setContentDescription("BChat");
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);

        shadow = new ShadowView(context);
        LayoutParams shadowSize = new LayoutParams(Ui.dp(context, 104), Ui.dp(context, 18),
                Gravity.CENTER_HORIZONTAL | Gravity.BOTTOM);
        shadowSize.bottomMargin = Ui.dp(context, 8);
        addView(shadow, shadowSize);

        mark = new EntryMarkView(context);
        mark.setDrawShadow(false);
        mark.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        mark.setTranslationZ(Ui.dp(context, 2));
        LayoutParams markSize = new LayoutParams(Ui.dp(context, 140), Ui.dp(context, 140),
                Gravity.CENTER_HORIZONTAL | Gravity.TOP);
        markSize.topMargin = Ui.dp(context, 2);
        addView(mark, markSize);
        setRestingState();
    }

    @Override public void onVisibilityAggregated(boolean isVisible) {
        super.onVisibilityAggregated(isVisible);
        if (isVisible) startFloating(); else stopFloating();
    }

    @Override protected void onDetachedFromWindow() {
        stopFloating();
        super.onDetachedFromWindow();
    }

    private void startFloating() {
        if (floatAnimator != null) return;
        if (!ValueAnimator.areAnimatorsEnabled()) {
            setRestingState();
            return;
        }
        final float liftDistance = Ui.dp(getContext(), 6);
        floatAnimator = ValueAnimator.ofFloat(0f, 1f, 0f);
        floatAnimator.setDuration(FLOAT_CYCLE_MILLIS);
        floatAnimator.setRepeatCount(ValueAnimator.INFINITE);
        floatAnimator.setInterpolator(new PathInterpolator(.37f, 0f, .63f, 1f));
        floatAnimator.addUpdateListener(animation -> {
            float lift = (float) animation.getAnimatedValue();
            mark.setTranslationY(-liftDistance * lift);
            shadow.setScaleX(1f + .22f * lift);
            shadow.setScaleY(1f + .06f * lift);
            shadow.setAlpha(.32f - .14f * lift);
        });
        floatAnimator.start();
    }

    private void stopFloating() {
        if (floatAnimator != null) {
            floatAnimator.cancel();
            floatAnimator = null;
        }
        setRestingState();
    }

    private void setRestingState() {
        mark.setTranslationY(0f);
        shadow.setScaleX(1f);
        shadow.setScaleY(1f);
        shadow.setAlpha(.32f);
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

// Original Baseer offline demo. No network transport or real recipient data.
package com.baseer.freshchat;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.app.AlertDialog;
import android.view.*;
import android.widget.*;

final class Ui {
    static final int NAVY = Color.rgb(9, 43, 71);
    static final int INK = Color.rgb(24, 42, 59);
    static final int MUTED = Color.rgb(100, 114, 130);
    static final int GREEN = Color.rgb(11, 109, 184);
    static final int SKY = Color.rgb(28, 156, 235);
    static final int LIGHT = Color.rgb(248, 250, 252);
    static final int LINE = Color.rgb(229, 234, 238);
    static final int LIME = Color.rgb(231, 244, 253);
    static final int SURFACE = Color.WHITE;
    static final int CHAT_CANVAS = Color.rgb(248, 246, 242);
    static final int CHAT_SENT = Color.rgb(227, 249, 233);
    static final int CHAT_RECEIVED = Color.WHITE;
    static final int CHAT_DATE = Color.rgb(255, 255, 255);
    static final int ACTION_PRESSED = Color.rgb(8, 84, 145);
    static final int ACTION_TONAL = Color.rgb(234, 243, 252);
    static final int ACTION_TONAL_PRESSED = Color.rgb(214, 231, 248);
    static final int ACTION_DISABLED = Color.rgb(239, 241, 244);
    static final int ACTION_TOUCH_DP = 48;
    static final int CHAT_BODY_SP = 16;
    static final int CHAT_PREVIEW_SP = 14;
    static final int CHAT_META_SP = 12;
    static final int CHAT_TIME_SP = 13;
    static final int CHAT_HEADER_TITLE_SP = 16;
    static final int CHAT_TEXT_LINE_DP = 22;
    static final int ROOM_TITLE_SP = 17;
    static final int ROOM_ROW_MIN_DP = 75;
    static final int ROOM_AVATAR_DP = 48;

    enum ActionTone { PRIMARY, SECONDARY, TEXT }
    enum IconTone { PLAIN, TONAL, FILLED, RECORDING }

    static int dp(Context c, float n) {
        return (int)(c.getResources().getDisplayMetrics().density * n + 0.5F);
    }

    static GradientDrawable bg(int color, float radius, Context c) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(c, radius));
        return d;
    }

    static GradientDrawable outline(int color, int stroke, float radius, Context c) {
        GradientDrawable d = bg(color, radius, c);
        d.setStroke(dp(c, 1), stroke);
        return d;
    }

    static TextView text(Context c, String s, float size, int color, boolean bold) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(size);
        t.setTextColor(color);
        t.setFontFeatureSettings("kern");
        t.setTextDirection(AppLocale.textDirection(c));
        t.setLayoutDirection(AppLocale.direction(c));
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        t.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        return t;
    }

    static LinearLayout column(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setLayoutDirection(AppLocale.direction(c));
        return l;
    }

    static LinearLayout row(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setLayoutDirection(AppLocale.direction(c));
        l.setGravity(Gravity.CENTER_VERTICAL);
        return l;
    }

    static void pad(View v, int h, int vert) {
        v.setPadding(dp(v.getContext(), h), dp(v.getContext(), vert), dp(v.getContext(), h), dp(v.getContext(), vert));
    }

    static LinearLayout.LayoutParams lp(int w, int h) {
        return new LinearLayout.LayoutParams(w, h);
    }

    static View line(Context c) {
        View v = new View(c);
        v.setBackgroundColor(LINE);
        v.setLayoutParams(lp(-1, dp(c, 1)));
        return v;
    }

    /** Shared action treatment; call sites retain their own labels and click listeners. */
    static void styleAction(TextView button, ActionTone tone) {
        Context context = button.getContext();
        if (button instanceof Button) ((Button) button).setAllCaps(false);
        button.setTextSize(14);
        button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        button.setTextDirection(AppLocale.textDirection(context));
        button.setLayoutDirection(AppLocale.direction(context));
        button.setGravity(Gravity.CENTER);
        button.setMinWidth(dp(context, ACTION_TOUCH_DP));
        button.setMinHeight(dp(context, ACTION_TOUCH_DP));
        button.setMinimumWidth(dp(context, ACTION_TOUCH_DP));
        button.setMinimumHeight(dp(context, ACTION_TOUCH_DP));
        button.setPaddingRelative(dp(context, 16), dp(context, 8),
                dp(context, 16), dp(context, 8));
        button.setBackgroundTintList(null);
        int normal = tone == ActionTone.PRIMARY ? GREEN
                : tone == ActionTone.SECONDARY ? ACTION_TONAL : Color.TRANSPARENT;
        int pressed = tone == ActionTone.PRIMARY ? ACTION_PRESSED
                : tone == ActionTone.SECONDARY ? ACTION_TONAL_PRESSED : LIME;
        button.setBackground(actionBackground(context, normal, pressed,
                tone == ActionTone.TEXT ? Color.TRANSPARENT : ACTION_DISABLED, 12));
        int textColor = tone == ActionTone.PRIMARY ? Color.WHITE : GREEN;
        button.setTextColor(actionTextColors(textColor, MUTED));
        button.setStateListAnimator(null);
        button.setForeground(null);
        button.setClickable(true);
        button.setFocusable(true);
    }

    /** Loading is explicit: callers provide translated labels and can restore the idle label. */
    static void setActionLoading(TextView button, boolean loading,
                                 CharSequence idleLabel, CharSequence loadingLabel) {
        button.setText(loading ? loadingLabel : idleLabel);
        button.setEnabled(!loading);
        button.setContentDescription(loading ? loadingLabel : idleLabel);
    }

    static void styleIconAction(View button, IconTone tone) {
        Context context = button.getContext();
        button.setMinimumWidth(dp(context, ACTION_TOUCH_DP));
        button.setMinimumHeight(dp(context, ACTION_TOUCH_DP));
        int normal = tone == IconTone.FILLED ? GREEN
                : tone == IconTone.RECORDING ? 0xffbc3342
                : tone == IconTone.TONAL ? ACTION_TONAL : Color.TRANSPARENT;
        int pressed = tone == IconTone.FILLED ? ACTION_PRESSED
                : tone == IconTone.RECORDING ? 0xff9c2735
                : tone == IconTone.TONAL ? ACTION_TONAL_PRESSED : LIME;
        button.setBackground(actionBackground(context,
                normal, pressed, ACTION_DISABLED, 12));
        if (button instanceof FrameLayout) {
            FrameLayout frame = (FrameLayout) button;
            for (int i = 0; i < frame.getChildCount(); i++) {
                View child = frame.getChildAt(i);
                if (child instanceof Icon) {
                    ((Icon) child).color = tone == IconTone.FILLED
                            || tone == IconTone.RECORDING ? Color.WHITE : GREEN;
                    child.invalidate();
                }
            }
        }
        button.setForeground(null);
        button.setClickable(true);
        button.setFocusable(true);
    }

    static void styleTab(LinearLayout tab, FrameLayout indicator,
                         TextView label, boolean selected) {
        Context context = tab.getContext();
        tab.setSelected(selected);
        tab.setMinimumHeight(dp(context, ACTION_TOUCH_DP));
        tab.setBackground(actionBackground(context, Color.TRANSPARENT, LIME,
                Color.TRANSPARENT, 8));
        tab.setForeground(null);
        tab.setClickable(true);
        tab.setFocusable(true);
        indicator.setBackgroundColor(Color.TRANSPARENT);
        for (int i = 0; i < indicator.getChildCount(); i++) {
            View child = indicator.getChildAt(i);
            if (child instanceof Icon) {
                ((Icon) child).color = selected ? SKY : MUTED;
                child.invalidate();
            }
        }
        label.setTextColor(selected ? GREEN : MUTED);
        label.setTypeface(Typeface.create(selected ? "sans-serif-medium" : "sans-serif",
                Typeface.NORMAL));
        label.setTextDirection(AppLocale.textDirection(context));
        label.setLayoutDirection(AppLocale.direction(context));
    }

    static void styleHeaderIcon(View button) {
        Context context = button.getContext();
        button.setBackground(actionBackground(context, Color.TRANSPARENT,
                0x334a708d, Color.TRANSPARENT, 12));
        if (button instanceof FrameLayout) {
            FrameLayout frame = (FrameLayout) button;
            for (int i = 0; i < frame.getChildCount(); i++) {
                View child = frame.getChildAt(i);
                if (child instanceof Icon) {
                    ((Icon) child).color = Color.WHITE;
                    child.invalidate();
                }
            }
        }
        button.setMinimumWidth(dp(context, ACTION_TOUCH_DP));
        button.setMinimumHeight(dp(context, ACTION_TOUCH_DP));
    }

    /** Fixed-height order tab; its separate underline never changes the row height. */
    static void styleSegment(TextView button, boolean selected) {
        Context context = button.getContext();
        button.setSelected(selected);
        button.setTextSize(15);
        button.setTypeface(Typeface.create(selected ? "sans-serif-medium" : "sans-serif",
                Typeface.NORMAL));
        button.setTextDirection(AppLocale.textDirection(context));
        button.setLayoutDirection(AppLocale.direction(context));
        button.setGravity(Gravity.CENTER);
        button.setMinWidth(dp(context, ACTION_TOUCH_DP));
        button.setMinHeight(dp(context, ACTION_TOUCH_DP));
        button.setMinimumWidth(dp(context, ACTION_TOUCH_DP));
        button.setMinimumHeight(dp(context, ACTION_TOUCH_DP));
        button.setPaddingRelative(dp(context, 6), dp(context, 6),
                dp(context, 6), dp(context, 6));
        button.setTextColor(actionTextColors(selected ? GREEN : MUTED, MUTED));
        button.setBackground(actionBackground(context, Color.TRANSPARENT,
                ACTION_TONAL_PRESSED, Color.TRANSPARENT, 0));
        button.setForeground(null);
        button.setClickable(true);
        button.setFocusable(true);
    }

    private static ColorStateList actionTextColors(int enabled, int disabled) {
        return new ColorStateList(new int[][] {
                new int[] {-android.R.attr.state_enabled}, new int[] {}
        }, new int[] {disabled, enabled});
    }

    private static Drawable actionBackground(Context context, int normal,
                                             int pressed, int disabled, float radius) {
        StateListDrawable fills = new StateListDrawable();
        fills.addState(new int[] {-android.R.attr.state_enabled}, bg(disabled, radius, context));
        fills.addState(new int[] {android.R.attr.state_pressed}, bg(pressed, radius, context));
        fills.addState(new int[] {}, bg(normal, radius, context));
        return new RippleDrawable(ColorStateList.valueOf(0x242566b7), fills,
                bg(Color.WHITE, radius, context));
    }

    static TextView pill(Context c, String s, boolean selected) {
        TextView t = text(c, s, 13, selected ? Color.WHITE : MUTED, selected);
        pad(t, 15, 7);
        t.setGravity(Gravity.CENTER);
        t.setBackground(bg(selected ? GREEN : Color.WHITE, 24, c));
        t.setMinHeight(dp(c, ACTION_TOUCH_DP));
        return t;
    }

    static LinearLayout emptyState(Context c, String title, String detail) {
        LinearLayout state = column(c);
        state.setGravity(Gravity.CENTER);
        pad(state, 24, 24);
        TextView heading = text(c, title, 17, INK, true);
        heading.setGravity(Gravity.CENTER);
        state.addView(heading, lp(-1, -2));
        TextView explanation = text(c, detail, 13, MUTED, false);
        explanation.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams detailSize = lp(-1, -2);
        detailSize.topMargin = dp(c, 8);
        state.addView(explanation, detailSize);
        return state;
    }

    static void decorateDialog(AlertDialog dialog) {
        if (dialog == null || dialog.getWindow() == null) return;
        dialog.getWindow().setBackgroundDrawable(bg(SURFACE, 20, dialog.getContext()));
        int screen = dialog.getContext().getResources().getDisplayMetrics().widthPixels;
        dialog.getWindow().setLayout(Math.min(screen - dp(dialog.getContext(), 32),
                dp(dialog.getContext(), 560)), -2);
        Button positive = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
        Button negative = dialog.getButton(AlertDialog.BUTTON_NEGATIVE);
        Button neutral = dialog.getButton(AlertDialog.BUTTON_NEUTRAL);
        if (positive != null) styleAction(positive, ActionTone.PRIMARY);
        if (negative != null) styleAction(negative, ActionTone.TEXT);
        if (neutral != null) styleAction(neutral, ActionTone.SECONDARY);
    }

    static FrameLayout iconButton(Context context, String kind, String label) {
        FrameLayout button = new FrameLayout(context);
        button.setMinimumWidth(dp(context, 48));
        button.setMinimumHeight(dp(context, 48));
        button.setContentDescription(label);
        Icon icon = new Icon(context, kind, GREEN);
        FrameLayout.LayoutParams iconSize = new FrameLayout.LayoutParams(
                dp(context, 22), dp(context, 22), Gravity.CENTER);
        button.addView(icon, iconSize);
        styleIconAction(button, IconTone.PLAIN);
        return button;
    }

    static void clickable(View v) {
        v.setClickable(true);
        v.setFocusable(true);
        android.util.TypedValue tv = new android.util.TypedValue();
        v.getContext().getTheme().resolveAttribute(android.R.attr.selectableItemBackground, tv, true);
        v.setForeground(v.getContext().getDrawable(tv.resourceId));
    }

    static class ActionButton extends FrameLayout {
        ActionButton(Context context) { super(context); }
        @Override public boolean performClick() { return super.performClick(); }
    }

    /** Horizontal reply gestures mirror with locale and leave vertical scrolling/seek controls alone. */
    static final class ReplySwipeLayout extends LinearLayout {
        private final Runnable reply;private final String label;private final int slop;
        private float downX,downY;private boolean eligible,dragging,threshold;
        ReplySwipeLayout(Context context,String label,Runnable reply){super(context);this.label=label;this.reply=reply;slop=ViewConfiguration.get(context).getScaledTouchSlop();setOrientation(VERTICAL);setLayoutDirection(AppLocale.direction(context));}
        private int direction(){return AppLocale.rtl(getContext())?-1:1;}
        private void startIfHorizontal(MotionEvent event){
            float x=event.getRawX()-downX,y=event.getRawY()-downY;
            if(Math.abs(y)>slop&&Math.abs(y)>Math.abs(x))eligible=false;
            else if(x*direction()>slop*1.5f&&Math.abs(x)>Math.abs(y)*1.5f){dragging=true;cancelLongPress();if(getParent()!=null)getParent().requestDisallowInterceptTouchEvent(true);}
        }
        @Override public boolean onInterceptTouchEvent(MotionEvent event){
            int action=event.getActionMasked();
            if(action==MotionEvent.ACTION_DOWN){animate().cancel();setTranslationX(0);downX=event.getRawX();downY=event.getRawY();dragging=threshold=false;eligible=reply!=null&&!touchesSeek(this,event.getX(),event.getY());}
            else if(action==MotionEvent.ACTION_POINTER_DOWN||action==MotionEvent.ACTION_CANCEL){eligible=false;resetSwipe();}
            else if(action==MotionEvent.ACTION_MOVE&&eligible)startIfHorizontal(event);
            return dragging||super.onInterceptTouchEvent(event);
        }
        @Override public boolean onTouchEvent(MotionEvent event){
            if(!dragging&&eligible&&event.getActionMasked()==MotionEvent.ACTION_MOVE)startIfHorizontal(event);
            if(!dragging)return super.onTouchEvent(event);
            int action=event.getActionMasked();
            if(action==MotionEvent.ACTION_MOVE){float distance=Math.max(0,(event.getRawX()-downX)*direction());setTranslationX(direction()*Math.min(dp(getContext(),76),distance*.7f));boolean reached=distance>=dp(getContext(),64);if(reached&&!threshold)performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);threshold=reached;return true;}
            if(action==MotionEvent.ACTION_UP){boolean trigger=eligible&&threshold;resetSwipe();if(trigger)reply.run();return true;}
            if(action==MotionEvent.ACTION_CANCEL||action==MotionEvent.ACTION_POINTER_DOWN){eligible=false;resetSwipe();return true;}return true;
        }
        private void resetSwipe(){dragging=threshold=false;if(getParent()!=null)getParent().requestDisallowInterceptTouchEvent(false);animate().cancel();if(android.animation.ValueAnimator.areAnimatorsEnabled())animate().translationX(0).setDuration(120).start();else setTranslationX(0);}
        @Override protected void onDetachedFromWindow(){animate().cancel();setTranslationX(0);eligible=dragging=threshold=false;super.onDetachedFromWindow();}
        @Override public void onInitializeAccessibilityNodeInfo(android.view.accessibility.AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(info);if(reply!=null)info.addAction(new android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction(R.id.foundation_reply_action,label));}
        @Override public boolean performAccessibilityAction(int action,android.os.Bundle args){if(reply!=null&&action==R.id.foundation_reply_action){reply.run();return true;}return super.performAccessibilityAction(action,args);}
        private static boolean touchesSeek(View view,float x,float y){
            if(view instanceof SeekBar||view instanceof HorizontalScrollView)return true;if(!(view instanceof ViewGroup))return false;ViewGroup parent=(ViewGroup)view;
            for(int i=parent.getChildCount()-1;i>=0;i--){View child=parent.getChildAt(i);float localX=x+parent.getScrollX()-child.getLeft(),localY=y+parent.getScrollY()-child.getTop();if(child.getVisibility()==VISIBLE&&localX>=0&&localY>=0&&localX<child.getWidth()&&localY<child.getHeight()&&touchesSeek(child,localX,localY))return true;}return false;
        }
    }

    static class Icon extends View {
        String kind;
        int color;
        Paint p = new Paint(3);

        Icon(Context c, String k, int color) {
            super(c);
            kind = k;
            this.color = color;
            setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        }

        void line(Canvas c, float... xy) {
            for (int i = 0; i + 3 < xy.length; i += 2) c.drawLine(xy[i], xy[i + 1], xy[i + 2], xy[i + 3], p);
        }

        void circle(Canvas c, float x, float y, float r) {
            c.drawCircle(x, y, r, p);
        }

        protected void onDraw(Canvas cc) {
            super.onDraw(cc);
            Canvas c = cc;
            float k = Math.min(getWidth(), getHeight()) / 24.0F;
            c.save();
            c.translate((getWidth() - 24 * k) / 2, (getHeight() - 24 * k) / 2);
            c.scale(k, k);
            p.setColor(color);
            p.setStrokeWidth(1.8F);
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeCap(Paint.Cap.ROUND);
            p.setStrokeJoin(Paint.Join.ROUND);
            Path q = new Path();
            switch (kind) {
            case "search":
                circle(c, 10.5F, 10.5F, 6);
                line(c, 15, 15, 20, 20);
                break;

            case "back":
                if (AppLocale.rtl(getContext())) line(c, 9, 5, 16, 12, 9, 19);
                else line(c, 15, 5, 8, 12, 15, 19);
                break;

            case "close":
                line(c, 6, 6, 18, 18);
                line(c, 18, 6, 6, 18);
                break;

            case "down":
                line(c, 6, 9, 12, 15, 18, 9);
                break;

            case "send":
                q.moveTo(20, 4);
                q.lineTo(3, 11);
                q.lineTo(10, 14);
                q.lineTo(13, 21);
                q.close();
                c.drawPath(q, p);
                line(c, 10, 14, 20, 4);
                break;

            case "attach":
                q.moveTo(8, 8);
                q.lineTo(8, 16);
                q.cubicTo(8, 21, 17, 21, 17, 16);
                q.lineTo(17, 6);
                q.cubicTo(17, 0, 5, 0, 5, 6);
                q.lineTo(5, 17);
                q.cubicTo(5, 25, 21, 25, 21, 17);
                c.save();
                c.translate(-1, -2);
                c.scale(0.9F, 0.9F);
                c.drawPath(q, p);
                c.restore();
                break;

            case "camera":
                c.drawRoundRect(3, 7, 21, 20, 3, 3, p);
                line(c, 7, 7, 9, 3, 15, 3, 17, 7);
                circle(c, 12, 13, 4);
                break;

            case "photo":
                c.drawRoundRect(3, 3, 21, 21, 3, 3, p);
                circle(c, 8, 8, 1.3F);
                line(c, 4, 17, 10, 11, 14, 15, 17, 12, 21, 16);
                break;

            case "pdf":
                q.moveTo(6, 2);
                q.lineTo(14, 2);
                q.lineTo(20, 8);
                q.lineTo(20, 22);
                q.lineTo(6, 22);
                q.close();
                c.drawPath(q, p);
                line(c, 14, 2, 14, 8, 20, 8);
                line(c, 9, 13, 16, 13);
                line(c, 9, 17, 14, 17);
                break;

            case "chat":
                c.drawRoundRect(3, 3, 21, 17, 5, 5, p);
                line(c, 7, 17, 6, 22, 13, 17);
                line(c, 8, 9, 16, 9);
                line(c, 8, 12, 13, 12);
                break;

            case "tasks":
                circle(c, 12, 12, 9);
                line(c, 7.5F, 12, 10.5F, 15, 16.5F, 9);
                break;

            case "orders":
                q.moveTo(6, 2);
                q.lineTo(18, 2);
                q.lineTo(18, 22);
                q.lineTo(15, 20);
                q.lineTo(12, 22);
                q.lineTo(9, 20);
                q.lineTo(6, 22);
                q.close();
                c.drawPath(q, p);
                line(c, 9, 8, 15, 8);
                line(c, 9, 12, 15, 12);
                line(c, 9, 16, 13, 16);
                break;

            case "group":
                circle(c, 9, 8, 3);
                circle(c, 17, 9, 2.3F);
                q.moveTo(2, 21);
                q.cubicTo(2, 11, 16, 11, 16, 21);
                c.drawPath(q, p);
                q.reset();
                q.moveTo(17, 14);
                q.cubicTo(23, 14, 23, 18, 23, 21);
                c.drawPath(q, p);
                break;

            case "person":
                circle(c, 12, 7, 4);
                q.moveTo(4, 22);
                q.cubicTo(4, 10, 20, 10, 20, 22);
                c.drawPath(q, p);
                break;

            case "company":
                c.drawRoundRect(5, 3, 19, 22, 2, 2, p);
                line(c, 9, 22, 9, 16, 15, 16, 15, 22);
                line(c, 9, 7, 10, 7);
                line(c, 14, 7, 15, 7);
                line(c, 9, 11, 10, 11);
                line(c, 14, 11, 15, 11);
                break;

            case "clock":
                circle(c, 12, 12, 8);
                line(c, 12, 7, 12, 12, 16, 14);
                break;

            case "plus":
                line(c, 12, 5, 12, 19);
                line(c, 5, 12, 19, 12);
                break;

            case "edit":
                q.moveTo(5, 16);
                q.lineTo(5, 21);
                q.lineTo(10, 20);
                q.lineTo(22, 8);
                q.lineTo(17, 3);
                q.close();
                c.drawPath(q, p);
                line(c, 14, 6, 19, 11);
                break;

            case "shield":
                q.moveTo(12, 2);
                q.lineTo(21, 6);
                q.lineTo(19, 16);
                q.lineTo(12, 22);
                q.lineTo(5, 16);
                q.lineTo(3, 6);
                q.close();
                c.drawPath(q, p);
                line(c, 8, 12, 11, 15, 16, 9);
                break;

            case "eye":
                q.moveTo(2, 12); q.cubicTo(7, 4, 17, 4, 22, 12);
                q.cubicTo(17, 20, 7, 20, 2, 12); c.drawPath(q, p); circle(c, 12, 12, 3); break;
            case "lock":
                c.drawRoundRect(5, 10, 19, 22, 2, 2, p); c.drawArc(8, 2, 16, 16, 180, 180, false, p); line(c, 12, 15, 12, 18); break;
            case "stop":
                p.setStyle(Paint.Style.FILL); c.drawRoundRect(5, 5, 19, 19, 2, 2, p); break;
            case "mic":
                c.drawRoundRect(9, 2, 15, 15, 3, 3, p);
                c.drawArc(5, 7, 19, 19, 0, 180, false, p);
                line(c, 12, 19, 12, 23); line(c, 8, 23, 16, 23); break;
            case "bell":
                q.moveTo(5, 17); q.lineTo(7, 14); q.lineTo(7, 9);
                q.cubicTo(7, 2, 17, 2, 17, 9); q.lineTo(17, 14); q.lineTo(19, 17); q.close();
                c.drawPath(q, p); c.drawArc(10, 18, 14, 22, 0, 180, false, p);
                break;
            case "settings":
                circle(c, 12, 12, 7);
                circle(c, 12, 12, 2.5F);
                line(c, 12, 2, 12, 5, 12, 19, 12, 22, 2, 12, 5, 12, 19, 12, 22, 12);
                break;
            case "info":
                circle(c, 12, 12, 9);
                line(c, 12, 10, 12, 17);
                p.setStyle(Paint.Style.FILL); circle(c, 12, 6.5F, 1.2F);
                break;
            case "logout":
                c.drawRoundRect(3, 4, 15, 20, 2, 2, p);
                line(c, 11, 12, 22, 12, 18, 8, 22, 12, 18, 16);
                break;
            case "language":
                circle(c, 12, 12, 9);
                c.drawOval(9, 3, 15, 21, p);
                line(c, 3, 12, 21, 12);
                break;
            case "more":
            case "kebab":
                p.setStyle(Paint.Style.FILL);
                circle(c, 12, 5, 2.1F);
                circle(c, 12, 12, 2.1F);
                circle(c, 12, 19, 2.1F);
                break;

            case "refresh":
                c.drawArc(4, 4, 20, 20, 35, 290, false, p);
                line(c, 17, 4, 21, 5, 20, 9);
                break;

            case "mark":
                p.setStyle(Paint.Style.FILL);
                c.drawRoundRect(2, 3, 22, 18, 5, 5, p);
                q.moveTo(10, 17);
                q.lineTo(10, 23);
                q.lineTo(16, 17);
                q.close();
                c.drawPath(q, p);
                p.setColor(GREEN);
                circle(c, 7, 10, 1.3F);
                circle(c, 12, 10, 1.3F);
                circle(c, 17, 10, 1.3F);
                break;

            }
            c.restore();
        }
    }

    static class Avatar extends View {
        String name;
        String kind;
        int hue;
        Paint p = new Paint(3);

        Avatar(Context c, String name, String kind, int hue) {
            super(c);
            this.name = name;
            this.kind = kind;
            this.hue = hue;
            setContentDescription(name);
        }

        protected void onDraw(Canvas c) {
            float w = getWidth();
            float h = getHeight();
            float r = Math.min(w, h) / 2;
            int[] avatarTop = {0xff299de5, 0xff7166db, 0xff34ac88, 0xffe0843c, 0xffad619b};
            int[] avatarBottom = {0xff197bc3, 0xff5548b9, 0xff238b71, 0xffbd632d, 0xff864777};
            int variant = Math.floorMod(hue, avatarTop.length);
            p.setShader(new LinearGradient(0, 0, w, h, avatarTop[variant],
                    avatarBottom[variant], Shader.TileMode.CLAMP));
            c.drawCircle(w / 2, h / 2, r, p);
            p.setShader(null);
            p.setColor(Color.WHITE);
            p.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
            p.setTextAlign(Paint.Align.CENTER);
            p.setTextSize(r * 0.86F);
            String[] words = name.trim().split("\\s+");
            String s = words.length > 1 ? words[0].substring(0, 1) + " " + words[1].substring(0, 1) : name.substring(0, Math.min(2, name.length()));
            Paint.FontMetrics f = p.getFontMetrics();
            c.drawText(s, w / 2, h / 2 - (f.ascent + f.descent) / 2, p);
        }
    }

    /** A warm, quiet canvas separates the message thread from surrounding chrome. */
    static class Wallpaper extends View {
        Wallpaper(Context c) { super(c); setBackgroundColor(CHAT_CANVAS); }
    }
}

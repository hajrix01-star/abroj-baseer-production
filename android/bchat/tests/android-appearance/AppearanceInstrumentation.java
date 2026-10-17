package com.baseer.freshchat;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.Bundle;
import android.os.LocaleList;
import android.view.ContextThemeWrapper;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.util.Locale;

/** Standalone package, production components. Never starts or modifies the connected app. */
public final class AppearanceInstrumentation extends Instrumentation {
    private int cases, assertions;
    private Throwable failure;
    private boolean disposable;
    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        disposable = args != null && "true".equals(args.getString("disposable"));
        start();
    }
    private void check(boolean passed, String label) {
        assertions++;
        if (!passed) throw new AssertionError(label);
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if (!disposable) throw new IllegalStateException("Standalone disposable test opt-in required");
            for (String language : new String[]{"ar", "en"}) {
                check(new LocalSettings(getTargetContext()).language(language), "language preference saved");
                for (boolean dark : new boolean[]{false, true}) {
                    for (float scale : new float[]{1f, 1.3f, 2f}) {
                        for (int body : new int[]{14, 16, 18}) {
                            ChatAppearance.setBodySp(getTargetContext(), body);
                            runOnMainSync(() -> {
                                try { render(language, dark, scale, body); }
                                catch (Throwable error) { failure = error; }
                            });
                            if (failure != null) throw new AssertionError(failure);
                        }
                    }
                }
            }
            result.putString("stream", "PASS " + cases + " actual Android measure/draw cases, "
                    + assertions + " assertions; no Activity, network, FPS or device claim\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            result.putString("stream", android.util.Log.getStackTraceString(error));
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private void render(String language, boolean dark, float scale, int body) throws Exception {
        Configuration config = new Configuration();
        Locale locale = Locale.forLanguageTag(language);
        config.setLocales(new LocaleList(locale));
        config.setLayoutDirection(locale);
        config.uiMode = dark ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO;
        config.fontScale = scale;
        config.screenWidthDp = 360;
        Context scoped = getTargetContext().createConfigurationContext(config);
        Context themed = new ContextThemeWrapper(scoped, ChatAppearance.themeResource(scoped));
        check(ChatAppearance.dark(themed) == dark, "night resources follow context");
        check(ChatAppearance.bodySp(themed) == body, "font preference retained");
        LinearLayout root = Ui.column(themed);
        root.setBackgroundColor(UiPalette.canvas(themed));
        Ui.pad(root, 16, 16);
        root.addView(Ui.text(themed, language.equals("ar")
                ? "مجموعة فريق العمل BChat 123" : "Work team group BChat 123", 18, Ui.INK, true), Ui.lp(-1, -2));
        TextView text = Ui.chatText(themed, language.equals("ar")
                ? "رسالة عربية طويلة مع تشكيل وإيموجي 👩🏽‍💻، ثم نص English 123 لاختبار السطر والتباعد دون قص."
                : "A long message with Arabic العربية and emoji 👩🏽‍💻, testing flexible lines without clipping.");
        text.setBackground(Ui.bg(Ui.CHAT_SENT, 17, themed));
        Ui.pad(text, 12, 8);
        root.addView(text, Ui.lp(-1, -2));
        LinearLayout meta = Ui.messageMeta(themed, "12:34", "read", () -> { });
        root.addView(meta, Ui.lp(-1, -2));
        TextView action = Ui.text(themed, language.equals("ar") ? "إرسال الرسالة" : "Send message", 14, Ui.GREEN, true);
        Ui.styleAction(action, Ui.ActionTone.PRIMARY);
        root.addView(action, Ui.lp(-1, -2));
        action.refreshDrawableState();
        check(action.isEnabled(), "primary action is enabled");
        android.graphics.drawable.RippleDrawable ripple = (android.graphics.drawable.RippleDrawable) action.getBackground();
        android.graphics.drawable.StateListDrawable fills = (android.graphics.drawable.StateListDrawable) ripple.getDrawable(0);
        android.graphics.drawable.GradientDrawable activeFill = (android.graphics.drawable.GradientDrawable) fills.getCurrent();
        check(activeFill.getColor().getDefaultColor() == Ui.GREEN, "enabled primary fill is blue, not disabled: color="
                + Integer.toHexString(activeFill.getColor().getDefaultColor()) + " view="
                + java.util.Arrays.toString(action.getDrawableState()) + " ripple="
                + java.util.Arrays.toString(ripple.getState()) + " fills="
                + java.util.Arrays.toString(fills.getState()));
        action.setEnabled(false);
        check(((android.graphics.drawable.GradientDrawable) fills.getCurrent()).getColor().getDefaultColor()
                == UiPalette.background(themed, Ui.ACTION_DISABLED), "disabled background follows theme");
        check(action.getCurrentTextColor() == UiPalette.muted(themed), "disabled label remains legible");
        action.setEnabled(true);
        action.setPressed(true);
        check(((android.graphics.drawable.GradientDrawable) fills.getCurrent()).getColor().getDefaultColor()
                == Ui.ACTION_PRESSED, "pressed action has distinct feedback");
        action.setPressed(false);
        check(((android.graphics.drawable.GradientDrawable) fills.getCurrent()).getColor().getDefaultColor()
                == Ui.GREEN, "re-enabled action recovers primary colour");
        int width = Ui.dp(themed, 360);
        root.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
        root.layout(0, 0, width, root.getMeasuredHeight());
        check(text.getLayout() != null && text.getLineCount() > 1, "body wraps");
        check(text.getLayout().getHeight() <= text.getHeight() - text.getPaddingTop()
                - text.getPaddingBottom(), "font-scaled body is not vertically clipped");
        for (int line = 0; line < text.getLineCount(); line++)
            check(text.getLayout().getLineMax(line) <= text.getWidth() - text.getPaddingLeft()
                    - text.getPaddingRight() + 1, "visible line remains inside width: "
                    + language + "/" + dark + "/" + scale + "/" + body + " line=" + line
                    + " max=" + text.getLayout().getLineMax(line) + " available="
                    + (text.getWidth() - text.getPaddingLeft() - text.getPaddingRight()));
        check(action.getHeight() >= Ui.dp(themed, 48), "touch target min48");
        check(meta.getContentDescription().toString().contains("12:34"), "receipt accessible with time");
        check(((TextView) meta.getChildAt(0)).getCurrentTextColor() == UiPalette.muted(themed), "read does not recolor time");
        check(Ui.bubbleMaxWidth(root) <= root.getWidth(), "bubble uses available container");
        Bitmap frame = Bitmap.createBitmap(width, root.getHeight(), Bitmap.Config.ARGB_8888);
        root.draw(new Canvas(frame));
        File path = new File(getTargetContext().getFilesDir(), "appearance-" + language + "-"
                + (dark ? "dark" : "light") + "-" + scale + "-" + body + ".png");
        try (FileOutputStream output = new FileOutputStream(path)) {
            check(frame.compress(Bitmap.CompressFormat.PNG, 100, output), "frame captured");
        } finally { frame.recycle(); }
        cases++;
    }
}

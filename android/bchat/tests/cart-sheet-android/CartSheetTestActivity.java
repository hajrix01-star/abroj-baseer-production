package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Bundle;
import android.text.InputType;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Host is a presentation fixture, NOT product Activity, procurement authority or financial logic. */
public final class CartSheetTestActivity extends Activity {
    static String language = "ar";
    static boolean dark;
    static float scale = 1f;
    BChatCartSheet sheet;
    AlertDialog editor;
    EditText editorInput;
    final List<LinearLayout> steppers = new ArrayList<>();
    int decreased, edited, increased, removed, submitted, dismissed;

    @Override protected void attachBaseContext(Context base) {
        Configuration config = new Configuration(base.getResources().getConfiguration());
        config.setLocale(new Locale(language));
        config.setLayoutDirection(new Locale(language));
        config.fontScale = scale;
        config.uiMode = (config.uiMode & ~Configuration.UI_MODE_NIGHT_MASK)
                | (dark ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
        super.attachBaseContext(base.createConfigurationContext(config));
    }
    @Override public void onCreate(Bundle state) {
        setTheme(dark ? R.style.AppTheme_Dark : R.style.AppTheme);
        super.onCreate(state);
        setContentView(Ui.column(this));
        LinearLayout content = Ui.column(this);
        Ui.pad(content, 14, 6);
        for (int i = 0; i < 20; ++i) {
            String name = "ar".equals(language) ? "صنف طويل لاختبار وضوح اسم المنتج كاملًا في السلة " + i
                    : "Long product name that remains readable in the cart " + i;
            LinearLayout stepper = OrderQuantityStepper.create(this, "9999999.99", name, true,
                    () -> ++decreased, this::openEditor, () -> ++increased);
            steppers.add(stepper);
            LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(-1, -2);
            size.bottomMargin = Ui.dp(this, 8);
            content.addView(BChatCartSheet.line(this, name, "ar".equals(language) ? "عبوة · كجم" : "Pack · kg",
                    stepper, () -> ++removed), size);
        }
        // Server-shaped display fixture only. No amount calculation or actual quote request.
        TextView quote = Ui.text(this, "SR 1234.50", 17, UiPalette.ink(this), true);
        quote.setContentDescription("server quote fixture");
        content.addView(quote);
        content.addView(Ui.text(this, getString(R.string.order_quote_disclaimer), 12, UiPalette.muted(this), false));
        sheet = new BChatCartSheet(this, content, () -> ++submitted, owner -> ++dismissed);
        sheet.show();
    }
    void openEditor() {
        ++edited;
        editorInput = new EditText(this);
        editorInput.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        editorInput.setText("9999999.99");
        editor = new AlertDialog.Builder(this).setTitle(R.string.order_quantity).setView(editorInput)
                .setNegativeButton(R.string.task_close, null).create();
        editor.setOnShowListener(ignored -> {
            editorInput.requestFocus();
            editor.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE
                    | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            ((android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE))
                    .showSoftInput(editorInput, android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
        });
        editor.show();
    }
    @Override protected void onDestroy() {
        if (editor != null) editor.dismiss();
        if (sheet != null) sheet.dismiss();
        super.onDestroy();
    }
}

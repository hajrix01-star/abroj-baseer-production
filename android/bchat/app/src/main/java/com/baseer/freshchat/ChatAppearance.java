package com.baseer.freshchat;

import android.content.Context;
import android.content.res.Configuration;

/** Device-only presentation choices. Never stores identities, content, or entitlements. */
final class ChatAppearance {
    private static final String PREFS = "bchat-appearance-v1";
    private ChatAppearance() { }

    static String theme(Context context) {
        String value = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString("theme", "system");
        return "light".equals(value) || "dark".equals(value) ? value : "system";
    }

    static int bodySp(Context context) {
        int value = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getInt("body_sp", 16);
        return value == 14 || value == 18 ? value : 16;
    }

    static void setTheme(Context context, String value) {
        if (!"system".equals(value) && !"light".equals(value) && !"dark".equals(value))
            throw new IllegalArgumentException("theme");
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("theme", value).apply();
    }

    static void setBodySp(Context context, int value) {
        if (value != 14 && value != 16 && value != 18) throw new IllegalArgumentException("body_sp");
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putInt("body_sp", value).apply();
    }

    static Context wrap(Context context) {
        String choice = theme(context);
        if ("system".equals(choice)) return context;
        Configuration override = new Configuration();
        // Set only this mask: copying the entire Configuration freezes window/font changes.
        override.uiMode = "dark".equals(choice) ? Configuration.UI_MODE_NIGHT_YES
                : Configuration.UI_MODE_NIGHT_NO;
        return context.createConfigurationContext(override);
    }

    static boolean dark(Context context) {
        return (context.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
    }

    static int themeResource(Context context) {
        return dark(context) ? R.style.AppTheme_Dark : R.style.AppTheme;
    }
}

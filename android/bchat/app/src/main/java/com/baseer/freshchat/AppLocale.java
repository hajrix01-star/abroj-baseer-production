package com.baseer.freshchat;

import android.content.Context;
import android.content.res.Configuration;
import android.content.res.TypedArray;
import android.os.LocaleList;
import android.text.BidiFormatter;
import android.view.View;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/** Explicit per-app resources; never rewrites names, message text, or serialized ChatStore data. */
final class AppLocale {
    private static Map<String, Integer> legacyErrors;
    private AppLocale() { }

    static Context wrap(Context context) { return withLanguage(context, new LocalSettings(context).language()); }
    static Context withLanguage(Context context, String language) {
        Locale locale = Locale.forLanguageTag(AppLocalePolicy.language(language));
        Configuration current = context.getResources().getConfiguration();
        if (locale.equals(current.getLocales().get(0))
                && current.getLayoutDirection() == (AppLocalePolicy.rtl(language) ? View.LAYOUT_DIRECTION_RTL : View.LAYOUT_DIRECTION_LTR)) return context;
        // Override locale only. Copying the whole configuration pins orientation,
        // density and window size in this context when the display later changes.
        Configuration configuration = new Configuration();
        configuration.setLocales(new LocaleList(locale));
        configuration.setLayoutDirection(locale);
        return context.createConfigurationContext(configuration);
    }
    static Locale locale(Context context) { return context.getResources().getConfiguration().getLocales().get(0); }
    static boolean rtl(Context context) { return "ar".equals(locale(context).getLanguage()); }
    static int direction(Context context) { return rtl(context) ? View.LAYOUT_DIRECTION_RTL : View.LAYOUT_DIRECTION_LTR; }
    static int textDirection(Context context) { return rtl(context) ? View.TEXT_DIRECTION_FIRST_STRONG_RTL : View.TEXT_DIRECTION_FIRST_STRONG_LTR; }
    static String s(Context context, int resource, Object... values) {
        Context localized = wrap(context);
        return values.length == 0 ? localized.getString(resource) : localized.getString(resource, values);
    }
    static String name(Context context, String value) { return BidiFormatter.getInstance(rtl(context)).unicodeWrap(value == null ? "" : value); }

    /** Domain exceptions remain platform-neutral. Translate only recognized diagnostics, never arbitrary stored content. */
    static String error(Context context, String message) {
        synchronized (AppLocale.class) {
            if (legacyErrors == null) {
                legacyErrors = new HashMap<>();
                Context arabic = withLanguage(context, "ar"), english = withLanguage(context, "en");
                TypedArray ids = context.getResources().obtainTypedArray(R.array.localized_error_messages);
                try {
                    for (int i = 0; i < ids.length(); i++) {
                        int id = ids.getResourceId(i, 0);
                        if (id != 0) { legacyErrors.put(arabic.getString(id), id); legacyErrors.put(english.getString(id), id); }
                    }
                } finally { ids.recycle(); }
                legacyErrors.put("ATTACHMENT_IMPORT_CHANGED", R.string.media_import_changed);
                legacyErrors.put("ATTACHMENT_IMPORT_EMPTY_MEDIA", R.string.media_import_empty);
                legacyErrors.put("ATTACHMENT_EXPORT_PARTIAL", R.string.media_export_partial);
                legacyErrors.put("ATTACHMENT_SOURCE_CORRUPT", R.string.media_integrity_changed);
                String[] codes = context.getResources().getStringArray(R.array.domain_error_codes);
                TypedArray targets = context.getResources().obtainTypedArray(R.array.domain_error_messages);
                try { for (int i = 0; i < codes.length; i++) legacyErrors.put(codes[i], targets.getResourceId(i, 0)); }
                finally { targets.recycle(); }
            }
            Integer resource = message == null ? null : legacyErrors.get(message);
            // Do not expose platform English exceptions, private paths, or unknown raw provider messages.
            return s(context, resource == null || resource == 0 ? R.string.error_local_operation : resource);
        }
    }
}

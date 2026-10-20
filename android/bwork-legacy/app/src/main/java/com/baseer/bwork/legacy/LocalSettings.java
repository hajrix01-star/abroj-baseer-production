package com.baseer.bwork.legacy;

import android.content.Context;
import android.content.SharedPreferences;

/** Device-local preferences separate from the unchanged serialized chat store. */
final class LocalSettings {
    private final SharedPreferences values;
    LocalSettings(Context context) { values = context.getSharedPreferences(com.baseer.bwork.legacy.compat.LegacyIdentity.SETTINGS, Context.MODE_PRIVATE); }
    // Process-only demo entry unless Remember me was selected. Neither state authenticates anyone.
    private static boolean processDemoSession;
    boolean demoSessionActive() { return processDemoSession || values.getBoolean("demo-entry-active", false); }
    boolean rememberDemoEntry() { return values.getBoolean("remember-demo-entry", false); }
    boolean demoSessionActive(boolean active) { return demoSessionActive(active, rememberDemoEntry()); }
    boolean demoSessionActive(boolean active, boolean remember) {
        if (!values.edit().putBoolean("remember-demo-entry", remember).putBoolean("demo-entry-active", active && remember).commit()) return false;
        processDemoSession = active;
        return true;
    }
    boolean sound(String category) { LocalSettingsPolicy.category(category); return values.getBoolean(category + ":sound", true); }
    boolean vibration(String category) { LocalSettingsPolicy.category(category); return values.getBoolean(category + ":vibration", true); }
    void sound(String category, boolean enabled) { LocalSettingsPolicy.category(category); values.edit().putBoolean(category + ":sound", enabled).apply(); }
    void vibration(String category, boolean enabled) { LocalSettingsPolicy.category(category); values.edit().putBoolean(category + ":vibration", enabled).apply(); }
    boolean mute(String company, String chat) { return values.getBoolean(LocalSettingsPolicy.muteKey(company, chat), false); }
    void mute(String company, String chat, boolean enabled) { values.edit().putBoolean(LocalSettingsPolicy.muteKey(company, chat), enabled).apply(); }
    boolean hideLockscreen() { return values.getBoolean("hide-lockscreen", true); }
    void hideLockscreen(boolean enabled) { values.edit().putBoolean("hide-lockscreen", enabled).apply(); }
    String language() { return AppLocalePolicy.language(values.getString("interface-language", AppLocalePolicy.ARABIC)); }
    boolean language(String language) {
        if (!AppLocalePolicy.supported(language)) throw new IllegalArgumentException("Unsupported interface language");
        // Commit before recreation so the new Activity and delayed notifications see one durable choice.
        String previous = language();
        if (values.edit().putString("interface-language", language).commit()) return true;
        values.edit().putString("interface-language", previous).commit();
        return false;
    }
    String channel(String category) { return LocalSettingsPolicy.channel(category, sound(category), vibration(category), hideLockscreen()); }
}

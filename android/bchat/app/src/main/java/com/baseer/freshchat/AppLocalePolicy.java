package com.baseer.freshchat;

/** Small platform-independent policy; existing installations retain Arabic until changed. */
public final class AppLocalePolicy {
    public static final String ARABIC = "ar", ENGLISH = "en";
    private AppLocalePolicy() { }
    public static String language(String stored) { return ENGLISH.equals(stored) ? ENGLISH : ARABIC; }
    public static boolean supported(String language) { return ARABIC.equals(language) || ENGLISH.equals(language); }
    public static boolean rtl(String language) { return ARABIC.equals(language(language)); }
    public static boolean changed(String previous, String next) {
        if (!supported(next)) throw new IllegalArgumentException("Unsupported interface language");
        return !language(previous).equals(next);
    }
}

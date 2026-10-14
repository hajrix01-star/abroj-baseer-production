package com.baseer.freshchat;

/** Display an Odoo company in one language without changing its stored legal name. */
final class CompanyLabel {
    private CompanyLabel() { }

    static String choose(String combined, String arabic, String english, boolean arabicUi) {
        String ar = clean(arabic), en = clean(english);
        String preferred = arabicUi ? ar : en;
        if (!preferred.isEmpty()) return preferred;
        String fallback = clean(combined);
        String[] parts = fallback.split("\\s*\\|\\s*", -1);
        if (parts.length > 1) {
            String first = "", matching = "";
            for (String part : parts) {
                String candidate = part.trim();
                if (candidate.isEmpty()) continue;
                if (first.isEmpty()) first = candidate;
                if (matching.isEmpty() && hasArabic(candidate) == arabicUi) matching = candidate;
            }
            // A legacy joined name is never itself a display label.
            if (!matching.isEmpty()) return matching;
            String secondary = arabicUi ? en : ar;
            return secondary.isEmpty() ? first : secondary;
        }
        if (!fallback.isEmpty() && hasArabic(fallback) == arabicUi) return fallback;
        String secondary = arabicUi ? en : ar;
        return secondary.isEmpty() ? fallback : secondary;
    }

    private static String clean(String text) { return text == null ? "" : text.trim(); }

    private static boolean hasArabic(String text) {
        for (int offset = 0; offset < text.length(); ) {
            int codepoint = text.codePointAt(offset);
            Character.UnicodeBlock block = Character.UnicodeBlock.of(codepoint);
            if (block == Character.UnicodeBlock.ARABIC
                    || block == Character.UnicodeBlock.ARABIC_PRESENTATION_FORMS_A
                    || block == Character.UnicodeBlock.ARABIC_PRESENTATION_FORMS_B
                    || block == Character.UnicodeBlock.ARABIC_SUPPLEMENT
                    || block == Character.UnicodeBlock.ARABIC_EXTENDED_A) return true;
            offset += Character.charCount(codepoint);
        }
        return false;
    }
}

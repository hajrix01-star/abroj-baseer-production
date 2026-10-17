package com.baseer.freshchat;

import java.text.BreakIterator;
import java.util.Locale;

/** Grapheme-safe initials; no UTF-16 substring boundary is inferred from character count. */
final class AvatarInitials {
    private AvatarInitials() { }
    static String of(String name) {
        if (name == null || name.trim().isEmpty()) return "?";
        String[] words = name.trim().split("\\s+", 3);
        String first = cluster(words[0]);
        return words.length > 1 ? first + " " + cluster(words[1]) : first;
    }

    private static String cluster(String text) {
        if (text.isEmpty()) return "?";
        BreakIterator boundary = BreakIterator.getCharacterInstance(Locale.ROOT);
        boundary.setText(text);
        int end = boundary.following(0);
        if (end == BreakIterator.DONE) return "?";
        // Older Android/JDK Unicode tables split modern emoji. Extend those boundaries
        // for modifiers, regional-indicator pairs and arbitrarily joined ZWJ sequences.
        int first = text.codePointAt(0);
        if (regional(first) && end == Character.charCount(first)
                && end < text.length() && regional(text.codePointAt(end)))
            end += Character.charCount(text.codePointAt(end));
        while (end < text.length()) {
            int next = text.codePointAt(end);
            if (text.codePointBefore(end) == 0x200D || extend(next))
                end += Character.charCount(next);
            else if (next == 0x200D) {
                int joined = end + Character.charCount(next);
                if (joined >= text.length()) break;
                end = joined + Character.charCount(text.codePointAt(joined));
            } else break;
        }
        return text.substring(0, end);
    }

    private static boolean regional(int c) { return c >= 0x1F1E6 && c <= 0x1F1FF; }
    private static boolean extend(int c) {
        int type = Character.getType(c);
        return type == Character.NON_SPACING_MARK || type == Character.COMBINING_SPACING_MARK
                || type == Character.ENCLOSING_MARK || c == 0xFE0F || c == 0xFE0E
                || c >= 0x1F3FB && c <= 0x1F3FF || c >= 0xE0020 && c <= 0xE007F;
    }
}

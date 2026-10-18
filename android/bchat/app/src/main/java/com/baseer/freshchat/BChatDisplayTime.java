package com.baseer.freshchat;

import java.time.DateTimeException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DecimalStyle;
import java.time.format.ResolverStyle;
import java.util.Locale;
import java.util.regex.Pattern;

/** Presentation only: two existing UTC wire shapes, never a clock or zone conversion.
 * A null result means absent/invalid; the caller keeps its existing localized fallback.
 * This helper neither validates a response contract nor grants any receipt authority. */
final class BChatDisplayTime {
    private static final Pattern RECEIPT_SHAPE = Pattern.compile("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}");
    private static final Pattern GROUP_SHAPE = Pattern.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z");
    private static final DateTimeFormatter RECEIPT = formatter("uuuu-MM-dd HH:mm:ss");
    private static final DateTimeFormatter GROUP = formatter("uuuu-MM-dd'T'HH:mm:ss'Z'");
    private static final DateTimeFormatter DISPLAY = formatter("uuuu-MM-dd '·' HH:mm:ss 'UTC'");

    static String receipt(String value) { return display(value, 19, RECEIPT_SHAPE, RECEIPT, false); }
    static String groupEvent(String value) { return display(value, 20, GROUP_SHAPE, GROUP, true); }

    private static String display(String value, int length, Pattern shape, DateTimeFormatter source, boolean positiveYear) {
        if (value == null || value.length() != length || !shape.matcher(value).matches()) return null;
        try {
            LocalDateTime time = LocalDateTime.parse(value, source);
            // Match the existing projections: receipts accept proleptic year 0000;
            // group events require a positive year. Neither wire parser is changed.
            if (positiveYear && time.getYear() <= 0) return null;
            return "\u2066" + DISPLAY.format(time) + "\u2069";
        } catch (DateTimeException invalid) { return null; }
    }

    private static DateTimeFormatter formatter(String pattern) {
        return DateTimeFormatter.ofPattern(pattern, Locale.ROOT).withDecimalStyle(DecimalStyle.STANDARD)
                .withResolverStyle(ResolverStyle.STRICT);
    }
    private BChatDisplayTime() { }
}

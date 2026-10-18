package com.baseer.freshchat;

import java.util.Locale;
import java.util.TimeZone;

/** Actual pure production formatter. Process-local default changes are restored. */
public final class DisplayTimeTest {
    private static int checks;
    private static void check(boolean value, String label) {
        ++checks;
        if (!value) throw new AssertionError(label);
    }
    private static String isolated(String value) { return "\u2066" + value + "\u2069"; }
    private static void valid(String receipt, String expected) {
        String group = receipt.replace(' ', 'T') + "Z";
        check(isolated(expected).equals(BChatDisplayTime.receipt(receipt)), "exact receipt " + receipt);
        check(isolated(expected).equals(BChatDisplayTime.groupEvent(group)), "exact group " + group);
    }
    public static void main(String[] args) {
        valid("2026-10-17 12:20:04", "2026-10-17 · 12:20:04 UTC");
        valid("2024-02-29 23:59:59", "2024-02-29 · 23:59:59 UTC");
        valid("2000-02-29 00:00:00", "2000-02-29 · 00:00:00 UTC");
        valid("0001-01-01 00:00:01", "0001-01-01 · 00:00:01 UTC");
        valid("9999-12-31 23:59:58", "9999-12-31 · 23:59:58 UTC");
        check(isolated("0000-02-29 · 01:02:03 UTC").equals(BChatDisplayTime.receipt("0000-02-29 01:02:03")), "existing proleptic receipt year zero");
        check(BChatDisplayTime.groupEvent("0000-02-29T01:02:03Z") == null, "existing group year must be positive");
        check(BChatDisplayTime.receipt(null) == null && BChatDisplayTime.groupEvent(null) == null, "absent never invents a time");
        String[] invalid = {"", "2026-02-29 12:20:04", "1900-02-29 12:20:04", "2026-04-31 12:20:04",
                "2026-00-17 12:20:04", "2026-13-17 12:20:04", "2026-10-00 12:20:04", "2026-10-32 12:20:04",
                "2026-10-17 24:00:00", "2026-10-17 12:60:04", "2026-10-17 12:20:60", "2026-1-17 12:20:04",
                "2026-10-17 2:20:04", "2026-10-17 12:20", "2026-10-17 12:20:04.1", "2026-10-17 12:20:04 UTC",
                " 2026-10-17 12:20:04", "2026-10-17 12:20:04 ", "2026/10/17 12:20:04", "+2026-10-17 12:20:04",
                "-001-10-17 12:20:04", "٢٠٢٦-١٠-١٧ ١٢:٢٠:٠٤", "２０２６-１０-１７ １２:２０:０４",
                "\u20662026-10-17 12:20:04\u2069", "2026-10-17\n12:20:04"};
        for (String value : invalid) {
            check(BChatDisplayTime.receipt(value) == null, "invalid receipt fails closed: " + value);
            check(BChatDisplayTime.groupEvent(value.replace(' ', 'T') + "Z") == null, "invalid group fails closed: " + value);
        }
        check(BChatDisplayTime.receipt("2026-10-17T12:20:04Z") == null, "receipt never accepts group shape");
        check(BChatDisplayTime.groupEvent("2026-10-17 12:20:04") == null, "group never accepts receipt shape");
        for (String value : new String[]{"2026-10-17T12:20:04z", "2026-10-17T12:20:04+00:00", "2026-10-17T12:20:04.000Z", "2026-10-17T12:20:04ZZ"})
            check(BChatDisplayTime.groupEvent(value) == null, "no alternate zone/fraction shape");
        Locale original = Locale.getDefault(), originalFormat = Locale.getDefault(Locale.Category.FORMAT), originalDisplay = Locale.getDefault(Locale.Category.DISPLAY);
        TimeZone originalZone = TimeZone.getDefault();
        try {
            for (Locale locale : new Locale[]{Locale.US, Locale.forLanguageTag("ar-SA-u-nu-arab"), Locale.forLanguageTag("fa-IR"), Locale.forLanguageTag("th-TH-u-ca-buddhist")}) {
                Locale.setDefault(locale);
                for (String zone : new String[]{"UTC", "Pacific/Kiritimati", "America/Los_Angeles"}) {
                    TimeZone.setDefault(TimeZone.getTimeZone(zone));
                    valid("2026-10-17 12:20:04", "2026-10-17 · 12:20:04 UTC");
                    String result = BChatDisplayTime.groupEvent("2026-10-17T12:20:04Z");
                    check(result.charAt(0) == '\u2066' && result.charAt(result.length() - 1) == '\u2069'
                            && result.substring(1, result.length() - 1).matches("[0-9]{4}-[0-9]{2}-[0-9]{2} · [0-9]{2}:[0-9]{2}:[0-9]{2} UTC"), "ASCII digits and exactly one LRI/PDI pair under " + locale + "/" + zone);
                }
            }
        } finally {
            Locale.setDefault(original); Locale.setDefault(Locale.Category.FORMAT, originalFormat); Locale.setDefault(Locale.Category.DISPLAY, originalDisplay); TimeZone.setDefault(originalZone);
        }
        check(Locale.getDefault().equals(original) && TimeZone.getDefault().equals(originalZone), "process defaults restored");
        System.out.println("PASS " + checks + " pure display-time checks; actual production formatter, no UI/wire/auth/clock/zone-conversion claim");
    }
}

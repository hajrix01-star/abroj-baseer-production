import com.baseer.bwork.legacy.AppLocalePolicy;
/** Pure policy tests; Android preference persistence is covered by device instrumentation. */
public final class AppLocalePolicyTest {
    private static int checks;
    private static void check(boolean ok, String reason) { if (!ok) throw new AssertionError(reason); checks++; }
    public static void main(String[] args) {
        check("ar".equals(AppLocalePolicy.language(null)), "existing install defaults to Arabic");
        check("ar".equals(AppLocalePolicy.language("")), "empty preference defaults safely");
        check("ar".equals(AppLocalePolicy.language("fr")), "unsupported persisted locale falls back");
        check("en".equals(AppLocalePolicy.language("en")), "English choice retained");
        check("ar".equals(AppLocalePolicy.language("ar")), "Arabic choice retained");
        check(AppLocalePolicy.rtl("ar"), "Arabic is RTL");
        check(!AppLocalePolicy.rtl("en"), "English is LTR");
        check(!AppLocalePolicy.changed("en", "en"), "same choice avoids unnecessary recreation");
        check(!AppLocalePolicy.changed(null, "ar"), "default Arabic choice avoids recreation");
        check(AppLocalePolicy.changed("ar", "en"), "English selection changes locale");
        check(AppLocalePolicy.changed("en", "ar"), "Arabic selection changes locale");
        for (String invalid : new String[]{null, "", "fr", "en-US", "ar-EG"}) {
            boolean failed = false; try { AppLocalePolicy.changed("ar", invalid); } catch (IllegalArgumentException expected) { failed = true; }
            check(failed, "unsupported selection rejected: " + invalid);
        }
        System.out.println("PASS " + checks + " locale policy checks (no Android runtime)");
    }
}

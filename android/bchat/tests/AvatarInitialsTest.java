package com.baseer.freshchat;

public final class AvatarInitialsTest {
    private static int checks;
    private static void equals(String expected, String source) {
        String actual = AvatarInitials.of(source);
        if (!expected.equals(actual)) throw new AssertionError(source + " -> " + actual + " != " + expected);
        checks++;
    }
    public static void main(String[] args) {
        equals("?", null);
        equals("?", "  ");
        equals("أ م", "أحمد محمد");
        equals("عَ م", "عَلي محمد");
        equals("B", "BChat");
        equals("A M", "  Ali   Mohamed  ");
        equals("😀", "😀Test");
        equals("👩🏽‍💻", "👩🏽‍💻Admin");
        equals("👨‍👩‍👧‍👦", "👨‍👩‍👧‍👦Family");
        equals("🇸🇦", "🇸🇦🇬🇧");
        equals("1️⃣", "1️⃣Group");
        equals("شّ", "شّمس");
        equals("👋🏿 أ", "👋🏿 أحمد");
        System.out.println("PASS " + checks + " grapheme initials checks (production Java class)");
    }
}

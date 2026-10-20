package com.baseer.bwork.legacy;

public final class CompanyLabelTest {
    private static void equal(String actual, String expected) {
        if (!expected.equals(actual)) throw new AssertionError(actual + " != " + expected);
    }

    public static void main(String[] args) {
        equal(CompanyLabel.choose("أرز | ARZ", "أرز", "ARZ", true), "أرز");
        equal(CompanyLabel.choose("أرز | ARZ", "أرز", "ARZ", false), "ARZ");
        equal(CompanyLabel.choose("أرز", "أرز", "", false), "أرز");
        equal(CompanyLabel.choose("أرز | ARZ", "", "", false), "ARZ");
        equal(CompanyLabel.choose("أرز | ARZ", "أرز", "", false), "ARZ");
        equal(CompanyLabel.choose("ARZ | أرز", "", "", true), "أرز");
        equal(CompanyLabel.choose("SHAMI TAX | SHAMI TAX", "", "", true), "SHAMI TAX");
        equal(CompanyLabel.choose("أرز | ARZ | backup", "", "", false), "ARZ");
        equal(CompanyLabel.choose("أرز", "", "", false), "أرز");
    }
}

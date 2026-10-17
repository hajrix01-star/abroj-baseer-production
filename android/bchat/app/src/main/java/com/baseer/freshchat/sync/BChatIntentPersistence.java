package com.baseer.freshchat.sync;

import android.content.SharedPreferences;

/** Exact compare-and-commit on the serial storage lane. A memory hit is not durability. */
public final class BChatIntentPersistence {
    public interface Store {
        String read(String key);
        boolean commit(String key, String value);
    }

    public static Store preferences(SharedPreferences preferences) {
        return new Store() {
            public String read(String key) { return preferences.getString(key, null); }
            public boolean commit(String key, String value) {
                SharedPreferences.Editor edit = preferences.edit();
                return (value == null ? edit.remove(key) : edit.putString(key, value)).commit();
            }
        };
    }

    /** Preserve the existing long-valued receipt-share format; never migrate it to a string. */
    public static Store longPreferences(SharedPreferences preferences) {
        return new Store() {
            public String read(String key) {
                return preferences.contains(key) ? Long.toString(preferences.getLong(key, 0)) : null;
            }
            public boolean commit(String key, String value) {
                SharedPreferences.Editor edit = preferences.edit();
                return (value == null ? edit.remove(key)
                        : edit.putLong(key, Long.parseLong(value))).commit();
            }
        };
    }

    public static boolean replace(Store store, String key, String expected, String value) {
        String current = store.read(key);
        if (!(expected == null ? current == null : expected.equals(current))) return false;
        // Always commit, including retry of the same raw value: a previous false commit may
        // already have changed SharedPreferences' memory without changing its disk file.
        boolean saved;
        try { saved = store.commit(key, value); }
        catch (RuntimeException failure) {
            restoreUncertainDelete(store, key, expected, value);
            throw failure;
        }
        if (!saved && value == null && expected != null && store.read(key) == null) {
            // A failed deletion also mutates SharedPreferences memory. Restore the uncertain
            // UUID there (and disk if possible), so review/replay remains available.
            restoreUncertainDelete(store, key, expected, value);
        }
        return saved;
    }

    private static void restoreUncertainDelete(Store store, String key, String expected, String value) {
        if (value != null || expected == null) return;
        try { if (store.read(key) == null) store.commit(key, expected); }
        catch (RuntimeException ignored) { /* Original failure is still surfaced, never success. */ }
    }

    public static boolean markerThenRetire(Store pending, String key, String expected,
            Store markers, String markerKey, String markerValue) {
        if (!expected.equals(pending.read(key))) return false;
        String existingMarker = markers.read(markerKey);
        if (existingMarker != null && !existingMarker.equals(markerValue)) return false;
        if (!markers.commit(markerKey, markerValue)) return false;
        return replace(pending, key, expected, null);
    }

    private BChatIntentPersistence() { }
}

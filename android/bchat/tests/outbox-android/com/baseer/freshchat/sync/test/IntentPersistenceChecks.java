package com.baseer.freshchat.sync.test;

import android.content.Context;
import android.content.SharedPreferences;
import com.baseer.freshchat.sync.BChatIntentPersistence;
import java.util.*;

/** Failure store deliberately reproduces Android commit(false)'s in-memory mutation. */
public final class IntentPersistenceChecks {
    private static int checks;
    private static void check(boolean condition) {
        checks++; if (!condition) throw new AssertionError("Intent persistence " + checks);
    }
    static final class Store implements BChatIntentPersistence.Store {
        final Map<String,String> memory = new HashMap<>(), disk = new HashMap<>();
        final List<String> writes;
        final String name;
        int fail, throwsNext;
        Store(String name, List<String> writes) { this.name = name; this.writes = writes; }
        public String read(String key) { return memory.get(key); }
        public boolean commit(String key, String value) {
            writes.add(name + ":" + (value == null ? "delete" : value));
            if (value == null) memory.remove(key); else memory.put(key, value);
            if (throwsNext-- > 0) throw new IllegalStateException("injected commit exception");
            if (fail-- > 0) return false;
            if (value == null) disk.remove(key); else disk.put(key, value);
            return true;
        }
        void restart() { memory.clear(); memory.putAll(disk); }
    }
    public static int run(Context context) throws Exception {
        checks = 0;
        final String key = "synthetic-account", raw = "{\"client_uuid\":\"same-uuid\",\"quantity\":\"3.50\"}";
        List<String> writes = new ArrayList<>();
        Store pending = new Store("pending", writes), marker = new Store("marker", writes);
        pending.fail = 1;
        check(!BChatIntentPersistence.replace(pending, key, null, raw));
        check(raw.equals(pending.read(key)) && pending.disk.isEmpty());
        int beforeRetry = writes.size();
        check(BChatIntentPersistence.replace(pending, key, raw, raw));
        check(writes.size() == beforeRetry + 1 && raw.equals(pending.disk.get(key)));
        pending.restart(); check(raw.equals(pending.read(key)));
        check(!BChatIntentPersistence.replace(pending, key, "other-uuid", null));
        check(raw.equals(pending.read(key)));
        pending.fail = 1;
        check(!BChatIntentPersistence.replace(pending, key, raw, null));
        check(raw.equals(pending.read(key)) && raw.equals(pending.disk.get(key)));
        pending.throwsNext = 1;
        try { BChatIntentPersistence.replace(pending, key, raw, null); throw new AssertionError("Expected commit exception"); }
        catch (IllegalStateException expected) { check(raw.equals(pending.read(key))); }
        pending.restart(); check(raw.equals(pending.read(key)));
        marker.fail = 1; writes.clear();
        check(!BChatIntentPersistence.markerThenRetire(pending, key, raw, marker, "order:9", "1"));
        check(writes.equals(Collections.singletonList("marker:1")) && raw.equals(pending.read(key)));
        pending.restart(); marker.restart(); check(marker.read("order:9") == null && raw.equals(pending.read(key)));
        pending.fail = 1; writes.clear();
        check(!BChatIntentPersistence.markerThenRetire(pending, key, raw, marker, "order:9", "1"));
        check(writes.get(0).equals("marker:1") && writes.get(1).equals("pending:delete"));
        pending.restart(); marker.restart();
        check("1".equals(marker.read("order:9")) && raw.equals(pending.read(key)));
        check(BChatIntentPersistence.markerThenRetire(pending, key, raw, marker, "order:9", "1"));
        pending.restart(); check(pending.read(key) == null && "1".equals(marker.read("order:9")));
        pending.commit(key, "newer-uuid"); writes.clear();
        check(!BChatIntentPersistence.markerThenRetire(pending, key, raw, marker, "order:9", "1") && writes.isEmpty());
        check("newer-uuid".equals(pending.read(key)));
        marker.commit("order:9", "2"); writes.clear();
        check(!BChatIntentPersistence.markerThenRetire(pending, key, "newer-uuid", marker, "order:9", "1"));
        check(writes.isEmpty() && "2".equals(marker.read("order:9")) && "newer-uuid".equals(pending.read(key)));
        // Actual Android preferences adapter keeps the released long marker format intact.
        SharedPreferences actual = context.getSharedPreferences("intent-persistence-test", 0);
        check(actual.edit().clear().commit());
        BChatIntentPersistence.Store longs = BChatIntentPersistence.longPreferences(actual);
        check(BChatIntentPersistence.replace(longs, "order:9", null, "7"));
        check(actual.getAll().get("order:9") instanceof Long && actual.getLong("order:9", 0) == 7);
        check(BChatIntentPersistence.replace(longs, "order:9", "7", "7"));
        check(!BChatIntentPersistence.replace(longs, "order:9", "8", null));
        check(BChatIntentPersistence.replace(longs, "order:9", "7", null));
        check(!actual.contains("order:9"));
        actual.edit().clear().commit();
        return checks;
    }
    private IntentPersistenceChecks() { }
}

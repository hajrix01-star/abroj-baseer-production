package org.json;

import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/** Explicit semantic object-map adapter: no text parsing, coercion, HTTP or Android claim. */
public final class JSONObject {
    public static final Object NULL = new Object();
    private final Map<String, Object> values = new LinkedHashMap<>();
    public JSONObject put(String key, Object value) throws JSONException {
        if (key == null) throw new JSONException("Null fixture key");
        if (value == null) values.remove(key); else values.put(key, value);
        return this;
    }
    public boolean has(String key) { return values.containsKey(key); }
    public Object opt(String key) { return values.get(key); }
    public Object remove(String key) { return values.remove(key); }
    public int length() { return values.size(); }
    public Iterator<String> keys() { return values.keySet().iterator(); }
}

package org.json;

import com.google.gson.JsonArray;
import java.util.*;

/** Structured object-array adapter; never packaged into the product. */
public final class JSONArray {
    private final List<Object> values = new ArrayList<>();
    public JSONArray put(Object value) { values.add(value == null ? JSONObject.NULL : value); return this; }
    public int length() { return values.size(); }
    public Object opt(int index) { return index >= 0 && index < values.size() ? values.get(index) : null; }
    public JSONObject getJSONObject(int index) {
        Object value = opt(index);
        if (!(value instanceof JSONObject)) throw new IllegalArgumentException("Expected fixture object at " + index);
        return (JSONObject)value;
    }
    JsonArray tree() { JsonArray result = new JsonArray(); for (Object value : values) result.add(JSONObject.tree(value)); return result; }
    public String toString() { return tree().toString(); }
}

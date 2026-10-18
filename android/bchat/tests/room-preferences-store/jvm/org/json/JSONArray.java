package org.json;
import com.google.gson.JsonArray;
import java.util.*;
public final class JSONArray {
    private final List<Object> values = new ArrayList<>();
    public JSONArray put(Object value) { values.add(value == null ? JSONObject.NULL : value); return this; }
    public int length() { return values.size(); }
    public Object opt(int index) { return index >= 0 && index < values.size() ? values.get(index) : null; }
    JsonArray tree() { JsonArray array = new JsonArray(); for (Object value : values) array.add(JSONObject.tree(value)); return array; }
    @Override public String toString() { return tree().toString(); }
}

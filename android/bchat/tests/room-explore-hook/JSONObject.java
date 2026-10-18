package org.json;

import com.google.gson.*;
import java.util.*;

/** Test-only Gson object API adapter. Not Android JSON parsing/coercion evidence. */
public final class JSONObject {
    public static final Object NULL = new Object();
    private final Map<String, Object> values = new LinkedHashMap<>();
    public JSONObject() { }
    public JSONObject(String text) {
        JsonElement parsed = JsonParser.parseString(text);
        if (!parsed.isJsonObject()) throw new IllegalArgumentException("Expected fixture object");
        for (Map.Entry<String, JsonElement> entry : parsed.getAsJsonObject().entrySet())
            values.put(entry.getKey(), convert(entry.getValue()));
    }
    static Object convert(JsonElement value) {
        if (value.isJsonNull()) return NULL;
        if (value.isJsonObject()) return new JSONObject(value.toString());
        if (value.isJsonArray()) {
            JSONArray result = new JSONArray();
            for (JsonElement child : value.getAsJsonArray()) result.put(convert(child));
            return result;
        }
        JsonPrimitive primitive = value.getAsJsonPrimitive();
        if (primitive.isBoolean()) return primitive.getAsBoolean();
        if (primitive.isString()) return primitive.getAsString();
        String raw = primitive.getAsString();
        if (raw.matches("-?[0-9]+")) {
            long integer = Long.parseLong(raw);
            return integer >= Integer.MIN_VALUE && integer <= Integer.MAX_VALUE ? (Number)(int)integer : integer;
        }
        return Double.valueOf(raw);
    }
    static JsonElement tree(Object value) {
        if (value == null || value == NULL) return JsonNull.INSTANCE;
        if (value instanceof JSONObject) {
            JsonObject result = new JsonObject();
            for (Map.Entry<String,Object> entry : ((JSONObject)value).values.entrySet())
                result.add(entry.getKey(), tree(entry.getValue()));
            return result;
        }
        if (value instanceof JSONArray) return ((JSONArray)value).tree();
        if (value instanceof Boolean) return new JsonPrimitive((Boolean)value);
        if (value instanceof Number) return new JsonPrimitive((Number)value);
        return new JsonPrimitive((String)value);
    }
    public JSONObject put(String key, Object value) {
        if (key == null) throw new IllegalArgumentException("Null fixture key");
        if (value == null) values.remove(key); else values.put(key, value);
        return this;
    }
    public Object get(String key) {
        if (!values.containsKey(key)) throw new IllegalArgumentException("Missing fixture key " + key);
        return values.get(key);
    }
    public String getString(String key) {
        Object value = get(key);
        if (!(value instanceof String)) throw new IllegalArgumentException("Expected fixture string " + key);
        return (String)value;
    }
    public boolean getBoolean(String key) {
        Object value = get(key);
        if (!(value instanceof Boolean)) throw new IllegalArgumentException("Expected fixture boolean " + key);
        return (Boolean)value;
    }
    public int getInt(String key) {
        Object value = get(key);
        if (!(value instanceof Number)) throw new IllegalArgumentException("Expected fixture number " + key);
        return ((Number)value).intValue();
    }
    public JSONObject getJSONObject(String key) {
        Object value = get(key);
        if (!(value instanceof JSONObject)) throw new IllegalArgumentException("Expected fixture object " + key);
        return (JSONObject)value;
    }
    public JSONArray getJSONArray(String key) {
        Object value = get(key);
        if (!(value instanceof JSONArray)) throw new IllegalArgumentException("Expected fixture array " + key);
        return (JSONArray)value;
    }
    public Object opt(String key) { return values.get(key); }
    public long optLong(String key) { Object value = opt(key); return value instanceof Number ? ((Number)value).longValue() : 0; }
    public JSONObject optJSONObject(String key) { Object value = opt(key); return value instanceof JSONObject ? (JSONObject)value : null; }
    public boolean optBoolean(String key, boolean fallback) { Object value = opt(key); return value instanceof Boolean ? (Boolean)value : fallback; }
    public boolean has(String key) { return values.containsKey(key); }
    public boolean isNull(String key) { return !has(key) || opt(key) == NULL; }
    public int length() { return values.size(); }
    public Iterator<String> keys() { return values.keySet().iterator(); }
    public Object remove(String key) { return values.remove(key); }
    public String toString() { return tree(this).toString(); }
}

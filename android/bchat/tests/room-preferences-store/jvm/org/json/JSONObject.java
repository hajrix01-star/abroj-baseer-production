package org.json;

import com.google.gson.*;
import java.util.*;

/** Existing Gradle Gson-backed API adapter for disk tests, never a product/wire parser. */
public final class JSONObject {
    public static final Object NULL = new Object();
    private static final Gson JSON = new GsonBuilder().disableHtmlEscaping().create();
    private final Map<String, Object> values = new LinkedHashMap<>();
    public JSONObject() { }
    public JSONObject(String text) throws JSONException {
        try {
            JsonElement element = JsonParser.parseString(text);
            if (!element.isJsonObject()) throw new IllegalArgumentException();
            for (Map.Entry<String, JsonElement> entry : element.getAsJsonObject().entrySet()) values.put(entry.getKey(), convert(entry.getValue()));
        } catch (RuntimeException error) { throw new JSONException("Invalid fixture JSON"); }
    }
    static Object convert(JsonElement element) throws JSONException {
        if (element.isJsonNull()) return NULL;
        if (element.isJsonObject()) return new JSONObject(element.toString());
        if (element.isJsonArray()) {
            JSONArray array = new JSONArray(); for (JsonElement value : element.getAsJsonArray()) array.put(convert(value)); return array;
        }
        JsonPrimitive value = element.getAsJsonPrimitive();
        if (value.isBoolean()) return value.getAsBoolean();
        if (value.isString()) return value.getAsString();
        String raw = value.getAsString();
        if (raw.matches("-?[0-9]+")) try {
            long number = Long.parseLong(raw);
            if (number >= Integer.MIN_VALUE && number <= Integer.MAX_VALUE) return (int) number;
            return number;
        } catch (NumberFormatException ignored) { }
        return Double.valueOf(raw);
    }
    static JsonElement tree(Object value) {
        if (value == null || value == NULL) return JsonNull.INSTANCE;
        if (value instanceof JSONObject) {
            JsonObject object = new JsonObject();
            for (Map.Entry<String, Object> entry : ((JSONObject) value).values.entrySet()) object.add(entry.getKey(), tree(entry.getValue()));
            return object;
        }
        if (value instanceof JSONArray) return ((JSONArray) value).tree();
        if (value instanceof Boolean) return new JsonPrimitive((Boolean) value);
        if (value instanceof Number) return new JsonPrimitive((Number) value);
        return new JsonPrimitive((String) value);
    }
    public JSONObject put(String key, Object value) throws JSONException {
        if (key == null) throw new JSONException("Invalid fixture key");
        if (value == null) values.remove(key); else values.put(key, value); return this;
    }
    public Object opt(String key) { return values.get(key); }
    public boolean has(String key) { return values.containsKey(key); }
    public int length() { return values.size(); }
    public Iterator<String> keys() { return values.keySet().iterator(); }
    public Object remove(String key) { return values.remove(key); }
    public static String quote(String value) { return JSON.toJson(value); }
    @Override public String toString() { return tree(this).toString(); }
}

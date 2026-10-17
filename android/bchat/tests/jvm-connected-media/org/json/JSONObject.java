package org.json;

import com.google.gson.*;

/** Test-only Android JSONObject surface using the existing Gradle Gson jar; never packaged. */
public final class JSONObject {
    private final JsonObject object;
    public JSONObject() { object = new JsonObject(); }
    public JSONObject(String json) { object = JsonParser.parseString(json).getAsJsonObject(); }
    public JSONObject put(String key, Object value) {
        if (value instanceof Number) object.addProperty(key, (Number)value);
        else if (value instanceof Boolean) object.addProperty(key, (Boolean)value);
        else if (value instanceof String) object.addProperty(key, (String)value);
        else if (value == null) object.add(key, JsonNull.INSTANCE);
        else throw new IllegalArgumentException("Unsupported fixture field");
        return this;
    }
    private JsonElement required(String key) {
        JsonElement value = object.get(key);
        if (value == null || value.isJsonNull()) throw new IllegalArgumentException(key);
        return value;
    }
    public String getString(String key) { return required(key).getAsString(); }
    public long getLong(String key) { return required(key).getAsLong(); }
    public int getInt(String key) { return required(key).getAsInt(); }
    public String optString(String key, String fallback) { return object.has(key) ? getString(key) : fallback; }
    public int optInt(String key, int fallback) { return object.has(key) ? getInt(key) : fallback; }
    public long optLong(String key, long fallback) { return object.has(key) ? getLong(key) : fallback; }
    /** Primitive-only fixture surface; removal mutates the object like Android JSONObject. */
    public Object remove(String key) {
        JsonElement previous = object.remove(key);
        if (previous == null || previous.isJsonNull()) return null;
        JsonPrimitive primitive = previous.getAsJsonPrimitive();
        if (primitive.isBoolean()) return primitive.getAsBoolean();
        if (primitive.isNumber()) return primitive.getAsNumber();
        return primitive.getAsString();
    }
    public String toString() { return object.toString(); }
}

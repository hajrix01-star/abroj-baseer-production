package com.baseer.freshchat.sync;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Bounded, all-or-nothing cursor accumulator. The server alone supplies availability and prices. */
public final class BChatCartResolver {
    private final List<Long> requested;
    private final LinkedHashMap<Long, JSONObject> items = new LinkedHashMap<>();
    private final Set<Long> missing = new LinkedHashSet<>();
    private int processed;
    private boolean complete;
    public BChatCartResolver(Collection<Long> ids) {
        TreeSet<Long> sorted = new TreeSet<>();
        for (Long id : ids) if (id == null || id <= 0 || id > Integer.MAX_VALUE || !sorted.add(id))
            throw new IllegalArgumentException("Invalid cart identifiers");
        if (sorted.isEmpty() || sorted.size() > 100) throw new IllegalArgumentException("Invalid cart size");
        requested = Collections.unmodifiableList(new ArrayList<>(sorted));
    }
    public List<Long> requested() { return requested; }
    public long afterId() { return processed == 0 ? 0 : requested.get(processed - 1); }
    public boolean complete() { return complete; }
    public Map<Long, JSONObject> items() {
        if (!complete) throw new IllegalStateException("Incomplete cart");
        return Collections.unmodifiableMap(items);
    }
    public Set<Long> missingIds() {
        if (!complete) throw new IllegalStateException("Incomplete cart");
        return Collections.unmodifiableSet(missing);
    }
    public void accept(JSONObject response) throws Exception {
        if (complete || response == null || response.toString().getBytes(StandardCharsets.UTF_8).length > 65536
                || id(response.get("api_version")) != 2) throw new IllegalArgumentException("Invalid cart page");
        JSONArray done = response.getJSONArray("processed_option_ids");
        JSONArray supplied = response.getJSONArray("items"), absent = response.getJSONArray("missing_ids");
        if (done.length() < 1 || done.length() > 24 || processed + done.length() > requested.size()
                || supplied.length() + absent.length() != done.length())
            throw new IllegalArgumentException("Invalid cart page boundary");
        Set<Long> page = new LinkedHashSet<>();
        for (int i = 0; i < done.length(); i++) {
            long value = id(done.get(i));
            if (value != requested.get(processed + i)) throw new IllegalArgumentException("Cart cursor skipped identifiers");
            page.add(value);
        }
        Map<Long, JSONObject> nextItems = new LinkedHashMap<>();
        Set<Long> nextMissing = new LinkedHashSet<>(), accounted = new HashSet<>();
        for (int i = 0; i < supplied.length(); i++) {
            JSONObject item = supplied.getJSONObject(i);
            long value = id(item.get("id"));
            if (!page.contains(value) || !accounted.add(value)) throw new IllegalArgumentException("Unexpected cart item");
            nextItems.put(value, item);
        }
        for (int i = 0; i < absent.length(); i++) {
            long value = id(absent.get(i));
            if (!page.contains(value) || !accounted.add(value)) throw new IllegalArgumentException("Unexpected missing item");
            nextMissing.add(value);
        }
        boolean finalPage = processed + done.length() == requested.size();
        Object cursor = response.get("next_after_option_id");
        if (finalPage ? cursor != JSONObject.NULL : id(cursor) != requested.get(processed + done.length() - 1))
            throw new IllegalArgumentException("Invalid next cart cursor");
        items.putAll(nextItems); missing.addAll(nextMissing);
        processed += done.length(); complete = finalPage;
    }
    private static long id(Object value) {
        if (!(value instanceof Number) || !value.toString().matches("[1-9][0-9]*"))
            throw new IllegalArgumentException("Invalid cart identifier");
        long result = ((Number) value).longValue();
        if (result <= 0 || result > Integer.MAX_VALUE) throw new IllegalArgumentException("Invalid cart identifier");
        return result;
    }
}

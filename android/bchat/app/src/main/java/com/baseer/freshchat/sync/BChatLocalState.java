package com.baseer.freshchat.sync;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Untrusted restoration intent, never an authorization, price, quote, session or sent order. */
public final class BChatLocalState {
    public final String section, taskFilter, purchaseRoute;
    public final long companyId, roomId, membershipId, anchorMessageId, cartCompanyId, warehouseId, representativeId;
    public final int anchorOffset;
    public final Map<Long, String> cart;

    public BChatLocalState(String section, long companyId, long roomId, long membershipId,
                           long anchorMessageId, int anchorOffset, String taskFilter,
                           long cartCompanyId, long warehouseId, long representativeId, String route, Map<Long, String> cart) {
        if (!("chats".equals(section) || "tasks".equals(section) || "orders".equals(section))
                || companyId < 0 || roomId < 0 || membershipId < 0 || anchorMessageId < 0
                || cartCompanyId < 0 || warehouseId < 0 || representativeId < 0 || Math.abs((long)anchorOffset) > 100000
                || !("open".equals(taskFilter) || "new".equals(taskFilter) || "in_progress".equals(taskFilter)
                || "done".equals(taskFilter) || "cancelled".equals(taskFilter))
                || !("representative".equals(route) || "cash".equals(route) || "bank_transfer".equals(route))
                || cart == null || cart.size() > 100 || (roomId == 0) != (membershipId == 0))
            throw new IllegalArgumentException("Invalid local restoration intent");
        Map<Long, String> checked = new LinkedHashMap<>();
        for (Map.Entry<Long, String> line : cart.entrySet()) {
            OutboxPolicy.requireRecordId(line.getKey());
            if (line.getValue() == null || !line.getValue().matches("[0-9]{1,14}(\\.[0-9]{1,2})?")
                    || new java.math.BigDecimal(line.getValue()).signum() <= 0)
                throw new IllegalArgumentException("Invalid raw cart quantity");
            checked.put(line.getKey(), line.getValue());
        }
        this.section = section; this.companyId = companyId; this.roomId = roomId;
        this.membershipId = membershipId; this.anchorMessageId = anchorMessageId;
        this.anchorOffset = anchorOffset; this.taskFilter = taskFilter;
        this.cartCompanyId = cartCompanyId;
        this.warehouseId = warehouseId; this.representativeId = representativeId;
        purchaseRoute = route; this.cart = Collections.unmodifiableMap(checked);
    }

    public String toJson() {
        try {
            JSONObject object = new JSONObject();
            object.put("version", 1); object.put("section", section); object.put("company_id", companyId);
            object.put("room_id", roomId); object.put("membership_id", membershipId);
            object.put("anchor_id", anchorMessageId); object.put("anchor_offset", anchorOffset);
            object.put("task_filter", taskFilter); object.put("warehouse_id", warehouseId);
            object.put("cart_company_id", cartCompanyId);
            object.put("representative_id", representativeId); object.put("route", purchaseRoute);
            JSONArray lines = new JSONArray();
            for (Map.Entry<Long, String> line : cart.entrySet())
                lines.put(new JSONObject().put("option_id", line.getKey()).put("quantity", line.getValue()));
            object.put("cart", lines); return object.toString();
        } catch (Exception invalid) { throw new IllegalArgumentException("Invalid local context", invalid); }
    }

    public static BChatLocalState fromJson(String json) {
        try {
            if (json == null || json.getBytes(StandardCharsets.UTF_8).length > 32 * 1024)
                throw new IllegalArgumentException("Context exceeds local bound");
            JSONObject object = new JSONObject(json);
            if (object.getInt("version") != 1) throw new IllegalArgumentException("Unknown local context");
            JSONArray list = object.getJSONArray("cart");
            if (list.length() > 100) throw new IllegalArgumentException("Cart exceeds local bound");
            Map<Long, String> cart = new LinkedHashMap<>();
            for (int i = 0; i < list.length(); i++) {
                JSONObject line = list.getJSONObject(i);
                if (cart.put(line.getLong("option_id"), line.getString("quantity")) != null)
                    throw new IllegalArgumentException("Duplicate cart option");
            }
            return new BChatLocalState(object.getString("section"), object.getLong("company_id"),
                    object.getLong("room_id"), object.getLong("membership_id"), object.getLong("anchor_id"),
                    object.getInt("anchor_offset"), object.getString("task_filter"), object.getLong("cart_company_id"), object.getLong("warehouse_id"),
                    object.getLong("representative_id"), object.getString("route"), cart);
        } catch (Exception invalid) { throw new IllegalArgumentException("Invalid local context", invalid); }
    }
}

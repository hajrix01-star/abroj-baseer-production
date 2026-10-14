package com.baseer.freshchat.sync;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Versioned immutable request. Construct once; every retry uses the same UUID and payload. */
public final class MessageRequest {
    public final long companyId;
    public final long channelId;
    public final String clientUuid;
    public final String payload;
    public final String payloadHash;

    public MessageRequest(long companyId, long channelId, String clientUuid, String text,
                          long[] attachmentIds, Long replyToId) {
        OutboxPolicy.requireRecordId(companyId);
        OutboxPolicy.requireRecordId(channelId);
        OutboxPolicy.requireText(text);
        if (replyToId != null) OutboxPolicy.requireRecordId(replyToId);
        if (attachmentIds == null || attachmentIds.length > OutboxPolicy.MAX_ATTACHMENTS) {
            throw new IllegalArgumentException("Invalid attachment list");
        }
        this.companyId = companyId;
        this.channelId = channelId;
        this.clientUuid = OutboxPolicy.requireUuid(clientUuid);
        JSONArray attachments = new JSONArray();
        java.util.Set<Long> seen = new java.util.HashSet<>();
        for (long id : attachmentIds) {
            OutboxPolicy.requireRecordId(id);
            if (!seen.add(id)) throw new IllegalArgumentException("Attachment IDs must be unique and positive");
            attachments.put(id);
        }
        try {
            JSONObject value = new JSONObject();
            value.put("api_version", 1);
            value.put("company_id", companyId);
            value.put("channel_id", channelId);
            value.put("client_uuid", this.clientUuid);
            value.put("text", text);
            value.put("attachment_ids", attachments);
            value.put("reply_to_id", replyToId == null ? JSONObject.NULL : replyToId);
            this.payload = value.toString();
            OutboxPolicy.requirePayload(this.payload);
            this.payloadHash = AccountScope.sha256(payload);
        } catch (JSONException impossible) { throw new IllegalStateException(impossible); }
    }
}

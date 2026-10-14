package com.baseer.freshchat.sync.test;

import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.BChatConnectedMediaStore;
import com.baseer.freshchat.sync.BChatV2Outbox;
import com.baseer.freshchat.sync.DurableOutbox;
import com.baseer.freshchat.sync.MessageRequest;
import com.baseer.freshchat.sync.OutboxPolicy;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.UUID;

/** Explicit, disposable-device test. It uses only this test APK's own database namespace. */
public final class OutboxInstrumentation extends Instrumentation {
    private int assertions;
    private void check(boolean value) { assertions++; if (!value) throw new AssertionError("Assertion " + assertions); }
    private void rejects(Runnable action) {
        assertions++;
        try { action.run(); throw new AssertionError("Expected rejection " + assertions); }
        catch (IllegalArgumentException expected) { }
    }
    private void rejectsIo(IoAction action) throws Exception {
        assertions++;
        try { action.run(); throw new AssertionError("Expected IO rejection " + assertions); }
        catch (IOException expected) { }
    }
    private interface IoAction { void run() throws Exception; }

    /** The test package owns these synthetic files; no Odoo request or real account is involved. */
    private void mediaExpiryRecovery(Context context) throws Exception {
        AccountScope scope = new AccountScope("https://media-expiry.invalid", "media-expiry-" + UUID.randomUUID(), 1);
        String localUuid = UUID.randomUUID().toString();
        String clientUuid = UUID.randomUUID().toString();
        File directory = new File(context.getFilesDir(), "bchat-v2-media/" + scope.key);
        check(directory.mkdirs());
        File original = new File(directory, localUuid + ".bin");
        File metadata = new File(directory, localUuid + ".json");
        byte[] bytes = "synthetic original media bytes".getBytes(StandardCharsets.UTF_8);
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder hex = new StringBuilder(64);
        for (byte value : digest) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        try {
            try (FileOutputStream output = new FileOutputStream(original)) { output.write(bytes); }
            JSONObject legacy = new JSONObject();
            legacy.put("account_key", scope.key);
            legacy.put("room_id", 17);
            legacy.put("company_id", 3);
            legacy.put("membership_id", 8);
            legacy.put("upload_uuid", localUuid);
            legacy.put("client_uuid", clientUuid);
            legacy.put("kind", "image");
            legacy.put("mime", "image/jpeg");
            legacy.put("name", "photo.jpg");
            legacy.put("size", bytes.length);
            legacy.put("sha256", hex.toString());
            legacy.put("text", "");
            legacy.put("reply_to_message_id", 0);
            legacy.put("media_id", 91);
            try (FileOutputStream output = new FileOutputStream(metadata)) {
                output.write(legacy.toString().getBytes(StandardCharsets.UTF_8));
            }
            BChatConnectedMediaStore store = new BChatConnectedMediaStore(context);
            BChatConnectedMediaStore.Entry old = store.pending(scope, 17, 8);
            check(old != null && old.remoteUploadUuid.isEmpty()
                    && localUuid.equals(old.networkUploadUuid()) && old.mediaId == 91);
            check(!BChatConnectedMediaStore.canRenewExpiredUpload(409, "upload_closed", false));
            check(!BChatConnectedMediaStore.canRenewExpiredUpload(409, "cancelled", false));
            check(!BChatConnectedMediaStore.canRenewExpiredUpload(400, "upload_expired", false));
            check(!BChatConnectedMediaStore.canRenewExpiredUpload(409, "upload_expired", true));
            check(BChatConnectedMediaStore.canRenewExpiredUpload(409, "upload_expired", false));
            rejectsIo(() -> store.renewExpiredUpload(scope, old, "upload_closed"));
            rejectsIo(() -> store.renewExpiredUpload(scope, old, "cancelled"));
            BChatConnectedMediaStore.Entry renewed = store.renewExpiredUpload(scope, old, "upload_expired");
            check(!localUuid.equals(renewed.networkUploadUuid()) && renewed.mediaId == 0);
            check(localUuid.equals(renewed.uploadUuid) && clientUuid.equals(renewed.clientUuid)
                    && hex.toString().equals(renewed.sha256) && renewed.size == bytes.length);
            check(renewed.networkUploadUuid().equals(renewed.uploadMetadata().getString("upload_uuid")));
            check(Arrays.equals(bytes, Files.readAllBytes(original.toPath())));
            check(directory.listFiles((folder, name) -> name.endsWith(".json")).length == 1);
            rejectsIo(() -> store.markUploaded(scope, old, 91));
            rejectsIo(() -> store.renewExpiredUpload(scope, old, "upload_expired"));
            BChatConnectedMediaStore reopened = new BChatConnectedMediaStore(context);
            BChatConnectedMediaStore.Entry afterKill = reopened.pending(scope, 17, 8);
            check(afterKill != null && renewed.networkUploadUuid().equals(afterKill.networkUploadUuid())
                    && clientUuid.equals(afterKill.clientUuid) && afterKill.mediaId == 0);
            check(afterKill.networkUploadUuid().equals(afterKill.uploadMetadata().getString("upload_uuid")));
            BChatConnectedMediaStore.Entry uploaded = reopened.markUploaded(scope, afterKill, 92);
            check(uploaded.mediaId == 92 && clientUuid.equals(uploaded.clientUuid));
            reopened.acknowledge(scope, uploaded);
            check(reopened.pending(scope, 17, 8) == null && !metadata.exists());
            rejectsIo(() -> reopened.renewExpiredUpload(scope, uploaded, "upload_expired"));
        } finally {
            metadata.delete();
            original.delete();
            directory.delete();
        }
    }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        Context context = getContext();
        DurableOutbox box = null;
        BChatV2Outbox textBox = null;
        try {
            if (!"com.baseer.freshchat.outbox.test".equals(context.getPackageName())) {
                throw new IllegalStateException("Refusing to touch a non-test database namespace");
            }
            context.deleteDatabase("bchat-authenticated-outbox.db");
            box = new DurableOutbox(context);
            AccountScope a = new AccountScope("https://example.invalid", "qa", 1);
            AccountScope b = new AccountScope("https://example.invalid", "qa", 2);
            AccountScope otherOrigin = new AccountScope("https://qa.example.invalid", "qa", 1);
            MessageRequest message = new MessageRequest(1, 10, "550e8400-e29b-41d4-a716-446655440000", "Test", new long[0], null);
            DurableOutbox.Entry first = box.enqueue(a, message, 1);
            check(first.id == box.enqueue(a, message, 2).id);
            check(box.find(b, 1, 10, message.clientUuid) == null);
            check(box.claimNext(b, 3) == null);
            check(box.find(otherOrigin, 1, 10, message.clientUuid) == null);
            check(box.claimNext(otherOrigin, 3) == null);
            final DurableOutbox liveBox = box;
            rejects(() -> liveBox.enqueue(a, new MessageRequest(1, 10, message.clientUuid, "Changed", new long[0], null), 3));
            rejects(() -> liveBox.enqueue(a, new MessageRequest(1, 11, message.clientUuid, "Test", new long[0], null), 3));
            DurableOutbox.Entry claim = box.claimNext(a, 3);
            check(claim.attempts == 1);
            check(box.claimNext(a, 4) == null);
            box.close();
            box = new DurableOutbox(context);
            check(box.find(a, 1, 10, message.clientUuid).state == OutboxPolicy.State.IN_FLIGHT);
            DurableOutbox.Entry recovery = box.claimNext(a, 3 + OutboxPolicy.LEASE_MILLIS);
            check(recovery.attempts == 2);
            check(!box.recordFailure(a, claim, OutboxPolicy.Failure.TRANSIENT, 70_000));
            check(box.recordFailure(a, recovery, OutboxPolicy.Failure.TRANSIENT, 70_000));
            check(box.claimNext(a, 79_999) == null);
            DurableOutbox.Entry third = box.claimNext(a, 80_000);
            check(third.attempts == 3);
            final DurableOutbox reopened = box;
            rejects(() -> reopened.acknowledge(a, third, 1, 2, 10, message.clientUuid, 42, "sent"));
            rejects(() -> reopened.acknowledge(b, third, 1, 1, 10, message.clientUuid, 42, "sent"));
            rejects(() -> reopened.acknowledge(a, third, 1, 1, 10, message.clientUuid, 42, "read"));
            box.acknowledge(a, third, 1, 1, 10, message.clientUuid, 42, "sent");
            box.acknowledge(a, third, 1, 1, 10, message.clientUuid, 42, "sent");
            check(box.find(a, 1, 10, message.clientUuid).messageId == 42);
            check(box.find(a, 1, 10, message.clientUuid).state == OutboxPolicy.State.SENT);
            check(!box.recordFailure(a, third, OutboxPolicy.Failure.PERMANENT, 90_000));
            check(box.claimNext(a, 900_000) == null);
            MessageRequest second = new MessageRequest(1, 10, "650e8400-e29b-41d4-a716-446655440000", "Auth", new long[0], null);
            box.enqueue(a, second, 1_000_000);
            box.enqueue(a, new MessageRequest(1, 10, "750e8400-e29b-41d4-a716-446655440000", "Queued behind auth", new long[0], null), 1_000_001);
            DurableOutbox.Entry authClaim = box.claimNext(a, 1_000_000);
            check(box.recordFailure(a, authClaim, OutboxPolicy.Failure.AUTHENTICATION, 1_000_001));
            check(box.claimNext(a, 2_000_000) == null);
            box.close();
            box = new DurableOutbox(context);
            check(box.claimNext(a, 2_000_000) == null);
            check(box.resumeAfterAuthentication(b, 2_000_000) == 0);
            check(box.resumeAfterAuthentication(a, 2_000_000) == 1);
            check(box.claimNext(a, 2_000_000).attempts == 1);

            context.deleteDatabase("bchat-v2-text-outbox.db");
            textBox = new BChatV2Outbox(context);
            BChatV2Outbox.Entry plain = textBox.enqueue(a, 2, 20, "Pending text");
            check(!textBox.acknowledge(b, plain));
            check(textBox.acknowledge(a, plain));
            check(textBox.first(a, 2, 20) == null);
            BChatV2Outbox.Entry reply = textBox.enqueue(a, 2, 20, "Reply text", 42);
            check(textBox.convertToDraft(a, reply, 2, 20, false));
            check("Reply text".equals(textBox.draft(a, 2, 20)));
            check(textBox.first(a, 2, 20) == null);
            BChatV2Outbox.Entry discarded = textBox.enqueuePreservingDraft(a, 2, 20, "Discard text");
            check(textBox.recordRejected(a, discarded));
            check(!textBox.discard(b, discarded));
            check(textBox.discard(a, discarded));
            check(textBox.first(a, 2, 20) == null);
            mediaExpiryRecovery(context);
            result.putString("stream", "PASS: " + assertions + " outbox and media-expiry assertions\n");
            finish(0, result);
        } catch (Throwable error) {
            result.putString("stream", "FAIL: " + error.getClass().getSimpleName() + ": " + error.getMessage() + "\n");
            finish(1, result);
        } finally {
            if (box != null) box.close();
            if (textBox != null) textBox.close();
            if ("com.baseer.freshchat.outbox.test".equals(context.getPackageName())) {
                context.deleteDatabase("bchat-authenticated-outbox.db");
                context.deleteDatabase("bchat-v2-text-outbox.db");
            }
        }
    }
}

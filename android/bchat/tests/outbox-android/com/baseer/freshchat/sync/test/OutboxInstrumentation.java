package com.baseer.freshchat.sync.test;

import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.database.sqlite.SQLiteDatabase;
import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.BChatConnectedMediaStore;
import com.baseer.freshchat.sync.BChatV2Outbox;
import com.baseer.freshchat.sync.BChatLocalState;
import com.baseer.freshchat.sync.BChatComposerSnapshot;
import com.baseer.freshchat.sync.BChatCartResolver;
import com.baseer.freshchat.sync.BChatStorageRepository;
import com.baseer.freshchat.PermissionPolicyProbe;
import com.baseer.freshchat.PermissionRefreshProbe;
import com.baseer.freshchat.ConnectedAudioProbe;
import com.baseer.freshchat.IntentDispatchProbe;
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
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;

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

    private void localCallbackBarriers() throws Exception {
        check(android.os.Looper.myLooper() != android.os.Looper.getMainLooper());
        AccountScope scope = new AccountScope("https://callback.invalid", "synthetic", 17);
        CountDownLatch started = new CountDownLatch(1), release = new CountDownLatch(1), barrier = new CountDownLatch(1);
        AtomicBoolean staleCallback = new AtomicBoolean(), staleQueuedWork = new AtomicBoolean(), mainCallback = new AtomicBoolean();
        BChatStorageRepository.submit(scope, () -> {
            started.countDown();
            if (!release.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("Test release timed out");
            return true;
        }, (value, error) -> staleCallback.set(true));
        check(started.await(5, TimeUnit.SECONDS));
        BChatStorageRepository.submit(scope, () -> { staleQueuedWork.set(true); return true; },
                (value, error) -> staleCallback.set(true));
        BChatStorageRepository.invalidate(scope);
        BChatStorageRepository.submit(null, () -> Thread.currentThread().getName(), (name, error) -> {
            mainCallback.set(error == null && "bchat-local-storage".equals(name)
                    && android.os.Looper.myLooper() == android.os.Looper.getMainLooper());
            barrier.countDown();
        });
        release.countDown();
        check(barrier.await(5, TimeUnit.SECONDS));
        check(!staleCallback.get() && !staleQueuedWork.get() && mainCallback.get());
    }

    private JSONObject resolvedPage(long[] processed, long[] missing, Long cursor) throws Exception {
        Set<Long> unavailable = new HashSet<>();
        JSONArray done = new JSONArray(), absent = new JSONArray(), items = new JSONArray();
        for (long id : missing) { unavailable.add(id); absent.put(id); }
        for (long id : processed) {
            done.put(id);
            if (!unavailable.contains(id)) items.put(new JSONObject().put("id", id).put("last_price", "2.50"));
        }
        return new JSONObject().put("api_version", 2).put("processed_option_ids", done)
                .put("items", items).put("missing_ids", absent)
                .put("next_after_option_id", cursor == null ? JSONObject.NULL : cursor);
    }

    private void cartAndComposerContracts() throws Exception {
        AccountScope account = new AccountScope("https://composer.invalid", "synthetic", 7);
        BChatComposerSnapshot editor = new BChatComposerSnapshot(account, 11, 13, 17, "body", 19);
        check(editor.matches(account, 11, 13, 17, "body", 19));
        check(!editor.matches(new AccountScope("https://composer.invalid", "synthetic", 8), 11, 13, 17, "body", 19));
        check(!editor.matches(account, 12, 13, 17, "body", 19));
        check(!editor.matches(account, 11, 14, 17, "body", 19));
        check(!editor.matches(account, 11, 13, 18, "body", 19)); // edited, then restored identical characters
        check(!editor.matches(account, 11, 13, 17, "body2", 19));
        check(!editor.matches(account, 11, 13, 17, "body", 20));
        check(!editor.matches(null, 11, 13, 17, "body", 19));
        BChatCartResolver resolver = new BChatCartResolver(Arrays.asList(3L, 1L, 2L));
        check(resolver.requested().equals(Arrays.asList(1L, 2L, 3L)) && resolver.afterId() == 0);
        resolver.accept(resolvedPage(new long[]{1, 2}, new long[]{2}, 2L));
        check(!resolver.complete() && resolver.afterId() == 2);
        try { resolver.items(); throw new AssertionError("Partial cart exposed"); }
        catch (IllegalStateException expected) { check(true); }
        resolver.accept(resolvedPage(new long[]{3}, new long[]{}, null));
        check(resolver.complete() && resolver.items().size() == 2 && resolver.missingIds().equals(Collections.singleton(2L)));
        List<Long> hundred = new ArrayList<>(); for (long id = 1; id <= 100; id++) hundred.add(id);
        BChatCartResolver tinyPages = new BChatCartResolver(hundred);
        for (long id = 1; id <= 100; id++) tinyPages.accept(resolvedPage(new long[]{id}, new long[]{}, id == 100 ? null : id));
        check(tinyPages.complete() && tinyPages.items().size() == 100); // UTF-8 limits can shrink pages below 24
        try { new BChatCartResolver(Arrays.asList(1L, 1L)); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { check(true); }
        hundred.add(101L); rejects(() -> new BChatCartResolver(hundred));
        for (int invalid = 0; invalid < 6; invalid++) {
            BChatCartResolver strict = new BChatCartResolver(Arrays.asList(1L, 2L));
            JSONObject page = resolvedPage(new long[]{1}, new long[]{}, 1L);
            if (invalid == 0) page.put("processed_option_ids", new JSONArray().put(2));
            if (invalid == 1) page.put("next_after_option_id", JSONObject.NULL);
            if (invalid == 2) page.put("items", new JSONArray().put(new JSONObject().put("id", "1")));
            if (invalid == 3) page.put("items", new JSONArray().put(new JSONObject().put("id", 9)));
            if (invalid == 4) page.put("missing_ids", new JSONArray().put(1));
            if (invalid == 5) page.put("padding", String.join("", Collections.nCopies(33000, "ع")));
            try { strict.accept(page); throw new AssertionError("Invalid page " + invalid); }
            catch (IllegalArgumentException expected) { check(strict.afterId() == 0 && !strict.complete()); }
        }
    }

    /** Actual Android SQLite migrations and queue state, in the disposable test package only. */
    private void textMaturity(Context context) throws Exception {
        final String database = "bchat-v2-text-outbox.db";
        AccountScope account = new AccountScope("https://queue.invalid", "synthetic", 7);
        AccountScope other = new AccountScope("https://queue.invalid", "synthetic", 8);
        for (int version = 1; version <= 4; version++) {
            context.deleteDatabase(database);
            String uuid = UUID.randomUUID().toString();
            try (SQLiteDatabase legacy = context.openOrCreateDatabase(database, Context.MODE_PRIVATE, null)) {
                legacy.execSQL("CREATE TABLE pending_text (_id INTEGER PRIMARY KEY, account_key TEXT NOT NULL, "
                        + "room_id INTEGER NOT NULL,membership_id INTEGER NOT NULL,client_uuid TEXT NOT NULL UNIQUE,"
                        + "body TEXT NOT NULL,created_at INTEGER NOT NULL"
                        + (version >= 3 ? ",review_code INTEGER NOT NULL DEFAULT 0" : "")
                        + (version >= 4 ? ",reply_to_message_id INTEGER" : "") + ")");
                if (version >= 2) legacy.execSQL("CREATE TABLE draft_text (account_key TEXT NOT NULL,room_id INTEGER NOT NULL,"
                        + "membership_id INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(account_key,room_id,membership_id))");
                legacy.execSQL("INSERT INTO pending_text (_id,account_key,room_id,membership_id,client_uuid,body,created_at)"
                        + " VALUES (17,?,1,101,?,'legacy preserved',123)", new Object[]{account.key, uuid});
                if (version >= 4) legacy.execSQL("UPDATE pending_text SET reply_to_message_id=42");
                legacy.setVersion(version);
            }
            try (BChatV2Outbox box = new BChatV2Outbox(context)) {
                BChatV2Outbox.Entry preserved = box.first(account, 1, 101);
                check(preserved.id == 17 && uuid.equals(preserved.uuid) && "legacy preserved".equals(preserved.body));
                check("uncertain".equals(preserved.state) && preserved.attempts == 0);
                check(preserved.replyToMessageId == (version >= 4 ? 42 : 0));
                check(box.getReadableDatabase().getVersion() == 5);
                box.saveDraft(account, 1, 101, "draft reply", 42);
                check(box.draftRecord(account, 1, 101).replyToMessageId == 42);
            }
        }
        context.deleteDatabase(database);
        List<String> uuids = new ArrayList<>();
        try (BChatV2Outbox box = new BChatV2Outbox(context)) {
            box.saveDraft(account, 1, 101, "draft consumed", 42);
            for (int i = 0; i < 10; i++) {
                BChatV2Outbox.Entry entry = box.enqueue(account, 1, 101, "message " + i, i == 0 ? 42 : 0);
                uuids.add(entry.uuid);
                check(entry.body.equals("message " + i));
            }
            check(box.draftRecord(account, 1, 101) == null && box.roomEntries(account, 1, 101).size() == 10);
            check(box.roomEntries(other, 1, 101).isEmpty() && box.roomEntries(account, 1, 999).isEmpty());
            BChatV2Outbox.Entry first = box.claimHead(account, 1, 101, 1000);
            check(first.attempts == 1 && first.uuid.equals(uuids.get(0)));
            check(box.claimHead(account, 1, 101, 1001) == null);
            check(box.recordFailure(account, first, false, 1001));
            check(box.claimHead(account, 1, 101, 6000) == null);
        }
        // The attempt/backoff is reloaded from disk, not reset when Activity/process is rebuilt.
        try (BChatV2Outbox box = new BChatV2Outbox(context)) {
            BChatV2Outbox.Entry secondAttempt = box.claimHead(account, 1, 101, 6001);
            check(secondAttempt != null && secondAttempt.attempts == 2 && secondAttempt.uuid.equals(uuids.get(0)));
            check(box.recordReceipt(account, secondAttempt, 77));
            check(!box.recordFailure(account, secondAttempt, true, 9000));
            check(box.claimHead(account, 1, 101, 90000) == null); // receipt head cannot POST again.
        }
        try (BChatV2Outbox box = new BChatV2Outbox(context)) {
            BChatV2Outbox.Entry receipt = box.first(account, 1, 101);
            check("receipt".equals(receipt.state) && receipt.messageId == 77 && receipt.attempts == 2);
            check(!box.recordReceipt(other, receipt, 77));
            check(box.acknowledge(account, receipt));
            check(box.first(account, 1, 101).uuid.equals(uuids.get(1)));
            BChatV2Outbox.Entry undelivered = box.claimHead(account, 1, 101, 100000);
            check(box.deferUndispatched(account, undelivered));
            check(box.first(account, 1, 101).attempts == 0);
            BChatV2Outbox.Entry sending = box.claimHead(account, 1, 101, 100001);
            check(sending.attempts == 1);
        }
        try (BChatV2Outbox box = new BChatV2Outbox(context)) {
            box.recoverInterrupted(account);
            BChatV2Outbox.Entry recovered = box.first(account, 1, 101);
            check("uncertain".equals(recovered.state) && recovered.attempts == 1 && recovered.uuid.equals(uuids.get(1)));
            long now = 200000;
            for (int attempt = 2; attempt <= OutboxPolicy.MAX_ATTEMPTS; attempt++) {
                BChatV2Outbox.Entry claim = box.claimHead(account, 1, 101, now);
                check(claim != null && claim.attempts == attempt && claim.uuid.equals(uuids.get(1)));
                check(box.recordFailure(account, claim, false, now));
                now += 2 * OutboxPolicy.MAX_BACKOFF_MILLIS;
            }
            check("review".equals(box.first(account, 1, 101).state));
            check(box.claimHead(account, 1, 101, now) == null); // later UUID never overtakes review.
            for (int i = 9; i < 20; i++) box.enqueue(account, 1, 101, "behind review " + i);
            check(box.roomEntries(account, 1, 101).size() == 20);
            try { box.enqueue(account, 1, 101, "21st rejected"); throw new AssertionError("Capacity bypass"); }
            catch (IllegalStateException expected) { check(true); }
            for (int room = 2; room <= 5; room++) for (int i = 0; i < 20; i++) box.enqueue(account, room, 100 + room, "account capacity");
            try { box.enqueue(account, 6, 106, "101st rejected"); throw new AssertionError("Account capacity bypass"); }
            catch (IllegalStateException expected) { check(true); }
            Map<Long, String> cart = new LinkedHashMap<>(); cart.put(2L, "3.25");
            BChatLocalState state = new BChatLocalState("chats", 3, 1, 101, 77, -15, "open", 3, 4, 5,
                    "representative", cart);
            box.saveContext(account, state);
            check(box.context(other) == null && box.context(account).cart.get(2L).equals("3.25"));
            check(box.context(account).anchorMessageId == 77 && !state.toJson().contains("price") && !state.toJson().contains("total"));
            BChatV2Outbox.Entry old = box.first(account, 1, 101);
            box.purgeAccount(account);
            check(box.context(account) == null && box.first(account, 1, 101) == null);
            check(!box.recordReceipt(account, old, 99)); // stale callback never resurrects purged UUID.
        }
    }

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
            textBox.close(); textBox = null;
            textMaturity(context);
            cartAndComposerContracts();
            localCallbackBarriers();
            assertions += PermissionPolicyProbe.run();
            assertions += PermissionRefreshProbe.run();
            final int[] audioAssertions = {0};
            final Throwable[] audioFailure = {null};
            runOnMainSync(() -> {
                try { audioAssertions[0] = ConnectedAudioProbe.run(context.getCacheDir()); }
                catch (Throwable error) { audioFailure[0] = error; }
            });
            if (audioFailure[0] != null) throw new AssertionError(audioFailure[0]);
            assertions += audioAssertions[0];
            assertions += IntentPersistenceChecks.run(context);
            assertions += IntentDispatchProbe.run(this);
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

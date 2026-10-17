package com.baseer.freshchat.sync;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** A bounded, non-authoritative copy of verified BChat v2 history. Never stores media bytes. */
public final class ConnectedHistoryCache extends SQLiteOpenHelper {
    public static final int PAGE_SIZE = 30;
    private static final int MAX_PER_ROOM = 500;
    private static final int MAX_PER_ACCOUNT = 10000;
    private static final long MAX_PAYLOAD_BYTES = 64L * 1024 * 1024;
    private static final int MAX_MESSAGE_BYTES = 64 * 1024;
    public static final int MAX_RECEIPT_KEYS = 1000;
    public static final int MAX_RECEIPT_BYTES = 1024 * 1024;
    private static final String FILE = "bchat-v2-history-v1.db";

    public static final class RoomRecord {
        public final long id, membershipId, companyId;
        public final String name, policy;
        public final int policyVersion;
        public RoomRecord(long id, long membershipId, long companyId, String name,
                          String policy, int policyVersion) {
            OutboxPolicy.requireRecordId(id);
            OutboxPolicy.requireRecordId(membershipId);
            OutboxPolicy.requireRecordId(companyId);
            if (name == null || name.trim().isEmpty()
                    || name.getBytes(StandardCharsets.UTF_8).length > 256
                    || name.indexOf('\n') >= 0 || name.indexOf('\r') >= 0
                    || !("off".equals(policy) || "select_on_upload".equals(policy)
                    || "invoice_default".equals(policy)) || policyVersion < 1)
                throw new IllegalArgumentException("Invalid verified room");
            this.id = id;
            this.membershipId = membershipId;
            this.companyId = companyId;
            this.name = name;
            this.policy = policy;
            this.policyVersion = policyVersion;
        }
    }

    public static final class Snapshot {
        public final AccountScope account;
        public final List<RoomRecord> rooms;
        /** The latest verified server snapshot time, used only to label a read-only cold view. */
        public final long verifiedAt;
        private Snapshot(AccountScope account, List<RoomRecord> rooms, long verifiedAt) {
            this.account = account;
            this.rooms = rooms;
            this.verifiedAt = verifiedAt;
        }
    }

    public ConnectedHistoryCache(Context context) {
        super(context, FILE, null, 2);
    }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE account_scope (account_key TEXT PRIMARY KEY, origin TEXT NOT NULL, "
                + "database_name TEXT NOT NULL, user_id INTEGER NOT NULL, remembered INTEGER NOT NULL, "
                + "verified_at INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE cached_room (account_key TEXT NOT NULL, room_id INTEGER NOT NULL, "
                + "membership_id INTEGER NOT NULL, company_id INTEGER NOT NULL, name TEXT NOT NULL, "
                + "policy TEXT NOT NULL, policy_version INTEGER NOT NULL, "
                + "PRIMARY KEY(account_key,room_id))");
        db.execSQL("CREATE TABLE cached_message (account_key TEXT NOT NULL, room_id INTEGER NOT NULL, "
                + "membership_id INTEGER NOT NULL, message_id INTEGER NOT NULL, payload_json TEXT NOT NULL, "
                + "payload_bytes INTEGER NOT NULL, created_at TEXT NOT NULL, "
                + "PRIMARY KEY(account_key,room_id,membership_id,message_id))");
        db.execSQL("CREATE INDEX cached_message_page ON cached_message"
                + "(account_key,room_id,membership_id,message_id DESC)");
        db.execSQL("CREATE INDEX cached_message_eviction ON cached_message"
                + "(account_key,created_at,message_id)");
        receiptSchema(db);
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion == 1 && newVersion == 2) { receiptSchema(db); return; }
        throw new IllegalStateException("Unknown BChat history schema");
    }

    private static void receiptSchema(SQLiteDatabase db) {
        db.execSQL("ALTER TABLE cached_message ADD COLUMN delivered_acked INTEGER NOT NULL DEFAULT 0");
        db.execSQL("ALTER TABLE cached_message ADD COLUMN read_acked INTEGER NOT NULL DEFAULT 0");
        db.execSQL("ALTER TABLE cached_message ADD COLUMN receipt_verified INTEGER NOT NULL DEFAULT 0");
        db.execSQL("CREATE TABLE receipt_work (account_key TEXT NOT NULL, room_id INTEGER NOT NULL, "
                + "membership_id INTEGER NOT NULL, message_id INTEGER NOT NULL, kind TEXT NOT NULL "
                + "CHECK(kind IN ('fetch','verify','delivered','read')), receipt_id INTEGER NOT NULL, "
                + "metadata_bytes INTEGER NOT NULL, PRIMARY KEY(account_key,room_id,membership_id,message_id,kind))");
        db.execSQL("CREATE INDEX receipt_work_drain ON receipt_work(account_key,kind,receipt_id,message_id)");
    }

    /** Metadata only. An ACK work row pins its canonical message until a verified ACK settles it. */
    public static final class ReceiptWork {
        public final long roomId, membershipId, messageId, receiptId;
        public final String kind;
        public ReceiptWork(long room, long membership, long message, long receipt, String kind) {
            roomId = OutboxPolicy.requireRecordId(room);
            membershipId = OutboxPolicy.requireRecordId(membership);
            messageId = OutboxPolicy.requireRecordId(message);
            if (!("fetch".equals(kind) || "verify".equals(kind) || "delivered".equals(kind) || "read".equals(kind)))
                throw new IllegalArgumentException("Invalid receipt kind");
            if ("fetch".equals(kind)) OutboxPolicy.requireRecordId(receipt);
            else if (receipt != 0) throw new IllegalArgumentException("ACK cannot choose a receipt ID");
            receiptId = receipt;
            this.kind = kind;
        }
        public String key() { return roomId + ":" + membershipId + ":" + messageId + ":" + kind; }
        private int metadataBytes(AccountScope account) {
            return (account.key + "|" + key() + "|" + receiptId).getBytes(StandardCharsets.UTF_8).length;
        }
    }

    /** Admission is all-or-nothing: the RAM cursor must not advance if this page cannot fit. */
    public void admitReceiptReferences(AccountScope account, List<ReceiptWork> refs) {
        if (account == null || refs == null || refs.size() > PAGE_SIZE)
            throw new IllegalArgumentException("Invalid receipt reference page");
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            long previous = 0;
            for (ReceiptWork ref : refs) {
                if (!"fetch".equals(ref.kind) || ref.receiptId <= previous)
                    throw new IllegalArgumentException("Unsorted receipt reference page");
                previous = ref.receiptId;
                if (!hasRoom(db, account, ref.roomId, ref.membershipId))
                    throw new IllegalStateException("Room membership no longer verified");
                putWork(db, account, ref);
            }
            receiptCapacity(db, account);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** ACKs sort before new fetches. Caller applies a bounded per-pass failed-key set. */
    public List<ReceiptWork> receiptWork(AccountScope account) {
        if (account == null) return Collections.emptyList();
        List<ReceiptWork> work = new ArrayList<>();
        try (Cursor rows = getReadableDatabase().rawQuery(
                "SELECT w.room_id,w.membership_id,w.message_id,w.receipt_id,w.kind FROM receipt_work w "
                        + "JOIN cached_room r ON r.account_key=w.account_key AND r.room_id=w.room_id "
                        + "AND r.membership_id=w.membership_id WHERE w.account_key=? "
                        + "ORDER BY CASE w.kind WHEN 'read' THEN 0 WHEN 'delivered' THEN 1 WHEN 'verify' THEN 2 ELSE 3 END,"
                        + "w.receipt_id,w.message_id LIMIT 1000", new String[]{account.key})) {
            while (rows.moveToNext()) work.add(new ReceiptWork(rows.getLong(0), rows.getLong(1),
                    rows.getLong(2), rows.getLong(3), rows.getString(4)));
        }
        return work;
    }

    /** Canonical + pin + intent commit together. No best-effort skip or eviction of an ACK's evidence. */
    public void savePageAndQueueDelivered(AccountScope account, long roomId, long membershipId,
                                           List<JSONObject> page) throws Exception {
        savePage(account, roomId, membershipId, page, true, null);
    }

    /** The caller must supply its already validated canonical bubble and actual viewport evidence. */
    public void queueRead(AccountScope account, long roomId, long membershipId, JSONObject message) throws Exception {
        savePage(account, roomId, membershipId, Collections.singletonList(message), true, "read");
    }

    public static final class MissingReceiptEvidence extends IllegalStateException {
        MissingReceiptEvidence() { super("Canonical epoch has not been authenticated for receipt delivery"); }
    }

    /** A visible but unproven legacy/evicted row requests canonical revalidation, never a read ACK. */
    public void requestReadEvidence(AccountScope account, long roomId, long membershipId, long messageId) {
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            if (!hasRoom(db, account, roomId, membershipId))
                throw new IllegalStateException("Room membership no longer verified");
            putWork(db, account, new ReceiptWork(roomId, membershipId, messageId, 0, "verify"));
            receiptCapacity(db, account); db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public boolean hasReceiptEvidence(AccountScope account, ReceiptWork work) {
        if (account == null || work == null || !("delivered".equals(work.kind) || "read".equals(work.kind))) return false;
        try (Cursor row = getReadableDatabase().rawQuery("SELECT 1 FROM receipt_work w JOIN cached_message m "
                + "ON m.account_key=w.account_key AND m.room_id=w.room_id AND m.membership_id=w.membership_id "
                + "AND m.message_id=w.message_id JOIN cached_room r ON r.account_key=w.account_key "
                + "AND r.room_id=w.room_id AND r.membership_id=w.membership_id WHERE w.account_key=? "
                + "AND w.room_id=? AND w.membership_id=? AND w.message_id=? AND w.kind=? AND m.receipt_verified=1 LIMIT 1",
                workArgs(account, work))) { return row.moveToFirst(); }
    }

    /** Settle only this account/epoch and exact durable intent, irrespective of which room is selected. */
    public boolean settleReceipt(AccountScope account, ReceiptWork work) {
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            if (!hasReceiptEvidence(account, work)) return false;
            ContentValues values = new ContentValues(); values.put("delivered_acked", 1);
            if ("read".equals(work.kind)) values.put("read_acked", 1);
            db.update("cached_message", values, "account_key=? AND room_id=? AND membership_id=? AND message_id=?",
                    messageArgs(account, work));
            String where = "account_key=? AND room_id=? AND membership_id=? AND message_id=? AND kind";
            db.delete("receipt_work", where + ("read".equals(work.kind) ? " IN ('delivered','read','fetch','verify')" : " IN ('delivered','fetch')"),
                    messageArgs(account, work));
            trim(db, account, work.roomId, work.membershipId);
            db.setTransactionSuccessful(); return true;
        } finally { db.endTransaction(); }
    }

    private static String[] messageArgs(AccountScope account, ReceiptWork work) {
        return new String[]{account.key, String.valueOf(work.roomId), String.valueOf(work.membershipId), String.valueOf(work.messageId)};
    }
    private static String[] workArgs(AccountScope account, ReceiptWork work) {
        return new String[]{account.key, String.valueOf(work.roomId), String.valueOf(work.membershipId), String.valueOf(work.messageId), work.kind};
    }
    private static void putWork(SQLiteDatabase db, AccountScope account, ReceiptWork work) {
        ContentValues values = new ContentValues(); values.put("account_key", account.key);
        values.put("room_id", work.roomId); values.put("membership_id", work.membershipId);
        values.put("message_id", work.messageId); values.put("kind", work.kind);
        values.put("receipt_id", work.receiptId); values.put("metadata_bytes", work.metadataBytes(account));
        db.insertWithOnConflict("receipt_work", null, values, SQLiteDatabase.CONFLICT_IGNORE);
        try (Cursor row = db.query("receipt_work", new String[]{"receipt_id", "metadata_bytes"},
                "account_key=? AND room_id=? AND membership_id=? AND message_id=? AND kind=?",
                workArgs(account, work), null, null, null, "1")) {
            if (!row.moveToFirst() || row.getLong(0) != work.receiptId
                    || row.getInt(1) != work.metadataBytes(account))
                throw new IllegalStateException("Receipt evidence admission failed");
        }
    }
    private static void receiptCapacity(SQLiteDatabase db, AccountScope account) {
        try (Cursor totals = db.rawQuery("SELECT COUNT(*),COALESCE(SUM(metadata_bytes),0) FROM receipt_work WHERE account_key=?",
                new String[]{account.key})) {
            totals.moveToFirst();
            if (totals.getLong(0) > MAX_RECEIPT_KEYS || totals.getLong(1) > MAX_RECEIPT_BYTES)
                throw new IllegalStateException("Receipt evidence capacity reached");
        }
    }

    /** A verified room list replaces the previous membership set atomically. */
    public void reconcile(AccountScope account, boolean remembered, List<RoomRecord> rooms) {
        if (account == null || rooms == null || rooms.size() > 100)
            throw new IllegalArgumentException("Verified scope and rooms required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("receipt_work", "account_key<>?", new String[]{account.key});
            db.delete("cached_message", "account_key<>?", new String[]{account.key});
            db.delete("cached_room", "account_key<>?", new String[]{account.key});
            db.delete("account_scope", "account_key<>?", new String[]{account.key});
            ContentValues scope = new ContentValues();
            scope.put("account_key", account.key);
            scope.put("origin", account.origin);
            scope.put("database_name", account.database);
            scope.put("user_id", account.userId);
            scope.put("remembered", remembered ? 1 : 0);
            scope.put("verified_at", System.currentTimeMillis());
            db.insertWithOnConflict("account_scope", null, scope, SQLiteDatabase.CONFLICT_REPLACE);
            List<Long> current = new ArrayList<>();
            for (RoomRecord room : rooms) {
                if (current.contains(room.id)) throw new IllegalArgumentException("Duplicate room");
                current.add(room.id);
                String[] selection = {account.key, String.valueOf(room.id), String.valueOf(room.membershipId)};
                db.delete("receipt_work", "account_key=? AND room_id=? AND membership_id<>?", selection);
                db.delete("cached_message", "account_key=? AND room_id=? AND membership_id<>?", selection);
                ContentValues values = new ContentValues();
                values.put("account_key", account.key);
                values.put("room_id", room.id);
                values.put("membership_id", room.membershipId);
                values.put("company_id", room.companyId);
                values.put("name", room.name);
                values.put("policy", room.policy);
                values.put("policy_version", room.policyVersion);
                db.insertWithOnConflict("cached_room", null, values, SQLiteDatabase.CONFLICT_REPLACE);
            }
            List<Long> removed = new ArrayList<>();
            try (Cursor previous = db.query("cached_room", new String[]{"room_id"},
                    "account_key=?", new String[]{account.key}, null, null, null)) {
                while (previous.moveToNext()) {
                    long id = previous.getLong(0);
                    if (!current.contains(id)) removed.add(id);
                }
            }
            for (Long id : removed) {
                String[] gone = {account.key, String.valueOf(id)};
                db.delete("receipt_work", "account_key=? AND room_id=?", gone);
                db.delete("cached_message", "account_key=? AND room_id=?", gone);
                db.delete("cached_room", "account_key=? AND room_id=?", gone);
            }
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** A newly verified different user cannot inherit an earlier user's offline view. */
    public void purgeOtherAccounts(AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified scope required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("receipt_work", "account_key<>?", new String[]{account.key});
            db.delete("cached_message", "account_key<>?", new String[]{account.key});
            db.delete("cached_room", "account_key<>?", new String[]{account.key});
            db.delete("account_scope", "account_key<>?", new String[]{account.key});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** Only the account explicitly remembered after a verified login may be browsed cold. */
    public Snapshot remembered(String origin, String database) {
        return remembered(origin, database, System.currentTimeMillis(), Long.MAX_VALUE);
    }

    /** A cold view is bounded by a last verified time; caller owns the product retention policy. */
    public Snapshot remembered(String origin, String database, long now, long maxAge) {
        if (now <= 0 || maxAge <= 0) return null;
        long cutoff = maxAge >= now ? 0 : now - maxAge;
        AccountScope scope;
        long verifiedAt;
        try (Cursor rows = getReadableDatabase().query("account_scope",
                new String[]{"origin", "database_name", "user_id", "verified_at"},
                "remembered=1 AND origin=? AND database_name=? AND verified_at<=? AND verified_at>=?",
                new String[]{origin, database, String.valueOf(now), String.valueOf(cutoff)},
                null, null, "verified_at DESC", "1")) {
            if (!rows.moveToFirst()) return null;
            scope = new AccountScope(rows.getString(0), rows.getString(1), rows.getLong(2));
            verifiedAt = rows.getLong(3);
        }
        List<RoomRecord> rooms = rooms(scope);
        return rooms.isEmpty() ? null : new Snapshot(scope, rooms, verifiedAt);
    }

    public List<RoomRecord> rooms(AccountScope account) {
        if (account == null) return Collections.emptyList();
        List<RoomRecord> rooms = new ArrayList<>();
        try (Cursor rows = getReadableDatabase().query("cached_room",
                new String[]{"room_id", "membership_id", "company_id", "name", "policy", "policy_version"},
                "account_key=?", new String[]{account.key}, null, null, "room_id ASC", "100")) {
            while (rows.moveToNext()) rooms.add(new RoomRecord(rows.getLong(0), rows.getLong(1),
                    rows.getLong(2), rows.getString(3), rows.getString(4), rows.getInt(5)));
        }
        return rooms;
    }

    public void purgeAll() {
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("receipt_work", null, null);
            db.delete("cached_message", null, null);
            db.delete("cached_room", null, null);
            db.delete("account_scope", null, null);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** Revoke this account's offline room access without touching other account scopes. */
    public void purgeAccount(AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified scope required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            String[] scope = {account.key};
            db.delete("receipt_work", "account_key=?", scope);
            db.delete("cached_message", "account_key=?", scope);
            db.delete("cached_room", "account_key=?", scope);
            db.delete("account_scope", "account_key=?", scope);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public void purgeRoom(AccountScope account, long roomId) {
        if (account == null || roomId <= 0) return;
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            String[] scope = {account.key, String.valueOf(roomId)};
            db.delete("receipt_work", "account_key=? AND room_id=?", scope);
            db.delete("cached_message", "account_key=? AND room_id=?", scope);
            db.delete("cached_room", "account_key=? AND room_id=?", scope);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** A page must already have passed the v2 response validator. */
    public void savePage(AccountScope account, long roomId, long membershipId,
                         List<JSONObject> page) throws Exception {
        savePage(account, roomId, membershipId, page, false, null);
    }

    private void savePage(AccountScope account, long roomId, long membershipId,
                          List<JSONObject> page, boolean delivery, String extraKind) throws Exception {
        if (account == null || page == null || page.size() > PAGE_SIZE)
            throw new IllegalArgumentException("Invalid verified page");
        OutboxPolicy.requireRecordId(roomId);
        OutboxPolicy.requireRecordId(membershipId);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            if (!hasRoom(db, account, roomId, membershipId))
                throw new IllegalStateException("Room membership no longer verified");
            long previous = 0;
            for (JSONObject item : page) {
                long id = OutboxPolicy.requireRecordId(item.getLong("id"));
                if (id <= previous) throw new IllegalArgumentException("Unsorted verified page");
                previous = id;
                String payload = item.toString();
                int bytes = payload.getBytes(StandardCharsets.UTF_8).length;
                if (bytes <= 0 || bytes > MAX_MESSAGE_BYTES)
                    throw new IllegalArgumentException("Canonical message exceeds cache bound");
                String createdAt = item.getString("created_at");
                // Preserve a previously settled proof; REPLACE would reset these columns.
                int deliveredAcked = 0, readAcked = 0, receiptVerified = 0;
                try (Cursor old = db.rawQuery("SELECT delivered_acked,read_acked,receipt_verified FROM cached_message "
                        + "WHERE account_key=? AND room_id=? AND membership_id=? AND message_id=?",
                        new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId), String.valueOf(id)})) {
                    if (old.moveToFirst()) {
                        deliveredAcked = old.getInt(0); readAcked = old.getInt(1); receiptVerified = old.getInt(2);
                    }
                }
                if ("read".equals(extraKind) && receiptVerified != 1)
                    throw new MissingReceiptEvidence();
                ContentValues values = new ContentValues();
                values.put("account_key", account.key);
                values.put("room_id", roomId);
                values.put("membership_id", membershipId);
                values.put("message_id", id);
                values.put("payload_json", payload);
                values.put("payload_bytes", bytes);
                values.put("created_at", createdAt);
                values.put("delivered_acked", deliveredAcked); values.put("read_acked", readAcked);
                values.put("receipt_verified", delivery ? 1 : receiptVerified);
                if (db.insertWithOnConflict("cached_message", null, values, SQLiteDatabase.CONFLICT_REPLACE) < 0)
                    throw new IllegalStateException("Canonical cache commit failed");
                if (delivery && OutboxPolicy.requireRecordId(item.getLong("author_user_id")) != account.userId) {
                    if (deliveredAcked == 0)
                        putWork(db, account, new ReceiptWork(roomId, membershipId, id, 0, "delivered"));
                    if ("read".equals(extraKind) && readAcked == 0)
                        putWork(db, account, new ReceiptWork(roomId, membershipId, id, 0, "read"));
                    db.delete("receipt_work", "account_key=? AND room_id=? AND membership_id=? AND message_id=? AND kind IN ('fetch','verify')",
                            new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId), String.valueOf(id)});
                }
            }
            receiptCapacity(db, account);
            trim(db, account, roomId, membershipId);
            if (delivery) for (JSONObject item : page) {
                // All admitted canonical rows must really remain after retention, not just the newest row.
                try (Cursor saved = db.rawQuery("SELECT 1 FROM cached_message WHERE account_key=? AND room_id=? "
                        + "AND membership_id=? AND message_id=?", new String[]{account.key, String.valueOf(roomId),
                        String.valueOf(membershipId), String.valueOf(item.getLong("id"))})) {
                    if (!saved.moveToFirst()) throw new IllegalStateException("Canonical evidence could not fit");
                }
            }
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public List<JSONObject> page(AccountScope account, long roomId, long membershipId,
                                 long beforeId) throws Exception {
        if (account == null || roomId <= 0 || membershipId <= 0 || beforeId < 0)
            throw new IllegalArgumentException("Invalid room cursor");
        List<JSONObject> messages = new ArrayList<>();
        String where = "account_key=? AND room_id=? AND membership_id=?"
                + (beforeId > 0 ? " AND message_id<?" : "");
        String[] args = beforeId > 0
                ? new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId), String.valueOf(beforeId)}
                : new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)};
        try (Cursor rows = getReadableDatabase().query("cached_message",
                new String[]{"message_id", "payload_json"}, where, args, null, null,
                "message_id DESC", String.valueOf(PAGE_SIZE))) {
            while (rows.moveToNext()) {
                JSONObject item = new JSONObject(rows.getString(1));
                if (item.getLong("id") != rows.getLong(0)) throw new IllegalStateException("Cache mismatch");
                messages.add(item);
            }
        }
        Collections.reverse(messages);
        return messages;
    }

    /** The next saved page toward the present; the caller retains its current last bubble. */
    public List<JSONObject> pageAfter(AccountScope account, long roomId, long membershipId,
                                      long afterId) throws Exception {
        if (account == null || roomId <= 0 || membershipId <= 0 || afterId <= 0)
            throw new IllegalArgumentException("Invalid forward cursor");
        List<JSONObject> messages = new ArrayList<>();
        try (Cursor rows = getReadableDatabase().query("cached_message",
                new String[]{"message_id", "payload_json"},
                "account_key=? AND room_id=? AND membership_id=? AND message_id>?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId),
                        String.valueOf(afterId)}, null, null, "message_id ASC",
                String.valueOf(PAGE_SIZE - 1))) {
            while (rows.moveToNext()) {
                JSONObject item = new JSONObject(rows.getString(1));
                if (item.getLong("id") != rows.getLong(0)) throw new IllegalStateException("Cache mismatch");
                messages.add(item);
            }
        }
        return messages;
    }

    public boolean hasNewer(AccountScope account, long roomId, long membershipId, long afterId) {
        if (account == null || afterId <= 0) return false;
        try (Cursor rows = getReadableDatabase().rawQuery(
                "SELECT 1 FROM cached_message WHERE account_key=? AND room_id=? "
                        + "AND membership_id=? AND message_id>? LIMIT 1",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId),
                        String.valueOf(afterId)})) {
            return rows.moveToFirst();
        }
    }

    public boolean hasOlder(AccountScope account, long roomId, long membershipId, long beforeId) {
        if (account == null || beforeId <= 0) return false;
        try (Cursor rows = getReadableDatabase().rawQuery(
                "SELECT 1 FROM cached_message WHERE account_key=? AND room_id=? "
                        + "AND membership_id=? AND message_id<? LIMIT 1",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId),
                        String.valueOf(beforeId)})) {
            return rows.moveToFirst();
        }
    }

    private static boolean hasRoom(SQLiteDatabase db, AccountScope account, long roomId, long membershipId) {
        try (Cursor rows = db.query("cached_room", new String[]{"room_id"},
                "account_key=? AND room_id=? AND membership_id=?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)},
                null, null, null, "1")) { return rows.moveToFirst(); }
    }

    private static void trim(SQLiteDatabase db, AccountScope account, long roomId, long membershipId) {
        String unpinned = " NOT EXISTS (SELECT 1 FROM receipt_work w WHERE w.account_key=cached_message.account_key "
                + "AND w.room_id=cached_message.room_id AND w.membership_id=cached_message.membership_id "
                + "AND w.message_id=cached_message.message_id AND w.kind IN ('delivered','read')) ";
        long pinned;
        try (Cursor rows = db.rawQuery("SELECT COUNT(*) FROM cached_message WHERE account_key=? AND room_id=? "
                + "AND membership_id=? AND NOT (" + unpinned + ")",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)})) {
            rows.moveToFirst(); pinned = rows.getLong(0);
        }
        if (pinned > MAX_PER_ROOM) throw new IllegalStateException("Pinned canonical room capacity reached");
        db.execSQL("DELETE FROM cached_message WHERE rowid IN (SELECT rowid FROM cached_message "
                + "WHERE account_key=? AND room_id=? AND membership_id=? AND " + unpinned
                + "ORDER BY message_id DESC LIMIT -1 OFFSET ?)",
                new Object[]{account.key, roomId, membershipId, MAX_PER_ROOM - pinned});
        long count;
        long bytes;
        try (Cursor totals = db.rawQuery("SELECT COUNT(*),COALESCE(SUM(payload_bytes),0) FROM cached_message "
                + "WHERE account_key=?", new String[]{account.key})) {
            totals.moveToFirst();
            count = totals.getLong(0);
            bytes = totals.getLong(1);
        }
        while (count > MAX_PER_ACCOUNT || bytes > MAX_PAYLOAD_BYTES) {
            List<Long> ids = new ArrayList<>();
            List<Integer> sizes = new ArrayList<>();
            try (Cursor oldest = db.rawQuery("SELECT rowid,payload_bytes FROM cached_message WHERE account_key=? "
                    + "AND " + unpinned + "ORDER BY created_at ASC,message_id ASC LIMIT 128", new String[]{account.key})) {
                if (!oldest.moveToFirst()) throw new IllegalStateException("Pinned canonical account capacity reached");
                do {
                    ids.add(oldest.getLong(0));
                    sizes.add(oldest.getInt(1));
                } while (oldest.moveToNext());
            }
            for (int i = 0; i < ids.size(); i++) {
                db.delete("cached_message", "rowid=?", new String[]{String.valueOf(ids.get(i))});
                count--;
                bytes -= sizes.get(i);
                if (count <= MAX_PER_ACCOUNT && bytes <= MAX_PAYLOAD_BYTES) break;
            }
        }
    }
}

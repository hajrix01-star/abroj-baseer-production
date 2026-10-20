package com.baseer.bwork.legacy.sync;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** A small, account- and membership-scoped queue. Only a server receipt removes an entry. */
public final class BWorkV2Outbox extends SQLiteOpenHelper {
    private static final String TABLE = "pending_text";

    public BWorkV2Outbox(Context context) {
        super(context, com.baseer.bwork.legacy.compat.LegacyIdentity.TEXT_OUTBOX, null, 4);
    }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE pending_text (_id INTEGER PRIMARY KEY, account_key TEXT NOT NULL, " +
                "room_id INTEGER NOT NULL, membership_id INTEGER NOT NULL, client_uuid TEXT NOT NULL UNIQUE, " +
                "body TEXT NOT NULL, created_at INTEGER NOT NULL, review_code INTEGER NOT NULL DEFAULT 0, " +
                "reply_to_message_id INTEGER)");
        db.execSQL("CREATE INDEX pending_text_scope ON pending_text(account_key,room_id,membership_id,created_at)");
        createDraftTable(db);
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion == 1) {
            createDraftTable(db);
            db.execSQL("ALTER TABLE pending_text ADD COLUMN review_code INTEGER NOT NULL DEFAULT 0");
        } else if (oldVersion == 2) {
            db.execSQL("ALTER TABLE pending_text ADD COLUMN review_code INTEGER NOT NULL DEFAULT 0");
        } else if (oldVersion != 3) throw new IllegalStateException("Unknown text outbox migration");
        if (newVersion != 4) throw new IllegalStateException("Unknown text outbox target");
        db.execSQL("ALTER TABLE pending_text ADD COLUMN reply_to_message_id INTEGER");
    }

    private static void createDraftTable(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE draft_text (account_key TEXT NOT NULL, room_id INTEGER NOT NULL, " +
                "membership_id INTEGER NOT NULL, body TEXT NOT NULL, " +
                "PRIMARY KEY(account_key,room_id,membership_id))");
    }

    /** One unacknowledged message per current room keeps ordering and retry decisions explicit. */
    public Entry enqueue(AccountScope account, long roomId, long membershipId, String body) {
        return enqueue(account, roomId, membershipId, body, 0);
    }

    public Entry enqueue(AccountScope account, long roomId, long membershipId, String body,
                         long replyToMessageId) {
        return enqueue(account, roomId, membershipId, body, replyToMessageId, true);
    }

    /** Share external content without consuming a draft already typed in the room. */
    public Entry enqueuePreservingDraft(AccountScope account, long roomId,
                                        long membershipId, String body) {
        return enqueue(account, roomId, membershipId, body, 0, false);
    }

    private Entry enqueue(AccountScope account, long roomId, long membershipId, String body,
                          long replyToMessageId, boolean consumeDraft) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        OutboxPolicy.requireRecordId(roomId);
        OutboxPolicy.requireRecordId(membershipId);
        if (replyToMessageId < 0) throw new IllegalArgumentException("Invalid reply reference");
        if (replyToMessageId > 0) OutboxPolicy.requireRecordId(replyToMessageId);
        OutboxPolicy.requireText(body);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            Entry pending = first(db, account, roomId, membershipId);
            if (pending != null) throw new IllegalStateException("Resolve the pending message first");
            ContentValues values = new ContentValues();
            values.put("account_key", account.key);
            values.put("room_id", roomId);
            values.put("membership_id", membershipId);
            values.put("client_uuid", UUID.randomUUID().toString());
            values.put("body", body);
            if (replyToMessageId > 0) values.put("reply_to_message_id", replyToMessageId);
            values.put("created_at", System.currentTimeMillis());
            db.insertOrThrow(TABLE, null, values);
            Entry result = first(db, account, roomId, membershipId);
            if (consumeDraft)
                db.delete("draft_text", "account_key=? AND room_id=? AND membership_id=?",
                        new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)});
            db.setTransactionSuccessful();
            return result;
        } finally { db.endTransaction(); }
    }

    public Entry first(AccountScope account, long roomId, long membershipId) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        return first(getReadableDatabase(), account, roomId, membershipId);
    }

    private static Entry first(SQLiteDatabase db, AccountScope account, long roomId, long membershipId) {
        try (Cursor rows = db.query(TABLE,
                new String[]{"_id", "room_id", "membership_id", "client_uuid", "body", "review_code", "reply_to_message_id"},
                "account_key=? AND room_id=? AND membership_id=?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)},
                null, null, "created_at ASC,_id ASC", "1")) {
            return rows.moveToFirst() ? read(rows) : null;
        }
    }

    /** An old membership's UUID must never be retried under the new membership. */
    public Entry firstStale(AccountScope account, long roomId, long currentMembershipId) {
        requireScope(account, roomId, currentMembershipId);
        try (Cursor rows = getReadableDatabase().query(TABLE,
                new String[]{"_id", "room_id", "membership_id", "client_uuid", "body", "review_code", "reply_to_message_id"},
                "account_key=? AND room_id=? AND membership_id<>?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(currentMembershipId)},
                null, null, "created_at ASC,_id ASC", "1")) {
            return rows.moveToFirst() ? read(rows) : null;
        }
    }

    /** Account-only cursor; no room membership is assumed for local text recovery. */
    public List<Entry> pageForAccount(AccountScope account, long afterId) {
        if (account == null || afterId < 0) throw new IllegalArgumentException("Verified account required");
        List<Entry> entries = new ArrayList<>();
        try (Cursor rows = getReadableDatabase().query(TABLE,
                new String[]{"_id", "room_id", "membership_id", "client_uuid", "body", "review_code", "reply_to_message_id"},
                "account_key=? AND _id>?", new String[]{account.key, String.valueOf(afterId)},
                null, null, "_id ASC", "31")) {
            while (rows.moveToNext()) entries.add(read(rows));
        }
        return entries;
    }

    private static Entry read(Cursor row) {
        return new Entry(row.getLong(0), row.getLong(1), row.getLong(2),
                row.getString(3), row.getString(4), row.getInt(5), row.isNull(6) ? 0 : row.getLong(6));
    }

    /** Preserve a permanent 400/413 review state across redraw and process death. */
    public boolean recordRejected(AccountScope account, Entry entry) {
        if (account == null || entry == null) throw new IllegalArgumentException("Pending scope required");
        ContentValues values = new ContentValues();
        values.put("review_code", 1);
        return getWritableDatabase().update(TABLE, values,
                "_id=? AND account_key=? AND room_id=? AND membership_id=? AND client_uuid=? AND body=? " +
                        "AND COALESCE(reply_to_message_id,0)=CAST(? AS INTEGER)",
                new String[]{String.valueOf(entry.id), account.key, String.valueOf(entry.roomId),
                        String.valueOf(entry.membershipId), entry.uuid, entry.body,
                        String.valueOf(entry.replyToMessageId)}) == 1;
    }

    public String draft(AccountScope account, long roomId, long membershipId) {
        requireScope(account, roomId, membershipId);
        return draft(getReadableDatabase(), account, roomId, membershipId);
    }

    private static String draft(SQLiteDatabase db, AccountScope account, long roomId, long membershipId) {
        try (Cursor rows = db.query("draft_text", new String[]{"body"},
                "account_key=? AND room_id=? AND membership_id=?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)},
                null, null, null, "1")) {
            return rows.moveToFirst() ? rows.getString(0) : null;
        }
    }

    public void saveDraft(AccountScope account, long roomId, long membershipId, String body) {
        requireScope(account, roomId, membershipId);
        if (body == null || body.getBytes(StandardCharsets.UTF_8).length > 65536)
            throw new IllegalArgumentException("Draft exceeds local bound");
        ContentValues values = new ContentValues();
        values.put("account_key", account.key);
        values.put("room_id", roomId);
        values.put("membership_id", membershipId);
        values.put("body", body);
        if (getWritableDatabase().insertWithOnConflict("draft_text", null, values,
                SQLiteDatabase.CONFLICT_REPLACE) < 0) throw new IllegalStateException("Draft save failed");
    }

    /** User-approved finalization: atomically preserve text as a new draft, then retire old UUID. */
    public boolean convertToDraft(AccountScope account, Entry entry, long targetRoomId, long targetMembershipId,
                                  boolean overwriteDraft) {
        requireScope(account, targetRoomId, targetMembershipId);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            if (entry == null || !exists(db, account, entry)) return false;
            if (!overwriteDraft && draft(db, account, targetRoomId, targetMembershipId) != null)
                throw new IllegalStateException("Existing draft must be confirmed before replacement");
            ContentValues values = new ContentValues();
            values.put("account_key", account.key);
            values.put("room_id", targetRoomId);
            values.put("membership_id", targetMembershipId);
            values.put("body", entry.body);
            if (db.insertWithOnConflict("draft_text", null, values,
                    SQLiteDatabase.CONFLICT_REPLACE) < 0) throw new IllegalStateException("Draft save failed");
            if (deleteExact(db, account, entry) != 1) throw new IllegalStateException("Pending request changed");
            db.setTransactionSuccessful();
            return true;
        } finally { db.endTransaction(); }
    }

    /** Explicit user deletion only. This does not assert whether the server received the request. */
    public boolean discard(AccountScope account, Entry entry) {
        if (account == null || entry == null) throw new IllegalArgumentException("Pending scope required");
        return deleteExact(getWritableDatabase(), account, entry) == 1;
    }

    /** Permission revocation invalidates both queued sends and unsent drafts. */
    public void purgeAccount(AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete(TABLE, "account_key=?", new String[]{account.key});
            db.delete("draft_text", "account_key=?", new String[]{account.key});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** A reduced company scope retains drafts only in still-authorized rooms. */
    public void purgeExceptRooms(AccountScope account, java.util.Set<Long> allowedRoomIds) {
        if (account == null || allowedRoomIds == null)
            throw new IllegalArgumentException("Verified rooms required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            for (String table : new String[]{TABLE, "draft_text"}) {
                java.util.Set<Long> removed = new java.util.HashSet<>();
                try (Cursor rows = db.query(table, new String[]{"room_id"}, "account_key=?",
                        new String[]{account.key}, null, null, null)) {
                    while (rows.moveToNext()) {
                        long roomId = rows.getLong(0);
                        if (!allowedRoomIds.contains(roomId)) removed.add(roomId);
                    }
                }
                for (Long roomId : removed)
                    db.delete(table, "account_key=? AND room_id=?",
                            new String[]{account.key, String.valueOf(roomId)});
            }
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    private static boolean exists(SQLiteDatabase db, AccountScope account, Entry entry) {
        try (Cursor rows = db.rawQuery("SELECT 1 FROM pending_text WHERE _id=? AND account_key=? " +
                        "AND room_id=? AND membership_id=? AND client_uuid=? AND body=? " +
                        "AND COALESCE(reply_to_message_id,0)=CAST(? AS INTEGER)",
                new String[]{String.valueOf(entry.id), account.key, String.valueOf(entry.roomId),
                        String.valueOf(entry.membershipId), entry.uuid, entry.body,
                        String.valueOf(entry.replyToMessageId)})) {
            return rows.moveToFirst();
        }
    }

    private static int deleteExact(SQLiteDatabase db, AccountScope account, Entry entry) {
        return db.delete(TABLE,
                "_id=? AND account_key=? AND room_id=? AND membership_id=? AND client_uuid=? AND body=? " +
                        "AND COALESCE(reply_to_message_id,0)=CAST(? AS INTEGER)",
                new String[]{String.valueOf(entry.id), account.key, String.valueOf(entry.roomId),
                        String.valueOf(entry.membershipId), entry.uuid, entry.body,
                        String.valueOf(entry.replyToMessageId)});
    }

    private static void requireScope(AccountScope account, long roomId, long membershipId) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        OutboxPolicy.requireRecordId(roomId);
        OutboxPolicy.requireRecordId(membershipId);
    }

    /** The caller must validate api_version, room, membership, UUID, state and message ID first. */
    public boolean acknowledge(AccountScope account, Entry entry) {
        if (account == null || entry == null) throw new IllegalArgumentException("Receipt scope required");
        return deleteExact(getWritableDatabase(), account, entry) == 1;
    }

    public static final class Entry {
        public final long id, roomId, membershipId;
        public final long replyToMessageId;
        public final int reviewCode;
        public final String uuid, body;
        private Entry(long id, long roomId, long membershipId, String uuid, String body, int reviewCode,
                      long replyToMessageId) {
            this.id = id; this.roomId = roomId; this.membershipId = membershipId;
            this.uuid = uuid; this.body = body; this.reviewCode = reviewCode;
            this.replyToMessageId = replyToMessageId;
        }
    }
}

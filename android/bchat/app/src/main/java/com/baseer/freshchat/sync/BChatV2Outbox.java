package com.baseer.freshchat.sync;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.Collections;

/** A small, account- and membership-scoped queue. Only a server receipt removes an entry. */
public final class BChatV2Outbox extends SQLiteOpenHelper {
    private static final String TABLE = "pending_text";
    public static final int MAX_PER_ROOM = 20, MAX_PER_ACCOUNT = 100;
    public static final long MAX_ACCOUNT_BYTES = 2L * 1024 * 1024;
    private static final String[] COLUMNS = {"_id", "room_id", "membership_id", "client_uuid", "body",
            "review_code", "reply_to_message_id", "queue_state", "attempts", "next_attempt_at",
            "lease_until", "message_id", "created_at", "claim_owner", "claim_generation"};

    public BChatV2Outbox(Context context) {
        super(context, "bchat-v2-text-outbox.db", null, 6);
    }
    public BChatSendTickets tickets() { return new BChatSendTickets(this); }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE pending_text (_id INTEGER PRIMARY KEY, account_key TEXT NOT NULL, " +
                "room_id INTEGER NOT NULL, membership_id INTEGER NOT NULL, client_uuid TEXT NOT NULL UNIQUE, " +
                "body TEXT NOT NULL, created_at INTEGER NOT NULL, review_code INTEGER NOT NULL DEFAULT 0, " +
                "reply_to_message_id INTEGER, queue_state TEXT NOT NULL DEFAULT 'queued', " +
                "attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL DEFAULT 0, " +
                "lease_until INTEGER NOT NULL DEFAULT 0, message_id INTEGER NOT NULL DEFAULT 0, "
                + "claim_owner TEXT NOT NULL DEFAULT '',claim_generation INTEGER NOT NULL DEFAULT 0)");
        db.execSQL("CREATE INDEX pending_text_scope ON pending_text(account_key,room_id,membership_id,created_at)");
        createDraftTable(db);
        createContextTable(db);
        BChatSendTickets.create(db, false);
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion < 1 || oldVersion > 5 || newVersion != 6)
            throw new IllegalStateException("Unknown text outbox migration");
        if (oldVersion < 5) {
        if (oldVersion == 1) {
            createDraftTable(db);
            db.execSQL("ALTER TABLE pending_text ADD COLUMN review_code INTEGER NOT NULL DEFAULT 0");
        } else if (oldVersion == 2) {
            db.execSQL("ALTER TABLE pending_text ADD COLUMN review_code INTEGER NOT NULL DEFAULT 0");
        }
        if (oldVersion < 4) db.execSQL("ALTER TABLE pending_text ADD COLUMN reply_to_message_id INTEGER");
        db.execSQL("ALTER TABLE pending_text ADD COLUMN queue_state TEXT NOT NULL DEFAULT 'uncertain'");
        db.execSQL("ALTER TABLE pending_text ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0");
        db.execSQL("ALTER TABLE pending_text ADD COLUMN next_attempt_at INTEGER NOT NULL DEFAULT 0");
        db.execSQL("ALTER TABLE pending_text ADD COLUMN lease_until INTEGER NOT NULL DEFAULT 0");
        db.execSQL("ALTER TABLE pending_text ADD COLUMN message_id INTEGER NOT NULL DEFAULT 0");
        if (oldVersion != 1) db.execSQL("ALTER TABLE draft_text ADD COLUMN reply_to_message_id INTEGER");
        db.execSQL("UPDATE pending_text SET queue_state='review' WHERE review_code<>0");
        createContextTable(db);
        }
        db.execSQL("ALTER TABLE pending_text ADD COLUMN claim_owner TEXT NOT NULL DEFAULT ''");
        db.execSQL("ALTER TABLE pending_text ADD COLUMN claim_generation INTEGER NOT NULL DEFAULT 0");
        if(oldVersion!=1)db.execSQL("ALTER TABLE draft_text ADD COLUMN editor_revision INTEGER NOT NULL DEFAULT -1");
        BChatSendTickets.create(db, true);
    }

    private static void createDraftTable(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE draft_text (account_key TEXT NOT NULL, room_id INTEGER NOT NULL, " +
                "membership_id INTEGER NOT NULL, body TEXT NOT NULL, reply_to_message_id INTEGER, " +
                "editor_revision INTEGER NOT NULL DEFAULT -1, " +
                "PRIMARY KEY(account_key,room_id,membership_id))");
    }

    private static void createContextTable(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE local_context (account_key TEXT PRIMARY KEY, state_json TEXT NOT NULL)");
    }

    /** Capacity and draft consumption are checked in the same transaction as durable admission. */
    public Entry enqueue(AccountScope account, long roomId, long membershipId, String body) {
        return enqueue(account, roomId, membershipId, body, 0);
    }

    public Entry enqueue(AccountScope account, long roomId, long membershipId, String body,
                         long replyToMessageId) {
        return enqueue(account, roomId, membershipId, body, replyToMessageId, 0, true);
    }

    public Entry enqueue(AccountScope account,long roomId,long membershipId,String body,
                         long replyToMessageId,long editorRevision){
        return enqueue(account,roomId,membershipId,body,replyToMessageId,editorRevision,true);
    }

    /** Share external content without consuming a draft already typed in the room. */
    public Entry enqueuePreservingDraft(AccountScope account, long roomId,
                                        long membershipId, String body) {
        return enqueue(account, roomId, membershipId, body, 0, 0, false);
    }

    private Entry enqueue(AccountScope account, long roomId, long membershipId, String body,
                          long replyToMessageId, long editorRevision,boolean consumeDraft) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        if(editorRevision<0)throw new IllegalArgumentException("Current editor revision required");
        OutboxPolicy.requireRecordId(roomId);
        OutboxPolicy.requireRecordId(membershipId);
        if (replyToMessageId < 0) throw new IllegalArgumentException("Invalid reply reference");
        if (replyToMessageId > 0) OutboxPolicy.requireRecordId(replyToMessageId);
        OutboxPolicy.requireText(body);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            try (Cursor total = db.rawQuery("SELECT COUNT(*),COALESCE(SUM(length(CAST(body AS BLOB))),0),"
                    + "COALESCE(SUM(CASE WHEN room_id=? AND membership_id=? THEN 1 ELSE 0 END),0) "
                    + "FROM pending_text WHERE account_key=?",
                    new String[]{String.valueOf(roomId), String.valueOf(membershipId), account.key})) {
                total.moveToFirst();
                if (total.getLong(0) >= MAX_PER_ACCOUNT || total.getLong(2) >= MAX_PER_ROOM
                        || total.getLong(1) + body.getBytes(StandardCharsets.UTF_8).length > MAX_ACCOUNT_BYTES)
                    throw new IllegalStateException("Text queue capacity reached");
            }
            ContentValues values = new ContentValues();
            values.put("account_key", account.key);
            values.put("room_id", roomId);
            values.put("membership_id", membershipId);
            values.put("client_uuid", UUID.randomUUID().toString());
            values.put("body", body);
            if (replyToMessageId > 0) values.put("reply_to_message_id", replyToMessageId);
            values.put("created_at", System.currentTimeMillis());
            values.put("queue_state", "queued");
            long id = db.insertOrThrow(TABLE, null, values);
            BChatSendTickets.admitText(db, account, id, roomId, membershipId, values.getAsString("client_uuid"));
            Entry result = find(db, account, id);
            if (consumeDraft)
                consumeDraft(db,account,roomId,membershipId,body,replyToMessageId,editorRevision);
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
                COLUMNS,
                "account_key=? AND room_id=? AND membership_id=?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)},
                null, null, "_id ASC", "1")) {
            return rows.moveToFirst() ? read(rows) : null;
        }
    }

    /** An old membership's UUID must never be retried under the new membership. */
    public Entry firstStale(AccountScope account, long roomId, long currentMembershipId) {
        requireScope(account, roomId, currentMembershipId);
        try (Cursor rows = getReadableDatabase().query(TABLE,
                COLUMNS,
                "account_key=? AND room_id=? AND membership_id<>?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(currentMembershipId)},
                null, null, "_id ASC", "1")) {
            return rows.moveToFirst() ? read(rows) : null;
        }
    }

    /** Account-only cursor; no room membership is assumed for local text recovery. */
    public List<Entry> pageForAccount(AccountScope account, long afterId) {
        if (account == null || afterId < 0) throw new IllegalArgumentException("Verified account required");
        List<Entry> entries = new ArrayList<>();
        try (Cursor rows = getReadableDatabase().query(TABLE,
                COLUMNS,
                "account_key=? AND _id>?", new String[]{account.key, String.valueOf(afterId)},
                null, null, "_id ASC", "31")) {
            while (rows.moveToNext()) entries.add(read(rows));
        }
        return entries;
    }

    private static Entry read(Cursor row) {
        return new Entry(row.getLong(0), row.getLong(1), row.getLong(2),
                row.getString(3), row.getString(4), row.getInt(5), row.isNull(6) ? 0 : row.getLong(6),
                row.getString(7), row.getInt(8), row.getLong(9), row.getLong(10), row.getLong(11), row.getLong(12),
                row.getString(13), row.getLong(14));
    }

    private static Entry find(SQLiteDatabase db, AccountScope account, long id) {
        try (Cursor rows = db.query(TABLE, COLUMNS, "account_key=? AND _id=?",
                new String[]{account.key, String.valueOf(id)}, null, null, null, "1")) {
            return rows.moveToFirst() ? read(rows) : null;
        }
    }

    public List<Entry> roomEntries(AccountScope account, long roomId, long membershipId) {
        requireScope(account, roomId, membershipId);
        List<Entry> entries = new ArrayList<>();
        try (Cursor rows = getReadableDatabase().query(TABLE, COLUMNS,
                "account_key=? AND room_id=? AND membership_id=?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)},
                null, null, "_id ASC", String.valueOf(MAX_PER_ROOM))) {
            while (rows.moveToNext()) entries.add(read(rows));
        }
        return Collections.unmodifiableList(entries);
    }

    /** A reopened process keeps attempts and UUIDs; a previously dispatched request is uncertain. */
    public void recoverInterrupted(AccountScope account) {
        ContentValues values = new ContentValues();
        values.put("queue_state", "uncertain"); values.put("lease_until", 0);
        getWritableDatabase().update(TABLE, values, "account_key=? AND queue_state='sending'",
                new String[]{account.key});
        tickets().recover(account);
    }

    /** Claims only the ordered head. Review/receipt heads never permit a later write to overtake. */
    public Entry claimHead(AccountScope account, long roomId, long membershipId, long now) {
        requireScope(account, roomId, membershipId);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            Entry entry = first(db, account, roomId, membershipId);
            if (entry == null || "review".equals(entry.state) || "receipt".equals(entry.state)
                    || entry.nextAttemptAt > now || ("sending".equals(entry.state) && entry.leaseUntil > now)) return null;
            BChatSendTickets.Ticket ticket = BChatSendTickets.claim(db, account, roomId, membershipId,
                    "text", UUID.randomUUID().toString(), now);
            if (ticket == null) { db.setTransactionSuccessful(); return null; }
            if (ticket.textId != entry.id) return null;
            if (entry.attempts >= OutboxPolicy.MAX_ATTEMPTS) {
                ContentValues exhausted = new ContentValues();
                exhausted.put("queue_state", "review"); exhausted.put("review_code", 1);
                db.update(TABLE, exhausted, "_id=? AND account_key=?",
                        new String[]{String.valueOf(entry.id), account.key});
                db.setTransactionSuccessful(); return null;
            }
            ContentValues claimed = new ContentValues();
            claimed.put("queue_state", "sending"); claimed.put("attempts", entry.attempts + 1);
            claimed.put("lease_until", now + OutboxPolicy.LEASE_MILLIS);
            claimed.put("claim_owner", ticket.owner); claimed.put("claim_generation", ticket.generation);
            db.update(TABLE, claimed, "_id=? AND account_key=?",
                    new String[]{String.valueOf(entry.id), account.key});
            Entry result = find(db, account, entry.id);
            db.setTransactionSuccessful(); return result;
        } finally { db.endTransaction(); }
    }

    public boolean recordFailure(AccountScope account, Entry claim, boolean permanent, long now) {
        if (account == null || claim == null) throw new IllegalArgumentException("Claim required");
        ContentValues values = new ContentValues();
        boolean review = permanent || claim.attempts >= OutboxPolicy.MAX_ATTEMPTS;
        values.put("queue_state", review ? "review" : "uncertain");
        values.put("review_code", review ? 1 : 0); values.put("lease_until", 0);
        values.put("next_attempt_at", review ? 0 : now + OutboxPolicy.backoffMillis(Math.max(1, claim.attempts)));
        return updateClaim(account, claim, values, review ? "review" : "uncertain", 0, false, now);
    }

    private boolean updateClaim(AccountScope account, Entry claim, ContentValues values, String state,
            long message, boolean undo, long now) {
        SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
        BChatSendTickets.Ticket t=BChatSendTickets.text(db,account,claim.id);
        if(t==null||!t.owner.equals(claim.claimOwner)||t.generation!=claim.claimGeneration)return false;
        int changed=db.update(TABLE, values,
                "account_key=? AND _id=? AND client_uuid=? AND queue_state='sending' AND attempts=? AND lease_until=?",
                new String[]{account.key, String.valueOf(claim.id), claim.uuid, String.valueOf(claim.attempts),
                        String.valueOf(claim.leaseUntil)});
        if(changed!=1||!tickets().transition(db,account,t,state,0,message,undo,now))return false;
        db.setTransactionSuccessful();return true;
        }finally{db.endTransaction();}
    }

    /** A busy transport did not dispatch this claim, so it must not consume a retry attempt. */
    public boolean deferUndispatched(AccountScope account, Entry claim) {
        if (account == null || claim == null) throw new IllegalArgumentException("Claim required");
        ContentValues values = new ContentValues();
        values.put("queue_state", "queued"); values.put("attempts", Math.max(0, claim.attempts - 1));
        values.put("lease_until", 0); values.put("next_attempt_at", 0);
        return updateClaim(account, claim, values, "queued", 0, true, 0);
    }

    /** The exact, validated ACK persists before any screen-dependent canonical GET. */
    public boolean recordReceipt(AccountScope account, Entry entry, long messageId) {
        OutboxPolicy.requireRecordId(messageId);
        if (account == null || entry == null) throw new IllegalArgumentException("Receipt required");
        ContentValues values = new ContentValues();
        values.put("queue_state", "receipt"); values.put("message_id", messageId);
        values.put("lease_until", 0); values.put("next_attempt_at", 0);
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();
        try {
        BChatSendTickets.Ticket ticket=BChatSendTickets.text(db,account,entry.id);
        if(ticket==null||!ticket.owner.equals(entry.claimOwner)||ticket.generation!=entry.claimGeneration)return false;
        int changed=db.update(TABLE, values,
                "account_key=? AND _id=? AND room_id=? AND membership_id=? AND client_uuid=? "
                        + "AND body=? AND COALESCE(reply_to_message_id,0)=CAST(? AS INTEGER) "
                        + "AND (message_id=0 OR message_id=CAST(? AS INTEGER))",
                new String[]{account.key, String.valueOf(entry.id), String.valueOf(entry.roomId),
                        String.valueOf(entry.membershipId), entry.uuid, entry.body,
                        String.valueOf(entry.replyToMessageId), String.valueOf(messageId)});
        if(changed!=1||!tickets().transition(db,account,ticket,"receipt",0,messageId,false,0))return false;
        db.setTransactionSuccessful();return true;
        }finally{db.endTransaction();}
    }

    /** Preserve a permanent 400/413 review state across redraw and process death. */
    public boolean recordRejected(AccountScope account, Entry entry) {
        if (account == null || entry == null) throw new IllegalArgumentException("Pending scope required");
        ContentValues values = new ContentValues();
        values.put("review_code", 1);
        values.put("queue_state", "review"); values.put("lease_until", 0);
        SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
        BChatSendTickets.Ticket ticket=BChatSendTickets.text(db,account,entry.id);
        if(ticket==null||!ticket.owner.equals(entry.claimOwner)||ticket.generation!=entry.claimGeneration
                ||"receipt".equals(ticket.state))return false;
        int changed=db.update(TABLE, values,
                "_id=? AND account_key=? AND room_id=? AND membership_id=? AND client_uuid=? AND body=? " +
                        "AND COALESCE(reply_to_message_id,0)=CAST(? AS INTEGER)",
                new String[]{String.valueOf(entry.id), account.key, String.valueOf(entry.roomId),
                        String.valueOf(entry.membershipId), entry.uuid, entry.body,
                        String.valueOf(entry.replyToMessageId)});
        if(changed!=1||!tickets().review(db,account,ticket))return false;
        db.setTransactionSuccessful();return true;
        }finally{db.endTransaction();}
    }

    public String draft(AccountScope account, long roomId, long membershipId) {
        requireScope(account, roomId, membershipId);
        return draft(getReadableDatabase(), account, roomId, membershipId);
    }

    public static final class Draft {
        public final String body;
        public final long replyToMessageId,editorRevision;
        Draft(String body, long reply,long revision) { this.body = body; replyToMessageId = reply;editorRevision=revision; }
    }

    public Draft draftRecord(AccountScope account, long roomId, long membershipId) {
        requireScope(account, roomId, membershipId);
        try (Cursor rows = getReadableDatabase().query("draft_text", new String[]{"body", "reply_to_message_id","editor_revision"},
                "account_key=? AND room_id=? AND membership_id=?",
                new String[]{account.key, String.valueOf(roomId), String.valueOf(membershipId)},
                null, null, null, "1")) {
            return rows.moveToFirst() ? new Draft(rows.getString(0), rows.isNull(1) ? 0 : rows.getLong(1),rows.getLong(2)) : null;
        }
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
        saveDraft(account, roomId, membershipId, body, 0);
    }

    public void saveDraft(AccountScope account, long roomId, long membershipId, String body, long replyToMessageId) {
        saveDraft(account,roomId,membershipId,body,replyToMessageId,0);
    }

    public void saveDraft(AccountScope account,long roomId,long membershipId,String body,long replyToMessageId,long editorRevision){
        requireScope(account, roomId, membershipId);
        if(editorRevision<0)throw new IllegalArgumentException("Current editor revision required");
        if (replyToMessageId < 0) throw new IllegalArgumentException("Invalid draft reply");
        if (replyToMessageId > 0) OutboxPolicy.requireRecordId(replyToMessageId);
        if (body == null || body.getBytes(StandardCharsets.UTF_8).length > 65536)
            throw new IllegalArgumentException("Draft exceeds local bound");
        ContentValues values = new ContentValues();
        values.put("account_key", account.key);
        values.put("room_id", roomId);
        values.put("membership_id", membershipId);
        values.put("body", body);
        values.put("editor_revision",editorRevision);
        if (replyToMessageId > 0) values.put("reply_to_message_id", replyToMessageId);
        else values.putNull("reply_to_message_id");
        if (getWritableDatabase().insertWithOnConflict("draft_text", null, values,
                SQLiteDatabase.CONFLICT_REPLACE) < 0) throw new IllegalStateException("Draft save failed");
    }

    static void consumeDraft(SQLiteDatabase db,AccountScope a,long room,long member,String body,long reply,long revision){
        db.delete("draft_text","account_key=? AND room_id=? AND membership_id=? AND body=? "
                +"AND COALESCE(reply_to_message_id,0)=CAST(? AS INTEGER) AND editor_revision=CAST(? AS INTEGER)",
                new String[]{a.key,""+room,""+member,body,""+reply,""+revision});
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
            if (entry.roomId == targetRoomId && entry.membershipId == targetMembershipId && entry.replyToMessageId > 0)
                values.put("reply_to_message_id", entry.replyToMessageId);
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
        return retireExact(account, entry, false);
    }

    /** Permission revocation invalidates both queued sends and unsent drafts. */
    public void purgeAccount(AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete(TABLE, "account_key=?", new String[]{account.key});
            BChatSendTickets.purge(db, account);
            db.delete("draft_text", "account_key=?", new String[]{account.key});
            db.delete("local_context", "account_key=?", new String[]{account.key});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public void saveContext(AccountScope account, BChatLocalState state) {
        if (account == null || state == null) throw new IllegalArgumentException("Account context required");
        ContentValues values = new ContentValues();
        values.put("account_key", account.key); values.put("state_json", state.toJson());
        if (getWritableDatabase().insertWithOnConflict("local_context", null, values,
                SQLiteDatabase.CONFLICT_REPLACE) < 0) throw new IllegalStateException("Context save failed");
    }

    public BChatLocalState context(AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Account context required");
        try (Cursor rows = getReadableDatabase().query("local_context", new String[]{"state_json"},
                "account_key=?", new String[]{account.key}, null, null, null, "1")) {
            return rows.moveToFirst() ? BChatLocalState.fromJson(rows.getString(0)) : null;
        }
    }

    /** A reduced company scope retains drafts only in still-authorized rooms. */
    public void purgeExceptRooms(AccountScope account, java.util.Set<Long> allowedRoomIds) {
        if (account == null || allowedRoomIds == null)
            throw new IllegalArgumentException("Verified rooms required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            BChatSendTickets.purgeExceptRooms(db, account, allowedRoomIds);
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
        BChatSendTickets.Ticket ticket=BChatSendTickets.text(db,account,entry.id);
        if(ticket==null||!ticket.owner.equals(entry.claimOwner)||ticket.generation!=entry.claimGeneration)return 0;
        int changed=db.delete(TABLE,
                "_id=? AND account_key=? AND room_id=? AND membership_id=? AND client_uuid=? AND body=? " +
                        "AND COALESCE(reply_to_message_id,0)=CAST(? AS INTEGER)",
                new String[]{String.valueOf(entry.id), account.key, String.valueOf(entry.roomId),
                        String.valueOf(entry.membershipId), entry.uuid, entry.body,
                        String.valueOf(entry.replyToMessageId)});
        if(changed==1)BChatSendTickets.retireText(db,account,ticket);
        return changed;
    }

    private static void requireScope(AccountScope account, long roomId, long membershipId) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
        OutboxPolicy.requireRecordId(roomId);
        OutboxPolicy.requireRecordId(membershipId);
    }

    /** The caller must validate api_version, room, membership, UUID, state and message ID first. */
    public boolean acknowledge(AccountScope account, Entry entry) {
        if (account == null || entry == null) throw new IllegalArgumentException("Receipt scope required");
        return retireExact(account, entry, true);
    }

    private boolean retireExact(AccountScope account, Entry entry,boolean requireReceipt) {
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();
        try {
            if(requireReceipt){
                Entry current=find(db,account,entry.id);
                BChatSendTickets.Ticket ticket=BChatSendTickets.text(db,account,entry.id);
                if(current==null||ticket==null||!"receipt".equals(current.state)||current.messageId<=0
                        ||!"receipt".equals(ticket.state)||ticket.messageId!=current.messageId
                        ||entry.messageId!=current.messageId)return false;
            }
            boolean removed=deleteExact(db,account,entry)==1;db.setTransactionSuccessful();return removed;
        }
        finally { db.endTransaction(); }
    }

    public static final class Entry {
        public final long id, roomId, membershipId;
        public final long replyToMessageId;
        public final int reviewCode;
        public final String uuid, body;
        public final String state;
        public final int attempts;
        public final long nextAttemptAt, leaseUntil, messageId, createdAt;
        public final String claimOwner;
        public final long claimGeneration;
        private Entry(long id, long roomId, long membershipId, String uuid, String body, int reviewCode,
                      long replyToMessageId, String state, int attempts, long nextAttemptAt,
                      long leaseUntil, long messageId, long createdAt, String owner, long generation) {
            this.id = id; this.roomId = roomId; this.membershipId = membershipId;
            this.uuid = uuid; this.body = body; this.reviewCode = reviewCode;
            this.replyToMessageId = replyToMessageId;
            this.state = state; this.attempts = attempts; this.nextAttemptAt = nextAttemptAt;
            this.leaseUntil = leaseUntil; this.messageId = messageId; this.createdAt = createdAt;
            this.claimOwner = owner; this.claimGeneration = generation;
        }
    }
}

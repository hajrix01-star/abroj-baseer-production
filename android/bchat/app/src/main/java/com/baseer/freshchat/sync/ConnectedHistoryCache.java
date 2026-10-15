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
        private Snapshot(AccountScope account, List<RoomRecord> rooms) {
            this.account = account;
            this.rooms = rooms;
        }
    }

    public ConnectedHistoryCache(Context context) {
        super(context, FILE, null, 1);
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
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        throw new IllegalStateException("Unknown BChat history schema");
    }

    /** A verified room list replaces the previous membership set atomically. */
    public void reconcile(AccountScope account, boolean remembered, List<RoomRecord> rooms) {
        if (account == null || rooms == null || rooms.size() > 100)
            throw new IllegalArgumentException("Verified scope and rooms required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
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
        try (Cursor rows = getReadableDatabase().query("account_scope",
                new String[]{"origin", "database_name", "user_id"},
                "remembered=1 AND origin=? AND database_name=? AND verified_at<=? AND verified_at>=?",
                new String[]{origin, database, String.valueOf(now), String.valueOf(cutoff)},
                null, null, "verified_at DESC", "1")) {
            if (!rows.moveToFirst()) return null;
            scope = new AccountScope(rows.getString(0), rows.getString(1), rows.getLong(2));
        }
        List<RoomRecord> rooms = rooms(scope);
        return rooms.isEmpty() ? null : new Snapshot(scope, rooms);
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
            db.delete("cached_message", "account_key=? AND room_id=?", scope);
            db.delete("cached_room", "account_key=? AND room_id=?", scope);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** A page must already have passed the v2 response validator. */
    public void savePage(AccountScope account, long roomId, long membershipId,
                         List<JSONObject> page) throws Exception {
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
                if (bytes <= 0 || bytes > MAX_MESSAGE_BYTES) continue;
                String createdAt = item.getString("created_at");
                ContentValues values = new ContentValues();
                values.put("account_key", account.key);
                values.put("room_id", roomId);
                values.put("membership_id", membershipId);
                values.put("message_id", id);
                values.put("payload_json", payload);
                values.put("payload_bytes", bytes);
                values.put("created_at", createdAt);
                db.insertWithOnConflict("cached_message", null, values, SQLiteDatabase.CONFLICT_REPLACE);
            }
            trim(db, account, roomId, membershipId);
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
        db.execSQL("DELETE FROM cached_message WHERE rowid IN (SELECT rowid FROM cached_message "
                + "WHERE account_key=? AND room_id=? AND membership_id=? "
                + "ORDER BY message_id DESC LIMIT -1 OFFSET ?)",
                new Object[]{account.key, roomId, membershipId, MAX_PER_ROOM});
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
                    + "ORDER BY created_at ASC,message_id ASC LIMIT 128", new String[]{account.key})) {
                if (!oldest.moveToFirst()) break;
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

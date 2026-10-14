package com.baseer.freshchat.sync;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.util.UUID;

/**
 * Native SQLite is the durable local queue (no new dependency or transport). All mutations are
 * transactions, scoped to a verified session identity. Never store cookies/passwords in payloads.
 * This foundation is intentionally not wired to the synthetic demo or any network worker.
 */
public final class DurableOutbox extends SQLiteOpenHelper {
    public static final int MAX_PENDING_PER_ACCOUNT = 1_000;
    private static final String TABLE = "message_outbox";
    private static final String[] COLUMNS = {"_id", "account_key", "company_id", "channel_id",
            "client_uuid", "payload", "payload_hash", "state", "attempts", "next_attempt_at",
            "lease_until", "lease_token", "message_id"};

    public DurableOutbox(Context context) {
        super(context.getApplicationContext(), "bchat-authenticated-outbox.db", null, 1);
        setWriteAheadLoggingEnabled(true);
    }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE " + TABLE + " (" +
                "_id INTEGER PRIMARY KEY, account_key TEXT NOT NULL," +
                "company_id INTEGER NOT NULL CHECK(company_id>0)," +
                "channel_id INTEGER NOT NULL CHECK(channel_id>0)," +
                "client_uuid TEXT NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL," +
                "state TEXT NOT NULL CHECK(state IN ('QUEUED','IN_FLIGHT','RETRY','AUTH_REQUIRED','FAILED','SENT'))," +
                "attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0)," +
                "created_at INTEGER NOT NULL,next_attempt_at INTEGER NOT NULL," +
                "lease_until INTEGER NOT NULL DEFAULT 0,lease_token TEXT," +
                "message_id INTEGER CHECK(message_id>0),failure_code TEXT," +
                "UNIQUE(account_key,client_uuid))");
        db.execSQL("CREATE TABLE outbox_auth_pause (account_key TEXT PRIMARY KEY, paused_at INTEGER NOT NULL)");
        db.execSQL("CREATE INDEX outbox_due ON " + TABLE + "(account_key,state,next_attempt_at,lease_until)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // Never replace/drop the queue when a future schema version is introduced.
        throw new IllegalStateException("An explicit non-destructive outbox migration is required");
    }

    /** Returns the existing request on exact replay; a UUID may never change its original payload. */
    public Entry enqueue(AccountScope account, MessageRequest request, long now) {
        requireAccount(account);
        if (request == null || now < 0) throw new IllegalArgumentException("Request and time are required");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            Entry existing = findByUuid(db, account, request.clientUuid);
            if (existing != null) {
                if (existing.companyId != request.companyId || existing.channelId != request.channelId ||
                        !existing.payload.equals(request.payload)) throw new IllegalArgumentException("UUID payload conflict");
                db.setTransactionSuccessful();
                return existing;
            }
            try (Cursor count = db.rawQuery("SELECT COUNT(*) FROM " + TABLE +
                    " WHERE account_key=? AND state!='SENT'", new String[]{account.key})) {
                if (!count.moveToFirst() || count.getLong(0) >= MAX_PENDING_PER_ACCOUNT) {
                    throw new IllegalStateException("Outbox is full; review pending messages before adding more");
                }
            }
            ContentValues value = new ContentValues();
            value.put("account_key", account.key);
            value.put("company_id", request.companyId);
            value.put("channel_id", request.channelId);
            value.put("client_uuid", request.clientUuid);
            value.put("payload", request.payload);
            value.put("payload_hash", request.payloadHash);
            value.put("state", OutboxPolicy.State.QUEUED.name());
            value.put("created_at", now);
            value.put("next_attempt_at", now);
            db.insertOrThrow(TABLE, null, value);
            Entry result = find(db, account, request.companyId, request.channelId, request.clientUuid);
            db.setTransactionSuccessful();
            return result;
        } finally { db.endTransaction(); }
    }

    /** Claims one request. Expired process leases recover; retries remain bounded across restarts. */
    public Entry claimNext(AccountScope account, long now) {
        requireAccount(account);
        if (now < 0 || now > Long.MAX_VALUE - OutboxPolicy.LEASE_MILLIS) throw new IllegalArgumentException("Invalid time");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            try (Cursor paused = db.rawQuery("SELECT 1 FROM outbox_auth_pause WHERE account_key=?", new String[]{account.key})) {
                if (paused.moveToFirst()) { db.setTransactionSuccessful(); return null; }
            }
            ContentValues exhausted = new ContentValues();
            exhausted.put("state", OutboxPolicy.State.FAILED.name());
            exhausted.put("failure_code", "retry_exhausted");
            exhausted.putNull("lease_token");
            exhausted.put("lease_until", 0);
            db.update(TABLE, exhausted, "account_key=? AND attempts>=? AND state='IN_FLIGHT' AND lease_until<=?",
                    new String[]{account.key, String.valueOf(OutboxPolicy.MAX_ATTEMPTS), String.valueOf(now)});
            Entry candidate;
            try (Cursor rows = db.query(TABLE, COLUMNS,
                    "account_key=? AND attempts<? AND ((state IN ('QUEUED','RETRY') AND next_attempt_at<=?) " +
                            "OR (state='IN_FLIGHT' AND lease_until<=?))",
                    new String[]{account.key, String.valueOf(OutboxPolicy.MAX_ATTEMPTS), String.valueOf(now), String.valueOf(now)},
                    null, null, "created_at ASC,_id ASC", "1")) {
                candidate = rows.moveToFirst() ? read(rows) : null;
            }
            if (candidate == null) { db.setTransactionSuccessful(); return null; }
            ContentValues claim = new ContentValues();
            claim.put("state", OutboxPolicy.State.IN_FLIGHT.name());
            claim.put("attempts", candidate.attempts + 1);
            claim.put("lease_until", now + OutboxPolicy.LEASE_MILLIS);
            claim.put("lease_token", UUID.randomUUID().toString());
            db.update(TABLE, claim, "_id=? AND account_key=?", new String[]{String.valueOf(candidate.id), account.key});
            Entry result = find(db, account, candidate.companyId, candidate.channelId, candidate.clientUuid);
            db.setTransactionSuccessful();
            return result;
        } finally { db.endTransaction(); }
    }

    /** A stale failed attempt must not overwrite a new claim or a successful acknowledgement. */
    public boolean recordFailure(AccountScope account, Entry claim, OutboxPolicy.Failure failure, long now) {
        requireClaim(account, claim);
        if (now < 0 || now > Long.MAX_VALUE - OutboxPolicy.MAX_BACKOFF_MILLIS) throw new IllegalArgumentException("Invalid time");
        OutboxPolicy.State state = OutboxPolicy.afterFailure(failure, claim.attempts);
        ContentValues values = new ContentValues();
        values.put("state", state.name());
        values.put("next_attempt_at", now + OutboxPolicy.backoffMillis(claim.attempts));
        values.put("lease_until", 0);
        values.putNull("lease_token");
        // Use bounded codes only. Raw response bodies might contain confidential message/file data.
        values.put("failure_code", failure.name().toLowerCase(java.util.Locale.ROOT));
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            boolean accepted = db.update(TABLE, values,
                    "_id=? AND account_key=? AND state='IN_FLIGHT' AND lease_token=?",
                    new String[]{String.valueOf(claim.id), account.key, claim.leaseToken}) == 1;
            if (accepted && failure == OutboxPolicy.Failure.AUTHENTICATION) {
                ContentValues pause = new ContentValues();
                pause.put("account_key", account.key);
                pause.put("paused_at", now);
                db.insertWithOnConflict("outbox_auth_pause", null, pause, SQLiteDatabase.CONFLICT_REPLACE);
            }
            db.setTransactionSuccessful();
            return accepted;
        } finally { db.endTransaction(); }
    }

    /** Only an authenticated API response for this exact immutable request can establish 'sent'. */
    public void acknowledge(AccountScope account, Entry claim, int apiVersion, long companyId,
                            long channelId, String returnedUuid, long messageId, String state) {
        requireClaim(account, claim);
        OutboxPolicy.requireAcknowledgement(claim.clientUuid, returnedUuid, messageId, state);
        if (apiVersion != 1 || companyId != claim.companyId || channelId != claim.channelId) {
            throw new IllegalArgumentException("Acknowledgement scope mismatch");
        }
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            Entry current = find(db, account, companyId, channelId, claim.clientUuid);
            if (current == null || !current.payload.equals(claim.payload)) throw new IllegalStateException("Request no longer exists");
            if (current.messageId != null && current.messageId != messageId) {
                throw new IllegalStateException("Conflicting canonical message ID");
            }
            ContentValues values = new ContentValues();
            values.put("state", OutboxPolicy.State.SENT.name());
            values.put("message_id", messageId);
            values.put("lease_until", 0);
            values.putNull("lease_token");
            values.putNull("failure_code");
            db.update(TABLE, values, "_id=? AND account_key=?", new String[]{String.valueOf(current.id), account.key});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    /** Call only after a new authenticated bootstrap verifies the same immutable account identity. */
    public int resumeAfterAuthentication(AccountScope verifiedAccount, long now) {
        requireAccount(verifiedAccount);
        if (now < 0) throw new IllegalArgumentException("Invalid time");
        ContentValues values = new ContentValues();
        values.put("state", OutboxPolicy.State.QUEUED.name());
        values.put("attempts", 0);
        values.put("next_attempt_at", now);
        values.putNull("failure_code");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            int resumed = db.update(TABLE, values, "account_key=? AND state='AUTH_REQUIRED'",
                    new String[]{verifiedAccount.key});
            db.delete("outbox_auth_pause", "account_key=?", new String[]{verifiedAccount.key});
            db.setTransactionSuccessful();
            return resumed;
        } finally { db.endTransaction(); }
    }

    public Entry find(AccountScope account, long companyId, long channelId, String uuid) {
        requireAccount(account);
        return find(getReadableDatabase(), account, companyId, channelId, OutboxPolicy.requireUuid(uuid));
    }

    private static Entry findByUuid(SQLiteDatabase db, AccountScope account, String uuid) {
        try (Cursor rows = db.query(TABLE, COLUMNS, "account_key=? AND client_uuid=?",
                new String[]{account.key, uuid}, null, null, null)) {
            return rows.moveToFirst() ? read(rows) : null;
        }
    }

    private static Entry find(SQLiteDatabase db, AccountScope account, long company, long channel, String uuid) {
        try (Cursor rows = db.query(TABLE, COLUMNS, "account_key=? AND company_id=? AND channel_id=? AND client_uuid=?",
                new String[]{account.key, String.valueOf(company), String.valueOf(channel), uuid}, null, null, null)) {
            return rows.moveToFirst() ? read(rows) : null;
        }
    }

    private static Entry read(Cursor row) {
        return new Entry(row.getLong(0), row.getString(1), row.getLong(2), row.getLong(3), row.getString(4),
                row.getString(5), row.getString(6), OutboxPolicy.State.valueOf(row.getString(7)), row.getInt(8),
                row.getLong(9), row.getLong(10), row.getString(11), row.isNull(12) ? null : row.getLong(12));
    }

    private static void requireAccount(AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified account scope is required");
    }

    private static void requireClaim(AccountScope account, Entry claim) {
        requireAccount(account);
        if (claim == null || !account.key.equals(claim.accountKey) || claim.leaseToken == null ||
                claim.state != OutboxPolicy.State.IN_FLIGHT) throw new IllegalArgumentException("Wrong or unclaimed account request");
    }

    public static final class Entry {
        public final long id, companyId, channelId, nextAttemptAt, leaseUntil;
        public final String accountKey, clientUuid, payload, payloadHash, leaseToken;
        public final OutboxPolicy.State state;
        public final int attempts;
        public final Long messageId;

        private Entry(long id, String accountKey, long companyId, long channelId, String clientUuid,
                      String payload, String payloadHash, OutboxPolicy.State state, int attempts,
                      long nextAttemptAt, long leaseUntil, String leaseToken, Long messageId) {
            this.id = id; this.accountKey = accountKey; this.companyId = companyId; this.channelId = channelId;
            this.clientUuid = clientUuid; this.payload = payload; this.payloadHash = payloadHash;
            this.state = state; this.attempts = attempts; this.nextAttemptAt = nextAttemptAt;
            this.leaseUntil = leaseUntil; this.leaseToken = leaseToken; this.messageId = messageId;
        }
    }
}

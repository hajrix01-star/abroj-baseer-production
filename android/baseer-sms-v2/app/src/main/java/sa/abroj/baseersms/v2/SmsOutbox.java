package sa.abroj.baseersms.v2;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;

/** New v2 outbox: one dispatcher claims records atomically; an ACK preserves an auditable local state. */
final class SmsOutbox extends SQLiteOpenHelper {
    private static final String DB = "baseer_sms_v2.db";
    private static final long LEASE_MS = 90_000L;
    SmsOutbox(Context context) { super(context, DB, null, 1); }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE outbox (id INTEGER PRIMARY KEY, token TEXT NOT NULL UNIQUE, sender TEXT NOT NULL, body TEXT NOT NULL, received_at INTEGER NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, lease_until INTEGER, last_error TEXT, acknowledged_at INTEGER)");
        db.execSQL("CREATE INDEX outbox_dispatch_idx ON outbox(state, lease_until, id)");
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { throw new IllegalStateException("v2 has no legacy database migration"); }

    boolean capture(String sender, String body, long receivedAt) {
        try {
            ContentValues values = new ContentValues(); values.put("token", randomToken()); values.put("sender", SecureSettings.encryptLocal(sender)); values.put("body", SecureSettings.encryptLocal(body)); values.put("received_at", receivedAt); values.put("state", "queued");
            return getWritableDatabase().insert("outbox", null, values) != -1;
        } catch (Exception error) { throw new IllegalStateException("Could not encrypt SMS", error); }
    }
    List<Item> claimBatch(int limit) {
        SQLiteDatabase db = getWritableDatabase(); long now = System.currentTimeMillis(); long lease = now + LEASE_MS; List<Item> result = new ArrayList<>();
        db.beginTransaction();
        try (Cursor cursor = db.rawQuery("SELECT id,token,sender,body,received_at,attempts FROM outbox WHERE state IN ('queued','retry_scheduled') AND (lease_until IS NULL OR lease_until < ?) ORDER BY id LIMIT ?", new String[]{Long.toString(now), Integer.toString(limit)})) {
            while (cursor.moveToNext()) {
                long id = cursor.getLong(0); ContentValues update = new ContentValues(); update.put("state", "sending"); update.put("lease_until", lease);
                if (db.update("outbox", update, "id=? AND state IN ('queued','retry_scheduled') AND (lease_until IS NULL OR lease_until < ?)", new String[]{Long.toString(id), Long.toString(now)}) == 1)
                    try { result.add(new Item(id, cursor.getString(1), SecureSettings.decryptLocal(cursor.getString(2)), SecureSettings.decryptLocal(cursor.getString(3)), cursor.getLong(4), cursor.getInt(5))); }
                    catch (Exception corrupt) { repair(id, "decrypt_failed"); }
            }
        } finally { db.setTransactionSuccessful(); db.endTransaction(); }
        return result;
    }
    void acknowledge(long id) { update(id, "acknowledged", null, true); }
    void retry(long id, String reason) { update(id, "retry_scheduled", reason, false); }
    void block(long id, String reason) { update(id, "blocked_policy", reason, false); }
    void repair(long id, String reason) { update(id, "needs_repair", reason, false); }
    private void update(long id, String state, String error, boolean acknowledged) {
        ContentValues values = new ContentValues(); values.put("state", state); values.putNull("lease_until"); values.put("last_error", error);
        if (acknowledged) values.put("acknowledged_at", System.currentTimeMillis()); else values.put("attempts", "attempts + 1");
        if (acknowledged) getWritableDatabase().update("outbox", values, "id=?", new String[]{Long.toString(id)});
        else getWritableDatabase().execSQL("UPDATE outbox SET state=?, lease_until=NULL, last_error=?, attempts=attempts+1 WHERE id=?", new Object[]{state, error, id});
    }
    int countOpen() { return count("state != 'acknowledged'"); }
    long latestCapturedAt() { try (Cursor c = getReadableDatabase().rawQuery("SELECT COALESCE(MAX(received_at), 0) FROM outbox", null)) { c.moveToFirst(); return c.getLong(0); } }
    int count(String where) { try (Cursor c = getReadableDatabase().rawQuery("SELECT COUNT(*) FROM outbox WHERE " + where, null)) { c.moveToFirst(); return c.getInt(0); } }
    private static String randomToken() { byte[] bytes = new byte[24]; new SecureRandom().nextBytes(bytes); StringBuilder out = new StringBuilder(48); for (byte b : bytes) out.append(String.format("%02x", b)); return out.toString(); }
    static final class Item { final long id, receivedAt; final int attempts; final String token, sender, body; Item(long id,String token,String sender,String body,long receivedAt,int attempts){this.id=id;this.token=token;this.sender=sender;this.body=body;this.receivedAt=receivedAt;this.attempts=attempts;} }
}

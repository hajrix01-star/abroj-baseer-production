package com.baseer.freshchat.sync.test;

import android.app.Instrumentation;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Bundle;
import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.ConnectedHistoryCache;
import com.baseer.freshchat.sync.ReceiptDeliveryProtocol;
import com.baseer.freshchat.ReceiptActivityProbe;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Real Android SQLite / JSONObject, synthetic authenticated inputs. No HTTP, FCM or UI claim. */
public final class ReceiptInstrumentation extends Instrumentation {
    private static final String FILE = "bchat-v2-history-v1.db";
    private final AccountScope account = new AccountScope("https://receipts.invalid", "synthetic", 7);
    private final AccountScope other = new AccountScope("https://receipts.invalid", "synthetic", 8);
    private int checks;
    private String phase;
    private interface Action { void run() throws Exception; }
    private void check(boolean condition) { ++checks; if (!condition) throw new AssertionError("Assertion " + checks); }
    private void rejects(Action action) throws Exception {
        ++checks;
        try { action.run(); throw new AssertionError("Expected rejection " + checks); }
        catch (IllegalArgumentException | IllegalStateException expected) { }
    }
    private JSONObject message(long id) throws Exception {
        return new JSONObject().put("id", id).put("author_user_id", 9).put("author_name", "Synthetic")
                .put("text", "Synthetic immutable message " + id).put("created_at", "2026-10-18 01:00:00");
    }
    private List<ConnectedHistoryCache.RoomRecord> rooms(long epoch) {
        return Arrays.asList(new ConnectedHistoryCache.RoomRecord(11, epoch, 3, "One", "off", 1),
                new ConnectedHistoryCache.RoomRecord(12, 22, 3, "Two", "off", 1),
                new ConnectedHistoryCache.RoomRecord(13, 23, 3, "Three", "off", 1));
    }
    private ConnectedHistoryCache.ReceiptWork ref(long id) {
        return new ConnectedHistoryCache.ReceiptWork(11, 21, id, id + 1000, "fetch");
    }
    private ConnectedHistoryCache.ReceiptWork ack(long room, long epoch, long id, String kind) {
        return new ConnectedHistoryCache.ReceiptWork(room, epoch, id, 0, kind);
    }
    private long scalar(SQLiteDatabase db, String sql) {
        try (Cursor row = db.rawQuery(sql, null)) { row.moveToFirst(); return row.getLong(0); }
    }
    private JSONObject pending(long after, long id, boolean more) throws Exception {
        JSONArray rows = new JSONArray();
        if (id > 0) rows.put(new JSONObject().put("room_id", 11).put("membership_id", 21)
                .put("message_id", id).put("receipt_id", id + 1000));
        return new JSONObject().put("api_version", 2).put("refs", rows)
                .put("next_after_id", id > 0 ? id + 1000 : 0).put("has_more", more);
    }
    private void wire() throws Exception {
        check(ReceiptDeliveryProtocol.supported(new JSONObject().put("receipt_delivery_contract_version", 1)));
        check(!ReceiptDeliveryProtocol.supported(new JSONObject()));
        check(!ReceiptDeliveryProtocol.supported(new JSONObject().put("receipt_delivery_contract_version", "1")));
        check(!ReceiptDeliveryProtocol.supported(new JSONObject().put("receipt_delivery_contract_version", true)));
        check(ReceiptDeliveryProtocol.pending(pending(0, 1, true), 0).nextAfterId == 1001);
        check(ReceiptDeliveryProtocol.pending(pending(0, 0, false), 0).refs.isEmpty());
        for (int defect = 0; defect < 9; defect++) {
            JSONObject body = pending(0, 1, true);
            if (defect == 0) body.put("api_version", "2");
            if (defect == 1) body.put("next_after_id", 1002);
            if (defect == 2) body.put("has_more", "true");
            if (defect == 3) body.getJSONArray("refs").getJSONObject(0).put("membership_id", "21");
            if (defect == 4) body.getJSONArray("refs").getJSONObject(0).put("text", "not metadata");
            if (defect == 5) body.getJSONArray("refs").put(body.getJSONArray("refs").getJSONObject(0));
            if (defect == 6) body.put("padding", String.join("", Collections.nCopies(33000, "ع")));
            if (defect == 7) body.getJSONArray("refs").getJSONObject(0).put("message_id", true);
            if (defect == 8) body.getJSONArray("refs").getJSONObject(0).put("receipt_id", 2147483648L);
            rejects(() -> ReceiptDeliveryProtocol.pending(body, 0));
        }
        rejects(() -> ReceiptDeliveryProtocol.pending(pending(1001, 1, true), 1001));
        rejects(() -> ReceiptDeliveryProtocol.pending(pending(0, 0, true), 0));
        JSONObject accepted = new JSONObject().put("api_version", 2).put("message_id", 1)
                .put("delivered_at", "2026-10-18 01:02:03").put("read_at", JSONObject.NULL)
                .put("unread_count", 2).put("last_message_id", 3).put("replayed", true);
        ReceiptDeliveryProtocol.acknowledged(accepted, ack(11, 21, 1, "delivered")); check(true);
        rejects(() -> ReceiptDeliveryProtocol.acknowledged(accepted, ack(11, 21, 1, "read")));
        accepted.put("read_at", "2026-10-18 01:02:03");
        ReceiptDeliveryProtocol.acknowledged(accepted, ack(11, 21, 1, "read")); check(true);
        accepted.put("delivered_at", "2026-02-31 01:02:03");
        rejects(() -> ReceiptDeliveryProtocol.acknowledged(accepted, ack(11, 21, 1, "read")));
    }
    private void migration(Context context) throws Exception {
        context.deleteDatabase(FILE);
        try (SQLiteDatabase old = context.openOrCreateDatabase(FILE, 0, null)) {
            old.execSQL("CREATE TABLE account_scope(account_key TEXT PRIMARY KEY,origin TEXT NOT NULL,database_name TEXT NOT NULL,user_id INTEGER NOT NULL,remembered INTEGER NOT NULL,verified_at INTEGER NOT NULL)");
            old.execSQL("CREATE TABLE cached_room(account_key TEXT NOT NULL,room_id INTEGER NOT NULL,membership_id INTEGER NOT NULL,company_id INTEGER NOT NULL,name TEXT NOT NULL,policy TEXT NOT NULL,policy_version INTEGER NOT NULL,PRIMARY KEY(account_key,room_id))");
            old.execSQL("CREATE TABLE cached_message(account_key TEXT NOT NULL,room_id INTEGER NOT NULL,membership_id INTEGER NOT NULL,message_id INTEGER NOT NULL,payload_json TEXT NOT NULL,payload_bytes INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(account_key,room_id,membership_id,message_id))");
            old.execSQL("CREATE INDEX cached_message_page ON cached_message(account_key,room_id,membership_id,message_id DESC)");
            old.execSQL("CREATE INDEX cached_message_eviction ON cached_message(account_key,created_at,message_id)");
            old.execSQL("INSERT INTO account_scope VALUES(?,?,?,?,?,?)", new Object[]{account.key, account.origin, account.database, account.userId, 1, System.currentTimeMillis()});
            old.execSQL("INSERT INTO cached_room VALUES(?,?,?,?,?,?,?)", new Object[]{account.key,11,21,3,"One","off",1});
            String raw = message(1).toString();
            old.execSQL("INSERT INTO cached_message VALUES(?,?,?,?,?,?,?)", new Object[]{account.key,11,21,1,raw,raw.length(),"2026-10-18 01:00:00"});
            old.setVersion(1);
        }
        try (ConnectedHistoryCache cache = new ConnectedHistoryCache(context)) {
            check(cache.getReadableDatabase().getVersion() == 2);
            check(cache.page(account,11,21,0).size() == 1);
            check(cache.remembered(account.origin,account.database) != null);
            check(cache.receiptWork(account).isEmpty());
            rejects(() -> cache.queueRead(account,11,21,message(1))); // Legacy cached RAM is not fresh receipt evidence.
            cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(1)));
            check(cache.hasReceiptEvidence(account, ack(11,21,1,"delivered")));
        }
    }
    private void lifecycle(Context context) throws Exception {
        context.deleteDatabase(FILE);
        ConnectedHistoryCache cache = new ConnectedHistoryCache(context);
        cache.reconcile(account,true,rooms(21));
        cache.admitReceiptReferences(account,Arrays.asList(ref(1),ref(2)));
        check(cache.receiptWork(account).size() == 2);
        check(!cache.hasReceiptEvidence(account,ack(11,21,1,"delivered")));
        check(!cache.settleReceipt(account,ack(11,21,1,"delivered")));
        check(!cache.hasReceiptEvidence(other,ack(11,21,1,"delivered")));
        cache.close(); cache = new ConnectedHistoryCache(context);
        check(cache.receiptWork(account).size() == 2); // Durable references survive connection reopening.
        cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(1)));
        check(cache.receiptWork(account).size() == 2);
        check("delivered".equals(cache.receiptWork(account).get(0).kind));
        cache.queueRead(account,11,21,message(1));
        check(cache.receiptWork(account).size() == 3 && "read".equals(cache.receiptWork(account).get(0).kind));
        cache.close(); cache = new ConnectedHistoryCache(context);
        check(cache.hasReceiptEvidence(account,ack(11,21,1,"read")));
        check(cache.settleReceipt(account,ack(11,21,1,"read")));
        check(cache.receiptWork(account).size() == 1); // read settles delivery too, but never the unrelated reference.
        cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(1)));
        cache.queueRead(account,11,21,message(1));
        check(cache.receiptWork(account).size() == 1); // Rebinding a proven canonical bubble is quiet/idempotent.
        final ConnectedHistoryCache current = cache;
        rejects(() -> current.admitReceiptReferences(other,Collections.singletonList(ref(3))));
        cache.reconcile(account,true,rooms(31));
        check(cache.receiptWork(account).isEmpty() && cache.page(account,11,31,0).isEmpty());
        check(!cache.settleReceipt(account,ack(11,21,1,"read")));
        cache.savePageAndQueueDelivered(account,12,22,Collections.singletonList(message(10)));
        check(cache.receiptWork(account).size() == 1);
        cache.purgeRoom(account,12); check(cache.receiptWork(account).isEmpty());
        cache.reconcile(account,true,rooms(31));
        cache.savePageAndQueueDelivered(account,12,22,Collections.singletonList(message(10)));
        cache.purgeAccount(account); check(cache.receiptWork(account).isEmpty());
        cache.reconcile(account,true,rooms(21));
        cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(10)));
        cache.purgeOtherAccounts(other); check(cache.receiptWork(account).isEmpty());
        cache.close();
    }
    private void bounds(Context context) throws Exception {
        context.deleteDatabase(FILE);
        try (ConnectedHistoryCache cache = new ConnectedHistoryCache(context)) {
            cache.reconcile(account,true,rooms(21));
            for (int start=1;start<=1000;start+=30) {
                List<ConnectedHistoryCache.ReceiptWork> page=new ArrayList<>();
                for(int id=start;id<start+30&&id<=1000;id++)page.add(ref(id));
                cache.admitReceiptReferences(account,page);
            }
            check(cache.receiptWork(account).size()==1000);
            cache.admitReceiptReferences(account,Collections.singletonList(ref(1)));
            check(cache.receiptWork(account).size()==1000);
            rejects(()->cache.admitReceiptReferences(account,Collections.singletonList(ref(1001))));
            check(cache.receiptWork(account).size()==1000);
            cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(1)));
            check(cache.hasReceiptEvidence(account,ack(11,21,1,"delivered")));
            rejects(()->cache.queueRead(account,11,21,message(1))); // Combined refs+intents bound, not independent quotas.
            check(!cache.hasReceiptEvidence(account,ack(11,21,1,"read")));
            check(cache.settleReceipt(account,ack(11,21,1,"delivered")));
            cache.queueRead(account,11,21,message(1));
            check(cache.hasReceiptEvidence(account,ack(11,21,1,"read")));
            cache.purgeAll();cache.reconcile(account,true,rooms(21));
            cache.admitReceiptReferences(account,Collections.singletonList(ref(1)));
            cache.getWritableDatabase().execSQL("UPDATE receipt_work SET metadata_bytes=1048576");
            rejects(()->cache.admitReceiptReferences(account,Collections.singletonList(ref(2))));
            check(scalar(cache.getReadableDatabase(),"SELECT COUNT(*) FROM receipt_work")==1);
            cache.purgeAll();cache.reconcile(account,true,rooms(21));
            for(int start=1;start<=500;start+=30){
                List<JSONObject> page=new ArrayList<>();
                for(int id=start;id<start+30&&id<=500;id++)page.add(message(id));
                cache.savePageAndQueueDelivered(account,11,21,page);
            }
            check(scalar(cache.getReadableDatabase(),"SELECT COUNT(*) FROM cached_message")==500);
            cache.admitReceiptReferences(account,Collections.singletonList(ref(501)));
            rejects(()->cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(501))));
            check(scalar(cache.getReadableDatabase(),"SELECT COUNT(*) FROM cached_message")==500);
            check(cache.receiptWork(account).size()==501&&!cache.hasReceiptEvidence(account,ack(11,21,501,"delivered")));
            check(cache.hasReceiptEvidence(account,ack(11,21,1,"delivered"))); // Old pinned row survived trim.
            cache.settleReceipt(account,ack(11,21,1,"delivered"));
            cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(501)));
            check(cache.hasReceiptEvidence(account,ack(11,21,501,"delivered")));
            check(scalar(cache.getReadableDatabase(),"SELECT COUNT(*) FROM cached_message")==500);
            JSONObject tooLarge=message(502).put("padding",String.join("",Collections.nCopies(33000,"ع")));
            rejects(()->cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(tooLarge)));
            check(!cache.hasReceiptEvidence(account,ack(11,21,502,"delivered")));
            // The cache commit cannot precede its intent: force the INSERT itself to fail and inspect rollback.
            cache.settleReceipt(account,ack(11,21,2,"delivered"));
            cache.getWritableDatabase().execSQL("CREATE TRIGGER synthetic_receipt_failure BEFORE INSERT ON receipt_work BEGIN SELECT RAISE(ABORT,'synthetic'); END");
            try {cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(503)));throw new AssertionError();}
            catch(android.database.SQLException expected){check(true);}
            check(scalar(cache.getReadableDatabase(),"SELECT COUNT(*) FROM cached_message WHERE message_id=503")==0);
            cache.getWritableDatabase().execSQL("DROP TRIGGER synthetic_receipt_failure");
        }
    }
    private void restart(Context context, String phase) throws Exception {
        if ("seed-ref".equals(phase)) {
            context.deleteDatabase(FILE);
            try(ConnectedHistoryCache cache=new ConnectedHistoryCache(context)){
                cache.reconcile(account,true,rooms(21));cache.admitReceiptReferences(account,Collections.singletonList(ref(1)));
                check(cache.receiptWork(account).size()==1);
            }
        } else if("canonical".equals(phase)) {
            try(ConnectedHistoryCache cache=new ConnectedHistoryCache(context)){
                check("fetch".equals(cache.receiptWork(account).get(0).kind));
                cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(1)));
                check(cache.hasReceiptEvidence(account,ack(11,21,1,"delivered")));
            }
        } else if("settle".equals(phase)) {
            try(ConnectedHistoryCache cache=new ConnectedHistoryCache(context)){
                check(cache.hasReceiptEvidence(account,ack(11,21,1,"delivered")));
                check(cache.settleReceipt(account,ack(11,21,1,"delivered")));
                check(cache.receiptWork(account).isEmpty());
            }
        } else if("verify-settled".equals(phase)) {
            try(ConnectedHistoryCache cache=new ConnectedHistoryCache(context)){
                cache.savePageAndQueueDelivered(account,11,21,Collections.singletonList(message(1)));
                check(cache.receiptWork(account).isEmpty());
                check(cache.page(account,11,21,0).size()==1);
            }
        } else throw new IllegalArgumentException("Unknown isolated test phase");
    }
    @Override public void onCreate(Bundle args) { super.onCreate(args);phase=args.getString("phase","all");start(); }
    @Override public void onStart() {
        Bundle result=new Bundle();Context context=getContext();
        try {
            if(!"com.baseer.freshchat.receipts.test".equals(context.getPackageName()))throw new IllegalStateException("Not isolated test namespace");
            check(android.os.Looper.myLooper()!=android.os.Looper.getMainLooper());
            if("all".equals(phase)){wire();migration(context);lifecycle(context);bounds(context);context.deleteDatabase(FILE);}
            else if("coordinator".equals(phase)){checks+=ReceiptActivityProbe.run(context);context.deleteDatabase(FILE);}
            else if("invalidation".equals(phase)){checks+=ReceiptActivityProbe.runInvalidation(context);context.deleteDatabase(FILE);}
            else if("revalidation".equals(phase)){checks+=ReceiptActivityProbe.runRevalidation(context);context.deleteDatabase(FILE);}
            else if("room-ownership".equals(phase)){checks+=ReceiptActivityProbe.runRoomOwnership(context);context.deleteDatabase(FILE);}
            else restart(context,phase);
            result.putString("stream","PASS: "+checks+" receipt SQLite/wire assertions; phase="+phase+"\n");finish(0,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error+" at "+Arrays.toString(error.getStackTrace())+"\n");finish(1,result);}
    }
}

package com.baseer.freshchat.sync;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import java.util.*;

/** One durable ordering authority; files remain in the existing AtomicFile store. Off-main only. */
public final class BChatSendTickets {
    private static final String TABLE = "send_ticket";
    private static final String[] C = {"seq","room_id","membership_id","company_id","kind","ref_id",
            "client_uuid","upload_uuid","fingerprint","state","legacy","owner","claim_generation",
            "attempts","lease_until","next_attempt_at","media_id","message_id"};
    private final BChatV2Outbox box;
    BChatSendTickets(BChatV2Outbox box) { this.box=box; }
    static void create(SQLiteDatabase db, boolean migrate) {
        db.execSQL("CREATE TABLE send_ticket (seq INTEGER PRIMARY KEY AUTOINCREMENT, account_key TEXT NOT NULL, "
                + "room_id INTEGER NOT NULL,membership_id INTEGER NOT NULL,company_id INTEGER NOT NULL DEFAULT 0,"
                + "kind TEXT NOT NULL,ref_id INTEGER NOT NULL DEFAULT 0,client_uuid TEXT NOT NULL,"
                + "upload_uuid TEXT NOT NULL DEFAULT '',fingerprint TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,"
                + "legacy INTEGER NOT NULL DEFAULT 0,owner TEXT NOT NULL DEFAULT '',claim_generation INTEGER NOT NULL DEFAULT 0,"
                + "attempts INTEGER NOT NULL DEFAULT 0,lease_until INTEGER NOT NULL DEFAULT 0,"
                + "next_attempt_at INTEGER NOT NULL DEFAULT 0,media_id INTEGER NOT NULL DEFAULT 0,message_id INTEGER NOT NULL DEFAULT 0,"
                + "UNIQUE(account_key,kind,client_uuid))");
        db.execSQL("CREATE INDEX send_ticket_room ON send_ticket(account_key,room_id,membership_id,seq)");
        if (migrate) {
            // These IDs are references, NOT an invented interleaving with legacy media.
            db.execSQL("INSERT INTO send_ticket(account_key,room_id,membership_id,kind,ref_id,client_uuid,state,legacy,message_id,attempts) "
                    + "SELECT account_key,room_id,membership_id,'text',_id,client_uuid,"
                    + "CASE WHEN queue_state='receipt' THEN 'receipt' ELSE 'review' END,1,message_id,attempts FROM pending_text ORDER BY _id");
            db.execSQL("UPDATE pending_text SET queue_state='review',review_code=1 WHERE queue_state<>'receipt'");
        }
    }
    static void admitText(SQLiteDatabase db, AccountScope a, long id, long room, long member, String uuid) {
        ContentValues v=new ContentValues();v.put("account_key",a.key);v.put("room_id",room);v.put("membership_id",member);
        v.put("kind","text");v.put("ref_id",id);v.put("client_uuid",uuid);v.put("state","queued");db.insertOrThrow(TABLE,null,v);
    }
    private static Ticket read(Cursor r) { return new Ticket(r); }
    private static Ticket query(SQLiteDatabase db, AccountScope a, String selection, String[] extra, String order) {
        String[] args=new String[extra.length+1];args[0]=a.key;System.arraycopy(extra,0,args,1,extra.length);
        try(Cursor r=db.query(TABLE,C,"account_key=? AND "+selection,args,null,null,order,"1")){return r.moveToFirst()?read(r):null;}
    }
    public Ticket find(AccountScope a,String kind,String uuid) { return query(box.getReadableDatabase(),a,"kind=? AND client_uuid=?",new String[]{kind,uuid},null); }
    public List<Ticket> forAccount(AccountScope a) {
        List<Ticket> result=new ArrayList<>();
        try(Cursor r=box.getReadableDatabase().query(TABLE,C,"account_key=?",new String[]{a.key},null,null,"seq ASC","120")){
            while(r.moveToNext())result.add(read(r));
        }
        return Collections.unmodifiableList(result);
    }
    static Ticket text(SQLiteDatabase db,AccountScope a,long id) { return query(db,a,"kind='text' AND ref_id=?",new String[]{Long.toString(id)},null); }
    public Ticket head(AccountScope a,long room,long member) { return head(box.getReadableDatabase(),a,room,member); }
    static Ticket head(SQLiteDatabase db,AccountScope a,long room,long member) {
        return query(db,a,"room_id=? AND membership_id=?",new String[]{Long.toString(room),Long.toString(member)},
                "CASE WHEN legacy=1 THEN 0 ELSE 1 END,seq ASC");
    }
    public Ticket admitMedia(AccountScope a,BChatConnectedMediaStore.Entry e,boolean legacy) {
        return admitMedia(a,e,legacy,0);
    }
    public Ticket admitMedia(AccountScope a,BChatConnectedMediaStore.Entry e,boolean legacy,long editorRevision) {
        if(a==null||e==null||!a.key.equals(e.accountKey))throw new IllegalArgumentException("Media ticket scope required");
        if(!legacy&&editorRevision<0)throw new IllegalArgumentException("Current editor revision required");
        SQLiteDatabase db=box.getWritableDatabase();db.beginTransaction();
        try{
            Ticket old=query(db,a,"kind='media' AND client_uuid=?",new String[]{e.clientUuid},null);
            String fingerprint=e.requestFingerprint();
            if(old!=null){if(!old.matches(e))throw new IllegalStateException("Media ticket identity changed");return old;}
            try(Cursor count=db.rawQuery("SELECT COUNT(*) FROM send_ticket WHERE account_key=? AND kind='media'",new String[]{a.key})){
                count.moveToFirst();if(count.getLong(0)>=BChatConnectedMediaStore.MAX_PENDING_REQUESTS)
                    throw new IllegalStateException("Media queue capacity reached");
            }
            ContentValues v=new ContentValues();v.put("account_key",a.key);v.put("room_id",e.roomId);v.put("membership_id",e.membershipId);
            v.put("company_id",e.companyId);v.put("kind","media");v.put("client_uuid",e.clientUuid);v.put("upload_uuid",e.uploadUuid);
            v.put("fingerprint",fingerprint);v.put("state",legacy?"review":"queued");v.put("legacy",legacy?1:0);v.put("media_id",e.mediaId);
            long seq=db.insertOrThrow(TABLE,null,v);Ticket result=query(db,a,"seq=?",new String[]{Long.toString(seq)},null);
            if(!legacy)BChatV2Outbox.consumeDraft(db,a,e.roomId,e.membershipId,e.text,e.replyToMessageId,editorRevision);
            db.setTransactionSuccessful();return result;
        }finally{db.endTransaction();}
    }
    /** Explicit review only; keep the pre-new-ticket barrier until that exact legacy entry retires. */
    public boolean approveLegacyMedia(AccountScope a,Ticket t) {
        if(t==null||!"media".equals(t.kind))return false;
        ContentValues v=new ContentValues();v.put("state","queued");v.put("lease_until",0);v.put("next_attempt_at",0);
        v.put("owner","");v.put("claim_generation",t.generation+1);
        return box.getWritableDatabase().update(TABLE,v,"account_key=? AND seq=? AND client_uuid=? AND state<>'receipt' AND owner=? AND claim_generation=?",
                new String[]{a.key,""+t.sequence,t.uuid,t.owner,""+t.generation})==1;
    }
    public Ticket claimMediaHead(AccountScope a,long room,long member,String owner,long now) {
        SQLiteDatabase db=box.getWritableDatabase();db.beginTransaction();
        try{Ticket result=claim(db,a,room,member,"media",owner,now);db.setTransactionSuccessful();return result;}finally{db.endTransaction();}
    }
    static Ticket claim(SQLiteDatabase db,AccountScope a,long room,long member,String kind,String owner,long now) {
        if(owner==null||!UUID.fromString(owner).toString().equals(owner))throw new IllegalArgumentException("Claim owner required");
        Ticket t=head(db,a,room,member);
        if(t==null||!kind.equals(t.kind)||"review".equals(t.state)||"receipt".equals(t.state)
                ||t.nextAttemptAt>now||("sending".equals(t.state)&&t.leaseUntil>now))return null;
        if(t.attempts>=OutboxPolicy.MAX_ATTEMPTS){ContentValues v=new ContentValues();v.put("state","review");db.update(TABLE,v,"seq=?",new String[]{""+t.sequence});return null;}
        ContentValues v=new ContentValues();v.put("state","sending");v.put("owner",owner);v.put("claim_generation",t.generation+1);
        v.put("attempts",t.attempts+1);v.put("lease_until",now+OutboxPolicy.LEASE_MILLIS);
        db.update(TABLE,v,"seq=?",new String[]{""+t.sequence});return query(db,a,"seq=?",new String[]{""+t.sequence},null);
    }
    private static String[] exact(AccountScope a,Ticket t){return new String[]{a.key,""+t.sequence,t.uuid,t.owner,""+t.generation};}
    private static final String EXACT="account_key=? AND seq=? AND client_uuid=? AND owner=? AND claim_generation=?";
    public boolean current(AccountScope a,Ticket t){return t!=null&&query(box.getReadableDatabase(),a,"seq=? AND client_uuid=? AND owner=? AND claim_generation=?",
            new String[]{""+t.sequence,t.uuid,t.owner,""+t.generation},null)!=null;}
    public boolean sending(AccountScope a,Ticket t){Ticket found=t==null?null:query(box.getReadableDatabase(),a,"seq=?",new String[]{""+t.sequence},null);
        return found!=null&&found.sameClaim(t)&&"sending".equals(found.state);}
    boolean transition(SQLiteDatabase db,AccountScope a,Ticket t,String state,long media,long message,boolean undo,long now) {
        ContentValues v=new ContentValues();v.put("state",state);v.put("lease_until",0);
        if(media>0)v.put("media_id",media);if(message>0)v.put("message_id",message);
        if(undo)v.put("attempts",Math.max(0,t.attempts-1));
        v.put("next_attempt_at","uncertain".equals(state)?now+OutboxPolicy.backoffMillis(Math.max(1,t.attempts)):0);
        String allowed=message>0?"state IN ('sending','uploaded','uncertain','review','queued','receipt') AND (message_id=0 OR message_id="+message+")"
                :media>0?"state IN ('sending','uncertain','queued','review')":"state='sending'";
        return db.update(TABLE,v,EXACT+" AND "+allowed,exact(a,t))==1;
    }
    public boolean uploaded(AccountScope a,Ticket t,long media){OutboxPolicy.requireRecordId(media);return transition(box.getWritableDatabase(),a,t,"uploaded",media,0,false,0);}
    public boolean receipt(AccountScope a,Ticket t,long message){OutboxPolicy.requireRecordId(message);return transition(box.getWritableDatabase(),a,t,"receipt",0,message,false,0);}
    public boolean failed(AccountScope a,Ticket t,boolean permanent,long now){return transition(box.getWritableDatabase(),a,t,permanent?"review":"uncertain",0,0,false,now);}
    public boolean defer(AccountScope a,Ticket t){return transition(box.getWritableDatabase(),a,t,"queued",0,0,true,0);}
    /** Cancellation fences that attempt itself, not only a possible later claim. */
    public boolean cancel(AccountScope a,Ticket t,boolean dispatched,long now){
        ContentValues v=new ContentValues();v.put("state",dispatched?"uncertain":"queued");
        v.put("owner","");v.put("claim_generation",t.generation+1);v.put("lease_until",0);
        v.put("next_attempt_at",dispatched?now+OutboxPolicy.backoffMillis(Math.max(1,t.attempts)):0);
        if(!dispatched)v.put("attempts",Math.max(0,t.attempts-1));
        return box.getWritableDatabase().update(TABLE,v,EXACT+" AND state='sending'",exact(a,t))==1;
    }
    boolean review(SQLiteDatabase db,AccountScope a,Ticket t){
        ContentValues v=new ContentValues();v.put("state","review");v.put("lease_until",0);v.put("next_attempt_at",0);
        return db.update(TABLE,v,EXACT+" AND state<>'receipt'",exact(a,t))==1;
    }
    public void recover(AccountScope a){ContentValues v=new ContentValues();v.put("state","uncertain");v.put("lease_until",0);
        box.getWritableDatabase().update(TABLE,v,"account_key=? AND state='sending'",new String[]{a.key});}
    public interface Cleanup {void run()throws Exception;}
    /** Serialize a bounded private-file mutation with claim validation. Never pass HTTP/SAF here. */
    public boolean saveUploaded(AccountScope a,Ticket expected,long media,Cleanup write)throws Exception{
        SQLiteDatabase db=box.getWritableDatabase();db.beginTransaction();
        try{Ticket t=query(db,a,"seq=?",new String[]{""+expected.sequence},null);
            if(t==null||!t.sameClaim(expected)||"receipt".equals(t.state)||"uploaded".equals(t.state))return false;
            write.run();if(!transition(db,a,t,t.legacy&&"review".equals(t.state)?"review":"uploaded",media,0,false,0))return false;
            db.setTransactionSuccessful();return true;
        }finally{db.endTransaction();}
    }
    /** Explicit local discard also uses the captured generation, never a room-wide deletion. */
    public boolean discardMedia(AccountScope a,Ticket expected,Cleanup cleanup)throws Exception{
        SQLiteDatabase db=box.getWritableDatabase();db.beginTransaction();
        try{Ticket t=query(db,a,"seq=?",new String[]{""+expected.sequence},null);
            if(t==null||!t.sameClaim(expected)||"sending".equals(t.state))return false;
            cleanup.run();boolean removed=db.delete(TABLE,EXACT,exact(a,expected))==1;
            db.setTransactionSuccessful();return removed;
        }finally{db.endTransaction();}
    }
    /** SQLite -> store lock order, no provider/HTTP; receipt survives a failed file cleanup. */
    public boolean retireMedia(AccountScope a,Ticket expected,Cleanup cleanup)throws Exception{
        SQLiteDatabase db=box.getWritableDatabase();db.beginTransaction();
        try{Ticket t=query(db,a,"seq=?",new String[]{""+expected.sequence},null);
            if(t==null||!t.sameClaim(expected)||!"receipt".equals(t.state))return false;
            cleanup.run();boolean removed=db.delete(TABLE,EXACT,exact(a,expected))==1;db.setTransactionSuccessful();return removed;
        }finally{db.endTransaction();}
    }
    static boolean retireText(SQLiteDatabase db,AccountScope a,Ticket t){return t!=null&&db.delete(TABLE,EXACT,exact(a,t))==1;}
    static void purge(SQLiteDatabase db,AccountScope a){db.delete(TABLE,"account_key=?",new String[]{a.key});}
    public void purgeMedia(AccountScope a){box.getWritableDatabase().delete(TABLE,"account_key=? AND kind='media'",new String[]{a.key});}
    static void purgeExceptRooms(SQLiteDatabase db,AccountScope a,Set<Long> allowed){
        List<Long> remove=new ArrayList<>();try(Cursor r=db.query(TABLE,new String[]{"room_id"},"account_key=?",new String[]{a.key},null,null,null)){
            while(r.moveToNext())if(!allowed.contains(r.getLong(0)))remove.add(r.getLong(0));}
        for(long room:remove)db.delete(TABLE,"account_key=? AND room_id=?",new String[]{a.key,""+room});
    }
    public static final class Ticket {
        public final long sequence,roomId,membershipId,companyId,textId,generation,leaseUntil,nextAttemptAt,mediaId,messageId;
        public final int attempts;public final boolean legacy;public final String kind,uuid,uploadUuid,fingerprint,state,owner;
        Ticket(Cursor r){sequence=r.getLong(0);roomId=r.getLong(1);membershipId=r.getLong(2);companyId=r.getLong(3);kind=r.getString(4);textId=r.getLong(5);
            uuid=r.getString(6);uploadUuid=r.getString(7);fingerprint=r.getString(8);state=r.getString(9);legacy=r.getInt(10)!=0;owner=r.getString(11);
            generation=r.getLong(12);attempts=r.getInt(13);leaseUntil=r.getLong(14);nextAttemptAt=r.getLong(15);mediaId=r.getLong(16);messageId=r.getLong(17);}
        public boolean matches(BChatConnectedMediaStore.Entry e){return e!=null&&roomId==e.roomId&&membershipId==e.membershipId&&companyId==e.companyId
                &&uuid.equals(e.clientUuid)&&uploadUuid.equals(e.uploadUuid)&&fingerprint.equals(e.requestFingerprint());}
        public boolean sameClaim(Ticket t){return t!=null&&sequence==t.sequence&&uuid.equals(t.uuid)&&owner.equals(t.owner)&&generation==t.generation;}
    }
}

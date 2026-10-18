package com.baseer.freshchat.sync;

import android.os.Handler;
import android.os.Looper;
import java.io.IOException;
import java.lang.ref.WeakReference;
import java.util.*;

/** Serial-lane preparation + process-wide ownership across the SAF -> SQLite gap.
 * No monitor/lane is retained while a provider supplies bytes. A process restart
 * intentionally loses this ownership and recovers an unadmitted original as review. */
public final class BChatStageAdmission {
    private static final Map<String,Token> ACTIVE=new HashMap<>();
    private static final List<WeakReference<Observer>> OBSERVERS=new ArrayList<>();
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    public interface Observer{void changed(String accountKey,long room,long member);}
    public static synchronized void observe(Observer observer){OBSERVERS.add(new WeakReference<>(observer));}
    public static synchronized void unobserve(Observer observer){OBSERVERS.removeIf(r->r.get()==null||r.get()==observer);}
    private static String key(AccountScope a,long room,long member){return a.key+":"+room+":"+member;}
    public static synchronized boolean active(AccountScope a,long room,long member){
        Token t=ACTIVE.get(key(a,room,member));return t!=null&&t.generation==BChatStorageRepository.generation(a);
    }
    /** Must run in the same serial lane as recover/admit and permission purges. */
    public static Token begin(BChatV2Outbox box,BChatConnectedMediaStore store,AccountScope a,long room,long member)throws IOException{
        Recovery before=recover(box,store,a,room,member);
        if(before.dispatchBlocked)throw new IOException("Existing media requires reconciliation");
        synchronized(BChatStageAdmission.class){
            if(active(a,room,member))throw new IOException("Media stage admission already owned");
            Token token=new Token(a,room,member);ACTIVE.put(token.key,token);return token;
        }
    }
    public static final class Token implements AutoCloseable{
        private final AccountScope account;private final String key,owner=UUID.randomUUID().toString();
        public final long roomId,membershipId,generation;
        private Token(AccountScope a,long room,long member){account=a;key=key(a,room,member);roomId=room;membershipId=member;
            generation=BChatStorageRepository.generation(a);}
        public boolean owns(){synchronized(BChatStageAdmission.class){Token current=ACTIVE.get(key);
            return current==this&&current.owner.equals(owner)&&generation==BChatStorageRepository.generation(account);}}
        /** Worker finally, not an Activity callback. Old owners cannot release a replacement. */
        @Override public void close(){
            synchronized(BChatStageAdmission.class){if(ACTIVE.get(key)!=this)return;ACTIVE.remove(key);}
            MAIN.post(()->{List<Observer> listeners=new ArrayList<>();synchronized(BChatStageAdmission.class){
                OBSERVERS.removeIf(ref->ref.get()==null);for(WeakReference<Observer> ref:OBSERVERS){Observer o=ref.get();if(o!=null)listeners.add(o);}}
                for(Observer o:listeners)o.changed(account.key,roomId,membershipId);
            });
        }
    }
    public static final class Issue{
        public final String uploadUuid,code;
        private Issue(String uuid,String code){uploadUuid=uuid;this.code=code;}
    }
    public static final class Recovery{
        public final List<BChatConnectedMediaStore.Entry> media;
        public final List<Issue> issues;
        public final boolean staging,dispatchBlocked;
        private Recovery(List<BChatConnectedMediaStore.Entry> media,List<Issue> issues,boolean staging,boolean blocked){
            this.media=Collections.unmodifiableList(media);this.issues=Collections.unmodifiableList(issues);this.staging=staging;dispatchBlocked=blocked;
        }
    }
    /** Receipt cleanup precedes orphan admission: a full count cannot block its own drain.
     * One failed cleanup/import produces a bounded UUID/code diagnostic, never hides the room. */
    public static Recovery recover(BChatV2Outbox box,BChatConnectedMediaStore store,AccountScope a,long room,long member)throws IOException{
        List<Issue> issues=new ArrayList<>();
        for(BChatSendTickets.Ticket ticket:box.tickets().forAccount(a)){
            if(!"media".equals(ticket.kind)||!"receipt".equals(ticket.state))continue;
            try{box.tickets().retireMedia(a,ticket,()->store.retireReceipted(a,ticket.uploadUuid,ticket.fingerprint));}
            catch(Exception error){issues.add(new Issue(ticket.uploadUuid,"receipt_cleanup_failed"));}
        }
        boolean staging=active(a,room,member),blocked=staging;
        List<BChatConnectedMediaStore.Entry> media=new ArrayList<>(store.pendingForRoom(a,room,member));
        if(!staging)for(BChatConnectedMediaStore.Entry e:media){
            try{if(box.tickets().find(a,"media",e.clientUuid)==null)box.tickets().admitMedia(a,e,true);}
            catch(Exception error){issues.add(new Issue(e.uploadUuid,"orphan_admission_failed"));blocked=true;}
        }
        Map<String,Long> sequence=new HashMap<>();
        for(BChatSendTickets.Ticket ticket:box.tickets().forAccount(a))if("media".equals(ticket.kind))
            sequence.put(ticket.uuid,ticket.legacy?ticket.sequence-Long.MAX_VALUE/2:ticket.sequence);
        media.sort((x,y)->Long.compare(sequence.getOrDefault(x.clientUuid,Long.MAX_VALUE),sequence.getOrDefault(y.clientUuid,Long.MAX_VALUE)));
        return new Recovery(media,issues,staging,blocked);
    }
    private BChatStageAdmission(){}
}

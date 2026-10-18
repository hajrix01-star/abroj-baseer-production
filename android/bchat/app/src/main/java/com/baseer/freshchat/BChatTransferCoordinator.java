package com.baseer.freshchat;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PersistableBundle;
import com.baseer.freshchat.sync.*;
import org.json.JSONObject;
import java.io.File;
import java.lang.ref.WeakReference;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.BooleanSupplier;

/** Process-owned native byte transport. No Activity, cookies or capability is persisted.
 * Link creation remains on the freshly authenticated foreground control plane. */
final class BChatTransferCoordinator {
    static final String ACTION_STOP="com.baseer.freshchat.STOP_TRANSFER", EXTRA_ID="transfer_id";
    private static final String CHANNEL="bchat-transfers-v1";
    private static BChatTransferCoordinator singleton;
    static synchronized BChatTransferCoordinator get(Context context) {
        if(singleton==null)singleton=new BChatTransferCoordinator(context.getApplicationContext());
        return singleton;
    }
    interface Observer { void changed(String accountKey,long roomId,long memberId); }
    interface Finished { void finished(); }
    private final Context app;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final ExecutorService network=Executors.newSingleThreadExecutor(r->new Thread(r,"bchat-transfer-http"));
    private final Map<Integer,Work> work=new HashMap<>();
    private final Map<String,Long> generations=new HashMap<>();
    private final Map<String,Set<String>> permitted=new HashMap<>();
    private final List<WeakReference<Observer>> observers=new ArrayList<>();
    private int nextId=74000;
    private BChatTransferCoordinator(Context app){this.app=app;}
    synchronized void observe(Observer observer){observers.add(new WeakReference<>(observer));}
    synchronized void unobserve(Observer observer){observers.removeIf(r->r.get()==null||r.get()==observer);}
    private static String room(long id,long member,long company){return id+":"+member+":"+company;}
    /** Fresh server authorization only. Room navigation does not alter this authority. */
    void authorize(AccountScope scope,Set<String> rooms){
        List<Integer> removed=new ArrayList<>();
        synchronized(this){
            for(String key:new ArrayList<>(permitted.keySet()))if(!key.equals(scope.key)){
                permitted.remove(key);generations.put(key,generations.getOrDefault(key,0L)+1);
            }
            permitted.put(scope.key,new HashSet<>(rooms));
            for(Work w:work.values())if(!allowed(w))removed.add(w.id);}
        for(int id:removed)stop(id);
    }
    static String roomKey(long id,long member,long company){return room(id,member,company);}
    void revoke(AccountScope scope){
        if(scope==null)return;List<Integer> ids=new ArrayList<>();
        synchronized(this){generations.put(scope.key,generation(scope)+1);permitted.remove(scope.key);
            for(Work w:work.values())if(w.scope.key.equals(scope.key))ids.add(w.id);}
        for(int id:ids)stop(id);
    }
    private long generation(AccountScope a){Long n=generations.get(a.key);return n==null?0:n;}
    private boolean allowed(Work w){Set<String> rooms=permitted.get(w.scope.key);
        return generation(w.scope)==w.generation&&rooms!=null&&rooms.contains(room(w.ticket.roomId,w.ticket.membershipId,w.ticket.companyId));}
    private synchronized boolean active(Work w){return work.get(w.id)==w&&allowed(w)&&!w.stopped;}

    /** Called on main AFTER durable claim. Eligibility is checked immediately before OS scheduling.
     * A denied UIDT must NOT fall through to an FGS on Android34+. */
    boolean schedule(AccountScope scope,BChatSendTickets.Ticket ticket,BChatConnectedMediaStore.Entry entry,
                     File source,String grant,String secret,BooleanSupplier visibleUserEligible){
        if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("Schedule on main");
        if(scope==null||ticket==null||entry==null||!scope.key.equals(entry.accountKey)
                ||!"media".equals(ticket.kind)||!"sending".equals(ticket.state)||!ticket.matches(entry))return false;
        Work w;
        synchronized(this){
            w=new Work(++nextId,scope,ticket,entry,source,grant,secret,generation(scope));
            if(!allowed(w)||!work.isEmpty()||!visibleUserEligible.getAsBoolean())return false;
            for(Work existing:work.values())if(existing.scope.key.equals(scope.key)&&existing.ticket.sequence==ticket.sequence)return false;
            work.put(w.id,w);
        }
        boolean scheduled=false;
        try{
            if(!visibleUserEligible.getAsBoolean()||!active(w))return false;
            if(Build.VERSION.SDK_INT>=34){
                PersistableBundle extras=new PersistableBundle();extras.putInt(EXTRA_ID,w.id); // no authority/secret/file URI.
                NetworkRequest request=new NetworkRequest.Builder()
                        .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN).build();
                JobInfo job=new JobInfo.Builder(w.id,new ComponentName(app,BChatTransferJobService.class))
                        .setUserInitiated(true).setRequiredNetwork(request).setEstimatedNetworkBytes(8192,entry.size)
                        .setExtras(extras).build();
                JobScheduler scheduler=app.getSystemService(JobScheduler.class);
                scheduled=scheduler!=null&&scheduler.schedule(job)==JobScheduler.RESULT_SUCCESS;
            }else{
                Intent intent=new Intent(app,BChatTransferService.class).putExtra(EXTRA_ID,w.id);
                app.startForegroundService(intent);scheduled=true;
            }
            return scheduled;
        }catch(RuntimeException denied){return false;}
        finally{if(!scheduled){synchronized(this){work.remove(w.id);}defer(w);}}
    }
    synchronized boolean contains(int id){Work w=work.get(id);return w!=null&&allowed(w)&&!w.stopped;}
    synchronized boolean isBusy(){return !work.isEmpty();}
    void start(int id,Finished done){
        Work w;
        synchronized(this){w=work.get(id);if(w==null||!allowed(w)||w.stopped||w.started){main.post(done::finished);return;}
            w.started=true;w.done=done;}
        network.execute(()->run(w));
    }
    private void run(Work w){
        BChatV2Outbox box=new BChatV2Outbox(app);BChatConnectedMediaStore store=new BChatConnectedMediaStore(app);
        try{
            if(!active(w)||!box.tickets().sending(w.scope,w.ticket)){box.close();finish(w);return;}
            BChatNativeMediaUploader.Result response=BChatNativeMediaUploader.upload(w.call,w.scope.origin,w.scope.database,
                    w.grant,w.secret,w.source,w.entry.size,w.entry.mime);
            for(int attempt=0;active(w)&&(response.status==202||response.isTransportFailure())&&attempt<3;attempt++)
                response=BChatNativeMediaUploader.status(w.call,w.scope.origin,w.scope.database,w.grant,w.secret);
            if(!active(w))return;
            try{
                JSONObject result=new JSONObject(response.body);
                Object api=result.get("api_version"),raw=result.get("media_id");
                if(response.status!=200||!(api instanceof Number)||((Number)api).doubleValue()!=2
                        ||!(raw instanceof Number)||((Number)raw).longValue()<=0
                        ||((Number)raw).doubleValue()!=((Number)raw).longValue()
                        ||!w.entry.networkUploadUuid().equals(result.getString("upload_uuid"))
                        ||!("staged".equals(result.getString("state"))||"attached".equals(result.getString("state"))))
                    throw new IllegalArgumentException("Unconfirmed native upload");
                long media=((Number)raw).longValue();OutboxPolicy.requireRecordId(media);
                // Ordered with policy purges; claim validation encloses file mutation, not HTTP.
                BChatStorageRepository.submit(null,()->{
                    if(!active(w))return false;
                    return box.tickets().saveUploaded(w.scope,w.ticket,media,()->store.markUploaded(w.scope,w.entry,media));
                },(saved,error)->{finish(w);box.close();});
                return;
            }catch(Exception unconfirmed){
                final boolean permanent=response.status==400||response.status==409||response.status==413||response.status==415;
                BChatStorageRepository.submit(null,()->box.tickets().failed(w.scope,w.ticket,permanent,System.currentTimeMillis()),
                        (saved,error)->{finish(w);box.close();});return;
            }
        }catch(RuntimeException unexpected){
            BChatStorageRepository.submit(null,()->box.tickets().failed(w.scope,w.ticket,false,System.currentTimeMillis()),
                    (saved,error)->{finish(w);box.close();});
        }finally{if(!active(w)){box.close();finish(w);}}
    }
    private void defer(Work w){BChatStorageRepository.submit(null,()->{
        try(BChatV2Outbox b=new BChatV2Outbox(app)){return b.tickets().defer(w.scope,w.ticket);}
    },(ignored,error)->notifyObservers(w));}
    void stop(int id){
        Work w;synchronized(this){w=work.get(id);if(w==null||w.stopped)return;w.stopped=true;}
        w.call.cancel();
        BChatStorageRepository.submit(null,()->{
            try(BChatV2Outbox box=new BChatV2Outbox(app)){
                return box.tickets().cancel(w.scope,w.ticket,w.started,System.currentTimeMillis());
            }
        },(ignored,error)->finish(w));
        if(Build.VERSION.SDK_INT>=34){JobScheduler jobs=app.getSystemService(JobScheduler.class);if(jobs!=null)jobs.cancel(id);}
    }
    private void finish(Work w){Finished done;
        synchronized(this){if(work.get(w.id)!=w)return;work.remove(w.id);done=w.done;}
        main.post(()->{if(done!=null)done.finished();notifyObservers(w);});
    }
    private void notifyObservers(Work w){
        List<Observer> listeners=new ArrayList<>();synchronized(this){observers.removeIf(ref->ref.get()==null);
            for(WeakReference<Observer> ref:observers){Observer o=ref.get();if(o!=null)listeners.add(o);}}
        for(Observer o:listeners)o.changed(w.scope.key,w.ticket.roomId,w.ticket.membershipId);
    }
    Notification notification(int id){
        NotificationManager manager=app.getSystemService(NotificationManager.class);
        if(manager!=null)manager.createNotificationChannel(new NotificationChannel(CHANNEL,
                app.getString(R.string.bchat_transfer_channel_title),NotificationManager.IMPORTANCE_LOW));
        Intent stop=new Intent(app,BChatTransferService.class).setAction(ACTION_STOP).putExtra(EXTRA_ID,id);
        PendingIntent action=PendingIntent.getService(app,id,stop,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(app,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_upload)
                .setContentTitle(app.getString(R.string.bchat_transfer_channel_title))
                .setContentText(app.getString(R.string.bchat_transfer_running)).setOngoing(true)
                .setProgress(0,0,true).addAction(new Notification.Action.Builder(android.R.drawable.ic_media_pause,
                        app.getString(R.string.bchat_transfer_cancel),action).build()).build();
    }
    private static final class Work{
        final int id;final AccountScope scope;final BChatSendTickets.Ticket ticket;final BChatConnectedMediaStore.Entry entry;
        final File source;final String grant,secret;final long generation;final BChatNativeMediaUploader.Call call=new BChatNativeMediaUploader.Call();
        volatile boolean started,stopped;Finished done;
        Work(int id,AccountScope scope,BChatSendTickets.Ticket ticket,BChatConnectedMediaStore.Entry entry,File source,String grant,String secret,long generation){
            this.id=id;this.scope=scope;this.ticket=ticket;this.entry=entry;this.source=source;this.grant=grant;this.secret=secret;this.generation=generation;}
    }
}

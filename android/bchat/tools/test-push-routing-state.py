#!/usr/bin/env python3
"""Execute production PushState with explicit preferences/handler/executor/notification adapters.

This exercises account, preview and durable-snapshot interleavings, not Android storage/OEM FCM.
The preference adapter deliberately changes memory even when commit returns false.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
files = {
    "org/json/JSONObject.java": r"""
package org.json;
import java.util.HashMap;
import java.util.Map;
public class JSONObject {
 public static final Object NULL=new Object();
 private final Map<String,Object> values=new HashMap<>();
 public Object opt(String key){return values.get(key);}
 public boolean has(String key){return values.containsKey(key);}
 public JSONObject optJSONObject(String key){Object v=opt(key);return v instanceof JSONObject?(JSONObject)v:null;}
 public JSONObject getJSONObject(String key){JSONObject v=optJSONObject(key);if(v==null)throw new IllegalArgumentException();return v;}
 public JSONObject put(String key,Object value){if(value==null)values.remove(key);else values.put(key,value);return this;}
}
""",
    "android/content/Context.java": r"""
package android.content;
public abstract class Context {
 public static final int MODE_PRIVATE=0;
 public Context getApplicationContext(){return this;}
 public abstract SharedPreferences getSharedPreferences(String name,int mode);
 public abstract <T> T getSystemService(Class<T> type);
}
""",
    "android/content/SharedPreferences.java": r"""
package android.content;
public interface SharedPreferences {
 String getString(String key,String fallback); long getLong(String key,long fallback); Editor edit();
 interface OnSharedPreferenceChangeListener {void onSharedPreferenceChanged(SharedPreferences p,String key);}
 interface Editor {Editor putString(String k,String v);Editor putLong(String k,long v);Editor remove(String k);boolean commit();}
}
""",
    "android/app/NotificationManager.java": r"""
package android.app;
public class NotificationManager {
 public volatile boolean visible;
 public int cancellations;
 public void cancelAll(){visible=false;cancellations++;}
}
""",
    "android/os/Looper.java": r"""
package android.os;
public class Looper {
 private static final Thread thread=Thread.currentThread();
 private static final Looper main=new Looper();
 public static Looper getMainLooper(){return main;}
 public static Looper myLooper(){return Thread.currentThread()==thread?main:null;}
}
""",
    "android/os/Handler.java": r"""
package android.os;
import java.util.concurrent.ConcurrentLinkedQueue;
public class Handler {
 private static final ConcurrentLinkedQueue<Runnable> tasks=new ConcurrentLinkedQueue<>();
 public Handler(Looper ignored){}
 public boolean post(Runnable r){tasks.add(r);return true;}
 public static void drain(){Runnable r;while((r=tasks.poll())!=null)r.run();}
}
""",
    "com/baseer/freshchat/sync/BChatStorageRepository.java": r"""
package com.baseer.freshchat.sync;
import java.util.concurrent.*;
public class BChatStorageRepository {
 private static final ConcurrentLinkedQueue<Runnable> tasks=new ConcurrentLinkedQueue<>();
 public static Executor executor(){return tasks::add;}
 public static void drain()throws Exception {
   run(false);
 }
 public static void one()throws Exception {run(true);}
 private static void run(boolean one)throws Exception {
   Throwable[] failure={null};
   Thread worker=new Thread(()->{try{Runnable r;while((r=tasks.poll())!=null){r.run();if(one)break;}}catch(Throwable t){failure[0]=t;}},"bchat-test-io");
   worker.start();worker.join(5000);
   if(worker.isAlive())throw new AssertionError("test disk lane did not finish");
   if(failure[0]!=null)throw new AssertionError(failure[0]);
 }
}
""",
    "com/baseer/freshchat/PushRoutingHarness.java": r"""
package com.baseer.freshchat;
import android.app.NotificationManager;
import android.content.*;
import android.os.Handler;
import com.baseer.freshchat.sync.*;
import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
public class PushRoutingHarness extends Context {
 static int checks;
 static final String ACCOUNT="00000000-0000-4000-8000-000000000001";
 static final String TOKEN=String.join("",Collections.nCopies(40,"T"));
 final Prefs prefs=new Prefs();final NotificationManager notifications=new NotificationManager();
 public SharedPreferences getSharedPreferences(String name,int mode){
   check(Thread.currentThread().getName().equals("bchat-test-io"),"preferences initialized off UI");return prefs;
 }
 @SuppressWarnings("unchecked") public <T>T getSystemService(Class<T> type){return (T)notifications;}
 static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);checks++;}
 static void flush()throws Exception{BChatStorageRepository.drain();Handler.drain();}
 static void restart(PushRoutingHarness app)throws Exception {
   flush();Field field=BChatPushState.class.getDeclaredField("state");field.setAccessible(true);field.set(null,null);
   app.prefs.memory=new HashMap<>(app.prefs.disk);BChatPushState.ready(app);flush();
 }
 static void register(PushRoutingHarness app,AccountScope scope)throws Exception {
   BChatPushState.verifiedAccount(app,scope);flush();
   BChatPushState.Registration request=BChatPushState.registration(app,scope);
   check(request!=null,"registration ticket after durable installation");
   boolean[] accepted={false};
   BChatPushState.registeredAsync(app,request,ACCOUNT,(ok,durable)->accepted[0]=ok&&durable);
   check(!BChatPushState.matches(app,ACCOUNT),"pending registration is not durable routing");
   flush();check(accepted[0]&&BChatPushState.matches(app,ACCOUNT),"registration committed and routed");
 }
 public static void main(String[] args)throws Exception {
   PushRoutingHarness app=new PushRoutingHarness();
   AccountScope scope=new AccountScope("https://example.invalid","bchat_fixture",1);
   BChatPushState.token(app,TOKEN);BChatPushState.verifiedAccount(app,scope);
   check(BChatPushState.installationId(app)==null,"new installation cannot dispatch before its commit");
   flush();register(app,scope);
   BChatPushState.Delivery oldDelivery=BChatPushState.delivery(app,ACCOUNT);
   BChatPushState.clearAccount(app);
   check(!BChatPushState.present(oldDelivery,mode->app.notifications.visible=true)&&!app.notifications.visible,
       "logout between initial match and final gate blocks notification");
   flush();restart(app);
   check(!BChatPushState.matches(app,ACCOUNT),"committed logout remains revoked after process recreation");
   register(app,scope);
   BChatPushState.Registration oldRegistration=BChatPushState.registration(app,scope);
   BChatPushState.clearAccount(app);BChatPushState.verifiedAccount(app,scope);
   boolean[] resurrected={true};
   BChatPushState.registeredAsync(app,oldRegistration,ACCOUNT,(ok,durable)->resurrected[0]=ok);
   flush();check(!resurrected[0]&&!BChatPushState.matches(app,ACCOUNT),"old response cannot revive route even after same-account login");
   register(app,scope);
   BChatPushState.PreviewRequest first=BChatPushState.previewRequest(app,ACCOUNT);
   BChatPushState.acceptPreviewMode(app,first,"full",1,(ok,durable)->check(ok&&durable,"fresh authenticated preview committed"));
   flush();check(BChatPushState.previewMode(app,ACCOUNT).equals("full"),"explicit current full enabled");
   BChatPushState.Delivery beforeRecheck=BChatPushState.delivery(app,ACCOUNT);
   BChatPushState.verifiedAccount(app,scope);
   check(BChatPushState.present(beforeRecheck,mode->check(mode.equals("full"),"same-account recheck keeps preview")),
       "same-account bridge recheck preserves existing delivery generation");
   BChatPushState.PreviewRequest oldGet=BChatPushState.previewRequest(app,ACCOUNT);
   BChatPushState.beginPreviewChange(app,ACCOUNT,"none",(ticket,durable)->check(ticket!=null&&durable,"none intent durably saved"));
   check(BChatPushState.previewMode(app,ACCOUNT).equals("none"),"none applies before disk or HTTP finishes");
   BChatPushState.acceptPreviewMode(app,oldGet,"full",1,(ok,durable)->check(!ok,"old GET full rejected after local none intent"));
   flush();
   BChatPushState.Delivery current=BChatPushState.delivery(app,ACCOUNT);
   check(BChatPushState.present(current,mode->check(mode.equals("none"),"gate reads latest privacy ceiling")),"current gate accepted");
   restart(app);check(BChatPushState.previewMode(app,ACCOUNT).equals("none"),"cold start never restores cached full opt-in");
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"full",2,
       (ok,durable)->check(!ok,"durable pending none rejects server full after restart until confirmed"));
   flush();
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"none",2,(ok,durable)->{});flush();
   register(app,scope);
   first=BChatPushState.previewRequest(app,ACCOUNT);
   BChatPushState.acceptPreviewMode(app,first,"full",3,(ok,durable)->{});flush();
   app.prefs.fail=true;
   BChatPushState.beginPreviewChange(app,ACCOUNT,"none",(ticket,durable)->check(ticket==null&&!durable,"commit false is not durable intent"));
   flush();check(BChatPushState.previewMode(app,ACCOUNT).equals("none"),"failed write never restores broader RAM preview");
   check(app.prefs.disk.get("preview-mode").equals("full")&&app.prefs.memory.get("preview-mode").equals("none"),
       "adapter reproduces commit=false with changed memory and unchanged disk");
   app.prefs.fail=false;restart(app);
   check(BChatPushState.previewMode(app,ACCOUNT).equals("none"),"process reload of old full disk remains none until fresh server response");
   register(app,scope);
   BChatPushState.Registration previousGeneration=BChatPushState.registration(app,scope);
   BChatPushState.registeredAsync(app,previousGeneration,ACCOUNT,(ok,durable)->{});
   BChatPushState.clearAccount(app);BChatPushState.verifiedAccount(app,scope);
   BChatPushState.Registration newGeneration=BChatPushState.registration(app,scope);
   BChatPushState.registeredAsync(app,newGeneration,ACCOUNT,(ok,durable)->{});
   BChatStorageRepository.one();
   check(!BChatPushState.matches(app,ACCOUNT),"old snapshot commit cannot durably enable a new same-account generation");
   flush();check(BChatPushState.matches(app,ACCOUNT),"new generation enables only after its own committed snapshot");
   BChatPushState.clearToken(app);
   check(!BChatPushState.matches(app,ACCOUNT),"clearToken revokes account route immediately");
   flush();restart(app);
   check(!BChatPushState.matches(app,ACCOUNT)&&BChatPushState.pendingToken(app)==null,"clearToken persists all registration invalidation");
   BChatPushState.token(app,TOKEN);flush();register(app,scope);
   BChatPushState.Registration delayedOld=BChatPushState.registration(app,scope);
   BChatPushState.Registration delayedNew=BChatPushState.registration(app,scope);
   BChatPushState.PreviewRequest[] pendingNone={null};
   BChatPushState.beginPreviewChange(app,ACCOUNT,"none",(ticket,durable)->pendingNone[0]=ticket);
   BChatPushState.registeredAsync(app,delayedOld,ACCOUNT,(ok,durable)->check(!ok,"older registration request response rejected"));
   BChatPushState.registeredAsync(app,delayedNew,ACCOUNT,(ok,durable)->check(ok,"latest same-binding registration accepted"));
   flush();
   check(pendingNone[0]!=null&&BChatPushState.currentPreviewRequest(pendingNone[0]),"same-binding registration preserves newer none intent/ticket");
   BChatPushState.token(app,String.join("",Collections.nCopies(40,"N")));flush();register(app,scope);
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"full",6,
       (ok,durable)->check(!ok,"token rotation/re-registration preserves pending none before its HTTP POST"));flush();
   restart(app);
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"full",6,
       (ok,durable)->check(!ok,"pending none survives token rotation and process recreation"));flush();
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"none",6,(ok,durable)->{});flush();
   BChatPushState.PreviewRequest[] oldMainTicket={null};
   BChatPushState.beginPreviewChange(app,ACCOUNT,"none",(ticket,durable)->oldMainTicket[0]=ticket);
   BChatStorageRepository.drain();
   BChatPushState.beginPreviewChange(app,ACCOUNT,"sender",(ticket,durable)->{});
   Handler.drain();check(oldMainTicket[0]==null,"intent changed after disk completion invalidates queued MAIN callback");
   flush();
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"sender",7,
       (ok,durable)->check(ok&&durable,"new sender intent acknowledged before delayed-callback test"));flush();
   boolean[] staleAccepted={true};
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"sender",8,(ok,durable)->staleAccepted[0]=ok);
   BChatStorageRepository.drain();BChatPushState.clearAccount(app);Handler.drain();
   check(!staleAccepted[0],"logout after disk completion invalidates queued acceptance callback");
   flush();register(app,scope);
   String oldInstallation=BChatPushState.installationId(app);
   app.prefs.disk.remove("installation-id");restart(app);
   check(!BChatPushState.matches(app,ACCOUNT)&&BChatPushState.needsRegistration(app,scope),"missing installation cannot restore old server route");
   check(!oldInstallation.equals(BChatPushState.installationId(app)),"new installation persisted before fresh registration");
   register(app,scope);
   BChatPushState.Delivery concurrent=BChatPushState.delivery(app,ACCOUNT);
   CountDownLatch attempted=new CountDownLatch(1);Thread[] logout={null};
   BChatPushState.present(concurrent,mode->{
     logout[0]=new Thread(()->{attempted.countDown();BChatPushState.clearAccount(app);});logout[0].start();
     try{check(attempted.await(1,TimeUnit.SECONDS),"concurrent logout started");}catch(InterruptedException e){throw new AssertionError(e);}
     app.notifications.visible=true;
   });
   logout[0].join(2000);
   check(!logout[0].isAlive()&&!app.notifications.visible,"notify gate precedes serialized logout cancellation");
   flush();
   register(app,scope);
   BChatPushState.beginPreviewChange(app,ACCOUNT,"none",(ticket,durable)->{});flush();
   AccountScope another=new AccountScope("https://example.invalid","bchat_fixture",2);
   BChatPushState.verifiedAccount(app,another);flush();
   String anotherKey="00000000-0000-4000-8000-000000000002";
   BChatPushState.registeredAsync(app,BChatPushState.registration(app,another),anotherKey,(ok,durable)->{});flush();
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,anotherKey),"full",10,
       (ok,durable)->check(ok&&durable,"different verified account does not inherit previous pending privacy intent"));flush();
   check(BChatPushState.previewMode(app,ACCOUNT).equals("none")&&BChatPushState.previewMode(app,anotherKey).equals("full"),
       "privacy opt-in and pending intent remain account scoped");
   BChatPushState.clearAccount(app);flush();register(app,scope);
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"full",20,(ok,durable)->{});flush();
   BChatPushState.PreviewRequest serverGet=BChatPushState.previewRequest(app,ACCOUNT);
   BChatPushState.PreviewControl[] choice={null};
   BChatPushState.beginPreviewControl(app,serverGet,"none",20,(ticket,durable)->choice[0]=ticket);
   check(choice[0]==null&&BChatPushState.previewMode(app,ACCOUNT).equals("none"),
       "control restriction immediate; HTTP ticket waits for its commit");
   BChatPushState.PreviewControl metadata=BChatPushState.pendingPreviewControl(app,ACCOUNT);
   check(metadata!=null&&!BChatPushState.currentPreviewControl(metadata),"panel metadata is never a dispatch ticket");
   flush();check(choice[0]!=null&&BChatPushState.currentPreviewControl(choice[0]),"own exact control snapshot unlocks ticket");
   NotificationSettingsProtocolTest.run(scope,ACCOUNT,choice[0].installationId,choice[0]);
   String exactUuid=choice[0].clientUuid,exactInstallation=choice[0].installationId;
   check(choice[0].expectedRevision==20&&choice[0].mode.equals("none")&&choice[0].accountKey.equals(ACCOUNT),
       "control payload includes expected revision/mode/account");
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"full",21,
       (ticket,durable)->check(ticket==null&&!durable,"unknown operation cannot be replaced under a new UUID"));
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"none",21,
       (ok,durable)->check(!ok,"even matching GET cannot clear the pending operation"));flush();
   BChatPushState.PreviewControl beforeRestart=choice[0];restart(app);
   metadata=BChatPushState.pendingPreviewControl(app,ACCOUNT);
   check(metadata!=null&&metadata.clientUuid.equals(exactUuid)&&metadata.expectedRevision==20
       &&metadata.mode.equals("none")&&metadata.installationId.equals(exactInstallation),
       "process recreation retains exact UUID/revision/install/mode");
   check(!BChatPushState.currentPreviewControl(beforeRestart),"old process ticket is invalid");
   BChatPushState.PreviewControl[] retried={null};
   BChatPushState.retryPreviewControl(app,ACCOUNT,(ticket,durable)->retried[0]=ticket);
   check(retried[0]==null,"restart retry also proves its own durable write");flush();
   check(retried[0]!=null&&retried[0].clientUuid.equals(exactUuid)&&retried[0].expectedRevision==20,
       "unknown retry reuses exact payload rather than fresh GET revision");
   BChatPushState.acceptPreviewControl(app,retried[0],"none",21,22,
       (ok,durable)->check(!ok,"wrong operation revision rejected"));flush();
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)!=null,"bad response cannot clear operation");
   app.prefs.fail=true;
   BChatPushState.retryPreviewControl(app,ACCOUNT,
       (ticket,durable)->check(ticket==null&&!durable,"failed retry commit cannot issue ticket"));
   flush();check(!BChatPushState.currentPreviewControl(retried[0]),"failed snapshot cannot reuse previous send authority");
   check(app.prefs.disk.get("preview-control-uuid").equals(exactUuid),"failed retry leaves durable operation intact");
   app.prefs.fail=false;restart(app);register(app,scope);
   BChatPushState.retryPreviewControl(app,ACCOUNT,(ticket,durable)->retried[0]=ticket);flush();
   check(retried[0]!=null&&retried[0].clientUuid.equals(exactUuid),"retry remains exact after failed commit and restart");
   boolean[] oldSettle={true};
   BChatPushState.acceptPreviewControl(app,retried[0],"none",21,21,(ok,durable)->oldSettle[0]=ok);
   BChatPushState.PreviewControl acceptedOld=retried[0];
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"full",21,(ticket,durable)->choice[0]=ticket);
   flush();check(!oldSettle[0]&&choice[0]!=null&&!choice[0].clientUuid.equals(exactUuid),
       "queued old settle completion cannot report or clear newer explicit choice");
   String nextUuid=choice[0].clientUuid;
   BChatPushState.acceptPreviewControl(app,acceptedOld,"none",21,21,
       (ok,durable)->check(!ok,"old ACK cannot settle a newer UUID"));flush();
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT).clientUuid.equals(nextUuid),
       "new pending choice remains intact after old ACK");
   BChatPushState.acceptPreviewControl(app,choice[0],"full",22,22,
       (ok,durable)->check(ok&&durable,"matching control ACK commits expansion"));flush();
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)==null&&BChatPushState.previewMode(app,ACCOUNT).equals("full"),
       "matching acknowledged operation clears and enables full");
   BChatPushState.PreviewRequest staleConflictGet=BChatPushState.previewRequest(app,ACCOUNT);
   BChatPushState.beginPreviewControl(app,staleConflictGet,"none",22,(ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.rejectPreviewControl(app,choice[0],
       (ok,durable)->check(ok&&durable,"definitive conflict releases exact operation"));flush();
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)==null&&BChatPushState.previewMode(app,ACCOUNT).equals("none"),
       "conflict keeps local restriction rather than server expansion");
   BChatPushState.beginPreviewControl(app,staleConflictGet,"sender",23,
       (ticket,durable)->check(ticket==null,"pre-conflict GET cannot authorize replacement"));flush();
   BChatPushState.PreviewRequest freshConflictGet=BChatPushState.previewRequest(app,ACCOUNT);
   BChatPushState.acceptPreviewMode(app,freshConflictGet,"full",23,
       (ok,durable)->check(!ok,"fresh GET cannot raise the retained restriction"));flush();
   BChatPushState.beginPreviewControl(app,freshConflictGet,"sender",23,(ticket,durable)->choice[0]=ticket);flush();
   check(choice[0]!=null&&choice[0].expectedRevision==23&&!choice[0].clientUuid.equals(nextUuid),
       "fresh explicit post-conflict choice gets a new UUID and revision");
   BChatPushState.PreviewControl beforeTokenChange=choice[0];
   BChatPushState.clearToken(app);flush();restart(app);
   check(!BChatPushState.matches(app,ACCOUNT),"process death between token removal and registration has no active route");
   BChatPushState.token(app,TOKEN);flush();register(app,scope);
   check(!BChatPushState.currentPreviewControl(beforeTokenChange),"token rotation invalidates prior dispatch ticket");
   BChatPushState.retryPreviewControl(app,ACCOUNT,(ticket,durable)->choice[0]=ticket);flush();
   check(choice[0]!=null&&choice[0].clientUuid.equals(beforeTokenChange.clientUuid),
       "same installation retains payload when process dies before token re-registration");
   BChatPushState.PreviewControl beforeColdVerify=choice[0];flush();
   Field stateField=BChatPushState.class.getDeclaredField("state");stateField.setAccessible(true);stateField.set(null,null);
   app.prefs.memory=new HashMap<>(app.prefs.disk);
   BChatPushState.verifiedAccount(app,scope); // Queues load but touches the verified scope before it runs.
   flush();register(app,scope);
   BChatPushState.retryPreviewControl(app,ACCOUNT,(ticket,durable)->choice[0]=ticket);flush();
   check(choice[0]!=null&&choice[0].clientUuid.equals(beforeColdVerify.clientUuid),
       "same-scope verification before cold load does not erase unknown operation");
   BChatPushState.clearAccount(app);flush();register(app,another);
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)==null&&!BChatPushState.currentPreviewControl(choice[0]),
       "different verified account cannot inherit pending control or old ACK");
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"none",30,
       (ticket,durable)->choice[0]=ticket);flush();
   check(choice[0]!=null,"installation change fixture has durable operation");
   app.prefs.disk.remove("installation-id");restart(app);register(app,another);
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)==null,"new installation cannot send old installation control");
   app.prefs.fail=true;
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"sender",31,
       (ticket,durable)->check(ticket==null&&!durable,"memory-only new operation is not sendable"));flush();
   check(app.prefs.memory.containsKey("preview-control-uuid")&&!app.prefs.disk.containsKey("preview-control-uuid"),
       "adapter retains changed memory but not failed new-operation disk state");
   app.prefs.fail=false;restart(app);
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)==null,"cold reload never invents failed operation");
   register(app,another);
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"full",32,
       (ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.rejectPreviewControl(app,choice[0],(ok,durable)->check(ok&&durable,"expansion conflict settled"));flush();
   check(BChatPushState.previewMode(app,ACCOUNT).equals("none"),"rejected expansion never raises current ceiling");
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"full",33,
       (ok,durable)->check(!ok,"post-conflict GET cannot resurrect rejected expansion"));flush();
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"sender",33,
       (ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.PreviewControl previousAccountBinding=choice[0];
   BChatPushState.clearToken(app);flush();restart(app);BChatPushState.token(app,TOKEN);flush();
   BChatPushState.registeredAsync(app,BChatPushState.registration(app,another),anotherKey,
       (ok,durable)->check(ok&&durable,"fresh registration may change server account binding"));flush();
   check(BChatPushState.pendingPreviewControl(app,anotherKey)==null
       &&!BChatPushState.currentPreviewControl(previousAccountBinding),
       "restored operation cannot transfer to different server account key");
   BChatPushState.clearAccount(app);flush();register(app,scope);
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"full",50,(ok,durable)->{});flush();
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"none",50,
       (ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.acceptPreviewControl(app,choice[0],"full",52,51,false,
       (ok,durable)->check(!ok,"newer revision requires a replay receipt"));flush();
   BChatPushState.acceptPreviewControl(app,choice[0],"full",52,51,true,
       (ok,durable)->check(ok&&durable,"superseded original operation is settled"));flush();
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)==null
       &&BChatPushState.previewMode(app,ACCOUNT).equals("none"),"wider current server mode never lifts local ceiling");
   BChatPushState.acceptPreviewMode(app,BChatPushState.previewRequest(app,ACCOUNT),"full",52,
       (ok,durable)->check(!ok,"GET cannot lift superseded-operation floor"));flush();
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"full",52,
       (ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.acceptPreviewControl(app,choice[0],"full",53,53,(ok,durable)->{});flush();
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"sender",53,
       (ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.acceptPreviewControl(app,choice[0],"none",55,54,true,
       (ok,durable)->check(ok&&durable,"narrower current server mode settles known original"));flush();
   check(BChatPushState.previewMode(app,ACCOUNT).equals("none"),"narrower superseding mode restricts immediately");
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"full",55,
       (ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.acceptPreviewControl(app,choice[0],"full",56,56,(ok,durable)->{});flush();
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"sender",56,
       (ticket,durable)->choice[0]=ticket);flush();
   String supersededUuid=choice[0].clientUuid;
   app.prefs.fail=true;
   BChatPushState.acceptPreviewControl(app,choice[0],"full",58,57,true,
       (ok,durable)->check(!ok&&!durable,"failed superseded settlement never reports durable save"));flush();
   app.prefs.fail=false;restart(app);
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT)!=null
       &&BChatPushState.pendingPreviewControl(app,ACCOUNT).clientUuid.equals(supersededUuid)
       &&BChatPushState.previewMode(app,ACCOUNT).equals("none"),
       "failed settle plus restart retains original UUID and conservative cold ceiling");
   BChatPushState.retryPreviewControl(app,ACCOUNT,(ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.PreviewControl supersededOld=choice[0];
   BChatPushState.acceptPreviewControl(app,choice[0],"full",58,57,true,(ok,durable)->{});flush();
   BChatPushState.beginPreviewControl(app,BChatPushState.previewRequest(app,ACCOUNT),"full",58,
       (ticket,durable)->choice[0]=ticket);flush();
   BChatPushState.acceptPreviewControl(app,supersededOld,"full",58,57,true,
       (ok,durable)->check(!ok,"superseded old ACK cannot settle newer choice"));flush();
   check(BChatPushState.pendingPreviewControl(app,ACCOUNT).clientUuid.equals(choice[0].clientUuid),
       "new UUID survives old superseded ACK");
   System.out.println("PASS "+checks+" production PushState checks; explicit preferences/handler/notification adapters, not Android FCM");
 }
 static class Prefs implements SharedPreferences {
   Map<String,Object> memory=new HashMap<>(),disk=new HashMap<>();boolean fail;
   public String getString(String key,String fallback){Object v=memory.get(key);return v==null?fallback:(String)v;}
   public long getLong(String key,long fallback){Object v=memory.get(key);return v==null?fallback:(Long)v;}
   public Editor edit(){return new Edit();}
   class Edit implements Editor {
     Map<String,Object> changes=new HashMap<>();
     public Editor putString(String k,String v){changes.put(k,v);return this;}
     public Editor putLong(String k,long v){changes.put(k,v);return this;}
     public Editor remove(String k){changes.put(k,null);return this;}
     public boolean commit(){
       check(Thread.currentThread().getName().equals("bchat-test-io"),"commit off UI");
       try{Field lock=BChatPushState.class.getDeclaredField("ROUTING");lock.setAccessible(true);
         check(!Thread.holdsLock(lock.get(null)),"no commit under routing lock");
       }catch(ReflectiveOperationException e){throw new AssertionError(e);}
       for(Map.Entry<String,Object> c:changes.entrySet())if(c.getValue()==null)memory.remove(c.getKey());else memory.put(c.getKey(),c.getValue());
       if(!fail)disk=new HashMap<>(memory);return !fail;
     }
   }
 }
}
""",
}
temporary_root = root / "artifacts/test-runtime"
temporary_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="push-routing-", dir=temporary_root) as temporary:
    target = Path(temporary)
    for name, content in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    production = root / "app/src/main/java/com/baseer/freshchat"
    sources = list(target.rglob("*.java")) + [production / "BChatPushState.java",
              production / "NotificationSettingsProtocol.java", root / "tests/NotificationSettingsProtocolTest.java",
              production / "sync/AccountScope.java", production / "sync/OutboxPolicy.java"]
    subprocess.run([shutil.which("javac") or "javac", "-encoding", "UTF-8", "-d", str(target), *map(str, sources)], check=True)
    subprocess.run([shutil.which("java") or "java", "-cp", str(target), "com.baseer.freshchat.PushRoutingHarness"], check=True)

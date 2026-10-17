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
 String getString(String key,String fallback); Editor edit();
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
   System.out.println("PASS "+checks+" production PushState checks; explicit preferences/handler/notification adapters, not Android FCM");
 }
 static class Prefs implements SharedPreferences {
   Map<String,Object> memory=new HashMap<>(),disk=new HashMap<>();boolean fail;
   public String getString(String key,String fallback){Object v=memory.get(key);return v==null?fallback:(String)v;}
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
              production / "sync/AccountScope.java", production / "sync/OutboxPolicy.java"]
    subprocess.run([shutil.which("javac") or "javac", "-encoding", "UTF-8", "-d", str(target), *map(str, sources)], check=True)
    subprocess.run([shutil.which("java") or "java", "-cp", str(target), "com.baseer.freshchat.PushRoutingHarness"], check=True)

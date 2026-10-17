package com.baseer.freshchat;

import android.app.*;
import android.content.*;
import android.os.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Real channel module; platform and preference surfaces are explicit deterministic JVM adapters. */
public final class ChannelRoutingHarness extends Context {
    private static final AtomicInteger checks=new AtomicInteger();
    final Prefs prefs=new Prefs();final NotificationManager manager=new NotificationManager();
    int preferencesReads;boolean failPreferences;
    static final BChatNotificationChannels.Names NAMES=new BChatNotificationChannels.Names("Messages","Tasks","Orders");
    public SharedPreferences getSharedPreferences(String name,int mode){platform();++preferencesReads;if(failPreferences)throw new IllegalStateException("synthetic storage unavailable");return prefs;}
    @SuppressWarnings("unchecked") public <T>T getSystemService(Class<T> type){platform();return (T)manager;}
    static void check(boolean value,String label){checks.incrementAndGet();if(!value)throw new AssertionError(label);}
    public static void platform(){
        check(Looper.myLooper()!=Looper.getMainLooper(),"platform/disk work is off main");
        try{Field field=BChatNotificationChannels.class.getDeclaredField("STATE");field.setAccessible(true);
            check(!Thread.holdsLock(field.get(null)),"no platform/disk work under STATE gate");
        }catch(ReflectiveOperationException e){throw new AssertionError(e);}
    }
    private interface Work<T>{T run()throws Exception;}
    @SuppressWarnings("unchecked") private static <T>T worker(Work<T> work)throws Exception{
        Object[] value={null};Throwable[] error={null};Thread thread=new Thread(()->{try{value[0]=work.run();}catch(Throwable e){error[0]=e;}},"channel-worker");
        thread.start();thread.join(5000);if(thread.isAlive())throw new AssertionError("Worker timed out");if(error[0]!=null)throw new AssertionError(error[0]);return (T)value[0];
    }
    private static void reset()throws Exception{
        Constructor<BChatNotificationChannels.Snapshot> ctor=BChatNotificationChannels.Snapshot.class.getDeclaredConstructor(boolean.class,boolean.class,long.class);
        ctor.setAccessible(true);Field state=BChatNotificationChannels.class.getDeclaredField("current");state.setAccessible(true);state.set(null,ctor.newInstance(false,false,0));
        Field prefs=BChatNotificationChannels.class.getDeclaredField("preferences");prefs.setAccessible(true);prefs.set(null,null);
    }
    private NotificationChannel baseline(int importance,Object sound,boolean vibration){
        NotificationChannel channel=new NotificationChannel(BChatNotificationChannels.LEGACY,"BChat",importance);
        channel.sound=sound;channel.attributes="observed-attributes";channel.vibration=vibration;
        channel.pattern=new long[]{0,60,30,60};channel.effect="observed-effect";channel.visibility=Notification.VISIBILITY_SECRET;
        channel.badge=false;channel.lights=false;channel.lightColor=0x123456;channel.registered=true;
        manager.channels.put(channel.id,channel);return channel;
    }
    private static void defaultsAndStorage()throws Exception{
        reset();ChannelRoutingHarness app=new ChannelRoutingHarness();
        BChatNotificationChannels.Selection cold=BChatNotificationChannels.resolve("chat");
        check(!cold.known&&cold.channelId.equals(BChatNotificationChannels.LEGACY),"cold state is legacy unknown/quiet");
        check(BChatNotificationChannels.present(cold,()->{}),"unknown may present only through caller's documented QUIET fallback");
        try{BChatNotificationChannels.load(app);throw new AssertionError("main load allowed");}catch(IllegalStateException expected){check(true,"main load refused");}
        try{BChatNotificationChannels.setSeparated(app,true,NAMES);throw new AssertionError("main change allowed");}catch(IllegalStateException expected){check(true,"main edit refused");}
        BChatNotificationChannels.Snapshot state=worker(()->BChatNotificationChannels.load(app));
        check(state.known&&!state.separated,"new and existing installs default legacy");
        for(String kind:Arrays.asList("chat","task","order","diagnostic"))check(BChatNotificationChannels.resolve(kind).known&&BChatNotificationChannels.resolve(kind).channelId.equals(BChatNotificationChannels.LEGACY),"known default legacy "+kind);
        check(!BChatNotificationChannels.resolve("foreign").known,"unrecognized kind is not falsely known");
        check(!BChatNotificationChannels.present(cold,()->{throw new AssertionError();}),"old unknown selection cannot post after state load");
        BChatNotificationChannels.Result missing=worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES));
        check(!missing.accepted&&missing.code.equals("baseline_missing")&&app.manager.creates==0,"missing baseline never invents loud channels");
        reset();app.prefs.memory.put("separated","true");
        check(!worker(()->BChatNotificationChannels.load(app)).known,"malformed persisted type remains unknown/quiet");
        app.prefs.memory.clear();app.failPreferences=true;
        check(!worker(()->BChatNotificationChannels.load(app)).known,"read failure remains unknown/quiet");
        app.failPreferences=false;
        check(worker(()->BChatNotificationChannels.load(app)).known,"failed cold read can be explicitly retried");
    }
    private static void migration(int sdk,int importance,Object sound,boolean vibration)throws Exception{
        reset();Build.VERSION.SDK_INT=sdk;ChannelRoutingHarness app=new ChannelRoutingHarness();NotificationChannel source=app.baseline(importance,sound,vibration);
        worker(()->BChatNotificationChannels.load(app));BChatNotificationChannels.Selection old=BChatNotificationChannels.resolve("chat");
        BChatNotificationChannels.Result result=worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES));
        check(result.accepted&&result.changed&&result.state.separated&&app.manager.creates==3,"explicit migration creates exactly three missing channels");
        check(source.mutations==0,"legacy channel is untouched");
        for(String id:Arrays.asList(BChatNotificationChannels.CHAT,BChatNotificationChannels.TASKS,BChatNotificationChannels.ORDERS)){
            NotificationChannel channel=app.manager.channels.get(id);
            check(channel.importance==importance&&Objects.equals(channel.sound,sound),"observed blocked/quiet/custom importance+sound copied");
            check(channel.attributes.equals(source.attributes)&&channel.vibration==vibration,"observed attributes and vibration mute copied");
            check(channel.pattern!=source.pattern&&Arrays.equals(channel.pattern,source.pattern),"pattern is defensively copied");
            check(!channel.bypass&&!channel.badge&&!channel.lights&&channel.lightColor==source.lightColor&&channel.visibility==Notification.VISIBILITY_SECRET,"new channel never bypasses DND or relaxes visible baseline restrictions");
            check(sdk<35?channel.effect==null:channel.effect.equals(source.effect),"vibration-effect API follows SDK boundary");
        }
        check(!BChatNotificationChannels.present(old,()->{throw new AssertionError();}),"pre-migration selection cannot notify afterward");
        check(BChatNotificationChannels.resolve("chat").channelId.equals(BChatNotificationChannels.CHAT),"chat resolves fixed channel");
        check(BChatNotificationChannels.resolve("task").channelId.equals(BChatNotificationChannels.TASKS),"task resolves fixed channel");
        check(BChatNotificationChannels.resolve("order").channelId.equals(BChatNotificationChannels.ORDERS),"order resolves fixed channel");
        check(BChatNotificationChannels.resolve("diagnostic").channelId.equals(BChatNotificationChannels.LEGACY),"diagnostics remain legacy");
        int creates=app.manager.creates;
        check(worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES)).accepted&&app.manager.creates==creates,"already selected is idempotent");
        check(worker(()->BChatNotificationChannels.setSeparated(app,false,null)).accepted,"explicit revert committed");
        check(!BChatNotificationChannels.state().separated&&app.manager.creates==creates,"revert changes routing only");
        NotificationChannel chat=app.manager.channels.get(BChatNotificationChannels.CHAT);
        chat.importance=0;chat.sound=null;chat.vibration=false; // Explicit user/system fixture, not an app setter.
        source.importance=4;source.sound="new legacy sound";source.vibration=true;
        check(worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES)).accepted,"explicit re-enable accepted");
        check(chat.importance==0&&chat.sound==null&&!chat.vibration&&app.manager.creates==creates,"existing new-channel choices survive a different legacy channel");
    }
    private static void failedChanges()throws Exception{
        reset();Build.VERSION.SDK_INT=35;ChannelRoutingHarness app=new ChannelRoutingHarness();app.baseline(4,"sound",true);
        BChatNotificationChannels.Snapshot before=worker(()->BChatNotificationChannels.load(app));
        app.prefs.fail=true;
        BChatNotificationChannels.Result rejected=worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES));
        check(!rejected.accepted&&rejected.code.equals("commit_failed")&&BChatNotificationChannels.state()==before,"failed commit never publishes routing");
        check(Boolean.TRUE.equals(app.prefs.memory.get("separated"))&&!app.prefs.disk.containsKey("separated"),"adapter models SharedPreferences mutated RAM on commit false");
        check(worker(()->BChatNotificationChannels.load(app))==before&&!BChatNotificationChannels.state().separated,"load never re-reads uncommitted preference RAM");
        check(BChatNotificationChannels.resolve("chat").channelId.equals(BChatNotificationChannels.LEGACY),"failed migration remains legacy");
        app.prefs.fail=false;check(worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES)).accepted,"same explicit migration can retry without channel rewrites");
        before=BChatNotificationChannels.state();app.prefs.fail=true;
        rejected=worker(()->BChatNotificationChannels.setSeparated(app,false,null));
        check(!rejected.accepted&&BChatNotificationChannels.state()==before&&BChatNotificationChannels.state().separated,"failed revert retains prior separated route");
        check(Boolean.FALSE.equals(app.prefs.memory.get("separated"))&&Boolean.TRUE.equals(app.prefs.disk.get("separated")),"failed revert mutates RAM but not committed fixture disk");
        check(worker(()->BChatNotificationChannels.load(app))==before&&BChatNotificationChannels.resolve("chat").channelId.equals(BChatNotificationChannels.CHAT),"reload cannot bypass a muted separated channel after failed revert");
        reset();app.prefs.memory=new HashMap<>(app.prefs.disk);
        check(worker(()->BChatNotificationChannels.load(app)).separated,"cold process reads last successful committed choice");
    }
    private static void partialAndPlatformFailures()throws Exception{
        for(int defect=0;defect<4;defect++){
            reset();ChannelRoutingHarness app=new ChannelRoutingHarness();app.baseline(3,null,false);
            BChatNotificationChannels.Snapshot before=worker(()->BChatNotificationChannels.load(app));
            if(defect==0)app.manager.failRead=true;
            if(defect==1)app.manager.failCreate=true;
            if(defect==2)app.manager.failOnCreate=BChatNotificationChannels.TASKS;
            if(defect==3)app.manager.dropCreate=true;
            BChatNotificationChannels.Result failed=worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES));
            check(!failed.accepted&&failed.code.equals("channel_unavailable")&&BChatNotificationChannels.state()==before,"platform failure preserves committed routing");
            check(app.prefs.commits==0,"channel failure never commits opt-in");
            app.manager.failRead=app.manager.failCreate=app.manager.dropCreate=false;app.manager.failOnCreate=null;
            int retained=app.manager.channels.size();
            check(worker(()->BChatNotificationChannels.setSeparated(app,true,NAMES)).accepted,"explicit retry fills missing channels only");
            check(app.manager.channels.size()==4&&app.manager.creates>=4-retained,"partial channels are retained, not deleted or reset");
        }
    }
    private static void atomicPresentation()throws Exception{
        reset();ChannelRoutingHarness app=new ChannelRoutingHarness();app.baseline(4,"sound",true);worker(()->BChatNotificationChannels.load(app));
        BChatNotificationChannels.Selection selected=BChatNotificationChannels.resolve("chat");
        CountDownLatch inside=new CountDownLatch(1),allowExit=new CountDownLatch(1),committed=new CountDownLatch(1),published=new CountDownLatch(1);
        CountDownLatch preparing=new CountDownLatch(1),continueCreate=new CountDownLatch(1);
        AtomicBoolean firstCreate=new AtomicBoolean(true);
        app.manager.beforeCreate=()->{if(firstCreate.getAndSet(false)){
            preparing.countDown();try{if(!continueCreate.await(5,TimeUnit.SECONDS))throw new AssertionError("creation gate timed out");}
            catch(InterruptedException e){throw new AssertionError(e);}
        }};
        app.prefs.afterCommit=committed::countDown;
        Throwable[] failure={null};
        Thread presentation=new Thread(()->{try{BChatNotificationChannels.present(selected,()->{inside.countDown();try{if(!allowExit.await(5,TimeUnit.SECONDS))throw new AssertionError("gate exit timed out");}catch(InterruptedException e){throw new AssertionError(e);}});}catch(Throwable e){failure[0]=e;}},"presentation-gate");
        Thread update=new Thread(()->{try{BChatNotificationChannels.setSeparated(app,true,NAMES);published.countDown();}catch(Throwable e){failure[0]=e;}},"channel-update");
        update.start();
        check(preparing.await(5,TimeUnit.SECONDS),"update passed initial snapshot before presentation gate");
        presentation.start();check(inside.await(5,TimeUnit.SECONDS),"presentation gate entered");
        continueCreate.countDown();
        check(committed.await(5,TimeUnit.SECONDS),"platform creation and disk commit execute without STATE gate");
        check(published.getCount()==1,"publication waits for the atomic presentation gate, not between check and notify");
        allowExit.countDown();presentation.join(5000);update.join(5000);
        check(failure[0]==null&&committed.getCount()==0&&published.getCount()==0,"worker update finishes without ROUTING/STATE inversion");
        check(!BChatNotificationChannels.present(selected,()->{throw new AssertionError();}),"old selection cannot present after publish");
        BChatNotificationChannels.Selection current=BChatNotificationChannels.resolve("chat");
        boolean[] effect={false};check(BChatNotificationChannels.present(current,()->effect[0]=true)&&effect[0],"atomic current selection presents");
        check(!BChatNotificationChannels.present(null,()->{})&&!BChatNotificationChannels.present(current,null),"null gate arguments do nothing");
    }
    public static void main(String[] args)throws Exception{
        Looper.getMainLooper();defaultsAndStorage();
        migration(26,0,null,false);migration(26,2,null,false);migration(26,4,"custom://sound",true);
        migration(35,4,"custom://sound",false);migration(35,3,null,true);
        failedChanges();partialAndPlatformFailures();atomicPresentation();
        System.out.println("PASS "+checks+" production channel routing checks; explicit JVM platform/prefs adapters, not Android/OEM/audio");
    }
    static final class Prefs implements SharedPreferences {
        Map<String,Object> memory=new HashMap<>(),disk=new HashMap<>();boolean fail;int commits;Runnable afterCommit;
        public Map<String,?> getAll(){platform();return new HashMap<>(memory);}
        public Editor edit(){platform();return new Edit();}
        final class Edit implements Editor {
            boolean value;public Editor putBoolean(String key,boolean value){if(!key.equals("separated"))throw new AssertionError();this.value=value;return this;}
            public boolean commit(){platform();++commits;memory.put("separated",value);if(!fail)disk=new HashMap<>(memory);if(afterCommit!=null)afterCommit.run();return !fail;}
        }
    }
}

package com.baseer.freshchat;

import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.graphics.drawable.BitmapDrawable;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.LruCache;
import android.view.View;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import com.baseer.freshchat.sync.AccountScope;
import java.io.FileOutputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real Activity/AndroidX views, explicit synthetic identity/Host/transport-completion fixtures. No HTTP/auth/perf. */
public final class RoomListInstrumentation extends Instrumentation {
    private OdooIdentityActivity activity;private Context context;private AccountScope scope;private Class<?> roomType;
    private Constructor<?> roomCtor;private int checks;private boolean uiOnly;private final JSONArray journeys=new JSONArray();
    interface Work {void run()throws Exception;}
    void check(boolean pass,String label){++checks;if(!pass)throw new AssertionError(label);}
    void ui(Work work){AtomicReference<Throwable> error=new AtomicReference<>();runOnMainSync(()->{try{work.run();}catch(Throwable failure){error.set(failure);}});if(error.get()!=null)throw new AssertionError(error.get());}
    Object get(Object target,String name)throws Exception{Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(target);}
    Object get(String name)throws Exception{return get(activity,name);}
    void set(Object target,String name,Object value)throws Exception{Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);field.set(target,value);}
    void set(String name,Object value)throws Exception{set(activity,name,value);}
    Object call(String name,Class<?>[] types,Object...args)throws Exception{Method method=OdooIdentityActivity.class.getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(activity,args);}
    Object call(String name)throws Exception{return call(name,new Class<?>[0]);}
    void settle(){waitForIdleSync();SystemClock.sleep(180);waitForIdleSync();}
    void await(String label,java.util.function.BooleanSupplier value)throws Exception{for(int i=0;i<100;++i){AtomicReference<Boolean> ready=new AtomicReference<>();ui(()->ready.set(value.getAsBoolean()));if(ready.get())return;SystemClock.sleep(25);}throw new AssertionError(label);}
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);uiOnly=arguments!=null&&"darkFont2".equals(arguments.getString("componentOnly"));start();}
    @Override public void onStart(){Bundle reply=new Bundle();JSONObject result=new JSONObject();boolean passed=false;
        try{
            context=getTargetContext();check(context.getPackageName().equals("com.baseer.bchat.room.list.test"),"isolated package");
            check(context.getPackageManager().checkPermission("android.permission.INTERNET",context.getPackageName())!=0,"no INTERNET");
            activity=(OdooIdentityActivity)startActivitySync(new Intent(context,OdooIdentityActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            await("Activity local layout",()->{try{return get("roomRecycler")!=null;}catch(Exception ignored){return false;}});
            SystemClock.sleep(400);ui(()->call("releaseWeb"));settle();
            if(!uiOnly){fixture();activityJourneys();avatarJourneys();}
            componentJourneys();if(!uiOnly)laneJourneys();
            check(get("web")==null,"no WebView transport recreated");passed=true;
        }catch(Throwable error){try{result.put("failure",error.toString()).put("stack",new JSONArray(Arrays.asList(error.getStackTrace())));}catch(Exception ignored){}}
        try{result.put("passed",passed).put("checks",checks).put("journeys",journeys).put("scope","Synthetic full Activity identity/proof, real room adapter/differ/Android views; controlled Host and avatar completion. NOT auth/HTTP/benchmark/product APK/cart acceptance.");
            try(FileOutputStream file=context.openFileOutput("room-list-results.json",0)){file.write(result.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        }catch(Exception error){passed=false;}
        if(activity!=null)ui(()->activity.finish());reply.putString("stream",(passed?"PASS ":"FAIL ")+checks+" room-list checks "+result.optString("failure")+"\n");finish(passed?-1:1,reply);
    }
    Object room(long id,long member,String name)throws Exception{Object room=roomCtor.newInstance(id,1L,member,name);set(room,"isGroup",true);set(room,"avatarVersion",1);return room;}
    @SuppressWarnings("unchecked") void fixture()throws Exception{
        scope=new AccountScope("https://c26.invalid","synthetic",7);
        roomType=Class.forName("com.baseer.freshchat.OdooIdentityActivity$Room");roomCtor=roomType.getDeclaredConstructor(long.class,long.class,long.class,String.class);roomCtor.setAccessible(true);
        Class<?> permission=Class.forName("com.baseer.freshchat.OdooIdentityActivity$PermissionSet");Method parse=permission.getDeclaredMethod("parse",JSONObject.class);parse.setAccessible(true);
        JSONObject wire=new JSONObject().put("version",1).put("revision",1);for(String key:new String[]{"chat_view","chat_send","media","media_view","media_upload","media_download"})wire.put(key,true);
        for(String key:new String[]{"group_create","group_manage","task_view","task_manage","room_admin"})wire.put(key,false);Object rights=parse.invoke(null,wire);
        List<Object> rooms=new ArrayList<>();for(int id=1;id<=100;++id)rooms.add(room(id,1000+id,String.format(Locale.ROOT,"فريق Room %03d",id)));
        ui(()->{call("clearChatView");set("account",scope);set("verified",true);set("offlineHistory",false);set("permissionSet",rights);set("permissionAccount",scope);
            set("v2Busy",true);set("roomsVerifiedForSession",true);set("globalPendingKnown",true);set("visibleSection","chats");
            Set<Long> companies=(Set<Long>)get("v1Companies");companies.clear();companies.add(1L);((List<Object>)get("rooms")).addAll(rooms);
            call("showShell");call("showPermittedRoot");call("admitRoomListSnapshot");call("showRooms");});settle();
    }
    @SuppressWarnings("unchecked") void activityJourneys()throws Exception{
        RecyclerView list=(RecyclerView)get("roomRecycler");await("100 actual rows",()->list.getAdapter()!=null&&list.getAdapter().getItemCount()==100);
        ui(()->{check(list.getChildCount()>0,"actual Activity visible Recycler rows");check(((View)get("nativeForm")).getVisibility()==View.GONE,"no duplicate login sibling");});
        ui(()->((EditText)get("roomSearchInput")).setText("Room 09"));await("query subset",()->list.getAdapter().getItemCount()==10);
        ui(()->((EditText)get("roomSearchInput")).setText("zzzz"));await("zero results",()->list.getAdapter().getItemCount()==0);
        ui(()->check(((View)get("roomItems")).getVisibility()==View.VISIBLE,"no-result overlay"));
        ui(()->((EditText)get("roomSearchInput")).setText(""));await("all restored",()->list.getAdapter().getItemCount()==100);
        Object old=((List<?>)get("rooms")).get(0), replacement=room(1,2001,"Rejoined");long owner=((Number)get("roomListEpoch")).longValue();
        BChatRoomRow.Key oldKey=new BChatRoomRow.Key(scope.key,1,1001);
        ui(()->{
            check(call("currentRoomRow",new Class<?>[]{long.class,BChatRoomRow.Key.class},owner,oldKey)==old,"click resolver returns current Room object");
            List<Object> next=new ArrayList<>((List<Object>)get("rooms"));next.set(0,replacement);
            call("invalidateRoomListForSnapshot",new Class<?>[]{List.class},next);
            check(list.getAdapter()==null,"membership replacement detaches synchronously");
            List<Object> current=(List<Object>)get("rooms");current.clear();current.addAll(next);call("admitRoomListSnapshot");call("renderRooms");
            long fresh=((Number)get("roomListEpoch")).longValue();check(call("currentRoomRow",new Class<?>[]{long.class,BChatRoomRow.Key.class},fresh,oldKey)==null,"old membership cannot resolve");
            check(call("currentRoomRow",new Class<?>[]{long.class,BChatRoomRow.Key.class},fresh,new BChatRoomRow.Key(scope.key,1,2001))==replacement,"fresh membership exact canonical resolver");
            call("clearRoomListNow");check(list.getAdapter()==null,"rights clear synchronously empty");call("renderRooms");check(list.getAdapter()==null,"render cannot re-admit cleared authority");
            set("offlineHistory",true);set("verified",false);set("offlineChatCacheAvailable",true);set("offlinePersistenceReady",true);call("admitRoomListSnapshot");call("showRooms");
        });await("offline rows",()->list.getAdapter()!=null&&list.getAdapter().getItemCount()==100);
        ui(()->check(((View)get("composerRow")).getVisibility()==View.GONE,"offline room list remains read-only"));
        journeys.put("fullActivity-search-empty-rejoin-currentClickResolver-synchronousRightsClear-offline");
        ui(()->{set("offlineHistory",false);set("verified",true);call("admitRoomListSnapshot");call("showRooms");});settle();
    }
    @SuppressWarnings("unchecked") void avatarJourneys()throws Exception{
        Object canonical=((List<?>)get("rooms")).get(0);String key=scope.key+":1:2001:1";Bitmap red=Bitmap.createBitmap(8,8,Bitmap.Config.ARGB_8888);red.eraseColor(0xffff0000);
        Bitmap blue=Bitmap.createBitmap(8,8,Bitmap.Config.ARGB_8888);blue.eraseColor(0xff0000ff);
        ui(()->{
            ((LruCache<String,Bitmap>)get("groupAvatarCache")).put(scope.key+":1:1001:1",red);
            View fresh=(View)call("roomAvatarView",new Class<?>[]{roomType},canonical);ImageView image=(ImageView)((FrameLayout)fresh).getChildAt(1);
            check(image.getDrawable()==null,"old membership cache not borrowed");Object target=fresh.getTag(),request=get(target,"request");
            check(key.equals(get(request,"key")),"header and list use membership-qualified avatar key");
            set("groupAvatarActive",request);int nonce=((Number)get("groupAvatarNonce")).intValue();set("groupAvatarBusy",true);
            call("finishGroupAvatar",new Class<?>[]{String.class,Bitmap.class,int.class},key,blue,nonce);
            check(image.getDrawable() instanceof BitmapDrawable&&((BitmapDrawable)image.getDrawable()).getBitmap()==blue,"current canonical completion accepted");
            call("releaseGroupAvatarView",new Class<?>[]{View.class},fresh);check(image.getDrawable()==null,"detach/recycle lease scrubs bitmap");
            ((LruCache<String,Bitmap>)get("groupAvatarCache")).evictAll();
            View stale=(View)call("roomAvatarView",new Class<?>[]{roomType},canonical);Object staleTarget=stale.getTag(),staleRequest=get(staleTarget,"request");
            ImageView staleImage=(ImageView)((FrameLayout)stale).getChildAt(1);set("groupAvatarActive",staleRequest);nonce=((Number)get("groupAvatarNonce")).intValue();
            ((List<Object>)get("rooms")).set(0,room(1,3001,"New member"));
            call("finishGroupAvatar",new Class<?>[]{String.class,Bitmap.class,int.class},key,red,nonce);
            check(staleImage.getDrawable()==null,"late removed-membership completion rejected");check(((LruCache<?,?>)get("groupAvatarCache")).size()==0,"stale completion does not populate cache");
            call("clearRoomListNow");check(((List<?>)get("groupAvatarQueue")).size()<=100,"queue metadata bounded by current leases");
        });journeys.put("actualActivity-avatar-cacheMembership-completionLease-rejoin-recycle-noHTTP");
    }
    BChatRoomRow row(String name,long member,int unread,String style){return new BChatRoomRow(new BChatRoomRow.Key("synthetic",1,member),1,name,"preview رسالة","12:34","شركة Branch","مهام Tasks",unread,1,true,true,style);}
    static final class ControlledHost implements BChatRoomListAdapter.Host {
        boolean valid=true;int opened,cancelled;BChatRoomRow.Key allowed;
        public boolean current(){return valid;}public boolean current(BChatRoomRow row){return valid&&row.key.equals(allowed);}
        public void open(BChatRoomRow.Key key){if(valid&&key.equals(allowed))++opened;}
        public Runnable avatar(BChatRoomRow row,FrameLayout slot){slot.addView(new Ui.Avatar(slot.getContext(),row.name,"group",47),new FrameLayout.LayoutParams(-1,-1));return () -> {++cancelled;slot.removeAllViews();};}
        public void committed(int count){}
    }
    void componentJourneys()throws Exception{
        for(String locale:new String[]{"ar","en"})for(String theme:new String[]{"light","dark"})for(int scale:new int[]{1,2}){
            if(uiOnly&&!(locale.equals("ar")&&theme.equals("dark")&&scale==2))continue;
            Configuration config=new Configuration(activity.getResources().getConfiguration());config.setLocale(Locale.forLanguageTag(locale));config.setLayoutDirection(Locale.forLanguageTag(locale));config.fontScale=scale;
            config.uiMode=(config.uiMode&~Configuration.UI_MODE_NIGHT_MASK)|("dark".equals(theme)?Configuration.UI_MODE_NIGHT_YES:Configuration.UI_MODE_NIGHT_NO);
            Context themed=activity.createConfigurationContext(config);ControlledHost host=new ControlledHost();BChatRoomRow row=row("اسم طويل Professional room name repeated repeated repeated",1,199,locale+theme+scale);host.allowed=row.key;
            AtomicReference<RecyclerView> reference=new AtomicReference<>();AtomicReference<BChatRoomListAdapter> adapterRef=new AtomicReference<>();
            ui(()->{RecyclerView list=new RecyclerView(themed);list.setLayoutDirection(AppLocale.direction(themed));list.setBackgroundColor(UiPalette.surface(themed));list.setLayoutManager(new LinearLayoutManager(themed));list.setItemAnimator(null);
                BChatRoomListAdapter adapter=new BChatRoomListAdapter(host,Runnable::run);reference.set(list);adapterRef.set(adapter);list.setAdapter(adapter);activity.setContentView(list);adapter.submit(Arrays.asList(row));});settle();
            RecyclerView list=reference.get();BChatRoomListAdapter adapter=adapterRef.get();
            ui(()->{BChatRoomListAdapter.Holder holder=(BChatRoomListAdapter.Holder)list.findViewHolderForAdapterPosition(0);check(holder!=null,"real row attached "+locale+theme+scale);
                check(themed.getResources().getConfiguration().getLocales().get(0).getLanguage().equals(locale),"actual resource locale");
                check(holder.entry.getLayoutDirection()==AppLocale.direction(themed),"actual resolved row direction");
                Rect avatarRect=new Rect(),labelRect=new Rect();holder.avatar.getGlobalVisibleRect(avatarRect);holder.name.getGlobalVisibleRect(labelRect);
                check("ar".equals(locale)?avatarRect.centerX()>labelRect.centerX():avatarRect.centerX()<labelRect.centerX(),"avatar physical side matches RTL/LTR");
                check(holder.entry.getHeight()>=Ui.dp(themed,48),"48dp touch minimum");
                check(holder.badge.getHeight()>=holder.badge.getLayout().getHeight()+holder.badge.getCompoundPaddingTop()+holder.badge.getCompoundPaddingBottom(),"badge text not vertically clipped font"+scale);
                check(holder.task.getHeight()>=holder.task.getLayout().getHeight()+holder.task.getCompoundPaddingTop()+holder.task.getCompoundPaddingBottom(),"task chip wrap/min-height font"+scale);
                if(uiOnly)check(((android.graphics.drawable.GradientDrawable)holder.task.getBackground()).getColor().getDefaultColor()==UiPalette.background(themed,Ui.ACTION_TONAL),"task background resolves central semantic tonal token");
                Rect nameRect=new Rect(),timeRect=new Rect();holder.name.getGlobalVisibleRect(nameRect);holder.time.getGlobalVisibleRect(timeRect);check(holder.name.getWidth()>0&&!Rect.intersects(nameRect,timeRect),"time/name non-overlap");
                check(holder.entry.performClick()&&host.opened==1,"current exact-key click");
                host.valid=false;adapter.invalidateNow();list.setAdapter(null);check(holder.name.length()==0&&holder.preview.length()==0&&holder.avatar.getChildCount()==0,"sync detached row scrub");
                holder.entry.performClick();check(host.opened==1,"stale click rejected");
                host.valid=true;BChatRoomListAdapter replacement=new BChatRoomListAdapter(host,Runnable::run);list.setAdapter(replacement);replacement.submit(Arrays.asList(row));
            });settle();
            try(FileOutputStream capture=context.openFileOutput("rooms-"+locale+"-"+theme+"-font"+scale+".png",0)){getUiAutomation().takeScreenshot().compress(Bitmap.CompressFormat.PNG,100,capture);}
            journeys.put("component-realAndroidX-"+locale+"-"+theme+"-font"+scale);
        }
        if(uiOnly)return;
        // Actual AsyncListDiffer completion held across owner detach, not a copied differ algorithm.
        List<Runnable> held=new ArrayList<>();ControlledHost old=new ControlledHost();BChatRoomRow a=row("owner A",1,0,"x");old.allowed=a.key;
        AtomicReference<RecyclerView> list=new AtomicReference<>();AtomicReference<BChatRoomListAdapter> obsolete=new AtomicReference<>();
        ui(()->{RecyclerView view=new RecyclerView(activity);view.setLayoutManager(new LinearLayoutManager(activity));activity.setContentView(view);list.set(view);
            BChatRoomListAdapter adapter=new BChatRoomListAdapter(old,held::add);obsolete.set(adapter);view.setAdapter(adapter);adapter.submit(Arrays.asList(a));adapter.submit(Arrays.asList(row("queued A",1,1,"x")));});settle();
        check(held.size()==1,"real differ work deliberately held");ControlledHost fresh=new ControlledHost();BChatRoomRow b=row("owner B",2,0,"x");fresh.allowed=b.key;
        ui(()->{old.valid=false;obsolete.get().invalidateNow();list.get().setAdapter(null);BChatRoomListAdapter adapter=new BChatRoomListAdapter(fresh,Runnable::run);list.get().setAdapter(adapter);adapter.submit(Arrays.asList(b));});
        Thread completion=new Thread(held.get(0),"test-held-diff");completion.start();completion.join();settle();
        ui(()->{check(obsolete.get().getItemCount()==0,"old diff cannot reactivate detached owner");BChatRoomListAdapter.Holder holder=(BChatRoomListAdapter.Holder)list.get().findViewHolderForAdapterPosition(0);check("owner B".contentEquals(holder.name.getText()),"old diff cannot overwrite new owner");});
        journeys.put("realAsyncListDiffer-heldCompletion-ownerDetach-newMembership");
    }
    void laneJourneys()throws Exception{
        BChatRoomListAdapter.Lane first=new BChatRoomListAdapter.Lane(),second=new BChatRoomListAdapter.Lane();CountDownLatch started=new CountDownLatch(2),release=new CountDownLatch(1),done=new CountDownLatch(2);List<Integer> seen=java.util.Collections.synchronizedList(new ArrayList<>());
        Runnable blocking=()->{started.countDown();try{release.await(2,TimeUnit.SECONDS);}catch(Exception ignored){}};
        first.execute(blocking);second.execute(blocking);check(started.await(2,TimeUnit.SECONDS),"two screen-owned lanes independent");
        first.execute(()->seen.add(10));first.execute(()->{seen.add(11);done.countDown();});second.execute(()->{seen.add(20);done.countDown();});release.countDown();
        check(done.await(2,TimeUnit.SECONDS),"both latest owners finish");check(seen.contains(11)&&seen.contains(20)&&!seen.contains(10),"bounded latest-only queue never drops another screen request");first.close();second.close();journeys.put("actualTwoIndependentBoundedLanes-close");
    }
}

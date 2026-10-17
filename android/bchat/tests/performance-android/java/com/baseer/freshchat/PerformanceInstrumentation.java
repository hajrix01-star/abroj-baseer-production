package com.baseer.freshchat;

import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.content.res.Configuration;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.os.Debug;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.LruCache;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewTreeObserver;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import androidx.recyclerview.widget.AsyncListDiffer;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import com.baseer.freshchat.sync.*;
import java.io.FileOutputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Full unmodified production Activity. Reflection is an EXPLICIT synthetic fixture, not auth/HTTP. */
public final class PerformanceInstrumentation extends Instrumentation {
    private static final String PACKAGE="com.baseer.bchat.performance.test",INPUT="c26-native-input";
    private OdooIdentityActivity activity;
    private Context context;
    private AccountScope scope;
    private Object room;
    private Class<?> roomType;
    private BChatV2Outbox outbox;
    private ConnectedHistoryCache cache;
    private RecyclerView timeline;
    private LinearLayoutManager layoutManager;
    private CountingTimelineAdapter adapter;
    private RecyclerView roomTimeline;
    private CountingTimelineAdapter roomAdapter;
    private String fixture;
    private JSONObject activeRound;
    private JSONArray activeRoomQueries;
    private volatile String memoryScenario="idle";
    private final JSONArray rounds=new JSONArray();
    private int checks,blockedInputObservations;
    private interface Work {void run()throws Exception;}
    private void check(boolean value,String label){++checks;if(!value)throw new AssertionError(label);}
    private void ui(Work work){
        AtomicReference<Throwable> failure=new AtomicReference<>();
        runOnMainSync(()->{try{work.run();}catch(Throwable error){failure.set(error);}});
        if(failure.get()!=null)throw new AssertionError("UI fixture/action failed",failure.get());
    }
    private Object get(String name)throws Exception{Field field=OdooIdentityActivity.class.getDeclaredField(name);field.setAccessible(true);return field.get(activity);}
    private void set(String name,Object value)throws Exception{Field field=OdooIdentityActivity.class.getDeclaredField(name);field.setAccessible(true);field.set(activity,value);}
    private Object call(String name,Class<?>[] types,Object... args)throws Exception{
        Method method=OdooIdentityActivity.class.getDeclaredMethod(name,types);method.setAccessible(true);
        try{return method.invoke(activity,args);}catch(InvocationTargetException failure){throw new Exception("Production "+name,failure.getCause());}
    }
    private Object call(String name)throws Exception{return call(name,new Class<?>[0]);}
    @SuppressWarnings("unchecked") private <T> T field(String name)throws Exception{return (T)get(name);}
    private void visible(String name,boolean shown)throws Exception{((View)get(name)).setVisibility(shown?View.VISIBLE:View.GONE);}
    private void settle(){waitForIdleSync();SystemClock.sleep(180);waitForIdleSync();}
    private void await(String label,java.util.function.BooleanSupplier condition)throws Exception{
        long until=SystemClock.elapsedRealtime()+10000;
        while(SystemClock.elapsedRealtime()<until){AtomicBoolean ok=new AtomicBoolean();ui(()->ok.set(condition.getAsBoolean()));if(ok.get())return;SystemClock.sleep(25);}
        throw new IllegalStateException("Blocked scenario: "+label);
    }
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
    @Override public void onStart(){
        JSONObject evidence=new JSONObject();Bundle result=new Bundle();boolean passed=false;
        try{
            context=getTargetContext();check(PACKAGE.equals(context.getPackageName()),"isolated namespace");
            evidence.put("compiled_source_commit",BuildConfig.BCHAT_SOURCE_COMMIT);
            check(Build.VERSION.SDK_INT==35,"actual API35 only");
            check(!BuildConfig.BCHAT_PUSH_ENABLED&&"https://c26.invalid".equals(BuildConfig.BCHAT_ORIGIN),"test-only disabled transport origin");
            check(context.getPackageManager().checkPermission("android.permission.INTERNET",PACKAGE)!=0,"no INTERNET permission");
            context.getSharedPreferences("bchat-appearance-v1",0).edit().putString("theme","light").putInt("body_sp",16).commit();
            context.getSharedPreferences("bchat-local-settings-v1",0).edit().putString("interface-language","ar").commit();
            activity=(OdooIdentityActivity)startActivitySync(new Intent(context,OdooIdentityActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            await("full Activity local initialization",()->{try{return get("roomItems")!=null&&get("messageScroll")!=null;}catch(Exception error){return false;}});
            // Wait for the existing local cookie/open callback, then stop all ports/timers with the real method.
            SystemClock.sleep(400);ui(()->call("releaseWeb"));settle();
            check(get("web")==null,"real releaseWeb stopped WebView/ports");
            installFixture();
            evidence.put("fixture",fixtureManifest()).put("platform",platform());
            resetRound();rounds.put(runRound("warmup",false));
            for(int round=1;round<=3;++round){resetRound();rounds.put(runRound("round-"+round,true));}
            resetRound();evidence.put("memory_round",memoryRound());
            check(get("web")==null&&(Boolean)get("v2Busy"),"no transport recreated during measurements");
            evidence.put("rounds",rounds);passed=true;
        }catch(Throwable failure){
            try{evidence.put("failure",failure.toString()).put("stack",new JSONArray(Arrays.asList(failure.getStackTrace()))).put("rounds",rounds).put("partial_round",activeRound);}catch(Exception ignored){}
        }
        try{
            evidence.put("passed",passed).put("checks",checks).put("schema",2)
                .put("blocked_input_visibility_observations",blockedInputObservations)
                .put("baseline_status",blockedInputObservations>0?"partial_input_visibility_blocked":"collected_pending_independent_review")
                .put("scope","Full unmodified production Activity/components/SQLite with test-only reflection identity/permission/data injection, NOT authentication/bootstrap/HTTP. Synthetic100rooms/500messages, cached thumbnails and idleaudio; no codec/network/backend/audio/OEM/ownerphone/product-performance claim.")
                .put("limitations","Instrumented emulator, debug/JIT and transparent adapter observer overhead. Host contention cannot be eliminated. Pre-draw is not input-to-photon; durable local row is not server ACK. Memory highest sample is not true peak/leak/battery proof. Frame-report loss invalidates comparison, not displayed lost-frame count.");
            try(FileOutputStream file=context.openFileOutput("performance-results.json",Context.MODE_PRIVATE)){
                file.write(evidence.toString(2).getBytes(StandardCharsets.UTF_8));
            }
            result.putString("stream",(passed?"PASS ":"FAIL ")+checks+" full Activity C26 fixture checks; "+evidence.optString("failure","")+"\n");
        }catch(Exception failure){passed=false;result.putString("stream","FAIL evidence write "+failure+"\n");}
        if(activity!=null)ui(()->activity.finish());
        finish(passed?-1:1,result);
    }

    @SuppressWarnings("unchecked") private void installFixture()throws Exception{
        scope=new AccountScope("https://c26.invalid","synthetic",7);
        roomType=Class.forName("com.baseer.freshchat.OdooIdentityActivity$Room");
        Constructor<?> ctor=roomType.getDeclaredConstructor(long.class,long.class,long.class,String.class);ctor.setAccessible(true);
        List<Object> rooms=new ArrayList<>();List<ConnectedHistoryCache.RoomRecord> records=new ArrayList<>();
        for(int id=1;id<=100;++id){rooms.add(ctor.newInstance((long)id,1L,1000L+id,String.format(Locale.ROOT,"فريق Room %03d",id)));
            records.add(new ConnectedHistoryCache.RoomRecord(id,1000+id,1,String.format(Locale.ROOT,"فريق Room %03d",id),"off",1));}
        room=rooms.get(0);outbox=new BChatV2Outbox(context);
        BChatConnectedMediaStore media=new BChatConnectedMediaStore(context);cache=field("historyCache");
        List<JSONObject> messages=messages();JSONArray data=new JSONArray();for(JSONObject message:messages)data.put(message);fixture=data.toString();
        // Validate each real wire-sized page, then seed actual SQLite off main. Not authentication.
        cache.reconcile(scope,false,records);
        for(int offset=0;offset<messages.size();offset+=30){
            List<JSONObject> page=messages.subList(offset,Math.min(messages.size(),offset+30));JSONArray wire=new JSONArray();
            for(JSONObject message:page)wire.put(message);
            List<JSONObject> validated=(List<JSONObject>)call("validateMessageList",new Class<?>[]{JSONArray.class,long.class},wire,0L);
            check(validated.size()==page.size(),"actual production page/media/reply validation");cache.savePage(scope,1,1001,validated);
        }
        check(cache.rooms(scope).size()==100,"actual SQLite contains100 fixture rooms");
        try(Cursor rows=cache.getReadableDatabase().rawQuery("SELECT COUNT(*) FROM cached_message WHERE account_key=? AND room_id=1 AND membership_id=1001",new String[]{scope.key})){
            check(rows.moveToFirst()&&rows.getLong(0)==500,"actual SQLite contains500 fixture messages");
        }
        JSONObject permission=new JSONObject().put("version",1).put("revision",1);
        for(String key:new String[]{"chat_view","chat_send","media","media_view","media_upload","media_download"})permission.put(key,true);
        for(String key:new String[]{"group_create","group_manage","task_view","task_manage","room_admin"})permission.put(key,false);
        Class<?> permissions=Class.forName("com.baseer.freshchat.OdooIdentityActivity$PermissionSet");
        Method parse=permissions.getDeclaredMethod("parse",JSONObject.class);parse.setAccessible(true);Object granted=parse.invoke(null,permission);
        List<Bitmap> thumbs=new ArrayList<>();for(int i=0;i<50;++i){Bitmap bitmap=Bitmap.createBitmap(96,96,Bitmap.Config.ARGB_8888);bitmap.eraseColor(0xff336699+i);thumbs.add(bitmap);}
        ui(()->{
            set("account",scope);set("verified",true);set("offlineHistory",false);set("permissionSet",granted);set("permissionAccount",scope);
            set("csrfToken","synthetic-local-only");set("outbox",outbox);set("mediaStore",media);set("mediaAvailable",true);
            set("receiptsAvailable",false);set("receiptDeliverySupported",false);set("liveStarted",false);set("v2Busy",true);
            set("globalPendingKnown",true);set("globalPendingAvailable",false);set("visibleSection","chats");set("roomsVerifiedForSession",true);
            Set<Long> companies=field("v1Companies");companies.clear();companies.add(1L);
            List<Object> actual=field("rooms");actual.clear();actual.addAll(rooms);
            // Explicit synthetic accepted-snapshot fixture, NOT a bootstrap/authentication proof.
            // Use the real owner helper rather than bypassing its current-scope checks in renderRooms.
            call("admitRoomListSnapshot");
            LruCache<String,Bitmap> thumbnails=field("mediaThumbnailCache");thumbnails.evictAll();
            for(int i=0;i<50;++i)thumbnails.put(scope.key+":1:"+(10401+i),thumbs.get(i));
            check(thumbnails.size()==50*96*96*4&&thumbnails.size()<=2*1024*1024,"50 real96px bitmap fixtures within2MiB");
            // Real verified flow passes through showShell before exposing the permitted root.
            // showPermittedRoot alone does not hide the startup weighted login ScrollView.
            call("showShell");call("showPermittedRoot");
            check(((View)get("nativeForm")).getVisibility()==View.GONE&&((View)get("status")).getVisibility()==View.GONE
                &&((View)get("shell")).getVisibility()==View.GONE,"actual login/status/shell absent from synthetic verified layout");
            timeline=field("messageScroll");layoutManager=field("messageLayout");
            RecyclerView.Adapter<RecyclerView.ViewHolder> original=(RecyclerView.Adapter<RecyclerView.ViewHolder>)get("messageAdapter");
            adapter=new CountingTimelineAdapter(original);timeline.setAdapter(adapter);
        });
    }
    private List<JSONObject> messages()throws Exception{
        List<JSONObject> result=new ArrayList<>();
        for(int index=1;index<=500;++index){
            JSONObject message=new JSONObject().put("id",30+index).put("author_user_id",index%3==0?7:2)
                .put("author_name",index%3==0?"أنا Owner":"زميل Peer").put("created_at",String.format(Locale.ROOT,"2026-10-17 %02d:%02d:%02d",8+index/3600,(index/60)%60,index%60))
                .put("text",index<=400?text(index):"").put("delivery_state",index%4==0?"read":"sent");
            if(index>400)message.put("media",media(index>450?"audio":"image",10000+index));
            if(index<=400&&index%17==0)message.put("reply",new JSONObject().put("id",index+20).put("author_name","زميل Peer").put("text","رد Reply"));
            result.add(message);
        }
        return result;
    }
    private static String text(int index){
        String base=index%2==0?"رسالة عربية ثابتة للاختبار فقط ":"Deterministic English fixture only ";
        StringBuilder value=new StringBuilder();for(int i=0;i<(index%3==0?8:index%3==1?1:3);++i)value.append(base);return value.append(index).toString();
    }
    private static JSONObject media(String kind,long id)throws Exception{return new JSONObject().put("id",id).put("kind",kind)
        .put("mime","audio".equals(kind)?"audio/mp4":"image/jpeg").put("name",kind+"-"+id+("audio".equals(kind)?".m4a":".jpg"))
        .put("sha256","0000000000000000000000000000000000000000000000000000000000000001")
        .put("document_type","other").put("thumbnail_available",!"audio".equals(kind)).put("size",4096);}
    private List<JSONObject> copyFixture()throws Exception{JSONArray values=new JSONArray(fixture);List<JSONObject> result=new ArrayList<>();for(int i=0;i<values.length();++i)result.add(values.getJSONObject(i));return result;}
    private void resetRound()throws Exception{
        for(BChatV2Outbox.Entry entry:outbox.roomEntries(scope,1,1001))check(outbox.discard(scope,entry),"discard only preceding synthetic local entry");
        List<JSONObject> window=copyFixture();
        ui(()->{
            ((EditText)get("messageInput")).clearFocus();InputMethodManager ime=activity.getSystemService(InputMethodManager.class);
            if(ime!=null)ime.hideSoftInputFromWindow(((View)get("messageInput")).getWindowToken(),0);
            set("suppressDraftChanges",true);((EditText)get("messageInput")).setText("");set("suppressDraftChanges",false);
            set("roomDraftNeedsRestore",false);set("draftActive",true);set("textEnqueueBusy",false);set("v2Busy",true);
            set("selectedRoom",room);call("refreshLocalRoom",new Class<?>[]{roomType,boolean.class},room,false);
            call("updateMessageRows",new Class<?>[]{List.class},window);
        });
        await("real local RoomLocalSnapshot callback",()->{try{return get("roomLocal")!=null&&!(Boolean)get("localReadBusy");}catch(Exception e){return false;}});
        ui(()->{set("draftActive",true);call("updatePendingUi");});settle();
        check(outbox.roomEntries(scope,1,1001).isEmpty(),"each round begins with no local queued entry");
        check(((List<?>)get("displayedMessages")).size()==500,"unchanged500 fixture bound");
        verifyPositions();
    }
    private void verifyPositions(){ui(()->{for(int i=0;i<timeline.getChildCount();++i){RecyclerView.ViewHolder holder=timeline.getChildViewHolder(timeline.getChildAt(i));
        int position=holder.getBindingAdapterPosition();check(position!=RecyclerView.NO_POSITION,"proxy preserves binding position");
        check(holder.getItemId()==adapter.delegate.getItemId(position),"proxy preserves stable IDs");}});}
    @SuppressWarnings("unchecked") private void roomsView()throws Exception{
        ui(()->{
            set("globalPendingKnown",true);call("showRooms");
            RecyclerView actual=field("roomRecycler");
            RecyclerView.Adapter<RecyclerView.ViewHolder> delegate=(RecyclerView.Adapter<RecyclerView.ViewHolder>)get("roomListAdapter");
            check(delegate!=null,"real accepted room-list owner created actual adapter");
            if(roomAdapter==null){
                roomTimeline=actual;roomAdapter=new CountingTimelineAdapter(delegate);roomTimeline.setAdapter(roomAdapter);
            }else check(roomTimeline==actual&&roomAdapter.delegate==delegate&&actual.getAdapter()==roomAdapter,
                "one transparent room wrapper retained; no implicit adapter replacement or extra manual binding");
        });
        settle();awaitRoomList("");
        ui(()->check(((View)get("roomScroll")).getHeight()>0&&((View)get("roomScroll")).isShown(),"actual room viewport visible before search measurements"));
    }
    private List<Long> expectedRoomIds(String input){
        String query=input.trim().toLowerCase(Locale.ROOT);List<Long> expected=new ArrayList<>();
        // Independent deterministic fixture truth: one company has no company subtitle/search label.
        // Do not call product filter/projection to derive the expected answer.
        for(long id=1;id<=100;++id)if(String.format(Locale.ROOT,"فريق Room %03d",id).toLowerCase(Locale.ROOT).contains(query))expected.add(id);
        return expected;
    }
    @SuppressWarnings("unchecked") private List<BChatRoomRow> currentRoomRows()throws Exception{
        Field field=BChatRoomListAdapter.class.getDeclaredField("differ");field.setAccessible(true);
        return ((AsyncListDiffer<BChatRoomRow>)field.get(roomAdapter.delegate)).getCurrentList();
    }
    private boolean roomListSettled(List<Long> expected)throws Exception{
        if(roomTimeline!=get("roomRecycler")||roomAdapter.delegate!=get("roomListAdapter")||roomTimeline.getAdapter()!=roomAdapter)return false;
        List<BChatRoomRow> current=currentRoomRows();
        if(current.size()!=expected.size()||roomAdapter.getItemCount()!=expected.size())return false;
        for(int index=0;index<current.size();++index){BChatRoomRow row=current.get(index);long id=expected.get(index);
            if(row.key.room!=id||row.key.membership!=1000+id||!scope.key.equals(row.key.account))return false;
        }
        if(roomTimeline.hasPendingAdapterUpdates()||roomTimeline.isComputingLayout()||roomTimeline.isLayoutRequested())return false;
        if(!current.isEmpty()&&(roomTimeline.getChildCount()==0||roomTimeline.getHeight()<=0||!roomTimeline.isShown()))return false;
        if(current.isEmpty()&&roomTimeline.getChildCount()!=0)return false;
        for(int index=0;index<roomTimeline.getChildCount();++index){
            RecyclerView.ViewHolder holder=roomTimeline.getChildViewHolder(roomTimeline.getChildAt(index));int position=holder.getBindingAdapterPosition();
            if(position==RecyclerView.NO_POSITION||position>=current.size()||!(holder instanceof BChatRoomListAdapter.Holder))return false;
            BChatRoomRow bound=((BChatRoomListAdapter.Holder)holder).bound;
            if(bound==null||!bound.key.equals(current.get(position).key))return false;
        }
        return true;
    }
    private JSONObject awaitRoomList(String query)throws Exception{
        List<Long> expected=expectedRoomIds(query);long start=System.nanoTime(),deadline=SystemClock.elapsedRealtime()+10000;int polls=0;
        while(SystemClock.elapsedRealtime()<deadline){
            AtomicBoolean ready=new AtomicBoolean();ui(()->ready.set(roomListSettled(expected)));++polls;
            if(ready.get()){
                long waited=System.nanoTime()-start;
                ui(()->check(roomListSettled(expected),"latest room diff/order/membership and actual laid-out holder binding positions match deterministic fixture"));
                return new JSONObject().put("query",query).put("expected_room_ids",new JSONArray(expected)).put("fixed_delay_ms",80)
                    .put("additional_current_diff_layout_wait_ns",waited).put("readiness_polls",polls);
            }
            SystemClock.sleep(10);
        }
        throw new IllegalStateException("Blocked scenario: latest room diff/layout did not settle for query="+query);
    }
    private void chatView()throws Exception{ui(()->{
        set("selectedRoom",room);visible("brandBar",false);visible("bottomTabs",false);visible("roomListHeader",false);
        visible("roomScroll",false);visible("chatTitleBar",true);visible("messageFrame",true);visible("composerRow",true);
        visible("olderControl",false);visible("newerControl",false);set("draftActive",true);call("updatePendingUi");
        layoutManager.scrollToPositionWithOffset(250,8);
    });settle();ui(()->check(timeline.getHeight()>0&&timeline.isShown(),"actual chat viewport visible before timeline measurements"));verifyPositions();}

    private JSONObject runRound(String name,boolean measured)throws Exception{
        FrameSamples frames=measured?new FrameSamples():null;JSONObject round=new JSONObject().put("name",name).put("measured",measured)
            .put("fixture_sha256",sha(fixture)).put("local_rows_before",outbox.roomEntries(scope,1,1001).size()).put("platform",platform());
        activeRound=round;JSONArray scenarios=new JSONArray();round.put("scenarios",scenarios);
        Throwable actionFailure=null;if(frames!=null)ui(()->frames.attach(activity.getWindow()));
        try{
            roomsView();activeRoomQueries=new JSONArray();scenario(frames,scenarios,"rooms-search",()->{
                for(String query:new String[]{"Room","فريق","Room 0","Room 09","zzzz","","1",""}){
                    ui(()->((EditText)get("roomSearchInput")).setText(query));SystemClock.sleep(80);activeRoomQueries.put(awaitRoomList(query));
                }
            });
            chatView();scenario(frames,scenarios,"timeline-scroll",()->{for(int i=0;i<6;++i)swipe(timeline,i%2==0);});
            scenario(frames,scenarios,"unchanged-poll",()->{for(int i=0;i<10;++i){List<JSONObject> same=new ArrayList<>((List<JSONObject>)get("displayedMessages"));ui(()->call("updateMessageRows",new Class<?>[]{List.class},same));SystemClock.sleep(80);}});
            ui(()->layoutManager.scrollToPositionWithOffset(251,8));settle();
            scenario(frames,scenarios,"visible-row-state-change",()->{
                List<JSONObject> changed=new ArrayList<>((List<JSONObject>)get("displayedMessages"));int first=layoutManager.findFirstVisibleItemPosition(),last=layoutManager.findLastVisibleItemPosition(),target=-1;
                for(int position=first;position<=last&&position<changed.size();++position)if(position>=0&&changed.get(position).optLong("author_user_id")==7){target=position;break;}
                check(target>=0,"visible own-author delivery-state target");JSONObject clone=new JSONObject(changed.get(target).toString());clone.put("delivery_state","delivered");changed.set(target,clone);
                ui(()->call("updateMessageRows",new Class<?>[]{List.class},changed));
            });
            scenario(frames,scenarios,"prepend-trim-anchor",()->{
                AtomicReference<Object> anchor=new AtomicReference<>();ui(()->anchor.set(call("currentScrollAnchor")));
                Field id=anchor.get().getClass().getDeclaredField("messageId"),offset=anchor.get().getClass().getDeclaredField("offset");id.setAccessible(true);offset.setAccessible(true);
                long before=id.getLong(anchor.get());int pixels=offset.getInt(anchor.get());
                List<JSONObject> next=new ArrayList<>();for(int i=1;i<=30;++i)next.add(new JSONObject().put("id",i).put("author_user_id",2).put("author_name","زميل Peer").put("created_at",String.format(Locale.ROOT,"2026-10-17 07:59:%02d",i)).put("text","").put("media",media("audio",20000+i)));
                next.addAll(((List<JSONObject>)get("displayedMessages")).subList(0,470));
                ui(()->call("renderMessageWindow",new Class<?>[]{roomType,List.class,boolean.class,long.class,anchor.get().getClass()},room,next,false,0L,anchor.get()));settle();
                AtomicReference<Object> after=new AtomicReference<>();ui(()->after.set(call("currentScrollAnchor")));
                check(id.getLong(after.get())==before&&Math.abs(offset.getInt(after.get())-pixels)<=1,"prepend/trim preserves actual stable-ID anchor within1px");
                check(((List<?>)get("displayedMessages")).size()==500,"prepend retains500 cap");
            });
            ui(()->layoutManager.scrollToPosition(adapter.getItemCount()-1));settle();
            AtomicReference<JSONObject> latency=new AtomicReference<>();
            scenario(frames,scenarios,"native-input-send-during-update",()->latency.set(nativeSend()));
            round.put("input_to_predraw",latency.get());
        }catch(Throwable failure){actionFailure=failure;round.put("blocked_or_failure",failure.toString());
        }finally{
            if(frames!=null){ui(()->activity.getWindow().removeOnFrameMetricsAvailableListener(frames));frames.finish();}
        }
        if(frames!=null){JSONObject data=frames.export();round.put("frames",data);check(data.getBoolean("comparison_valid"),"reject overflow/lost frame-metric reports");
            JSONObject input=round.optJSONObject("input_to_predraw");if(input!=null){JSONArray summaries=data.getJSONArray("summaries");for(int index=0;index<summaries.length();++index){JSONObject summary=summaries.getJSONObject(index);
                if("native-input-send-during-update".equals(summary.getString("scenario")))summary.put("input_visibility_status",input.getString("status")).put("input_latency_accepted","observed".equals(input.getString("status")));
            }}
        }
        if(actionFailure!=null)throw new Exception("Blocked round "+name,actionFailure);
        return round;
    }
    private void scenario(FrameSamples frames,JSONArray rows,String name,Work action)throws Exception{
        memoryScenario=name;JSONObject before=adapter.counts(),roomBefore=roomAdapter.counts();
        FrameSamples.Stage stage=frames==null?null:frames.begin(name);long start=System.nanoTime();
        action.run();settle();long end=System.nanoTime();if(stage!=null)frames.end(stage);
        JSONObject row=new JSONObject().put("name",name).put("action_and_settle_ns",end-start).put("adapter_before",before).put("adapter_after",adapter.counts())
            .put("room_recycler_before",roomBefore).put("room_recycler_after",roomAdapter.counts());
        if("rooms-search".equals(name))row.put("query_settle",activeRoomQueries)
            .put("comparison_units","Baseline529 counted clickable LinearLayout entry creations for8queries. Current creates count real RecyclerView holder creations; binds/notifications are separate and are NOT the old529 unit.");
        rows.put(row);
        memoryScenario="idle";
    }
    private void swipe(View view,boolean up)throws Exception{
        int[] origin=new int[2];ui(()->view.getLocationOnScreen(origin));float x=origin[0]+view.getWidth()*.5f;
        float from=origin[1]+view.getHeight()*(up?.80f:.25f),to=origin[1]+view.getHeight()*(up?.25f:.80f);
        long down=SystemClock.uptimeMillis();event(down,down,MotionEvent.ACTION_DOWN,x,from);
        for(int i=1;i<=12;++i){SystemClock.sleep(30);event(down,SystemClock.uptimeMillis(),MotionEvent.ACTION_MOVE,x,from+(to-from)*i/12);}
        event(down,SystemClock.uptimeMillis(),MotionEvent.ACTION_UP,x,to);SystemClock.sleep(100);
    }
    private void event(long down,long at,int action,float x,float y){MotionEvent event=MotionEvent.obtain(down,at,action,x,y,0);event.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);sendPointerSync(event);event.recycle();}
    private long tap(View view)throws Exception{
        int[] xy=new int[2];ui(()->view.getLocationOnScreen(xy));float x=xy[0]+view.getWidth()/2f,y=xy[1]+view.getHeight()/2f;
        long at=SystemClock.uptimeMillis();event(at,at,MotionEvent.ACTION_DOWN,x,y);SystemClock.sleep(45);long up=SystemClock.uptimeMillis();event(at,up,MotionEvent.ACTION_UP,x,y);return up*1000000L;
    }
    private JSONObject nativeSend()throws Exception{
        ui(()->check(timeline.getHeight()>0&&timeline.isShown(),"actual chat viewport visible before native input"));
        EditText composer=field("messageInput");tap(composer);sendStringSync(INPUT);settle();
        ui(()->{check(INPUT.contentEquals(composer.getText()),"actual injected editor text exact");check(((View)get("sendButton")).isEnabled(),"actual product send button enabled");
            check(timeline.getHeight()>0&&timeline.isShown(),"actual chat viewport remains visible after keyboard settles, before native send");});
        Handler main=new Handler(Looper.getMainLooper());List<Runnable> refreshes=new ArrayList<>();CountDownLatch updates=new CountDownLatch(4);
        AtomicInteger executedUpdates=new AtomicInteger();AtomicReference<Throwable> updateFailure=new AtomicReference<>();
        for(int i=0;i<4;++i){Runnable action=()->{try{call("updateMessageRows",new Class<?>[]{List.class},new ArrayList<>((List<JSONObject>)get("displayedMessages")));executedUpdates.incrementAndGet();}catch(Throwable error){updateFailure.set(error);}finally{updates.countDown();}};refreshes.add(action);main.postDelayed(action,i*120);}
        CountDownLatch drawn=new CountDownLatch(1);long[] first={0};String[] uuid={null};long[] id={0};
        ViewTreeObserver.OnPreDrawListener observer=()->{
            try{
                List<BChatV2Outbox.Entry> local=field("localTextRows");
                for(BChatV2Outbox.Entry entry:local)if(INPUT.equals(entry.body)){
                    for(int index=0;index<timeline.getChildCount();++index){View child=timeline.getChildAt(index);RecyclerView.ViewHolder holder=timeline.getChildViewHolder(child);Rect visible=new Rect();
                        if(holder.getItemId()==-entry.id&&child.getWidth()>0&&child.getHeight()>0&&child.getGlobalVisibleRect(visible)&&visible.height()>0){
                            if(first[0]==0){first[0]=System.nanoTime();uuid[0]=entry.uuid;id[0]=entry.id;drawn.countDown();}
                        }
                    }
                }
            }catch(Exception e){throw new AssertionError(e);}return true;
        };
        ui(()->timeline.getViewTreeObserver().addOnPreDrawListener(observer));long inputUp=tap(field("sendButton"));
        boolean observed=drawn.await(10,TimeUnit.SECONDS);ui(()->timeline.getViewTreeObserver().removeOnPreDrawListener(observer));
        check(updates.await(2,TimeUnit.SECONDS)&&executedUpdates.get()==4&&updateFailure.get()==null,"all four actual concurrent update callbacks completed");
        for(Runnable action:refreshes)main.removeCallbacks(action);
        BChatV2Outbox.Entry durable=null;for(BChatV2Outbox.Entry entry:outbox.roomEntries(scope,1,1001))if(INPUT.equals(entry.body))durable=entry;
        check(durable!=null&&INPUT.equals(durable.body),"actual native send durably queued unique synthetic body in SQLite, no ACK");
        JSONObject result=new JSONObject().put("native_action_up_ns",inputUp).put("uuid",durable.uuid).put("local_entry_id",durable.id)
            .put("sqlite_verified_after_observation",true).put("concurrent_update_callbacks",executedUpdates.get()).put("not_server_ack",true);
        if(!observed){
            ++blockedInputObservations;
            AtomicReference<JSONObject> viewport=new AtomicReference<>();ui(()->{JSONArray ids=new JSONArray();
                for(int index=0;index<timeline.getChildCount();++index)ids.put(timeline.getChildViewHolder(timeline.getChildAt(index)).getItemId());
                JSONArray localRows=new JSONArray();for(BChatV2Outbox.Entry entry:(List<BChatV2Outbox.Entry>)get("localTextRows"))localRows.put(new JSONObject().put("id",entry.id).put("uuid",entry.uuid));
                JSONArray snapshotRows=new JSONArray();Object snapshot=get("roomLocal");if(snapshot!=null){Field text=snapshot.getClass().getDeclaredField("text");text.setAccessible(true);
                    for(BChatV2Outbox.Entry entry:(List<BChatV2Outbox.Entry>)text.get(snapshot))snapshotRows.put(new JSONObject().put("id",entry.id).put("uuid",entry.uuid));}
                int modelPosition=-1;for(int position=0;position<adapter.getItemCount();++position)if(adapter.getItemId(position)<0)modelPosition=position;
                AccountScope current=field("account");Object currentRoom=get("selectedRoom");Rect shown=new Rect();boolean timelineVisible=timeline.getGlobalVisibleRect(shown);
                viewport.set(new JSONObject().put("first_visible_position",layoutManager.findFirstVisibleItemPosition()).put("last_visible_position",layoutManager.findLastVisibleItemPosition())
                    .put("attached_stable_ids",ids).put("adapter_count",adapter.getItemCount()).put("pending_model_position",modelPosition).put("local_text_rows",localRows).put("room_local_text_rows",snapshotRows)
                    .put("timeline_height_px",timeline.getHeight()).put("timeline_visible",timelineVisible).put("timeline_visible_height_px",shown.height()).put("vertical_scroll_offset_px",timeline.computeVerticalScrollOffset())
                    .put("ime_bottom_px",activity.getWindow().getDecorView().getRootWindowInsets().getInsets(android.view.WindowInsets.Type.ime()).bottom)
                    .put("fixture_scope_key",scope.key).put("current_scope_key",current==null?JSONObject.NULL:current.key).put("selected_room_is_fixture",currentRoom==room)
                    .put("fixture_room_id",1).put("fixture_membership_id",1001).put("receipt_storage_generation",get("receiptStorageGeneration"))
                    .put("receipt_rebind_generation",get("receiptRebindGeneration")).put("history_global_generation",get("historyGlobalGeneration"))
                    .put("history_write_generation",get("historyWriteGeneration")).put("storage_repository_generation",BChatStorageRepository.generation(scope)).put("local_read_busy",get("localReadBusy")));
            });
            return result.put("status","blocked_uuid_not_visible").put("first_visible_uuid_predraw_ns",JSONObject.NULL).put("elapsed_ns",JSONObject.NULL)
                .put("observation_timeout_ms",10000).put("viewport",viewport.get())
                .put("note","Durable enqueue succeeded, but exact local UUID did not reach visible pre-draw within observation. No synthetic scroll or latency fabricated; this scenario has no input-to-visible baseline.");
        }
        check(durable.id==id[0]&&durable.uuid.equals(uuid[0]),"visible pre-draw UUID matches actual durable SQLite row");
        check(first[0]>=inputUp,"same monotonic timebase input->predraw nonnegative");
        return result.put("status","observed").put("first_visible_uuid_predraw_ns",first[0]).put("elapsed_ns",first[0]-inputUp).put("sqlite_verified_after_predraw",true);
    }
    private JSONObject memoryRound()throws Exception{
        AtomicBoolean running=new AtomicBoolean(true);AtomicReference<Throwable> samplingFailure=new AtomicReference<>();List<long[]> samples=new ArrayList<>();List<String> names=new ArrayList<>();
        Thread sampler=new Thread(()->{
            try{
            long next=SystemClock.elapsedRealtime();while(running.get()){
                Debug.MemoryInfo memory=new Debug.MemoryInfo();Debug.getMemoryInfo(memory);
                long javaUsed=Runtime.getRuntime().totalMemory()-Runtime.getRuntime().freeMemory();
                if(samples.size()==128)throw new IllegalStateException("Memory sample cap exceeded");
                samples.add(new long[]{SystemClock.elapsedRealtime(),memory.getTotalPss(),javaUsed,Debug.getNativeHeapAllocatedSize()});names.add(memoryScenario);
                next+=500;SystemClock.sleep(Math.max(1,next-SystemClock.elapsedRealtime()));
            }
            }catch(Throwable failure){samplingFailure.set(failure);}
        },"c26-memory-sampler");sampler.start();JSONObject actions;
        try{actions=runRound("separate-memory",false);memoryScenario="steady-observation-window";SystemClock.sleep(2500);}finally{running.set(false);sampler.join(3000);}
        check(!sampler.isAlive()&&samples.size()>0&&samplingFailure.get()==null,"bounded separate memory sampler completed");
        JSONArray raw=new JSONArray();List<Long> pss=new ArrayList<>(),java=new ArrayList<>(),nativeBytes=new ArrayList<>();
        for(int i=0;i<samples.size();++i){long[] value=samples.get(i);raw.put(new JSONObject().put("elapsed_ms",value[0]).put("scenario",names.get(i))
            .put("pss_kib",value[1]).put("java_used_bytes",value[2]).put("native_allocated_bytes",value[3]));pss.add(value[1]);java.add(value[2]);nativeBytes.add(value[3]);}
        List<Long> steady=new ArrayList<>();for(int i=0;i<samples.size();++i)if("steady-observation-window".equals(names.get(i)))steady.add(samples.get(i)[1]);
        return new JSONObject().put("raw",raw).put("interval_ms",500).put("pss_kib",FrameSamples.stats(pss)).put("steady_observation_pss_kib",FrameSamples.stats(steady)).put("java_used_bytes",FrameSamples.stats(java))
            .put("native_allocated_bytes",FrameSamples.stats(nativeBytes)).put("actions",actions)
            .put("note","Separate round; medians/highest observed samples, NOT true peak, leak, battery, or production footprint proof.");
    }
    private JSONObject fixtureManifest()throws Exception{return new JSONObject().put("rooms",100).put("messages",500).put("text",400).put("images",50).put("idle_audio",50)
        .put("thumb_edge_px",96).put("thumb_bytes",50*96*96*4).put("text_json_sha256",sha(fixture)).put("input",INPUT)
        .put("identity","synthetic test-only uid7/company1/room1/member1001; no actual bootstrap/authentication")
        .put("room_owner","real admitRoomListSnapshot called after synthetic account/permissions/100rooms injection; not actual server acceptance/authentication")
        .put("room_search","same8queries and80ms fixed delay; additional latest-diff/order/membership+layout wait measured inside scenario and recorded, never subtracted")
        .put("room_counters","same transparent delegate wrapper used for real room RecyclerView create/bind/notify/lifecycle; no manual bind. Old529 was LinearLayout entry creations, not RecyclerView binds. No assertion that avatar/network call counts are unchanged")
        .put("layout","actual showShell then showPermittedRoot; startup login/status hidden, no second weighted login sibling")
        .put("prepend", "30 older idle audio rows replace last30idleaudio, still400text50image50audio and500bound");}
    private JSONObject platform()throws Exception{
        Configuration config=activity.getResources().getConfiguration();Rect bounds=activity.getWindowManager().getCurrentWindowMetrics().getBounds();
        return new JSONObject().put("sdk",Build.VERSION.SDK_INT).put("fingerprint",Build.FINGERPRINT).put("hardware",Build.HARDWARE)
            .put("window_width",bounds.width()).put("window_height",bounds.height()).put("density_dpi",config.densityDpi).put("font_scale",config.fontScale)
            .put("locale",config.getLocales().toLanguageTags()).put("orientation",config.orientation).put("ui_mode",config.uiMode).put("body_sp",ChatAppearance.bodySp(activity))
            .put("refresh_hz",activity.getDisplay().getRefreshRate()).put("host_contention","exclusive team heavy-tool window requested; host/emulator contention not perfectly isolated");
    }
    private static String sha(String value)throws Exception{
        StringBuilder result=new StringBuilder();for(byte part:MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)))result.append(String.format(Locale.ROOT,"%02x",part&255));return result.toString();
    }
}

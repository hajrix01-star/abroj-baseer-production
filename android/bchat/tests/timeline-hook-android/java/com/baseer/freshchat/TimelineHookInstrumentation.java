package com.baseer.freshchat;

import android.app.*;
import android.content.*;
import android.content.res.Configuration;
import android.database.Cursor;
import android.graphics.*;
import android.graphics.drawable.BitmapDrawable;
import android.os.*;
import android.util.LruCache;
import android.view.*;
import android.webkit.WebView;
import android.widget.*;
import androidx.recyclerview.widget.*;
import com.baseer.freshchat.sync.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.*;

/** Full unmodified target Activity + real AndroidX/SQLite. Identity/proofs are synthetic, NOT auth/HTTP. */
public final class TimelineHookInstrumentation extends Instrumentation {
    static final String PACKAGE="com.baseer.bchat.timeline.hook.test";
    OdooIdentityActivity activity; Context context; AccountScope scope;
    Object room,secondRoom,permission; Class<?> roomType,permissionType,ownerType;
    BChatV2Outbox outbox; ConnectedHistoryCache cache;
    RecyclerView timeline; LinearLayoutManager layout; CountingTimelineAdapter adapter;
    List<JSONObject> original; int checks; String selectedCase="functional"; final JSONArray journeys=new JSONArray();
    interface Work { void run() throws Exception; }
    void check(boolean ok,String label){++checks;if(!ok)throw new AssertionError(label);}
    void ui(Work work){AtomicReference<Throwable> failure=new AtomicReference<>();runOnMainSync(()->{try{work.run();}catch(Throwable error){failure.set(error);}});if(failure.get()!=null)throw new AssertionError("MAIN action",failure.get());}
    Object get(String name)throws Exception{Field f=OdooIdentityActivity.class.getDeclaredField(name);f.setAccessible(true);return f.get(activity);}
    void set(String name,Object value)throws Exception{Field f=OdooIdentityActivity.class.getDeclaredField(name);f.setAccessible(true);f.set(activity,value);}
    @SuppressWarnings("unchecked") <T>T field(String name)throws Exception{return(T)get(name);}
    Object call(String name,Class<?>[] types,Object...args)throws Exception{Method m=OdooIdentityActivity.class.getDeclaredMethod(name,types);m.setAccessible(true);try{return m.invoke(activity,args);}catch(InvocationTargetException e){throw new Exception(name,e.getCause());}}
    Object call(String name)throws Exception{return call(name,new Class<?>[0]);}
    void settle(){waitForIdleSync();SystemClock.sleep(150);waitForIdleSync();}
    void await(String label,java.util.function.BooleanSupplier test)throws Exception{long end=SystemClock.elapsedRealtime()+6000;while(SystemClock.elapsedRealtime()<end){AtomicBoolean ok=new AtomicBoolean();ui(()->ok.set(test.getAsBoolean()));if(ok.get())return;SystemClock.sleep(20);}throw new IllegalStateException("Blocked: "+label);}
    void visibility(String name,boolean shown)throws Exception{((View)get(name)).setVisibility(shown?View.VISIBLE:View.GONE);}
    @Override public Activity newActivity(ClassLoader loader,String name,Intent intent)
            throws InstantiationException,IllegalAccessException,ClassNotFoundException{
        Activity target=super.newActivity(loader,name,intent);
        // Public test instantiation seam: the same final production Activity, before
        // attach/resources. No subclass/product/global configuration modification.
        Configuration override=new Configuration();override.fontScale=2f;
        Locale language=Locale.forLanguageTag("ar");override.setLocale(language);override.setLayoutDirection(language);
        override.uiMode=Configuration.UI_MODE_NIGHT_YES;
        target.applyOverrideConfiguration(override);return target;
    }
    @Override public void onCreate(Bundle args){if(args!=null)selectedCase=args.getString("case","functional");super.onCreate(args);start();}
    @Override public void onStart(){Bundle status=new Bundle();JSONObject result=new JSONObject();boolean passed=false;
        try{
            context=getTargetContext();check(PACKAGE.equals(context.getPackageName()),"isolated package");
            check(Build.VERSION.SDK_INT==35,"actual SDK35");
            check(!BuildConfig.BCHAT_PUSH_ENABLED&&BuildConfig.BCHAT_ORIGIN.equals("https://timeline.invalid"),"test transport configuration");
            check(context.getPackageManager().checkPermission("android.permission.INTERNET",PACKAGE)!=0,"no INTERNET permission");
            context.getSharedPreferences("bchat-appearance-v1",0).edit().putString("theme","dark").putInt("body_sp",16).commit();
            context.getSharedPreferences("bchat-local-settings-v1",0).edit().putString("interface-language","ar").commit();
            activity=(OdooIdentityActivity)startActivitySync(new Intent(context,OdooIdentityActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            await("actual local initialization",()->{try{return get("messageScroll")!=null&&get("historyCache")!=null;}catch(Exception e){return false;}});
            SystemClock.sleep(350);ui(()->call("releaseWeb"));settle();check(get("web")==null,"actual releaseWeb stops ports and timers");
            Configuration config=activity.getResources().getConfiguration();
            result.put("actual_configuration",new JSONObject().put("fontScale",config.fontScale)
                .put("locale",config.getLocales().get(0).toLanguageTag()).put("uiMode",config.uiMode)
                .put("dark",ChatAppearance.dark(activity)).put("width_px",activity.getResources().getDisplayMetrics().widthPixels));
            check(config.fontScale==2f,"actual font2");check(config.getLocales().get(0).getLanguage().equals("ar"),"actual Arabic locale");check(ChatAppearance.dark(activity),"actual dark mode");
            install();fresh();
            if(selectedCase.equals("send-visibility"))sendVisibility(result);
            else if(selectedCase.equals("functional")){unchangedAndFieldChange();neighborAndAnchor();emptyAndLocals();mediaAndIdleAudio();invalidationJourneys();sameRoomAba();}
            else throw new IllegalArgumentException("Unknown isolated case");
            check(get("web")==null,"no transport recreated");passed=true;
        }catch(Throwable failure){try{result.put("failure",failure.toString()).put("stack",new JSONArray(Arrays.asList(failure.getStackTrace())));}catch(Exception ignored){}}
        try{result.put("passed",passed).put("checks",checks).put("case",selectedCase).put("journeys",journeys)
            .put("base_commit",BuildConfig.BCHAT_SOURCE_COMMIT).put("activity_sha256",BuildConfig.BCHAT_TARGET_ACTIVITY_SHA)
            .put("configuration_fixture","Explicit public early Activity override AR/RTL+dark+font2, not appearance/locale preference restoration acceptance; no global device setting change")
            .put("scope","Full unmodified Activity/AndroidX/SQLite, synthetic account/permissions/canonical and receipt proof inputs. One AR/dark/font2 functional run; no auth/HTTP/FCM/benchmark.")
            .put("media_limits","Native cached-image/recycle/queued-target and synthetic idle-audio owner/control checks only. No inflight decode/download, playing, focus, codec or owner-phone claim; unchanged callback bodies reuse prior separately scoped evidence.");
            try(FileOutputStream file=context.openFileOutput("timeline-hook-results.json",0)){file.write(result.toString(2).getBytes(StandardCharsets.UTF_8));}
            status.putString("stream",(passed?"PASS ":"FAIL ")+checks+" full Activity timeline functional checks; "+result.optString("failure","")+"\n");
        }catch(Exception error){passed=false;status.putString("stream","FAIL result write "+error);}
        if(activity!=null)ui(()->activity.finish());finish(passed?-1:1,status);
    }
    @SuppressWarnings("unchecked") void install()throws Exception{
        scope=new AccountScope("https://timeline.invalid","synthetic",7);roomType=Class.forName("com.baseer.freshchat.OdooIdentityActivity$Room");
        Constructor<?> ctor=roomType.getDeclaredConstructor(long.class,long.class,long.class,String.class);ctor.setAccessible(true);
        room=ctor.newInstance(1L,1L,1001L,"فريق الاختبار — Timeline");secondRoom=ctor.newInstance(2L,1L,2001L,"غرفة ثانية");
        permissionType=Class.forName("com.baseer.freshchat.OdooIdentityActivity$PermissionSet");permission=parsePermission(true,true);
        ownerType=Class.forName("com.baseer.freshchat.OdooIdentityActivity$TimelineWindowOwner");
        outbox=new BChatV2Outbox(context);cache=field("historyCache");original=messages();
        cache.reconcile(scope,false,Arrays.asList(new ConnectedHistoryCache.RoomRecord(1,1001,1,"Room","off",1),new ConnectedHistoryCache.RoomRecord(2,2001,1,"Other","off",1)));
        for(int offset=0;offset<500;offset+=30){List<JSONObject> page=original.subList(offset,Math.min(500,offset+30));JSONArray raw=new JSONArray();for(JSONObject m:page)raw.put(m);
            List<JSONObject> validated=(List<JSONObject>)call("validateMessageList",new Class<?>[]{JSONArray.class,long.class},raw,0L);cache.savePage(scope,1,1001,validated);}
        try(Cursor count=cache.getReadableDatabase().rawQuery("SELECT COUNT(*) FROM cached_message WHERE account_key=? AND room_id=1 AND membership_id=1001",new String[]{scope.key})){check(count.moveToFirst()&&count.getInt(0)==500,"real SQLite500 canonical fixtures");}
        timeline=field("messageScroll");layout=field("messageLayout");
        adapter=new CountingTimelineAdapter((RecyclerView.Adapter<RecyclerView.ViewHolder>)get("messageAdapter"));
        LruCache<String,Bitmap> thumbs=field("mediaThumbnailCache");for(int i=401;i<=450;++i){Bitmap b=Bitmap.createBitmap(96,96,Bitmap.Config.ARGB_8888);b.eraseColor(0xff336699+i);thumbs.put(scope.key+":1:"+(10000+i),b);}
        check(thumbs.size()==50*96*96*4&&thumbs.size()<=2*1024*1024,"50cached96px bitmaps within2MiB");
    }
    Object parsePermission(boolean chat,boolean media)throws Exception{JSONObject p=new JSONObject().put("version",1).put("revision",chat?1:2);
        for(String key:new String[]{"chat_view","chat_send"})p.put(key,chat);
        for(String key:new String[]{"media","media_view","media_upload","media_download"})p.put(key,media);
        for(String key:new String[]{"group_create","group_manage","task_view","task_manage","room_admin"})p.put(key,false);
        Method parse=permissionType.getDeclaredMethod("parse",JSONObject.class);parse.setAccessible(true);return parse.invoke(null,p);}
    List<JSONObject> messages()throws Exception{List<JSONObject> rows=new ArrayList<>();for(int n=1;n<=500;++n){JSONObject m=message(30+n,n%3==0?7:2,n<=400?"رسالة طويلة للاختبار — Message "+n:"");
        if(n>400)m.put("media",media(n>450?"audio":"image",10000+n));if(n<=400&&n%17==0)m.put("reply",new JSONObject().put("id",n+20).put("author_name","زميل").put("text","اقتباس"));rows.add(m);}return rows;}
    static JSONObject message(long id,long author,String text)throws Exception{return new JSONObject().put("id",id).put("author_user_id",author).put("author_name",author==7?"أنا":"زميل")
        .put("text",text).put("created_at","2026-10-18 08:00:00").put("delivery_state","sent");}
    static JSONObject media(String kind,long id)throws Exception{return new JSONObject().put("id",id).put("kind",kind).put("mime",kind.equals("audio")?"audio/mp4":"image/jpeg")
        .put("name",kind+"-"+id+(kind.equals("audio")?".m4a":".jpg")).put("sha256","0000000000000000000000000000000000000000000000000000000000000001")
        .put("document_type","other").put("thumbnail_available",!kind.equals("audio")).put("size",4096);}
    List<JSONObject> copy(List<JSONObject> rows)throws Exception{List<JSONObject> result=new ArrayList<>();for(JSONObject row:rows)result.add(new JSONObject(row.toString()));return result;}
    @SuppressWarnings("unchecked") void fresh()throws Exception{ui(()->{
        call("invalidateMessageTimelineOwner");set("account",scope);set("verified",true);set("offlineHistory",false);set("permissionSet",permission);set("permissionAccount",scope);
        set("csrfToken","synthetic-only");set("outbox",outbox);set("mediaStore",new BChatConnectedMediaStore(context));set("mediaAvailable",true);
        set("receiptsAvailable",false);set("receiptDeliverySupported",false);set("liveStarted",false);set("liveForeground",true);set("v2Busy",true);
        set("globalPendingKnown",true);set("globalPendingAvailable",false);set("visibleSection","chats");set("roomsVerifiedForSession",true);set("selectedRoom",room);
        Set<Long> companies=field("v1Companies");companies.clear();companies.add(1L);List<Object> rooms=field("rooms");rooms.clear();rooms.add(room);rooms.add(secondRoom);
        call("showShell");call("showPermittedRoot");check((Boolean)call("admitMessageTimelineOwner",new Class<?>[]{roomType},room),"actual synthetic binding admitted, not auth");
        check(((View)get("nativeForm")).getVisibility()==View.GONE&&((View)get("status")).getVisibility()==View.GONE&&((View)get("shell")).getVisibility()==View.GONE,"startup siblings hidden by actual shell flow");
        // The dedicated send oracle uses the actual product adapter, before setup.
        // The separately scoped functional/counting fixture remains unchanged.
        if(selectedCase.equals("send-visibility"))timeline.setAdapter(adapter.delegate);
        call("publishMessageRows",new Class<?>[]{List.class,List.class},copy(original),Collections.emptyList());
        if(!selectedCase.equals("send-visibility"))timeline.setAdapter(adapter);
        for(String v:new String[]{"brandBar","bottomTabs","roomListHeader","roomScroll"})visibility(v,false);
        for(String v:new String[]{"chatTitleBar","messageFrame","composerRow"})visibility(v,true);
        visibility("olderControl",false);visibility("newerControl",false);set("draftActive",true);set("roomDraftNeedsRestore",false);
        layout.scrollToPositionWithOffset(250,8);
    });settle();ui(()->check(timeline.getHeight()>0&&timeline.isShown()&&timeline.getChildCount()>0,"actual positive viewport"));positions();}
    BChatTimelineRows.Snapshot snapshot()throws Exception{return field("messageRowSnapshot");}
    Object currentAnchor(){AtomicReference<Object> value=new AtomicReference<>();ui(()->value.set(call("currentScrollAnchor")));return value.get();}
    void positions(){ui(()->{check(timeline.getAdapter()==(selectedCase.equals("send-visibility")?adapter.delegate:adapter),"declared actual/counting adapter retained for bounded functional action");for(int n=0;n<timeline.getChildCount();++n){RecyclerView.ViewHolder h=timeline.getChildViewHolder(timeline.getChildAt(n));int p=h.getBindingAdapterPosition();check(p>=0&&p<adapter.getItemCount(),"actual binding position");check(h.getItemId()==adapter.delegate.getItemId(p),"actual stable id");Field bubble=h.getClass().getDeclaredField("bubble");bubble.setAccessible(true);check(bubble.get(h) instanceof View||adapter.getItemId(p)==Long.MIN_VALUE,"actual Holder.bubble preserved");}});}
    void unchangedAndFieldChange()throws Exception{long binds=adapter.binds,notify=adapter.rangeChanged,all=adapter.changed;BChatTimelineRows.Snapshot before=snapshot();
        ui(()->call("updateMessageRows",new Class<?>[]{List.class},copy(original)));settle();
        check(adapter.binds==binds&&adapter.rangeChanged==notify&&adapter.changed==all,"500unchanged no notify/rebind");
        check(snapshot().rows.size()==500&&snapshot().scope.equals(before.scope),"snapshot bounded and stable owner");
        int index=layout.findFirstVisibleItemPosition()+1;List<JSONObject> changed=copy(original);changed.get(index).put("text","تعديل مرئي فقط");
        ui(()->call("updateMessageRows",new Class<?>[]{List.class},changed));settle();
        check(adapter.changed==all&&adapter.rangeChanged==notify+1&&adapter.binds>binds,"one visible body field not fullnotify");
        check(snapshot().rows.get(index).server.body.equals("تعديل مرئي فقط"),"actual immutable projection field");positions();
        journeys.put(new JSONObject().put("name","500unchanged-one-visible-change").put("counts",adapter.counts()));}
    long anchorField(Object anchor,String name)throws Exception{Field f=anchor.getClass().getDeclaredField(name);f.setAccessible(true);return((Number)f.get(anchor)).longValue();}
    void neighborAndAnchor()throws Exception{AtomicReference<Object> anchor=new AtomicReference<>();ui(()->anchor.set(call("currentScrollAnchor")));long id=anchorField(anchor.get(),"messageId"),pixels=anchorField(anchor.get(),"offset");
        List<JSONObject> next=new ArrayList<>();for(int n=1;n<=30;++n)next.add(message(n,2,"أقدم "+n));next.addAll(copy(original.subList(0,470)));
        BChatTimelineRows.Row oldFirst=snapshot().rows.get(0);ui(()->call("renderMessageWindow",new Class<?>[]{roomType,List.class,boolean.class,long.class,anchor.get().getClass()},room,next,false,0L,anchor.get()));settle();
        Object after=currentAnchor();check(anchorField(after,"messageId")==id&&Math.abs(anchorField(after,"offset")-pixels)<=1,"prepend+trim stableID/pixel anchor<=1px");
        check(snapshot().serverCount==500&&!oldFirst.sameRender(snapshot().rows.get(30)),"first former row neighbor invalidated after prepend");
        int visible=layout.findFirstVisibleItemPosition()+1;List<JSONObject> stamp=copy(next);stamp.get(visible).put("created_at","2026-10-17 22:00:00");long prior=adapter.rangeChanged;
        ui(()->call("updateMessageRows",new Class<?>[]{List.class},stamp));settle();check(adapter.rangeChanged==prior+2,"timestamp/header change invalidates own and next neighbor rows");
        positions();screenshot("timeline-ar-dark-font2-anchor.png");journeys.put("prepend-trim-neighbor-header-anchor");}
    void refresh()throws Exception{ui(()->call("refreshLocalRoom",new Class<?>[]{roomType,boolean.class},room,false));await("actual SQLite local callback",()->{try{return!(Boolean)get("localReadBusy");}catch(Exception e){return false;}});settle();}
    void localState(BChatV2Outbox.Entry entry,String state)throws Exception{refresh();BChatTimelineRows.Snapshot s=snapshot();boolean found=false;for(BChatTimelineRows.Row row:s.rows)if(row.local!=null&&row.local.sqliteId==entry.id){check(row.local.uuid.equals(entry.uuid)&&row.local.state.name().equalsIgnoreCase(state),"actual local state/UUID "+state);found=true;}check(found,"local row admitted "+state);positions();}
    void emptyAndLocals()throws Exception{for(BChatV2Outbox.Entry e:outbox.roomEntries(scope,1,1001))check(outbox.discard(scope,e),"discard isolated fixture only");
        ui(()->check((Boolean)call("publishMessageRows",new Class<?>[]{List.class,List.class},Collections.emptyList(),Collections.emptyList()),"publish EMPTY"));settle();
        check(snapshot().rows.size()==1&&adapter.getItemCount()==1&&adapter.getItemId(0)==Long.MIN_VALUE,"EMPTY has actual sentinel stableID");
        outbox.saveDraft(scope,1,1001,"persistent draft",0,77);BChatV2Outbox.Entry queued=outbox.enqueue(scope,1,1001,"same-body"),second=outbox.enqueue(scope,1,1001,"same-body");
        localState(queued,"queued");check(snapshot().localCount==2&&adapter.getItemId(0)==-queued.id&&adapter.getItemId(1)==-second.id,"same-body locals keep distinct durableIDs/UUIDs");
        long now=1000000;BChatV2Outbox.Entry claim=outbox.claimHead(scope,1,1001,now);check(claim!=null,"real SQLite claim");localState(claim,"sending");
        check(outbox.recordFailure(scope,claim,false,now),"real uncertain transition");localState(claim,"uncertain");
        claim=outbox.claimHead(scope,1,1001,now+100000);check(claim!=null&&outbox.recordFailure(scope,claim,true,now+100000),"real review transition");localState(claim,"review");
        check(outbox.discard(scope,outbox.first(scope,1,1001)),"retire isolated review fixture explicitly");
        BChatV2Outbox.Entry nextClaim=outbox.claimHead(scope,1,1001,now+200000);check(nextClaim!=null&&outbox.recordReceipt(scope,nextClaim,700),"synthetic ACK input durably recorded by actual API");localState(nextClaim,"receipt");
        BChatV2Outbox.Entry receipt=outbox.first(scope,1,1001);JSONObject canonical=message(700,7,"same-body");cache.savePage(scope,1,1001,Collections.singletonList(canonical));
        ui(()->call("updateMessageRows",new Class<?>[]{List.class},Collections.singletonList(canonical)));settle();
        check(snapshot().serverCount==1&&snapshot().localCount==1,"no inferred body/hint dedup before retirement");
        check(outbox.acknowledge(scope,receipt),"actual exact receipt retirement");refresh();
        check(snapshot().localCount==0&&adapter.getItemId(0)==700,"canonical positiveID after durable local retirement");
        check("persistent draft".equals(outbox.draft(scope,1,1001)),"draft survives receipt/presentation changes");
        for(int n=0;n<20;++n)outbox.enqueue(scope,1,1001,"bounded pending "+n);refresh();
        List<BChatV2Outbox.Entry> pending=outbox.roomEntries(scope,1,1001);ui(()->call("publishMessageRows",new Class<?>[]{List.class,List.class},copy(original),pending));settle();
        check(snapshot().serverCount==500&&snapshot().localCount==20&&adapter.getItemCount()==520,"actual500+20 bound canonicalprefix/localsuffix");
        Set<Long> stable=new HashSet<>();for(int n=0;n<520;++n)check(stable.add(adapter.getItemId(n))&&(n<500?adapter.getItemId(n)>0:adapter.getItemId(n)<0),"prefix/suffix unique stableID");
        for(BChatV2Outbox.Entry e:pending)check(outbox.discard(scope,e),"remove only own isolated fixture");refresh();journeys.put("EMPTY-localstates-UUID-receipt-canonical-500plus20");}
    ImageView bitmapImage(View root){if(root instanceof ImageView&&((ImageView)root).getDrawable() instanceof BitmapDrawable)return(ImageView)root;if(root instanceof ViewGroup)for(int n=0;n<((ViewGroup)root).getChildCount();++n){ImageView v=bitmapImage(((ViewGroup)root).getChildAt(n));if(v!=null)return v;}return null;}
    void mediaAndIdleAudio()throws Exception{ui(()->{call("updateMessageRows",new Class<?>[]{List.class},copy(original));layout.scrollToPositionWithOffset(420,0);});settle();
        AtomicReference<ImageView> oldImage=new AtomicReference<>();ui(()->{RecyclerView.ViewHolder h=timeline.findViewHolderForAdapterPosition(420);check(h!=null,"cached image holder attached");oldImage.set(bitmapImage(h.itemView));check(oldImage.get()!=null,"actual cached BitmapDrawable shown");});
        List<JSONObject> imageChanged=copy(original);imageChanged.get(420).put("text","image rebind");ui(()->call("updateMessageRows",new Class<?>[]{List.class},imageChanged));settle();check(!oldImage.get().isAttachedToWindow(),"old image detached on real bubble rebind");
        ui(()->{Class<?> m=Class.forName("com.baseer.freshchat.OdooIdentityActivity$MediaRecord"),t=Class.forName("com.baseer.freshchat.OdooIdentityActivity$MediaThumbTarget");Constructor<?> mc=m.getDeclaredConstructor(JSONObject.class);mc.setAccessible(true);Constructor<?> tc=t.getDeclaredConstructor(roomType,m,ImageView.class);tc.setAccessible(true);
            List<Object> queue=field("mediaThumbnailQueue");queue.clear();queue.add(tc.newInstance(room,mc.newInstance(original.get(420).getJSONObject("media")),oldImage.get()));
            WebView unloaded=new WebView(activity);set("web",unloaded);try{call("pumpMediaThumbnails");check(queue.isEmpty()&&!(Boolean)get("mediaReadBusy"),"actual queued detached target discarded before fetch");}finally{set("web",null);unloaded.destroy();}
            set("inlineAudioRoom",room);set("inlineAudioAccount",scope);set("inlineAudioMediaId",10481L);layout.scrollToPositionWithOffset(480,0);
        });settle();View previous=(View)get("inlineAudioPlay");check(previous!=null&&get("inlineAudioPlayer")==null,"synthetic idle owner attaches actual native controls, no player");
        List<JSONObject> audioChanged=copy(original);audioChanged.get(480).put("text","audio rebind");ui(()->call("updateMessageRows",new Class<?>[]{List.class},audioChanged));settle();
        check(get("inlineAudioRoom")==room&&get("inlineAudioAccount")==scope&&(Long)get("inlineAudioMediaId")==10481L,"idle ownership stays account/room/media");
        check(get("inlineAudioPlay")!=previous&&!previous.isAttachedToWindow(),"old audio controls detached/new native controls rebound");
        Object anchor=currentAnchor();ui(()->call("renderMessageWindow",new Class<?>[]{roomType,List.class,boolean.class,long.class,anchor.getClass()},room,copy(original.subList(0,400)),false,0L,anchor));settle();
        check(get("inlineAudioRoom")==null&&(Long)get("inlineAudioMediaId")==0L&&get("inlineAudioPlayer")==null,"removing owning media clears idle owner/player fields");
        screenshot("timeline-ar-dark-font2-media.png");journeys.put("cached-image-recycle-queued-stale-target-idle-audio-owner");}
    void diskDrain()throws Exception{CountDownLatch done=new CountDownLatch(1);BChatStorageRepository.submit(null,()->true,(v,e)->done.countDown());check(done.await(6,TimeUnit.SECONDS),"actual disk lane drained");settle();}
    void invalidationJourneys()throws Exception{for(String kind:new String[]{"rights","company","account","room","rejoin","repository"}){
        fresh();CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);BChatStorageRepository.submit(null,()->{entered.countDown();if(!release.await(5,TimeUnit.SECONDS))throw new IllegalStateException("fixture barrier timeout");return true;},(v,e)->{});
        check(entered.await(5,TimeUnit.SECONDS),"held actual storage lane");AtomicReference<Object> prior=new AtomicReference<>();
        ui(()->{prior.set(get("messageRowSnapshot"));call("refreshLocalRoom",new Class<?>[]{roomType,boolean.class},room,false);
            if(kind.equals("rights"))call("applyPermissionSet",new Class<?>[]{AccountScope.class,permissionType},scope,parsePermission(false,false));
            else if(kind.equals("company"))call("restrictCompanyScope",new Class<?>[]{AccountScope.class,Set.class},scope,Collections.emptySet());
            else if(kind.equals("account")){call("clearChatView");set("account",new AccountScope("https://timeline.invalid","synthetic",8));}
            else if(kind.equals("room")){call("invalidateMessageTimelineOwner");set("selectedRoom",secondRoom);}
            else if(kind.equals("rejoin")){call("invalidateMessageTimelineOwner");Constructor<?> c=roomType.getDeclaredConstructor(long.class,long.class,long.class,String.class);c.setAccessible(true);Object joined=c.newInstance(1L,1L,1002L,"Rejoin");List<Object> rs=field("rooms");rs.clear();rs.add(joined);set("selectedRoom",joined);}
            else {call("invalidateMessageTimelineOwner");BChatStorageRepository.invalidate(scope);}
        });release.countDown();diskDrain();
        check(get("messageRowSnapshot")==null&&timeline.getAdapter()==null,"held old local callback cannot resurrect after "+kind);
        journeys.put("held-storage-invalidate-"+kind);
    }}
    void sameRoomAba()throws Exception{fresh();cache.reconcile(scope,false,Collections.singletonList(new ConnectedHistoryCache.RoomRecord(1,1001,1,"Room","off",1)));cache.savePage(scope,1,1001,original.subList(470,500));AtomicReference<Object> candidate=new AtomicReference<>();CountDownLatch readDone=new CountDownLatch(1);AtomicReference<Throwable> ioFailure=new AtomicReference<>();
        // MAIN deliberately stays in one bounded action: old actual cache read finishes and
        // posts its callback, then showRooms/re-admission happen before that callback can run.
        ui(()->{Constructor<?> constructor=ownerType.getDeclaredConstructor(OdooIdentityActivity.class,roomType);constructor.setAccessible(true);candidate.set(constructor.newInstance(activity,room));
            call("showCachedMessages",new Class<?>[]{roomType,long.class,boolean.class},room,0L,false);
            BChatStorageRepository.submit(null,()->{try{outbox.saveDraft(scope,1,1001,"ABA durable proof",0,99);}catch(Throwable e){ioFailure.set(e);}readDone.countDown();return true;},(v,e)->{});
            check(readDone.await(5,TimeUnit.SECONDS),"old real cache read finished before callback release");
            call("showRooms");set("selectedRoom",room);
            check((Boolean)call("admitMessageTimelineOwner",new Class<?>[]{roomType},room),"same Room legitimate new admission");
            check(!(Boolean)call("admitMessageTimelineOwner",new Class<?>[]{ownerType},candidate.get()),"old candidate rejected by actual admission epoch (ABA)");
            timeline.setAdapter(adapter);
        });check(ioFailure.get()==null,"legitimate storage work committed");diskDrain();
        check("ABA durable proof".equals(outbox.draft(scope,1,1001)),"no DB rollback of legitimate old-lane commit");
        check(get("messageRowSnapshot")==null,"old production cache callback does not publish/followBottom in reentered owner");
        journeys.put("same-room-reentry-real-cache-callback-actual-owner-epoch-DBcommit-retained");}
    JSONObject rectangle(Rect value)throws Exception{return new JSONObject().put("left",value.left).put("top",value.top).put("right",value.right).put("bottom",value.bottom);}
    JSONObject targetGeometry(RecyclerView.ViewHolder holder)throws Exception{
        JSONObject result=new JSONObject().put("holder_present",holder!=null);
        Rect viewport=new Rect();boolean hasViewport=timeline.getGlobalVisibleRect(viewport);
        result.put("viewport",rectangle(viewport)).put("viewport_width",viewport.width()).put("viewport_height",viewport.height())
            .put("viewport_globally_visible",hasViewport).put("full_bubble_inside_viewport",false);
        if(holder==null)return result;
        Field bubbleField=holder.getClass().getDeclaredField("bubble");bubbleField.setAccessible(true);View bubble=(View)bubbleField.get(holder);
        result.put("bubble_present",bubble!=null);if(bubble==null)return result;
        int[] location=new int[2];bubble.getLocationOnScreen(location);
        Rect bounds=new Rect(location[0],location[1],location[0]+bubble.getWidth(),location[1]+bubble.getHeight());
        Rect intersection=new Rect(bounds);boolean intersects=hasViewport&&intersection.intersect(viewport);if(!intersects)intersection.setEmpty();
        return result.put("bubble_full_bounds",rectangle(bounds)).put("bubble_width",bubble.getWidth()).put("bubble_height",bubble.getHeight())
            .put("bubble_shown",bubble.isShown()).put("bubble_attached",bubble.isAttachedToWindow())
            .put("bubble_fits_viewport",bubble.getWidth()<=viewport.width()&&bubble.getHeight()<=viewport.height())
            .put("visible_intersection",rectangle(intersection)).put("visible_intersection_width",intersection.width()).put("visible_intersection_height",intersection.height())
            .put("full_bubble_inside_viewport",hasViewport&&viewport.contains(bounds));
    }
    JSONObject sendPreDrawAttempt(String marker)throws Exception{
        JSONObject attempt=new JSONObject().put("first_visible",layout.findFirstVisibleItemPosition()).put("last_visible",layout.findLastVisibleItemPosition())
            .put("actual_adapter_attached",timeline.getAdapter()==adapter.delegate).put("oracle_accepted",false);
        List<BChatV2Outbox.Entry> locals=field("localTextRows");List<JSONObject> canonical=field("displayedMessages");BChatTimelineRows.Snapshot projected=snapshot();
        for(int n=0;n<locals.size();++n){BChatV2Outbox.Entry entry=locals.get(n);if(!entry.body.equals(marker))continue;
            int position=canonical.size()+n;RecyclerView.ViewHolder holder=timeline.findViewHolderForItemId(-entry.id);
            attempt.put("sqlite_id",entry.id).put("uuid",entry.uuid).put("expected_position",position).put("target_geometry",targetGeometry(holder));
            if(holder==null)return attempt.put("rejection","holder_absent");
            attempt.put("holder_stable_id",holder.getItemId()).put("binding_position",holder.getBindingAdapterPosition());
            if(holder.getBindingAdapterPosition()!=position||holder.getItemId()!=-entry.id||projected==null||position>=projected.rows.size())return attempt.put("rejection","holder_or_projection_identity");
            BChatTimelineRows.Row row=projected.rows.get(position);
            if(row.local==null||row.local.sqliteId!=entry.id||!row.local.uuid.equals(entry.uuid)||row.key.stableId()!=-entry.id)return attempt.put("rejection","exact_local_projection_identity");
            attempt.put("snapshot_key_stable_id",row.key.stableId()).put("server_count",projected.serverCount).put("local_count",projected.localCount);
            JSONObject geometry=attempt.getJSONObject("target_geometry");
            // Identical oracle to the original RED: full attached/shown positive-size
            // bubble must be contained in the actual globally visible viewport.
            if(!geometry.optBoolean("bubble_present")||!geometry.optBoolean("bubble_shown")||!geometry.optBoolean("bubble_attached")
                    ||geometry.optInt("bubble_width")<=0||geometry.optInt("bubble_height")<=0||!geometry.optBoolean("viewport_globally_visible"))return attempt.put("rejection","bubble_or_viewport_not_ready");
            if(!geometry.getBoolean("full_bubble_inside_viewport"))return attempt.put("rejection","full_containment");
            return attempt.put("oracle_accepted",true);
        }
        return attempt.put("rejection","matching_local_not_published");
    }
    JSONArray matchingEntries(List<BChatV2Outbox.Entry> entries,String marker)throws Exception{JSONArray result=new JSONArray();for(BChatV2Outbox.Entry entry:entries)if(entry.body.equals(marker))result.put(new JSONObject()
        .put("sqlite_id",entry.id).put("uuid",entry.uuid).put("body",entry.body).put("state",entry.state).put("room_id",entry.roomId).put("membership_id",entry.membershipId));return result;}
    JSONObject sendDiagnostics(String marker)throws Exception{
        JSONObject result=new JSONObject().put("durable_entries",matchingEntries(outbox.roomEntries(scope,1,1001),marker));
        ui(()->{
            result.put("account_is_fixture",get("account")==scope).put("selected_room_is_fixture",get("selectedRoom")==room)
                .put("epoch",get("epoch")).put("history_global_generation",get("historyGlobalGeneration"))
                .put("repository_generation",BChatStorageRepository.generation(scope)).put("receipt_storage_generation",get("receiptStorageGeneration"))
                .put("local_read_busy",get("localReadBusy")).put("text_enqueue_busy",get("textEnqueueBusy"))
                .put("v2_busy",get("v2Busy")).put("web_absent",get("web")==null)
                .put("composer_text",((EditText)get("messageInput")).getText().toString())
                .put("send_enabled",((View)get("sendButton")).isEnabled()).put("notice",((TextView)get("chatNotice")).getText().toString());
            Object owner=get("messageWindowOwner");if(owner!=null){Method current=owner.getClass().getDeclaredMethod("current");current.setAccessible(true);result.put("actual_owner_current",current.invoke(owner));}
            List<BChatV2Outbox.Entry> locals=field("localTextRows");result.put("local_rows",matchingEntries(locals,marker));
            Object local=get("roomLocal");if(local!=null){Field rows=local.getClass().getDeclaredField("text");rows.setAccessible(true);
                @SuppressWarnings("unchecked") List<BChatV2Outbox.Entry> entries=(List<BChatV2Outbox.Entry>)rows.get(local);result.put("room_local_text",matchingEntries(entries,marker));}
            BChatTimelineRows.Snapshot projected=snapshot();JSONArray matching=new JSONArray();
            if(projected!=null){result.put("server_count",projected.serverCount).put("local_count",projected.localCount).put("render_owner",projected.scope.renderOwner);
                for(int p=0;p<projected.rows.size();++p){BChatTimelineRows.Row row=projected.rows.get(p);if(row.local!=null&&row.local.body.equals(marker))matching.put(new JSONObject()
                    .put("position",p).put("sqlite_id",row.local.sqliteId).put("uuid",row.local.uuid).put("stable_id",row.key.stableId())
                    .put("target_geometry",targetGeometry(timeline.findViewHolderForItemId(-row.local.sqliteId))));}}
            result.put("projected_matches",matching).put("first_visible",layout.findFirstVisibleItemPosition()).put("last_visible",layout.findLastVisibleItemPosition())
                .put("can_scroll_down",timeline.canScrollVertically(1)).put("timeline_height",timeline.getHeight());
            JSONArray attached=new JSONArray();for(int n=0;n<timeline.getChildCount();++n){RecyclerView.ViewHolder holder=timeline.getChildViewHolder(timeline.getChildAt(n));attached.put(new JSONObject().put("stable_id",holder.getItemId()).put("position",holder.getBindingAdapterPosition()));}
            result.put("attached_holders",attached);Rect viewport=new Rect();timeline.getGlobalVisibleRect(viewport);result.put("viewport",rectangle(viewport));
        });return result;
    }
    void sendVisibility(JSONObject result)throws Exception{
        // Dedicated functional case, not the 799-assertion suite or a latency experiment.
        check(outbox.roomEntries(scope,1,1001).isEmpty(),"dedicated send fixture starts with no pending rows");
        refresh();String marker="اختبار إرسال "+UUID.randomUUID().toString();
        ui(()->{
            check((Boolean)call("localMatches",new Class<?>[]{roomType},room),"actual room-local admission ready before send");
            ((EditText)get("messageInput")).setText(marker);call("updatePendingUi");
        });settle();
        ui(()->layout.scrollToPosition(adapter.getItemCount()-1));settle();
        JSONObject proof=new JSONObject().put("input_marker",marker).put("transport_fixture","existing v2Busy=true, web=null; actual send admission/enqueue/publish not overridden")
            .put("adapter_fixture","actual production messageAdapter attached before setup/publish/input/bottom/click; counting wrapper not attached in this dedicated case")
            .put("oracle_criterion","unchanged: exact SQLiteID/UUID projection and stable holder identity; attached/shown positive-size FULL bubble inside actual viewport")
            .put("post_click_scripted_scroll",false).put("post_click_scripted_refresh_or_publish",false).put("latency_measured",false);
        result.put("send_visibility",proof);
        AtomicReference<JSONObject> observed=new AtomicReference<>();AtomicReference<Throwable> listenerFailure=new AtomicReference<>();
        AtomicReference<JSONObject> lastAttempt=new AtomicReference<>();JSONArray attempts=new JSONArray();AtomicInteger attemptCount=new AtomicInteger();
        CountDownLatch visible=new CountDownLatch(1);AtomicBoolean clicked=new AtomicBoolean();
        ViewTreeObserver.OnPreDrawListener listener=()->{
            if(!clicked.get()||observed.get()!=null||listenerFailure.get()!=null)return true;
            try{
                JSONObject attempt=sendPreDrawAttempt(marker);lastAttempt.set(attempt);if(attemptCount.incrementAndGet()<=128)attempts.put(attempt);
                if(attempt.getBoolean("oracle_accepted")){observed.set(attempt);visible.countDown();}
            }catch(Throwable failure){listenerFailure.set(failure);visible.countDown();}
            return true;
        };
        ui(()->{
            check(timeline.isShown()&&timeline.getHeight()>0&&!timeline.canScrollVertically(1),"actual bottom prepared before click");
            check(timeline.getAdapter()==adapter.delegate,"actual production adapter attached before send");
            check(layout.findLastVisibleItemPosition()==adapter.getItemCount()-1,"last pre-send row actually visible");
            View button=(View)get("sendButton");check(button.isShown()&&button.isEnabled(),"actual send button enabled, no forced admission");
            proof.put("pre_click_last_position",layout.findLastVisibleItemPosition()).put("pre_click_item_count",adapter.getItemCount()).put("pre_click_bottom",true);
            timeline.getViewTreeObserver().addOnPreDrawListener(listener);clicked.set(true);check(button.performClick(),"actual send button listener invoked");
        });
        boolean signalled=visible.await(8,TimeUnit.SECONDS);
        ui(()->timeline.getViewTreeObserver().removeOnPreDrawListener(listener));
        proof.put("pre_draw_attempt_count",attemptCount.get()).put("pre_draw_attempts_first128",attempts)
            .put("last_pre_draw_attempt",lastAttempt.get()==null?JSONObject.NULL:lastAttempt.get()).put("diagnostics",sendDiagnostics(marker));
        if(listenerFailure.get()!=null)throw new AssertionError("PreDraw oracle failed",listenerFailure.get());
        check(signalled&&observed.get()!=null,"new local UUID bubble observed in actual preDraw without post-click scroll");
        JSONObject frame=observed.get();proof.put("actual_pre_draw",frame);boolean durable=false;
        for(BChatV2Outbox.Entry entry:outbox.roomEntries(scope,1,1001))if(entry.id==frame.getLong("sqlite_id")&&entry.uuid.equals(frame.getString("uuid"))&&entry.body.equals(marker)){
            proof.put("verified_sqlite_entry",new JSONObject().put("sqlite_id",entry.id).put("uuid",entry.uuid).put("body",entry.body).put("state",entry.state));
            check(entry.state.equals("queued"),"blocked transport leaves real durable entry queued");durable=true;
        }
        check(durable,"exact observed SQLite ID/UUID/body durably present in actual outbox");
        ui(()->check(((EditText)get("messageInput")).getText().length()==0,"actual composer CAS cleared after durable enqueue"));
        check((Boolean)get("v2Busy")&&get("web")==null,"no HTTP transport enabled to make case pass");
        screenshot("timeline-send-visibility.png");journeys.put("actual-button-SQLite-enqueue-exactUUID-stableID-preDraw-visible-no-postclick-scroll");
    }
    void screenshot(String name)throws Exception{Bitmap bitmap=getUiAutomation().takeScreenshot();check(bitmap!=null,"actual screenshot");try(FileOutputStream output=context.openFileOutput(name,0)){bitmap.compress(Bitmap.CompressFormat.PNG,100,output);}finally{bitmap.recycle();}}
}

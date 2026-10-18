package com.baseer.freshchat;

import android.content.*;
import android.content.res.Configuration;
import android.graphics.Rect;
import android.os.*;
import android.view.*;
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

/** Five bounded position groups. No latency, auth, HTTP, ACK or playback claim. */
public final class TimelinePositionInstrumentation extends TimelinePositionFixture {
    static final String POSITION_PACKAGE="com.baseer.bchat.timeline.position.test";
    final JSONArray cases=new JSONArray(),executions=new JSONArray();
    String positionSelection="all";int completedCases;
    Scenario active;JSONObject preparedWindow;
    final class Barrier implements AutoCloseable {
        final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        final AtomicReference<Throwable> failure=new AtomicReference<>();
        final AtomicBoolean expired=new AtomicBoolean(),exited=new AtomicBoolean(),intendedRelease=new AtomicBoolean();
        final AtomicLong enteredAt=new AtomicLong();
        Barrier()throws Exception{
            BChatStorageRepository.submit(null,()->{
                enteredAt.set(SystemClock.elapsedRealtime());entered.countDown();
                try{if(!release.await(12,TimeUnit.SECONDS)){expired.set(true);throw new IllegalStateException("bounded fixture disk hold expired");}return true;}
                catch(Exception error){failure.compareAndSet(null,error);throw error;}
                finally{exited.set(true);}
            },(v,e)->{if(e!=null)failure.compareAndSet(null,e);});
            check(entered.await(5,TimeUnit.SECONDS),"actual storage lane held before enqueue");
        }
        void requireHeld(String stage){
            if(enteredAt.get()>0&&SystemClock.elapsedRealtime()-enteredAt.get()>=12000){expired.set(true);failure.compareAndSet(null,new IllegalStateException("fixture hold deadline reached before "+stage));}
            check(entered.getCount()==0&&release.getCount()==1&&!exited.get()&&!expired.get()&&failure.get()==null,"actual lane still held: "+stage);
        }
        void releaseForContinuation(){requireHeld("intended release");intendedRelease.set(true);release.countDown();}
        void requireReleasedHealthy(){check(intendedRelease.get()&&exited.get()&&!expired.get()&&failure.get()==null,"barrier released normally, never expired/interrupted/failed");}
        JSONObject status()throws Exception{return new JSONObject().put("entered",entered.getCount()==0).put("release_signalled",release.getCount()==0)
            .put("intended_release",intendedRelease.get()).put("worker_exited",exited.get()).put("expired",expired.get())
            .put("failure",failure.get()==null?JSONObject.NULL:failure.get().toString());}
        @Override public void close(){release.countDown();}
    }
    final class Scenario implements ViewTreeObserver.OnPreDrawListener {
        final JSONObject result=new JSONObject();final JSONArray frames=new JSONArray();
        final AtomicReference<Throwable> failure=new AtomicReference<>();
        final String marker="اختبار موضع "+UUID.randomUUID();
        long target,anchorId,offset;boolean released,invalidated,actionCompletedWhileHeld,sourceRequestedAnchor,sourceRestoredAnchor;int frameCount;Barrier barrier;
        JSONObject last,referenceLayout,referenceTarget;
        Scenario(String name)throws Exception{result.put("name",name).put("input_marker",marker).put("passed",false).put("position_action_completed_while_held",false).put("post_click_rescue_scroll_refresh_publish_admit",false);cases.put(result);}
        @Override public boolean onPreDraw(){try{
            JSONObject frame=new JSONObject().put("after_release",released).put("position_intent",get("messagePositionIntentSerial"))
                .put("jump_serial",get("messageJumpSerial")).put("render_serial",get("messageRenderSerial")).put("adapter_is_actual",timeline.getAdapter()==adapter.delegate)
                .put("first_visible",layout.findFirstVisibleItemPosition()).put("last_visible",layout.findLastVisibleItemPosition()).put("recycler_layout",recyclerLayout());
            Object owner=get("messageWindowOwner");boolean current=false;
            if(owner!=null){Method method=owner.getClass().getDeclaredMethod("current");method.setAccessible(true);current=(Boolean)method.invoke(owner);}
            frame.put("actual_owner_current",current).put("snapshot_present",get("messageRowSnapshot")!=null);
            if(target>0){Object anchor=call("currentScrollAnchor");frame.put("anchor_id",anchorField(anchor,"messageId")).put("anchor_offset",anchorField(anchor,"offset"))
                .put("target_id",target).put("target_geometry",targetGeometry(timeline.findViewHolderForItemId(target)));}
            if(sourceRequestedAnchor)frame.put("source_request_facts",sourceRequestFacts(this));
            frame.put("local_projection",sendPreDrawAttempt(marker));
            last=frame;++frameCount;if(frameCount<=128)frames.put(frame);
        }catch(Throwable error){failure.compareAndSet(null,error);}return true;}
        void start(){activity.getWindow().getDecorView().getViewTreeObserver().addOnPreDrawListener(this);}
        void stop(){activity.getWindow().getDecorView().getViewTreeObserver().removeOnPreDrawListener(this);}
    }
    @Override public void onCreate(Bundle arguments){if(arguments!=null)positionSelection=arguments.getString("selection","all");super.onCreate(arguments);}
    JSONArray requestedCases(){return positionSelection.equals("newer-remaining")
        ?new JSONArray(Arrays.asList("late-enqueue-with-actual-cached-newer","late-enqueue-after-actual-owner-invalidation"))
        :positionSelection.equals("cached-remaining")
        ?new JSONArray(Arrays.asList("late-enqueue-with-actual-cached-older","late-enqueue-with-actual-cached-newer","late-enqueue-after-actual-owner-invalidation"))
        :new JSONArray(Arrays.asList("late-enqueue-then-known-present-jump","present-jump-before-layout-sendcapture","late-enqueue-after-real-user-gesture","late-enqueue-with-actual-cached-older","late-enqueue-with-actual-cached-newer","late-enqueue-after-actual-owner-invalidation"));}
    void execute(String name,Work work)throws Exception{
        int before=checks,scenariosBefore=cases.length();JSONObject execution=new JSONObject().put("name",name).put("checks_before",before).put("passed",false);executions.put(execution);
        try{work.run();++completedCases;execution.put("passed",true);}
        finally{execution.put("checks_after",checks).put("checks_executed",checks-before).put("scenario_records_before",scenariosBefore).put("scenario_records_after",cases.length());}
    }
    @Override public void onStart(){Bundle status=new Bundle();JSONObject result=new JSONObject();boolean passed=false;
        try{
            check(positionSelection.equals("all")||positionSelection.equals("cached-remaining")||positionSelection.equals("newer-remaining"),"explicit bounded case selection");
            context=getTargetContext();check(context.getPackageName().equals(POSITION_PACKAGE),"isolated position package");check(Build.VERSION.SDK_INT==35,"actual SDK35");
            check(!BuildConfig.BCHAT_PUSH_ENABLED&&BuildConfig.BCHAT_ORIGIN.equals("https://timeline.invalid"),"declared invalid transport origin");
            check(context.getPackageManager().checkPermission("android.permission.INTERNET",POSITION_PACKAGE)!=0,"no INTERNET permission");
            context.getSharedPreferences("bchat-appearance-v1",0).edit().putString("theme","dark").putInt("body_sp",16).commit();
            context.getSharedPreferences("bchat-local-settings-v1",0).edit().putString("interface-language","ar").commit();
            activity=(OdooIdentityActivity)startActivitySync(new Intent(context,OdooIdentityActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            await("local initialization",()->{try{return get("messageScroll")!=null&&get("historyCache")!=null;}catch(Exception e){return false;}});
            SystemClock.sleep(350);ui(()->call("releaseWeb"));settle();
            Configuration cfg=activity.getResources().getConfiguration();result.put("configuration",new JSONObject().put("fontScale",cfg.fontScale).put("locale",cfg.getLocales().get(0).toLanguageTag()).put("uiMode",cfg.uiMode).put("dark",ChatAppearance.dark(activity)));
            check(cfg.fontScale==2f&&cfg.getLocales().get(0).getLanguage().equals("ar")&&ChatAppearance.dark(activity),"forced AR dark font2 (not preference restoration)");
            selectedCase="send-visibility";install();
            if(positionSelection.equals("all")){
                execute("late-enqueue-then-known-present-jump",()->knownJump(false));execute("present-jump-before-layout-sendcapture",()->knownJump(true));execute("late-enqueue-after-real-user-gesture",this::gesture);
            }
            if(!positionSelection.equals("newer-remaining"))execute("late-enqueue-with-actual-cached-older",this::cachedOlder);
            execute("late-enqueue-with-actual-cached-newer",this::cachedNewer);execute("late-enqueue-after-actual-owner-invalidation",this::invalidateOwner);
            check(get("web")==null,"no transport recreated");passed=true;
        }catch(Throwable error){try{result.put("failure",error.toString()).put("stack",new JSONArray(Arrays.asList(error.getStackTrace())));}catch(Exception ignored){}}
        try{
            if(active!=null)finishDiagnostics(active);
            result.put("passed",passed).put("checks",checks).put("selection",positionSelection).put("requested_case_names",requestedCases()).put("requested_case_count",requestedCases().length())
                .put("started_case_count",executions.length()).put("completed_case_count",completedCases).put("case_execution_counts",executions).put("cases",cases)
                .put("base_commit",BuildConfig.BCHAT_SOURCE_COMMIT).put("activity_sha256",BuildConfig.BCHAT_TARGET_ACTIVITY_SHA)
                .put("scope","Actual unmodified Activity/AndroidX/SQLite/owner/adapter/preDraw. Synthetic identity/permissions/canonical setup; actual enqueue held only by bounded repository executor barrier. No HTTP/auth/receipt truth/benchmark/799 rerun.")
                .put("foundation","E85A test-only fixture archived; only its class declaration renamed/non-final in compiled copy. No product transformation and no original fixture edits.")
                .put("separate_seam","Pending 2GET commit and latest initial-admission sequencing belong to the explicitly adapted C16 source-extraction fixture, not native HTTP here.");
            try(FileOutputStream file=context.openFileOutput("timeline-position-results.json",0)){file.write(result.toString(2).getBytes(StandardCharsets.UTF_8));}
            status.putString("stream",(passed?"PASS ":"FAIL ")+checks+" bounded position checks; "+result.optString("failure","")+"\n");
        }catch(Throwable error){passed=false;status.putString("stream","FAIL results "+error);}
        if(activity!=null)ui(()->activity.finish());finish(passed?-1:1,status);
    }
    void prepare(int first,int last)throws Exception{
        diskDrain();for(BChatV2Outbox.Entry entry:outbox.roomEntries(scope,1,1001))check(outbox.discard(scope,entry),"cleanup only own isolated prior entry");
        fresh();if(first!=0||last!=500){Object anchor=currentAnchor();ui(()->call("renderMessageWindow",new Class<?>[]{roomType,List.class,boolean.class,long.class,anchor.getClass()},room,copy(original.subList(first,last)),true,0L,anchor));settle();}
        // A synthetic window must have the same cursor/historical/control state as
        // the actual cache callbacks, before composer/reference/click. Never let
        // a previous case's cursor/history leak through the foundation's fresh().
        long[] ids=new long[2];ui(()->{List<JSONObject> current=field("displayedMessages");check(!current.isEmpty(),"actual canonical fixture window nonempty");ids[0]=current.get(0).getLong("id");ids[1]=current.get(current.size()-1).getLong("id");});
        boolean hasOlder=cache.hasOlder(scope,1,1001,ids[0]),hasNewer=cache.hasNewer(scope,1,1001,ids[1]);
        ui(()->{
            set("nextBeforeId",hasOlder?ids[0]:0L);set("historicalWindow",hasNewer);set("olderPageLoading",false);set("olderPageFailed",false);
            call("updateOlderControl");visibility("newerControl",hasNewer);
            check(((Long)get("nextBeforeId"))==(hasOlder?ids[0]:0L)&&(Boolean)get("historicalWindow")==hasNewer,"cache-derived cursor/historical precondition applied");
        });settle();
        ui(()->{
            check(timeline.isShown()&&timeline.getWidth()>0&&timeline.getHeight()>0&&!timeline.isLayoutRequested()&&!timeline.isComputingLayout()&&!timeline.hasPendingAdapterUpdates(),"window controls and positive actual layout settled before composer");
            boolean manual=hasNewer||((List<?>)get("displayedMessages")).size()>=500;
            check(((View)get("olderControl")).getVisibility()==(hasOlder&&manual?View.VISIBLE:View.GONE),"actual older control agrees with seeded manual historical window");
            check(((View)get("newerControl")).getVisibility()==(hasNewer?View.VISIBLE:View.GONE),"newer control agrees with cache-derived historical window");
            preparedWindow=new JSONObject().put("first_id",ids[0]).put("last_id",ids[1]).put("actual_cache_has_older",hasOlder).put("actual_cache_has_newer",hasNewer)
                .put("next_before_id",get("nextBeforeId")).put("historical_window",get("historicalWindow")).put("loading",get("olderPageLoading")).put("failed",get("olderPageFailed"))
                .put("settled_layout_before_composer",recyclerLayout());
        });
        refresh();ui(()->check((Boolean)call("localMatches",new Class<?>[]{roomType},room),"actual ready local binding before action"));
    }
    void composer(Scenario scenario)throws Exception{
        scenario.result.put("window_precondition",preparedWindow);
        ui(()->{((EditText)get("messageInput")).setText(scenario.marker);call("updatePendingUi");});settle();ui(()->layout.scrollToPosition(adapter.delegate.getItemCount()-1));settle();
        ui(()->{check(timeline.getAdapter()==adapter.delegate,"actual production adapter");check(timeline.isShown()&&timeline.isAttachedToWindow()&&timeline.getWidth()>0&&timeline.getHeight()>0,"positive shown attached viewport");
            check(!timeline.canScrollVertically(1)&&layout.findLastVisibleItemPosition()==adapter.delegate.getItemCount()-1,"bottom before intended action");
            check(!timeline.hasPendingAdapterUpdates()&&!timeline.isComputingLayout()&&!timeline.isLayoutRequested(),"settled adapter/layout before action");
            scenario.result.put("pre_action_bottom",true).put("pre_action_last",layout.findLastVisibleItemPosition());scenario.start();});
    }
    void click()throws Exception{View button=(View)get("sendButton");check(button.isShown()&&button.isEnabled(),"actual send button enabled");check(button.performClick(),"actual send listener invoked");}
    JSONObject recyclerLayout()throws Exception{
        int[] location=new int[2];timeline.getLocationOnScreen(location);Rect visible=new Rect();boolean hasVisible=timeline.getGlobalVisibleRect(visible);
        Rect laidOut=new Rect(location[0],location[1],location[0]+timeline.getWidth(),location[1]+timeline.getHeight());
        Rect inner=new Rect(laidOut.left+timeline.getPaddingLeft(),laidOut.top+timeline.getPaddingTop(),laidOut.right-timeline.getPaddingRight(),laidOut.bottom-timeline.getPaddingBottom());
        Rect visibleInner=new Rect(inner);if(!hasVisible||!visibleInner.intersect(visible))visibleInner.setEmpty();
        return new JSONObject().put("width",timeline.getWidth()).put("height",timeline.getHeight())
            .put("padding_left",timeline.getPaddingLeft()).put("padding_top",timeline.getPaddingTop()).put("padding_right",timeline.getPaddingRight()).put("padding_bottom",timeline.getPaddingBottom())
            .put("inner_width",inner.width()).put("inner_height",inner.height()).put("laid_out_bounds",rectangle(laidOut)).put("laid_out_inner_bounds",rectangle(inner))
            .put("global_visible",hasVisible).put("global_visible_bounds",rectangle(visible)).put("visible_inner_bounds",rectangle(visibleInner))
            .put("older_control",controlGeometry("olderControl")).put("newer_control",controlGeometry("newerControl"));
    }
    JSONObject controlGeometry(String name)throws Exception{View control=(View)get(name);int[] location=new int[2];control.getLocationOnScreen(location);
        return new JSONObject().put("visibility",control.getVisibility()).put("shown",control.isShown()).put("width",control.getWidth()).put("height",control.getHeight())
            .put("screen_bounds",rectangle(new Rect(location[0],location[1],location[0]+control.getWidth(),location[1]+control.getHeight())));}
    void rememberLayoutReference(Scenario scenario,String offsetKind)throws Exception{
        scenario.referenceLayout=recyclerLayout();scenario.referenceTarget=targetGeometry(timeline.findViewHolderForItemId(scenario.target));
        check(scenario.referenceLayout.getInt("inner_height")>0&&scenario.referenceLayout.getInt("inner_width")>0,"positive actual laid-out inner RecyclerView reference");
        check(scenario.referenceTarget.optBoolean("holder_present")&&scenario.referenceTarget.optBoolean("bubble_attached")&&scenario.referenceTarget.optBoolean("bubble_shown")&&scenario.referenceTarget.optInt("visible_intersection_height")>0,"intended canonical target visible at reference");
        scenario.result.put("reference_recycler_layout",scenario.referenceLayout).put("reference_target_geometry",scenario.referenceTarget).put("reference_offset_kind",offsetKind);
    }
    void beginHeldAction(Scenario scenario,Barrier barrier)throws Exception{scenario.barrier=barrier;barrier.requireHeld("position action start");scenario.result.put("barrier_at_action_start",barrier.status());}
    void endHeldAction(Scenario scenario,Barrier barrier)throws Exception{barrier.requireHeld("position action complete");scenario.actionCompletedWhileHeld=true;scenario.result.put("position_action_completed_while_held",true).put("barrier_at_action_end",barrier.status());}
    void rememberAnchor(Scenario scenario)throws Exception{Object anchor=call("currentScrollAnchor");scenario.anchorId=anchorField(anchor,"messageId");if(scenario.target==0)scenario.target=scenario.anchorId;scenario.offset=anchorField(anchor,"offset");check(scenario.anchorId>0,"intended canonical anchor");scenario.result.put("expected_anchor_id",scenario.anchorId).put("expected_anchor_offset",scenario.offset).put("expected_target_id",scenario.target);rememberLayoutReference(scenario,scenario.sourceRestoredAnchor?"source-restored-pre-release-observed-offset":"actual pre-release canonical anchor");}
    void afterRelease(Scenario scenario,Barrier barrier)throws Exception{
        check(scenario.actionCompletedWhileHeld,"position action actually completed before enqueue release");barrier.requireHeld("before continuation");scenario.result.put("barrier_before_release",barrier.status());
        scenario.released=true;barrier.releaseForContinuation();diskDrain();barrier.requireReleasedHealthy();await("actual enqueue/local callbacks",()->{try{return!(Boolean)get("textEnqueueBusy")&&!(Boolean)get("localReadBusy");}catch(Exception e){return false;}});diskDrain();barrier.requireReleasedHealthy();
        // Two observation-only animation boundaries let earlier product posts/layout finish.
        // Neither scroll, refresh, bind, owner admission nor publication is invoked here.
        CountDownLatch frames=new CountDownLatch(1);ui(()->activity.getWindow().getDecorView().postOnAnimation(()->activity.getWindow().getDecorView().postOnAnimation(frames::countDown)));
        check(frames.await(3,TimeUnit.SECONDS),"bounded native animation observation");settle();
        finishDiagnostics(scenario);if(scenario.failure.get()!=null)throw new AssertionError("actual preDraw observation",scenario.failure.get());
        check(scenario.last!=null,"actual preDraw captured");
        if(scenario.invalidated){check(get("messageRowSnapshot")==null&&timeline.getAdapter()==null,"late enqueue cannot republish invalid owner");}
        else{
            JSONObject last=scenario.last;check(last.getBoolean("after_release")&&last.getBoolean("actual_owner_current")&&last.getBoolean("adapter_is_actual"),"post-release frame has actual current owner/adapter");
            check(last.getLong("anchor_id")==scenario.anchorId&&last.getLong("target_id")==scenario.target,"exact canonical anchor and intended stable target IDs retained");
            requirePositionGeometry(scenario,last);
        }
        int durable=0;BChatV2Outbox.Entry exact=null;for(BChatV2Outbox.Entry entry:outbox.roomEntries(scope,1,1001))if(entry.body.equals(scenario.marker)){++durable;exact=entry;scenario.result.put("durable_entry",new JSONObject().put("sqlite_id",entry.id).put("uuid",entry.uuid).put("state",entry.state));}
        check(durable==1,"exact own committed entry retained once, no business rollback");
        if(!scenario.invalidated)requireActualLocalIdentity(scenario,exact);
        check((Boolean)get("v2Busy")&&get("web")==null,"transport remains blocked");
    }
    Rect fromRectangle(JSONObject value)throws Exception{return new Rect(value.getInt("left"),value.getInt("top"),value.getInt("right"),value.getInt("bottom"));}
    JSONObject sourceRequestFacts(Scenario scenario)throws Exception{
        List<JSONObject> canonical=field("displayedMessages");int count=adapter.delegate.getItemCount();
        RecyclerView.ViewHolder holder=timeline.findViewHolderForItemId(scenario.target);
        JSONObject facts=new JSONObject().put("requested_offset",scenario.offset).put("first_canonical_id",canonical.isEmpty()?0:canonical.get(0).optLong("id"))
            .put("canonical_count",canonical.size()).put("following_canonical_id",canonical.size()>1?canonical.get(1).optLong("id"):0)
            .put("actual_adapter_attached",timeline.getAdapter()==adapter.delegate).put("adapter_count",count)
            .put("first_adapter_id",count>0?adapter.delegate.getItemId(0):0).put("following_adapter_id",count>1?adapter.delegate.getItemId(1):0)
            .put("target_binding_position",holder==null?RecyclerView.NO_POSITION:holder.getBindingAdapterPosition())
            .put("target_binding_adapter_actual",holder!=null&&holder.getBindingAdapter()==adapter.delegate).put("target_stable_id",holder==null?0:holder.getItemId())
            .put("orientation",layout.getOrientation()).put("reverse_layout",layout.getReverseLayout()).put("stack_from_end",layout.getStackFromEnd())
            .put("first_visible_position",layout.findFirstVisibleItemPosition()).put("last_visible_position",layout.findLastVisibleItemPosition())
            .put("can_scroll_up",timeline.canScrollVertically(-1)).put("can_scroll_down",timeline.canScrollVertically(1)).put("item_decoration_count",timeline.getItemDecorationCount());
        if(holder==null)return facts;
        View item=holder.itemView;RecyclerView.LayoutParams params=(RecyclerView.LayoutParams)item.getLayoutParams();Rect decorated=new Rect();layout.getDecoratedBoundsWithMargins(item,decorated);
        Field bubbleField=holder.getClass().getDeclaredField("bubble");bubbleField.setAccessible(true);View bubble=(View)bubbleField.get(holder);
        facts.put("decorated_top",layout.getDecoratedTop(item)).put("decorated_bounds_with_margins",rectangle(decorated)).put("item_top",item.getTop())
            .put("margin_left",params.leftMargin).put("margin_top",params.topMargin).put("margin_right",params.rightMargin).put("margin_bottom",params.bottomMargin)
            .put("decoration_left",layout.getLeftDecorationWidth(item)).put("decoration_top",layout.getTopDecorationHeight(item))
            .put("decoration_right",layout.getRightDecorationWidth(item)).put("decoration_bottom",layout.getBottomDecorationHeight(item))
            .put("item_padding_top",item.getPaddingTop()).put("item_translation_y",item.getTranslationY()).put("bubble_present",bubble!=null);
        if(bubble!=null){int[] bubbleLocation=new int[2],recyclerLocation=new int[2];bubble.getLocationOnScreen(bubbleLocation);timeline.getLocationOnScreen(recyclerLocation);
            facts.put("bubble_top_in_recycler",bubbleLocation[1]-recyclerLocation[1]).put("bubble_top_in_item",bubble.getTop()).put("bubble_translation_y",bubble.getTranslationY())
                .put("bubble_only_direct_child",item instanceof ViewGroup&&((ViewGroup)item).getChildCount()==1&&((ViewGroup)item).getChildAt(0)==bubble&&bubble.getParent()==item);}
        return facts;
    }
    boolean firstContentStartPolicy(Scenario scenario,JSONObject facts)throws Exception{
        // Select from the source request, identity, layout configuration and following
        // content ONLY. No observed offset, top, visibility or scroll result selects it.
        return scenario.sourceRequestedAnchor&&scenario.offset>0&&facts.getLong("first_canonical_id")==scenario.target
            &&facts.getBoolean("actual_adapter_attached")&&facts.getInt("target_binding_position")==0&&facts.getBoolean("target_binding_adapter_actual")
            &&facts.getLong("target_stable_id")==scenario.target&&facts.getLong("first_adapter_id")==scenario.target
            &&facts.getInt("orientation")==RecyclerView.VERTICAL&&!facts.getBoolean("reverse_layout")&&facts.getBoolean("stack_from_end")
            &&facts.getInt("canonical_count")>1&&facts.getInt("adapter_count")>1&&facts.getLong("following_canonical_id")>scenario.target
            &&facts.getLong("following_adapter_id")==facts.getLong("following_canonical_id");
    }
    void requireContentStartBoundary(JSONObject facts,JSONObject after,Rect bubbleBounds)throws Exception{
        int padding=after.getInt("padding_top"),recyclerTop=fromRectangle(after.getJSONObject("laid_out_bounds")).top;
        check(facts.getInt("item_decoration_count")==0,"first content-start has no RecyclerView decoration");
        for(String edge:new String[]{"left","top","right","bottom"})check(facts.getInt("margin_"+edge)==0&&facts.getInt("decoration_"+edge)==0,"no item margin/decoration "+edge+" confound");
        check(facts.getBoolean("bubble_present")&&facts.getBoolean("bubble_only_direct_child")&&facts.getInt("bubble_top_in_item")==0&&facts.getInt("item_padding_top")==0,"no separate header or padding before target bubble");
        check(facts.getDouble("item_translation_y")==0&&facts.getDouble("bubble_translation_y")==0,"no translated item/bubble position confound");
        check(facts.getInt("decorated_top")==padding&&fromRectangle(facts.getJSONObject("decorated_bounds_with_margins")).top==padding,"decorated first item starts at RecyclerView padding");
        check(facts.getInt("item_top")==padding&&facts.getInt("bubble_top_in_recycler")==padding&&bubbleBounds.top-recyclerTop==padding,"actual item and target bubble start at RecyclerView padding");
        check(facts.getInt("first_visible_position")==0&&!facts.getBoolean("can_scroll_up")&&facts.getBoolean("can_scroll_down")
            &&facts.getInt("last_visible_position")<facts.getInt("adapter_count")-1,"first content-start is top-clamped with following scrollable content and end not visible");
    }
    void requirePositionGeometry(Scenario scenario,JSONObject frame)throws Exception{
        JSONObject before=scenario.referenceLayout,after=frame.getJSONObject("recycler_layout"),geometry=frame.getJSONObject("target_geometry");
        check(before!=null&&scenario.referenceTarget!=null,"explicit actual layout/target reference recorded");
        check(before.getInt("width")==after.getInt("width")&&before.getInt("inner_width")==after.getInt("inner_width"),"RecyclerView width unchanged for height-only oracle");
        for(String key:new String[]{"padding_left","padding_top","padding_right","padding_bottom"})check(before.getInt(key)==after.getInt(key),"RecyclerView "+key+" unchanged");
        Rect beforeVisible=fromRectangle(before.getJSONObject("global_visible_bounds")),afterVisible=fromRectangle(after.getJSONObject("global_visible_bounds"));
        check(beforeVisible.top==afterVisible.top&&fromRectangle(before.getJSONObject("laid_out_bounds")).top==fromRectangle(after.getJSONObject("laid_out_bounds")).top,"global viewport and actual RecyclerView top unchanged");
        check(geometry.optBoolean("holder_present")&&geometry.optBoolean("bubble_attached")&&geometry.optBoolean("bubble_shown"),"actual intended target remains attached/shown");
        // Newer explicitly requests dp12 asynchronously. At the first content item,
        // LinearLayoutManager fixes a positive start gap; select that policy only
        // from source/configuration/identity, then assert its exact boundary below.
        // Neither source-requested branch receives height credit.
        if(!scenario.sourceRequestedAnchor)check(scenario.referenceTarget.getInt("bubble_width")==geometry.getInt("bubble_width")&&scenario.referenceTarget.getInt("bubble_height")==geometry.getInt("bubble_height"),"canonical target size unchanged");
        Rect bounds=fromRectangle(geometry.getJSONObject("bubble_full_bounds")),visibleInner=fromRectangle(after.getJSONObject("visible_inner_bounds")),intersection=new Rect(bounds);
        check(after.getBoolean("global_visible")&&intersection.intersect(visibleInner)&&intersection.width()>0&&intersection.height()>0,"intended canonical target actually intersects laid-out inner globally visible viewport");
        JSONObject requestFacts=scenario.sourceRequestedAnchor?frame.getJSONObject("source_request_facts"):null;
        boolean firstContentStart=scenario.sourceRequestedAnchor&&firstContentStartPolicy(scenario,requestFacts);
        long expectedOffset=firstContentStart?0:scenario.offset;
        long absolute=frame.getLong("anchor_offset")-expectedOffset,height=after.getInt("inner_height")-before.getInt("inner_height"),bottomRelative=absolute-height;
        Rect referenceBounds=fromRectangle(scenario.referenceTarget.getJSONObject("bubble_full_bounds"));
        boolean heightCreditAllowed=!scenario.sourceRequestedAnchor&&!scenario.sourceRestoredAnchor;
        scenario.result.put("position_oracle",new JSONObject().put("absolute_offset_delta",absolute).put("actual_inner_height_delta",height).put("bottom_relative_offset_delta",bottomRelative)
            .put("source_requested_offset",scenario.offset).put("policy_expected_offset",expectedOffset).put("first_content_start_selected",firstContentStart)
            .put("source_request_facts",requestFacts==null?JSONObject.NULL:requestFacts)
            .put("branch",firstContentStart?"source-requested-first-content-start":scenario.sourceRequestedAnchor?"source-requested-absolute":scenario.sourceRestoredAnchor?"source-restored-absolute":height==0?"same-height-absolute":"height-only-bottom-relative")
            .put("height_credit_allowed",heightCreditAllowed).put("reference_target_bottom_gap",beforeVisible.bottom-referenceBounds.bottom)
            .put("final_target_bottom_gap",afterVisible.bottom-bounds.bottom).put("final_recycler_layout",after).put("final_target_geometry",geometry).put("final_visible_inner_intersection",rectangle(intersection)));
        if(firstContentStart)requireContentStartBoundary(requestFacts,after,bounds);
        check((!heightCreditAllowed||height==0)?Math.abs(absolute)<=1:Math.abs(bottomRelative)<=1,"canonical anchor follows its fixed source policy: first-content/restored/requested absolute; observed height-only otherwise");
    }
    int exactEntries(List<BChatV2Outbox.Entry> entries,BChatV2Outbox.Entry exact){int found=0;for(BChatV2Outbox.Entry entry:entries)if(entry.id==exact.id&&entry.uuid.equals(exact.uuid)&&entry.body.equals(exact.body)&&entry.roomId==1&&entry.membershipId==1001)++found;return found;}
    void requireActualLocalIdentity(Scenario scenario,BChatV2Outbox.Entry exact)throws Exception{ui(()->{
        List<BChatV2Outbox.Entry> localRows=field("localTextRows");check(exactEntries(localRows,exact)==1,"exact committed SQLiteID/UUID in actual localTextRows");
        Object local=get("roomLocal");check(local!=null,"actual roomLocal snapshot present");Field rows=local.getClass().getDeclaredField("text");rows.setAccessible(true);
        @SuppressWarnings("unchecked") List<BChatV2Outbox.Entry> roomEntries=(List<BChatV2Outbox.Entry>)rows.get(local);
        check(exactEntries(roomEntries,exact)==1,"exact committed SQLiteID/UUID in actual roomLocal.text");
        BChatTimelineRows.Snapshot projected=snapshot();check(projected!=null&&projected.scope.account.equals(scope.key)&&projected.scope.userId==7&&projected.scope.roomId==1&&projected.scope.membershipId==1001,"actual immutable projection has exact fixture account/room/member");
        int found=0;for(BChatTimelineRows.Row row:projected.rows)if(row.local!=null&&row.local.sqliteId==exact.id&&row.local.uuid.equals(exact.uuid)&&row.local.body.equals(exact.body)&&row.key.stableId()==-exact.id)++found;
        check(found==1,"exact committed SQLiteID/UUID/stableID in actual immutable snapshot, independent of local holder visibility");
        scenario.result.put("actual_local_identity_proof",new JSONObject().put("sqlite_id",exact.id).put("uuid",exact.uuid).put("stable_id",-exact.id)
            .put("localTextRows",true).put("roomLocal_text",true).put("immutable_snapshot",true).put("local_holder_visibility_required",false));
    });}
    void complete(Scenario scenario)throws Exception{scenario.result.put("passed",true);active=null;}
    void finishDiagnostics(Scenario scenario)throws Exception{
        ui(scenario::stop);scenario.result.put("frame_count",scenario.frameCount).put("pre_draw_first128",scenario.frames)
            .put("last_pre_draw",scenario.last==null?JSONObject.NULL:scenario.last).put("final_diagnostics",sendDiagnostics(scenario.marker));
        if(scenario.barrier!=null)scenario.result.put("barrier_final_status",scenario.barrier.status());
    }
    void knownJump(boolean pendingLayout)throws Exception{
        prepare(0,500);Scenario scenario=new Scenario(pendingLayout?"present-jump-before-layout-sendcapture":"late-enqueue-then-known-present-jump");scenario.target=131;active=scenario;composer(scenario);
        try(Barrier barrier=new Barrier()){
            ui(()->{beginHeldAction(scenario,barrier);if(!pendingLayout)click();call("jumpToCanonicalMessage",new Class<?>[]{roomType,long.class},room,131L);
                if(pendingLayout){check(timeline.isLayoutRequested()||timeline.hasPendingAdapterUpdates(),"actual jump has pending layout at send capture");scenario.result.put("pending_layout_at_click",timeline.isLayoutRequested()).put("pending_adapter_updates_at_click",timeline.hasPendingAdapterUpdates());click();}endHeldAction(scenario,barrier);});
            settle();ui(()->{rememberAnchor(scenario);check(targetGeometry(timeline.findViewHolderForItemId(131)).optInt("visible_intersection_height")>0,"actual present jump target intersects viewport before enqueue release");});afterRelease(scenario,barrier);complete(scenario);
        }
    }
    void gesture()throws Exception{
        prepare(0,500);Scenario scenario=new Scenario("late-enqueue-after-real-user-gesture");active=scenario;composer(scenario);AtomicInteger drag=new AtomicInteger();
        RecyclerView.OnScrollListener observed=new RecyclerView.OnScrollListener(){@Override public void onScrollStateChanged(RecyclerView view,int state){if(state!=RecyclerView.SCROLL_STATE_IDLE)drag.incrementAndGet();}};
        ui(()->timeline.addOnScrollListener(observed));try(Barrier barrier=new Barrier()){
            ui(()->{beginHeldAction(scenario,barrier);click();});int[] location=new int[2];ui(()->timeline.getLocationOnScreen(location));float x=location[0]+timeline.getWidth()/2f,start=location[1]+40,end=location[1]+timeline.getHeight()-40;long down=SystemClock.uptimeMillis();
            inject(down,down,MotionEvent.ACTION_DOWN,x,start);for(int n=1;n<=10;++n){SystemClock.sleep(20);inject(down,SystemClock.uptimeMillis(),MotionEvent.ACTION_MOVE,x,start+(end-start)*n/10);}SystemClock.sleep(20);inject(down,SystemClock.uptimeMillis(),MotionEvent.ACTION_UP,x,end);
            await("native gesture settles",()->timeline.getScrollState()==RecyclerView.SCROLL_STATE_IDLE);settle();ui(()->{check(drag.get()>0,"real RecyclerView drag/settling event reached product listener");rememberAnchor(scenario);endHeldAction(scenario,barrier);});
            scenario.result.put("observed_nonidle_states",drag.get());afterRelease(scenario,barrier);complete(scenario);
        }finally{ui(()->timeline.removeOnScrollListener(observed));}
    }
    void inject(long down,long time,int action,float x,float y){MotionEvent event=MotionEvent.obtain(down,time,action,x,y,0);event.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);try{check(getUiAutomation().injectInputEvent(event,true),"native input event delivered");}finally{event.recycle();}}
    void cachedOlder()throws Exception{
        prepare(300,330);Scenario scenario=new Scenario("late-enqueue-with-actual-cached-older");scenario.sourceRestoredAnchor=true;active=scenario;composer(scenario);ui(()->rememberAnchor(scenario));
        try(Barrier barrier=new Barrier()){ui(()->{beginHeldAction(scenario,barrier);click();call("showCachedMessages",new Class<?>[]{roomType,long.class,boolean.class},room,331L,false);endHeldAction(scenario,barrier);});afterRelease(scenario,barrier);}
        List<JSONObject> rows=field("displayedMessages");check(rows.get(0).getLong("id")<331,"actual cached older page committed despite local render serial");
        complete(scenario);
    }
    void cachedNewer()throws Exception{
        prepare(200,230);Scenario scenario=new Scenario("late-enqueue-with-actual-cached-newer");active=scenario;composer(scenario);scenario.sourceRequestedAnchor=true;scenario.target=scenario.anchorId=260;scenario.offset=((Number)call("dp",new Class<?>[]{int.class},12)).longValue();
        scenario.result.put("expected_anchor_id",scenario.target).put("expected_anchor_offset",scenario.offset);
        ui(()->rememberLayoutReference(scenario,"source-requested-dp12-not-observed"));
        try(Barrier barrier=new Barrier()){ui(()->{beginHeldAction(scenario,barrier);click();call("showNewerMessages");endHeldAction(scenario,barrier);});afterRelease(scenario,barrier);}
        List<JSONObject> rows=field("displayedMessages");check(rows.get(0).getLong("id")==260&&rows.get(rows.size()-1).getLong("id")>260,"actual newer page/explicit anchor committed");
        complete(scenario);
    }
    void invalidateOwner()throws Exception{
        prepare(0,500);Scenario scenario=new Scenario("late-enqueue-after-actual-owner-invalidation");active=scenario;composer(scenario);scenario.invalidated=true;
        try(Barrier barrier=new Barrier()){ui(()->{beginHeldAction(scenario,barrier);click();call("invalidateMessageTimelineOwner");endHeldAction(scenario,barrier);});settle();afterRelease(scenario,barrier);complete(scenario);}
    }
}

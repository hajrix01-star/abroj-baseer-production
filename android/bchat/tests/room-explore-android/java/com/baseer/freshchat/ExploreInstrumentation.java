package com.baseer.freshchat;

import android.app.Dialog;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import com.baseer.freshchat.sync.AccountScope;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real Panel/Dialog/RecyclerView/native JSON; fake Host HTTP/auth/formatter explicitly bounded to one room. */
public final class ExploreInstrumentation extends Instrumentation {
    private static final String PACKAGE="com.baseer.bchat.room.explore.test";
    private ExploreTestActivity activity;
    private Context context;
    private int checks;
    private final JSONArray renders=new JSONArray(),journeys=new JSONArray(),captures=new JSONArray();
    interface Work{void run()throws Exception;}
    void check(boolean ok,String label){++checks;if(!ok)throw new AssertionError(label);}
    void ui(Work work){AtomicReference<Throwable> failure=new AtomicReference<>();runOnMainSync(()->{try{work.run();}catch(Throwable t){failure.set(t);}});if(failure.get()!=null)throw new AssertionError(failure.get());}
    @SuppressWarnings("unchecked") <T>T field(Object owner,String name)throws Exception{Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return(T)f.get(owner);}
    <T>T get(String name)throws Exception{return field(activity.panel,name);}
    void settle(){waitForIdleSync();SystemClock.sleep(160);waitForIdleSync();}
    void await(String label,Work assertion)throws Exception{
        Throwable last=null;
        for(int attempt=0;attempt<100;++attempt){int before=checks;try{ui(assertion);return;}catch(AssertionError failure){checks=before;last=failure;SystemClock.sleep(25);}}
        throw new AssertionError("Layout/state did not settle: "+label,last);
    }
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle reply=new Bundle();JSONObject evidence=new JSONObject();boolean passed=false;
        try{
            context=getTargetContext();check(PACKAGE.equals(context.getPackageName()),"unique standalone package");
            check(Build.VERSION.SDK_INT==35,"actual SDK35");check(context.getPackageManager().checkPermission("android.permission.INTERNET",PACKAGE)!=0,"no INTERNET");
            RoomExploreCases.main(new String[0]);check(RoomExploreCases.assertions==91,"same91 protocol cases on actual Android JSONObject, no JSON adapters");
            evidence.put("protocol_checks",RoomExploreCases.assertions);
            for(String language:new String[]{"ar","en"})for(boolean dark:new boolean[]{false,true})for(int scale:new int[]{1,2})render(language,dark,scale);
            launch("ar",true,2);navigation();filtersAndModes();scopeAndPause();nativeIme();passed=true;
        }catch(Throwable failure){try{evidence.put("failure",failure.toString()).put("stack",new JSONArray(Arrays.asList(failure.getStackTrace())));}catch(Exception ignored){}}
        try{
            evidence.put("passed",passed).put("checks",checks).put("renders",renders).put("journeys",journeys).put("captures",captures)
                .put("scope","Actual frozen production RoomExplorePanel/Protocol/Ui + native AndroidX/JSONObject/Dialog/config/IME; synthetic Host account/current rights/HTTP replies/formatter. No product Activity/auth/HTTP/backend/receipt/media fetch/performance acceptance.")
                .put("protocol_label_note","Reused RoomExploreCases source prints its original JVM-adapter label; this isolated native build compiles no JSON adapters and executes SDK35 org.json with actual media constant owner.");
            try(FileOutputStream file=context.openFileOutput("room-explore-results.json",0)){file.write(evidence.toString(2).getBytes(StandardCharsets.UTF_8));}
        }catch(Exception failure){passed=false;reply.putString("stream","Evidence write failure "+failure);}
        if(activity!=null)ui(()->activity.finish());reply.putString("stream",(passed?"PASS ":"FAIL ")+checks+" C16 native component checks; "+evidence.optString("failure","")+"\n");finish(passed?-1:1,reply);
    }
    void launch(String language,boolean dark,int scale)throws Exception{
        if(activity!=null){ui(()->activity.finish());settle();}
        ExploreTestActivity.language=language;ExploreTestActivity.dark=dark;ExploreTestActivity.scale=scale;
        activity=(ExploreTestActivity)startActivitySync(new Intent(context,ExploreTestActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));settle();
        ui(()->{
            check(activity.getResources().getConfiguration().getLocales().get(0).getLanguage().equals(language),"actual locale");
            check(activity.getResources().getConfiguration().fontScale==scale,"actual font scale");check(ChatAppearance.dark(activity)==dark,"actual theme");
        });
    }
    void open(boolean gallery,boolean media,boolean supported)throws Exception{ui(()->activity.open(gallery,media,supported));settle();ui(()->{RecyclerView list=get("list");check(list.getHeight()>0&&list.isShown()&&!list.isLayoutRequested(),"actual positive panel viewport");});}
    RecyclerView list()throws Exception{return get("list");}
    ExploreTestActivity.Read read(){return activity.host.reads.get(activity.host.reads.size()-1);}
    @SuppressWarnings("unchecked") int stack()throws Exception{return((ArrayDeque<Long>)get("back")).size();}
    void search(String value)throws Exception{ui(()->{((EditText)get("input")).setText(value);((Button)get("search")).performClick();});settle();}
    JSONObject page(RoomExploreProtocol.Query query,long first,int count,boolean more)throws Exception{
        JSONArray rows=new JSONArray();
        for(int index=0;index<count;++index){long id=first+index;
            String kind=query.kind==RoomExploreProtocol.Kind.TEXT?"":query.kind==RoomExploreProtocol.Kind.ALL
                ?((query.gallery||index%4!=0)?new String[]{"image","file","audio"}[index%3]:""):query.kind.wire;
            JSONObject row=new JSONObject().put("id",id).put("author_user_id",8).put("author_name","اسم طويل Professional sender name repeated repeated repeated repeated")
                .put("text","رسالة طويلة ثابتة Long search preview repeated repeated repeated repeated repeated repeated repeated repeated repeated repeated "+id)
                .put("created_at","2026-10-18 10:20:30");
            if(!kind.isEmpty())row.put("media",new JSONObject().put("id",100000+id).put("kind",kind)
                .put("mime","image".equals(kind)?"image/jpeg":"audio".equals(kind)?"audio/mp4":"application/pdf")
                .put("name","تقرير طويل Professional report repeated 2026.pdf").put("sha256",String.join("",java.util.Collections.nCopies(64,"a")))
                .put("document_type","other").put("thumbnail_available",!"file".equals(kind)).put("size",1234));
            rows.put(row);
        }
        return new JSONObject().put("api_version",2).put("membership_id",query.membershipId).put("messages",rows)
            .put("next_before_id",more&&count>0?first:JSONObject.NULL);
    }
    void respond(ExploreTestActivity.Read read,int status,JSONObject body)throws Exception{
        ui(()->read.reply.complete(status,body));settle();await("callback idle",()->check(!(Boolean)get("busy"),"callback completed"));
    }
    void complete(long first,int count,boolean more)throws Exception{ExploreTestActivity.Read read=read();respond(read,200,page(read.query,first,count,more));}
    void rowAt(int position)throws Exception{
        ui(()->((LinearLayoutManager)list().getLayoutManager()).scrollToPositionWithOffset(position,0));settle();
        await("row "+position,()->check(list().findViewHolderForAdapterPosition(position)!=null&&!list().isComputingLayout()&&!list().hasPendingAdapterUpdates(),"real holder laid out"));
    }
    void fullyVisible(View target)throws Exception{
        for(int attempt=0;attempt<5;++attempt){AtomicBoolean ready=new AtomicBoolean();
            ui(()->{RecyclerView recycler=list();Rect viewport=new Rect();recycler.getGlobalVisibleRect(viewport);int[] at=new int[2];target.getLocationOnScreen(at);
                if(at[1]<viewport.top)recycler.scrollBy(0,at[1]-viewport.top);
                else if(at[1]+target.getHeight()>viewport.bottom)recycler.scrollBy(0,at[1]+target.getHeight()-viewport.bottom);
                else ready.set(true);
            });settle();if(ready.get())break;
        }
        ui(()->{Rect visible=new Rect();check(target.isShown()&&target.getGlobalVisibleRect(visible)&&target.getHeight()>0
                &&visible.height()>=target.getHeight()-2,"target fully reachable in actual adaptive scroll surface");});
    }
    void touchTarget(String name,int position)throws Exception{
        rowAt(position);View target=get(name);fullyVisible(target);
        ui(()->{check(target.getHeight()>=Ui.dp(activity,48),"48dp action target "+name);
            if(target instanceof TextView){TextView text=(TextView)target;check(text.getLayout()!=null&&text.getLayout().getHeight()<=text.getHeight()-text.getCompoundPaddingTop()-text.getCompoundPaddingBottom()+1,"button text wraps without vertical clipping "+name);}
        });
    }
    void capture(String name)throws Exception{
        settle();Bitmap frame=getUiAutomation().takeScreenshot();check(frame!=null,"actual screenshot available");
        try(FileOutputStream file=context.openFileOutput(name,0)){check(frame.compress(Bitmap.CompressFormat.PNG,100,file),"PNG capture");}finally{frame.recycle();}captures.put(name);
    }
    void render(String language,boolean dark,int scale)throws Exception{
        launch(language,dark,scale);open(false,true,true);int attempts=activity.host.attempts;
        ui(()->((EditText)get("input")).setText("فاتورة kitchen"));settle();check(activity.host.attempts==attempts,"no fetch while typing");
        ui(()->((Button)get("search")).performClick());SystemClock.sleep(260);settle();
        ui(()->{check((Boolean)get("busy"),"held synthetic request loading");check(!((EditText)get("input")).isEnabled(),"busy disables input");check(((TextView)get("notice")).getText().toString().equals(activity.getString(R.string.explore_loading_search)),"delayed actual loading label");});
        complete(401,30,true);String prefix="explore-"+language+"-"+(dark?"dark":"light")+"-font"+scale;
        ui(()->{RecyclerView.Adapter<?> a=list().getAdapter();check(a.hasStableIds()&&a.getItemCount()==32,"single30-row page plus form/footer");Set<Long> ids=new HashSet<>();for(int i=0;i<a.getItemCount();++i)check(ids.add(a.getItemId(i)),"stable row IDs unique");
            check(a.getItemId(0)==Long.MIN_VALUE&&a.getItemId(31)==Long.MIN_VALUE+1&&a.getItemId(1)==430,"form/footer sentinel and newest-first display");
            check(stack()==0,"first page no cursor stack");check(((View)get("form")).getLayoutDirection()==AppLocale.direction(activity),"actual form RTL/LTR");});
        touchTarget("search",0);capture(prefix+"-top.png");rowAt(1);capture(prefix+"-results.png");
        ui(()->{RecyclerView.ViewHolder h=list().findViewHolderForAdapterPosition(1);check(h.getBindingAdapterPosition()==1,"actual result binding position");
            TextView author=field(h,"author"),preview=field(h,"preview");check(author.length()>0&&author.getWidth()>0,"long author visible and wrapped");check(preview.getMaxLines()==3,"bounded multiline preview");});
        touchTarget("older",31);capture(prefix+"-footer.png");
        renders.put(new JSONObject().put("locale",language).put("dark",dark).put("font_scale",scale).put("width_px",activity.getResources().getDisplayMetrics().widthPixels).put("results",30));
        ui(()->activity.panel.dismiss());settle();
    }
    void navigation()throws Exception{
        open(false,true,true);search("فاتورة kitchen");complete(401,30,true);
        ui(()->((Button)get("older")).performClick());settle();ExploreTestActivity.Read failed=read();check(failed.query.beforeId==401,"next uses actual minimum cursor");
        respond(failed,503,null);ui(()->{check(stack()==0,"failed next never pushes cursor");check(((RoomExploreProtocol.Query)get("displayedQuery")).beforeId==0,"failed next retains prior displayed cursor");check(((Button)get("retry")).getVisibility()==View.VISIBLE,"manual retry shown");});
        ui(()->((Button)get("retry")).performClick());settle();ExploreTestActivity.Read retried=read();check(retried.query.beforeId==401,"retry same cursor not first page");complete(371,30,true);
        ui(()->check(stack()==1&&((RoomExploreProtocol.Query)get("displayedQuery")).beforeId==401,"only successful next pushes prior cursor"));
        respond(retried,200,page(retried.query,371,30,true));ui(()->check(stack()==1,"duplicate callback does not push twice"));
        ui(()->((Button)get("previous")).performClick());settle();check(read().query.beforeId==0,"previous uses saved cursor");complete(401,30,true);
        respond(failed,200,page(failed.query,371,30,true));ui(()->check(stack()==0&&((RoomExploreProtocol.Page)get("page")).rows.get(0).id==401,"late old callback cannot replace current page"));
        search("empty");complete(1,0,false);ui(()->check(((TextView)get("notice")).getText().toString().equals(activity.getString(R.string.explore_empty_search)),"empty result label"));
        int attempts=activity.host.attempts;search(" ");check(activity.host.attempts==attempts,"invalid query no Host call");
        ui(()->check(((TextView)get("notice")).getText().toString().equals(activity.getString(R.string.explore_invalid_query)),"invalid query label"));
        search("invalid response");respond(read(),200,new JSONObject().put("api_version",2).put("membership_id",999));
        ui(()->check(((TextView)get("notice")).getText().toString().equals(activity.getString(R.string.explore_unconfirmed)),"malformed native JSON response rejected"));
        search("permission");respond(read(),403,null);ui(()->check(get("attempted")==null&&stack()==0&&((TextView)get("notice")).getText().toString().equals(activity.getString(R.string.explore_unavailable)),"permission failure clears cursor/retry and content"));
        search("bounded cursors");complete(10000,1,true);
        for(int i=1;i<=33;++i){ui(()->((Button)get("older")).performClick());settle();long before=read().query.beforeId;complete(before-1,1,true);final int expected=Math.min(i,30);ui(()->check(stack()==expected&&list().getAdapter().getItemCount()==3,"one-page content/cursor stack cap30"));}
        ui(()->((Button)get("first")).performClick());settle();check(read().query.beforeId==0,"first resets cursor");complete(401,30,true);ui(()->check(stack()==0,"first accepted page clears bounded history"));
        rowAt(1);RecyclerView.ViewHolder held=list().findViewHolderForAdapterPosition(1);long target=list().getAdapter().getItemId(1);
        ui(()->held.itemView.performClick());settle();check(activity.host.opened==target,"row click only passes canonical message ID to fake Host");
        assertClosedScrub(held);journeys.put("pagination-failure-retry-previous-first-duplicate-late-empty-invalid-permission-bounded33pages-openID");
    }
    @SuppressWarnings("unchecked") void filtersAndModes()throws Exception{
        open(false,true,true);search("filter sample");complete(401,3,true);
        for(RoomExploreProtocol.Kind kind:RoomExploreProtocol.Kind.values()){
            if(kind==RoomExploreProtocol.Kind.ALL)continue;
            List<RoomExploreProtocol.Kind> kinds=get("filterKinds");List<Button> buttons=get("filters");final int index=kinds.indexOf(kind);
            ui(()->buttons.get(index).performClick());settle();check(read().query.kind==kind&&read().query.beforeId==0,"explicit kind filter query");complete(401,3,false);
            check(!read().query.path().contains(read().query.text)&&!read().query.path().contains("q="),"query text absent from search URL");
            check(read().query.payload().getString("q").equals("filter sample"),"search text exists only in payload");
        }
        open(true,true,true);check(activity.host.reads.size()==1&&read().query.gallery,"gallery first page explicit automatic read");complete(401,3,false);
        ui(()->{List<RoomExploreProtocol.Kind> kinds=get("filterKinds");check(!kinds.contains(RoomExploreProtocol.Kind.TEXT),"gallery has no text filter");check(((EditText)get("input")).getVisibility()==View.GONE,"gallery has no text input");});
        check(read().query.path().contains("/media?membership_id=41&kind=all")&&!read().query.path().contains("q="),"gallery current route only, no query text");
        open(true,false,true);check(activity.host.attempts==0,"no-media gallery never dispatches");ui(()->check(((TextView)get("notice")).getText().toString().equals(activity.getString(R.string.explore_unavailable)),"no-media gallery unavailable"));
        open(false,false,true);search("no media");complete(401,3,false);ui(()->{List<?> kinds=get("filterKinds");check(kinds.size()==2,"no-media search only all/text filters");});
        rowAt(1);ui(()->{RecyclerView.ViewHolder h=list().findViewHolderForAdapterPosition(1);TextView file=field(h,"file");check(file.getText().toString().equals(activity.getString(R.string.explore_file)),"media filename not leaked without media display rights");});
        open(false,true,false);ui(()->check(!((Button)get("search")).isEnabled()&&!((EditText)get("input")).isEnabled(),"unsupported controls disabled"));check(activity.host.attempts==0,"unsupported no probe/HTTP");
        ui(()->check(((TextView)get("notice")).getText().toString().equals(activity.getString(R.string.explore_unsupported)),"unsupported label"));
        journeys.put("kind-filters-gallery-no-media-unsupported-no-query-URL-no-fetch-from-metadata");
    }
    void assertClosedScrub(RecyclerView.ViewHolder held)throws Exception{
        ui(()->{check((Boolean)get("closed")&&get("page")==null&&get("attempted")==null&&get("displayedQuery")==null&&stack()==0,"closed panel releases page/query/cursor RAM");
            check(((EditText)get("input")).length()==0&&list().getAdapter()==null,"closed input and adapter cleared");
            if(held!=null){for(String name:new String[]{"author","preview","file","time"})check(((TextView)field(held,name)).length()==0,"recycled result text scrubbed "+name);check(held.itemView.getContentDescription()==null&&!held.itemView.isEnabled(),"closed row inaccessible and disabled");}
        });
    }
    void scopeAndPause()throws Exception{
        for(int variant=0;variant<5;++variant){
            open(false,true,true);search("held owner");ExploreTestActivity.Read held=read();complete(401,3,false);int attempts=activity.host.attempts;final int change=variant;
            ui(()->{if(change==0)activity.host.account=new AccountScope("https://explore.invalid","synthetic",7);
                else if(change==1)activity.host.room=13;else if(change==2)activity.host.member=42;
                else if(change==3)activity.host.generation=10;else activity.host.active=false;
                ((Button)get("search")).performClick(); // Not busy: bound() itself must prevent the next Host dispatch.
                held.reply.complete(200,page(held.query,401,3,true));
            });settle();check(activity.host.attempts==attempts&&activity.host.opened==0,"no old account/room/member/rights Host dispatch");assertClosedScrub(null);
        }
        open(false,true,true);search("explicit close");ExploreTestActivity.Read held=read();ui(()->activity.panel.dismiss());respond(held,200,page(held.query,401,3,false));assertClosedScrub(null);
        open(false,true,true);search("actual pause");ExploreTestActivity.FakeHost host=activity.host;ExploreTestActivity.Read pending=read();int pauses=activity.pauses;
        ExploreTestActivity.PauseActivity overlay=(ExploreTestActivity.PauseActivity)startActivitySync(new Intent(context,ExploreTestActivity.PauseActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));settle();
        check(activity.pauses>pauses,"real native Activity onPause reached test Host dismiss hook");ui(()->overlay.finish());settle();respond(pending,200,page(pending.query,401,3,false));assertClosedScrub(null);check(host.attempts==1,"no automatic read on resume");
        journeys.put("stale-account-object-room-member-rights-generation-close-native-pause-late-reply-no-resume-read");
    }
    void event(long down,long at,int action,float x,float y){MotionEvent e=MotionEvent.obtain(down,at,action,x,y,0);e.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);sendPointerSync(e);e.recycle();}
    void tap(View view)throws Exception{int[] at=new int[2];ui(()->view.getLocationOnScreen(at));float x=at[0]+view.getWidth()/2f,y=at[1]+view.getHeight()/2f;long down=SystemClock.uptimeMillis();event(down,down,MotionEvent.ACTION_DOWN,x,y);SystemClock.sleep(45);event(down,SystemClock.uptimeMillis(),MotionEvent.ACTION_UP,x,y);}
    void nativeIme()throws Exception{
        open(false,true,true);touchTarget("input",0);EditText input=get("input");tap(input);sendStringSync("kitchen");settle();
        await("real IME visible",()->{Dialog dialog=get("dialog");check(dialog.getWindow().getDecorView().getRootWindowInsets().isVisible(WindowInsets.Type.ime()),"native IME insets visible");});
        check(activity.host.attempts==0,"real key typing does not fetch");touchTarget("search",0);capture("explore-ime-font2-form.png");tap(get("search"));settle();
        check(activity.host.attempts==1&&read().query.text.equals("kitchen"),"actual pointer search submits typed value once");complete(401,30,true);
        rowAt(1);capture("explore-ime-font2-results.png");touchTarget("older",31);capture("explore-ime-font2-footer.png");
        check(list().getHeight()>0,"positive native result viewport after keyboard search");journeys.put("actual-native-IME-key-events-pointer-submit-font2-form-results-footer");
    }
}

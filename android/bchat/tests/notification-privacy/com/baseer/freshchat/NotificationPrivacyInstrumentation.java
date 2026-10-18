package com.baseer.freshchat;

import android.app.Instrumentation;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.Build;
import android.os.Bundle;
import android.os.Looper;
import android.os.Process;
import android.os.SystemClock;
import android.service.notification.StatusBarNotification;
import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.BChatStorageRepository;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Native OS acceptance of real production modules with a SYNTHETIC posting/auth driver.
 * Real NotificationManager/SharedPreferences/Handler; only the disk-lane scheduler is adapted.
 * Not FirebaseMessagingService, real authenticated HTTP, Activity, audio, OEM, or API26 execution.
 */
public final class NotificationPrivacyInstrumentation extends Instrumentation {
    private static final String PACKAGE="com.baseer.bchat.notification.privacy.test";
    private static final String ACCOUNT="00000000-0000-4000-8000-000000000001";
    private static final String TOKEN="synthetic-native-privacy-token-00000000000000000000";
    private static final String GROUP="native-privacy-business";
    private static final String OTHER="native-privacy-unrelated";
    private static final Method POSTING=postingMethod();
    private final AccountScope scope=new AccountScope("https://native-privacy.invalid","synthetic",7);
    private Context context;
    private NotificationManager manager;
    private String phase;
    private int assertions;
    private long revision=100;
    private final JSONArray journeys=new JSONArray();
    private final JSONArray observations=new JSONArray();

    private void check(boolean ok,String label){
        ++assertions;if(!ok)throw new AssertionError("Native privacy assertion "+assertions+": "+label);
    }
    @Override public void onCreate(Bundle args){super.onCreate(args);phase=args.getString("phase","main");start();}
    @Override public void onStart(){
        Bundle result=new Bundle();JSONObject evidence=new JSONObject();boolean passed=false;
        try{
            context=getContext();
            check(PACKAGE.equals(context.getPackageName()),"standalone namespace only");
            check(Looper.myLooper()!=Looper.getMainLooper()&&Build.VERSION.SDK_INT==35,"actual SDK35 worker");
            manager=context.getSystemService(NotificationManager.class);
            check(manager!=null&&manager.areNotificationsEnabled(),"real OS notification permission enabled for isolated package");
            if("main".equals(phase))mainJourneys();
            else if("cold".equals(phase))coldJourney();
            else if("boundary".equals(phase)){prepareFixture();immediateBoundaries(20);}
            else throw new IllegalArgumentException("Unknown native phase");
            passed=true;
        }catch(Throwable failure){
            try{evidence.put("failure",failure.toString());evidence.put("stack",new JSONArray(java.util.Arrays.asList(failure.getStackTrace())));}catch(Exception ignored){}
        }
        try{
            evidence.put("passed",passed).put("assertions",assertions).put("phase",phase)
                .put("sdk",Build.VERSION.SDK_INT).put("pid",Process.myPid()).put("journeys",journeys)
                .put("tracker_api_present",POSTING!=null)
                .put("observations",observations).put("scope","Actual Android35 OS notify/cancel and real production state/reset/buffer/parser/renderer/channels/ledger; synthetic event/auth posting driver and bounded executor adapter; no real service/FCM/HTTP/Activity/audio/OEM/API26 claim");
            try(FileOutputStream file=context.openFileOutput("notification-privacy-"+phase+".json",Context.MODE_PRIVATE)){
                file.write(evidence.toString(2).getBytes(StandardCharsets.UTF_8));
            }
            result.putString("stream",(passed?"PASS ":"FAIL ")+assertions+" actual Android35 OS privacy assertions; phase="+phase+"; "+evidence.optString("failure","")+"\n");
        }catch(Exception writeFailure){passed=false;result.putString("stream","FAIL evidence write "+writeFailure+"\n");}
        finish(passed?-1:1,result);
    }

    private void flush(){
        for(int pass=0;pass<64;++pass){
            while(BChatStorageRepository.drainOne()){}
            runOnMainSync(()->{});
            if(BChatStorageRepository.pending()==0)return;
        }
        throw new AssertionError("Bounded native disk/callback drain exhausted");
    }
    private void prepareRoute(){
        BChatPushState.token(context,TOKEN);BChatPushState.verifiedAccount(context,scope);flush();
        BChatPushState.Registration ticket=BChatPushState.registration(context,scope);
        check(ticket!=null,"synthetic registration ticket available after real local commit");
        boolean[] accepted={false};BChatPushState.registeredAsync(context,ticket,ACCOUNT,(ok,durable)->accepted[0]=ok&&durable);flush();
        check(accepted[0]&&BChatPushState.matches(context,ACCOUNT),"real committed PushState route, no HTTP auth claim");
    }
    private void mode(String mode){
        boolean[] accepted={false};BChatPushState.acceptPreviewMode(context,BChatPushState.previewRequest(context,ACCOUNT),
            mode,++revision,(ok,durable)->accepted[0]=ok&&durable);flush();
        check(accepted[0]&&mode.equals(BChatPushState.previewMode(context,ACCOUNT)),"synthetic validated preview accepted durably: "+mode);
    }
    private void restrict(String mode){
        BChatPushState.PreviewRequest[] request={null};
        BChatPushState.beginPreviewChange(context,ACCOUNT,mode,(ticket,durable)->{if(durable)request[0]=ticket;});
        // Assertions before draining prove synchronous privacy retraction, not commit timing luck.
        check(mode.equals(BChatPushState.previewMode(context,ACCOUNT)),"restriction immediate before queued commit");
        absent(roomTag(),0);absent(ACCOUNT+":bchat-summary",1);controls();flush();
        check(request[0]!=null,"restriction ticket becomes sendable after real commit");
        boolean[] accepted={false};BChatPushState.acceptPreviewMode(context,request[0],mode,++revision,
            (ok,durable)->accepted[0]=ok&&durable);flush();check(accepted[0],"restricted mode acknowledged");
    }
    private NotificationPresentation frame(long id){
        Map<String,String> data=new HashMap<>();data.put("kind","chat");data.put("event_id",String.valueOf(id));
        data.put("account_key",ACCOUNT);data.put("presentation_v","1");
        data.put("room_key",NotificationPresentation.roomKey(ACCOUNT,1,1,1));
        data.put("message_key",NotificationPresentation.messageKey(ACCOUNT,1,1,1,id));
        data.put("sender_key",NotificationPresentation.senderKey(ACCOUNT,1,1,1,2));
        data.put("sent_at_ms",String.valueOf(System.currentTimeMillis()));data.put("sender_name","Private sender");
        data.put("conversation_title","Private room");data.put("is_group","true");data.put("message_preview","Private body "+id);
        NotificationPresentation frame=NotificationPresentation.parse(data);check(frame!=null,"production parser accepts bounded synthetic frame");return frame;
    }
    private String roomTag(){return ACCOUNT+":bchat-room:"+NotificationPresentation.roomKey(ACCOUNT,1,1,1);}
    private static final class Posted {
        BChatPushState.Delivery delivery;BChatNotificationConversations.Conversation snapshot;
    }
    private static Method postingMethod(){
        try{return BChatNotificationPresentationReset.class.getDeclaredMethod("posting",NotificationManager.class,String.class,int.class);}
        catch(NoSuchMethodException oldServiceBeforeHook){return null;}
    }
    private void posting(String tag,int id){
        // Compatibility driver only: the frozen old Reset had no hook, exactly as its old service.
        // New Reset admission invokes the real production method, not a test approximation.
        if(POSTING==null)return;
        try{if(!Boolean.TRUE.equals(POSTING.invoke(null,manager,tag,id)))throw new AssertionError("Synthetic posting admission refused");}
        catch(ReflectiveOperationException failure){throw new AssertionError(failure);}
    }
    private Posted post(long id){
        return post(id,true);
    }
    private Posted post(long id,boolean waitVisible){
        Posted posted=new Posted();posted.delivery=BChatPushState.delivery(context,ACCOUNT);
        NotificationPresentation frame=frame(id);BChatNotificationChannels.Selection channel=BChatNotificationChannels.resolve("chat");
        check(channel.known,"actual module has committed channel selection");
        boolean[] rendered={false};boolean routed=BChatPushState.present(posted.delivery,ceiling->{
            BChatNotificationChannels.present(channel,()->{
                BChatNotificationConversations.Change change=BChatNotificationConversations.append(frame,ceiling);
                if(change==null)throw new AssertionError("Projection rejected");
                for(String tag:change.evictedTags)manager.cancel(tag,0);
                posted.snapshot=change.conversation;
                rendered[0]=BChatNotificationConversations.present(change.conversation,()->{
                    Notification publicVersion=generic("Public generic",false).build();
                    Notification notification=BChatMessagingNotificationStyle.create(context,channel.channelId,change.conversation)
                        .setSmallIcon(android.R.drawable.stat_notify_chat).setGroup(GROUP)
                        .setGroupAlertBehavior(Notification.GROUP_ALERT_SUMMARY).setOnlyAlertOnce(true)
                        .setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(publicVersion).build();
                    posting(change.conversation.tag,0);
                    manager.notify(change.conversation.tag,0,notification);
                    posting(ACCOUNT+":bchat-summary",1);
                    manager.notify(ACCOUNT+":bchat-summary",1,generic("Generic summary",true).build());
                });
            });
        });
        check(routed&&rendered[0],"real routing -> channels -> buffer gates allow synthetic native post");
        if(waitVisible){present(roomTag(),0);present(ACCOUNT+":bchat-summary",1);}return posted;
    }
    private Notification.Builder generic(String text,boolean summary){
        return new Notification.Builder(context,BChatNotificationChannels.LEGACY).setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("BChat").setContentText(text).setGroup(GROUP).setGroupSummary(summary)
            .setGroupAlertBehavior(Notification.GROUP_ALERT_CHILDREN).setOnlyAlertOnce(true);
    }
    private StatusBarNotification find(String tag,int id){
        for(StatusBarNotification row:manager.getActiveNotifications())
            if(row.getId()==id&&java.util.Objects.equals(row.getTag(),tag))return row;
        return null;
    }
    private StatusBarNotification waitRow(String tag,int id,boolean wanted){
        long deadline=SystemClock.elapsedRealtime()+2500;StatusBarNotification row;
        do{row=find(tag,id);if((row!=null)==wanted)return row;SystemClock.sleep(25);}while(SystemClock.elapsedRealtime()<deadline);
        throw new AssertionError("OS row "+tag+"/"+id+" expected "+wanted);
    }
    private StatusBarNotification present(String tag,int id){StatusBarNotification row=waitRow(tag,id,true);check(row!=null,"expected actual active OS row "+id);return row;}
    private void absent(String tag,int id){waitRow(tag,id,false);check(true,"owned actual OS row retracted "+id);}
    private void controls(){present(null,9001);present(OTHER,701);}
    private void stale(Posted posted){
        check(!BChatPushState.present(posted.delivery,ignored->{throw new AssertionError("Stale Delivery executed");}),"old Delivery rejected after reset");
        check(!BChatNotificationConversations.present(posted.snapshot,()->{throw new AssertionError("Stale buffer executed");}),"old snapshot rejected after reset");
    }
    private void inspect(String expected)throws Exception{
        Notification notification=present(roomTag(),0).getNotification();
        Notification.Style recovered=Notification.Builder.recoverBuilder(context,notification).getStyle();
        Notification.MessagingStyle style=recovered instanceof Notification.MessagingStyle?(Notification.MessagingStyle)recovered:null;
        if("full".equals(expected)){
            check(style!=null&&style.isGroupConversation()&&"Private room".contentEquals(style.getConversationTitle()),"OS full row retains canonical room/group");
            check(style.getMessages().size()>0&&style.getMessages().get(style.getMessages().size()-1).getText().toString().startsWith("Private body "),"OS full row has permitted synthetic text");
        }else if("sender".equals(expected)){
            check(style!=null&&!style.isGroupConversation()&&style.getConversationTitle()==null,"OS sender row has no group/title");
            for(Notification.MessagingStyle.Message message:style.getMessages()){
                check("New message".contentEquals(message.getText()),"OS sender row has generic body, no rich text");
                check(message.getSenderPerson()!=null&&"Private sender".contentEquals(message.getSenderPerson().getName()),"OS sender Person permitted");
            }
        }else{
            check(style==null&&notification.extras.getParcelableArray(Notification.EXTRA_MESSAGES)==null,"OS none row has no MessagingStyle/Person messages");
            check("BChat".contentEquals(notification.extras.getCharSequence(Notification.EXTRA_TITLE))
                &&"New message".contentEquals(notification.extras.getCharSequence(Notification.EXTRA_TEXT)),"OS none row contains only brand/generic body");
        }
        check(notification.publicVersion!=null&&"Public generic".contentEquals(notification.publicVersion.extras.getCharSequence(Notification.EXTRA_TEXT)),"OS public version stays generic");
        observations.put(new JSONObject().put("mode",expected).put("active_room",true).put("style",style!=null));
    }

    private void prepareFixture(){
        for(StatusBarNotification row:manager.getActiveNotifications())manager.cancel(row.getTag(),row.getId());
        for(String prefs:new String[]{"bchat-push-v1","bchat-presented-events-v1","bchat-notification-channels-v1","native-privacy-evidence"})
            check(context.getSharedPreferences(prefs,0).edit().clear().commit(),"clear disposable native test preferences only");
        NotificationChannel baseline=new NotificationChannel(BChatNotificationChannels.LEGACY,"Isolated quiet tests",NotificationManager.IMPORTANCE_LOW);
        baseline.setSound(null,null);baseline.enableVibration(false);manager.createNotificationChannel(baseline);
        check(manager.getNotificationChannel(BChatNotificationChannels.LEGACY).getSound()==null,"test OS channel is quiet; no audio claim");
        check(BChatNotificationChannels.load(context).known,"actual channel preferences loaded natively");
        manager.notify(9001,new Notification.Builder(context,BChatNotificationChannels.LEGACY).setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("Synthetic transfer control").setOngoing(true).build());
        manager.notify(OTHER,701,new Notification.Builder(context,BChatNotificationChannels.LEGACY).setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("Unrelated local control").build());controls();
        prepareRoute();mode("full");
    }
    private void mainJourneys()throws Exception{
        prepareFixture();Posted first=post(11);inspect("full");
        for(String kind:new String[]{"chat","task","order","diagnostic"}){
            String tag=ACCOUNT+":"+kind+":91";
            posting(tag,0);
            manager.notify(tag,0,generic("Legacy business",false).build());
        }
        for(String kind:new String[]{"chat","task","order","diagnostic"})present(ACCOUNT+":"+kind+":91",0);
        BChatPushState.contentInvalidated(context,scope);
        absent(roomTag(),0);absent(ACCOUNT+":bchat-summary",1);
        for(String kind:new String[]{"chat","task","order","diagnostic"})absent(ACCOUNT+":"+kind+":91",0);
        controls();stale(first);journeys.put("native selective rights reset: room+summary+business rows; retained transfer9001/unrelated");

        immediateBoundaries(4);

        mode("full");Posted rich=post(12);inspect("full");restrict("sender");stale(rich);
        Posted sender=post(13);inspect("sender");restrict("none");stale(sender);post(14);inspect("none");
        journeys.put("native full -> sender -> none: fresh projected builder/OS rows, immediate reset before commit");

        mode("full");Posted held=post(15);NotificationPresentation claimFrame=frame(77);long now=System.currentTimeMillis();
        check(BChatNotificationLedger.claimSound(context,ACCOUNT,claimFrame.messageKey,claimFrame.sentAt,now,"silent"),"real native durable sound claim reserved without playing");
        BChatPushState.PreviewControl[] control={null};BChatPushState.beginPreviewControl(context,BChatPushState.previewRequest(context,ACCOUNT),"full",revision,
            (ticket,durable)->{if(durable)control[0]=ticket;});flush();
        check(control[0]!=null,"real durable control ticket captured before rights reset");
        BChatPushState.Registration registration=BChatPushState.registration(context,scope);boolean[] accepted={false};
        BChatPushState.registeredAsync(context,registration,ACCOUNT,(ok,durable)->accepted[0]=ok&&durable);
        check(BChatStorageRepository.pending()>0&&!BChatPushState.matches(context,ACCOUNT),"same-binding commit deliberately held in bounded executor");
        BChatPushState.contentInvalidated(context,scope);absent(roomTag(),0);absent(ACCOUNT+":bchat-summary",1);controls();
        flush();check(accepted[0]&&BChatPushState.matches(context,ACCOUNT),"current registration ticket survives presentation-only reset");
        stale(held);check(BChatPushState.currentPreviewControl(control[0]),"current control ticket survives rights presentation reset");
        check(!BChatNotificationLedger.claimSound(context,ACCOUNT,claimFrame.messageKey,claimFrame.sentAt,System.currentTimeMillis(),"system"),"privacy/reset cannot erase native sound claim or replay a route");
        boolean[] settled={false};++revision;BChatPushState.acceptPreviewControl(context,control[0],"full",revision,revision,
            (ok,durable)->settled[0]=ok&&durable);flush();check(settled[0],"preserved native control ticket settles normally");
        journeys.put("native held same-binding commit -> rights reset -> commit: no stale revival, registration/control/claim preserved");

        Posted logout=post(16);BChatPushState.clearAccount(context);absent(roomTag(),0);absent(ACCOUNT+":bchat-summary",1);controls();stale(logout);flush();
        check(!BChatPushState.matches(context,ACCOUNT),"logout durably disables route");journeys.put("native logout retraction preserves unrelated/transfer rows");
        prepareRoute();mode("full");post(99);inspect("full");controls();
        check(context.getSharedPreferences("native-privacy-evidence",0).edit().putInt("seed-pid",Process.myPid()).commit(),"cold fixture stores PID metadata only");
        journeys.put("seed actual rich OS row + summary for next real process cold startup");
    }
    private void immediateBoundaries(int attempts)throws Exception{
        int failed=0;
        for(int iteration=0;iteration<attempts;++iteration){
            Posted immediate=post(40+iteration,false); // Deliberately no getActiveNotifications visibility wait.
            BChatPushState.contentInvalidated(context,scope);
            long started=SystemClock.elapsedRealtime(),deadline=started+1500;
            long firstSeen=-1,lastSeen=-1,firstAbsent=-1,absenceStart=-1;
            boolean hadAbsent=false,previousPresent=false,everRoom=false,everSummary=false;
            int reappearances=0,samples=0;
            do{
                StatusBarNotification delayedRoom=find(roomTag(),0),delayedSummary=find(ACCOUNT+":bchat-summary",1);
                long elapsed=SystemClock.elapsedRealtime()-started;boolean visible=delayedRoom!=null||delayedSummary!=null;
                ++samples;everRoom|=delayedRoom!=null;everSummary|=delayedSummary!=null;
                if(visible){
                    if(firstSeen<0)firstSeen=elapsed;lastSeen=elapsed;absenceStart=-1;
                    if(hadAbsent&&!previousPresent)++reappearances;
                }else{
                    if(firstAbsent<0)firstAbsent=elapsed;if(absenceStart<0)absenceStart=elapsed;hadAbsent=true;
                }
                previousPresent=visible;
                SystemClock.sleep(25);
            }while(SystemClock.elapsedRealtime()<deadline);
            boolean finalRoom=find(roomTag(),0)!=null,finalSummary=find(ACCOUNT+":bchat-summary",1)!=null;
            long elapsed=SystemClock.elapsedRealtime()-started;
            boolean stable=!finalRoom&&!finalSummary&&absenceStart>=0&&elapsed-absenceStart>=500;
            if(!stable)++failed;
            observations.put(new JSONObject().put("boundary_iteration",iteration).put("window_ms",elapsed)
                .put("samples",samples).put("first_seen_ms",firstSeen).put("last_seen_ms",lastSeen)
                .put("first_absent_ms",firstAbsent).put("final_absence_start_ms",absenceStart)
                .put("reappearances_after_absence",reappearances).put("ever_room",everRoom).put("ever_summary",everSummary)
                .put("final_room",finalRoom).put("final_summary",finalSummary).put("final_500ms_sampled_absent",stable));
            stale(immediate);controls();
        }
        journeys.put(attempts+" immediate notify -> reset boundaries, each fully observed1500ms at25ms samples; final500ms absence is fixture criterion only, not instantaneous cancellation/Android SLA/load/FPS proof");
        check(failed==0,"final500ms sampled absence in all immediate-post/reset windows; failed="+failed);
    }
    private void coldJourney()throws Exception{
        int seed=context.getSharedPreferences("native-privacy-evidence",0).getInt("seed-pid",-1);
        check(seed>0&&seed!=Process.myPid(),"actual new process, not reflection-reset simulation");
        Field state=BChatPushState.class.getDeclaredField("state");state.setAccessible(true);
        check(state.get(null)==null,"production PushState truly cold in new process");
        inspect("full");controls();
        check(!BChatPushState.ready(context),"cold production load queued, not restored rich opt-in");flush();
        check(BChatPushState.ready(context)&&"none".equals(BChatPushState.previewMode(context,ACCOUNT)),"cold real SharedPrefs load enforces none");
        absent(roomTag(),0);absent(ACCOUNT+":bchat-summary",1);controls();
        NotificationPresentation claimed=frame(77);
        check(!BChatNotificationLedger.claimSound(context,ACCOUNT,claimed.messageKey,claimed.sentAt,System.currentTimeMillis(),"system"),"native durable sound claim survives actual process restart");
        journeys.put("new-process cold SharedPrefs load retracts earlier-process rich OS rows; controls and sound claim survive");
        // Only this disposable package's rows, including our two synthetic controls, are cleaned up.
        for(StatusBarNotification row:manager.getActiveNotifications())manager.cancel(row.getTag(),row.getId());
    }
}

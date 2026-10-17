#!/usr/bin/env python3
"""Execute the real service callback and ledger with deterministic Android API fixtures.

--source checks the previous callback too; fixtures do not assert Android audio/device behavior.
"""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
service = (args.source or root / "app/src/main/java/com/baseer/freshchat/BChatFirebaseMessagingService.java").read_text(encoding="utf-8")


def method(marker):
    start = service.index(marker)
    opening = service.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (service[end] == "{") - (service[end] == "}")
        end += 1
    return service[start:end]


callback = method("public void onMessageReceived(")
text = method("private static String notificationText(") if "private static String notificationText(" in service else ""
context = r"""
package android.content;
public class Context {
 public static final int MODE_PRIVATE=0;
 public Context getApplicationContext(){return this;}
 public SharedPreferences getSharedPreferences(String name,int mode){throw new UnsupportedOperationException();}
}
"""
preferences = r"""
package android.content;
import java.util.Set;
public interface SharedPreferences {
 Set<String> getStringSet(String key,Set<String> fallback);
 Editor edit();
 interface Editor {Editor putStringSet(String key,Set<String> value);boolean commit();}
}
"""
uri = "package android.net; public final class Uri {public static String parse(String value){return value;}}"
push_state = r"""
package com.baseer.freshchat;
import android.content.Context;
/** Deterministic authenticated routing/preference boundary; PushState has separate tests. */
final class BChatPushState {
 interface Presentation {void show(String mode);}
 static final class Delivery {Context context;Delivery(Context c){context=c;}}
 static String EXTRA_ACCOUNT_KEY="account",EXTRA_KIND="kind",EXTRA_EVENT_ID="event";
 static boolean matches(Context c,String account){return NotificationPresentationHarness.ACCOUNT.equals(account);}
 static String previewMode(Context c,String account){return ((NotificationPresentationHarness)c).previewMode;}
 static boolean awaitReady(Context c,long wait){return true;}
 static Delivery delivery(Context c,String key){return matches(c,key)?new Delivery(c):null;}
 static boolean present(Delivery d,Presentation p){
   NotificationPresentationHarness host=(NotificationPresentationHarness)d.context;
   if(host.beforePresent!=null){Runnable once=host.beforePresent;host.beforePresent=null;once.run();}
   p.show(previewMode(d.context,null));return true;
 }
}
"""
channels = r"""
package com.baseer.freshchat;
import android.content.Context;
/** Explicit channel-state adapter; the real channels module has separate behavior tests. */
final class BChatNotificationChannels {
 static NotificationPresentationHarness owner;
 static final class Selection {
   final String channelId;final boolean known;final long revision;
   Selection(String id,boolean k,long r){channelId=id;known=k;revision=r;}
 }
 static void load(Context c){owner=(NotificationPresentationHarness)c;}
 static Selection resolve(String kind){
   String id=owner.separated&&owner.channelKnown?("chat".equals(kind)?"bchat-chat-v1":
       "task".equals(kind)?"bchat-tasks-v1":"order".equals(kind)?"bchat-orders-v1":"bchat-events-v3"):
       "bchat-events-v3";
   return new Selection(id,owner.channelKnown,owner.channelRevision);
 }
 static boolean present(Selection value,Runnable render){
   if(value.revision!=owner.channelRevision||value.known!=owner.channelKnown)return false;
   render.run();return true;
 }
}
"""
harness = r"""
package com.baseer.freshchat;
import android.content.*;
import java.util.*;
public class NotificationPresentationHarness extends Context {
 static final String CHANNEL="bchat-events-v3", ACCOUNT="00000000-0000-4000-8000-000000000001";
 static int checks;
 final Prefs prefs=new Prefs();
 final Map<String,Prefs> named=new HashMap<>();
 final NotificationManager manager=new NotificationManager();
 String previewMode="none";boolean permission=true,channelKnown=true,separated;
 long channelRevision;Runnable beforePresent;
 public SharedPreferences getSharedPreferences(String name,int mode){return name.equals("bchat-presented-events-v1")?prefs:named.computeIfAbsent(name,key->new Prefs());}
 @SuppressWarnings("unchecked") <T> T getSystemService(Class<T> kind){return (T)manager;}
 int checkSelfPermission(String ignored){return permission?PackageManager.PERMISSION_GRANTED:1;}
 String getString(int id){return "private notification";}
 void ensureChannel(NotificationManager manager){}
 static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);checks++;System.out.println("PASS "+label);}
 static class Prefs implements SharedPreferences,SharedPreferences.Editor {
   Set<String> items=new HashSet<>(); boolean writable=true;
   String primary; final Map<String,Set<String>> other=new HashMap<>();
   public Set<String> getStringSet(String key,Set<String> fallback){
     if(primary==null)primary=key;return primary.equals(key)?items:other.getOrDefault(key,fallback);
   }
   public SharedPreferences.Editor edit(){return this;}
   public SharedPreferences.Editor putStringSet(String key,Set<String> value){
     if(primary==null)primary=key;if(writable){if(primary.equals(key))items=new HashSet<>(value);else other.put(key,new HashSet<>(value));}return this;
   }
   public boolean commit(){return writable;}
 }
 static class Manifest {static class permission {static String POST_NOTIFICATIONS="notifications";}}
 static class Build {static class VERSION {static int SDK_INT=35;}}
 static class PackageManager {static int PERMISSION_GRANTED=0;}
 static class RemoteMessage {
   final Map<String,String> data=new HashMap<>();
   RemoteMessage(String kind,String event){data.put("account_key",ACCOUNT);data.put("kind",kind);data.put("event_id",event);
     if("chat".equals(kind)){data.put("presentation_v","1");
       data.put("room_key",NotificationPresentation.roomKey(ACCOUNT,1,1,1));
       data.put("message_key",NotificationPresentation.messageKey(ACCOUNT,1,1,1,Long.parseLong(event)));
       data.put("sent_at_ms",String.valueOf(System.currentTimeMillis()));}
   }
   Map<String,String> getData(){return data;}
 }
 static class Intent {
   static String ACTION_VIEW="view";static int FLAG_ACTIVITY_CLEAR_TOP=1,FLAG_ACTIVITY_SINGLE_TOP=2;
   Intent(Object c,Class<?> a){} void setAction(String a){}void setData(String a){}
   void putExtra(String k,String v){}void addFlags(int f){}
 }
 static class OdooIdentityActivity {}
 static class PendingIntent {
   static int FLAG_UPDATE_CURRENT=1,FLAG_IMMUTABLE=2;
   static PendingIntent getActivity(Object c,int id,Intent i,int f){return new PendingIntent();}
 }
 static class R {
   static class string {static int bchat_push_chat=1,bchat_push_task=2,bchat_push_order=3,bchat_push_attachment=4,bchat_push_diagnostic=5;}
   static class mipmap {static int ic_launcher=1;}
   static class drawable {static int ic_notification=2;}
 }
 static class NotificationChannel {int getImportance(){return 4;}}
 static class Notification {
   static int VISIBILITY_PRIVATE=1,VISIBILITY_PUBLIC=2,GROUP_ALERT_CHILDREN=2,GROUP_ALERT_SUMMARY=1;static String CATEGORY_MESSAGE="message",CATEGORY_REMINDER="reminder";
   String title,text,group,channelId;Notification publicView;int alertBehavior;boolean summary,onlyAlertOnce;
   static class Builder {
     Notification n=new Notification();
     Builder(Object c,String channel){n.channelId=channel;} Builder setSmallIcon(int i){return this;}
     Builder setContentTitle(String s){n.title=s;return this;}Builder setContentText(String s){n.text=s;return this;}
     Builder setContentIntent(PendingIntent p){return this;}Builder setAutoCancel(boolean v){return this;}
     Builder setOnlyAlertOnce(boolean v){n.onlyAlertOnce=v;return this;}Builder setVisibility(int i){return this;}
     Builder setGroup(String v){n.group=v;return this;}Builder setGroupSummary(boolean v){n.summary=v;return this;}
     Builder setGroupAlertBehavior(int v){n.alertBehavior=v;return this;}
     Builder setPublicVersion(Notification v){n.publicView=v;return this;}
     Builder setCategory(String s){return this;}Builder setStyle(BigTextStyle s){return this;}
     Notification build(){return n;}
   }
   static class BigTextStyle {BigTextStyle bigText(String s){return this;}}
 }
 static class NotificationManager {
   static int IMPORTANCE_NONE=0;
   int calls,summaryCalls;boolean fail,blocked,failSummary;Notification last,lastSummary;
   NotificationChannel getNotificationChannel(String channel){return new NotificationChannel();}
   boolean areNotificationsEnabled(){return !blocked;}
   void notify(int id,Notification n){if(fail)throw new SecurityException();calls++;}
   void notify(String tag,int id,Notification n){if(fail||n.summary&&failSummary)throw new SecurityException();
     if(n.summary){summaryCalls++;lastSummary=n;}else{calls++;last=n;}}
 }
 __CALLBACK__
 __TEXT__
 public static void main(String[] args){
   NotificationPresentationHarness first=new NotificationPresentationHarness();
   first.onMessageReceived(new RemoteMessage("chat","41"));
   first.onMessageReceived(new RemoteMessage("chat","41"));
   check(first.manager.calls==1,"Repeated provider event is presented once");
   check(first.manager.summaryCalls==1&&first.manager.lastSummary.alertBehavior==Notification.GROUP_ALERT_CHILDREN,
     "Generic group summary is independently silent on an audible channel");
   check(first.manager.last.alertBehavior==Notification.GROUP_ALERT_CHILDREN&&!first.manager.last.onlyAlertOnce,
     "First durable message claim may use the system alert route");
   first.onMessageReceived(new RemoteMessage("task","41"));
   check(first.manager.calls==2,"Same event ID in another kind is independent");
   check(first.manager.last.onlyAlertOnce,"Task retains its prior only-alert-once behavior");
   NotificationPresentationHarness unretiredTask=new NotificationPresentationHarness();unretiredTask.prefs.writable=false;
   unretiredTask.onMessageReceived(new RemoteMessage("task","71"));
   unretiredTask.onMessageReceived(new RemoteMessage("task","71"));
   check(unretiredTask.manager.calls==2&&unretiredTask.manager.last.onlyAlertOnce,
     "Lost shown receipt still updates an already visible task with only-alert-once");
   NotificationPresentationHarness restarted=new NotificationPresentationHarness();
   restarted.prefs.items=new HashSet<>(first.prefs.items);
   restarted.onMessageReceived(new RemoteMessage("chat","41"));
   check(restarted.manager.calls==0,"Receipt survives service/process recreation");
   NotificationPresentationHarness failed=new NotificationPresentationHarness();
   failed.manager.fail=true;
   failed.onMessageReceived(new RemoteMessage("chat","42"));
   failed.manager.fail=false;
   failed.onMessageReceived(new RemoteMessage("chat","42"));
   check(failed.manager.calls==1,"Failed presentation is not retired");
   RemoteMessage foreign=new RemoteMessage("chat","43");foreign.data.put("account_key","foreign");
   first.onMessageReceived(foreign);
   check(first.manager.calls==2,"Account route is verified before presentation");
   String other="00000000-0000-4000-8000-000000000002";
   check(!BChatNotificationLedger.key(ACCOUNT,"chat","1").equals(BChatNotificationLedger.key(other,"chat","1")),"Ledger keys isolate accounts");
   NotificationPresentationHarness bounded=new NotificationPresentationHarness();
   long now=1000000000L;
   for(int i=1;i<=600;i++)BChatNotificationLedger.recordShown(bounded,BChatNotificationLedger.key(ACCOUNT,"chat",String.valueOf(i)),now+i);
   check(bounded.prefs.items.size()==512,"Presentation ledger has a hard count bound");
   check(!BChatNotificationLedger.contains(bounded,BChatNotificationLedger.key(ACCOUNT,"chat","600"),now+601+BChatNotificationLedger.MAX_AGE_MILLIS),"Expired presentation receipt is not retained indefinitely");
   bounded.prefs.items.add("broken|not-a-time");
   check(BChatNotificationLedger.contains(bounded,BChatNotificationLedger.key(ACCOUNT,"chat","600"),now+700),"Malformed receipt does not break valid receipts");
   check(BChatNotificationLedger.contains(bounded,BChatNotificationLedger.key(ACCOUNT,"chat","600"),now-1),"Backwards clock does not replay a recent event");
   RemoteMessage privateMessage=new RemoteMessage("chat","51");
   privateMessage.data.put("sender_name","Secret sender");privateMessage.data.put("message_preview","Private text");
   privateMessage.data.put("sender_key",NotificationPresentation.senderKey(ACCOUNT,1,1,1,2));
   privateMessage.data.put("conversation_title","Secret room");privateMessage.data.put("is_group","true");
   NotificationPresentationHarness none=new NotificationPresentationHarness();none.onMessageReceived(privateMessage);
   check(none.manager.last.title.equals("BChat")&&none.manager.last.text.equals("private notification"),"Local none strips even a stale full payload");
   NotificationPresentationHarness sender=new NotificationPresentationHarness();sender.previewMode="sender";sender.onMessageReceived(privateMessage);
   check(sender.manager.last.title.equals("Secret sender")&&!sender.manager.last.text.equals("Private text"),"Sender mode never displays message preview");
   NotificationPresentationHarness full=new NotificationPresentationHarness();full.previewMode="full";full.onMessageReceived(privateMessage);
   check(full.manager.last.title.equals("Secret sender")&&full.manager.last.text.equals("Private text"),"Explicit full permits filtered preview");
   check(full.manager.last.publicView.title.equals("BChat")&&full.manager.last.publicView.text.equals("private notification"),"Public lockscreen version remains generic");
   RemoteMessage legacy=new RemoteMessage("chat","52");legacy.data.remove("presentation_v");
   legacy.data.put("sender_name","Old sender");legacy.data.put("message_preview","Old private text");
   full.onMessageReceived(legacy);
   check(full.manager.last.title.equals("BChat")&&full.manager.last.text.equals("private notification")
     &&full.manager.last.alertBehavior==Notification.GROUP_ALERT_SUMMARY&&full.manager.last.onlyAlertOnce,
     "Old or incomplete chat payload is generic and silent, not guessed identity");
   RemoteMessage duplicateMessage=new RemoteMessage("chat","53");
   String messageKey=duplicateMessage.data.get("message_key");
   BChatNotificationLedger.claimSound(full,ACCOUNT,messageKey,Long.parseLong(duplicateMessage.data.get("sent_at_ms")),
     System.currentTimeMillis(),"soft");
   full.onMessageReceived(duplicateMessage);
   check(full.manager.last.alertBehavior==Notification.GROUP_ALERT_SUMMARY,
     "A live-reserved message cannot acquire a second FCM sound route");
   String uuid="00000000-0000-4000-8000-000000000004";
   RemoteMessage test=new RemoteMessage("diagnostic","61");test.data.put("diagnostic_uuid",uuid);
   NotificationPresentationHarness denied=new NotificationPresentationHarness();denied.permission=false;denied.onMessageReceived(test);
   BChatNotificationDiagnostics.Receipt received=BChatNotificationDiagnostics.read(denied,ACCOUNT,"61",uuid,System.currentTimeMillis());
   check(received!=null&&received.receivedAt>0&&received.displayedAt==0&&received.outcome.equals("permission_denied"),"Denied notification permission still records device reception, not display");
   denied.permission=true;denied.onMessageReceived(test);denied.onMessageReceived(test);
   received=BChatNotificationDiagnostics.read(denied,ACCOUNT,"61",uuid,System.currentTimeMillis());
   check(denied.manager.calls==1&&received.displayedAt>0&&received.outcome.equals("displayed"),"Diagnostic retry/duplicate preserves first display receipt");
   NotificationPresentationHarness blocked=new NotificationPresentationHarness();blocked.manager.blocked=true;blocked.onMessageReceived(test);
   received=BChatNotificationDiagnostics.read(blocked,ACCOUNT,"61",uuid,System.currentTimeMillis());
   check(blocked.manager.calls==0&&received.outcome.equals("channel_blocked")&&received.displayedAt==0,"Channel/application block is separate from reception");
   NotificationPresentationHarness failedTest=new NotificationPresentationHarness();failedTest.manager.fail=true;failedTest.onMessageReceived(test);
   received=BChatNotificationDiagnostics.read(failedTest,ACCOUNT,"61",uuid,System.currentTimeMillis());
   check(received.displayedAt==0&&received.outcome.equals("presentation_failed"),"notify failure is not a displayed test");
   NotificationPresentationHarness failedSummary=new NotificationPresentationHarness();failedSummary.manager.failSummary=true;
   failedSummary.onMessageReceived(test);
   received=BChatNotificationDiagnostics.read(failedSummary,ACCOUNT,"61",uuid,System.currentTimeMillis());
   check(failedSummary.manager.calls==1&&failedSummary.manager.summaryCalls==0
     &&received.displayedAt>0&&received.outcome.equals("displayed"),
     "Summary-only failure does not undo accepted child diagnostics");
   failedSummary.onMessageReceived(test);
   check(failedSummary.manager.calls==1&&BChatNotificationLedger.contains(failedSummary,
     BChatNotificationLedger.key(ACCOUNT,"diagnostic","61"),System.currentTimeMillis()),
     "Accepted child is retired even when best-effort summary failed");
   NotificationPresentationHarness diagRestart=new NotificationPresentationHarness();diagRestart.named.putAll(denied.named);
   check(BChatNotificationDiagnostics.read(diagRestart,ACCOUNT,"61",uuid,System.currentTimeMillis()).displayedAt>0,"Diagnostic receipt survives process recreation");
   check(BChatNotificationDiagnostics.read(diagRestart,other,"61",uuid,System.currentTimeMillis())==null,"Another account cannot see local test receipt");
   RemoteMessage invalidTest=new RemoteMessage("diagnostic","62");invalidTest.data.put("diagnostic_uuid","not-a-uuid");denied.onMessageReceived(invalidTest);
   check(denied.manager.calls==1,"Malformed diagnostic cannot display or enter ledger");
   NotificationPresentationHarness split=new NotificationPresentationHarness();split.separated=true;
   split.onMessageReceived(new RemoteMessage("chat","71"));
   check(split.manager.last.channelId.equals("bchat-chat-v1"),"Chat uses the explicit committed messages channel");
   split.onMessageReceived(new RemoteMessage("task","72"));
   check(split.manager.last.channelId.equals("bchat-tasks-v1"),"Task uses the explicit committed tasks channel");
   split.onMessageReceived(new RemoteMessage("order","73"));
   check(split.manager.last.channelId.equals("bchat-orders-v1"),"Order uses the explicit committed orders channel");
   split.onMessageReceived(test);
   check(split.manager.last.channelId.equals("bchat-events-v3"),"Diagnostic remains on the original channel after split opt-in");
   NotificationPresentationHarness unknown=new NotificationPresentationHarness();unknown.channelKnown=false;
   unknown.previewMode="full";unknown.onMessageReceived(privateMessage);
   check(unknown.manager.last.channelId.equals("bchat-events-v3")&&unknown.manager.last.title.equals("BChat")
     &&unknown.manager.last.text.equals("private notification")
     &&unknown.manager.last.alertBehavior==Notification.GROUP_ALERT_SUMMARY,
     "Unknown channel preference renders generic silent legacy fallback even with a full payload");
   unknown.onMessageReceived(new RemoteMessage("task","74"));
   check(unknown.manager.last.alertBehavior==Notification.GROUP_ALERT_SUMMARY,
     "Unknown channel routing cannot make non-chat events audible");
   NotificationPresentationHarness changedRoute=new NotificationPresentationHarness();
   changedRoute.beforePresent=()->{changedRoute.channelRevision++;changedRoute.separated=true;};
   changedRoute.onMessageReceived(new RemoteMessage("chat","75"));
   check(changedRoute.manager.calls==0&&!BChatNotificationLedger.contains(changedRoute,
     BChatNotificationLedger.key(ACCOUNT,"chat","75"),System.currentTimeMillis()),
     "Routing changed after selection rejects final presentation without retiring the event");
   changedRoute.onMessageReceived(new RemoteMessage("chat","75"));
   check(changedRoute.manager.calls==1&&changedRoute.manager.last.channelId.equals("bchat-chat-v1")
     &&changedRoute.manager.last.alertBehavior==Notification.GROUP_ALERT_SUMMARY,
     "Retry uses current routing and cannot replay an already reserved sound");
   NotificationPresentationHarness diagBound=new NotificationPresentationHarness();
   for(int i=1;i<=40;i++)BChatNotificationDiagnostics.record(diagBound,ACCOUNT,String.valueOf(i),uuid,"received",now+i);
   Prefs diagnosticPrefs=diagBound.named.get("bchat-notification-diagnostics-v1");
   check(diagnosticPrefs.items.size()==32,"Diagnostic receipt count hard bound 32");
   check(BChatNotificationDiagnostics.read(diagBound,ACCOUNT,"40",uuid,now+41+BChatNotificationDiagnostics.MAX_AGE_MILLIS)==null,"Diagnostic receipts expire after seven days");
   System.out.println("PASS "+checks+" callback/ledger checks; Android audio/device NOT executed");
 }
}
"""
harness = harness.replace("__CALLBACK__", callback).replace("__TEXT__", text)
temp_root = (root / "artifacts/test-runtime").resolve()
temp_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="bchat-presentation-", dir=temp_root) as folder:
    target = Path(folder)
    files = {
        "android/content/Context.java": context,
        "android/content/SharedPreferences.java": preferences,
        "android/net/Uri.java": uri,
        "com/baseer/freshchat/BChatPushState.java": push_state,
        "com/baseer/freshchat/BChatNotificationChannels.java": channels,
        "com/baseer/freshchat/NotificationPresentationHarness.java": harness,
    }
    for relative, value in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    ledger = root / "app/src/main/java/com/baseer/freshchat/BChatNotificationLedger.java"
    diagnostic = root / "app/src/main/java/com/baseer/freshchat/BChatNotificationDiagnostics.java"
    contract = root / "app/src/main/java/com/baseer/freshchat/NotificationPresentation.java"
    sources = [str(path) for path in target.rglob("*.java")] + [str(ledger), str(diagnostic), str(contract)]
    subprocess.run([shutil.which("javac") or "javac", "-encoding", "UTF-8", "-d", str(target), *sources], check=True)
    subprocess.run([shutil.which("java") or "java", "-cp", str(target), "com.baseer.freshchat.NotificationPresentationHarness"], check=True)

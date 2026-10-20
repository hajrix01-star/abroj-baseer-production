package com.baseer.bwork.notifications;
import android.Manifest;
import android.app.*;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;
import java.util.Map;
/** Generic, short native work only. Never fetches a session, message, media, task or outbox. */
public final class BWorkMessagingService extends FirebaseMessagingService {
  public void onNewToken(String token){PushState.token(this,token);}
  public void onMessageReceived(RemoteMessage message){
    if(PushState.foreground)return; // Foreground chat owns its existing feedback; no duplicate alert.
    if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return;
    Map<String,String> data=message.getData();String account=data.get("account_key"),kind=data.get("kind"),event=data.get("event_id");
    String route=PushPolicy.notificationUri(account,kind,event);
    NotificationManager manager=getSystemService(NotificationManager.class);Intent open=getPackageManager().getLaunchIntentForPackage(getPackageName());
    if(manager==null||!manager.areNotificationsEnabled()||open==null||route==null||!PushState.accept(this,account,kind,event))return;
    if(Build.VERSION.SDK_INT>=26){NotificationChannel channel=new NotificationChannel("bwork-events-v1","BWork",NotificationManager.IMPORTANCE_HIGH);channel.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);manager.createNotificationChannel(channel);}
    open.setAction(Intent.ACTION_VIEW).setData(Uri.parse(route)).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
    PendingIntent intent=PendingIntent.getActivity(this,(kind+event).hashCode(),open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    String body=PushPolicy.body(PushState.arabic(this),kind);
    Notification.Builder builder=Build.VERSION.SDK_INT>=26?new Notification.Builder(this,"bwork-events-v1"):new Notification.Builder(this);
    Notification n=builder.setSmallIcon(getApplicationInfo().icon).setContentTitle(PushState.arabic(this)?"بيورك":"BWork").setContentText(body).setContentIntent(intent).setAutoCancel(true).setOnlyAlertOnce(true).setVisibility(Notification.VISIBILITY_PRIVATE).build();
    manager.notify("bwork:"+account+":"+kind+":"+event,0,n);
  }
}

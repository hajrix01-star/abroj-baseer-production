package com.baseer.bchat.trial.notifications;
import android.Manifest;
import android.os.Build;
import android.app.Activity;
import android.app.NotificationManager;
import android.app.NotificationChannel;
import android.content.pm.PackageManager;
import com.facebook.react.bridge.*;
import com.facebook.react.modules.core.PermissionAwareActivity;

public final class BWorkNotificationsModule extends ReactContextBaseJavaModule implements LifecycleEventListener {
  public BWorkNotificationsModule(ReactApplicationContext c){super(c);c.addLifecycleEventListener(this);}
  public void onHostResume(){PushState.foreground=true;}
  public void onHostPause(){PushState.foreground=false;}
  public void onHostDestroy(){PushState.foreground=false;}
  public String getName(){return "BWorkNotifications";}
  private boolean granted(){NotificationManager manager=getReactApplicationContext().getSystemService(NotificationManager.class);if(manager==null||!manager.areNotificationsEnabled())return false;if(Build.VERSION.SDK_INT>=26){NotificationChannel channel=manager.getNotificationChannel("bwork-events-v1");if(channel!=null&&channel.getImportance()==NotificationManager.IMPORTANCE_NONE)return false;}return Build.VERSION.SDK_INT<33||getReactApplicationContext().checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED;}
  @ReactMethod public void status(Promise p){WritableMap v=Arguments.createMap();v.putBoolean("configured",PushBackend.configured());v.putBoolean("enabled",PushState.enabled(getReactApplicationContext()));v.putBoolean("granted",granted());v.putString("scope",PushState.scope(getReactApplicationContext()));v.putString("accountKey",PushState.account(getReactApplicationContext()));v.putString("installationId",PushState.existingInstallation(getReactApplicationContext()));p.resolve(v);}
  @ReactMethod(isBlockingSynchronousMethod=true) public boolean clearNow(){synchronized(PushState.class){boolean ok=PushState.clear(getReactApplicationContext());PushBackend.suspend();return ok;}}
  @ReactMethod public void language(String value){PushState.language(getReactApplicationContext(),value);}
  @ReactMethod public void enable(Promise p){if(!PushBackend.configured()){p.resolve(false);return;}long epoch=PushState.epoch(getReactApplicationContext());Activity a=getCurrentActivity();if(a==null){p.resolve(false);return;}a.runOnUiThread(()->{if(PushState.epoch(getReactApplicationContext())!=epoch){p.resolve(false);return;}if(granted()){finishEnable(p,epoch);return;}if(Build.VERSION.SDK_INT<33||getReactApplicationContext().checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED||!(a instanceof PermissionAwareActivity)){p.resolve(false);return;}((PermissionAwareActivity)a).requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},29081,(request,permissions,results)->{if(request!=29081)return false;if(granted())finishEnable(p,epoch);else p.resolve(false);return true;});});}
  private void finishEnable(Promise p,long epoch){p.resolve(PushState.finishEnable(getReactApplicationContext(),epoch));}
  @ReactMethod public void disable(Promise p){synchronized(PushState.class){PushState.clear(getReactApplicationContext());PushBackend.disable();}p.resolve(null);}
  @ReactMethod public void token(Promise p){
    boolean started=PushCallbacks.begin(PushState.class,()->PushState.epoch(getReactApplicationContext()),
      ()->PushBackend.configured()&&PushState.enabled(getReactApplicationContext())&&granted(),
      expected->PushBackend.token(new PushBackend.TokenCallback(){
        public void token(String token){synchronized(PushState.class){
          if(!PushState.finishToken(getReactApplicationContext(),expected,token)){p.resolve(null);return;}
          WritableMap v=Arguments.createMap();v.putString("installationId",PushState.installation(getReactApplicationContext()));
          v.putString("token",token);v.putDouble("nativeEpoch",PushState.epoch(getReactApplicationContext()));p.resolve(v);
        }}
        public void failed(){p.reject("push_unavailable","Notifications unavailable");}
      }));
    if(!started)p.resolve(null);
  }
  @ReactMethod public void bind(String scope,String install,String token,String key,double epoch,Promise p){p.resolve(granted()&&PushState.bind(getReactApplicationContext(),scope,install,token,key,(long)epoch));}
}

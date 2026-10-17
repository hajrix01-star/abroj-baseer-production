package com.baseer.freshchat;

import android.app.Instrumentation;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.Build;
import android.os.Bundle;
import android.os.Looper;
import android.os.VibrationEffect;
import android.media.AudioAttributes;
import java.util.Arrays;
import java.util.Objects;

/** Actual SDK35 NotificationManager/Channel + SharedPreferences. No notification is posted or sounded. */
public final class ChannelInstrumentation extends Instrumentation {
    private int checks;
    private String phase;
    private void check(boolean value){++checks;if(!value)throw new AssertionError("Native channel assertion "+checks);}
    private static final BChatNotificationChannels.Names NAMES=new BChatNotificationChannels.Names("Messages","Tasks","Orders");
    @Override public void onCreate(Bundle args){super.onCreate(args);phase=args.getString("phase","all");start();}
    @Override public void onStart(){
        Bundle result=new Bundle();Context context=getContext();
        try{
            if(!"com.baseer.freshchat.channels.test".equals(context.getPackageName()))throw new IllegalStateException("Refusing non-test namespace");
            check(Looper.myLooper()!=Looper.getMainLooper());check(Build.VERSION.SDK_INT>=35);
            NotificationManager manager=context.getSystemService(NotificationManager.class);check(manager!=null);
            BChatNotificationChannels.Selection cold=BChatNotificationChannels.resolve("chat");
            check(!cold.known&&cold.channelId.equals(BChatNotificationChannels.LEGACY));
            if("verify-restart".equals(phase)){
                BChatNotificationChannels.Snapshot restored=BChatNotificationChannels.load(context);
                check(restored.known&&restored.separated);
                check(BChatNotificationChannels.resolve("chat").channelId.equals(BChatNotificationChannels.CHAT));
                check(BChatNotificationChannels.resolve("task").channelId.equals(BChatNotificationChannels.TASKS));
                check(BChatNotificationChannels.resolve("order").channelId.equals(BChatNotificationChannels.ORDERS));
                check(manager.getNotificationChannel(BChatNotificationChannels.TASKS)!=null);
            }else if("all".equals(phase)){
                // Start this phase only in a newly installed disposable package: deleting/recreating Android
                // channels can restore their old settings, so this fixture never claims such a reset is fresh.
                check(manager.getNotificationChannel(BChatNotificationChannels.LEGACY)==null);
                BChatNotificationChannels.Snapshot initial=BChatNotificationChannels.load(context);
                check(initial.known&&!initial.separated);
                BChatNotificationChannels.Result noBaseline=BChatNotificationChannels.setSeparated(context,true,NAMES);
                check(!noBaseline.accepted&&noBaseline.code.equals("baseline_missing"));
                NotificationChannel baseline=new NotificationChannel(BChatNotificationChannels.LEGACY,"BChat",NotificationManager.IMPORTANCE_DEFAULT);
                baseline.setSound(null,new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION).build());
                baseline.setVibrationEffect(VibrationEffect.createWaveform(new long[]{0,33,20,55},-1));
                baseline.enableVibration(false); // Non-null observed effect must NOT implicitly unmute migrated channels.
                baseline.setShowBadge(false);baseline.enableLights(false);manager.createNotificationChannel(baseline);
                NotificationChannel existing=new NotificationChannel(BChatNotificationChannels.CHAT,"Existing user choice",NotificationManager.IMPORTANCE_LOW);
                existing.setSound(null,null);existing.enableVibration(false);manager.createNotificationChannel(existing);
                baseline=manager.getNotificationChannel(BChatNotificationChannels.LEGACY);
                existing=manager.getNotificationChannel(BChatNotificationChannels.CHAT);
                check(baseline.getVibrationEffect()!=null&&!baseline.shouldVibrate());
                BChatNotificationChannels.Selection previous=BChatNotificationChannels.resolve("chat");
                BChatNotificationChannels.Result selected=BChatNotificationChannels.setSeparated(context,true,NAMES);
                check(selected.accepted&&selected.changed&&selected.state.separated);
                check(!BChatNotificationChannels.present(previous,()->{throw new AssertionError("Stale selection posted");}));
                NotificationChannel stillExisting=manager.getNotificationChannel(BChatNotificationChannels.CHAT);
                check(stillExisting.getName().toString().equals(existing.getName().toString()));
                check(stillExisting.getImportance()==existing.getImportance());
                check(Objects.equals(stillExisting.getSound(),existing.getSound())&&!stillExisting.shouldVibrate());
                for(String id:Arrays.asList(BChatNotificationChannels.TASKS,BChatNotificationChannels.ORDERS)){
                    NotificationChannel copied=manager.getNotificationChannel(id);check(copied!=null);
                    check(copied.getImportance()==baseline.getImportance());
                    check(Objects.equals(copied.getSound(),baseline.getSound()));
                    check(Objects.equals(copied.getAudioAttributes(),baseline.getAudioAttributes()));
                    check(copied.shouldVibrate()==baseline.shouldVibrate()&&!copied.shouldVibrate());
                    check(Objects.equals(copied.getVibrationEffect(),baseline.getVibrationEffect()));
                    check(Arrays.equals(copied.getVibrationPattern(),baseline.getVibrationPattern()));
                    check(!copied.canBypassDnd());
                }
                BChatNotificationChannels.Selection current=BChatNotificationChannels.resolve("chat");
                boolean[] presented={false};check(BChatNotificationChannels.present(current,()->presented[0]=true)&&presented[0]);
                check(BChatNotificationChannels.setSeparated(context,false,null).accepted&&!BChatNotificationChannels.state().separated);
                check(manager.getNotificationChannel(BChatNotificationChannels.CHAT)!=null
                        &&manager.getNotificationChannel(BChatNotificationChannels.TASKS)!=null
                        &&manager.getNotificationChannel(BChatNotificationChannels.ORDERS)!=null);
                check(BChatNotificationChannels.resolve("diagnostic").channelId.equals(BChatNotificationChannels.LEGACY));
                check(BChatNotificationChannels.setSeparated(context,true,NAMES).accepted);
                check(manager.getNotificationChannel(BChatNotificationChannels.CHAT).getName().toString().equals("Existing user choice"));
                check(!manager.getNotificationChannel(BChatNotificationChannels.LEGACY).shouldVibrate()
                        &&manager.getNotificationChannel(BChatNotificationChannels.LEGACY).getSound()==null);
            }else throw new IllegalArgumentException("Unknown isolated phase");
            result.putString("stream","PASS: "+checks+" real Android35 channel/prefs checks; phase="+phase+"; no notify/audio/FCM/OEM claim\n");finish(0,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error+" at "+Arrays.toString(error.getStackTrace())+"\n");finish(1,result);}
    }
}

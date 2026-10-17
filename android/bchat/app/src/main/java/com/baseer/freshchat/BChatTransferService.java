package com.baseer.freshchat;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.os.Build;

/** Only the explicit user-visible Android26–33 fallback; never a UIDT-denial bypass. */
public final class BChatTransferService extends Service {
    private int activeId;
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent==null){stopSelf(startId);return START_NOT_STICKY;}
        BChatTransferCoordinator coordinator=BChatTransferCoordinator.get(this);
        int id=intent.getIntExtra(BChatTransferCoordinator.EXTRA_ID,0);
        if(BChatTransferCoordinator.ACTION_STOP.equals(intent.getAction())){
            coordinator.stop(id);stopSelf(startId);return START_NOT_STICKY;
        }
        if(Build.VERSION.SDK_INT>=34||!coordinator.contains(id)){stopSelf(startId);return START_NOT_STICKY;}
        try{
            startForeground(id,coordinator.notification(id));activeId=id;
            coordinator.start(id,()->{activeId=0;stopForeground(STOP_FOREGROUND_REMOVE);stopSelf(startId);});
        }catch(RuntimeException denied){coordinator.stop(id);stopSelf(startId);}
        return START_NOT_STICKY;
    }
    @Override public void onTimeout(int startId,int type){
        if(activeId!=0)BChatTransferCoordinator.get(this).stop(activeId);stopSelf(startId);
    }
    @Override public void onDestroy(){
        if(activeId!=0)BChatTransferCoordinator.get(this).stop(activeId);super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent){return null;}
}

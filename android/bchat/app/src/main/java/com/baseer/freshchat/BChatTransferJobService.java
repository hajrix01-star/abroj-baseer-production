package com.baseer.freshchat;

import android.app.job.JobParameters;
import android.app.job.JobService;
import android.os.Build;

/** Android34+ UIDT: the OS envelope never contains session/capability material. */
public final class BChatTransferJobService extends JobService {
    @Override public boolean onStartJob(JobParameters params){
        if(Build.VERSION.SDK_INT<34)return false;
        BChatTransferCoordinator coordinator=BChatTransferCoordinator.get(this);
        int id=params.getExtras().getInt(BChatTransferCoordinator.EXTRA_ID,0);
        if(!coordinator.contains(id))return false; // process death waits for fresh foreground authentication.
        try{
            setNotification(params,id,coordinator.notification(id),JOB_END_NOTIFICATION_POLICY_REMOVE);
            coordinator.start(id,()->jobFinished(params,false));return true;
        }catch(RuntimeException denied){coordinator.stop(id);return false;}
    }
    @Override public boolean onStopJob(JobParameters params){
        BChatTransferCoordinator.get(this).stop(params.getExtras().getInt(BChatTransferCoordinator.EXTRA_ID,0));
        return false; // no token renewal, auto-retry or hidden WebView.
    }
}

package com.baseer.freshchat;

import android.app.Activity;
import android.app.Instrumentation;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.Context;
import android.content.Intent;
import android.net.NetworkCapabilities;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import com.baseer.freshchat.sync.*;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Real Android35 SQLite/JobScheduler/JobService/notification; only HTTP is a declared fake. */
public final class TransferInstrumentation extends Instrumentation{
    private int checks;private Activity surface;
    private void check(boolean condition){checks++;if(!condition)throw new AssertionError("Transfer "+checks+" at "+new Throwable().getStackTrace()[1]);}
    private void drain()throws Exception{CountDownLatch done=new CountDownLatch(1);
        BChatStorageRepository.submit(null,()->true,(ok,error)->done.countDown());check(done.await(5,TimeUnit.SECONDS));}
    private Activity visible(Context context)throws Exception{
        Activity activity=startActivitySync(new Intent(context,TransferTestSurface.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        long until=System.currentTimeMillis()+5000;while(!activity.hasWindowFocus()&&System.currentTimeMillis()<until)Thread.sleep(25);
        check(activity.hasWindowFocus());return activity;
    }
    static BChatConnectedMediaStore.Entry fixture(Context context,AccountScope scope)throws Exception{
        String uuid=UUID.randomUUID().toString();byte[] data="synthetic transfer bytes".getBytes(StandardCharsets.UTF_8);
        File dir=new File(context.getFilesDir(),"bchat-v2-media/"+scope.key);dir.mkdirs();StringBuilder hex=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(data))hex.append(String.format(Locale.ROOT,"%02x",b&255));
        JSONObject json=new JSONObject().put("account_key",scope.key).put("room_id",17).put("membership_id",8).put("company_id",3)
                .put("upload_uuid",uuid).put("client_uuid",UUID.randomUUID().toString()).put("kind","image")
                .put("mime","image/jpeg").put("name","synthetic.jpg").put("size",data.length).put("sha256",hex.toString())
                .put("text","").put("reply_to_message_id",0).put("media_id",0);
        try(FileOutputStream out=new FileOutputStream(new File(dir,uuid+".bin"))){out.write(data);}
        try(FileOutputStream out=new FileOutputStream(new File(dir,uuid+".json"))){out.write(json.toString().getBytes(StandardCharsets.UTF_8));}
        return new BChatConnectedMediaStore(context).lookup(scope,uuid);
    }
    private int jobId(Context context)throws Exception{
        for(JobInfo info:context.getSystemService(JobScheduler.class).getAllPendingJobs()){
            if(!info.getService().getClassName().equals(BChatTransferJobService.class.getName()))continue;
            check(info.isUserInitiated());check(!info.isPersisted());
            check(!info.getRequiredNetwork().hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN));
            check(!info.getRequiredNetwork().hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED));
            check(!info.getRequiredNetwork().hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED));
            check(info.getExtras().keySet().equals(Collections.singleton(BChatTransferCoordinator.EXTRA_ID)));
            check(info.getEstimatedNetworkUploadBytes()>0);return info.getId();
        }
        return 0;
    }
    private void force(Context context,int id)throws Exception{
        // Shell identity is limited to the synthetic package's already-scheduled test job.
        try(ParcelFileDescriptor descriptor=getUiAutomation().executeShellCommand("cmd jobscheduler run -f -s "+context.getPackageName()+" "+id);
            InputStream input=new ParcelFileDescriptor.AutoCloseInputStream(descriptor)){
            byte[] buffer=new byte[1024];while(input.read(buffer)!=-1){} }
    }
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();Context app=getTargetContext();BChatV2Outbox box=null;
        try{
            check(app.getPackageName().equals("com.baseer.freshchat.transfer.test"));
            checks+=TransferFallbackProbe.run();
            app.deleteDatabase("bchat-v2-text-outbox.db");box=new BChatV2Outbox(app);
            AccountScope scope=new AccountScope("https://synthetic.invalid","synthetic",71);
            BChatConnectedMediaStore store=new BChatConnectedMediaStore(app);BChatTransferCoordinator coordinator=BChatTransferCoordinator.get(app);
            surface=visible(app);
            BChatConnectedMediaStore.Entry entry=fixture(app,scope);box.tickets().admitMedia(scope,entry,false);
            BChatSendTickets.Ticket claim=box.tickets().claimMediaHead(scope,17,8,UUID.randomUUID().toString(),System.currentTimeMillis());
            coordinator.authorize(scope,Collections.singleton(BChatTransferCoordinator.roomKey(17,8,3)));
            final boolean[] accepted={true};File source=store.file(scope,entry);String secret=String.join("",Collections.nCopies(43,"x"));
            runOnMainSync(()->accepted[0]=coordinator.schedule(scope,claim,entry,source,UUID.randomUUID().toString(),secret,()->false));
            check(!accepted[0]&&app.getSystemService(JobScheduler.class).getAllPendingJobs().isEmpty());
            check(BChatNativeMediaUploader.calls.get()==0);check(box.tickets().defer(scope,claim));
            BChatSendTickets.Ticket actual=box.tickets().claimMediaHead(scope,17,8,UUID.randomUUID().toString(),System.currentTimeMillis());
            check(actual!=null&&"sending".equals(actual.state));
            check(actual.matches(entry)&&scope.key.equals(entry.accountKey));
            check(!coordinator.isBusy());
            BChatNativeMediaUploader.reset(entry.uploadUuid);
            runOnMainSync(()->accepted[0]=coordinator.schedule(scope,actual,entry,source,UUID.randomUUID().toString(),secret,()->surface.hasWindowFocus()));
            check(accepted[0]);int id=jobId(app);check(id>0);
            force(app,id);check(BChatNativeMediaUploader.began.await(5,TimeUnit.SECONDS));check(BChatNativeMediaUploader.calls.get()==1);
            // Actual Activity replacement while the process-owned fake byte stream is still blocked.
            runOnMainSync(()->surface.finish());surface=visible(app);
            CountDownLatch changed=new CountDownLatch(1);
            BChatTransferCoordinator.Observer observer=(key,room,member)->changed.countDown();coordinator.observe(observer);
            BChatNativeMediaUploader.release.countDown();check(changed.await(5,TimeUnit.SECONDS));drain();
            check(store.lookup(scope,entry.uploadUuid).mediaId==901);
            check("uploaded".equals(box.tickets().find(scope,"media",entry.clientUuid).state));
            check(!box.tickets().receipt(scope,claim,991)); // cancelled/older pre-schedule claim cannot ACK.
            check(BChatNativeMediaUploader.calls.get()==1);coordinator.unobserve(observer);
            check(box.tickets().receipt(scope,actual,992));BChatSendTickets.Ticket receipt=box.tickets().find(scope,"media",entry.clientUuid);
            check(box.tickets().retireMedia(scope,receipt,()->store.retireReceipted(scope,entry.uploadUuid,receipt.fingerprint)));
            // Revocation cancels only the captured owner and cannot produce a successful upload.
            BChatConnectedMediaStore.Entry second=fixture(app,scope);box.tickets().admitMedia(scope,second,false);
            BChatSendTickets.Ticket secondClaim=box.tickets().claimMediaHead(scope,17,8,UUID.randomUUID().toString(),System.currentTimeMillis());
            BChatNativeMediaUploader.reset(second.uploadUuid);File secondSource=store.file(scope,second);
            runOnMainSync(()->accepted[0]=coordinator.schedule(scope,secondClaim,second,secondSource,UUID.randomUUID().toString(),secret,()->surface.hasWindowFocus()));
            check(accepted[0]);id=jobId(app);force(app,id);check(BChatNativeMediaUploader.began.await(5,TimeUnit.SECONDS));
            coordinator.revoke(scope);drain();check(store.lookup(scope,second.uploadUuid).mediaId==0);
            check(!"uploaded".equals(box.tickets().find(scope,"media",second.clientUuid).state));
            check(!box.tickets().receipt(scope,secondClaim,999));
            // A cold JobService with no RAM capability is inert even when an opaque old integer survives.
            check(!coordinator.contains(123456789));check(!coordinator.isBusy());
            box.purgeAccount(scope);store.purgeAccount(scope);
            result.putString("stream","PASS: "+checks+" transfer assertions; real Android35 UIDT/SQLite/activity replacement; HTTP fake; no API26/OEM/network claim\n");finish(0,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n");finish(1,result);}
        finally{if(box!=null)box.close();if(surface!=null)runOnMainSync(()->surface.finish());}
    }
}

package com.baseer.freshchat;
import android.app.Instrumentation;
import android.content.Context;
import android.net.Uri;
import android.os.Bundle;
import com.baseer.freshchat.sync.*;
import java.io.*;
import java.util.concurrent.*;

/** Real Android SQLite/private store and serial lane; controlled synthetic SAF, no HTTP. */
public final class StageAdmissionInstrumentation extends Instrumentation{
    private String scenario;private int checks;
    private void check(boolean condition){checks++;if(!condition)throw new AssertionError("Stage "+scenario+" "+checks);}
    private <T>T serial(BChatStorageRepository.Work<T> work)throws Exception{
        CountDownLatch done=new CountDownLatch(1);Object[] result={null};Exception[] problem={null};
        BChatStorageRepository.submit(null,work,(value,error)->{result[0]=value;problem[0]=error;done.countDown();});
        if(!done.await(5,TimeUnit.SECONDS))throw new AssertionError("Serial lane timed out");
        if(problem[0]!=null)throw problem[0];return (T)result[0];
    }
    @Override public void onCreate(Bundle args){super.onCreate(args);scenario=args.getString("case","");start();}
    @Override public void onStart(){Bundle result=new Bundle();Context app=getTargetContext();
        try{
            check(app.getPackageName().equals("com.baseer.freshchat.transfer.test"));app.deleteDatabase("bchat-v2-text-outbox.db");
            AccountScope a=new AccountScope("https://stage.invalid","synthetic",96);BChatConnectedMediaStore store=new BChatConnectedMediaStore(app);
            store.purgeAccount(a);
            try(BChatV2Outbox box=new BChatV2Outbox(app);BChatV2Outbox replacement=new BChatV2Outbox(app)){
                if("gap".equals(scenario)){
                    box.saveDraft(a,17,8,"caption",0,19);
                    BChatStageAdmission.Token owner=serial(()->BChatStageAdmission.begin(box,store,a,17,8));
                    DraftTestMediaProvider.source=new File(app.getFilesDir(),"stage-synthetic-provider");
                    try(FileOutputStream out=new FileOutputStream(DraftTestMediaProvider.source)){out.write(new byte[]{1,2,3});}
                    DraftTestMediaProvider.opened=new CountDownLatch(1);DraftTestMediaProvider.release=new CountDownLatch(0);
                    BChatConnectedMediaStore.Entry staged=store.stage(app.getContentResolver(),a,17,3,8,
                            Uri.parse("content://com.baseer.freshchat.transfer.test.media/input"),"caption",0);
                    // Deliberately pause after metadata publication, before admission; a second Activity reads now.
                    BChatStageAdmission.Recovery during=serial(()->BChatStageAdmission.recover(replacement,store,a,17,8));
                    check(during.media.size()==1);check(during.staging&&during.dispatchBlocked);
                    check(replacement.tickets().find(a,"media",staged.clientUuid)==null);
                    boolean denied=false;try{serial(()->BChatStageAdmission.begin(replacement,store,a,17,8));}catch(IOException expected){denied=true;}
                    check(denied&&owner.owns());
                    serial(()->{try{box.tickets().admitMedia(a,staged,false,19);return true;}finally{owner.close();}});
                    BChatSendTickets.Ticket admitted=box.tickets().find(a,"media",staged.clientUuid);
                    check(admitted!=null&&!admitted.legacy&&"queued".equals(admitted.state));
                    check(box.draftRecord(a,17,8)==null&&box.tickets().forAccount(a).size()==1);
                    BChatStageAdmission.Token old=serial(()->BChatStageAdmission.begin(box,store,a,17,8));
                    BChatStorageRepository.invalidate(a);
                    BChatStageAdmission.Token newer=serial(()->BChatStageAdmission.begin(replacement,store,a,17,8));
                    serial(()->{old.close();return true;});check(newer.owns()&&!old.owns());
                    serial(()->{newer.close();return true;});check(!BChatStageAdmission.active(a,17,8));
                    DraftTestMediaProvider.source.delete();
                }else if("drain".equals(scenario)||"failed_import".equals(scenario)){
                    for(int i=0;i<20;i++){
                        BChatConnectedMediaStore.Entry e=TransferInstrumentation.fixture(app,a);BChatSendTickets.Ticket t=box.tickets().admitMedia(a,e,false);
                        if("drain".equals(scenario))check(box.tickets().receipt(a,t,200+i));
                        store.retireReceipted(a,e.uploadUuid,t.fingerprint);
                    }
                    BChatConnectedMediaStore.Entry orphan=TransferInstrumentation.fixture(app,a);
                    BChatStageAdmission.Recovery snapshot=serial(()->BChatStageAdmission.recover(box,store,a,17,8));
                    check(snapshot.media.size()==1&&store.file(a,orphan).isFile());
                    if("drain".equals(scenario)){
                        BChatSendTickets.Ticket legacy=box.tickets().find(a,"media",orphan.clientUuid);
                        check(legacy!=null&&legacy.legacy&&"review".equals(legacy.state));
                        check(box.tickets().forAccount(a).size()==1&&snapshot.issues.isEmpty());
                    }else{
                        check(snapshot.dispatchBlocked&&!snapshot.staging&&snapshot.issues.size()==1);
                        check("orphan_admission_failed".equals(snapshot.issues.get(0).code)&&orphan.uploadUuid.equals(snapshot.issues.get(0).uploadUuid));
                        check(box.tickets().forAccount(a).size()==20&&box.tickets().find(a,"media",orphan.clientUuid)==null);
                        BChatStageAdmission.Recovery other=serial(()->BChatStageAdmission.recover(box,store,a,18,9));
                        check(other.media.isEmpty()&&!other.dispatchBlocked);
                    }
                }else throw new IllegalArgumentException("Explicit case required");
                box.purgeAccount(a);store.purgeAccount(a);
            }
            result.putString("stream","PASS: "+checks+" stage "+scenario+" assertions; real Android35 SQLite/store/serial; SAF fake; no HTTP\n");finish(0,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n");finish(1,result);}
    }
}

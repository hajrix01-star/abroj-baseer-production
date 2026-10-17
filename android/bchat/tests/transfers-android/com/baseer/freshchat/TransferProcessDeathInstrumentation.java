package com.baseer.freshchat;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import com.baseer.freshchat.sync.*;
import java.util.*;
import java.util.concurrent.*;
/** Two invocations separated by explicit adb force-stop of this synthetic package only. */
public final class TransferProcessDeathInstrumentation extends Instrumentation{
    private String phase;private int checks;
    private void check(boolean value){checks++;if(!value)throw new AssertionError("Process death "+checks);}
    @Override public void onCreate(Bundle args){super.onCreate(args);phase=args.getString("phase","");start();}
    @Override public void onStart(){Context app=getTargetContext();Bundle result=new Bundle();
        try{
            check(app.getPackageName().equals("com.baseer.freshchat.transfer.test"));
            check(phase.matches("(prepare|recover)_(stage|ticket|receipt)"));
            String point=phase.substring(phase.indexOf('_')+1);
            AccountScope scope=new AccountScope("https://death.invalid","synthetic",91);
            BChatConnectedMediaStore store=new BChatConnectedMediaStore(app);
            if(phase.startsWith("prepare")){
                app.deleteDatabase("bchat-v2-text-outbox.db");store.purgeAccount(scope);
                try(BChatV2Outbox box=new BChatV2Outbox(app)){
                    BChatConnectedMediaStore.Entry entry=TransferInstrumentation.fixture(app,scope);
                    if(!"stage".equals(point)){
                        box.tickets().admitMedia(scope,entry,false);
                        BChatSendTickets.Ticket claim=box.tickets().claimMediaHead(scope,17,8,UUID.randomUUID().toString(),System.currentTimeMillis());
                        if("receipt".equals(point)){
                            check(box.tickets().saveUploaded(scope,claim,901,()->store.markUploaded(scope,entry,901)));
                            check(box.tickets().receipt(scope,claim,902));
                        }
                    }
                    check(app.getSharedPreferences("death-test",0).edit().putString("point",point).commit());
                }
                Bundle ready=new Bundle();ready.putString("stream","PREPARED "+point+"; waiting explicit synthetic-package force-stop\n");sendStatus(0,ready);
                new CountDownLatch(1).await(45,TimeUnit.SECONDS);
                throw new AssertionError("Harness did not terminate prepared test process");
            }
            check(point.equals(app.getSharedPreferences("death-test",0).getString("point",null)));
            check(!BChatTransferCoordinator.get(app).isBusy()); // fresh process has no secret or owner grant.
            try(BChatV2Outbox box=new BChatV2Outbox(app)){
                List<BChatConnectedMediaStore.Entry> entries=store.pendingForRoom(scope,17,8);check(entries.size()==1);
                BChatConnectedMediaStore.Entry entry=entries.get(0);BChatSendTickets.Ticket ticket=box.tickets().find(scope,"media",entry.clientUuid);
                check(store.file(scope,entry).isFile());
                if("stage".equals(point)){
                    check(ticket==null);ticket=box.tickets().admitMedia(scope,entry,true);check(ticket.legacy&&"review".equals(ticket.state));
                    check(box.tickets().claimMediaHead(scope,17,8,UUID.randomUUID().toString(),System.currentTimeMillis())==null);
                }else if("ticket".equals(point)){
                    check(ticket!=null&&"sending".equals(ticket.state));box.recoverInterrupted(scope);
                    BChatSendTickets.Ticket recovered=box.tickets().find(scope,"media",entry.clientUuid);
                    check(recovered.uuid.equals(ticket.uuid)&&recovered.attempts==ticket.attempts&&"uncertain".equals(recovered.state));
                }else{
                    check(ticket!=null&&"receipt".equals(ticket.state)&&ticket.messageId==902);
                    final BChatSendTickets.Ticket receipt=ticket;
                    check(box.tickets().retireMedia(scope,receipt,()->store.retireReceipted(scope,entry.uploadUuid,receipt.fingerprint)));
                    check(store.pendingForRoom(scope,17,8).isEmpty()&&box.tickets().head(scope,17,8)==null);
                }
                check(BChatNativeMediaUploader.calls.get()==0);box.purgeAccount(scope);store.purgeAccount(scope);
            }
            result.putString("stream","PASS: "+checks+" actual process-death assertions after "+point+"; synthetic package; no real HTTP\n");finish(0,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n");finish(1,result);}
    }
}

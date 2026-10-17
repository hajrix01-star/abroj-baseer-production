package com.baseer.freshchat;
import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import com.baseer.freshchat.sync.*;
import java.util.*;
/** Focused scope/receipt/quota invariants on real Android SQLite; no real HTTP. */
public final class TransferAdmissionInstrumentation extends Instrumentation{
    private String scenario;private int checks;private Activity surface;
    private void check(boolean value){checks++;if(!value)throw new AssertionError(scenario+" "+checks);}
    @Override public void onCreate(Bundle args){super.onCreate(args);scenario=args.getString("case","");start();}
    @Override public void onStart(){Context app=getTargetContext();Bundle result=new Bundle();
        AccountScope a=new AccountScope("https://admission.invalid","synthetic",92);
        BChatTransferCoordinator coordinator=BChatTransferCoordinator.get(app);
        try{
            check(app.getPackageName().equals("com.baseer.freshchat.transfer.test"));app.deleteDatabase("bchat-v2-text-outbox.db");
            BChatConnectedMediaStore store=new BChatConnectedMediaStore(app);store.purgeAccount(a);
            try(BChatV2Outbox box=new BChatV2Outbox(app)){
                if("scope".equals(scenario)){
                    surface=startActivitySync(new Intent(app,TransferTestSurface.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                    BChatConnectedMediaStore.Entry original=TransferInstrumentation.fixture(app,a),different=TransferInstrumentation.fixture(app,a);
                    box.tickets().admitMedia(a,original,false);
                    BChatSendTickets.Ticket claim=box.tickets().claimMediaHead(a,17,8,UUID.randomUUID().toString(),System.currentTimeMillis());
                    coordinator.authorize(a,Collections.singleton(BChatTransferCoordinator.roomKey(17,8,3)));
                    final boolean[] accepted={true};String secret=String.join("",Collections.nCopies(43,"x"));
                    runOnMainSync(()->accepted[0]=coordinator.schedule(a,claim,different,new java.io.File("unused"),UUID.randomUUID().toString(),secret,()->true));
                    check(!accepted[0]);check(!coordinator.isBusy());
                    AccountScope other=new AccountScope(a.origin,a.database,93);
                    BChatConnectedMediaStore.Entry foreign=TransferInstrumentation.fixture(app,other);
                    runOnMainSync(()->accepted[0]=coordinator.schedule(a,claim,foreign,new java.io.File("unused"),UUID.randomUUID().toString(),secret,()->true));
                    check(!accepted[0]);check(BChatNativeMediaUploader.calls.get()==0);store.purgeAccount(other);
                }else if("ack".equals(scenario)){
                    BChatV2Outbox.Entry pending=box.enqueue(a,17,8,"no ACK yet");
                    check(!box.acknowledge(a,pending));check(box.first(a,17,8)!=null);
                    check(box.recordReceipt(a,pending,101));check(!box.acknowledge(a,pending));
                    check(box.acknowledge(a,box.first(a,17,8)));
                    BChatV2Outbox.Entry discard=box.enqueue(a,17,8,"explicit discard");check(box.discard(a,discard));
                }else if("quota".equals(scenario)){
                    BChatConnectedMediaStore.Entry first=null;
                    for(int i=0;i<20;i++){
                        BChatConnectedMediaStore.Entry e=TransferInstrumentation.fixture(app,a);if(first==null)first=e;
                        BChatSendTickets.Ticket t=box.tickets().admitMedia(a,e,false);
                        check(box.tickets().receipt(a,t,100+i));store.retireReceipted(a,e.uploadUuid,t.fingerprint);
                    }
                    check(store.pendingForRoom(a,17,8).isEmpty()&&box.tickets().forAccount(a).size()==20);
                    check(box.tickets().admitMedia(a,first,false).uuid.equals(first.clientUuid)); // replay before quota.
                    BChatConnectedMediaStore.Entry over=TransferInstrumentation.fixture(app,a);
                    boolean rejected=false;try{box.tickets().admitMedia(a,over,false);}catch(IllegalStateException expected){rejected=true;}
                    check(rejected);check(box.tickets().forAccount(a).size()==20);
                }else throw new IllegalArgumentException("Explicit case required");
                box.purgeAccount(a);store.purgeAccount(a);
            }
            result.putString("stream","PASS: "+checks+" "+scenario+" admission assertions, real Android35/SQLite; HTTP fake\n");finish(0,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n");finish(1,result);}
        finally{coordinator.revoke(a);if(surface!=null)runOnMainSync(()->surface.finish());}
    }
}

package com.baseer.freshchat;
import android.app.Instrumentation;
import android.content.Context;
import android.net.Uri;
import android.os.Bundle;
import com.baseer.freshchat.sync.*;
import java.io.*;
import java.util.concurrent.*;
/** Real Android SQLite + real store via a declared gated SAF provider, not an Activity screen test. */
public final class DraftRevisionInstrumentation extends Instrumentation{
    private int checks;
    private void check(boolean ok){checks++;if(!ok)throw new AssertionError("Draft revision "+checks+" at "+new Throwable().getStackTrace()[1]);}
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();Context app=getTargetContext();
        try{
            check(app.getPackageName().equals("com.baseer.freshchat.transfer.test"));
            app.deleteDatabase("bchat-v2-text-outbox.db");
            AccountScope scope=new AccountScope("https://draft.invalid","synthetic",83);
            BChatConnectedMediaStore store=new BChatConnectedMediaStore(app);
            try(BChatV2Outbox box=new BChatV2Outbox(app)){
                box.saveDraft(scope,17,8,"identical",0,19);
                DraftTestMediaProvider.source=new File(app.getFilesDir(),"synthetic-saf-input");
                try(FileOutputStream out=new FileOutputStream(DraftTestMediaProvider.source)){out.write(new byte[]{1,2,3,4});}
                DraftTestMediaProvider.opened=new CountDownLatch(1);DraftTestMediaProvider.release=new CountDownLatch(1);
                BChatConnectedMediaStore.Entry[] staged={null};Throwable[] failure={null};
                Thread copy=new Thread(()->{try{staged[0]=store.stage(app.getContentResolver(),scope,17,3,8,
                        Uri.parse("content://com.baseer.freshchat.transfer.test.media/input"),"identical",0);}
                    catch(Throwable error){failure[0]=error;}},"synthetic-saf-copy");copy.start();
                check(DraftTestMediaProvider.opened.await(5,TimeUnit.SECONDS));
                // User edits, then restores the same characters while the provider is still blocked.
                box.saveDraft(scope,17,8,"changed",0,20);box.saveDraft(scope,17,8,"identical",0,21);
                DraftTestMediaProvider.release.countDown();copy.join(5000);
                check(!copy.isAlive()&&failure[0]==null&&staged[0]!=null&&!DraftTestMediaProvider.mainIo);
                box.tickets().admitMedia(scope,staged[0],false,19);
                BChatV2Outbox.Draft retained=box.draftRecord(scope,17,8);
                check(retained!=null&&retained.editorRevision==21&&"identical".equals(retained.body));
                BChatV2Outbox.Entry old=box.enqueue(scope,17,8,"identical",0,19);
                check(box.draftRecord(scope,17,8).editorRevision==21&&old.body.equals("identical"));
                box.enqueue(scope,17,8,"identical",0,21);check(box.draftRecord(scope,17,8)==null);
                // Matching media consumes only that revision, even with an otherwise identical caption.
                box.saveDraft(scope,18,9,"media exact",0,31);
                BChatConnectedMediaStore.Entry exact=store.stage(app.getContentResolver(),scope,18,3,9,
                        Uri.parse("content://com.baseer.freshchat.transfer.test.media/input"),"media exact",0);
                box.tickets().admitMedia(scope,exact,false,31);check(box.draftRecord(scope,18,9)==null);
                box.saveDraft(scope,19,10,"raw mismatch",0,40);
                box.enqueue(scope,19,10,"different",0,40);check("raw mismatch".equals(box.draft(scope,19,10)));
                check(!box.roomEntries(new AccountScope(scope.origin,scope.database,84),17,8).iterator().hasNext());
                box.purgeAccount(scope);store.purgeAccount(scope);DraftTestMediaProvider.source.delete();
            }
            result.putString("stream","PASS: "+checks+" draft revision assertions; Android35 SQLite/store; gated SAF provider fake\n");finish(0,result);
        }catch(Throwable error){result.putString("stream","FAIL: "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n");finish(1,result);}
    }
}

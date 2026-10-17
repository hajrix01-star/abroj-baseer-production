package com.baseer.freshchat;
import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
/** Explicit HTTP test double only; the test builder NEVER compiles this into the product. */
final class BChatNativeMediaUploader{
    static volatile CountDownLatch began=new CountDownLatch(1),release=new CountDownLatch(1);
    static volatile String uploadUuid;
    static final AtomicInteger calls=new AtomicInteger();
    static void reset(String uuid){uploadUuid=uuid;began=new CountDownLatch(1);release=new CountDownLatch(1);calls.set(0);}
    static final class Call{volatile boolean cancelled;void cancel(){cancelled=true;release.countDown();}}
    static final class Result{final int status;final String body,diagnostic;
        Result(int status,String body,String diagnostic){this.status=status;this.body=body;this.diagnostic=diagnostic;}
        boolean isTransportFailure(){return status==0;}}
    static Result upload(Call call,String origin,String database,String grant,String secret,File file,int size,String mime){
        calls.incrementAndGet();began.countDown();try{release.await(15,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}
        return call.cancelled?new Result(0,"","test_cancelled"):new Result(200,
                "{\"api_version\":2,\"upload_uuid\":\""+uploadUuid+"\",\"media_id\":901,\"state\":\"staged\"}","");}
    static Result status(Call call,String origin,String database,String grant,String secret){return new Result(0,"","test_status_unused");}
}

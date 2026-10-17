package com.baseer.freshchat.sync.test;
import android.app.Instrumentation;
import android.os.Bundle;
import com.baseer.freshchat.OrderPolicyPersistenceProbe;
public final class OrderPolicyInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
    @Override public void onStart(){
        Bundle result=new Bundle();
        try{int checks=OrderPolicyPersistenceProbe.run(this,getContext());result.putString("stream","PASS: "+checks+" targeted order-policy assertions\n");finish(0,result);}
        catch(Throwable failure){result.putString("stream","FAIL: "+failure.getClass().getSimpleName()+": "+failure.getMessage()+"\n");finish(1,result);}
    }
}

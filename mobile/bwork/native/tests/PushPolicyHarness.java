package com.baseer.bwork.notifications;
public final class PushPolicyHarness {
  public static void main(String[] args){
    String key="10000000-0000-4000-8000-000000000001";
    assert PushPolicy.valid(key,"chat","1");assert PushPolicy.valid(key,"task","2147483647");
    for(String value:new String[]{null,"","0","01","-1","2147483648","1?company_id=2","999999999999999999999"})assert !PushPolicy.valid(key,"chat",value);
    assert !PushPolicy.valid("different-account","chat","1");assert !PushPolicy.valid(key,"order","1");
    assert PushPolicy.bound(true,key,"authorized-scope",key,"chat","1");assert !PushPolicy.bound(false,key,"scope",key,"chat","1");assert !PushPolicy.bound(true,"other-account","scope",key,"chat","1");assert !PushPolicy.bound(true,key,"",key,"chat","1");
    java.util.List<String> seen=new java.util.ArrayList<>();seen=PushPolicy.nextSeen(seen,"chat:1");assert PushPolicy.nextSeen(seen,"chat:1")==null; // Dismissing a system alert does not clear dedupe.
    for(int i=2;i<200;i++)seen=PushPolicy.nextSeen(seen,"chat:"+i);assert seen.size()==128;assert PushPolicy.nextSeen(seen,"chat:199")==null;
    // Actual callback gate, held A callback resolves only after clear and B's token/binding.
    Object lock=new Object();long[] epoch={1};boolean[] enabled={true};String[] token={"A"},binding={"A"};int[] mutations={0};long[] captured={-1};Runnable[] held={null};
    assert PushCallbacks.begin(lock,()->epoch[0],()->{assert Thread.holdsLock(lock);return enabled[0];},expected->{assert Thread.holdsLock(lock);captured[0]=expected;held[0]=()->{assert !PushCallbacks.commit(lock,expected,()->epoch[0],()->enabled[0],()->{mutations[0]++;token[0]="old-A";binding[0]="";return true;});};});
    long heldA=captured[0];
    synchronized(lock){epoch[0]++;enabled[0]=false;binding[0]="";}
    long pendingB=epoch[0];assert PushCallbacks.commit(lock,pendingB,()->epoch[0],()->true,()->{assert Thread.holdsLock(lock);enabled[0]=true;return true;});
    assert PushCallbacks.commit(lock,pendingB,()->epoch[0],()->enabled[0],()->{epoch[0]++;token[0]="B";binding[0]="B";return true;});
    held[0].run();
    assert !PushCallbacks.commit(lock,heldA,()->epoch[0],()->true,()->{mutations[0]++;enabled[0]=true;return true;});
    assert token[0].equals("B")&&binding[0].equals("B")&&epoch[0]==3&&mutations[0]==0;
    assert PushPolicy.body(false,"chat").equals("You have a new message");assert PushPolicy.body(true,"task").equals("لديك تحديث في المهام");
    System.out.println("PASS bounded generic native push policy");
  }
}

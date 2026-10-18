package com.baseer.bchat.trial.session;
import java.io.*;
import java.net.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import okhttp3.*;
import okhttp3.internal.connection.RealCall;
import okhttp3.internal.http.RetryAndFollowUpInterceptor;
import okio.Buffer;
import okio.BufferedSink;

public final class AvatarReplayHarness {
  static int assertions;
  static void check(boolean value, String name) { assertions++; if(!value)throw new AssertionError(name); }
  interface Exchange { Response run(Request request) throws IOException; }
  static Interceptor.Chain chain(Request request, Call call, Exchange exchange) {
    return (Interceptor.Chain)java.lang.reflect.Proxy.newProxyInstance(Interceptor.Chain.class.getClassLoader(), new Class[]{Interceptor.Chain.class}, (p,m,a)-> {
      if(m.getName().equals("request"))return request;
      if(m.getName().equals("call"))return call;
      if(m.getName().equals("proceed"))return exchange.run((Request)a[0]);
      if(m.getReturnType()==int.class)return 0; return null;
    });
  }
  static Request request(String method,String url,AtomicInteger writes) {
    RequestBody body=new RequestBody(){public MediaType contentType(){return MediaType.get("application/octet-stream");}
      public void writeTo(BufferedSink sink)throws IOException{writes.incrementAndGet();sink.writeUtf8("synthetic-avatar");}};
    return new Request.Builder().url(url).method(method,method.equals("POST")?body:null).build();
  }
  static Response ok(Request request){return new Response.Builder().request(request).code(200).message("synthetic").protocol(Protocol.HTTP_1_1).body(ResponseBody.create(null,"synthetic")).build();}
  public static void main(String[]args)throws Exception{
    CookieHandler reader=new CookieManager();
    CommitCookieHandler.Writer writer=new CommitCookieHandler.Writer(){public boolean isMainThread(){return false;}public void write(URI uri,List<String> cookies,CommitCookieHandler.Completion done){done.complete(true);}};
    OriginCookieJar jar=new OriginCookieJar("https://qa.example.test",new CommitCookieHandler(reader,writer,100));
    Interceptor guard=jar.avatarNetworkGuard(); AtomicInteger writes=new AtomicInteger(),wire=new AtomicInteger();
    Request original=request("POST","https://qa.example.test/bchat/api/v2/rooms/4/avatar",writes);
    OkHttpClient.Builder builder=new OkHttpClient.Builder();
    new CapturedBlobUtilInterceptor().install(builder,original);
    builder.addInterceptor(inner -> guard.intercept(chain(inner.request(),inner.call(),actual->{
      wire.incrementAndGet(); check(actual.body().isOneShot(),"actual network body is one-shot");
      actual.body().writeTo(new Buffer()); throw new IOException("synthetic response lost");
    })));
    try{builder.build().newCall(original).execute();throw new AssertionError("expected failed upload");}
    catch(ProtocolException expected){check(expected.getMessage().equals("avatar_upload_replay_blocked"),"captured original request replay rejected");}
    check(wire.get()==1&&writes.get()==1,"installed BlobUtil inner retry cannot produce second wire/body write");
    OkHttpClient client=new OkHttpClient(); Call token=client.newCall(original);
    try(Response ignored=guard.intercept(chain(original,token,actual->{
      actual.body().writeTo(new Buffer());
      try{actual.body().writeTo(new Buffer());throw new AssertionError("second body write");}
      catch(ProtocolException expected){check(true,"atomic body write fence");}
      return ok(actual);
    }))){check(ignored.code()==200,"successful first avatar request preserved");}
    Method recover=RetryAndFollowUpInterceptor.class.getDeclaredMethod("recover",IOException.class,RealCall.class,Request.class,boolean.class);recover.setAccessible(true);
    check(!(Boolean)recover.invoke(new RetryAndFollowUpInterceptor(client),new ProtocolException("avatar_upload_replay_blocked"),(RealCall)token,original,true),"actual OkHttp marks ProtocolException nonrecoverable");
    for(String target:new String[]{"https://qa.example.test/bchat/api/v2/rooms/4/avatar?x=1","https://other.example.test/bchat/api/v2/rooms/4/avatar","https://qa.example.test:444/bchat/api/v2/rooms/4/avatar","http://qa.example.test/bchat/api/v2/rooms/4/avatar","https://qa.example.test/bchat/api/v2/rooms/4/uploads","https://qa.example.test/bchat/api/v2/rooms/0/avatar"}){
      Request excluded=request("POST",target,new AtomicInteger());Call call=client.newCall(excluded);
      for(int i=0;i<2;i++)try(Response ignored=guard.intercept(chain(excluded,call,actual->{check(!actual.body().isOneShot(),"non-avatar request body unchanged");return ok(actual);}))){check(true,"excluded endpoint not claimed");}
    }
    Request get=request("GET","https://qa.example.test/bchat/api/v2/rooms/4/avatar",new AtomicInteger());Call getCall=client.newCall(get);
    for(int i=0;i<2;i++)try(Response ignored=guard.intercept(chain(get,getCall,actual->ok(actual)))){check(true,"GET is not claimed");}
    System.out.println("PASS "+assertions+" avatar replay assertions (actual installed BlobUtil interceptor + OkHttp, synthetic wire)");
  }
}

#!/usr/bin/env python3
"""Execute production media-state methods on the JVM with deterministic transport fixtures.

This compiles the actual Activity methods, not a rewritten state-machine model. Android UI,
disk, WebView, and time are controlled fixtures so dropped replies and busy-lane timing are
reproducible without a device or network. Ticket/outbox/file cleanup and Android Context are
explicit in-memory adapters, NOT SQLite, Android lifecycle or crash-durability evidence.
--source can verify a previous source fails. Actual SQLite/UIDT checks are separate tools.
"""
from pathlib import Path
import argparse
import hashlib
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source_path = args.source or root / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java'
source = source_path.read_text(encoding='utf-8')


def method(marker, optional=False, text=None):
    text = source if text is None else text
    if optional and marker not in text:
        return ''
    start = text.index(marker)
    opening = text.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


markers = (
    ('private static long positiveId(', False),
    ('private static long nonnegativeCursor(', False),
    ('private void reconcileNativeMediaUpload(', False),
    ('private void sendConnectedMedia(', False),
    ('private void sendClaimedConnectedMedia(', False),
    ('private void dispatchConnectedMediaMessage(', True),
    ('private void deferMediaLink(', False),
    ('private boolean localMatches(', False),
    ('private void replayKnownConnectedMedia(', False),
    ('private void recoverUncertainMediaConfirmation(AccountScope scopedAccount, Room room) ', False),
    ('private void recoverUncertainMediaConfirmation(AccountScope scopedAccount, Room room,\n', False),
    ('private void reconcilePendingMediaFromVerifiedHistory(', False),
)
production = '\n'.join(method(marker, optional) for marker, optional in markers)
direct_method = method('private boolean postSmallFormDirectlyInWebView(')

fixture = r'''
import java.io.IOException;
import java.util.*;
public class MediaJourneyHarness {
  static final String V2_ROOMS="/bchat/api/v2/rooms";
  static final int MAX_NATIVE_GRANT_CONTROL_RETRIES=40;
  static final long NATIVE_GRANT_CONTROL_RETRY_MILLIS=250;
  int mediaConfirmDispatchGeneration, mediaSessionGeneration, mediaConfirmRecoveryGeneration;
  boolean mediaConfirmBusy, mediaStageBusy, mediaUploadBusy, v2Busy, webV2GetFallbackBusy, allowed=true;
  AccountScope account=new AccountScope(7);
  Room selectedRoom=new Room(1, 2);
  Room mediaConfirmRoom;
  final android.content.Context app=new android.content.Context(this);
  Store mediaStore=new Store(this);
  BChatSendTickets sendTickets=new BChatSendTickets(this);
  BChatV2Outbox outbox=new BChatV2Outbox(app);
  RoomLocalSnapshot roomLocal;
  final BChatStageAdmission.Recovery recovery=new BChatStageAdmission.Recovery();
  int recoveryReads;
  Coordinator transferCoordinator;
  FakeHandler handler=new FakeHandler();
  Notice chatNotice=new Notice();
  JSONObject receipt;
  List<JSONObject> history=new ArrayList<>();
  V2Callback dispatchedCallback;
  int posts, reads, retries, appended, updates, rawUploads, receiptStatus=200;
  final List<String> transitions=new ArrayList<>();
  String postedPayload;
  interface V2Callback { void complete(int status, JSONObject body); }
  static class JSONObject {
    static final Object NULL=new Object();
    final Map<String,Object> values=new HashMap<>();
    JSONObject put(String key,Object value){values.put(key,value);return this;}
    Object get(String key){if(!values.containsKey(key))throw new IllegalArgumentException(key);return values.get(key);}
    Object opt(String key){return values.get(key);}
    String getString(String key){Object value=get(key);if(!(value instanceof String))throw new IllegalArgumentException(key);return (String)value;}
    String optString(String key){Object value=opt(key);return value instanceof String?(String)value:"";}
    JSONObject getJSONObject(String key){return (JSONObject)get(key);}
    JSONObject optJSONObject(String key){return opt(key) instanceof JSONObject?(JSONObject)opt(key):null;}
    boolean has(String key){return values.containsKey(key);}
    public String toString(){return new TreeMap<>(values).toString();}
  }
  static class AccountScope {long userId; AccountScope(long id){userId=id;}}
  static class Room {long id,membershipId;int invoicePolicyVersion=1;Room(long id,long m){this.id=id;membershipId=m;}}
  // Typed API adapters only. No Android SQLite, AtomicFile, process-death or disk-lane claim.
  static class BChatConnectedMediaStore {
    final Store delegate;
    BChatConnectedMediaStore(){delegate=null;}
    BChatConnectedMediaStore(android.content.Context app){delegate=((MediaJourneyHarness)app.fixture).mediaStore;}
    static class Entry {
      long mediaId,invoiceCaseId,replyToMessageId,roomId=1,membershipId=2,companyId=1;int policyVersion=1;
      String uploadBlockCode="",clientUuid="message-uuid",text="caption",documentType="other";
      String uploadUuid="00000000-0000-4000-8000-000000000001";
      String networkUploadUuid(){return "00000000-0000-4000-8000-000000000001";}
      String requestFingerprint(){return clientUuid+"|"+uploadUuid+"|"+text+"|"+documentType;}
    }
    List<Entry> pendingForRoom(AccountScope a,long r,long m)throws IOException{return delegate.pendingForRoom(a,r,m);}
    Entry markUploaded(AccountScope a,Entry e,long id)throws IOException{return delegate.markUploaded(a,e,id);}
    void retireReceipted(AccountScope a,String upload,String fingerprint)throws IOException{delegate.retireReceipted(a,upload,fingerprint);}
  }
  static class Store extends BChatConnectedMediaStore {
    final MediaJourneyHarness owner;
    List<BChatConnectedMediaStore.Entry> pending=new ArrayList<>();int marks,acks;
    Store(MediaJourneyHarness owner){this.owner=owner;}
    List<BChatConnectedMediaStore.Entry> pendingForRoom(AccountScope a,long r,long m)throws IOException{return new ArrayList<>(pending);}
    BChatConnectedMediaStore.Entry markUploaded(AccountScope a,BChatConnectedMediaStore.Entry e,long id)throws IOException{e.mediaId=id;marks++;return e;}
    void retireReceipted(AccountScope a,String upload,String fingerprint)throws IOException{
      for(BChatConnectedMediaStore.Entry e:new ArrayList<>(pending))if(e.uploadUuid.equals(upload)&&e.requestFingerprint().equals(fingerprint)){
        BChatSendTickets.Ticket receipt=owner.sendTickets.find(a,"media",e.clientUuid);
        check(receipt!=null&&"receipt".equals(receipt.state)&&receipt.messageId>0,"cleanup happened before verified receipt");
        owner.transitions.add("cleanup:"+e.clientUuid);pending.remove(e);acks++;return;
      }
      throw new IOException("Fixture local media identity missing");
    }
  }
  static class BChatV2Outbox implements AutoCloseable {
    final MediaJourneyHarness owner;
    BChatV2Outbox(android.content.Context app){owner=(MediaJourneyHarness)app.fixture;}
    BChatSendTickets tickets(){return owner.sendTickets;}
    public void close(){}
  }
  // This does NOT implement or test the SQLite ticket repository. It supplies typed responses
  // to extracted Activity code and fails if that code attempts cleanup before a verified receipt.
  static class BChatSendTickets {
    final MediaJourneyHarness owner;
    final LinkedHashMap<String,Ticket> rows=new LinkedHashMap<>();
    BChatSendTickets(MediaJourneyHarness owner){this.owner=owner;}
    interface Cleanup{void run()throws Exception;}
    static class Ticket {
      final String kind="media",uuid,uploadUuid,fingerprint,state,claimOwner;
      final long roomId,membershipId,companyId,generation,mediaId,messageId;
      final boolean legacy;
      Ticket(BChatConnectedMediaStore.Entry e,String state,boolean legacy){uuid=e.clientUuid;uploadUuid=e.uploadUuid;
        fingerprint=e.requestFingerprint();roomId=e.roomId;membershipId=e.membershipId;companyId=e.companyId;
        this.state=state;this.legacy=legacy;claimOwner="";generation=0;mediaId=e.mediaId;messageId=0;}
      Ticket(Ticket t,String state,String claimOwner,long generation,long media,long message){uuid=t.uuid;uploadUuid=t.uploadUuid;
        fingerprint=t.fingerprint;roomId=t.roomId;membershipId=t.membershipId;companyId=t.companyId;legacy=t.legacy;
        this.state=state;this.claimOwner=claimOwner;this.generation=generation;mediaId=media;messageId=message;}
      boolean matches(BChatConnectedMediaStore.Entry e){return e!=null&&roomId==e.roomId&&membershipId==e.membershipId
        &&companyId==e.companyId&&uuid.equals(e.clientUuid)&&uploadUuid.equals(e.uploadUuid)&&fingerprint.equals(e.requestFingerprint());}
      boolean sameClaim(Ticket t){return t!=null&&uuid.equals(t.uuid)&&claimOwner.equals(t.claimOwner)&&generation==t.generation;}
    }
    Ticket find(AccountScope a,String kind,String uuid){return "media".equals(kind)?rows.get(uuid):null;}
    Ticket head(AccountScope a,long room,long member){for(Ticket t:rows.values())if(t.roomId==room&&t.membershipId==member)return t;return null;}
    Ticket admitMedia(AccountScope a,BChatConnectedMediaStore.Entry e,boolean legacy){
      Ticket old=rows.get(e.clientUuid);if(old!=null){check(old.matches(e),"fixture ticket identity changed");return old;}
      Ticket t=new Ticket(e,legacy?"review":"queued",legacy);rows.put(t.uuid,t);return t;
    }
    Ticket claimMediaHead(AccountScope a,long room,long member,String claimOwner,long now){
      Ticket t=head(a,room,member);if(t==null||"sending".equals(t.state)||"receipt".equals(t.state)||"review".equals(t.state))return null;
      Ticket claimed=new Ticket(t,"sending",claimOwner,t.generation+1,t.mediaId,0);rows.put(t.uuid,claimed);return claimed;
    }
    boolean saveUploaded(AccountScope a,Ticket expected,long media,Cleanup write)throws Exception{
      Ticket t=rows.get(expected.uuid);if(t==null||!t.sameClaim(expected)||"receipt".equals(t.state)||"uploaded".equals(t.state))return false;
      write.run();rows.put(t.uuid,new Ticket(t,"uploaded",t.claimOwner,t.generation,media,0));return true;
    }
    boolean receipt(AccountScope a,Ticket expected,long message){
      Ticket t=expected==null?null:rows.get(expected.uuid);if(t==null||!t.sameClaim(expected))return false;
      check(message>0,"nonpositive receipt message");owner.transitions.add("receipt:"+t.uuid);
      rows.put(t.uuid,new Ticket(t,"receipt",t.claimOwner,t.generation,t.mediaId,message));return true;
    }
    boolean retireMedia(AccountScope a,Ticket expected,Cleanup cleanup)throws Exception{
      Ticket t=expected==null?null:rows.get(expected.uuid);if(t==null||!t.sameClaim(expected)||!"receipt".equals(t.state))return false;
      cleanup.run();rows.remove(t.uuid);owner.transitions.add("retire:"+t.uuid);return true;
    }
    boolean defer(AccountScope a,Ticket expected){
      Ticket t=expected==null?null:rows.get(expected.uuid);if(t==null||!t.sameClaim(expected))return false;
      rows.put(t.uuid,new Ticket(t,"queued",t.claimOwner,t.generation,t.mediaId,0));return true;
    }
  }
  static class RoomLocalSnapshot {
    final long roomId,membershipId;
    final List<BChatConnectedMediaStore.Entry> media;
    final BChatSendTickets.Ticket sendHead;
    final BChatStageAdmission.Recovery recovery;
    RoomLocalSnapshot(Room r,List<BChatConnectedMediaStore.Entry> media,BChatSendTickets.Ticket head,BChatStageAdmission.Recovery recovery){roomId=r.id;membershipId=r.membershipId;this.media=media;sendHead=head;this.recovery=recovery;}
  }
  // Supplied recovery outcome only. Actual stage recovery/SQLite is tested separately on Android.
  static class BChatStageAdmission {
    static class Recovery{boolean dispatchBlocked;}
    static Recovery recover(BChatV2Outbox box,BChatConnectedMediaStore store,AccountScope account,long room,long member)throws IOException{
      box.owner.recoveryReads++;return box.owner.recovery;
    }
  }
  static class Coordinator{boolean isBusy(){return false;}}
  static class BChatStorageRepository {
    interface Work<T>{T run()throws Exception;}
    interface Ready<T>{void complete(T value,Exception failure);}
    static <T>void submit(AccountScope a,Work<T> work,Ready<T> callback){T result=null;Exception failure=null;
      try{result=work.run();}catch(Exception error){failure=error;}callback.complete(result,failure);}
    static void write(AccountScope a,Work<Void> work){submit(a,work,(value,error)->{});}
  }
  static class MediaRecord {long id;MediaRecord(JSONObject value){id=((Number)value.get("id")).longValue();}}
  static class Notice {int value;void setText(int v){value=v;}}
  static class R {static class string {
    static final int bchat_media_status_upload_pending=1,bchat_media_checking=2,
      chat_v2_uncertain=3,chat_v2_sent=4,bchat_media_policy_changed=5,bchat_media_rejected=6,chat_v2_save_failed=7;
  }}
  static class FakeHandler {
    final ArrayDeque<Runnable> tasks=new ArrayDeque<>();
    void post(Runnable task){tasks.add(task);}
    void postDelayed(Runnable task,long ignored){tasks.add(task);}
    void next(){if(!tasks.isEmpty())tasks.remove().run();}
    void drain(){for(int i=0;!tasks.isEmpty()&&i<200;i++)next();if(!tasks.isEmpty())throw new AssertionError("Unbounded polling");}
  }
  boolean stillCurrent(AccountScope a,Room r){return a==account&&r==selectedRoom;}
  boolean mediaUploadAllowed(){return allowed;}
  void updatePendingUi(){updates++;}
  interface DiskWork<T>{T run()throws Exception;}
  interface DiskReady<T>{void complete(T value,Exception error);}
  // Explicit deterministic storage adapter: production schedules this work off-main; the fixture
  // runs it immediately so network-loss cases retain their original deterministic event order.
  <T> void local(AccountScope a,DiskWork<T> work,DiskReady<T> ready){
    T value=null;Exception failure=null;try{value=work.run();}catch(Exception error){failure=error;}ready.complete(value,failure);
  }
  android.content.Context getApplicationContext(){return app;}
  // Snapshot/hook adapter only; the actual room/draft loading UI is outside this JVM journey.
  void refreshLocalRoom(Room room,boolean restoreDraft){
    if(room!=selectedRoom)return;
    roomLocal=new RoomLocalSnapshot(room,new ArrayList<>(mediaStore.pending),sendTickets.head(account,room.id,room.membershipId),recovery);
    updatePendingUi();handler.post(()->replayKnownConnectedMedia(account,room));
  }
  void uploadConnectedMedia(AccountScope a,Room r,BChatConnectedMediaStore.Entry e)throws IOException{rawUploads++;throw new AssertionError("Byte upload reached from known-media recovery");}
  void showMissingNativeMediaRetry(AccountScope a,Room r,BChatConnectedMediaStore.Entry e){retries++;}
  void fetchV2(String method,String path,String payload,V2Callback callback){
    if("GET".equals(method)){reads++;callback.complete(receiptStatus,receipt);}
    else{posts++;postedPayload=payload;dispatchedCallback=callback;}
  }
  boolean postSmallFormDirectlyInWebView(String path,String field,String payload,V2Callback callback){
    if(v2Busy||webV2GetFallbackBusy)return false;
    if(!path.equals(V2_ROOMS+"/"+selectedRoom.id+"/messages")||!"payload".equals(field))throw new AssertionError("Wrong endpoint");
    posts++;postedPayload=payload;dispatchedCallback=callback;return true;
  }
  boolean handleV2TransportFailure(int code,boolean uncertain){return false;}
  void loadRooms(){}
  void appendAcknowledgedMessage(AccountScope a,Room r,long id){appended++;}
  void loadMessages(long before){reads++;reconcilePendingMediaFromVerifiedHistory(account,selectedRoom,history);}
  BChatConnectedMediaStore.Entry entry(long id){BChatConnectedMediaStore.Entry e=new BChatConnectedMediaStore.Entry();e.mediaId=id;mediaStore.pending.add(e);
    sendTickets.admitMedia(account,e,false);roomLocal=new RoomLocalSnapshot(selectedRoom,new ArrayList<>(mediaStore.pending),sendTickets.head(account,1,2),recovery);return e;}
  JSONObject receipt(String state){return new JSONObject().put("api_version",2).put("room_id",1).put("membership_id",2)
    .put("upload_uuid","00000000-0000-4000-8000-000000000001").put("state",state);}
  JSONObject ack(){return new JSONObject().put("api_version",2).put("room_id",1).put("membership_id",2)
    .put("media_id",55).put("client_uuid","message-uuid").put("state","sent").put("message_id",77);}
  void sentHistory(){history.add(new JSONObject().put("id",77).put("author_user_id",7).put("media",new JSONObject().put("id",55)));}
  static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
  static int passed,failed;
  static void test(String name,Runnable test){try{test.run();passed++;System.out.println("PASS "+name);}catch(Throwable error){failed++;System.out.println("FAIL "+name+": "+error);}}
  public static void main(String[] args){
    test("missing absent media ID offers safe retry",()->{
      MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("missing");h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.retries==1&&h.posts==0,"missing was rejected or posted");
      // Additional assertions in the existing journey: an uncertain upload-status GET grants
      // no byte retry. Only the next explicit, valid missing-status read may offer one.
      for(boolean lost:new boolean[]{true,false}){MediaJourneyHarness uncertain=new MediaJourneyHarness();
        BChatConnectedMediaStore.Entry e=uncertain.entry(0);uncertain.receiptStatus=lost?0:200;
        uncertain.receipt=lost?null:new JSONObject();uncertain.reconcileNativeMediaUpload(uncertain.account,uncertain.selectedRoom,e);
        check(uncertain.reads==1&&uncertain.posts==0&&uncertain.retries==0&&uncertain.mediaStore.pending.size()==1,"lost/malformed status retried or discarded bytes");
        uncertain.receiptStatus=200;uncertain.receipt=uncertain.receipt("missing");uncertain.reconcileNativeMediaUpload(uncertain.account,uncertain.selectedRoom,e);
        check(uncertain.reads==2&&uncertain.retries==1&&uncertain.posts==0,"uncertain upload did not use explicit read reconciliation");}
    });
    test("missing explicit zero offers safe retry",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("missing").put("media_id",0);h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.retries==1,"numeric zero rejected");});
    test("uploading absent media ID polls without byte retry",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("uploading");h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.handler.tasks.size()==1&&h.retries==0&&h.posts==0,"in-flight was rejected or replayed");h.receipt=h.receipt("missing");h.handler.next();check(h.retries==1,"receipt never rechecked");});
    test("string ID remains rejected",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("missing").put("media_id","0");h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.retries==0&&h.posts==0,"string ID accepted");});
    test("native success during busy GET queues exactly one message",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.v2Busy=true;h.receipt=h.receipt("staged").put("media_id",55);BChatConnectedMediaStore.Entry e=h.entry(0);h.reconcileNativeMediaUpload(h.account,h.selectedRoom,e);check(h.posts==0&&h.mediaStore.marks==1&&"uploaded".equals(h.sendTickets.head(h.account,1,2).state),"send ticket lost at busy guard");h.v2Busy=false;h.handler.next();check(h.posts==1&&h.postedPayload.contains("message-uuid"),"send did not resume");h.sendConnectedMedia(h.account,h.selectedRoom,e);check(h.posts==1,"concurrent send duplicated POST");h.dispatchedCallback.complete(200,h.ack());check(h.mediaStore.acks==1&&!h.mediaConfirmBusy&&h.rawUploads==0,"ACK did not retire request or re-uploaded bytes");});
    test("busy deadline retains local receipt without dispatch",()->{
      MediaJourneyHarness h=new MediaJourneyHarness();h.v2Busy=true;h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.handler.drain();check(h.posts==0&&!h.mediaConfirmBusy&&h.mediaStore.pending.size()==1&&h.chatNotice.value==R.string.chat_v2_uncertain,"deadline lost request or stayed busy");
      // Exercise the new Activity recovery gate, NOT the SQLite recovery implementation.
      MediaJourneyHarness blocked=new MediaJourneyHarness();BChatConnectedMediaStore.Entry e=blocked.entry(55);blocked.recovery.dispatchBlocked=true;
      blocked.replayKnownConnectedMedia(blocked.account,blocked.selectedRoom);check(blocked.posts==0,"snapshot recovery barrier bypassed");
      blocked.sendConnectedMedia(blocked.account,blocked.selectedRoom,e);
      check(blocked.recoveryReads==1&&blocked.posts==0&&!blocked.mediaConfirmBusy&&blocked.mediaStore.pending.size()==1,"worker recovery barrier bypassed");
      blocked.recovery.dispatchBlocked=false;blocked.sendConnectedMedia(blocked.account,blocked.selectedRoom,e);
      check(blocked.posts==1&&blocked.postedPayload.contains(e.clientUuid)&&blocked.rawUploads==0,"unblocked known-media intent changed or re-uploaded");
    });
    test("room switch cancels only undispatched intent",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.v2Busy=true;h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.mediaSessionGeneration++;h.selectedRoom=new Room(9,9);h.v2Busy=false;h.handler.drain();check(h.posts==0&&!h.mediaConfirmBusy&&h.mediaStore.pending.size()==1,"old room posted after navigation");});
    test("lost reply reconciles history without second POST",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.sentHistory();h.dispatchedCallback.complete(0,null);h.handler.drain();check(h.posts==1&&h.mediaStore.acks==1&&h.reads==1,"lost ACK repeated write or failed history");});
    test("uncommitted lost reply stays pending without automatic POST",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.dispatchedCallback.complete(0,null);h.handler.drain();check(h.posts==1&&h.mediaStore.acks==0&&h.mediaStore.pending.size()==1,"uncertain request duplicated or discarded");});
    test("verified ACK retires before current-screen check",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.selectedRoom=new Room(9,9);h.dispatchedCallback.complete(200,h.ack());check(h.mediaStore.acks==1&&h.appended==0,"navigation trapped verified local request");check(h.transitions.equals(Arrays.asList("receipt:message-uuid","cleanup:message-uuid","retire:message-uuid")),"receipt/cleanup retirement order changed");});
    test("malformed 2xx reconciles rather than resending",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.sentHistory();h.dispatchedCallback.complete(200,new JSONObject());h.handler.drain();check(h.posts==1&&h.mediaStore.acks==1,"malformed 2xx did not reconcile");});
    System.out.println("Media journey: "+passed+" passed, "+failed+" failed");if(failed!=0)System.exit(1);
  }
'''

direct_fixture = r'''
import java.util.Base64;
import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;
public class SmallPostHarness {
  static final String V2_PUSH_REGISTER="/bchat/api/v2/notifications/register";
  static final String ORIGIN="https://bchat.example", BRIDGE=ORIGIN+"/bchat/app/bridge";
  static final int MAX_V2_RESPONSE=131072;
  boolean closed,verified=true,webV2GetFallbackBusy,v2Busy;
  int webV2GetFallbackGeneration,webEpoch=1,pageEpoch=1,epoch=1,polls;
  Object account=new Object();String csrfToken="fixture-csrf";
  Web web=new Web();
  interface V2Callback {void complete(int status,Object body);}
  static class Uri {static String parse(String s){return s;}}
  static class JSONObject {static String quote(String s){return "\""+s.replace("\\","\\\\").replace("\"","\\\"")+"\"";}}
  static class Web {String script;int evaluations;String getUrl(){return BRIDGE;}void evaluateJavascript(String s,Consumer<String> callback){script=s;evaluations++;callback.accept(null);}}
  boolean isBridgeUrl(String s){return BRIDGE.equals(s);}
  void releaseV2Port(){v2Busy=false;}
  void pollVerifiedGetFallback(String slot,int generation,String path,int max,int w,int p,int e,V2Callback callback,int attempt){polls++;}
  static void check(boolean v,String reason){if(!v)throw new AssertionError(reason);}
  public static void main(String[] args){
    SmallPostHarness h=new SmallPostHarness();
    check(h.postSmallFormDirectlyInWebView("/bchat/api/v2/rooms/1/messages","payload","fixture-payload",(s,b)->{}),"Media message not admitted");
    check(h.web.evaluations==1&&h.polls==1&&h.v2Busy&&h.webV2GetFallbackBusy,"Dispatch/poll did not own lane");
    check(!h.postSmallFormDirectlyInWebView("/bchat/api/v2/rooms/1/messages","payload","fixture-payload",(s,b)->{}),"Busy lane dispatched twice");
    SmallPostHarness blocked=new SmallPostHarness();
    check(!blocked.postSmallFormDirectlyInWebView("/bchat/api/v2/rooms/1/messages/other","payload","x",(s,b)->{}),"Unlisted route admitted");
    check(!blocked.postSmallFormDirectlyInWebView("/bchat/api/v2/rooms/1/messages","metadata","x",(s,b)->{}),"Wrong message form key admitted");
    check(blocked.web.evaluations==0,"Rejected request dispatched JavaScript");
    System.out.println("PASS production direct POST route/form allowlist and busy admission");
    System.out.println("SCRIPT:"+Base64.getEncoder().encodeToString(h.web.script.getBytes(StandardCharsets.UTF_8)));
  }
'''

node_fixture = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
global.window = {};
global.location = {href:'https://bchat.example/bchat/app/bridge',origin:'https://bchat.example'};
let calls=0;
global.fetch=async(url,options)=>{
  calls++;
  assert.equal(url,'https://bchat.example/bchat/api/v2/rooms/1/messages');
  assert.equal(options.method,'POST');
  assert.equal(options.credentials,'same-origin');
  assert.equal(options.redirect,'manual');
  const form=new URLSearchParams(options.body);
  assert.equal(form.get('csrf_token'),'fixture-csrf');
  assert.equal(form.get('payload'),'fixture-payload');
  let sent=false;
  return {status:200,type:'basic',url,headers:{get:()=> 'application/json'},body:{getReader:()=>({read:async()=>{
    if(sent)return {done:true};sent=true;
    return {done:false,value:new TextEncoder().encode('{"api_version":2,"state":"sent"}')};
  }})}};
};
vm.runInThisContext(Buffer.from(process.argv[1],'base64').toString('utf8'));
setImmediate(()=>{
  assert.equal(calls,1);
  const envelope=JSON.parse(window.__bchatSmallPost1);
  assert.equal(envelope.status,200);
  assert.equal(JSON.parse(envelope.body).state,'sent');
  for(let i=0;i<20;i++)JSON.parse(window.__bchatSmallPost1);
  assert.equal(calls,1);
  console.log('PASS production-generated WebView script: one authenticated POST, bounded result polling, no MessagePort');
});
'''

javac, java = shutil.which('javac'), shutil.which('java')
if not javac or not java:
    raise SystemExit('Existing JDK is required; no dependencies are installed by this test.')
runtime = root / 'artifacts/test-runtime'
runtime.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='bchat-media-journey-', dir=runtime) as temporary:
    folder = Path(temporary)
    # Opaque context identity for the explicitly declared JVM adapters, not Android framework.
    context = folder / 'android/content/Context.java'
    context.parent.mkdir(parents=True)
    context.write_text('package android.content; public final class Context { '
                       'public final Object fixture; public Context(Object fixture) { this.fixture=fixture; } }\n',
                       encoding='utf-8')
    harness = folder / 'MediaJourneyHarness.java'
    harness.write_text(fixture + '\n' + production + '\n}\n', encoding='utf-8')
    print('Declared fixtures: in-memory ticket/outbox/store/context; NOT Android SQLite, UIDT or disk durability.', flush=True)
    subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(folder), str(context), str(harness)], check=True)
    subprocess.run([java, '-cp', str(folder), 'MediaJourneyHarness'], check=True)
    direct = folder / 'SmallPostHarness.java'
    direct.write_text(direct_fixture + '\n' + direct_method + '\n}\n', encoding='utf-8')
    subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(folder), str(direct)], check=True)
    output = subprocess.check_output([java, '-cp', str(folder), 'SmallPostHarness'], text=True)
    script = next(line.removeprefix('SCRIPT:') for line in output.splitlines() if line.startswith('SCRIPT:'))
    print(next(line for line in output.splitlines() if line.startswith('PASS ')))
    node = shutil.which('node')
    if not node:
        raise SystemExit('Existing Node.js is required to execute the production-generated WebView script.')
    subprocess.run([node, '-e', node_fixture, script], check=True)
    # Another owner may edit unrelated Activity UI. Freeze only the methods this test executes.
    latest = source_path.read_text(encoding='utf-8')
    current = '\n'.join(method(marker, optional, latest) for marker, optional in markers)
    if current != production or method('private boolean postSmallFormDirectlyInWebView(', text=latest) != direct_method:
        raise SystemExit('Executed Activity methods changed during JVM verification; no frozen-source acceptance')
    print('Executed Activity methods SHA256: ' + hashlib.sha256((production + '\n' + direct_method).encode('utf-8')).hexdigest())

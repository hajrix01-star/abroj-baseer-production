#!/usr/bin/env python3
"""Execute production media-state methods on the JVM with deterministic transport fixtures.

This compiles the actual Activity methods, not a rewritten state-machine model. Android UI,
disk, WebView, and time are controlled fixtures so dropped replies and busy-lane timing are
reproducible without a device or network. --source can verify a previous source fails.
"""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = (args.source or root / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')


def method(marker, optional=False):
    if optional and marker not in source:
        return ''
    start = source.index(marker)
    opening = source.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


production = '\n'.join([
    method('private static long positiveId('),
    method('private static long nonnegativeCursor('),
    method('private void reconcileNativeMediaUpload('),
    method('private void sendConnectedMedia('),
    method('private void dispatchConnectedMediaMessage(', optional=True),
    method('private void recoverUncertainMediaConfirmation(AccountScope scopedAccount, Room room) '),
    method('private void recoverUncertainMediaConfirmation(AccountScope scopedAccount, Room room,\n'),
    method('private void reconcilePendingMediaFromVerifiedHistory('),
])

fixture = r'''
import java.io.IOException;
import java.util.*;
public class MediaJourneyHarness {
  static final String V2_ROOMS="/bchat/api/v2/rooms";
  static final int MAX_NATIVE_GRANT_CONTROL_RETRIES=40;
  static final long NATIVE_GRANT_CONTROL_RETRY_MILLIS=250;
  int mediaConfirmDispatchGeneration, mediaSessionGeneration, mediaConfirmRecoveryGeneration;
  boolean mediaConfirmBusy, v2Busy, webV2GetFallbackBusy, allowed=true;
  AccountScope account=new AccountScope(7);
  Room selectedRoom=new Room(1, 2);
  Room mediaConfirmRoom;
  Store mediaStore=new Store();
  FakeHandler handler=new FakeHandler();
  Notice chatNotice=new Notice();
  JSONObject receipt;
  List<JSONObject> history=new ArrayList<>();
  V2Callback dispatchedCallback;
  int posts, reads, retries, appended, updates;
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
  static class BChatConnectedMediaStore {
    static class Entry {
      long mediaId,invoiceCaseId,replyToMessageId;int policyVersion=1;
      String uploadBlockCode="",clientUuid="message-uuid",text="caption",documentType="other";
      String networkUploadUuid(){return "00000000-0000-4000-8000-000000000001";}
    }
  }
  static class Store {
    List<BChatConnectedMediaStore.Entry> pending=new ArrayList<>();int marks,acks;
    List<BChatConnectedMediaStore.Entry> pendingForRoom(AccountScope a,long r,long m)throws IOException{return new ArrayList<>(pending);}
    BChatConnectedMediaStore.Entry markUploaded(AccountScope a,BChatConnectedMediaStore.Entry e,long id)throws IOException{e.mediaId=id;marks++;return e;}
    void acknowledge(AccountScope a,BChatConnectedMediaStore.Entry e)throws IOException{if(!pending.remove(e))throw new IOException();acks++;}
  }
  static class MediaRecord {long id;MediaRecord(JSONObject value){id=((Number)value.get("id")).longValue();}}
  static class Notice {int value;void setText(int v){value=v;}}
  static class R {static class string {
    static final int bchat_media_status_upload_pending=1,bchat_media_checking=2,
      chat_v2_uncertain=3,chat_v2_sent=4,bchat_media_policy_changed=5,bchat_media_rejected=6;
  }}
  static class FakeHandler {
    final ArrayDeque<Runnable> tasks=new ArrayDeque<>();
    void postDelayed(Runnable task,long ignored){tasks.add(task);}
    void next(){if(!tasks.isEmpty())tasks.remove().run();}
    void drain(){for(int i=0;!tasks.isEmpty()&&i<200;i++)next();if(!tasks.isEmpty())throw new AssertionError("Unbounded polling");}
  }
  boolean stillCurrent(AccountScope a,Room r){return a==account&&r==selectedRoom;}
  boolean mediaUploadAllowed(){return allowed;}
  void updatePendingUi(){updates++;}
  void showMissingNativeMediaRetry(AccountScope a,Room r,BChatConnectedMediaStore.Entry e){retries++;}
  void fetchV2(String method,String path,String payload,V2Callback callback){
    if("GET".equals(method)){reads++;callback.complete(200,receipt);}
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
  BChatConnectedMediaStore.Entry entry(long id){BChatConnectedMediaStore.Entry e=new BChatConnectedMediaStore.Entry();e.mediaId=id;mediaStore.pending.add(e);return e;}
  JSONObject receipt(String state){return new JSONObject().put("api_version",2).put("room_id",1).put("membership_id",2)
    .put("upload_uuid","00000000-0000-4000-8000-000000000001").put("state",state);}
  JSONObject ack(){return new JSONObject().put("api_version",2).put("room_id",1).put("membership_id",2)
    .put("media_id",55).put("client_uuid","message-uuid").put("state","sent").put("message_id",77);}
  void sentHistory(){history.add(new JSONObject().put("author_user_id",7).put("media",new JSONObject().put("id",55)));}
  static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
  static int passed,failed;
  static void test(String name,Runnable test){try{test.run();passed++;System.out.println("PASS "+name);}catch(Throwable error){failed++;System.out.println("FAIL "+name+": "+error);}}
  public static void main(String[] args){
    test("missing absent media ID offers safe retry",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("missing");h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.retries==1&&h.posts==0,"missing was rejected or posted");});
    test("missing explicit zero offers safe retry",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("missing").put("media_id",0);h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.retries==1,"numeric zero rejected");});
    test("uploading absent media ID polls without byte retry",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("uploading");h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.handler.tasks.size()==1&&h.retries==0&&h.posts==0,"in-flight was rejected or replayed");h.receipt=h.receipt("missing");h.handler.next();check(h.retries==1,"receipt never rechecked");});
    test("string ID remains rejected",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.receipt=h.receipt("missing").put("media_id","0");h.reconcileNativeMediaUpload(h.account,h.selectedRoom,h.entry(0));check(h.retries==0&&h.posts==0,"string ID accepted");});
    test("native success during busy GET queues exactly one message",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.v2Busy=true;h.receipt=h.receipt("staged").put("media_id",55);BChatConnectedMediaStore.Entry e=h.entry(0);h.reconcileNativeMediaUpload(h.account,h.selectedRoom,e);check(h.mediaConfirmBusy&&h.posts==0&&h.mediaStore.marks==1,"send intent lost at busy guard");h.v2Busy=false;h.handler.next();check(h.posts==1&&h.postedPayload.contains("message-uuid"),"send did not resume");h.sendConnectedMedia(h.account,h.selectedRoom,e);check(h.posts==1,"concurrent send duplicated POST");h.dispatchedCallback.complete(200,h.ack());check(h.mediaStore.acks==1&&!h.mediaConfirmBusy,"ACK did not retire request");});
    test("busy deadline retains local receipt without dispatch",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.v2Busy=true;h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.handler.drain();check(h.posts==0&&!h.mediaConfirmBusy&&h.mediaStore.pending.size()==1&&h.chatNotice.value==R.string.chat_v2_uncertain,"deadline lost request or stayed busy");});
    test("room switch cancels only undispatched intent",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.v2Busy=true;h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.mediaSessionGeneration++;h.selectedRoom=new Room(9,9);h.v2Busy=false;h.handler.drain();check(h.posts==0&&!h.mediaConfirmBusy&&h.mediaStore.pending.size()==1,"old room posted after navigation");});
    test("lost reply reconciles history without second POST",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.sentHistory();h.dispatchedCallback.complete(0,null);h.handler.drain();check(h.posts==1&&h.mediaStore.acks==1&&h.reads==1,"lost ACK repeated write or failed history");});
    test("uncommitted lost reply stays pending without automatic POST",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.dispatchedCallback.complete(0,null);h.handler.drain();check(h.posts==1&&h.mediaStore.acks==0&&h.mediaStore.pending.size()==1,"uncertain request duplicated or discarded");});
    test("verified ACK retires before current-screen check",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.selectedRoom=new Room(9,9);h.dispatchedCallback.complete(200,h.ack());check(h.mediaStore.acks==1&&h.appended==0,"navigation trapped verified local request");});
    test("malformed 2xx reconciles rather than resending",()->{MediaJourneyHarness h=new MediaJourneyHarness();h.sendConnectedMedia(h.account,h.selectedRoom,h.entry(55));h.sentHistory();h.dispatchedCallback.complete(200,new JSONObject());h.handler.drain();check(h.posts==1&&h.mediaStore.acks==1,"malformed 2xx did not reconcile");});
    System.out.println("Media journey: "+passed+" passed, "+failed+" failed");if(failed!=0)System.exit(1);
  }
'''

javac, java = shutil.which('javac'), shutil.which('java')
if not javac or not java:
    raise SystemExit('Existing JDK is required; no dependencies are installed by this test.')
with tempfile.TemporaryDirectory(prefix='bchat-media-journey-') as temporary:
    folder = Path(temporary)
    harness = folder / 'MediaJourneyHarness.java'
    harness.write_text(fixture + '\n' + production + '\n}\n', encoding='utf-8')
    subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(folder), str(harness)], check=True)
    subprocess.run([java, '-cp', str(folder), 'MediaJourneyHarness'], check=True)

import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ChatEngine,ChatError,type Request,type Storage,type Message} from '../core/ChatEngine.ts';
import {MemoryHistoryArchive} from '../core/MemoryHistoryArchive.ts';
import {decodeContentState} from '../core/ContentRetention.ts';
const room={id:11,company_id:1,membership_id:21,name:'Synthetic retention',is_group:true,content_revision:0};
const message:Message={id:1,author_user_id:7,author_name:'Synthetic',text:'old content',created_at:'2026-10-20 10:00:00',media:{id:70,kind:'file',mime:'application/pdf',name:'test.pdf',size:4,sha256:'a'.repeat(64)}};
function fixture(){
 const data=new Map<string,string>(),archive=new MemoryHistoryArchive(),calls:Request[]=[],applied:any[]=[];let revision=0,ids:number[]=[],fail=false,hold:Promise<void>|undefined,contentHold:Promise<void>|undefined,wireMessages:Message[]|undefined,send:((req:Request)=>Promise<any>)|undefined,uuidSequence=0;
 const storage:Storage={async getItem(k){return data.get(k)??null;},async setItem(k,v){data.set(k,v);},async removeItem(k){data.delete(k);},async getAllKeys(){return [...data.keys()];}};
 const transport={async request(req:Request):Promise<any>{calls.push(req);
  if(req.path==='/web/session/destroy')return{result:null};if(req.path==='/web/session/authenticate')return{result:{uid:7,db:'trial'}};
  if(req.path.endsWith('/bootstrap'))return{api_version:2,user_id:7,database:'trial',company_ids:[1],csrf_token:'synthetic',permissions:{chat_view:true,chat_send:true,media:true},capabilities:{retention_version:1,retention_ready:false}};
  if(req.path==='/bchat/api/v2/rooms')return{api_version:2,rooms:[{...room,content_revision:revision}]};
  if(req.path.includes('/changes?'))return{api_version:2,changes:[],next_after:0,watermark:0,reset_required:false};
  if(req.path.endsWith('/content-state')){if(fail)throw new ChatError('connection_failed');const p=JSON.parse(req.form!.payload);assert.equal(p.content_revision,revision);const result={api_version:2,retention_version:1,room_id:11,company_id:1,membership_id:21,content_revision:revision,items:p.media_ids.map((media_id:number)=>({media_id,state:'removed'})),next_cursor:null};await contentHold;return result;}
  if(req.path.endsWith('/messages')){if(req.method==='POST'&&send)return send(req);const result={api_version:2,content_revision:revision,messages:wireMessages??(revision?[]:[message]),next_before_id:null};await hold;return result;}
  throw Error(req.path);
 }};
 const options={origin:'https://retention.test',database:'trial',storage,archive,transport,uuid:()=> `11111111-1111-4111-8111-${String(++uuidSequence).padStart(12,'0')}`,contentCache:{async quarantine(){return ids;},async apply(_s:any,_r:any,_v:any,items:any){applied.push(...items);},async complete(){}}};
 const engine=new ChatEngine(options);
 return{engine,options,data,archive,calls,applied,setRevision(v:number){revision=v;},setIds(v:number[]){ids=v;},setFail(v:boolean){fail=v;},setHold(v?:Promise<void>){hold=v;},setContentHold(v?:Promise<void>){contentHold=v;},setMessages(v:Message[]){wireMessages=v;},setSend(v:(req:Request)=>Promise<any>){send=v;}};
}

test('exact server tombstones and removed replay ACK preserve canonical IDs without resurrecting queued content or deleting a newer unsent stage',async()=>{
 const f=fixture(),removed:string[]=[],uploads:string[]=[];
 const engine=new ChatEngine({...f.options,upload:async(_room,attachment)=>{uploads.push(attachment.upload_uuid);return{media_id:71};},removeAttachment:async attachment=>{removed.push(attachment.uri);}});
 await engine.login('synthetic','synthetic',true);await engine.history(room);
 const oldStage={uri:'file:///owned/stage-old.pdf',name:'old.pdf',mime:'application/pdf',size:4,sha256:'a'.repeat(64),kind:'file' as const,upload_uuid:'22222222-2222-4222-8222-222222222222',media_id:70};
 const old=await engine.enqueueAttachment(room,oldStage,'old queued private text');
 const tombstones=[{id:1,author_user_id:7,author_name:'Synthetic',text:'',created_at:'2026-10-20 10:00:00',content_removed:true},{id:2,author_user_id:8,author_name:'Other',text:'',created_at:'2026-10-20 10:00:01',media_removed:true},{id:3,author_user_id:8,author_name:'Other',text:'caption survives',created_at:'2026-10-20 10:00:02',media_removed:true}];
 f.setRevision(1);f.setMessages(tombstones);let release!:()=>void,started!:()=>void;const held=new Promise<void>(r=>{release=r;}),seen=new Promise<void>(r=>{started=r;});
 f.setSend(async req=>{const p=JSON.parse(req.form!.payload);assert.equal(p.client_uuid,old.client_uuid);started();await held;return{api_version:2,room_id:11,membership_id:21,client_uuid:p.client_uuid,message_id:1,media_id:70,state:'sent',content_removed:true};});
 const pumping=engine.flush();await seen;
 const newStage={...oldStage,uri:'file:///owned/stage-new.pdf',name:'new.pdf',upload_uuid:'33333333-3333-4333-8333-333333333333',media_id:undefined};
 const newer=await engine.enqueueAttachment(engine.rooms()[0]!,newStage,'genuinely unsent');release();const flushed=await pumping;assert.deepEqual(flushed.historyFor(engine.rooms()[0]!)?.messages,tombstones);
 const page=await engine.history(engine.rooms()[0]!);assert.deepEqual(page.messages,tombstones);assert.equal(page.next_before_id,null);
 assert.deepEqual(engine.pending().map(item=>item.client_uuid),[newer.client_uuid]);assert.deepEqual(removed,[oldStage.uri]);assert.deepEqual(uploads,[]);
 assert.equal(JSON.stringify([...f.data]).includes('old queued private text'),false);
 const outboxKey=[...f.data.keys()].find(key=>key.endsWith(newer.client_uuid))!,account=outboxKey.slice(0,outboxKey.indexOf('c/1/r/11/m/21/outbox/'));
 const archived=await f.archive.read({account,companyId:1,roomId:11,membershipId:21},{direction:'latest',limit:10,maxBytes:100000},()=>{});assert.deepEqual(archived.messages,tombstones);
 assert.ok([...f.data].some(([key,value])=>key.endsWith(newer.client_uuid)&&JSON.parse(value).attachment.uri===newStage.uri));
});
test('retention barrier invalidates history retained associations and replies without touching queued text or stages',async()=>{
 const f=fixture();await f.engine.login('synthetic','synthetic',true);await f.engine.history(room);await f.engine.retainMediaAssociation(room,70,true);
 await f.engine.enqueue(room,'unsent',1);const before=[...f.data].filter(([k])=>k.includes('/outbox/'));
 f.setIds([70]);f.setRevision(1);await f.engine.refresh();
 assert.deepEqual(f.applied,[{media_id:70,state:'removed'}]);assert.deepEqual([...f.data].filter(([k])=>k.includes('/outbox/')),before);
 assert.equal(f.engine.pending().length,1);assert.equal(await f.engine.mediaAssociation(f.engine.rooms()[0]!,70),null);
 assert.deepEqual((await f.engine.history(f.engine.rooms()[0]!)).messages,[]);
});
test('incomplete retention reconciliation survives restart without renewing the offline lease or exposing old disk content',async()=>{
 const f=fixture();await f.engine.login('synthetic','synthetic',true);await f.engine.history(room);const lease=f.engine.leaseRemainingMs;
 f.setIds([70]);f.setRevision(1);f.setFail(true);await assert.rejects(f.engine.refresh(),{code:'connection_failed'});
 assert.ok(f.engine.leaseRemainingMs<=lease);const restarted=new ChatEngine(f.options);assert.equal(await restarted.restoreOffline(),true);
 await assert.rejects(restarted.history(restarted.rooms()[0]!),{code:'content_sync_required'});
 assert.ok([...f.data].some(([k,v])=>k.endsWith('/content-state')&&JSON.parse(v).ready===false));
});
test('late old revision history cannot repopulate a reconciled room and revision rollback is rejected',async()=>{
 const f=fixture();await f.engine.login('synthetic','synthetic',true);let release!:()=>void;f.setHold(new Promise<void>(r=>{release=r;}));
 const reading=f.engine.history(room),rejected=assert.rejects(reading,{code:'content_changed',status:409});await Promise.resolve();
 f.setRevision(1);await f.engine.refresh();release();await rejected;f.setHold();
 assert.deepEqual((await f.engine.history(f.engine.rooms()[0]!)).messages,[]);f.setRevision(0);await assert.rejects(f.engine.refresh(),{code:'content_revision_rollback'});
});
test('higher history or binary revision persists quarantine before rejection and survives offline restart without lease renewal',async()=>{
 for(const binary of [false,true]){
  const f=fixture();await f.engine.login('synthetic','synthetic',true);await f.engine.history(room);await f.engine.enqueue(room,'unsent',1);
  const lease=f.engine.leaseRemainingMs,queue=[...f.data].filter(([k])=>k.includes('/outbox/'));f.setRevision(1);
  await assert.rejects(binary?f.engine.checkContentRevision(room,1):f.engine.history(room),{code:'content_changed',status:409});
  const restarted=new ChatEngine(f.options);assert.equal(await restarted.restoreOffline(),true);
  await assert.rejects(restarted.history(restarted.rooms()[0]!),{code:'content_sync_required'});
  assert.ok(restarted.leaseRemainingMs<=lease);assert.deepEqual([...f.data].filter(([k])=>k.includes('/outbox/')),queue);
  f.setRevision(0);await assert.rejects(restarted.refresh(),{code:'content_revision_rollback'});
 }
});
test('content state decoder bounds exact scope IDs removed privacy bytes and cursor progress',()=>{
 const raw={api_version:2,retention_version:1,room_id:11,company_id:1,membership_id:21,content_revision:1,items:[{media_id:70,state:'live',message}],next_cursor:null};
 assert.equal(decodeContentState(raw,room,1,[70]).items.length,1);
 for(const value of [{...raw,company_id:2},{...raw,content_revision:0},{...raw,items:[{media_id:70,state:'removed',message}]},{...raw,items:[{media_id:71,state:'removed'}]},{...raw,items:[]},{...raw,next_cursor:'x'.repeat(257)},{...raw,items:[{...raw.items[0],message:{...message,text:'x'.repeat(140000)}}]}])assert.throws(()=>decodeContentState(value,room,1,[70]));
 assert.throws(()=>decodeContentState({...raw,next_cursor:'same'},room,1,[70],'same'));
});
test('higher revision marker write failure removes stale ready authority before offline restart',async()=>{
 const f=fixture();await f.engine.login('synthetic','synthetic',true);await f.engine.history(room);
 const write=f.options.storage.setItem;f.options.storage.setItem=async(key,value)=>{if(key.endsWith('/content-state'))throw Error('synthetic marker failure');await write(key,value);};
 await assert.rejects(f.engine.checkContentRevision(room,1),/synthetic marker failure/);
 assert.equal([...f.data.keys()].some(key=>key.endsWith('/content-state')),false);f.options.storage.setItem=write;
 const restarted=new ChatEngine(f.options);assert.equal(await restarted.restoreOffline(),true);
 await assert.rejects(restarted.history(restarted.rooms()[0]!),{code:'content_sync_required'});
});
test('held old room refresh cannot lower a newer observed revision or commit old ready authority',async()=>{
 const f=fixture();await f.engine.login('synthetic','synthetic',true);await f.engine.history(room);
 const reconcile=f.archive.reconcile.bind(f.archive);let release!:()=>void,started!:()=>void;
 const held=new Promise<void>(r=>{release=r;}),seen=new Promise<void>(r=>{started=r;}),roomReads=f.calls.filter(call=>call.path==='/bchat/api/v2/rooms').length;let once=true;
 f.archive.reconcile=async(...args)=>{await reconcile(...args);if(once&&f.calls.filter(call=>call.path==='/bchat/api/v2/rooms').length>roomReads){once=false;started();await held;}};
 const refresh=f.engine.refresh(),refreshRejected=assert.rejects(refresh,{code:'content_revision_rollback'});await seen;
 const observe=f.engine.checkContentRevision(room,1),observeRejected=assert.rejects(observe,{code:'content_changed'});release();await refreshRejected;await observeRejected;
 const marker=[...f.data].find(([key])=>key.endsWith('/content-state'))!;assert.deepEqual(JSON.parse(marker[1]),{revision:1,ready:false});
 const restarted=new ChatEngine(f.options);assert.equal(await restarted.restoreOffline(),true);await assert.rejects(restarted.history(restarted.rooms()[0]!),{code:'content_sync_required'});
});
test('unreadable content marker quarantines room without purging offline identity plaintext queue or lease',async()=>{
 const f=fixture();await f.engine.login('synthetic','synthetic',true);await f.engine.history(room);await f.engine.enqueue(room,'unsent');
 const queued=[...f.data].filter(([key])=>key.includes('/outbox/')),lease=f.engine.leaseRemainingMs,read=f.options.storage.getItem;
 f.options.storage.getItem=async key=>{if(key.endsWith('/content-state'))throw Error('synthetic unreadable marker');return read(key);};
 const restarted=new ChatEngine(f.options);assert.equal(await restarted.restoreOffline(),true);
 assert.equal(restarted.identity?.user_id,7);assert.equal(restarted.pending().length,1);assert.ok(restarted.leaseRemainingMs<=lease);
 assert.deepEqual([...f.data].filter(([key])=>key.includes('/outbox/')),queued);
 await assert.rejects(restarted.history(restarted.rooms()[0]!),{code:'content_sync_required'});
});
test('retention reconciliation bounds requests to 200 IDs and a held old actor cannot finish a replacement login marker',async()=>{
 const f=fixture();await f.engine.login('synthetic','synthetic',true);f.setIds(Array.from({length:201},(_,i)=>i+1));f.setRevision(1);await f.engine.refresh();
 const batches=f.calls.filter(r=>r.path.endsWith('/content-state')).map(r=>JSON.parse(r.form!.payload).media_ids.length);assert.deepEqual(batches,[200,1]);assert.equal(f.applied.length,201);
 let release!:()=>void;f.setContentHold(new Promise<void>(r=>{release=r;}));f.setRevision(2);const old=f.engine.refresh(),rejected=assert.rejects(old,{code:'stale_session'});
 while(f.calls.filter(r=>r.path.endsWith('/content-state')).length<3)await Promise.resolve();
 f.setContentHold();await f.engine.login('synthetic','synthetic',true);const markers=[...f.data].filter(([key])=>key.endsWith('/content-state'));release();await rejected;
 assert.deepEqual([...f.data].filter(([key])=>key.endsWith('/content-state')),markers);assert.equal(f.engine.contentReady(f.engine.rooms()[0]!),true);
});

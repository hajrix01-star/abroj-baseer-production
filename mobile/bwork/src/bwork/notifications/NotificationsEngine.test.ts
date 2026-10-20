import { test } from 'node:test';
import assert from 'node:assert/strict';
import { NotificationsEngine, parseIntent } from './NotificationsEngine.ts';

test('canonical notification hints accept legacy schemes only in the explicit QA compatibility profile',()=>{
 const path='notification/11111111-1111-4111-8111-111111111111/task/1';
 assert.ok(parseIntent(`bwork://${path}`));assert.equal(parseIntent(`bchat-trial://${path}`),null);
 assert.ok(parseIntent(`bchat-trial://${path}`,true));assert.equal(parseIntent(`bchat://${path}`,true),null);
});
const uuid='10000000-0000-4000-8000-000000000001';
function setup(configured=true) {
  let authority:any={origin:'https://example.test',db:'fixture',uid:9,epoch:1,companyIds:[1],revision:1,chat:true,task:true,csrf:'synthetic'};
  const calls:any[]=[], state:any={configured,enabled:false,granted:false,scope:'',accountKey:''};
  const native={async status(){calls.push('status');return {...state};},async enable(){calls.push('prompt');state.enabled=state.granted=true;return true;},async disable(){calls.push('disable');state.enabled=false;state.accountKey='';},async clear(){calls.push('clear');state.scope='';state.accountKey='';state.enabled=false;},async token(){calls.push('token');return {installationId:uuid,token:'t'.repeat(64)};},async bind(scope:string,installation:string,token:string,key:string){calls.push('bind');state.scope=scope;state.accountKey=key;return true;}};
  const request=async (r:any)=>{calls.push(r); if(r.path.endsWith('/register'))return {api_version:2,installation_id:uuid,account_key:uuid,push_enabled:true,client:'bwork',preview_enabled:false};return {api_version:2,notification:{id:1,kind:'task',source_ref:{destination:'task',task_id:7,company_id:1}}};};
  const engine=new NotificationsEngine({native,current:()=>authority,request});
  return {engine,native,calls,state,request,setAuthority:(next:any)=>{authority=next;},getAuthority:()=>authority};
}
test('unconfigured notifications never initialize, prompt, obtain a token or make HTTP',async()=>{const a=setup(false);assert.equal(await a.engine.sync(),'unconfigured');assert.equal(await a.engine.enable(),'unconfigured');assert.deepEqual(a.calls,['status','status']);});
test('push enrollment is opt-in, uses form CSRF and requires explicit generic BWork privacy ACK',async()=>{const a=setup();assert.equal(await a.engine.sync(),'disabled');assert.equal(a.calls.some(c=>c==='token'||c==='prompt'||typeof c==='object'),false);assert.equal(await a.engine.enable(),'ready');const r=a.calls.find(c=>typeof c==='object');assert.equal(r.path,'/bwork/api/v2/notifications/register');const p=JSON.parse(r.form.payload);assert.equal(p.client,'bwork');assert.equal(r.form.csrf_token,'synthetic');assert.equal(a.state.accountKey,uuid);});
test('legacy privacy ACK is rejected with no retry that omits BWork discriminator',async()=>{const a=setup();const e=new NotificationsEngine({native:a.native,current:a.getAuthority,request:async r=>{a.calls.push(r);return {api_version:2,installation_id:uuid,account_key:uuid,push_enabled:true};}});assert.equal(await e.enable(),'unavailable');assert.equal(a.calls.filter(c=>typeof c==='object').length,1);assert.equal(a.calls.includes('bind'),false);});
test('late enrollment after actor change cannot bind a previous account',async()=>{const a=setup();let finish:any;const held=new Promise(r=>{finish=r;});const e=new NotificationsEngine({native:a.native,current:a.getAuthority,request:async()=>held});const p=e.enable();await new Promise(r=>setTimeout(r,0));a.setAuthority({...a.getAuthority(),uid:10,epoch:2});finish({api_version:2,installation_id:uuid,account_key:uuid,client:'bwork',preview_enabled:false});assert.equal(await p,'unavailable');assert.equal(a.calls.includes('bind'),false);});
test('notification intent is a bounded hint, not an arbitrary URL or unauthenticated destination',async()=>{assert.ok(parseIntent(`bwork://notification/${uuid}/task/1`));for(const s of ['https://example.test/notification/'+uuid+'/task/1',`bwork://notification/${uuid}/task/0`,`bwork://notification/${uuid}/task/1?q=1`,`bwork://notification/${uuid}/order/1`])assert.equal(parseIntent(s),null);const a=setup();a.engine.intent(`bwork://notification/${uuid}/task/1`);a.setAuthority(null);assert.equal(await a.engine.destination(),null);assert.equal(a.calls.some(c=>typeof c==='object'),false);});
test('event navigation rechecks actor, company and strict authorized destination, never FCM company data',async()=>{const a=setup();await a.engine.enable();a.engine.intent(`bwork://notification/${uuid}/task/1`);assert.deepEqual(await a.engine.destination(),{kind:'task',companyId:1,taskId:7});assert.equal(await a.engine.destination(),null);const b=setup();await b.engine.enable();const e=new NotificationsEngine({native:b.native,current:b.getAuthority,request:async()=>({api_version:2,notification:{id:1,kind:'task',source_ref:{destination:'task',task_id:7,company_id:99}}})});e.intent(`bwork://notification/${uuid}/task/1`);assert.equal(await e.destination(),null);});
test('unregister is scoped and local binding clears even offline before any later actor can see it',async()=>{const a=setup();await a.engine.enable();a.calls.length=0;a.setAuthority(null);await a.engine.invalidate();assert.equal(a.state.accountKey,'');assert.equal(a.calls.some(c=>typeof c==='object'),false);});

test('permission denial and dismissed prompts do not obtain tokens register or navigate',async()=>{
  const a=setup();a.state.enabled=true;a.state.granted=false;
  assert.equal(await a.engine.sync(),'denied');assert.equal(a.calls.includes('token'),false);
  a.native.enable=async()=>false;assert.equal(await a.engine.enable(),'denied');
  a.engine.intent(`bwork://notification/${uuid}/task/1`);assert.equal(await a.engine.destination(),null);assert.equal(a.calls.some(c=>typeof c==='object'),false);
});
test('queued enrollment is bound to the invocation epoch and cannot prompt a replacement account',async()=>{
  const a=setup();const operation=a.engine.enable();a.setAuthority({...a.getAuthority(),epoch:2});assert.equal(await operation,'unavailable');assert.equal(a.calls.includes('prompt'),false);
});
test('logout clears binding before async cleanup and unregister never borrows replacement authority',async()=>{
  const a=setup();a.state.installationId=uuid;await a.engine.enable();a.calls.length=0;
  const cleanup=a.engine.invalidate();assert.equal(a.state.accountKey,'');a.setAuthority({...a.getAuthority(),uid:10,epoch:2});await cleanup;assert.equal(a.calls.some(c=>typeof c==='object'),false);
  const b=setup();b.state.installationId=uuid;await b.engine.enable();b.calls.length=0;await b.engine.disable();assert.equal(b.calls[0],'disable');const r=b.calls.find(c=>typeof c==='object');assert.equal(r.path,'/bwork/api/v2/notifications/unregister');assert.deepEqual(JSON.parse(r.form.payload),{api_version:2,installation_id:uuid});
});
test('host database company grant revision and epoch changes invalidate native binding and stale event completions',async()=>{
  for(const delta of [{origin:'https://other.test'},{db:'other'},{companyIds:[2]},{revision:2},{chat:false},{task:false}]){
    const a=setup();await a.engine.enable();a.setAuthority({...a.getAuthority(),...delta});a.calls.length=0;assert.equal(await a.engine.sync(),'disabled');assert.equal(a.state.accountKey,'');assert.equal(a.calls.includes('token'),false);
  }
  const a=setup();await a.engine.enable();let finish:any;
  const engine=new NotificationsEngine({native:a.native,current:a.getAuthority,request:()=>new Promise(r=>{finish=r;})});engine.intent(`bwork://notification/${uuid}/task/1`);
  const result=engine.destination();await new Promise(r=>setTimeout(r,0));a.setAuthority({...a.getAuthority(),epoch:2});finish({api_version:2,notification:{id:1,kind:'task',source_ref:{destination:'task',company_id:1,task_id:7}}});assert.equal(await result,null);
});
test('legacy server rejection missing privacy ACK and false push status cannot bind or downgrade registration',async()=>{
  for(const ack of [null,{api_version:2,installation_id:uuid,account_key:uuid,client:'bwork',preview_enabled:false,push_enabled:false},new Error('invalid_payload')]){
    const a=setup();let calls=0;const engine=new NotificationsEngine({native:a.native,current:a.getAuthority,request:async r=>{calls++;assert.equal(JSON.parse(r.form!.payload).client,'bwork');if(ack instanceof Error)throw ack;return ack;}});
    assert.equal(await engine.enable(),'unavailable');assert.equal(calls,1);assert.equal(a.calls.includes('bind'),false);assert.equal(a.state.accountKey,'');
  }
});
test('only one authorized lookup consumes a tap and mismatched account hints never fetch or mark read',async()=>{
  const a=setup();await a.engine.enable();a.calls.length=0;a.engine.intent('bwork://notification/20000000-0000-4000-8000-000000000002/task/1');assert.equal(await a.engine.destination(),null);assert.equal(a.calls.some(c=>typeof c==='object'),false);
  a.engine.intent(`bwork://notification/${uuid}/task/1`);const results=await Promise.all([a.engine.destination(),a.engine.destination()]);assert.equal(results.filter(Boolean).length,1);assert.equal(a.calls.filter(c=>typeof c==='object').length,1);assert.match(a.calls.find(c=>typeof c==='object').path,/notifications\/1$/);
});

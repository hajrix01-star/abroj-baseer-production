const {test}=require('node:test'),assert=require('node:assert/strict');
const {harness,nodes}=require('./tasks-harness.cjs');
const target=(app,taskId=7,companyId=2,nonce=1)=>({taskId,companyId,nonce,authority:app.module(require('node:path').resolve(__dirname,'TasksScreen.tsx')).taskNotificationScope(app.props.identity,app.props.scopeKey)});
test('notification task target rereads only the authorized modern company and falls back safely to inbox',async()=>{
  const app=harness();app.props.notificationTarget=target(app);
  try{await app.flush();assert.deepEqual(app.calls.find(c=>c[0]==='detail'),['detail',7,2]);assert.ok(nodes(app.render()).some(n=>n.props?.testID==='task-detail'));
    app.engine.detail=async()=>{throw {code:'not_found',status:404};};app.props.notificationTarget=target(app,8,2,2);await app.flush();assert.equal(nodes(app.render()).some(n=>n.props?.testID==='task-detail'),false);
    const before=app.calls.length;app.props.notificationTarget=target(app,8,99,3);await app.flush();assert.equal(app.calls.slice(before).some(c=>c[0]==='detail'),false);
  }finally{await app.unmount();}
});
test('late notification task detail cannot cross hidden presentation or a replacement identity',async()=>{
  const app=harness();let release;try{await app.flush();app.engine.detail=()=>new Promise(r=>{release=r;});app.props.notificationTarget=target(app);await app.flush();
    app.props.presented=false;await app.flush();await app.act(()=>release({task:app.task()}));assert.equal(nodes(app.render()).some(n=>n.props?.testID==='task-detail'),false);
    app.props.identity={...app.props.identity,user_id:10};app.props.scopeKey='another';app.props.presented=true;app.props.notificationTarget=undefined;await app.flush();assert.equal(nodes(app.render()).some(n=>n.props?.testID==='task-detail'),false);
  }finally{await app.unmount();}
});
test('retained notification task targets are suppressed before a new actor company or revision workspace can consume them',async()=>{
  for(const change of [app=>app.props.scopeKey='new-epoch',app=>app.props.identity={...app.props.identity,user_id:10},app=>app.props.identity={...app.props.identity,company_ids:[2]},app=>app.props.identity={...app.props.identity,permissions:{...app.props.identity.permissions,revision:2}}]){
    const app=harness({presented:false});try{app.props.notificationTarget=target(app);await app.flush();change(app);app.props.presented=true;await app.flush();assert.equal(app.calls.some(c=>c[0]==='detail'),false);}finally{await app.unmount();}
  }
});

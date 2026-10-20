const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const React=require('react'),renderer=require('react-test-renderer');
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
function harness(language='ar'){
  let mounted;const calls=[],listeners={},state={currentState:'active',addEventListener(_event,callback){listeners.state=callback;return {remove(){delete listeners.state;}};}};
  const engine={async sync(){calls.push('sync');return 'unconfigured';},async enable(){calls.push('enable');return 'ready';},async disable(){calls.push('disable');return 'disabled';},intent(url){calls.push(['intent',url]);},async destination(){calls.push('destination');return {kind:'task',companyId:1,taskId:7};}};
  const modules={react:React,'react/jsx-runtime':require('react/jsx-runtime'),'react-native':{View:'View',AppState:state,NativeModules:{},Linking:{getInitialURL:async()=>null,addEventListener(_event,callback){listeners.url=callback;return {remove(){delete listeners.url;}};}}},'../ui/components':{Button:'Button',Label:'Label',Sheet:'Sheet'},'../ui/dictionary':{translator:()=>x=>x}};
  const load=file=>{const mod={exports:{}};const output=ts.transpileModule(fs.readFileSync(path.join(__dirname,file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;vm.runInNewContext(output,{module:mod,exports:mod.exports,require:name=>name==='./dictionary'?load('dictionary.ts'):modules[name],console});return mod.exports;};
  const Screen=load('NotificationsHub.tsx').NotificationsHub,props={engine,language,ready:true,scopeKey:'actor1',visible:true,close:()=>calls.push('close'),onDestination:value=>calls.push(['navigate',value])};
  const flush=async()=>renderer.act(async()=>{if(!mounted)mounted=renderer.create(React.createElement(Screen,props));else mounted.update(React.createElement(Screen,props));});
  return {props,engine,calls,listeners,state,flush,buttons:()=>mounted.root.findAllByType('Button'),text:()=>JSON.stringify(mounted.toJSON()),async act(fn){await renderer.act(async()=>{await fn();});},async unmount(){await renderer.act(()=>mounted?.unmount());}};
}
test('notification settings honestly show unconfigured AR EN status and cannot prompt from a disabled or stale button',async()=>{
  for(const language of ['ar','en']){const app=harness(language);try{await app.flush();assert.equal(app.buttons()[0].props.disabled,true);assert.match(app.text(),language==='ar'?/غير مهيأة/:/not configured/);await app.act(()=>app.buttons()[0].props.onPress());assert.equal(app.calls.includes('enable'),false);}finally{await app.unmount();}}
  const app=harness();try{app.engine.sync=async()=>'disabled';await app.flush();const old=app.buttons()[0].props.onPress;app.props.scopeKey='actor2';await app.flush();await app.act(old);assert.equal(app.calls.includes('enable'),false);app.props.visible=false;await app.flush();await app.act(old);assert.equal(app.calls.includes('enable'),false);}finally{await app.unmount();}
});
test('foreground delivery never navigates without a tap and background or late UI work cannot navigate',async()=>{
  const app=harness();try{app.engine.sync=async()=>'ready';app.engine.destination=async()=>null;await app.flush();assert.equal(app.calls.some(c=>Array.isArray(c)&&c[0]==='navigate'),false);
    let resolve;app.engine.destination=()=>new Promise(r=>{resolve=r;});await app.act(()=>app.listeners.url({url:'bwork://notification/synthetic/task/1'}));app.props.ready=false;app.state.currentState='background';await app.flush();await app.act(()=>resolve({kind:'task',companyId:1,taskId:7}));assert.equal(app.calls.some(c=>Array.isArray(c)&&c[0]==='navigate'),false);
  }finally{await app.unmount();}
});

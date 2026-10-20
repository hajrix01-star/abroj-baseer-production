const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {execFileSync}=require('node:child_process');
const jdk=process.env.JAVA_HOME||'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
const bin=name=>path.join(jdk,'bin',name+(process.platform==='win32'?'.exe':''));
const source=path.join(__dirname,'../android/com/baseer/bwork/notifications');
const {contract,artifact}=require('../sdk.cjs');
function classpath(temp,files){return files.map((file,index)=>{if(file.endsWith('.jar'))return file;const dir=path.join(temp,'aar'+index);fs.mkdirSync(dir);execFileSync(bin('jar'),['xf',file,'classes.jar'],{cwd:dir});return path.join(dir,'classes.jar');});}
test('production disabled and enabled push native sources compile offline against cached RN Android and Firebase SDKs',()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-push-native-compile-'));
  const files=contract.push.map(artifact);
  const cp=[path.join(process.env.ANDROID_HOME||'D:/Codex/AndroidSdk','platforms/android-36/android.jar'),...classpath(temp,files)].join(path.delimiter);
  for(const mode of ['disabled','enabled']){
    const target=path.join(temp,mode);fs.mkdirSync(target);
    const sources=['PushPolicy.java','PushState.java','PushCallbacks.java','BWorkNotificationsModule.java','BWorkNotificationsPackage.java'].map(file=>path.join(source,file));
    sources.push(path.join(source,mode,'PushBackend.java'));if(mode==='enabled')sources.push(path.join(source,mode,'BWorkMessagingService.java'));
    execFileSync(bin('javac'),['-encoding','UTF-8','-cp',cp,'-d',target,...sources],{stdio:'pipe'});
    assert.ok(fs.existsSync(path.join(target,'com/baseer/bwork/notifications/BWorkNotificationsModule.class')));
    assert.equal(fs.existsSync(path.join(target,'com/baseer/bwork/notifications/BWorkMessagingService.class')),mode==='enabled');
  }
});
test('native push policy accepts only bounded account event hints and generic localized text',async()=>{
  const service=fs.readFileSync(path.join(source,'enabled/BWorkMessagingService.java'),'utf8');
  assert.doesNotMatch(service,/bwork-trial:\/\//);
  assert.match(service,/String route=PushPolicy\.notificationUri\(account,kind,event\)/);
  assert.match(service,/route==null/);assert.match(service,/Uri\.parse\(route\)/);
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-push-policy-'));
  execFileSync(bin('javac'),['-encoding','UTF-8','-d',temp,path.join(source,'PushPolicy.java'),path.join(source,'PushCallbacks.java'),path.join(__dirname,'PushPolicyHarness.java')]);
  const output=execFileSync(bin('java'),['-ea','-cp',temp,'com.baseer.bwork.notifications.PushPolicyHarness'],{encoding:'utf8'});
  assert.match(output,/PASS/);
  const {parseIntent}=await import('../../src/bwork/notifications/NotificationsEngine.ts');
  const identity=require('../../compatibility/identities.json');
  const hints=[...output.matchAll(/^URI_(CHAT|TASK)=(.+)$/gm)];assert.equal(hints.length,2);
  for(const [,kind,uri] of hints){
    const expected={accountKey:'10000000-0000-4000-8000-000000000001',kind:kind.toLowerCase(),eventId:kind==='CHAT'?1:2147483647};
    assert.ok(uri.startsWith(identity.production.scheme+'://notification/'));
    assert.deepEqual(parseIntent(uri),expected);assert.deepEqual(parseIntent(uri,true),expected);
    const legacy=uri.replace(identity.production.scheme+'://',identity.qa.legacyScheme+'://');
    assert.equal(parseIntent(legacy),null);assert.deepEqual(parseIntent(legacy,true),expected);
  }
  assert.match(service,/if\(PushState.foreground\)return/);assert.match(service,/PushState.accept/);assert.match(service,/PushPolicy.body/);
  assert.doesNotMatch(service.replace(/\/\*[\s\S]*?\*\//g,''),/sender_name|message_preview|https?:|fetch\(|ReactApplication|markRead|outbox\./);
});

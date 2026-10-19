const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {execFileSync}=require('node:child_process');
const jdk=process.env.JAVA_HOME||'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
const bin=name=>path.join(jdk,'bin',name+(process.platform==='win32'?'.exe':''));
const source=path.join(__dirname,'../android/com/baseer/bchat/trial/notifications');
const cache=path.join(process.env.GRADLE_USER_HOME||path.join(os.homedir(),'.gradle'),'caches/modules-2/files-2.1');
function artifacts(group,artifact,version){const root=path.join(cache,group,artifact,version);assert.ok(fs.existsSync(root),'Required offline SDK cache is present');return fs.readdirSync(root).flatMap(hash=>fs.readdirSync(path.join(root,hash)).filter(file=>/\.(aar|jar)$/.test(file)).map(file=>path.join(root,hash,file)));}
function classpath(temp,files){return files.map((file,index)=>{if(file.endsWith('.jar'))return file;const dir=path.join(temp,'aar'+index);fs.mkdirSync(dir);execFileSync(bin('jar'),['xf',file,'classes.jar'],{cwd:dir});return path.join(dir,'classes.jar');});}
test('production disabled and enabled push native sources compile offline against cached RN Android and Firebase SDKs',()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-push-native-compile-'));
  const files=[...artifacts('com.facebook.react','react-android','0.86.0')];
  // Known public SDK coordinates only. No downloads, project files or credentials.
  for(const group of ['com.google.firebase','com.google.android.gms','org.jetbrains.kotlin','androidx.annotation']){
    const root=path.join(cache,group);if(!fs.existsSync(root))continue;
    for(const artifact of fs.readdirSync(root)){
      if(!/^(firebase-|play-services-tasks$|play-services-basement$|kotlin-stdlib|annotation)/.test(artifact))continue;
      for(const version of fs.readdirSync(path.join(root,artifact)))files.push(...artifacts(group,artifact,version));
    }
  }
  const cp=[path.join(process.env.ANDROID_HOME||'D:/Codex/AndroidSdk','platforms/android-36/android.jar'),...classpath(temp,files)].join(path.delimiter);
  for(const mode of ['disabled','enabled']){
    const target=path.join(temp,mode);fs.mkdirSync(target);
    const sources=['PushPolicy.java','PushState.java','PushCallbacks.java','BWorkNotificationsModule.java','BWorkNotificationsPackage.java'].map(file=>path.join(source,file));
    sources.push(path.join(source,mode,'PushBackend.java'));if(mode==='enabled')sources.push(path.join(source,mode,'BWorkMessagingService.java'));
    execFileSync(bin('javac'),['-encoding','UTF-8','-cp',cp,'-d',target,...sources],{stdio:'pipe'});
    assert.ok(fs.existsSync(path.join(target,'com/baseer/bchat/trial/notifications/BWorkNotificationsModule.class')));
    assert.equal(fs.existsSync(path.join(target,'com/baseer/bchat/trial/notifications/BWorkMessagingService.class')),mode==='enabled');
  }
});
test('native push policy accepts only bounded account event hints and generic localized text',()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-push-policy-'));
  execFileSync(bin('javac'),['-encoding','UTF-8','-d',temp,path.join(source,'PushPolicy.java'),path.join(source,'PushCallbacks.java'),path.join(__dirname,'PushPolicyHarness.java')]);
  assert.match(execFileSync(bin('java'),['-ea','-cp',temp,'com.baseer.bchat.trial.notifications.PushPolicyHarness'],{encoding:'utf8'}),/PASS/);
  const service=fs.readFileSync(path.join(source,'enabled/BWorkMessagingService.java'),'utf8');
  assert.match(service,/if\(PushState.foreground\)return/);assert.match(service,/PushState.accept/);assert.match(service,/PushPolicy.body/);
  assert.doesNotMatch(service.replace(/\/\*[\s\S]*?\*\//g,''),/sender_name|message_preview|https?:|fetch\(|ReactApplication|markRead|outbox\./);
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const identity=require('../../compatibility/identities.json');
const {profile}=require('../../bwork-profile.cjs');
const {applySigningBoundary,applyNativeBoundary}=require('../../with-bwork-native.js');
const {execFileSync}=require('node:child_process');
const production=()=>({BWORK_PROFILE:'production',EXPO_PUBLIC_BWORK_PROFILE:'production',EXPO_PUBLIC_BWORK_ORIGIN:identity.production.origin,EXPO_PUBLIC_BWORK_DATABASE:identity.production.database,BWORK_RELEASE_KEYSTORE:'synthetic-path-only.jks',BWORK_RELEASE_KEY_ALIAS:'publisher-release',BWORK_RELEASE_STORE_PASSWORD:'synthetic-secret-not-used',BWORK_RELEASE_KEY_PASSWORD:'synthetic-secret-not-used'});
test('QA upgrade and independent production identities preserve durable namespaces without importing either container',()=>{
  const qa=profile({}),prod=profile(production(),()=>true);
  assert.equal(qa.applicationId,'com.baseer.bchat.trial');assert.equal(prod.applicationId,'com.baseer.bwork');assert.notEqual(qa.applicationId,prod.applicationId);
  assert.deepEqual(qa.schemes,['bwork','bchat-trial']);assert.deepEqual(prod.schemes,['bwork']);
  assert.equal(identity.storage.chatRoot,'odoo-chat/v1/');assert.equal(identity.storage.mediaDirectory,'odoo-chat-media');assert.equal(identity.storage.sqlite,'bwork-history-v1.db');
  const boundary=fs.readFileSync(path.join(__dirname,'../../src/bwork/compatibility.ts'),'utf8');assert.doesNotMatch(boundary,/copy|move|remove|readFile|mkdir/);
});
test('production signing and realm configuration fail closed without opening secrets or falling back to QA debug credentials',()=>{
  let probes=0;const exists=()=>{probes++;return true;};assert.equal(profile(production(),exists).name,'production');assert.equal(probes,1);
  for(const key of Object.keys(production())){const env=production();delete env[key];assert.throws(()=>profile(env,()=>true),key);}
  assert.throws(()=>profile(production(),()=>false));assert.throws(()=>profile({...production(),BWORK_RELEASE_KEY_ALIAS:'androiddebugkey'},()=>true));
  assert.throws(()=>profile({...production(),EXPO_PUBLIC_ODOO_ORIGIN:'https://qa.example.test'},()=>true),/conflict/);
  assert.throws(()=>profile({...production(),EXPO_PUBLIC_BWORK_PROFILE:'qa'},()=>true),/mismatch/);
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-signing-source-')),app=path.join(root,'android/app');fs.mkdirSync(app,{recursive:true});fs.writeFileSync(path.join(app,'build.gradle'),'android {}\n');
  applySigningBoundary(root,{name:'production'});const generated=fs.readFileSync(path.join(app,'build.gradle'),'utf8');
  assert.match(generated,/release \{ signingConfig signingConfigs\.bworkProduction/);assert.match(generated,/throw new GradleException/);assert.doesNotMatch(generated,/synthetic-secret|storePassword ['"]|signingConfigs\.debug/);
  applySigningBoundary(root,{name:'qa'});assert.doesNotMatch(fs.readFileSync(path.join(app,'build.gradle'),'utf8'),/bworkProduction|BWORK_RELEASE_KEYSTORE/);
});

test('legacy original serialized producers remain readable without rewriting source bytes or merging QA and production containers',()=>{
  const root=path.resolve(__dirname,'../../../../android/bwork-legacy');
  const java=path.join(root,'app/src/main/java/com/baseer/bwork/legacy');
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-legacy-compat-'));
  const jdk=process.env.JAVA_HOME||'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
  const bin=name=>path.join(jdk,'bin',name+(process.platform==='win32'?'.exe':''));
  execFileSync(bin('javac'),['-encoding','UTF-8','-d',temp,...['compat/LegacyIdentity.java','LegacyPreflight.java','StoreJournal.java','ChatStore.java'].map(file=>path.join(java,file)),path.join(root,'tests/ChatStoreTest.java'),path.join(__dirname,'LegacyIdentityHarness.java')]);
  assert.match(execFileSync(bin('java'),['-cp',temp,'LegacyIdentityHarness'],{encoding:'utf8'}),/PASS original v1\/v2/);
  const projection=fs.readFileSync(path.join(java,'compat/LegacyIdentity.java'),'utf8');
  for(const [key,value]of Object.entries(identity.legacyStorage))assert.ok(projection.includes(`String ${key} = ${JSON.stringify(value)}`),key);
});

test('canonical native projection replaces only known old adapters and keeps installed QA entrypoint and legacy shortcut aliases',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-projection-')),app=path.join(root,'android/app');
 const installed=path.join(app,'src/main/java',identity.qa.applicationId.replaceAll('.','/'));
 fs.mkdirSync(path.join(installed,'session'),{recursive:true});fs.writeFileSync(path.join(installed,'session/OriginCookieJar.java'),'old generated adapter');
 fs.writeFileSync(path.join(installed,'MainActivity.kt'),'retained QA entrypoint');
 fs.writeFileSync(path.join(installed,'MainApplication.kt'),'PackageList(this).packages.apply {\n}\noverride fun onCreate() {\n    super.onCreate()\n    loadReactNative(this)\n  }');
 fs.writeFileSync(path.join(app,'build.gradle'),'android {}\n');
 applyNativeBoundary(root,identity.qa.applicationId,'https://qa.example.test');
 assert.equal(fs.existsSync(path.join(installed,'session/OriginCookieJar.java')),false);
 assert.equal(fs.readFileSync(path.join(installed,'MainActivity.kt'),'utf8'),'retained QA entrypoint');
 assert.match(fs.readFileSync(path.join(installed,'MainApplication.kt'),'utf8'),/com\.baseer\.bwork\.session/);
 const waveform=fs.readFileSync(path.join(app,'src/main/java/com/baseer/bwork/feedback/BWorkWaveformModule.java'),'utf8');assert.ok(waveform.includes(identity.storage.mediaDirectory));assert.doesNotMatch(waveform,/__BWORK_MEDIA_DIRECTORY__/);
 const legacy=path.resolve(__dirname,'../../../../android/bwork-legacy/app/src');
 for(const file of ['main/AndroidManifest.xml','gradle/AndroidManifest.xml','gradle/AndroidManifestPush.xml']){
  const source=fs.readFileSync(path.join(legacy,file),'utf8');assert.ok(source.includes(`android:name="${identity.legacyPreview.originalComponent}"`));assert.match(source,/activity-alias[^>]+targetActivity="com\.baseer\.bwork\.legacy\.BWorkIdentityActivity"/);
 }
});

test('production pins its sole public origin database and version before any signing-file existence probe while QA stays compatible',()=>{
 const good=production();let probes=0;
 for(const origin of ['https://baseer-live-qa.tail938958.ts.net','https://localhost','https://127.0.0.1','https://10.0.0.1','https://192.168.1.1','https://[::1]','https://baseer.abroj.sa:444','http://baseer.abroj.sa','https://baseer.abroj.sa/','https://baseer.abroj.sa/path','https://baseer.abroj.sa?x=1','https://baseer.abroj.sa.evil.test','https://user@baseer.abroj.sa']){
  assert.throws(()=>profile({...good,EXPO_PUBLIC_BWORK_ORIGIN:origin},()=>{probes++;return true;}),origin);
 }
 for(const database of ['baseer_live_qa_clean_20260928','baseer_prod_copy',' baseer_prod','baseer_prod '])assert.throws(()=>profile({...good,EXPO_PUBLIC_BWORK_DATABASE:database},()=>{probes++;return true;}));
 assert.equal(probes,0);
 const prod=profile(good,()=>true);assert.equal(prod.origin,'https://baseer.abroj.sa');assert.equal(prod.database,'baseer_prod');assert.equal(prod.version,'1.0.0');assert.equal(prod.versionCode,1);
 const qa=profile({EXPO_PUBLIC_ODOO_ORIGIN:'https://qa.example.test',EXPO_PUBLIC_ODOO_DATABASE:'synthetic_qa'});
 assert.equal(qa.origin,'https://qa.example.test');assert.equal(qa.database,'synthetic_qa');assert.equal(qa.version,'0.1.32');assert.equal(qa.versionCode,33);
});

test('production native staging rejects a caller origin different from the selected profile before touching generated files',()=>{
 const vm=require('node:vm'),pluginRequire=require('node:module').createRequire(path.join(__dirname,'../../with-bwork-native.js'));
 const mod={exports:{}};const selected=profile(production(),()=>true);
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../with-bwork-native.js'),'utf8'),{module:mod,exports:mod.exports,URL,__dirname:path.join(__dirname,'../..'),require:name=>name==='./bwork-profile.cjs'?{profile:()=>selected}:pluginRequire(name)});
 for(const origin of ['https://baseer-live-qa.tail938958.ts.net','https://localhost','https://baseer.abroj.sa/'])assert.throws(()=>mod.exports.applyNativeBoundary('unused-no-files',selected.applicationId,origin),/production origin mismatch/);
 assert.throws(()=>mod.exports.applyNativeBoundary('unused-no-files',identity.qa.applicationId,selected.origin),/profile\/package mismatch/);
});

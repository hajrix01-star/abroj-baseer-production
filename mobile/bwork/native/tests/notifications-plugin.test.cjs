const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {pushOptions,validatePublicConfig,applyNativePushBoundary,patchApplication}=require('../../with-bwork-push.js');
const identity=require('../../compatibility/identities.json');
const fixture=(applicationId=identity.qa.applicationId)=>({project_info:{project_id:'bwork-public-test',project_number:'123456789'},client:[{client_info:{android_client_info:{package_name:applicationId},mobilesdk_app_id:'1:123456789:android:abcdef'},api_key:[{current_key:'synthetic_public_key_not_a_credential'}]}]});
test('optional push config is disabled without reads and enabled missing or mismatched public config fails build closed',()=>{
  assert.deepEqual(pushOptions({EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE:'Z:/never-read.json'}),{enabled:false});
  assert.deepEqual(pushOptions({BWORK_ANDROID_PUSH_ENABLED:'0'}),{enabled:false});
  assert.throws(()=>pushOptions({BWORK_ANDROID_PUSH_ENABLED:'yes'}));
  assert.throws(()=>pushOptions({BWORK_ANDROID_PUSH_ENABLED:'1'}));
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-public-config-')),file=path.join(root,'test-only-public-config.json');
  const env={BWORK_ANDROID_PUSH_ENABLED:'1',BWORK_FCM_PROJECT_ID:'bwork-public-test',EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE:file};
  assert.throws(()=>pushOptions(env));
  fs.writeFileSync(file,JSON.stringify(fixture()));assert.equal(pushOptions(env).enabled,true);
  for(const change of [x=>x.project_info.project_id='different-project',x=>x.client[0].client_info.android_client_info.package_name='com.baseer.bchat.preview',x=>x.client[0].client_info.mobilesdk_app_id='1:9999:android:abcdef',x=>x.client[0].api_key=[],x=>x.client.push(x.client[0])]){const config=fixture();change(config);fs.writeFileSync(file,JSON.stringify(config));assert.throws(()=>pushOptions(env));}
});
function project(applicationId=identity.qa.applicationId){const root=fs.mkdtempSync(path.join(os.tmpdir(),'bwork-push-projection-'));const app=path.join(root,'android/app'),main=path.join(app,'src/main/java',applicationId.replaceAll('.','/'));fs.mkdirSync(main,{recursive:true});fs.writeFileSync(path.join(main,'MainApplication.kt'),'PackageList(this).packages.apply {\n}');fs.writeFileSync(path.join(app,'src/main/AndroidManifest.xml'),'<manifest><application></application></manifest>');fs.writeFileSync(path.join(app,'build.gradle'),'android {}\n');fs.writeFileSync(path.join(root,'android/build.gradle'),"dependencies {\n classpath('com.android.tools.build:gradle')\n}\n");return root;}
test('disabled native projection has no Firebase SDK service plugin or auto-init and switching configurations is deterministic',()=>{
  const root=project(),app=path.join(root,'android/app'),file=path.join(root,'synthetic-public-config.json');fs.writeFileSync(file,JSON.stringify(fixture()));
  const options=pushOptions({BWORK_ANDROID_PUSH_ENABLED:'1',BWORK_FCM_PROJECT_ID:'bwork-public-test',EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE:file});
  applyNativePushBoundary(root,options);const enabled=fs.readFileSync(path.join(app,'build.gradle'),'utf8');assert.match(enabled,/firebase-bom:34\.19\.0/);assert.match(enabled,/firebase-messaging:25\.1\.3/);assert.match(fs.readFileSync(path.join(root,'android/build.gradle'),'utf8'),/google-services:4\.5\.0/);assert.match(fs.readFileSync(path.join(app,'src/main/AndroidManifest.xml'),'utf8'),/firebase_messaging_auto_init_enabled" android:value="false/);
  applyNativePushBoundary(root,{enabled:false});applyNativePushBoundary(root,{enabled:false});
  for(const file of ['build.gradle','src/main/AndroidManifest.xml','src/bworkPush/java/com/baseer/bwork/notifications/PushBackend.java'])assert.doesNotMatch(fs.readFileSync(path.join(app,file),'utf8'),/com\.google\.firebase|google-services|MESSAGING_EVENT|firebase-bom/);
  assert.equal(fs.existsSync(path.join(app,'src/bworkPush/java/com/baseer/bwork/notifications/BWorkMessagingService.java')),false);
  assert.equal(fs.readFileSync(path.join(app,'src/main/java',identity.qa.applicationId.replaceAll('.','/'),'MainApplication.kt'),'utf8').split('bwork-notifications-package').length,2);
  assert.throws(()=>applyNativePushBoundary(root,{enabled:false},'wrong.package'));assert.throws(()=>patchApplication('unknown template'));
});

test('public FCM validation is pure and bound to the exact supported Android package and expected project',()=>{
 for(const packageName of [identity.qa.applicationId,identity.production.applicationId]){
  assert.doesNotThrow(()=>validatePublicConfig(fixture(packageName),packageName,'bwork-public-test'));
  assert.throws(()=>validatePublicConfig(fixture(packageName),packageName,'wrong-project'));
  assert.throws(()=>validatePublicConfig(fixture(packageName),packageName===identity.qa.applicationId?identity.production.applicationId:identity.qa.applicationId,'bwork-public-test'));
 }
 assert.throws(()=>validatePublicConfig(fixture(),'wrong.package','bwork-public-test'));
 assert.throws(()=>validatePublicConfig(null,identity.production.applicationId,'bwork-public-test'));
});

test('production FCM staging revalidates its explicit package without dropping to QA or requiring signing inputs again',()=>{
 const root=project(identity.production.applicationId),file=path.join(root,'synthetic-public-config.json');
 fs.writeFileSync(file,JSON.stringify(fixture(identity.production.applicationId)));
 const options=pushOptions({BWORK_PROFILE:'production',EXPO_PUBLIC_BWORK_PROFILE:'production',EXPO_PUBLIC_BWORK_ORIGIN:identity.production.origin,EXPO_PUBLIC_BWORK_DATABASE:identity.production.database,
  BWORK_RELEASE_KEYSTORE:'synthetic-reference-never-opened',BWORK_RELEASE_KEY_ALIAS:'synthetic-publisher',BWORK_RELEASE_STORE_PASSWORD:'synthetic-not-used',BWORK_RELEASE_KEY_PASSWORD:'synthetic-not-used',
  BWORK_ANDROID_PUSH_ENABLED:'1',BWORK_FCM_PROJECT_ID:'bwork-public-test',EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE:file},root,()=>true);
 assert.equal(options.applicationId,identity.production.applicationId);
 applyNativePushBoundary(root,options,identity.production.applicationId);
 assert.match(fs.readFileSync(path.join(root,'android/app/src/main/java/com/baseer/bwork/MainApplication.kt'),'utf8'),/bwork-notifications-package/);
 assert.throws(()=>applyNativePushBoundary(root,options,identity.qa.applicationId),/options\/native package mismatch/);
});

test('changed public config fails staging before generated writes and disabled production needs no public config read',()=>{
 const root=project(identity.production.applicationId),file=path.join(root,'synthetic-public-config.json');
 fs.writeFileSync(file,JSON.stringify(fixture(identity.production.applicationId)));
 const options={enabled:true,configFile:file,project:'bwork-public-test',applicationId:identity.production.applicationId};
 fs.writeFileSync(file,JSON.stringify(fixture(identity.qa.applicationId)));
 assert.throws(()=>applyNativePushBoundary(root,options,identity.production.applicationId));
 assert.equal(fs.existsSync(path.join(root,'android/app/src/bworkPush')),false);
 assert.deepEqual(pushOptions({BWORK_PROFILE:'production',EXPO_PUBLIC_BWORK_PROFILE:'production',BWORK_ANDROID_PUSH_ENABLED:'0',EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE:'Z:/never-read-production.json'}),{enabled:false});
 applyNativePushBoundary(root,{enabled:false},identity.production.applicationId);
 assert.doesNotMatch(fs.readFileSync(path.join(root,'android/app/build.gradle'),'utf8'),/firebase|google-services/);
});

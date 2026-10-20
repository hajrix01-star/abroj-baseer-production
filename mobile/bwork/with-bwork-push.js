const fs = require('node:fs');
const path = require('node:path');
const { withDangerousMod } = require('@expo/config-plugins');
const identity = require('./compatibility/identities.json');
const { profile } = require('./bwork-profile.cjs');
const PACKAGE = identity.qa.applicationId;
// Public Firebase identifiers only. Never discovers a project or reads credentials.
function pushOptions(env = process.env, root = __dirname) {
  if (env.BWORK_ANDROID_PUSH_ENABLED === undefined || env.BWORK_ANDROID_PUSH_ENABLED === '0') return { enabled: false };
  if (env.BWORK_ANDROID_PUSH_ENABLED !== '1') throw new Error('BWork push flag must be 0 or 1');
  const applicationId = profile(env).applicationId;
  const file = env.EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE, project = env.BWORK_FCM_PROJECT_ID;
  if (!file || !project || !/^[a-z][a-z0-9-]{3,62}$/.test(project)) throw new Error('BWork push requires an explicit public config and expected project');
  let data;
  try { data = JSON.parse(fs.readFileSync(path.resolve(root, file), 'utf8')); } catch { throw new Error('BWork push public config is unavailable'); }
  const clients = Array.isArray(data.client) ? data.client.filter(c => c?.client_info?.android_client_info?.package_name === applicationId) : [];
  if (data.project_info?.project_id !== project || !/^\d{4,30}$/.test(String(data.project_info?.project_number ?? '')) || clients.length !== 1
      || !new RegExp(`^1:${data.project_info.project_number}:android:[a-f0-9]+$`,'i').test(clients[0]?.client_info?.mobilesdk_app_id ?? '')
      || !clients[0]?.api_key?.some(k => typeof k.current_key === 'string' && /^[A-Za-z0-9_-]{20,200}$/.test(k.current_key))) throw new Error('BWork push public config does not match the approved Android package/project');
  return { enabled: true, configFile: path.resolve(root, file), project };
}
function patchApplication(source) {
  const marker = '// bwork-notifications-package';
  const line = '          add(com.baseer.bwork.notifications.BWorkNotificationsPackage()) ' + marker;
  if (source.includes(marker)) {
    if (source.split(marker).length !== 2) throw new Error('BWork notifications package duplicated');
    return source.replace(/^.*\/\/ bwork-notifications-package.*$/m, line);
  }
  const anchor = 'PackageList(this).packages.apply {';
  if (!source.includes(anchor)) throw new Error('BWork notifications application template changed');
  return source.replace(anchor, anchor + '\n' + line);
}
function region(source, name, content) {
  const begin = `// ${name}-begin`, end = `// ${name}-end`;
  const block = `${begin}\n${content}\n${end}`;
  if (source.includes(begin)) {
    if (source.split(begin).length !== 2 || !source.includes(end)) throw new Error('BWork push generated boundary changed');
    return source.replace(new RegExp(`// ${name}-begin[\\s\\S]*?// ${name}-end`), block);
  }
  return source + '\n' + block + '\n';
}
function applyNativeBoundary(root, options = pushOptions(), applicationPackage = PACKAGE) {
  if (![identity.qa.applicationId,identity.production.applicationId].includes(applicationPackage)) throw new Error('BWork push package changed');
  // Revalidate enabled configuration at staging time, not just Expo evaluation.
  if (options.enabled) options = pushOptions({BWORK_ANDROID_PUSH_ENABLED:'1', EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE:options.configFile, BWORK_FCM_PROJECT_ID:options.project}, root);
  const base = path.join(root, 'android'), app = path.join(base, 'app');
  const source = path.join(__dirname, 'native/android/com/baseer/bwork/notifications');
  const target = path.join(app, 'src/bworkPush/java/com/baseer/bwork/notifications');
  fs.mkdirSync(target, {recursive:true});
  for (const file of ['PushState.java','PushPolicy.java','PushCallbacks.java','BWorkNotificationsModule.java','BWorkNotificationsPackage.java']) fs.copyFileSync(path.join(source,file),path.join(target,file));
  fs.copyFileSync(path.join(source,options.enabled?'enabled':'disabled','PushBackend.java'),path.join(target,'PushBackend.java'));
  const service = path.join(target,'BWorkMessagingService.java');
  if (options.enabled) fs.copyFileSync(path.join(source,'enabled/BWorkMessagingService.java'),service);
  else if (fs.existsSync(service)) fs.unlinkSync(service); // Exact generated file only; never a directory.
  const main = path.join(app,'src/main/java',applicationPackage.replaceAll('.','/'),'MainApplication.kt');
  fs.writeFileSync(main,patchApplication(fs.readFileSync(main,'utf8')));
  const gradle = path.join(app,'build.gradle');
  const content = "android.sourceSets.main.java.srcDir('src/bworkPush/java')" + (options.enabled ? "\napply plugin: 'com.google.gms.google-services'\ndependencies {\n  implementation platform('com.google.firebase:firebase-bom:34.19.0')\n  implementation 'com.google.firebase:firebase-messaging:25.1.3'\n}" : '');
  fs.writeFileSync(gradle,region(fs.readFileSync(gradle,'utf8'),'bwork-push',content));
  const top = path.join(base,'build.gradle');
  let topSource = fs.readFileSync(top,'utf8');
  topSource = topSource.replace(/^\s*classpath\('com.google.gms:google-services:4\.5\.0'\) \/\/ bwork-push-classpath\r?\n/gm,'');
  if (options.enabled) {
    const anchor = "classpath('com.android.tools.build:gradle')";
    if (!topSource.includes(anchor)) throw new Error('BWork push Gradle template changed');
    topSource = topSource.replace(anchor,anchor+"\n    classpath('com.google.gms:google-services:4.5.0') // bwork-push-classpath");
    fs.copyFileSync(options.configFile,path.join(app,'google-services.json'));
  }
  fs.writeFileSync(top,topSource);
  // The app keeps its normal manifest. Only a marked optional fragment changes.
  const manifest = path.join(app,'src/main/AndroidManifest.xml');
  let xml = fs.readFileSync(manifest,'utf8').replace(/\n?\s*<!-- bwork-push-begin -->[\s\S]*?<!-- bwork-push-end -->/g,'');
  if (options.enabled) {
    const addition = '<meta-data android:name="firebase_messaging_auto_init_enabled" android:value="false"/><meta-data android:name="firebase_analytics_collection_enabled" android:value="false"/><service android:name="com.baseer.bwork.notifications.BWorkMessagingService" android:exported="false"><intent-filter><action android:name="com.google.firebase.MESSAGING_EVENT"/></intent-filter></service>';
    if (!xml.includes('</application>')) throw new Error('BWork push manifest template changed');
    xml = xml.replace('</application>',`<!-- bwork-push-begin -->${addition}<!-- bwork-push-end -->\n</application>`);
  }
  fs.writeFileSync(manifest,xml);
}
module.exports = (config, options) => withDangerousMod(config,['android',async current => {applyNativeBoundary(current.modRequest.projectRoot,options,current.android?.package);return current;}]);
module.exports.pushOptions=pushOptions;
module.exports.applyNativeBoundary=applyNativeBoundary;
module.exports.applyNativePushBoundary=applyNativeBoundary;
module.exports.patchApplication=patchApplication;

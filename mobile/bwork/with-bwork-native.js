const { withSettingsGradle, withMainApplication, withDangerousMod } = require('@expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');
const compatibility = require('./compatibility/identities.json');
const { profile } = require('./bwork-profile.cjs');

// Expo 57's dependency merge retains an existing object for a null platform
// override. Exclude unused SDKs in the native linker command itself so the
// trial cannot silently link upstream telemetry/push or the retired FFmpeg SDK.
const excluded = [
  '@notifee/react-native', 'ffmpeg-kit-react-native',
  '@react-native-firebase/app', '@react-native-firebase/messaging', '@sentry/react-native',
];
const packageName = compatibility.qa.applicationId;
const validPackage = value => [compatibility.qa.applicationId, compatibility.production.applicationId].includes(value);
const marker = '// bwork-native-session-commit';
function checkedOrigin(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) throw new Error('Odoo native session requires a fixed HTTPS origin');
  return parsed.origin;
}
function patchApplication(source, origin) {
  source = source.replace(/\r\n/g, '\n');
  source = source.replaceAll(compatibility.nativeMarkers.session, 'bwork-native-session-commit');
  const registration = `    com.baseer.bwork.session.BaseerSessionNetworking.install(${JSON.stringify(checkedOrigin(origin))}) ${marker}`;
  if ((source.match(/loadReactNative\(this\)/g) || []).length !== 1 || !source.includes('override fun onCreate() {\n    super.onCreate()')) throw new Error('BWork MainApplication template changed');
  if (source.includes(marker)) {
    if ((source.match(/bwork-native-session-commit/g) || []).length !== 1) throw new Error('BWork session registration duplicated');
    source = source.replace(/^.*\/\/ bwork-native-session-commit.*$/m, registration);
  } else source = source.replace('override fun onCreate() {\n    super.onCreate()', `override fun onCreate() {\n    super.onCreate()\n${registration}`);
  if (source.indexOf(marker) > source.indexOf('loadReactNative(this)')) throw new Error('Odoo native session must register before ReactNative');
  return source;
}
function copySources(projectRoot, applicationPackage) {
  // Retire only the known generated adapters; preserve installed QA entrypoints/data.
  const previous = path.join(projectRoot, 'android/app/src/main/java', compatibility.qa.applicationId.replaceAll('.', '/'));
  for (const [folder, files] of Object.entries({
    session: ['CommitCookieHandler.java', 'OriginCookieJar.java', 'BaseerSessionNetworking.java', 'SessionDiagnostics.java'],
    feedback: ['FeedbackController.java', 'BWorkFeedbackModule.java', 'BWorkFeedbackPackage.java', 'PeakEnvelope.java', 'BWorkWaveformModule.java'],
    notifications: ['PushPolicy.java', 'PushState.java', 'PushCallbacks.java', 'BWorkNotificationsModule.java', 'BWorkNotificationsPackage.java', 'PushBackend.java', 'BWorkMessagingService.java'],
  })) for (const file of files) {
    const oldFile = path.join(previous, folder, file);
    if (fs.existsSync(oldFile)) fs.unlinkSync(oldFile);
  }
  if (!validPackage(applicationPackage)) throw new Error('BWork native session package changed');
  const relative = 'com/baseer/bwork/session';
  const destination = path.join(projectRoot, 'android/app/src/main/java', relative);
  fs.mkdirSync(destination, { recursive: true });
  for (const file of ['CommitCookieHandler.java', 'OriginCookieJar.java', 'BaseerSessionNetworking.java', 'SessionDiagnostics.java']) {
    fs.copyFileSync(path.join(__dirname, 'native/android', relative, file), path.join(destination, file));
  }
  const feedback = 'com/baseer/bwork/feedback';
  const target = path.join(projectRoot, 'android/app/src/main/java', feedback);
  fs.mkdirSync(target, { recursive: true });
  for (const file of ['FeedbackController.java', 'BWorkFeedbackModule.java', 'BWorkFeedbackPackage.java', 'PeakEnvelope.java', 'BWorkWaveformModule.java']) {
    const source = fs.readFileSync(path.join(__dirname, 'native/android', feedback, file), 'utf8').replaceAll('__BWORK_MEDIA_DIRECTORY__', compatibility.storage.mediaDirectory);
    fs.writeFileSync(path.join(target, file), source);
  }
}
function patchFeedback(source) {
  const marker = '// bwork-feedback-package';
  const registration = '          add(com.baseer.bwork.feedback.BWorkFeedbackPackage()) ' + marker;
  const anchor = 'PackageList(this).packages.apply {';
  if (!source.includes(anchor)) throw new Error('BWork feedback package template changed');
  if (source.includes(marker)) {
    if (source.split(marker).length !== 2) throw new Error('BWork feedback package duplicated');
    return source.replace(/^.*\/\/ bwork-feedback-package.*$/m, registration);
  }
  return source.replace(anchor, `${anchor}\n${registration}`);
}
function applySigningBoundary(projectRoot, selected) {
  // References only: the build operator supplies release secrets, never a source default.
  // Missing values fail before Gradle can fall back to any debug signing config.
  const file=path.join(projectRoot,'android/app/build.gradle');
  const begin='// bwork-production-signing-begin',end='// bwork-production-signing-end';
  const original=fs.readFileSync(file,'utf8');
  if(selected.name!=='production'){
    const restored=original.replace(new RegExp(`\\n?${begin}[\\s\\S]*?${end}\\n?`),'\n');
    if(restored!==original)fs.writeFileSync(file,restored);
    return;
  }
  const block=`${begin}
def bworkSigningNames=['BWORK_RELEASE_KEYSTORE','BWORK_RELEASE_KEY_ALIAS','BWORK_RELEASE_STORE_PASSWORD','BWORK_RELEASE_KEY_PASSWORD']
if(bworkSigningNames.any { !System.getenv(it) }) throw new GradleException('BWork release signing configuration missing')
if(System.getenv('BWORK_RELEASE_KEY_ALIAS').equalsIgnoreCase('androiddebugkey')) throw new GradleException('BWork debug signing forbidden')
android {
 signingConfigs { bworkProduction {
  storeFile file(System.getenv('BWORK_RELEASE_KEYSTORE'))
  keyAlias System.getenv('BWORK_RELEASE_KEY_ALIAS')
  storePassword System.getenv('BWORK_RELEASE_STORE_PASSWORD')
  keyPassword System.getenv('BWORK_RELEASE_KEY_PASSWORD')
 } }
 buildTypes { release { signingConfig signingConfigs.bworkProduction } }
}
${end}`;
  fs.writeFileSync(file,original.includes(begin)?original.replace(new RegExp(`${begin}[\\s\\S]*?${end}`),block):original+'\n'+block+'\n');
}
// Reuse after a frozen source change without destructive Expo prebuild/clean.
function applyNativeBoundary(projectRoot, applicationPackage, origin) {
  const selected=profile();
  if (!validPackage(applicationPackage) || applicationPackage!==selected.applicationId) throw new Error('BWork native profile/package mismatch');
  const application = path.join(projectRoot, 'android/app/src/main/java', applicationPackage.replaceAll('.','/'),'MainApplication.kt');
  const updated = patchFeedback(patchApplication(fs.readFileSync(application, 'utf8'), origin));
  copySources(projectRoot, applicationPackage);
  fs.writeFileSync(application, updated);
  applySigningBoundary(projectRoot, selected);
}
module.exports = config => {
  config = withSettingsGradle(config, current => {
  current.modResults.contents=current.modResults.contents.replaceAll(compatibility.nativeMarkers.linker,'bwork-native-boundary');
  const original = 'ex.autolinkLibrariesFromCommand(expoAutolinking.rnConfigCommand)';
  const replacement = `ex.autolinkLibrariesFromCommand(expoAutolinking.rnConfigCommand + ${JSON.stringify(['--exclude', ...excluded])}) // bwork-native-boundary`;
  if (!current.modResults.contents.includes('bwork-native-boundary')) {
    if (!current.modResults.contents.includes(original)) throw new Error('BWork native linker template changed');
    current.modResults.contents = current.modResults.contents.replace(original, replacement);
  }
  return current;
  });
  config = withMainApplication(config, current => {
    if (current.modResults.language !== 'kt' || !validPackage(current.android?.package)) throw new Error('BWork MainApplication package/language changed');
    current.modResults.contents = patchFeedback(patchApplication(current.modResults.contents, profile().origin));
    return current;
  });
  return withDangerousMod(config, ['android', async current => {
    const selected=profile();
    if(current.android?.package!==selected.applicationId)throw new Error('BWork profile/package mismatch');
    copySources(current.modRequest.projectRoot, current.android?.package);
    applySigningBoundary(current.modRequest.projectRoot, selected);
    return current;
  }]);
};
module.exports.applyNativeBoundary = applyNativeBoundary;
module.exports.patchApplication = patchApplication;
module.exports.patchFeedback = patchFeedback;
module.exports.applySigningBoundary = applySigningBoundary;

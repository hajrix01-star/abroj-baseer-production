const { withSettingsGradle, withMainApplication, withDangerousMod } = require('@expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');

// Expo 57's dependency merge retains an existing object for a null platform
// override. Exclude unused SDKs in the native linker command itself so the
// trial cannot silently link upstream telemetry/push or the retired FFmpeg SDK.
const excluded = [
  '@notifee/react-native', 'ffmpeg-kit-react-native',
  '@react-native-firebase/app', '@react-native-firebase/messaging', '@sentry/react-native',
];
const packageName = 'com.baseer.bchat.trial';
const marker = '// bchat-native-session-commit';
function checkedOrigin(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) throw new Error('Odoo native session requires a fixed HTTPS origin');
  return parsed.origin;
}
function patchApplication(source, origin) {
  source = source.replace(/\r\n/g, '\n');
  const registration = `    com.baseer.bchat.trial.session.BaseerSessionNetworking.install(${JSON.stringify(checkedOrigin(origin))}) ${marker}`;
  if ((source.match(/loadReactNative\(this\)/g) || []).length !== 1 || !source.includes('override fun onCreate() {\n    super.onCreate()')) throw new Error('Odoo trial MainApplication template changed');
  if (source.includes(marker)) {
    if ((source.match(/bchat-native-session-commit/g) || []).length !== 1) throw new Error('Odoo trial session registration duplicated');
    source = source.replace(/^.*\/\/ bchat-native-session-commit.*$/m, registration);
  } else source = source.replace('override fun onCreate() {\n    super.onCreate()', `override fun onCreate() {\n    super.onCreate()\n${registration}`);
  if (source.indexOf(marker) > source.indexOf('loadReactNative(this)')) throw new Error('Odoo native session must register before ReactNative');
  return source;
}
function copySources(projectRoot, applicationPackage) {
  if (applicationPackage !== packageName) throw new Error('Odoo native session package changed');
  const relative = 'com/baseer/bchat/trial/session';
  const destination = path.join(projectRoot, 'android/app/src/main/java', relative);
  fs.mkdirSync(destination, { recursive: true });
  for (const file of ['CommitCookieHandler.java', 'OriginCookieJar.java', 'BaseerSessionNetworking.java', 'SessionDiagnostics.java']) {
    fs.copyFileSync(path.join(__dirname, 'native/android', relative, file), path.join(destination, file));
  }
  const feedback = 'com/baseer/bchat/trial/feedback';
  const target = path.join(projectRoot, 'android/app/src/main/java', feedback);
  fs.mkdirSync(target, { recursive: true });
  for (const file of ['FeedbackController.java', 'BWorkFeedbackModule.java', 'BWorkFeedbackPackage.java']) {
    fs.copyFileSync(path.join(__dirname, 'native/android', feedback, file), path.join(target, file));
  }
}
function patchFeedback(source) {
  const marker = '// bwork-feedback-package';
  const registration = '          add(com.baseer.bchat.trial.feedback.BWorkFeedbackPackage()) ' + marker;
  const anchor = 'PackageList(this).packages.apply {';
  if (!source.includes(anchor)) throw new Error('BWork feedback package template changed');
  if (source.includes(marker)) {
    if (source.split(marker).length !== 2) throw new Error('BWork feedback package duplicated');
    return source.replace(/^.*\/\/ bwork-feedback-package.*$/m, registration);
  }
  return source.replace(anchor, `${anchor}\n${registration}`);
}
// Reuse after a frozen source change without destructive Expo prebuild/clean.
function applyNativeBoundary(projectRoot, applicationPackage, origin) {
  if (applicationPackage !== packageName) throw new Error('Odoo native session package changed');
  const application = path.join(projectRoot, 'android/app/src/main/java/com/baseer/bchat/trial/MainApplication.kt');
  const updated = patchFeedback(patchApplication(fs.readFileSync(application, 'utf8'), origin));
  copySources(projectRoot, applicationPackage);
  fs.writeFileSync(application, updated);
}
module.exports = config => {
  config = withSettingsGradle(config, current => {
  const original = 'ex.autolinkLibrariesFromCommand(expoAutolinking.rnConfigCommand)';
  const replacement = `ex.autolinkLibrariesFromCommand(expoAutolinking.rnConfigCommand + ${JSON.stringify(['--exclude', ...excluded])}) // bchat-odoo-native-boundary`;
  if (!current.modResults.contents.includes('bchat-odoo-native-boundary')) {
    if (!current.modResults.contents.includes(original)) throw new Error('Odoo trial native linker template changed');
    current.modResults.contents = current.modResults.contents.replace(original, replacement);
  }
  return current;
  });
  config = withMainApplication(config, current => {
    if (current.modResults.language !== 'kt' || current.android?.package !== packageName) throw new Error('Odoo trial MainApplication package/language changed');
    current.modResults.contents = patchFeedback(patchApplication(current.modResults.contents, process.env.EXPO_PUBLIC_ODOO_ORIGIN));
    return current;
  });
  return withDangerousMod(config, ['android', async current => {
    copySources(current.modRequest.projectRoot, current.android?.package);
    return current;
  }]);
};
module.exports.applyNativeBoundary = applyNativeBoundary;
module.exports.patchApplication = patchApplication;
module.exports.patchFeedback = patchFeedback;

// No downloads/Gradle/JUnit. Compile against the installed Android/RN/OkHttp artifacts.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const cache = process.env.GRADLE_USER_HOME || path.join(os.homedir(), '.gradle');
const resolved = fs.readFileSync(path.join(__dirname, '../../android/app/build/intermediates/lint_vital_report_lint_model/release/generateReleaseLintVitalReportModel/release-artifact-dependencies.xml'), 'utf8');
// Captured by the existing successful release build, not a version selected from cache order.
for (const dependency of ['com.facebook.react:react-android:0.86.0', 'com.squareup.okhttp3:okhttp:4.12.0', 'com.squareup.okhttp3:okhttp-urlconnection:4.9.2', 'com.squareup.okio:okio-jvm:3.16.0', 'org.jetbrains.kotlin:kotlin-stdlib:2.2.20']) {
  if (!resolved.includes(`name="${dependency}`)) throw new Error('Resolved Android dependency changed: ' + dependency);
}
function artifact(group, name, version, extension) {
  const root = path.join(cache, 'caches/modules-2/files-2.1', group, name, version);
  for (const hash of fs.readdirSync(root)) {
    for (const file of fs.readdirSync(path.join(root, hash))) if (file.endsWith(extension)) return path.join(root, hash, file);
  }
  throw new Error('Installed dependency artifact missing: ' + name);
}
const jdk = process.env.JAVA_HOME || 'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
const android = process.env.ANDROID_HOME || 'D:/Codex/AndroidSdk';
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'bchat-native-cookie-'));
const bin = name => path.join(jdk, 'bin', name + (process.platform === 'win32' ? '.exe' : ''));
const react = artifact('com.facebook.react', 'react-android', '0.86.0', '.aar');
execFileSync(bin('jar'), ['xf', react, 'classes.jar'], { cwd: temp, stdio: 'inherit' });
const cp = [path.join(temp, 'classes.jar'), path.join(android, 'platforms/android-36/android.jar'),
  artifact('com.squareup.okhttp3', 'okhttp', '4.12.0', '.jar'),
  artifact('com.squareup.okhttp3', 'okhttp-urlconnection', '4.9.2', '.jar'),
  artifact('com.squareup.okio', 'okio-jvm', '3.16.0', '.jar'),
  artifact('org.jetbrains.kotlin', 'kotlin-stdlib', '2.2.20', '.jar')].join(path.delimiter);
const source = path.join(__dirname, '../android/com/baseer/bchat/trial/session');
execFileSync(bin('javac'), ['-encoding', 'UTF-8', '-cp', cp, '-d', temp,
  ...['CommitCookieHandler.java', 'OriginCookieJar.java', 'BaseerSessionNetworking.java', 'SessionDiagnostics.java'].map(file => path.join(source, file)),
  path.join(__dirname, 'SessionCookieHarness.java'), path.join(__dirname, 'SessionDiagnosticsHarness.java')], { stdio: 'inherit' });
execFileSync(bin('java'), ['-ea', '-cp', temp + path.delimiter + cp, 'com.baseer.bchat.trial.session.SessionCookieHarness'], { stdio: 'inherit' });
execFileSync(bin('java'), ['-ea', '-cp', temp + path.delimiter + cp, 'com.baseer.bchat.trial.session.SessionDiagnosticsHarness'], { stdio: 'inherit' });
console.log('Compiled production Android adapter with installed RN and android-36 classes. Temporary classes: ' + temp);

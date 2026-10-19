const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
test('actual feedback controller passes JVM policy/resource seams and bridge binds Android lifecycle/system gates', () => {
  const jdk = process.env.JAVA_HOME || 'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
  const bin = name => path.join(jdk, 'bin', name + (process.platform === 'win32' ? '.exe' : ''));
  const source = path.join(__dirname, '../android/com/baseer/bchat/trial/feedback');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'bwork-feedback-'));
  execFileSync(bin('javac'), ['-encoding', 'UTF-8', '-d', temp, path.join(source, 'FeedbackController.java'), path.join(__dirname, 'FeedbackHarness.java')]);
  const result = execFileSync(bin('java'), ['-ea', '-cp', temp, 'com.baseer.bchat.trial.feedback.FeedbackHarness'], { encoding: 'utf8' });
  assert.match(result, /PASS/);
  const bridge = fs.readFileSync(path.join(source, 'BWorkFeedbackModule.java'), 'utf8');
  for (const gate of ['STREAM_NOTIFICATION', 'RINGER_MODE_NORMAL', 'getStreamVolume', 'INTERRUPTION_FILTER_ALL', 'LifecycleState.RESUMED', 'onHostPause', 'onHostDestroy', 'tone.release()', 'stopIfRevision']) assert.ok(bridge.includes(gate), gate);
  assert.doesNotMatch(bridge, /requestAudioFocus|setStreamVolume|setRingerMode|ACCESS_NOTIFICATION_POLICY|Firebase/);
});
test('production feedback module/package compile against installed RN0.86 and Android36, not Java mocks', () => {
  const jdk = process.env.JAVA_HOME || 'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
  const bin = name => path.join(jdk, 'bin', name + (process.platform === 'win32' ? '.exe' : ''));
  const cache = process.env.GRADLE_USER_HOME || path.join(os.homedir(), '.gradle');
  const root = path.join(cache, 'caches/modules-2/files-2.1/com.facebook.react/react-android/0.86.0');
  const aar = fs.readdirSync(root).flatMap(hash => fs.readdirSync(path.join(root, hash)).filter(file => file.endsWith('.aar')).map(file => path.join(root, hash, file)))[0];
  assert.ok(aar, 'installed RN artifact exists');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'bwork-feedback-android-'));
  execFileSync(bin('jar'), ['xf', aar, 'classes.jar'], { cwd: temp });
  const source = path.join(__dirname, '../android/com/baseer/bchat/trial/feedback');
  const cp = [path.join(temp, 'classes.jar'), path.join(process.env.ANDROID_HOME || 'D:/Codex/AndroidSdk', 'platforms/android-36/android.jar')].join(path.delimiter);
  execFileSync(bin('javac'), ['-encoding', 'UTF-8', '-cp', cp, '-d', temp,
    ...['FeedbackController.java', 'BWorkFeedbackModule.java', 'BWorkFeedbackPackage.java', 'PeakEnvelope.java', 'BWorkWaveformModule.java'].map(file => path.join(source, file))]);
  assert.ok(fs.existsSync(path.join(temp, 'com/baseer/bchat/trial/feedback/BWorkFeedbackModule.class')));
});

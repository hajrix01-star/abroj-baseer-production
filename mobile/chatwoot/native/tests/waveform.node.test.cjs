const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
test('real PCM envelope has bounded truthful time bins and rejects unsupported/partial inputs', () => {
  const jdk = process.env.JAVA_HOME || 'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
  const bin = name => path.join(jdk, 'bin', name + (process.platform === 'win32' ? '.exe' : ''));
  const source = path.join(__dirname, '../android/com/baseer/bchat/trial/feedback');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'bwork-waveform-'));
  execFileSync(bin('javac'), ['-encoding', 'UTF-8', '-d', temp, path.join(source, 'PeakEnvelope.java'), path.join(__dirname, 'PeakEnvelopeHarness.java')]);
  assert.match(execFileSync(bin('java'), ['-ea', '-cp', temp, 'com.baseer.bchat.trial.feedback.PeakEnvelopeHarness'], { encoding: 'utf8' }), /PASS/);
  const bridge = fs.readFileSync(path.join(source, 'BWorkWaveformModule.java'), 'utf8');
  for (const guard of ['getCanonicalFile()', 'file.length() > 10 * 1024 * 1024', 'new ArrayBlockingQueue<>(2)', 'SystemClock.elapsedRealtime() + 15000', 'cancelled.get()', 'codec.release()', 'extractor.release()', 'onHostPause()', 'getLifecycleState() != LifecycleState.RESUMED']) assert.ok(bridge.includes(guard), guard);
  assert.doesNotMatch(bridge, /https?:|FFmpeg|setDataSource\(uri\)/);
});

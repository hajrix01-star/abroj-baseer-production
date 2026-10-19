/** Build boundary contracts, not an APK/device test. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('default Odoo entry never evaluates upstream telemetry/Redux root', () => {
  const source = readFileSync(new URL('../../../App.tsx', import.meta.url), 'utf8').replace('export default Entry;', 'module.exports = Entry;');
  const required: string[] = [];
  const module = { exports: null };
  vm.runInNewContext(source, { module, process: { env: {} }, require: (path: string) => { required.push(path); return { default: 'odoo-entry' }; } });
  assert.deepEqual(required, ['./src/odoo/OdooTrialApp']);
  assert.equal(module.exports, 'odoo-entry');
});
test('trial native linker explicitly excludes unused push/telemetry/FFmpeg and fails on template drift', () => {
  const source = readFileSync(new URL('../../../with-odoo-trial-native.js', import.meta.url), 'utf8');
  const module: { exports: any } = { exports: null };
  vm.runInNewContext(source, { module, require: () => ({
    withSettingsGradle: (config: unknown, callback: (value: unknown) => unknown) => callback(config),
    withMainApplication: (config: unknown) => config, withDangerousMod: (config: unknown) => config,
  }) });
  const before = 'ex.autolinkLibrariesFromCommand(expoAutolinking.rnConfigCommand)';
  const result = module.exports({ modResults: { contents: before } });
  for (const packageName of ['@notifee/react-native', 'ffmpeg-kit-react-native', '@react-native-firebase/app', '@react-native-firebase/messaging', '@sentry/react-native']) assert.ok(result.modResults.contents.includes(`"${packageName}"`));
  assert.ok(result.modResults.contents.includes('"--exclude"'));
  assert.equal(module.exports(result).modResults.contents, result.modResults.contents);
  assert.throws(() => module.exports({ modResults: { contents: 'unknown native template' } }), /template changed/);
});

/** Exercise the actual hook teardown with native seams, not an Android visual/device test. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

function harness() {
  const slots = [];
  let index = 0;
  let effect;
  const player = { active: false, starts: 0, recorderStops: 0, playerStops: 0,
    async startRecorder(path) { this.active = true; this.starts++; return path; },
    async stopRecorder() { this.active = false; this.recorderStops++; return '/synthetic.m4a'; },
    async stopPlayer() { this.playerStops++; },
    removeRecordBackListener() {}, removePlayBackListener() {}, addRecordBackListener() {},
  };
  const react = {
    useRef(value) { const at = index++; return slots[at] ?? (slots[at] = { current: value }); },
    useState(value) { const at = index++; if (!(at in slots)) slots[at] = typeof value === 'function' ? value() : value; return [slots[at], next => { slots[at] = next; }]; },
    useEffect(callback, deps) {
      if (!effect || deps.some((value, at) => value !== effect.deps[at])) {
        effect?.cleanup?.(); effect = { deps, cleanup: callback() };
      }
    },
  };
  const native = { AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) }, Platform: { OS: 'ios' } };
  const recorder = { __esModule: true, default: class { constructor() { return player; } },
    AudioSourceAndroidType: { MIC: 1 }, OutputFormatAndroidType: { MPEG_4: 2 }, AudioEncoderAndroidType: { AAC: 3 }, AVEncodingOption: { aac: 'aac' } };
  const modules = {
    react,
    'react-native': native,
    'react-native-audio-recorder-player': recorder,
    'react-native-blob-util': { fs: { dirs: { CacheDir: '/synthetic' }, unlink: async () => undefined } },
    './dictionary': { errorWord: () => 'error' },
  };
  const source = readFileSync(join(__dirname, 'MediaTools.tsx'), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const mod = { exports: {} };
  const context = { module: mod, exports: mod.exports, require: name => modules[name] ?? {}, console };
  vm.runInNewContext(compiled, context, { filename: 'MediaTools.transpiled.cjs' });
  return {
    player,
    render(canPlay, canRecord) { index = 0; return mod.exports.useVoiceSession('same-company-room-membership', () => undefined, canPlay, canRecord); },
    close() { effect?.cleanup?.(); },
  };
}
async function settled() { for (let i = 0; i < 8; i++) await Promise.resolve(); }

test('DM-off tears down an active recorder even when room scope and media viewing remain unchanged', async () => {
  const app = harness();
  await app.render(true, true).start();
  assert.equal(app.player.active, true);
  const stops = app.player.recorderStops;
  const revoked = app.render(true, false);
  await settled();
  assert.equal(app.player.active, false);
  assert.ok(app.player.recorderStops > stops);
  await revoked.start();
  assert.equal(app.player.starts, 1);
  app.close();
});

test('media-right withdrawal tears down native playback and recording with unchanged scope', async () => {
  const app = harness();
  await app.render(true, true).start();
  const stops = app.player.playerStops;
  app.render(false, false);
  await settled();
  assert.equal(app.player.active, false);
  assert.ok(app.player.playerStops > stops);
  app.close();
});

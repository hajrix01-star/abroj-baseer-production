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
  let background;
  const unlinked = [];
  const staged = [];
  const feedback = [];
  const playback = [];
  let listener;
  let stateWrites = 0;
  const player = { active: false, starts: 0, recorderStops: 0, playerStops: 0,
    async startRecorder(path) { this.active = true; this.starts++; return path; },
    async stopRecorder() { this.active = false; this.recorderStops++; return '/synthetic.m4a'; },
    async stopPlayer() { this.playerStops++; },
    async startPlayer(uri) { playback.push(['play', uri]); },
    async pausePlayer() { playback.push(['pause']); },
    async resumePlayer() { playback.push(['resume']); },
    async seekToPlayer(at) { playback.push(['seek', at]); },
    addPlayBackListener(callback) { listener = callback; },
    removeRecordBackListener() {}, removePlayBackListener() {}, addRecordBackListener() {},
  };
  const react = {
    useRef(value) { const at = index++; return slots[at] ?? (slots[at] = { current: value }); },
    useState(value) { const at = index++; if (!(at in slots)) slots[at] = typeof value === 'function' ? value() : value; return [slots[at], next => { stateWrites++; slots[at] = next; }]; },
    useEffect(callback, deps) {
      if (!effect || deps.some((value, at) => value !== effect.deps[at])) {
        effect?.cleanup?.(); effect = { deps, cleanup: callback() };
      }
    },
  };
  const native = { AppState: { currentState: 'active', addEventListener: (_event, callback) => { background = callback; return { remove() {} }; } }, Platform: { OS: 'ios' } };
  const recorder = { __esModule: true, default: class { constructor() { return player; } },
    AudioSourceAndroidType: { MIC: 1 }, OutputFormatAndroidType: { MPEG_4: 2 }, AudioEncoderAndroidType: { AAC: 3 }, AVEncodingOption: { aac: 'aac' } };
  const modules = {
    react,
    'react-native': native,
    'react-native-audio-recorder-player': recorder,
    'react-native-blob-util': { fs: { dirs: { CacheDir: '/synthetic' }, unlink: async path => { unlinked.push(path); } } },
    '../runtime': { stageFile: async (room, file) => { staged.push({ room, file }); return { uri: 'file:///owned-stage/voice.m4a', name: 'voice.m4a', kind: 'audio' }; } },
    './dictionary': { errorWord: () => 'error' },
    './messageSounds': { setFeedbackVoice: (_owner, active) => feedback.push(active) },
  };
  const source = readFileSync(join(__dirname, 'MediaTools.tsx'), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const mod = { exports: {} };
  const context = { module: mod, exports: mod.exports, require: name => modules[name] ?? {}, console };
  vm.runInNewContext(compiled, context, { filename: 'MediaTools.transpiled.cjs' });
  return {
    player,
    unlinked,
    staged,
    feedback,
    playback,
    get stateWrites() { return stateWrites; },
    tick(position, duration) { listener?.({ currentPosition: position, duration }); },
    render(canPlay, canRecord, scope = 'same-company-room-membership') { index = 0; return mod.exports.useVoiceSession(scope, () => undefined, canPlay, canRecord); },
    background() { native.AppState.currentState = 'background'; background('background'); },
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

test('background and scope change stop recording before it can be sent', async () => {
  const app = harness();
  await app.render(true, true).start();
  app.background(); await settled();
  assert.equal(app.player.active, false);
  assert.equal(app.staged.length, 0);
  assert.ok(app.unlinked.every(path => path.startsWith('/synthetic/odoo-voice-')));
  app.close();
  const scoped = harness();
  await scoped.render(true, true).start();
  scoped.render(true, true, 'another-company-room-membership'); await settled();
  assert.equal(scoped.player.active, false);
  assert.equal(scoped.staged.length, 0);
  scoped.close();
});

test('finish stages once and cleanup deletes recorder temporary bytes, never the staged attachment', async () => {
  const app = harness();
  await app.render(true, true).start();
  const room = { id: 4, company_id: 1, membership_id: 9 };
  const attachment = await app.render(true, true).finish(room);
  assert.equal(attachment.uri, 'file:///owned-stage/voice.m4a');
  assert.equal(app.staged.length, 1);
  assert.equal(app.staged[0].room, room);
  assert.ok(app.unlinked.length > 0);
  assert.ok(app.unlinked.every(path => path.startsWith('/synthetic/odoo-voice-')));
  app.close(); await settled();
  assert.equal(app.unlinked.includes('/owned-stage/voice.m4a'), false);
});
test('voice acquisition suppresses feedback before native recording and releases it only after cleanup', async () => {
  const app = harness(); const session = app.render(true, true);
  const start = session.start(); assert.equal(app.feedback.at(-1), true);
  await start; assert.equal(app.feedback.at(-1), true);
  await app.render(true, true).stop(); assert.equal(app.feedback.at(-1), false);
  app.close(); await settled(); assert.equal(app.feedback.at(-1), false);
});

test('one voice session pauses, resumes and clamps seeking without releasing its pin until stopped or replaced', async () => {
  const app = harness(); let released = 0;
  await app.render(true, true).play('file:///owned/one.m4a', () => released++);
  app.tick(1000, 10000);
  let voice = app.render(true, true); assert.equal(voice.activeUri, 'file:///owned/one.m4a'); assert.equal(voice.playing, true);
  assert.equal(voice.positionMs, 1000); assert.equal(voice.durationMs, 10000);
  await voice.pause(); voice = app.render(true, true); assert.equal(voice.paused, true); assert.equal(voice.playing, false); assert.equal(released, 0);
  await voice.seek(50000); assert.deepEqual(app.playback.at(-1), ['seek', 10000]);
  await voice.seek(-200); assert.deepEqual(app.playback.at(-1), ['seek', 0]);
  await voice.resume(); assert.equal(app.render(true, true).playing, true); assert.equal(released, 0);
  await voice.play('file:///owned/two.m4a', () => released++); assert.equal(released, 1);
  assert.equal(app.render(true, true).activeUri, 'file:///owned/two.m4a');
  app.background(); await settled(); assert.equal(released, 2); assert.equal(app.render(true, true).activeUri, null);
  app.close();
});

test('native progress uses stable active-row subscriptions without rerendering the timeline hook', async () => {
  const app = harness(); await app.render(true, true).play('file:///one.m4a');
  const voice = app.render(true, true), observed = [];
  const unsubscribe = voice.progress.subscribe(() => observed.push(voice.progress.snapshot().positionMs));
  const before = app.stateWrites;
  for (let n = 1; n <= 30; n++) app.tick(n * 100, 10000);
  assert.equal(app.stateWrites, before, 'no Timeline hook setState from 30 native clock ticks');
  assert.equal(voice.progress, app.render(true, true).progress); assert.equal(observed.length, 30); assert.equal(observed.at(-1), 3000);
  unsubscribe(); app.tick(4000, 10000); assert.equal(observed.length, 30);
  await voice.stop(); app.close();
});

test('concurrent playback intentions keep only the newest recording and release superseded leases once', async () => {
  const app = harness(); const released = [];
  const voice = app.render(true, true);
  await Promise.all([voice.play('one', () => released.push('one')), voice.play('two', () => released.push('two'))]);
  assert.deepEqual(app.playback.filter(row => row[0] === 'play'), [['play', 'two']]);
  assert.deepEqual(released, ['one']);
  app.render(false, false); await settled(); assert.deepEqual(released, ['one', 'two']); app.close();
});

test('process-wide voice owner serializes delayed old-room start and cleanup across two keyed hook mounts', async () => {
  const instances = new Map(); let active, index = 0, releaseStart; const events = []; const released = [];
  const nativePlayer = { uri: null,
    async startPlayer(uri) { events.push(['start', uri]); this.uri = uri; if (uri === 'old') await new Promise(resolve => { releaseStart = resolve; }); },
    async stopPlayer() { events.push(['stop', this.uri]); this.uri = null; }, async stopRecorder() {},
    removeRecordBackListener() {}, removePlayBackListener() {}, addPlayBackListener() {},
  };
  const react = {
    useRef(value) { const at = index++; return active.slots[at] ?? (active.slots[at] = { current: value }); },
    useState(value) { const owner = active, at = index++; if (!(at in owner.slots)) owner.slots[at] = typeof value === 'function' ? value() : value; return [owner.slots[at], next => { owner.slots[at] = next; }]; },
    useEffect(fn, deps) { const owner = active; if (!owner.effect || deps.some((value, at) => value !== owner.effect.deps[at])) { owner.effect?.cleanup?.(); owner.effect = { deps, cleanup: fn() }; } },
  };
  const modules = { react, 'react-native': { AppState: { currentState: 'active', addEventListener() { return { remove() {} }; } }, Platform: { OS: 'ios' } },
    'react-native-audio-recorder-player': { __esModule: true, default: class { constructor() { return nativePlayer; } } },
    'react-native-blob-util': { fs: { dirs: { CacheDir: '/synthetic' }, async unlink() {} } }, './messageSounds': { setFeedbackVoice() {} } };
  const mod = { exports: {} };
  vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, 'MediaTools.tsx'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText,
    { module: mod, exports: mod.exports, require: name => modules[name] ?? {}, console });
  const render = id => { if (!instances.has(id)) instances.set(id, { slots: [] }); active = instances.get(id); index = 0; return mod.exports.useVoiceSession(id, () => {}, true, true); };
  const a = render('old-room'); const oldPlay = a.play('old', () => released.push('old'));
  await settled(); assert.equal(typeof releaseStart, 'function');
  instances.get('old-room').effect.cleanup();
  const b = render('new-room'); const newPlay = b.play('new', () => released.push('new'));
  await settled(); assert.deepEqual(events.filter(row => row[0] === 'start'), [['start', 'old']], 'no second native start overtakes the old pending command');
  releaseStart(); await Promise.all([oldPlay, newPlay]); await settled();
  assert.equal(nativePlayer.uri, 'new'); assert.deepEqual(released, ['old']);
  await a.stop(); assert.equal(nativePlayer.uri, 'new', 'late cleanup from old room cannot stop current owner');
  assert.deepEqual(released, ['old']); await b.stop(); assert.equal(nativePlayer.uri, null); assert.deepEqual(released, ['old', 'new']);
});

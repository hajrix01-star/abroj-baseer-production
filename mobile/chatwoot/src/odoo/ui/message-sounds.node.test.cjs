/** Actual policy/storage/native adapter through deterministic seams, not audible device proof. */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function load() {
  const plays = [], stops = []; const native = { AppState: { currentState: 'active' }, NativeModules: {
    BWorkFeedback: { play: async kind => { plays.push(kind); return true; }, stop: () => stops.push(true) } } };
  const mod = { exports: {} };
  const compiled = ts.transpileModule(readFileSync(join(__dirname, 'messageSounds.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  vm.runInNewContext(compiled, { module: mod, exports: mod.exports, require: name => ({ 'react-native': native,
    '@react-native-async-storage/async-storage': { getItem: async () => null, setItem: async () => undefined }, '../runtime': { config: { origin: 'https://synthetic.invalid' } } })[name] ?? {} });
  return { ...mod.exports, native, plays, stops };
}
async function settle() { for (let n = 0; n < 12; n++) await Promise.resolve(); }
const message = (id, author_user_id = 9) => ({ id, author_user_id });
test('startup/select/history/catchup/self/receipt/prepend are silent; one new remote batch sounds once and advances while muted', async () => {
  const lib = load(), played = [], states = [];
  const sounds = new lib.MessageSounds({ load: async () => null, save: async () => undefined, play: kind => played.push(kind), stop() {} }, value => states.push(value));
  sounds.account('actor1'); sounds.observe('room1', [message(1)], 7, true); assert.equal(played.length, 0);
  await settle(); sounds.observe('room1', [message(1), message(2, 7)], 7);
  sounds.observe('room1', [message(1), message(2, 7)], 7); sounds.observe('room1', [message(0), message(1), message(2, 7)], 7);
  assert.equal(played.length, 0);
  sounds.observe('room1', [message(1), message(2, 7), message(3), message(4)], 7);
  assert.deepEqual(played, ['receive']);
  sounds.observe('room1', [message(3), message(4)], 7); assert.equal(played.length, 1);
  sounds.enabled(false); sounds.observe('room1', [message(5)], 7); sounds.enabled(true);
  sounds.observe('room1', [message(5)], 7); assert.equal(played.length, 1);
  sounds.reset(); sounds.observe('room1', [message(6)], 7); assert.equal(played.length, 1);
  sounds.observe('room2', [message(99)], 7); assert.equal(played.length, 1);
  sounds.sent('room1'); assert.equal(played.length, 1); sounds.sent('room2'); assert.equal(played.at(-1), 'send');
});
test('preference reads/saves are actor-scoped, loaded before play, fenced on switch and serialized', async () => {
  const lib = load(); const reads = []; const writes = []; const played = []; let release;
  const sounds = new lib.MessageSounds({ load: key => new Promise(resolve => reads.push({ key, resolve })),
    save: (key, value) => { writes.push([key, value]); return new Promise(resolve => { release = resolve; }); }, play: kind => played.push(kind), stop() {} }, () => {});
  sounds.account('a'); sounds.observe('r', [message(1)], 7); sounds.sent('r'); assert.equal(played.length, 0);
  sounds.account('b'); reads[0].resolve('1'); await settle(); assert.equal(sounds.snapshot().ready, false);
  reads[1].resolve('0'); await settle(); assert.equal(sounds.snapshot().enabled, false);
  sounds.enabled(true); await settle(); assert.ok(writes[0][0].endsWith('/b'));
  sounds.enabled(false); sounds.account('c'); release(); await settle(); assert.equal(writes.length, 1, 'queued stale save is skipped');
  reads[2].resolve('1'); await settle(); sounds.observe('rc', [message(8)], 7, true); sounds.sent('rc'); assert.deepEqual(played, ['send']);
  sounds.close(); assert.equal(sounds.snapshot().ready, false);
});
test('native adapter suppresses tones during voice/background and does not replay suppressed incoming items later', async () => {
  const lib = load(); const sounds = lib.createMessageSounds(() => {});
  sounds.account('a'); await settle(); sounds.observe('r', [message(1)], 7, true);
  const owner = {}; lib.setFeedbackVoice(owner, true); sounds.observe('r', [message(2)], 7); sounds.sent('r'); assert.equal(lib.plays.length, 0);
  lib.setFeedbackVoice(owner, false); sounds.observe('r', [message(2)], 7); assert.equal(lib.plays.length, 0);
  sounds.observe('r', [message(3)], 7); assert.deepEqual(lib.plays, ['receive']);
  lib.native.AppState.currentState = 'background'; sounds.sent('r'); assert.equal(lib.plays.length, 1);
  assert.ok(lib.stops.length > 0);
});

/** Real VoiceBubble component under native seams; not physical speaker/layout proof. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const slots = () => {
  let at = 0, effects = [], cells = [], writes = 0;
  return { react: {
    useRef(value) { const n = at++; return cells[n] ?? (cells[n] = { current: value }); },
    useState(value) { const n = at++; if (!(n in cells)) cells[n] = value; return [cells[n], next => { writes++; cells[n] = typeof next === 'function' ? next(cells[n]) : next; }]; },
    useEffect(fn, deps) { const n = at++; if (!cells[n] || deps.some((v, i) => v !== cells[n].deps[i])) effects.push(() => { cells[n]?.cleanup?.(); cells[n] = { deps, cleanup: fn() }; }); },
  }, render(fn) { at = 0; effects = []; const tree = fn(); effects.forEach(fn => fn()); return tree; }, close() { cells.forEach(cell => cell?.cleanup?.()); }, get writes() { return writes; } };
};
const nodes = tree => Array.isArray(tree) ? tree.flatMap(nodes) : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];
function one(tree, type, filter = () => true) { const found = nodes(tree).filter(item => item.type === type && filter(item.props)); assert.equal(found.length, 1); return found[0].props; }
async function settled() { for (let i = 0; i < 24; i++) await Promise.resolve(); }
function harness() {
  const state = slots(), calls = [], listeners = new Set(); let cached = false, result, finish;
  const native = { View: 'View', Image: 'Image', Text: 'Text', AppState: { currentState: 'active', addEventListener(_, fn) { listeners.add(fn); return { remove() { listeners.delete(fn); } }; } },
    NativeModules: { BWorkWaveform: { async analyze(uri, id) { calls.push(['analyze', uri, id]); return result ?? new Promise(resolve => { finish = resolve; }); }, cancel(id) { calls.push(['cancel', id]); } } } };
  const props = { room: { id: 1, company_id: 2, membership_id: 3 }, media: { id: 4, sha256: 'a', size: 10 }, scopeKey: 'actor', visible: true, language: 'ar', t: word => word, senderName: 'Ahmed', senderUserId: 7, report: word => calls.push(['error', word]),
    voice: { activeUri: null, playing: false, paused: false, positionMs: 0, durationMs: 0, async play(uri, release) { calls.push(['play', uri]); props.voice.activeUri = uri; props.voice.playing = true; props.voice.release = release; }, async pause() { calls.push(['pause']); }, async resume() { calls.push(['resume']); }, async seek(at) { calls.push(['seek', at]); } } };
  const element = (type, props) => ({ type, props });
  const modules = { react: state.react, 'react/jsx-runtime': { jsx: element, jsxs: element, Fragment: 'Fragment' }, 'react-native': native,
    './components': { Icon: 'Icon', IconButton: 'IconButton', colors: { blue: '#1256da', muted: '#54697b', border: '#dce5ec', pale: '#edf2fc', chatSent: '#dff0ff' } }, './dictionary': { errorWord: () => 'error' },
    '../runtime': { async localMediaLease(room, media, variant, cachedOnly) { calls.push(['lease', room.id, media.id, variant, cachedOnly]); if (cachedOnly && !cached) throw Error('not_cached'); return { uri: `file:///owned/${media.id}.m4a`, release() { calls.push(['release', media.id]); } }; }, clearMemberAvatars() {}, async readMemberAvatar(room, id) { calls.push(['avatar', room.id, id]); return 'data:image/png;base64,synthetic'; } } };
  const mod = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(__dirname + '/VoiceBubble.tsx', 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText,
    { module: mod, exports: mod.exports, require: name => modules[name] ?? {}, Date, console });
  return { props, calls, mod: mod.exports, render: () => state.render(() => mod.exports.VoiceBubble(props)), close: () => state.close(), get writes() { return state.writes; }, cache(value = true) { cached = value; }, envelope(value) { result = value; }, finish(value) { finish(value); }, background() { native.AppState.currentState = 'background'; listeners.forEach(fn => fn('background')); } };
}
const envelope = { durationMs: 10000, peaks: Array.from({ length: 40 }, (_, n) => n / 40) };
test('voice bubble uses cache-only visible resolution, honest unknown rail, protected sender and bilingual compact controls', async () => {
  const app = harness(); app.render(); await settled();
  assert.deepEqual(app.calls.filter(row => row[0] === 'lease').map(row => row[4]), [true]);
  assert.equal(app.calls.some(row => row[0] === 'analyze'), false);
  let tree = app.render(); assert.equal(one(tree, 'IconButton').icon, 'play'); assert.equal(one(tree, 'Image').source.uri, 'data:image/png;base64,synthetic');
  assert.equal(nodes(tree).filter(row => row.type === 'Text').some(row => row.props.children === '—:—'), true);
  for (const language of ['ar', 'en']) { app.props.language = language; tree = app.render(); assert.equal(tree.props.style.width, 240); assert.equal(tree.props.style.maxWidth, '100%'); assert.equal(tree.props.style.flexDirection, language === 'ar' ? 'row-reverse' : 'row'); assert.equal(one(tree, 'IconButton').style.width, 44); }
  app.close();
});
test('cached voice displays only real native peaks, seeks by drag/accessibility and pauses/resumes only its own URI', async () => {
  const app = harness(); app.cache(); app.envelope(envelope); app.render(); await settled();
  let tree = app.render(); assert.equal(nodes(tree).filter(row => row.type === 'View' && row.props.style?.height === 28 * Math.sqrt(0.5)).length, 1);
  one(tree, 'IconButton').onPress(); await settled();
  app.props.voice.durationMs = 10000; app.props.voice.positionMs = 2500;
  tree = app.render(); assert.equal(one(tree, 'IconButton').icon, 'pause');
  const seek = one(tree, 'View', props => props.accessibilityRole === 'adjustable');
  seek.onLayout({ nativeEvent: { layout: { width: 100 } } }); seek.onResponderGrant({ nativeEvent: { locationX: 20 } }); seek.onResponderRelease({ nativeEvent: { locationX: 80 } });
  assert.deepEqual(app.calls.at(-1), ['seek', 8000]);
  seek.onAccessibilityAction({ nativeEvent: { actionName: 'increment' } }); assert.deepEqual(app.calls.at(-1), ['seek', 7500]);
  one(tree, 'IconButton').onPress(); await settled(); assert.deepEqual(app.calls.at(-1), ['pause']);
  app.props.voice.playing = false; app.props.voice.paused = true; one(app.render(), 'IconButton').onPress(); await settled(); assert.deepEqual(app.calls.at(-1), ['resume']);
  app.props.voice.activeUri = 'file:///another.m4a'; assert.equal(one(app.render(), 'IconButton').icon, 'play'); app.close(); app.props.voice.release();
});
test('background/recycling cancel analysis, ignore late peaks, and release the analysis lease', async () => {
  const app = harness(); app.cache(); app.render(); await settled(); assert.equal(app.calls.some(row => row[0] === 'analyze'), true);
  app.background(); app.render(); app.finish(envelope); await settled();
  assert.equal(app.calls.some(row => row[0] === 'cancel'), true); assert.equal(app.calls.some(row => row[0] === 'release'), true);
  assert.equal(nodes(app.render()).some(row => row.type === 'Image'), false);
  app.close();
});
test('active audio scrub keeps responder ownership against ancestor reply capture; inactive and invalidated rows yield', async () => {
  const app = harness(); app.cache(); app.envelope(envelope); app.render(); await settled();
  app.props.voice.activeUri = 'file:///owned/4.m4a'; app.props.voice.durationMs = 10000;
  let rail = one(app.render(), 'View', props => props.accessibilityRole === 'adjustable');
  rail.onLayout({ nativeEvent: { layout: { width: 100 } } });
  assert.equal(rail.onStartShouldSetResponder(), true);
  assert.equal(rail.onResponderTerminationRequest(), true, 'no scrub owns a gesture before grant');
  rail.onResponderGrant({ nativeEvent: { locationX: 15 } });
  assert.equal(rail.onResponderTerminationRequest(), false, 'reply-direction ancestor capture cannot steal an active scrub, even before a render');
  rail.onResponderMove({ nativeEvent: { locationX: 85 } });
  rail.onResponderRelease({ nativeEvent: { locationX: 85 } });
  assert.deepEqual(app.calls.at(-1), ['seek', 8500]); assert.equal(rail.onResponderTerminationRequest(), true);
  rail.onResponderGrant({ nativeEvent: { locationX: 20 } }); const oldRail = rail;
  app.props.voice.activeUri = 'file:///unrelated.m4a';
  rail = one(app.render(), 'View', props => props.accessibilityRole === 'adjustable');
  let seekCount = app.calls.filter(row => row[0] === 'seek').length;
  assert.equal(oldRail.onResponderTerminationRequest(), true); oldRail.onResponderRelease({ nativeEvent: { locationX: 90 } });
  assert.equal(app.calls.filter(row => row[0] === 'seek').length, seekCount, 'a retained old handler cannot seek a newly active recording');
  assert.equal(rail.onStartShouldSetResponder(), false); rail.onResponderGrant({ nativeEvent: { locationX: 10 } });
  assert.equal(rail.onResponderTerminationRequest(), true, 'inactive rows never prevent reply/scroll transfer');
  app.props.voice.activeUri = 'file:///owned/4.m4a'; rail = one(app.render(), 'View', props => props.accessibilityRole === 'adjustable');
  rail.onResponderGrant({ nativeEvent: { locationX: 10 } }); app.background();
  const before = app.calls.filter(row => row[0] === 'seek').length;
  assert.equal(rail.onResponderTerminationRequest(), true); rail.onResponderRelease({ nativeEvent: { locationX: 90 } });
  assert.equal(app.calls.filter(row => row[0] === 'seek').length, before, 'background cancels the old owner without seeking'); app.close();
});
test('only the active voice bubble subscribes to native progress; unrelated rows receive no clock writes', async () => {
  const app = harness(); app.cache(); app.envelope(envelope);
  const listeners = new Set(); let snapshot = { uri: 'file:///owned/4.m4a', durationMs: 10000, positionMs: 0 };
  app.props.voice.progress = { snapshot: () => snapshot, subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); } };
  app.render(); await settled(); app.render(); assert.equal(listeners.size, 0);
  one(app.render(), 'IconButton').onPress(); await settled(); app.render(); assert.equal(listeners.size, 1);
  let before = app.writes;
  for (let n = 1; n <= 20; n++) { snapshot = { ...snapshot, positionMs: n * 100 }; listeners.forEach(fn => fn()); }
  assert.equal(app.writes - before, 20, 'active row gets clock state, not the parent timeline');
  app.props.voice.activeUri = 'file:///unrelated.m4a'; app.render(); assert.equal(listeners.size, 0); before = app.writes;
  listeners.forEach(fn => fn()); assert.equal(app.writes, before); app.close(); app.props.voice.release();
});
test('native envelope validation rejects nonfinite, partial, out-of-range or over-limit data', () => {
  const app = harness(); assert.equal(app.mod.validEnvelope(envelope), true);
  for (const value of [{ ...envelope, durationMs: Infinity }, { ...envelope, durationMs: 600001 }, { ...envelope, peaks: [0.5] }, { ...envelope, peaks: Array(40).fill(NaN) }, { ...envelope, peaks: Array(40).fill(2) }]) assert.equal(app.mod.validEnvelope(value), false);
  assert.equal(app.mod.audioTime(65000), '1:05'); app.close();
});

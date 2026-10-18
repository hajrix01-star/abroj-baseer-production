/** Actual media/viewer source through native seams. Not a native layout/device proof. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');
const element = (type, props) => ({ type, props: props || {} });
const jsx = { jsx: element, jsxs: element, Fragment: 'Fragment' };
const t = word => word;
function hooks() {
  const slots = []; let at = 0; let effects = []; let unmounted = false; let lateWrites = 0;
  return {
    react: {
      useRef(value) { const i = at++; return slots[i] ?? (slots[i] = { current: value }); },
      useState(value) { const i = at++; if (!(i in slots)) slots[i] = typeof value === 'function' ? value() : value;
        return [slots[i], next => { if (unmounted) lateWrites++; slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; },
      useEffect(callback, deps) { const i = at++; if (!slots[i] || deps.some((v, n) => v !== slots[i].deps[n])) {
        effects.push(() => { slots[i]?.cleanup?.(); slots[i] = { deps, cleanup: callback() }; });
      } },
    },
    render(fn) { at = 0; effects = []; const tree = fn(); effects.forEach(effect => effect()); return tree; },
    unmount() { unmounted = true; slots.forEach(slot => slot?.cleanup?.()); },
    get lateWrites() { return lateWrites; },
  };
}
function load(file, deps) {
  const compiled = ts.transpileModule(readFileSync(join(__dirname, file), 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => deps[name] ?? {}, console }, { filename: file });
  return module.exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function one(tree, type, predicate = () => true) {
  const matches = nodes(tree).filter(node => node.type === type && predicate(node.props));
  assert.equal(matches.length, 1, `${type} unique match`); return matches[0].props;
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function settled() { for (let n = 0; n < 12; n++) await Promise.resolve(); }
const components = { Icon: 'Icon', IconButton: 'IconButton', Label: 'Label', Button: 'Button', styles: {},
  colors: { white: '#fff', pale: '#eef', blue: '#08f', ink: '#222' } };
function mediaHarness(kind = 'image') {
  const state = hooks(); const listeners = new Set(); const calls = []; const errors = [];
  let pending = deferred();
  const native = { View: 'View', Image: 'Image', Pressable: 'Pressable', ActivityIndicator: 'ActivityIndicator',
    AppState: { currentState: 'active', addEventListener(_type, callback) { listeners.add(callback); return { remove() { listeners.delete(callback); } }; } } };
  const props = { room: { company_id: 2, id: 7, membership_id: 12 },
    media: { id: 31, kind, mime: kind === 'image' ? 'image/jpeg' : 'application/pdf', sha256: 'a'.repeat(64), size: 33, name: 'synthetic.jpg' },
    voice: { playing: false, play: async uri => calls.push(['play', uri]), stop: async () => calls.push(['stop']) },
    scopeKey: 'synthetic-db/user7', t, language: 'ar', report: word => errors.push(word) };
  const mod = load('MediaTools.tsx', { react: state.react, 'react/jsx-runtime': jsx, 'react-native': native,
    './components': components, './ImageViewer': { ImageViewer: 'ImageViewer' }, './dictionary': { errorWord: () => 'error' },
    '../runtime': { localMedia: async (room, media) => { calls.push(['localMedia', room, media]); return pending.promise; } },
    'react-native-file-viewer': { open: async (...args) => calls.push(['file', ...args]) },
  });
  return { props, calls, errors, render: () => state.render(() => mod.MediaTile(props)),
    pending: () => pending, next() { pending = deferred(); }, unmount: () => state.unmount(),
    get lateWrites() { return state.lateWrites; },
    appState(value) { native.AppState.currentState = value; [...listeners].forEach(callback => callback(value)); } };
}
test('image keeps 240x180 geometry before and after explicit download; duplicate taps resolve once into local full-screen viewer', async () => {
  const app = mediaHarness();
  const initial = app.render(); const tile = one(initial, 'Pressable');
  assert.equal(app.calls.length, 0, 'history render never downloads images');
  assert.equal(nodes(initial).some(node => node.type === 'Image'), false);
  assert.deepEqual([tile.style({ pressed: false }).width, tile.style({ pressed: false }).height], [240, 180]);
  assert.equal(one(initial, 'Icon', p => p.icon === 'maximize').size, 20);
  tile.onPress(); tile.onPress();
  assert.equal(app.calls.length, 1);
  assert.equal(one(app.render(), 'Pressable').disabled, true);
  app.pending().resolve('file:///scoped/image31.jpg'); await settled();
  const loaded = app.render();
  assert.equal(one(loaded, 'ImageViewer').uri, 'file:///scoped/image31.jpg');
  assert.deepEqual([one(loaded, 'Pressable').style({ pressed: false }).width, one(loaded, 'Pressable').style({ pressed: false }).height], [240, 180]);
  one(loaded, 'ImageViewer').onClose();
  const closed = app.render();
  assert.equal(nodes(closed).some(node => node.type === 'ImageViewer'), false);
  assert.equal(one(closed, 'Image').source.uri, 'file:///scoped/image31.jpg', 'thumbnail survives closing');
  app.next(); one(closed, 'Pressable').onPress();
  assert.equal(app.calls.length, 2, 'reopening still uses guarded localMedia, not a new network shortcut');
  app.pending().resolve('file:///scoped/image31.jpg'); await settled();
  assert.equal(one(app.render(), 'ImageViewer').uri, 'file:///scoped/image31.jpg');
});
test('background invalidates a pending image result and never reopens it on return', async () => {
  const app = mediaHarness(); one(app.render(), 'Pressable').onPress();
  app.appState('background'); app.appState('active');
  app.pending().resolve('file:///scoped/late.jpg'); await settled();
  assert.equal(nodes(app.render()).some(node => ['Image', 'ImageViewer'].includes(node.type)), false);
  assert.equal(app.errors.length, 0);
  app.next(); one(app.render(), 'Pressable').onPress();
  app.pending().resolve('file:///scoped/current.jpg'); await settled();
  assert.equal(one(app.render(), 'ImageViewer').uri, 'file:///scoped/current.jpg');
  app.appState('background');
  assert.equal(nodes(app.render()).some(node => node.type === 'ImageViewer'), false);
});
test('scope and recycled media changes cannot expose stale thumbnails or late full-screen results', async () => {
  for (const change of [app => { app.props.scopeKey = 'synthetic-db/user8'; },
    app => { app.props.media = { ...app.props.media, id: 32 }; },
    app => { app.props.room = { ...app.props.room, membership_id: 99 }; }]) {
    const app = mediaHarness(); one(app.render(), 'Pressable').onPress();
    const old = app.pending(); change(app); app.render();
    old.resolve('file:///scoped/old.jpg'); await settled();
    assert.equal(nodes(app.render()).some(node => ['Image', 'ImageViewer'].includes(node.type)), false);
    app.next(); one(app.render(), 'Pressable').onPress();
    app.pending().resolve('file:///scoped/new.jpg'); await settled();
    assert.equal(one(app.render(), 'ImageViewer').uri, 'file:///scoped/new.jpg');
    app.props.media = { ...app.props.media, id: 50 };
    assert.equal(nodes(app.render()).some(node => ['Image', 'ImageViewer'].includes(node.type)), false, 'hide previous image on first recycled render');
  }
});
test('recycling back to the original descriptor never resurrects the previous image without a fresh scoped open', async () => {
  const app = mediaHarness(); one(app.render(), 'Pressable').onPress();
  app.pending().resolve('file:///scoped/first.jpg'); await settled();
  assert.equal(one(app.render(), 'ImageViewer').uri, 'file:///scoped/first.jpg');
  const original = app.props.media;
  app.props.media = { ...original, id: 32 }; app.render();
  app.props.media = original;
  assert.equal(nodes(app.render()).some(node => ['Image', 'ImageViewer'].includes(node.type)), false);
  assert.equal(one(app.render(), 'Pressable').disabled, false);
});
test('unmount ignores late media completion; rejected/remote image input leaves a retryable placeholder', async () => {
  const closed = mediaHarness(); one(closed.render(), 'Pressable').onPress(); closed.unmount();
  closed.pending().resolve('file:///scoped/late.jpg'); await settled(); assert.equal(closed.errors.length, 0);
  assert.equal(closed.lateWrites, 0);
  for (const result of ['https://not-an-image-source.invalid/picture', null]) {
    const app = mediaHarness(); one(app.render(), 'Pressable').onPress();
    if (result) app.pending().resolve(result); else app.pending().reject(new Error('synthetic failure'));
    await settled(); const tree = app.render();
    assert.equal(nodes(tree).some(node => ['Image', 'ImageViewer'].includes(node.type)), false);
    assert.equal(one(tree, 'Pressable').disabled, false); assert.deepEqual(app.errors, ['error']);
  }
});
test('file and audio retain guarded local resolution, file-viewer and playback paths without image UI', async () => {
  for (const kind of ['audio', 'file']) {
    const app = mediaHarness(kind); const tree = app.render();
    assert.equal(nodes(tree).some(node => ['ImageViewer', 'Pressable'].includes(node.type)), false);
    one(tree, 'Button').onPress();
    app.pending().resolve('file:///scoped/attachment'); await settled();
    assert.equal(app.calls[0][0], 'localMedia'); assert.equal(app.calls[0][1], app.props.room);
    assert.equal(app.calls[0][2], app.props.media);
    assert.equal(app.calls[1][0], kind === 'audio' ? 'play' : 'file');
    assert.equal(app.calls[1][1], kind === 'audio' ? 'file:///scoped/attachment' : '/scoped/attachment');
    if (kind === 'audio') { app.props.voice.playing = true; one(app.render(), 'Button', p => p.title === 'stop').onPress(); await settled(); assert.equal(app.calls.at(-1)[0], 'stop'); }
  }
});
function viewerHarness(uri = 'file:///scoped/image.jpg') {
  const state = hooks(); let gestures; let closes = 0;
  const mod = load('ImageViewer.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { Image: 'Image', Modal: 'Modal', Text: 'Text', View: 'View', PanResponder: { create(config) { gestures = config; return { panHandlers: { responderFixture: true } }; } } },
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' }, './components': components });
  const props = { uri, name: 'synthetic.jpg', language: 'ar', t, onClose() { closes++; } };
  return { props, get gestures() { return gestures; }, get closes() { return closes; }, render: () => state.render(() => mod.ImageViewer(props)) };
}
test('full-screen viewer closes by explicit button and Android modal back; zoom bounds, pan and resize are constrained', () => {
  const app = viewerHarness(); let tree = app.render();
  assert.equal(one(tree, 'Modal').presentationStyle, 'fullScreen');
  assert.equal(one(tree, 'Modal').animationType, 'none');
  one(tree, 'Modal').onRequestClose(); one(tree, 'IconButton', p => p.icon === 'close').onPress(); assert.equal(app.closes, 2);
  one(tree, 'View', p => !!p.onLayout).onLayout({ nativeEvent: { layout: { width: 300, height: 400 } } });
  one(tree, 'Image').onLoad({ nativeEvent: { source: { width: 600, height: 800 } } });
  tree = app.render(); assert.equal(one(tree, 'IconButton', p => p.icon === 'zoomOut').disabled, true);
  assert.equal(app.gestures.onMoveShouldSetPanResponder({ nativeEvent: { touches: [1] } }, { dx: 20, dy: 5 }), false);
  for (let i = 0; i < 6; i++) one(app.render(), 'IconButton', p => p.icon === 'zoomIn').onPress();
  tree = app.render(); assert.equal(one(tree, 'IconButton', p => p.icon === 'zoomIn').disabled, true);
  assert.equal(one(tree, 'Image').style.transform[2].scale, 4);
  assert.equal(app.gestures.onMoveShouldSetPanResponder({ nativeEvent: { touches: [1] } }, { dx: 20, dy: 5 }), true);
  assert.equal(app.gestures.onMoveShouldSetPanResponder({ nativeEvent: { touches: [1, 2] } }, { dx: 20, dy: 5 }), false);
  app.gestures.onPanResponderGrant();
  app.gestures.onPanResponderMove({ nativeEvent: { touches: [1] } }, { dx: 9999, dy: -9999 });
  tree = app.render(); const transform = one(tree, 'Image').style.transform;
  assert.equal(transform[0].translateX, 450); assert.equal(transform[1].translateY, -600);
  app.gestures.onPanResponderMove({ nativeEvent: { touches: [1, 2] } }, { dx: -9999, dy: 9999 });
  assert.equal(one(app.render(), 'Image').style.transform[0].translateX, 450, 'additional fingers never jump the image');
  for (let i = 0; i < 6; i++) one(app.render(), 'IconButton', p => p.icon === 'zoomOut').onPress();
  tree = app.render(); assert.equal(one(tree, 'Image').style.transform[2].scale, 1);
  assert.equal(Math.abs(one(tree, 'Image').style.transform[0].translateX), 0);
  assert.equal(Math.abs(one(tree, 'Image').style.transform[1].translateY), 0);
  app.props.language = 'en'; assert.equal(one(app.render(), 'View', p => Array.isArray(p.style) ? false : !!p.style?.flexDirection).style.flexDirection, 'row');
  assert.equal(viewerHarness('https://remote.invalid/image.jpg').render(), null);
});
test('all image controls have distinct bilingual labels in the actual dictionary', () => {
  const { translator } = load('dictionary.ts', {});
  for (const key of ['viewPhoto', 'zoomPhoto', 'closePhoto', 'zoomIn', 'zoomOut', 'photoPanHint']) {
    assert.ok(translator('ar')(key)); assert.ok(translator('en')(key)); assert.notEqual(translator('ar')(key), translator('en')(key));
  }
});

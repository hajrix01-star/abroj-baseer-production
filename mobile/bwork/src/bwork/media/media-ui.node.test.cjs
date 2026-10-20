/** Executes production components; native pixels are verified separately, never claimed here. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const jsx = { jsx: (type, props, key) => ({ type, key, props: props || {} }), jsxs: (type, props, key) => ({ type, key, props: props || {} }) };
function hooks() {
  const slots = []; let index = 0, dirty, effects, closed = false, late = 0;
  return { react: {
    useRef(value) { const at = index++; return slots[at] ?? (slots[at] = { current: value }); },
    useState(initial) { const at = index++; if (!(at in slots)) slots[at] = typeof initial === 'function' ? initial() : initial;
      return [slots[at], value => { if (closed) late++; const next = typeof value === 'function' ? value(slots[at]) : value; if (next !== slots[at]) { slots[at] = next; dirty = true; } }]; },
    useEffect(callback, deps) { const at = index++; if (!slots[at] || deps.some((v, n) => v !== slots[at].deps[n])) effects.push(() => { slots[at]?.cleanup?.(); slots[at] = { deps, cleanup: callback() }; }); },
  }, render(callback) { for (let pass = 0; pass < 12; pass++) { index = 0; dirty = false; effects = []; const tree = callback(); effects.forEach(effect => effect()); if (!dirty) return tree; } throw Error('render loop'); },
    close() { closed = true; slots.forEach(slot => slot?.cleanup?.()); }, get late() { return late; } };
}
function load(file, modules) {
  const module = { exports: {} }, code = ts.transpileModule(fs.readFileSync(path.join(__dirname, file), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  vm.runInNewContext(code, { module, exports: module.exports, require: name => modules[name] ?? {}, console, Map, Set, Date }, { filename: file }); return module.exports;
}
function nodes(tree) { if (!tree || typeof tree !== 'object') return []; if (Array.isArray(tree)) return tree.flatMap(nodes); return [tree, ...nodes(tree.props?.children)]; }
function one(tree, type, filter = () => true) { const values = nodes(tree).filter(node => node.type === type && filter(node.props)); assert.equal(values.length, 1, `${type} unique`); return values[0].props; }
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
async function settle() { for (let i = 0; i < 25; i++) await Promise.resolve(); }
const components = { Button: 'Button', Label: 'Label', Sheet: 'Sheet', styles: { row: {}, text: {}, muted: {} }, direction: () => ({}), colors: { blue: 'blue', pale: 'pale', ink: 'ink', white: 'white' } };
const dictionary = load('dictionary.ts', {});
const totals = { files: 2, bytes: 1024, filesDisplay: '2', bytesDisplay: '1.00 KiB' };
const overview = { total: totals, protected: { ...totals, files: 0 }, policy: { autoClean30Days: false } };
function fixture(file, runtime = {}) {
  let currentHooks = hooks(); const react = new Proxy({}, { get: (_target, key) => key === '__esModule' ? true : key === 'default' ? react : currentHooks.react[key] });
  const listeners = new Set(), native = { currentState: 'active', addEventListener(_name, callback) { listeners.add(callback); return { remove: () => listeners.delete(callback) }; }, change(state) { this.currentState = state; [...listeners].forEach(callback => callback(state)); } };
  class ChatError extends Error { constructor(code, status) { super(code); this.code = code; this.status = status; } }
  const module = load(file, { react, 'react/jsx-runtime': jsx, 'react-native': { AppState: native, ActivityIndicator: 'ActivityIndicator', View: 'View', Switch: 'Switch', Pressable: 'Pressable', Text: 'Text' },
    '@shopify/flash-list': { FlashList: 'FlashList' }, '../ui/components': components, './dictionary': dictionary, '../runtime': runtime,
    '../core/ChatEngine': { ChatError }, '../core/MediaGallery': { GALLERY_LIMITS: { associations: 180 } }, '../ui/MediaTools': { MediaTile: 'MediaTile', useVoiceSession: () => ({}) }, '../ui/viewModel': { messageDateTime: value => value } });
  const state = currentHooks;
  return { module, state, native, childState() { currentHooks = hooks(); return currentHooks; }, useState(value) { currentHooks = value; } };
}
test('device cleanup requires a preview token, prevents double confirmation and reports actual partial results', async () => {
  const calls = [], pending = deferred();
  const app = fixture('MediaStorageSheet.tsx', { mediaCacheOverview: async () => overview, planMediaCacheCleanup: async mode => { calls.push(['plan', mode]); return { id: 'opaque', mode, expiresAt: Date.now() + 300000, estimated: totals }; },
    confirmMediaCacheCleanup: token => { calls.push(['confirm', token]); return pending.promise; }, setMediaCachePolicy: async value => calls.push(['policy', value]) });
  const props = { scopeKey: 'actor7', language: 'en', t: key => key, close() {} }, render = () => app.state.render(() => app.module.MediaStorageSheet(props));
  render(); await settle(); let tree = render(); assert.equal(one(tree, 'Switch').value, false);
  one(tree, 'Button', p => p.title === 'Clean temporary copies').onPress(); await settle(); tree = render();
  const confirm = one(tree, 'Button', p => p.title === 'Clean from device'); confirm.onPress(); confirm.onPress();
  assert.equal(calls.filter(call => call[0] === 'confirm').length, 1);
  pending.resolve({ deleted: totals, skipped: totals, failed: totals, partial: true }); await settle(); tree = render();
  assert.ok(nodes(tree).some(node => node.props.children === 'Some copies were not removed. Review the result below.'));
  assert.ok(nodes(tree).some(node => node.props.title === 'Could not remove' && node.props.value.files === 2));
});
test('stale storage actions and late preview results cannot affect a new actor or an unmounted sheet', async () => {
  const calls = [], pending = deferred();
  const app = fixture('MediaStorageSheet.tsx', { mediaCacheOverview: async () => overview, planMediaCacheCleanup: async () => { calls.push('plan'); return pending.promise; }, setMediaCachePolicy: async () => calls.push('policy') });
  const props = { scopeKey: 'actor7', language: 'en', t: key => key, close() {} }, render = () => app.state.render(() => app.module.MediaStorageSheet(props));
  render(); await settle(); const tree = render(), oldSwitch = one(tree, 'Switch').onValueChange, oldClean = one(tree, 'Button', p => p.title === 'Clean temporary copies').onPress;
  oldClean(); props.scopeKey = 'actor8'; render(); await settle(); oldSwitch(true); oldClean();
  assert.deepEqual(calls, ['plan']);
  app.state.close(); pending.resolve({ id: 'old-plan', estimated: totals }); await settle(); assert.equal(app.state.late, 0);
});
test('a held policy save cannot start a new actor storage read after the sheet closes', async () => {
  const pending = deferred(); let reads = 0;
  const app = fixture('MediaStorageSheet.tsx', { mediaCacheOverview: async () => { reads++; return overview; }, setMediaCachePolicy: () => pending.promise });
  const props = { scopeKey: 'actor7', language: 'en', t: key => key, close() {} }, render = () => app.state.render(() => app.module.MediaStorageSheet(props));
  render(); await settle(); one(render(), 'Switch').onValueChange(true);
  app.state.close(); pending.resolve(); await settle();
  assert.equal(reads, 1); assert.equal(app.state.late, 0);
});
test('gallery lazily exposes media only for visible rows and stale page responses cannot cross filters or unmount', async () => {
  const pending = deferred(), requests = [];
  const app = fixture('MediaGallerySheet.tsx');
  const props = { scopeKey: 'actor7', room: { id: 4, company_id: 1, membership_id: 12 }, language: 'en', t: key => key, close() {}, onMessage: async () => {},
    engine: { mediaGallery: async (_room, query) => { requests.push(query); return requests.length === 1 ? { items: [{ id: 8, media: { id: 108, size_label: '3 B' }, author_name: 'Test', created_at: '2026-10-20' }], next_cursor: 'next' } : pending.promise; } } };
  const render = () => app.state.render(() => app.module.MediaGallerySheet(props)); render(); await settle(); let tree = render(), list = one(tree, 'FlashList');
  let row = list.renderItem({ item: list.data[0] }); assert.equal(one(row, 'MediaTile').previewVisible, false);
  list.onViewableItemsChanged({ viewableItems: [{ isViewable: true, item: list.data[0] }] }); list = one(render(), 'FlashList');
  row = list.renderItem({ item: list.data[0] }); assert.equal(one(row, 'MediaTile').previewVisible, true);
  one(list.ListFooterComponent, 'Button').onPress(); const held = list.onViewableItemsChanged;
  app.state.close(); pending.resolve({ items: [], next_cursor: null }); await settle();
  held({ viewableItems: [] }); assert.equal(app.state.late, 0); assert.equal(requests.length, 2);
});
test('offline state reads cannot overwrite a newer keep result when a row becomes visible again', async () => {
  const staleRead = deferred(), mutation = deferred(); let reads = 0;
  const app = fixture('MediaGallerySheet.tsx', { mediaOfflineState: async () => { reads++; return reads === 2 ? staleRead.promise : { kept: reads >= 3, available: reads >= 3 }; }, setMediaOffline: () => mutation.promise });
  const props = { scopeKey: 'actor7', room: { id: 4, company_id: 1, membership_id: 12 }, language: 'en', t: key => key, close() {}, onMessage: async () => {}, engine: { mediaGallery: async () => ({ items: [], next_cursor: null }) } };
  app.state.render(() => app.module.MediaGallerySheet(props)); await settle();
  const row = one(app.state.render(() => app.module.MediaGallerySheet(props)), 'FlashList').renderItem({ item: { id: 8, media: { id: 108 }, author_name: 'T', created_at: '2026-10-20' } });
  const child = nodes(row).find(node => typeof node.type === 'function' && node.type.name === 'OfflineControl'); assert.ok(child);
  const state = app.childState(), childProps = { ...child.props, visible: true }, render = () => state.render(() => child.type(childProps));
  render(); await settle(); let tree = render();
  childProps.visible = false; render(); childProps.visible = true; render(); // second read held
  one(tree, 'Button').onPress(); mutation.resolve({ kept: true, available: true }); await settle();
  staleRead.resolve({ kept: false, available: false }); await settle(); tree = render();
  assert.equal(one(tree, 'Button').title, 'Release offline copy');
  assert.ok(nodes(tree).some(node => node.props.children === 'Kept on this device'));
});

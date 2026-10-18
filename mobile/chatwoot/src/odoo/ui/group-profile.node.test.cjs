/** Actual group UI/effect source through native/API seams; not backend or Android rendering proof. */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const element = (type, props) => ({ type, props: props || {} });
const jsx = { jsx: element, jsxs: element, Fragment: 'Fragment' };
function hooks() {
  const slots = []; let index = 0, effects = [], dirty = false, closed = false, lateWrites = 0;
  return { react: {
    useRef(value) { const at = index++; return slots[at] ?? (slots[at] = { current: value }); },
    useState(value) { const at = index++; if (!(at in slots)) slots[at] = typeof value === 'function' ? value() : value;
      return [slots[at], next => { if (closed) lateWrites++; const result = typeof next === 'function' ? next(slots[at]) : next;
        if (!Object.is(result, slots[at])) { slots[at] = result; dirty = true; } }]; },
    useEffect(callback, deps) { const at = index++; if (!slots[at] || deps.some((value, n) => value !== slots[at].deps[n])) {
      effects.push(() => { slots[at]?.cleanup?.(); slots[at] = { deps, cleanup: callback() }; });
    } },
  }, render(component) { for (let pass = 0; pass < 15; pass++) { index = 0; effects = []; dirty = false;
      const tree = component(); effects.forEach(effect => effect()); if (!dirty) return tree; } throw Error('render did not settle'); },
    close() { closed = true; slots.forEach(slot => slot?.cleanup?.()); }, get lateWrites() { return lateWrites; } };
}
function load(file, dependencies) {
  const module = { exports: {} };
  const code = ts.transpileModule(readFileSync(join(__dirname, file), 'utf8'), { fileName: file, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  vm.runInNewContext(code, { module, exports: module.exports, require: name => dependencies[name] ?? {}, TextEncoder,
    setTimeout: dependencies.setTimeout, clearTimeout: dependencies.clearTimeout }, { filename: file });
  return module.exports;
}
function nodes(tree) { if (!tree || typeof tree !== 'object') return []; if (Array.isArray(tree)) return tree.flatMap(nodes); return [tree, ...nodes(tree.props?.children)]; }
function one(tree, type, predicate = () => true) { const found = nodes(tree).filter(node => node.type === type && predicate(node.props)); assert.equal(found.length, 1, `${type} unique match`); return found[0].props; }
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function settle() { for (let n = 0; n < 25; n++) await Promise.resolve(); }
const copy = value => JSON.parse(JSON.stringify(value));
const components = { GroupAvatar: 'GroupAvatar', Button: 'Button', Field: 'Field', IconButton: 'IconButton', Label: 'Label', Icon: 'Icon', Sheet: 'Sheet',
  colors: { pale: 'pale', blue: 'blue', border: 'border' }, direction: () => ({}), styles: { row: {}, muted: {}, fill: {}, text: {} } };
function avatar() {
  const state = hooks(), pending = [], cache = new Set(), listeners = new Set(); let clears = 0;
  const props = { room: { id: 4, company_id: 1, membership_id: 12, is_group: true, name: 'مجموعة', avatar_version: 1 }, enabled: true,
    engine: { accountScope: 'https://synthetic.invalid/db/user7/epoch1', identity: { database: 'db', user_id: 7, permissions: { chat_view: true, media: false } }, rooms: () => [props.room] } };
  const mod = load('GroupAvatar.tsx', { react: state.react, 'react/jsx-runtime': jsx, 'react-native': { View: 'View', Image: 'Image', Text: 'Text' }, './components': components,
    '../runtime': { hasGroupAvatar: key => cache.has(key), clearGroupAvatars() { cache.clear(); clears++; listeners.forEach(listener => listener()); },
      subscribeGroupAvatars(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      readGroupAvatar(engine, room) { const request = { ...deferred(), engine, room: copy(room) }; pending.push(request); return request.promise; } } });
  return { props, pending, render: () => state.render(() => mod.GroupAvatar(props)), close: () => state.close(), get lateWrites() { return state.lateWrites; },
    get clears() { return clears; },
    resolve(at = pending.length - 1, key = `owned-${at}`) { cache.add(key); pending[at].resolve({ key, version: pending[at].room.avatar_version, uri: `data:image/png;base64,${key}` }); },
    evict() { cache.clear(); listeners.forEach(listener => listener()); } };
}
test('GroupAvatar version0 does not fetch; authorized media=false member gets local data image, decorative unless labelled', async () => {
  const app = avatar(); app.props.room.avatar_version = 0;
  const fallback = app.render(); assert.equal(app.pending.length, 0); assert.equal(nodes(fallback).some(n => n.type === 'Image'), false);
  assert.equal(one(fallback, 'View').accessible, false); assert.equal(one(fallback, 'Text').children, 'م');
  app.props.room.avatar_version = 1; app.render(); assert.equal(app.pending.length, 1);
  app.resolve(); await settle(); const image = one(app.render(), 'Image');
  assert.match(image.source.uri, /^data:image\/png;base64,/); assert.equal(image.accessible, false);
  app.props.label = 'groupPhoto'; app.props.size = 200;
  const labelled = app.render(); assert.equal(one(labelled, 'View').accessible, true); assert.equal(one(labelled, 'View').accessibilityLabel, 'groupPhoto');
  assert.equal(one(labelled, 'View').style.width, 96); assert.equal(app.pending.length, 1);
});
test('GroupAvatar hides old images and ignores stale promises on actor/database/engine/member/version changes', async () => {
  const changes = [app => { app.props.engine.accountScope += '/new-epoch'; },
    app => { app.props.engine.identity = { ...app.props.engine.identity, database: 'db2' }; },
    app => { app.props.engine = { ...app.props.engine }; },
    app => { app.props.room = { ...app.props.room, membership_id: 13 }; },
    app => { app.props.room = { ...app.props.room, avatar_version: 2 }; }];
  for (const change of changes) {
    const app = avatar(); app.render(); app.resolve(0, 'first'); await settle(); assert.ok(one(app.render(), 'Image'));
    change(app); assert.equal(nodes(app.render()).some(n => n.type === 'Image'), false);
    assert.equal(app.pending.length, 2); app.resolve(1, 'current'); await settle();
    assert.equal(one(app.render(), 'Image').source.uri, 'data:image/png;base64,current');
    const late = avatar(); late.render(); change(late); late.render(); late.resolve(0, 'late'); await settle();
    assert.equal(nodes(late.render()).some(n => n.type === 'Image'), false);
  }
});
test('GroupAvatar eviction, masking, rights loss and unmount never retain a private image or late state write', async () => {
  const app = avatar(); app.render(); app.resolve(); await settle(); assert.ok(one(app.render(), 'Image'));
  app.evict(); assert.equal(nodes(app.render()).some(n => n.type === 'Image'), false); assert.equal(app.pending.length, 1);
  app.props.enabled = false; app.render(); assert.equal(app.clears, 1);
  app.props.enabled = true; app.props.engine.identity.permissions.chat_view = false;
  assert.equal(nodes(app.render()).some(n => n.type === 'Image'), false);
  const late = avatar(); late.render(); late.close(); late.resolve(); await settle(); assert.equal(late.lateWrites, 0);
});

function management(manage = true) {
  const state = hooks(), timers = new Map(), calls = []; let nextTimer = 0, picker = { didCancel: true }, post = null;
  const core = load('../core/ChatEngine.ts', {});
  const listeners = new Set();
  const AppState = { currentState: 'active', addEventListener(event, listener) { listeners.add(listener); return { remove: () => listeners.delete(listener) }; } };
  const clock = { setTimeout: callback => { const id = ++nextTimer; timers.set(id, callback); return id; }, clearTimeout: id => timers.delete(id) };
  const helper = load('groupPhotoOperation.ts', { ...clock, 'react-native': { AppState }, '../core/ChatEngine': core });
  const detail = { api_version: 2, can_manage: manage,
    room: { id: 4, company_id: 1, is_group: true, name: 'Synthetic', description: 'Saved description', avatar_version: 1 },
    members: [{ user_id: 7, name: 'Current', is_admin: manage }] };
  const engine = { accountScope: 'actor7/epoch1', identity: { database: 'db', user_id: 7, company_ids: [1], permissions: { chat_view: true } }, offline: false,
    rooms: () => [props.room],
    groupInfo: async () => { calls.push(['detail']); return copy(detail); }, candidates: async () => ({ users: [] }),
    groupChange: async (room, payload) => { calls.push(['change', room, copy(payload)]); if (post) await post.promise;
      if (payload.action === 'set_description') detail.room.description = payload.description; },
    setGroupAvatar: async (room, input) => { calls.push(['photo', room, input]); detail.room.avatar_version++; return copy(detail); } };
  const props = { mode: 'members', room: { id: 4, company_id: 1, membership_id: 12, is_group: true, avatar_version: 1, name: 'Synthetic' }, companyId: 1,
    engine, language: 'ar', t: key => key, close: () => calls.push(['close']), changed: async () => { calls.push(['changed']); },
    onPhotoOutcome: outcome => calls.push(['outcome', outcome]) };
  const mod = load('ManagementSheet.tsx', { react: state.react, 'react/jsx-runtime': jsx, '../core/ChatEngine': core, './GroupAvatar': { GroupAvatar: 'GroupAvatar' },
    './components': components, './dictionary': { errorWord: error => error.code || 'error' },
    './groupPhotoOperation': helper,
    'react-native': { ActivityIndicator: 'ActivityIndicator', AppState, View: 'View', Text: 'Text', Pressable: 'Pressable', Switch: 'Switch', Alert: { alert() {} } },
    'react-native-image-picker': { launchImageLibrary: async () => { calls.push(['picker']); return picker; } },
    ...clock });
  return { props, calls, detail, core, render: () => state.render(() => mod.ManagementSheet(props)),
    async ready() { this.render(); await settle(); this.render(); for (const [id, callback] of [...timers]) { timers.delete(id); await callback(); } await settle(); return this.render(); },
    deferPost() { post = deferred(); return post; }, picker(value) { picker = value; }, close: () => state.close(), get lateWrites() { return state.lateWrites; },
    lifecycle(value) { AppState.currentState = value; for (const listener of [...listeners]) listener(value); },
    get listenerCount() { return listeners.size; }, expire() { for (const callback of [...timers.values()]) callback(); } };
}
const description = tree => one(tree, 'Field', p => p.accessibilityLabel === 'groupDescription');
const saveDescription = tree => one(tree, 'Button', p => p.title === 'saveDescription');
const photo = tree => one(tree, 'Button', p => p.title === 'changeGroupPhoto');
test('admin description uses actual normalization, exact payload/readback and empty clear; duplicate save is serialized', async () => {
  const app = management(); await app.ready();
  description(app.render()).onChangeText('  first\r\nsecond  '); const save = saveDescription(app.render());
  save.onPress(); save.onPress(); await settle();
  const sent = app.calls.filter(call => call[0] === 'change'); assert.equal(sent.length, 1);
  assert.deepEqual(sent[0][2], { action: 'set_description', description: 'first\nsecond' });
  assert.equal(sent[0][1], app.props.room); assert.equal(description(app.render()).value, 'first\nsecond');
  assert.equal(saveDescription(app.render()).disabled, true);
  description(app.render()).onChangeText('   '); saveDescription(app.render()).onPress(); await settle();
  assert.equal(app.calls.filter(call => call[0] === 'change').at(-1)[2].description, '');
  assert.equal(description(app.render()).value, '');
});
test('later dirty description survives an earlier save ACK and readback', async () => {
  const app = management(); await app.ready(); const pending = app.deferPost();
  description(app.render()).onChangeText('submitted'); saveDescription(app.render()).onPress();
  description(app.render()).onChangeText('newer draft'); pending.resolve(); await settle();
  assert.equal(app.detail.room.description, 'submitted'); assert.equal(description(app.render()).value, 'newer draft');
  assert.equal(saveDescription(app.render()).disabled, false);
});
test('ordinary group member sees description/avatar without editor, photo picker or mutation controls', async () => {
  const app = management(false); const tree = await app.ready();
  assert.equal(nodes(tree).some(n => n.type === 'Field'), false);
  assert.equal(nodes(tree).some(n => n.type === 'Button' && ['saveDescription', 'changeGroupPhoto'].includes(n.props.title)), false);
  assert.ok(nodes(tree).some(n => n.type === 'Label' && n.props.children === 'Saved description'));
  assert.equal(one(tree, 'GroupAvatar').engine, app.props.engine); assert.equal(one(tree, 'GroupAvatar').enabled, true);
  assert.equal(app.calls.some(call => ['photo', 'change', 'picker'].includes(call[0])), false);
});
test('photo picker cancellation is harmless; pending picker from changed account is rejected even before rerender', async () => {
  const cancel = management(); await cancel.ready(); photo(cancel.render()).onPress(); await settle();
  assert.equal(cancel.calls.filter(call => call[0] === 'photo').length, 0); assert.equal(photo(cancel.render()).disabled, false);
  const app = management(); await app.ready(); const pick = deferred(); app.picker(pick.promise);
  photo(app.render()).onPress(); app.props.engine.accountScope = 'actor8/epoch2'; app.props.engine.identity = { database: 'db', user_id: 8 };
  pick.resolve({ assets: [{ uri: 'file:///picker/group.jpg', fileName: 'group.jpg', type: 'image/jpeg' }] }); await settle();
  assert.equal(app.calls.filter(call => call[0] === 'photo').length, 0); assert.equal(app.calls.filter(call => call[0] === 'changed').length, 0);
});
test('successful photo ACK updates avatar version; uncertain upload reads back but never retries or invents success', async () => {
  const app = management(); await app.ready(); app.picker({ assets: [{ uri: 'file:///picker/group.jpg', type: 'image/jpeg', fileName: 'group.jpg' }] });
  photo(app.render()).onPress(); await settle();
  assert.equal(app.calls.filter(call => call[0] === 'photo').length, 1); assert.equal(one(app.render(), 'GroupAvatar').room.avatar_version, 2);
  assert.equal(app.calls.filter(call => call[0] === 'changed').length, 1);
  const uncertain = management(); await uncertain.ready(); uncertain.picker({ assets: [{ uri: 'file:///picker/uncertain.jpg', type: 'image/jpeg' }] });
  let uploads = 0; uncertain.props.engine.setGroupAvatar = async () => { uploads++; uncertain.detail.room.avatar_version = 2; throw new uncertain.core.ChatError('avatar_upload_uncertain'); };
  photo(uncertain.render()).onPress(); await settle();
  assert.equal(uploads, 1); assert.equal(one(uncertain.render(), 'GroupAvatar').room.avatar_version, 2);
  assert.equal(uncertain.calls.filter(call => call[0] === 'changed').length, 0);
  assert.ok(nodes(uncertain.render()).some(n => n.type === 'Text' && n.props.children === 'avatar_upload_uncertain'));
});

test('same-actor new session rejects the previous pending photo picker without requiring a render', async () => {
  const app = management(); await app.ready(); const pick = deferred(); app.picker(pick.promise);
  const sameIdentity = copy(app.props.engine.identity), sameRoom = copy(app.props.room);
  photo(app.render()).onPress();
  // Same database/uid/company/room/member after logout + relogin, but a new core epoch.
  app.props.engine.accountScope = 'actor7/epoch2';
  assert.deepEqual(app.props.engine.identity, sameIdentity); assert.deepEqual(app.props.room, sameRoom);
  pick.resolve({ assets: [{ uri: 'file:///picker/stale-session.jpg', type: 'image/jpeg' }] }); await settle();
  assert.equal(app.calls.filter(call => call[0] === 'photo').length, 0);
  assert.equal(app.calls.filter(call => call[0] === 'changed').length, 0);
});

test('native picker privacy unmount does not discard an explicitly chosen photo or write into the closed sheet', async () => {
  const app = management(); await app.ready(); const pick = deferred(); app.picker(pick.promise);
  photo(app.render()).onPress(); app.lifecycle('background'); app.close();
  pick.resolve({ assets: [{ uri: 'file:///picker/chosen-after-background.jpg', type: 'image/jpeg' }] }); await settle();
  assert.equal(app.calls.filter(call => call[0] === 'photo').length, 0, 'chosen callback before active cannot upload yet');
  assert.equal(app.listenerCount, 1); app.lifecycle('active'); await settle();
  assert.equal(app.calls.filter(call => call[0] === 'photo').length, 1);
  assert.equal(app.detail.room.avatar_version, 2, 'successful operation exposes authoritative ACK version');
  assert.equal(app.calls.filter(call => call[0] === 'changed').length, 0, 'closed sheet cannot invoke presentation callback');
  assert.equal(app.lateWrites, 0);
  assert.equal(app.listenerCount, 0);
  assert.equal(app.calls.filter(call => call[0] === 'outcome').length, 1);
  assert.equal(app.calls.find(call => call[0] === 'outcome')[1].status, 'saved');
  assert.equal(app.calls.find(call => call[0] === 'outcome')[1].error, undefined);
});

test('unmounted picker cancel, revoked membership, new epoch and foreground timeout never upload', async () => {
  for (const scenario of ['cancel', 'membership', 'epoch', 'timeout', 'noasset', 'membership-after-choice', 'epoch-after-choice']) {
    const app = management(); await app.ready(); const pick = deferred(); app.picker(pick.promise);
    photo(app.render()).onPress(); app.lifecycle('background'); app.close();
    if (scenario === 'membership') app.props.engine.rooms = () => [];
    if (scenario === 'epoch') app.props.engine.accountScope = 'actor7/epoch2';
    pick.resolve(scenario === 'cancel' ? { didCancel: true } : scenario === 'noasset' ? {} : { assets: [{ uri: 'file:///picker/not-authorized.jpg', type: 'image/jpeg' }] });
    await settle();
    if (scenario === 'membership-after-choice') app.props.engine.rooms = () => [];
    if (scenario === 'epoch-after-choice') app.props.engine.accountScope = 'actor7/epoch2';
    if (scenario === 'timeout') { assert.equal(app.listenerCount, 1); app.expire(); await settle(); }
    app.lifecycle('active'); await settle();
    assert.equal(app.calls.filter(call => call[0] === 'photo').length, 0, scenario);
    assert.equal(app.calls.filter(call => call[0] === 'changed').length, 0, scenario);
    assert.equal(app.calls.filter(call => call[0] === 'outcome' && call[1].status === 'saved').length, 0, 'no false success');
    assert.equal(app.listenerCount, 0, scenario); assert.equal(app.lateWrites, 0, scenario);
  }
});
test('description readback mismatch leaves the draft dirty and surfaces an error, not a false saved value', async () => {
  const app = management(); await app.ready();
  app.props.engine.groupChange = async () => { app.detail.room.description = 'Unexpected server value'; };
  description(app.render()).onChangeText('Wanted draft'); saveDescription(app.render()).onPress(); await settle();
  const tree = app.render(); assert.equal(description(tree).value, 'Wanted draft');
  assert.equal(saveDescription(tree).disabled, false);
  assert.ok(nodes(tree).some(n => n.type === 'Text' && n.props.children === 'group_readback_mismatch'));
});

test('unknown upload failure cannot be confused with a saved outcome after privacy unmount', async () => {
  const app = management(); await app.ready(); const pick = deferred(); app.picker(pick.promise);
  app.props.engine.setGroupAvatar = async () => { throw undefined; };
  photo(app.render()).onPress(); app.close();
  pick.resolve({ assets: [{ uri: 'file:///picker/unknown-failure.jpg', type: 'image/jpeg' }] }); await settle();
  const outcomes = app.calls.filter(call => call[0] === 'outcome');
  assert.equal(outcomes.length, 1); assert.equal(outcomes[0][1].status, 'failed');
  assert.equal(app.detail.room.avatar_version, 1); assert.equal(app.lateWrites, 0);
});

test('late detail and candidate reads cannot update an unmounted sheet or a replaced engine with the same actor IDs', async () => {
  const detailApp = management(); const detailWait = deferred(); detailApp.props.engine.groupInfo = () => detailWait.promise;
  detailApp.render(); detailApp.close(); detailWait.resolve(copy(detailApp.detail)); await settle(); assert.equal(detailApp.lateWrites, 0);
  const app = management(); await app.ready(); const candidateWait = deferred();
  app.props.engine.candidates = () => candidateWait.promise;
  one(app.render(), 'Field', p => p.accessibilityLabel === 'search').onChangeText('query'); app.render(); app.expire(); await settle();
  app.props.engine = { ...app.props.engine, groupInfo: () => new Promise(() => {}) };
  app.render(); candidateWait.resolve({ users: [{ user_id: 44, name: 'Old engine candidate' }] }); await settle();
  assert.equal(nodes(app.render()).some(node => node.props.accessibilityLabel === 'add: Old engine candidate'), false);
  const closed = management(); await closed.ready(); const late = deferred(); closed.props.engine.candidates = () => late.promise;
  one(closed.render(), 'Field', p => p.accessibilityLabel === 'search').onChangeText('pending'); closed.render(); closed.expire(); await settle();
  closed.close(); late.resolve({ users: [{ user_id: 45, name: 'Closed candidate' }] }); await settle(); assert.equal(closed.lateWrites, 0);
  const revoked = management(); await revoked.ready(); const revokedWait = deferred(); revoked.props.engine.candidates = () => revokedWait.promise;
  one(revoked.render(), 'Field', p => p.accessibilityLabel === 'search').onChangeText('before revoke'); revoked.render(); revoked.expire(); await settle();
  revoked.props.engine.rooms = () => []; revokedWait.resolve({ users: [{ user_id: 46, name: 'Revoked candidate' }] }); await settle();
  assert.equal(nodes(revoked.render()).some(node => node.props.accessibilityLabel === 'add: Revoked candidate'), false);
});

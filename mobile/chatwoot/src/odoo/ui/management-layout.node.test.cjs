/** Actual ManagementSheet execution with React/native seams, not a device or backend test. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

function hooks() {
  const slots = [];
  let index = 0, dirty = false, effects = [];
  return {
    react: {
      useState(initial) {
        const at = index++;
        if (!(at in slots)) slots[at] = typeof initial === 'function' ? initial() : initial;
        return [slots[at], value => { const next = typeof value === 'function' ? value(slots[at]) : value;
          if (!Object.is(next, slots[at])) { slots[at] = next; dirty = true; } }];
      },
      useEffect(callback, deps) {
        const at = index++;
        if (!slots[at] || deps.some((value, i) => value !== slots[at].deps[i])) effects.push(() => {
          slots[at]?.cleanup?.(); slots[at] = { deps, cleanup: callback() };
        });
      },
    },
    render(component) {
      for (let pass = 0; pass < 10; pass++) {
        index = 0; dirty = false; effects = [];
        const tree = component(); for (const effect of effects) effect();
        if (!dirty) return tree;
      }
      throw new Error('Synthetic render did not settle');
    },
  };
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function one(tree, type, predicate = () => true) {
  const matches = nodes(tree).filter(node => node.type === type && predicate(node.props));
  assert.equal(matches.length, 1, `${type} expected unique match`);
  return matches[0].props;
}
const copy = value => JSON.parse(JSON.stringify(value));
async function settled() { for (let i = 0; i < 15; i++) await Promise.resolve(); }

function harness(manage = true) {
  const state = hooks(), timers = new Map(), calls = [], alerts = [];
  let nextTimer = 0, deferred = null, release;
  const detail = { can_manage: manage, members: [
    { user_id: 7, name: 'Current admin', is_admin: true },
    { user_id: 8, name: 'اسم عضو طويل للاختبار يحافظ على مرونة عرض الاسم', is_admin: false },
    { user_id: 9, name: 'Another admin', is_admin: true },
  ] };
  const engine = { identity: { user_id: 7 },
    groupInfo: async () => detail,
    candidates: async () => ({ users: [
      { user_id: 8, name: detail.members[1]?.name ?? 'Already member' },
      { user_id: 10, name: 'Candidate with a long display name' },
    ] }),
    groupChange: async (room, payload) => {
      calls.push({ room, payload: copy(payload) });
      if (deferred === payload.action) await new Promise(resolve => { release = resolve; });
      if (payload.action === 'promote_admin' || payload.action === 'demote_admin') {
        detail.members = detail.members.map(member => member.user_id === payload.user_id
          ? { ...member, is_admin: payload.action === 'promote_admin' } : member);
      }
      if (payload.action === 'remove_member') detail.members = detail.members.filter(member => member.user_id !== payload.user_id);
    },
  };
  const props = { mode: 'members', companyId: 1, room: { id: 4, company_id: 1, membership_id: 12, name: 'Synthetic group' },
    engine, language: 'ar', t: key => key, close: () => calls.push('close'), changed: async () => { calls.push('changed'); } };
  const element = (type, props) => ({ type, props: props || {} });
  const modules = { react: state.react, 'react/jsx-runtime': { jsx: element, jsxs: element, Fragment: 'Fragment' },
    'react-native': { View: 'View', Text: 'Text', Pressable: 'Pressable', Switch: 'Switch', Alert: { alert: (title, message, buttons) => alerts.push({ title, message, buttons }) } },
    './components': { Button: 'Button', Field: 'Field', Icon: 'Icon', IconButton: 'IconButton', Label: 'Label', Sheet: 'Sheet',
      colors: { pale: 'pale', blue: 'blue', border: 'border', danger: 'danger' }, direction: language => ({ textAlign: language === 'ar' ? 'right' : 'left' }),
      styles: { row: { flexDirection: 'row', flexWrap: 'wrap' }, card: { cardMarker: true }, listRow: {}, text: {}, muted: {}, fill: { flex: 1 } } },
    './dictionary': { errorWord: () => 'error' },
  };
  const source = readFileSync(join(__dirname, 'ManagementSheet.tsx'), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => modules[name] ?? {},
    setTimeout: callback => { const id = ++nextTimer; timers.set(id, callback); return id; }, clearTimeout: id => timers.delete(id) }, { filename: 'ManagementSheet.tsx' });
  return { props, calls, alerts, detail, render: () => state.render(() => module.exports.ManagementSheet(props)),
    async load() { for (const [id, callback] of [...timers]) { timers.delete(id); await callback(); } },
    defer(action) { deferred = action; }, release() { release(); },
  };
}
async function ready(manage = true) { const app = harness(manage); app.render(); await app.load(); app.render(); return app; }
function row(tree, id) { return nodes(tree).find(node => node.type === 'View' && node.props.testID === `group-member-${id}`); }
function more(tree, id) { return one(row(tree, id), 'IconButton', p => p.icon === 'more'); }
const actions = tree => nodes(tree).filter(node => node.type === 'Button' && ['remove', 'makeAdmin', 'demote'].includes(node.props.title));

test('member layout is compact with flexible accessible names, 36px initials and inline rename/save', async () => {
  const app = await ready(); const tree = app.render();
  assert.equal(one(tree, 'Sheet').compact, true); assert.equal(one(tree, 'Sheet').language, 'ar');
  const name = one(tree, 'Field', p => p.accessibilityLabel === 'name');
  assert.equal(name.maxLength, 100); assert.equal(name.style.flex, 1); assert.equal(name.style.minWidth, 0); assert.equal(name.style.minHeight, 44);
  assert.ok(one(tree, 'IconButton', p => p.icon === 'check'));
  assert.equal(nodes(tree).some(node => node.props.style?.cardMarker), false);
  for (const member of app.detail.members) {
    const memberRow = row(tree, member.user_id);
    assert.equal(memberRow.props.style.borderBottomWidth, 1);
    assert.equal(memberRow.props.style.paddingVertical, 4);
    const label = one(memberRow, 'Text', p => p.accessibilityLabel === member.name);
    assert.equal(label.numberOfLines, 2);
    const flexibleName = nodes(memberRow).find(node => node.type === 'View' && node.props.style?.flex === 1);
    assert.equal(flexibleName.props.style.minWidth, 0);
    assert.ok(nodes(memberRow).some(node => node.type === 'View' && node.props.style?.width === 36 && node.props.style?.height === 36));
  }
  assert.equal(nodes(row(tree, 7)).some(node => node.type === 'IconButton'), false, 'self has no admin action toggle');
  assert.equal(actions(tree).length, 0, 'administrative buttons do not consume every member row');
});

test('only one manageable non-self member expands actions; admin status determines the existing action', async () => {
  const app = await ready();
  more(app.render(), 8).onPress();
  let tree = app.render();
  assert.deepEqual(actions(tree).map(node => node.props.title), ['remove', 'makeAdmin']);
  assert.ok(actions(tree).every(node => node.props.accessibilityLabel.endsWith(app.detail.members[1].name)));
  more(tree, 9).onPress(); tree = app.render();
  assert.equal(actions(row(tree, 8)).length, 0);
  assert.deepEqual(actions(row(tree, 9)).map(node => node.props.title), ['remove', 'demote']);
  more(tree, 9).onPress(); assert.equal(actions(app.render()).length, 0);
});

test('rename, promote, demote, remove and add preserve exact groupChange payloads and room identity', async () => {
  const app = await ready();
  one(app.render(), 'Field', p => p.accessibilityLabel === 'name').onChangeText('  Updated group  ');
  one(app.render(), 'IconButton', p => p.icon === 'check').onPress(); await settled();
  more(app.render(), 8).onPress();
  one(app.render(), 'Button', p => p.title === 'makeAdmin').onPress(); await settled();
  one(app.render(), 'Button', p => p.title === 'demote').onPress(); await settled();
  one(app.render(), 'Button', p => p.title === 'remove').onPress(); await settled();
  const candidate = one(app.render(), 'Pressable', p => p.accessibilityLabel === 'add: Candidate with a long display name');
  const style = candidate.style[0];
  assert.equal(style.minHeight, 48); assert.equal(style.flexDirection, 'row-reverse');
  const candidateTree = nodes(app.render()).find(node => node.type === 'Pressable' && node.props.accessibilityLabel === candidate.accessibilityLabel);
  assert.ok(nodes(candidateTree).some(node => node.type === 'Icon' && node.props.icon === 'plus'));
  assert.ok(nodes(candidateTree).some(node => node.type === 'Text' && node.props.children === 'add'));
  candidate.onPress(); await settled();
  const requests = app.calls.filter(call => typeof call === 'object');
  assert.deepEqual(requests.map(call => call.payload), [
    { action: 'rename', name: '  Updated group  ' }, { action: 'promote_admin', user_id: 8 },
    { action: 'demote_admin', user_id: 8 }, { action: 'remove_member', user_id: 8 }, { action: 'add_member', user_id: 10 },
  ]);
  assert.ok(requests.every(call => call.room === app.props.room));
});

test('non-managers have no rename, add or member-action path; busy state disables existing controls', async () => {
  const readOnly = await ready(false); const locked = readOnly.render();
  assert.ok(nodes(locked).some(node => node.type === 'Label' && node.props.children === readOnly.props.room.name));
  assert.equal(nodes(locked).some(node => node.type === 'IconButton'), false);
  assert.equal(nodes(locked).some(node => node.type === 'Field'), false);
  assert.equal(actions(locked).length, 0);
  const app = await ready(); more(app.render(), 8).onPress(); app.defer('promote_admin');
  one(app.render(), 'Button', p => p.title === 'makeAdmin').onPress(); await settled();
  const busy = app.render();
  assert.ok(actions(busy).every(node => node.props.disabled));
  assert.equal(more(busy, 8).disabled, true);
  assert.equal(one(busy, 'IconButton', p => p.icon === 'check').disabled, true);
  assert.equal(one(busy, 'Pressable', p => p.accessibilityLabel === 'leave').disabled, true);
  app.release(); await settled();
  assert.equal(more(app.render(), 8).disabled, false);
});

test('leave remains a 48px danger action with the original confirmation and exact leave payload', async () => {
  const app = await ready();
  const leave = one(app.render(), 'Pressable', p => p.accessibilityLabel === 'leave');
  assert.equal(leave.style.minHeight, 48);
  leave.onPress();
  assert.equal(app.calls.length, 0);
  assert.equal(app.alerts[0].title, 'leave'); assert.equal(app.alerts[0].message, 'confirmLeave');
  assert.equal(app.alerts[0].buttons[0].style, 'cancel');
  app.alerts[0].buttons.find(button => button.style === 'destructive').onPress(); await settled();
  assert.deepEqual(app.calls.find(call => typeof call === 'object').payload, { action: 'leave' });
  assert.ok(app.calls.includes('changed') && app.calls.includes('close'));
});

test('expanded member actions reset on room scope changes and stay behind the current can_manage result', async () => {
  const app = await ready(); more(app.render(), 8).onPress();
  assert.equal(actions(app.render()).length, 2);
  app.props.room = { ...app.props.room, id: 5, membership_id: 13 };
  assert.equal(actions(app.render()).length, 0);
  app.detail.can_manage = false; await app.load();
  assert.equal(actions(app.render()).length, 0);
  assert.equal(nodes(app.render()).some(node => node.type === 'IconButton' && node.props.icon === 'more'), false);
});

test('actual central Sheet opts into compact RTL/LTR header and 44px close target without changing legacy layout', () => {
  const element = (type, props) => ({ type, props: props || {} });
  const offsets = [];
  const native = { StyleSheet: { create: value => value }, Platform: { OS: 'android' } };
  for (const name of ['ActivityIndicator', 'KeyboardAvoidingView', 'Modal', 'Pressable', 'ScrollView', 'Text', 'TextInput', 'View']) native[name] = name;
  const modules = { react: { forwardRef: component => component, useState: () => [0, value => offsets.push(value)], useRef: value => ({ current: value }) },
    'react/jsx-runtime': { jsx: element, jsxs: element, Fragment: 'Fragment' }, 'react-native': native,
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' },
    'react-native-svg': { __esModule: true, default: 'Svg', Path: 'Path' } };
  const source = readFileSync(join(__dirname, 'components.tsx'), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => modules[name] ?? {} }, { filename: 'components.tsx' });
  const components = module.exports;
  let closed = 0;
  const props = { title: 'Synthetic', t: key => key, close: () => { closed++; } };
  const legacy = components.Sheet(props);
  assert.equal(one(legacy, 'ScrollView').contentContainerStyle.gap, 14);
  assert.equal(nodes(legacy).some(node => node.type === components.IconButton), false);
  assert.ok(one(legacy, components.Button));
  for (const language of ['ar', 'en']) {
    const compact = components.Sheet({ ...props, compact: true, language });
    const keyboard = one(compact, 'KeyboardAvoidingView');
    assert.equal(keyboard.behavior, 'height');
    assert.equal(keyboard.style.flex, 1);
    assert.equal(one(compact, 'ScrollView').style.flexShrink, 1);
    assert.ok(nodes(compact).some(node => node.props.onLayout && node.props.collapsable === false), 'modal-local offset is measured');
    const frame = one(compact, 'View', p => p.onLayout && p.collapsable === false);
    const callbacks = [];
    frame.ref.current = { measureInWindow: callback => callbacks.push(callback) };
    const before = offsets.length;
    frame.onLayout(); frame.onLayout();
    callbacks[0](0, 99);
    assert.equal(offsets.length, before, 'stale measure ignored');
    callbacks[1](0, 40);
    assert.equal(offsets.at(-1), 40, 'offset uses modal window coordinates');
    frame.ref.current = null; callbacks[1](0, 88);
    assert.equal(offsets.at(-1), 40, 'unmounted frame ignored');
    assert.equal(one(compact, 'ScrollView').contentContainerStyle.gap, 8);
    const closeNode = nodes(compact).find(node => node.type === components.IconButton);
    assert.equal(closeNode.props.icon, 'close');
    const header = nodes(compact).find(node => node.type === 'View' && Array.isArray(node.props.children) && node.props.children.includes(closeNode));
    assert.equal(header.props.style.flexDirection, language === 'ar' ? 'row-reverse' : 'row');
    assert.equal(header.props.style.direction, 'ltr');
    const target = one(components.IconButton(closeNode.props), 'Pressable');
    assert.equal(target.style({ pressed: false })[0].minHeight, 44);
    assert.equal(target.style({ pressed: false })[0].minWidth, 44);
    target.onPress();
  }
  assert.equal(closed, 2);
  assert.equal(one(components.Sheet(props), 'ScrollView').contentContainerStyle.gap, 14);
});

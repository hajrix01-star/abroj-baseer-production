/** Actual SessionApp/NavigationDrawer execution with React/native seams, not device rendering QA. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

function hookState() {
  const slots = [];
  let index = 0, dirty = false, effects = [];
  const changed = (old, next) => !old || next.some((value, at) => value !== old[at]);
  const react = {
    useState(initial) {
      const at = index++;
      if (!(at in slots)) slots[at] = typeof initial === 'function' ? initial() : initial;
      return [slots[at], value => {
        const next = typeof value === 'function' ? value(slots[at]) : value;
        if (!Object.is(next, slots[at])) { dirty = true; slots[at] = next; }
      }];
    },
    useRef(value) { const at = index++; return slots[at] ?? (slots[at] = { current: value }); },
    useCallback(callback, deps) {
      const at = index++;
      if (changed(slots[at]?.deps, deps)) slots[at] = { deps, callback };
      return slots[at].callback;
    },
    useEffect(callback, deps) {
      const at = index++;
      if (changed(slots[at]?.deps, deps)) effects.push(() => {
        slots[at]?.cleanup?.(); slots[at] = { deps, cleanup: callback() };
      });
    },
  };
  return { react, render(component) {
    let tree;
    for (let pass = 0; pass < 10; pass++) {
      dirty = false; index = 0; effects = []; tree = component();
      for (const effect of effects) effect();
      if (!dirty) return tree;
    }
    throw new Error('Synthetic render did not settle');
  } };
}
const jsx = { jsx: (type, props) => ({ type, props: props || {} }), jsxs: (type, props) => ({ type, props: props || {} }), Fragment: 'Fragment' };
function load(relative, modules, globals = {}) {
  const source = readFileSync(join(__dirname, relative), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => modules[name] ?? {}, console, ...globals }, { filename: relative });
  return module.exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  // Render the real stateless MenuRow so accessibility/disabled props are asserted on Pressable.
  if (typeof tree.type === 'function' && tree.type.name === 'MenuRow') return nodes(tree.type(tree.props));
  return [tree, ...nodes(tree.props?.children)];
}
function one(tree, type, predicate = () => true) {
  const matches = nodes(tree).filter(node => node.type === type && predicate(node.props));
  assert.equal(matches.length, 1, `${type} expected unique match`);
  return matches[0].props;
}
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree !== 'object') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join(' ');
  return text(tree.props?.children);
}
const components = { Button: 'Button', Icon: 'Icon', IconButton: 'IconButton', Label: 'Label',
  direction: () => ({}), styles: { page: {}, header: {}, row: {}, title: {}, fill: { flex: 1 }, muted: {}, text: {}, banner: {} },
  colors: { white: 'white', pale: 'pale', danger: 'danger', blue: 'blue', ink: 'ink', border: 'border' } };
const dictionary = load('dictionary.ts', {});
const names = load('companyNames.ts', {});
const viewModel = load('viewModel.ts', {});
function identity(uid = 7) {
  return { api_version: 2, database: 'synthetic', user_id: uid, company_ids: [1], current_company_id: 1,
    permissions: { chat_view: true, chat_send: true, media: true, group_create: true },
    mobile_policy: [{ company_id: 1, direct_enabled: true, can_manage: true }],
    profile: { name: `Private user ${uid}`, companies: [
      { id: 1, name: 'Authorized fallback', name_ar: 'الشركة المصرح بها', name_en: 'Authorized company' },
      { id: 99, name_ar: 'شركة محجوبة', name_en: 'Hidden company' },
    ] } };
}
function appState() {
  const callbacks = new Set();
  return { currentState: 'active', addEventListener(_event, callback) { callbacks.add(callback); return { remove() { callbacks.delete(callback); } }; },
    change(value) { this.currentState = value; for (const callback of [...callbacks]) callback(value); } };
}
function drawer() {
  const state = hookState(), nativeApp = appState(), events = [];
  const props = { visible: true, identity: identity(), language: 'ar', t: dictionary.translator('ar'),
    offline: false, pendingCount: 5, busy: false, canManage: true,
    close: () => events.push('close'), onAction: action => events.push(action) };
  const module = load('NavigationDrawer.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { AppState: nativeApp, Modal: 'Modal', Pressable: 'Pressable', ScrollView: 'ScrollView', Text: 'Text', View: 'View', useWindowDimensions: () => ({ width: 320 }) },
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' }, './companyNames': names, './components': components, './VersionLabel': { VersionLabel: 'VersionLabel' } });
  return { props, events, nativeApp, render: () => state.render(() => module.NavigationDrawer(props)) };
}
function session() {
  const state = hookState(), nativeApp = appState(), calls = [], alerts = [], frames = [];
  let width = 320, back;
  const chat = { identity: identity(), presentationReady: true, selected: null, offline: false, busy: false,
    pending: [], rooms: [], error: null, select: async room => { calls.push(['select', room]); },
    sync: async () => { calls.push('sync'); }, logout: async () => { calls.push('logout'); }, capture() {} };
  const module = load('../OdooTrialApp.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { Alert: { alert: (title, message, buttons) => alerts.push({ title, message, buttons }) }, AppState: nativeApp,
      BackHandler: { addEventListener(_event, callback) { back = callback; return { remove() { back = undefined; } }; } },
      Text: 'Text', View: 'View', useWindowDimensions: () => ({ width }) },
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView', SafeAreaProvider: 'SafeAreaProvider' },
    './ui/components': components, './ui/dictionary': dictionary, './ui/useChat': { useChat: () => chat }, './ui/viewModel': viewModel,
    './ui/LoginScreen': { LoginScreen: 'LoginScreen' }, './ui/ManagementSheet': { ManagementSheet: 'ManagementSheet' },
    './ui/RoomsScreen': { RoomsScreen: 'RoomsScreen' }, './ui/TimelineScreen': { TimelineScreen: 'TimelineScreen' },
    './ui/VersionLabel': { VersionLabel: 'VersionLabel' }, './ui/NavigationDrawer': { NavigationDrawer: 'NavigationDrawer' },
  }, { requestAnimationFrame: callback => { frames.push(callback); return frames.length; } });
  assert.equal(typeof module.SessionApp, 'function', 'test uses the actual named SessionApp export');
  return { chat, calls, alerts, nativeApp, render: () => state.render(() => module.SessionApp({ engine: {} })),
    width(value) { width = value; }, back() { return back?.(); }, flushFrames() { for (const frame of frames.splice(0)) frame(); } };
}

test('drawer never renders a masked identity and profile lists only authorized company metadata', () => {
  const app = drawer(); app.props.identity = null;
  assert.equal(app.render(), null);
  app.props.identity = identity(); app.props.visible = false;
  assert.equal(app.render(), null);
  app.props.visible = true;
  one(app.render(), 'Pressable', p => p.accessibilityLabel === app.props.t('profile')).onPress();
  const profile = app.render();
  assert.ok(text(profile).includes('Private user 7'));
  assert.ok(text(profile).includes('الشركة المصرح بها'));
  assert.equal(text(profile).includes('شركة محجوبة'), false);
  assert.ok(text(profile).includes('7'));
  assert.equal(one(profile, 'ScrollView').style.flex, 1);
  one(profile, 'Modal').onRequestClose();
  assert.ok(nodes(app.render()).some(node => node.type === 'Pressable' && node.props.accessibilityLabel === app.props.t('profile')));
});

test('drawer settings route language/actions, respect busy/offline policy, and close on background/backdrop', () => {
  const app = drawer();
  one(app.render(), 'Pressable', p => p.accessibilityLabel === app.props.t('settings')).onPress();
  let settings = app.render();
  one(settings, 'Pressable', p => p.accessibilityLabel === 'English').onPress();
  one(settings, 'Pressable', p => p.accessibilityLabel === 'العربية').onPress();
  assert.deepEqual(app.events, ['en', 'ar']);
  one(settings, 'Pressable', p => p.accessibilityLabel === app.props.t('policy')).onPress();
  assert.equal(app.events.at(-1), 'policy');
  app.props.offline = true; settings = app.render();
  assert.equal(one(settings, 'Pressable', p => p.accessibilityLabel === app.props.t('policy')).disabled, true);
  app.props.busy = true; settings = app.render();
  assert.equal(one(settings, 'Pressable', p => p.accessibilityLabel === app.props.t('refresh')).disabled, true);
  assert.equal(one(settings, 'Pressable', p => p.accessibilityLabel === app.props.t('logout')).disabled, true);
  one(settings, 'Pressable', p => p.accessibilityLabel === app.props.t('close')).onPress();
  assert.equal(app.events.at(-1), 'close');
  app.nativeApp.change('background');
  assert.equal(app.events.filter(event => event === 'close').length, 2);
});

test('SessionApp masks profile/menu and all retained conversation content while presentation is blocked', () => {
  const app = session(); app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
  const ready = app.render();
  const oldOpen = one(ready, 'TimelineScreen').onMenu;
  const oldAction = one(ready, 'NavigationDrawer').onAction;
  app.chat.presentationReady = false;
  let blocked = app.render();
  assert.equal(one(blocked, 'NavigationDrawer').identity, null);
  assert.equal(one(blocked, 'NavigationDrawer').visible, false);
  assert.equal(nodes(blocked).some(node => ['RoomsScreen', 'TimelineScreen', 'ManagementSheet'].includes(node.type)), false);
  assert.equal(text(blocked).includes('Private user 7'), false);
  oldOpen(); oldAction('en'); oldAction('refresh'); oldAction('logout');
  blocked = app.render();
  assert.equal(one(blocked, 'NavigationDrawer').visible, false);
  assert.equal(one(blocked, 'NavigationDrawer').language, 'ar');
  assert.deepEqual(app.calls, []);
});

test('selected phone conversation hides duplicate app header and opens its own menu; wide layout retains list/header', () => {
  const app = session();
  let tree = app.render();
  assert.ok(text(tree).includes(dictionary.translator('ar')('app')));
  app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
  tree = app.render();
  assert.equal(text(tree).includes(dictionary.translator('ar')('app')), false);
  assert.equal(nodes(tree).some(node => node.type === 'RoomsScreen'), false);
  one(tree, 'TimelineScreen').onMenu();
  tree = app.render();
  assert.equal(one(tree, 'NavigationDrawer').visible, true);
  app.back();
  assert.equal(one(app.render(), 'NavigationDrawer').visible, false);
  assert.equal(app.calls.length, 0, 'first Android back closes menu, not conversation');
  app.back();
  assert.equal(app.calls[0][0], 'select'); assert.equal(app.calls[0][1], null);
  app.width(900); tree = app.render();
  assert.ok(text(tree).includes(dictionary.translator('ar')('app')));
  assert.ok(one(tree, 'RoomsScreen'));
  assert.equal(one(tree, 'TimelineScreen').onMenu, undefined);
});

test('SessionApp routes current-scope language, refresh and policy actions and invalidates scheduled old policy', () => {
  const app = session();
  let tree = app.render();
  one(tree, 'IconButton', p => p.icon === 'menu').onPress();
  tree = app.render();
  assert.equal(one(tree, 'NavigationDrawer').visible, true);
  one(tree, 'NavigationDrawer').onAction('en');
  tree = app.render();
  assert.equal(one(tree, 'RoomsScreen').language, 'en');
  one(tree, 'NavigationDrawer').onAction('refresh');
  assert.ok(app.calls.includes('sync'));
  one(app.render(), 'NavigationDrawer').onAction('policy'); app.flushFrames();
  assert.equal(one(app.render(), 'ManagementSheet').mode, 'policy');
  one(app.render(), 'ManagementSheet').close();
  const previousAction = one(app.render(), 'NavigationDrawer').onAction;
  previousAction('policy'); app.chat.identity = identity(8); app.render(); app.flushFrames();
  assert.equal(nodes(app.render()).some(node => node.type === 'ManagementSheet'), false);
  previousAction('ar');
  assert.equal(one(app.render(), 'NavigationDrawer').language, 'en');
});

test('logout requires pending-message confirmation, and a stale confirmation cannot log out a newer identity', () => {
  const app = session(); app.chat.pending = [{ client_uuid: 'synthetic' }];
  one(app.render(), 'NavigationDrawer').onAction('logout');
  assert.equal(app.calls.includes('logout'), false);
  assert.equal(app.alerts.length, 1);
  assert.equal(app.alerts[0].message, dictionary.translator('ar')('pendingWarning'));
  assert.ok(app.alerts[0].buttons.some(button => button.style === 'cancel'));
  const staleConfirm = app.alerts[0].buttons.find(button => button.style === 'destructive').onPress;
  app.chat.identity = identity(8); app.render(); staleConfirm();
  assert.equal(app.calls.includes('logout'), false);
  one(app.render(), 'NavigationDrawer').onAction('logout');
  app.alerts[1].buttons.find(button => button.style === 'destructive').onPress();
  assert.equal(app.calls.filter(call => call === 'logout').length, 1);
});

test('background closes an open SessionApp drawer and management page without invoking remote actions', () => {
  const app = session();
  one(app.render(), 'IconButton', p => p.icon === 'menu').onPress();
  assert.equal(one(app.render(), 'NavigationDrawer').visible, true);
  app.nativeApp.change('background');
  const tree = app.render();
  assert.equal(one(tree, 'NavigationDrawer').visible, false);
  assert.equal(nodes(tree).some(node => node.type === 'ManagementSheet'), false);
  assert.deepEqual(app.calls, []);
});

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
const jsx = { jsx: (type, props, key) => ({ type, key, props: props || {} }), jsxs: (type, props, key) => ({ type, key, props: props || {} }), Fragment: 'Fragment' };
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
const ordersDictionary = load('../orders/dictionary.ts', {});
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
function drawer(width = 320) {
  const state = hookState(), nativeApp = appState(), events = [];
  const props = { visible: true, identity: identity(), language: 'ar', t: dictionary.translator('ar'),
    offline: false, pendingCount: 5, busy: false, canManage: true,
    close: () => events.push('close'), onAction: action => events.push(action) };
  const module = load('NavigationDrawer.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { AppState: nativeApp, Modal: 'Modal', Pressable: 'Pressable', ScrollView: 'ScrollView', Switch: 'Switch', Text: 'Text', View: 'View', useWindowDimensions: () => ({ width }) },
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' }, './companyNames': names, './components': components, './VersionLabel': { VersionLabel: 'VersionLabel' }, './Brand': { Brand: 'Brand' } });
  return { props, events, nativeApp, render: () => state.render(() => module.NavigationDrawer(props)) };
}
function session() {
  const state = hookState(), nativeApp = appState(), calls = [], alerts = [], frames = [];
  let width = 320; const backHandlers = new Set();
  const chat = { identity: identity(), presentationReady: true, selected: null, offline: false, busy: false,
    pending: [], rooms: [], error: null, select: async room => { calls.push(['select', room]); },
    sync: async () => { calls.push('sync'); }, logout: async () => { calls.push('logout'); }, capture() {} };
  const engine = { accountScope: 'synthetic-actor/epoch:1', get identity() { return chat.identity; }, rooms: () => chat.rooms };
  const module = load('../OdooTrialApp.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { Alert: { alert: (title, message, buttons) => alerts.push({ title, message, buttons }) }, AppState: nativeApp,
      BackHandler: { addEventListener(_event, callback) { backHandlers.add(callback); return { remove() { backHandlers.delete(callback); } }; } },
      Keyboard: { dismiss: () => calls.push('dismiss-keyboard') },
      Text: 'Text', View: 'View', useWindowDimensions: () => ({ width }) },
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView', SafeAreaProvider: 'SafeAreaProvider' },
    './ui/components': components, './ui/dictionary': dictionary, './ui/useChat': { useChat: () => chat }, './ui/viewModel': viewModel,
    './orders/dictionary': ordersDictionary, './orders/ui/OrdersScreen': { OrdersScreen: 'OrdersScreen' },
    './tasks/dictionary': { taskTranslator: language => word => `${language}:${word}` }, './tasks/ui/TasksScreen': { TasksScreen: 'TasksScreen' },
    './leadership/ui/LeadershipScreen': { LeadershipScreen: 'LeadershipScreen' },
    './session/OrdersOnlyShell': { OrdersOnlyShell: 'OrdersOnlyShell' },
    './runtime': { getEngine: () => engine, getOrdersEngine: () => ({}), getTasksEngine: () => ({}), getLeadershipEngine: () => ({}), ordersOnlySnapshot: () => ({ identity: null, verified: false, generation: 0, revision: 0 }),
      subscribeOrdersOnlySession: () => () => {}, refreshOrdersOnlySession: async () => {}, setOrdersConnectivity() {} },
    './ui/LoginScreen': { LoginScreen: 'LoginScreen' }, './ui/ManagementSheet': { ManagementSheet: 'ManagementSheet' },
    './ui/RoomsScreen': { RoomsScreen: 'RoomsScreen' }, './ui/TimelineScreen': { TimelineScreen: 'TimelineScreen' },
    './ui/VersionLabel': { VersionLabel: 'VersionLabel' }, './ui/NavigationDrawer': { NavigationDrawer: 'NavigationDrawer' },
    './ui/Brand': { Brand: 'Brand' },
    './ui/CompanySelector': { CompanySelector: 'CompanySelector' },
  }, { requestAnimationFrame: callback => { frames.push(callback); return frames.length; } });
  assert.equal(typeof module.SessionApp, 'function', 'test uses the actual named SessionApp export');
  return { engine, chat, calls, alerts, nativeApp, render: () => state.render(() => module.SessionApp({ engine })),
    width(value) { width = value; }, back() { for (const callback of [...backHandlers].reverse()) if (callback()) return true; return false; }, flushFrames() { for (const frame of frames.splice(0)) frame(); } };
}

test('Chats is the first authorized drawer section and opens the inbox from every workspace in either language', () => {
  for (const language of ['ar', 'en']) {
    const panel = drawer(320); panel.props.language = language; panel.props.t = dictionary.translator(language);
    panel.props.onChats = () => panel.events.push('chats');
    panel.props.onOrders = () => {}; panel.props.ordersLabel = 'Orders';
    panel.props.onTasks = () => {}; panel.props.tasksLabel = 'Tasks';
    panel.props.onLeadership = () => {}; panel.props.leadershipLabel = 'Leadership';
    const entries = nodes(one(panel.render(), 'ScrollView').children).filter(n => n.type === 'Pressable');
    assert.equal(entries[0].props.accessibilityLabel, panel.props.t('rooms'));
    entries[0].props.onPress(); assert.equal(panel.events.at(-1), 'chats');
    panel.props.identity.permissions.chat_view = false;
    assert.equal(nodes(panel.render()).some(n => n.type === 'Pressable' && n.props.accessibilityLabel === panel.props.t('rooms')), false);

    const app = session();
    if (language === 'en') one(app.render(), 'NavigationDrawer').onAction('en');
    Object.assign(app.chat.identity.permissions, { order_view: true, task_view: true, dashboard_view: true });
    assert.equal(one(app.render(), 'View', p => p.testID === 'chat-workspace').style.at(-1).display, 'flex', 'cold start defaults to chat');
    for (const section of ['Orders', 'Tasks', 'Leadership']) {
      one(app.render(), 'NavigationDrawer')[`on${section}`]();
      assert.equal(one(app.render(), 'View', p => p.testID === 'chat-workspace').style.at(-1).display, 'none');
      app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
      one(app.render(), 'NavigationDrawer').onChats();
      assert.equal(one(app.render(), 'View', p => p.testID === 'chat-workspace').style.at(-1).display, 'flex');
      assert.deepEqual(app.calls.at(-1), ['select', null]);
      app.chat.selected = null;
    }
    const stale = one(app.render(), 'NavigationDrawer').onChats;
    app.chat.identity.permissions.chat_view = false; app.render();
    assert.equal(one(app.render(), 'NavigationDrawer').onChats, undefined);
    const before = app.calls.length; stale(); assert.equal(app.calls.length, before);
  }
});

test('dashboard navigation is separately granted, retained when hidden and revoked without touching chat', () => {
  const app = session();
  assert.equal(one(app.render(), 'NavigationDrawer').onLeadership, undefined);
  app.chat.identity.permissions.dashboard_view = true;
  one(app.render(), 'NavigationDrawer').onLeadership();
  let tree = app.render();
  assert.equal(one(tree, 'LeadershipScreen').presented, true);
  assert.equal(nodes(tree).filter(n => n.props?.testID === 'chat-workspace').length, 1);
  one(tree, 'LeadershipScreen').onBack(); tree = app.render();
  assert.equal(one(tree, 'LeadershipScreen').presented, false);
  one(tree, 'NavigationDrawer').onLeadership(); app.render();
  app.chat.identity.permissions.dashboard_view = false; tree = app.render();
  assert.equal(nodes(tree).filter(n => n.type === 'LeadershipScreen').length, 0);
  assert.equal(one(tree, 'NavigationDrawer').onLeadership, undefined);
  assert.equal(nodes(tree).filter(n => n.props?.testID === 'chat-workspace').length, 1);
});

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

test('compact drawer keeps brand on the toggle row and pins logout below the independently scrollable actions', () => {
  const app = drawer();
  const tree = app.render();
  const pane = one(tree, 'View', p => p.accessibilityViewIsModal);
  assert.equal(pane.style.width, 208);
  const toggle = nodes(tree).find(n => n.type === 'IconButton' && n.props.icon === 'menu');
  const heading = nodes(tree).find(n => Array.isArray(n.props?.children) && n.props.children.includes(toggle));
  assert.equal(nodes(heading).filter(n => n.type === 'Brand').length, 1);
  const scroll = nodes(tree).find(n => n.type === 'ScrollView');
  assert.equal(nodes(scroll).some(n => n.type === 'Brand'), false);
  for (const key of ['profile','settings','refresh']) {
    const action = one(scroll, 'Pressable', p => p.accessibilityLabel === app.props.t(key));
    const style = action.style({pressed:false})[0];
    assert.equal(style.minHeight, 48);
  }
  assert.equal(nodes(scroll).some(n => n.type === 'Pressable' && n.props.accessibilityLabel === app.props.t('logout')), false);
  assert.equal(nodes(scroll).some(n => n.type === 'VersionLabel'), false);
  const footer = nodes(tree).find(n => n.props?.testID === 'drawer-footer');
  assert.equal(footer.props.style.flexShrink, 0);
  assert.equal(one(footer, 'Pressable', p => p.accessibilityLabel === app.props.t('logout')).style({pressed:false})[0].minHeight, 48);
  assert.equal(nodes(footer).at(-1).type, 'VersionLabel');
  const paneChildren = pane.children.filter(Boolean);
  assert.equal(paneChildren.at(-2), scroll); assert.equal(paneChildren.at(-1), footer);
  const account = nodes(tree).find(n => n.type === 'View' && n.props.testID === 'drawer-account');
  assert.equal(account.props.style.flexDirection, 'row-reverse');
  assert.equal(one(account, 'Text', p => p.accessibilityLabel === app.props.identity.profile.name).numberOfLines, 2);
});

test('drawer uses 65 percent phone width without changing wide screen cap', () => {
  for (const [width, expected] of [[320, 208], [360, 234], [400, 260], [900, 304]]) {
    const app = drawer(width);
    for (const language of ['ar', 'en']) {
      app.props.language = language;
      assert.equal(one(app.render(), 'View', p => p.accessibilityViewIsModal).style.width, expected);
    }
  }
});

test('shell menu is first on its language edge and drawer keeps the same edge toggle', () => {
  const app = session(); const panel = drawer();
  for (const language of ['ar', 'en']) {
    if (language === 'en') one(app.render(), 'NavigationDrawer').onAction('en');
    panel.props.language = language; panel.props.t = dictionary.translator(language);
    const tree = app.render();
    const menu = nodes(tree).find(node => node.type === 'IconButton' && node.props.icon === 'menu');
    const header = nodes(tree).find(node => Array.isArray(node.props?.children) && node.props.children.includes(menu));
    assert.ok(header, 'toggle is a direct header child, not a trailing action wrapper');
    assert.equal(header.props.children.filter(Boolean)[0], menu);
    assert.equal(header.props.style.at(-1).flexDirection, language === 'ar' ? 'row-reverse' : 'row');
    assert.equal(header.props.style.at(-1).direction, 'ltr', 'physical edge independent of OS RTL');
    assert.equal(header.props.style.at(-1).paddingHorizontal, 8);
    const opened = panel.render();
    const toggle = nodes(opened).find(node => node.type === 'IconButton' && node.props.icon === 'menu');
    assert.ok(toggle, 'same hamburger remains at drawer edge when expanded');
    const heading = nodes(opened).find(node => Array.isArray(node.props?.children) && node.props.children.includes(toggle));
    assert.equal(heading.props.children.filter(Boolean)[0], toggle);
    assert.equal(heading.props.style.flexDirection, language === 'ar' ? 'row-reverse' : 'row');
    toggle.props.onPress(); assert.equal(panel.events.at(-1), 'close');
  }
});

test('orders shell entry uses explicit user rights and cannot unmount a selected frozen conversation', () => {
  const app = session();
  assert.equal(one(app.render(), 'NavigationDrawer').onOrders, undefined);
  app.chat.identity.permissions.order_view = true;
  const openOrders = one(app.render(), 'NavigationDrawer').onOrders;
  assert.equal(typeof openOrders, 'function'); openOrders();
  const orders = one(app.render(), 'OrdersScreen');
  assert.equal(orders.scopeKey, app.engine.accountScope); assert.equal(orders.online, true);
  assert.equal(orders.identity, app.chat.identity); assert.deepEqual(app.calls, ['dismiss-keyboard']);
  orders.onBack(); assert.ok(one(app.render(), 'RoomsScreen'));
  app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
  const before = app.render(); const selected = app.chat.selected;
  const timelineBefore = nodes(before).find(node => node.type === 'TimelineScreen');
  assert.equal(typeof one(before, 'NavigationDrawer').onOrders, 'function');
  openOrders(); assert.ok(one(app.render(), 'TimelineScreen'));
  assert.equal(nodes(app.render()).some(node => node.type === 'OrdersScreen'), false);
  assert.equal(app.calls.some(call => Array.isArray(call) && call[0] === 'select'), false, 'old menu action cannot reselect or load a room');
  const currentOpen = one(app.render(), 'NavigationDrawer').onOrders; currentOpen();
  const hidden = app.render();
  const timelineHidden = nodes(hidden).find(node => node.type === 'TimelineScreen');
  assert.equal(timelineHidden.type, timelineBefore.type); assert.equal(timelineHidden.key, timelineBefore.key);
  const path = (tree, target, prefix = '') => {
    if (tree === target) return prefix;
    if (!tree || typeof tree !== 'object') return null;
    const children = Array.isArray(tree) ? tree : [tree.props?.children];
    for (let i = 0; i < children.length; i++) { const found = path(children[i], target, `${prefix}/${i}`); if (found !== null) return found; }
    return null;
  };
  assert.equal(path(hidden, timelineHidden), path(before, timelineBefore), 'same type/key and sibling path preserves the mounted React subtree');
  assert.equal(timelineHidden.props.presented, false);
  const workspace = one(hidden, 'View', p => p.testID === 'chat-workspace');
  assert.equal(workspace.style.at(-1).display, 'none'); assert.equal(workspace.pointerEvents, 'none');
  assert.equal(workspace.importantForAccessibility, 'no-hide-descendants');
  assert.equal(app.chat.selected, selected);
  app.back(); const restored = app.render();
  assert.equal(one(restored, 'TimelineScreen').presented, true);
  assert.equal(app.chat.selected, selected);
  assert.equal(app.calls.some(call => Array.isArray(call) && call[0] === 'select'), false, 'Orders hardware back returns without clearing/reselecting the conversation');
  app.chat.selected = null; app.render();
  one(app.render(), 'NavigationDrawer').onOrders(); app.render();
  app.chat.presentationReady = false;
  assert.equal(nodes(app.render()).some(node => node.type === 'OrdersScreen'), false);
  app.chat.identity.permissions.order_view = false; app.chat.presentationReady = true;
  assert.equal(one(app.render(), 'NavigationDrawer').onOrders, undefined);
  assert.equal(nodes(app.render()).some(node => node.type === 'OrdersScreen'), false);
});

test('task navigation retains the frozen chat tree and uses independent rights in both languages', () => {
  for (const language of ['ar', 'en']) {
    const app = session();
    if (language === 'en') one(app.render(), 'NavigationDrawer').onAction('en');
    assert.equal(one(app.render(), 'NavigationDrawer').onTasks, undefined);
    app.chat.identity.permissions.task_view = true;
    app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
    one(app.render(), 'NavigationDrawer').onTasks();
    assert.equal(one(app.render(), 'TasksScreen').presented, true);
    assert.equal(one(app.render(), 'TimelineScreen').presented, false);
    assert.equal(one(app.render(), 'NavigationDrawer').onOrders, undefined);
    const staleBack = one(app.render(), 'TasksScreen').onBack;
    app.back(); app.render(); staleBack();
    assert.equal(one(app.render(), 'TasksScreen').presented, false);
    assert.equal(one(app.render(), 'TimelineScreen').presented, true);
    assert.equal(app.calls.some(call => Array.isArray(call) && call[0] === 'select'), false);
    app.chat.identity.permissions.task_view = false; app.render();
    assert.equal(one(app.render(), 'NavigationDrawer').onTasks, undefined);
    assert.equal(nodes(app.render()).some(node => node.type === 'TasksScreen'), false);
  }
});

test('unified Orders entry keeps the same label and permission guard for home and conversation in both languages', () => {
  for (const language of ['ar', 'en']) {
    const app = session(); app.chat.identity.permissions.order_view = true;
    if (language === 'en') one(app.render(), 'NavigationDrawer').onAction('en');
    const home = one(app.render(), 'NavigationDrawer');
    app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
    const conversation = one(app.render(), 'NavigationDrawer');
    assert.equal(home.ordersLabel, conversation.ordersLabel);
    assert.equal(typeof conversation.onOrders, 'function');
    const retained = conversation.onOrders;
    app.chat.identity.permissions.order_view = false; app.render(); retained();
    assert.equal(nodes(app.render()).some(n => n.type === 'OrdersScreen'), false);
    assert.equal(one(app.render(), 'NavigationDrawer').onOrders, undefined);
  }
});

test('orders and chat share the selected company; retained orders callbacks cannot change another area or actor', () => {
  const app = session(); app.chat.identity.permissions.order_view = true;
  one(app.render(), 'NavigationDrawer').onOrders();
  let orders = one(app.render(), 'OrdersScreen'); assert.equal(orders.selectedCompanyId, 0);
  orders.onCompanyChange(1); orders = one(app.render(), 'OrdersScreen');
  assert.equal(orders.selectedCompanyId, 1); orders.onCompanyChange(99);
  assert.equal(one(app.render(), 'OrdersScreen').selectedCompanyId, 1);
  const stale = orders.onCompanyChange; orders.onBack(); app.render(); stale(0);
  assert.equal(one(app.render(), 'RoomsScreen').companyId, 1);
  one(app.render(), 'NavigationDrawer').onOrders(); orders = one(app.render(), 'OrdersScreen');
  const oldActor = orders.onCompanyChange;
  app.engine.accountScope = 'new-actor/epoch:2'; app.chat.identity = identity(9); app.chat.identity.permissions.order_view = true;
  app.render(); oldActor(0); assert.equal(one(app.render(), 'OrdersScreen').selectedCompanyId, 1, 'old callback cannot alter the current authorized chat company filter');
});

test('Orders keeps authorized global policy settings without allowing hidden conversation management callbacks', () => {
  const app = session(); app.chat.identity.permissions.order_view = true;
  app.chat.selected = {id: 4, company_id: 1, membership_id: 9, is_group: true};
  const oldManage = one(app.render(), 'TimelineScreen').manage;
  one(app.render(), 'NavigationDrawer').onOrders(); app.render(); oldManage();
  assert.equal(nodes(app.render()).some(node => node.type === 'ManagementSheet'), false);
  one(app.render(), 'NavigationDrawer').onAction('policy'); app.flushFrames();
  one(app.render(), 'CompanySelector').onSelect(1);
  assert.equal(one(app.render(), 'ManagementSheet').mode, 'policy');
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

test('SessionApp retains a TTL-approved conversation during silent verification and covers background pixels without remounting it', () => {
  const app = session(); app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
  let tree = app.render(); const old = one(tree, 'TimelineScreen');
  app.chat.retainedDisplay = true; app.chat.displayReady = true; app.chat.presentationReady = false;
  tree = app.render();
  assert.equal(one(tree, 'TimelineScreen').chat.selected, old.chat.selected);
  assert.equal(one(tree, 'TimelineScreen').presented, false);
  assert.equal(nodes(tree).some(n => n.props.testID === 'session-privacy-cover'), false);
  assert.equal(nodes(tree).some(n => n.type === 'Label' && n.props.children === dictionary.translator('ar')('loading')), false);
  assert.equal(one(tree, 'NavigationDrawer').identity, null);
  const gate = one(tree, 'View', p => p.importantForAccessibility === 'no-hide-descendants' && p.pointerEvents === 'none');
  assert.equal(gate.accessibilityElementsHidden, true);
  old.onMenu(); old.manage(); tree = app.render();
  assert.equal(one(tree, 'NavigationDrawer').visible, false);
  assert.equal(nodes(tree).some(n => n.type === 'ManagementSheet'), false);
  app.nativeApp.change('background'); app.chat.displayReady = false; tree = app.render();
  assert.equal(one(tree, 'TimelineScreen').presented, false);
  const cover = one(tree, 'View', p => p.testID === 'session-privacy-cover');
  assert.equal(cover.style.backgroundColor, components.colors.white);
  assert.equal(cover.style.top, 0); assert.equal(cover.style.bottom, 0);
  assert.equal(cover.style.left, 0); assert.equal(cover.style.right, 0);
});

test('selected phone conversation hides duplicate app header and opens its own menu; wide layout retains list/header', () => {
  const app = session();
  let tree = app.render();
  assert.ok(nodes(tree).some(node => node.type === 'Brand'));
  app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
  tree = app.render();
  assert.equal(nodes(tree).some(node => node.type === 'Brand'), false);
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
  assert.ok(nodes(tree).some(node => node.type === 'Brand'));
  assert.ok(one(tree, 'RoomsScreen'));
  assert.equal(one(tree, 'TimelineScreen').onMenu, undefined);
});

test('online queue updates never insert a height-changing banner above an open conversation; offline warning remains', () => {
  const app = session();
  app.chat.selected = { id: 4, company_id: 1, membership_id: 9 };
  app.chat.pending = [{ client_uuid: 'test' }];
  assert.equal(text(app.render()).includes(dictionary.translator('ar')('queue')), false);
  app.chat.pending = [];
  assert.equal(text(app.render()).includes(dictionary.translator('ar')('queue')), false);
  app.chat.offline = true;
  assert.ok(text(app.render()).includes(dictionary.translator('ar')('offlineNote')));
  app.chat.offline = false; app.chat.selected = null; app.chat.pending = [{}];
  assert.ok(text(app.render()).includes(dictionary.translator('ar')('queue')));
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
  const picker = one(app.render(), 'CompanySelector');
  assert.equal(picker.pickerOnly, true);
  assert.equal(picker.companyId, 0);
  picker.onSelect(1);
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

test('unified inbox defaults to local 0 and operations require a positive explicit eligible company', () => {
  const app = session();
  assert.equal(one(app.render(), 'RoomsScreen').companyId, 0);
  one(app.render(), 'RoomsScreen').manage('create');
  let picker = one(app.render(), 'CompanySelector');
  assert.deepEqual(Array.from(picker.companyIds), [1]);
  assert.equal(picker.allowAll, undefined, 'operation selector never offers synthetic 0');
  picker.onSelect(0);
  assert.equal(nodes(app.render()).some(node => node.type === 'ManagementSheet'), false);
  picker.onSelect(99);
  assert.equal(nodes(app.render()).some(node => node.type === 'ManagementSheet'), false);
  picker.onSelect(1);
  const sheet = one(app.render(), 'ManagementSheet');
  assert.equal(sheet.companyId, 1);
  assert.equal(sheet.room, null);
  assert.equal(one(app.render(), 'RoomsScreen').companyId, 0, 'operation company does not change inbox filter');
  sheet.close();
  one(app.render(), 'RoomsScreen').selectCompany(99);
  assert.equal(one(app.render(), 'RoomsScreen').companyId, 0);
  assert.deepEqual(app.calls, []);
});

test('members use the room company, independent of the selected inbox filter', () => {
  const app = session();
  app.chat.identity.company_ids = [1, 2];
  app.chat.identity.mobile_policy.push({ company_id: 2, direct_enabled: true, can_manage: true });
  one(app.render(), 'RoomsScreen').selectCompany(1);
  const room = { id: 8, company_id: 2, membership_id: 18, is_group: true };
  app.chat.selected = room;
  one(app.render(), 'TimelineScreen').manage();
  let sheet = one(app.render(), 'ManagementSheet');
  assert.equal(sheet.mode, 'members');
  assert.equal(sheet.companyId, 2);
  assert.equal(sheet.room, room);
  app.width(900);
  assert.equal(one(app.render(), 'RoomsScreen').companyId, 1);
});

test('saved metadata captures the engine snapshot without another refresh or same-room history selection', async () => {
  const app = session();
  const room = { id: 8, company_id: 1, membership_id: 18, is_group: true, name: 'Old' };
  app.chat.rooms = [{ ...room, name: 'Server-confirmed name' }];
  app.chat.selected = room;
  app.engine.refresh = async () => { app.calls.push('redundant-refresh'); };
  app.chat.capture = () => { app.calls.push('capture'); };
  one(app.render(), 'TimelineScreen').manage();
  const sheet = one(app.render(), 'ManagementSheet');
  await sheet.changed(room.id);
  assert.equal(app.calls.filter(call => call === 'capture').length, 1);
  assert.equal(app.calls.filter(call => call === 'redundant-refresh').length, 0);
  assert.equal(app.calls.filter(call => Array.isArray(call) && call[0] === 'select').length, 0,
    'same membership keeps its current history/draft/keyboard/sound baseline');
});

test('confirmed creation/open selects a different authorized tuple, but never an absent room', async () => {
  for (const sameIdNewMembership of [false, true]) {
    const app = session();
    const current = { id: 8, company_id: 1, membership_id: 18, is_group: true };
    const fresh = { ...current, id: sameIdNewMembership ? 8 : 9, membership_id: 19 };
    app.chat.selected = current; app.chat.rooms = [fresh];
    app.chat.capture = () => { app.calls.push('capture'); };
    app.engine.refresh = async () => { app.calls.push('redundant-refresh'); };
    one(app.render(), 'TimelineScreen').manage();
    const sheet = one(app.render(), 'ManagementSheet');
    await sheet.changed(fresh.id);
    const selects = app.calls.filter(call => Array.isArray(call) && call[0] === 'select');
    assert.equal(selects.length, 1); assert.equal(selects[0][1], fresh);
    await sheet.changed(999);
    assert.equal(app.calls.filter(call => Array.isArray(call) && call[0] === 'select').length, 1);
    assert.equal(app.calls.includes('redundant-refresh'), false);
  }
});

test('pending company operations and old room actions cannot survive revoke, mask, scope change or background', () => {
  for (const scenario of ['companies', 'rights', 'masked', 'user', 'background']) {
    const app = session();
    app.chat.identity.company_ids = [1, 2];
    one(app.render(), 'RoomsScreen').manage('create');
    const oldPicker = one(app.render(), 'CompanySelector').onSelect;
    const oldManage = one(app.render(), 'RoomsScreen').manage;
    const oldSelect = one(app.render(), 'RoomsScreen').select;
    if (scenario === 'companies') app.chat.identity.company_ids = [1];
    if (scenario === 'rights') app.chat.identity.permissions.chat_view = false;
    if (scenario === 'masked') app.chat.presentationReady = false;
    if (scenario === 'user') app.chat.identity = identity(8);
    if (scenario === 'background') app.nativeApp.change('background');
    app.render();
    oldPicker(2); oldManage('create'); oldSelect({ id: 8, company_id: 2, membership_id: 18 });
    const tree = app.render();
    assert.equal(nodes(tree).some(node => ['CompanySelector', 'ManagementSheet'].includes(node.type)), false, scenario);
    assert.deepEqual(app.calls, [], scenario);
  }
});

test('a revoked local company filter resets to all companies and closes old management targets', () => {
  const app = session();
  app.chat.identity.company_ids = [1, 2];
  one(app.render(), 'RoomsScreen').selectCompany(2);
  one(app.render(), 'RoomsScreen').manage('create');
  assert.equal(one(app.render(), 'ManagementSheet').companyId, 2);
  app.chat.identity.company_ids = [1];
  const tree = app.render();
  assert.equal(one(tree, 'RoomsScreen').companyId, 0);
  assert.equal(nodes(tree).some(node => node.type === 'ManagementSheet'), false);
});

test('verified picker outcome survives private-sheet unmount without reopening it and is scoped to the current session and room', () => {
  const app = session();
  const room = {id: 8, company_id: 1, membership_id: 18, is_group: true, name: 'Synthetic group'};
  app.chat.rooms = [room]; app.chat.selected = room;
  one(app.render(), 'TimelineScreen').manage();
  const finish = one(app.render(), 'ManagementSheet').onPhotoOutcome;
  const scope = app.engine.accountScope;
  app.nativeApp.change('background'); app.render(); app.nativeApp.change('active');
  finish({scope, room, status: 'saved'});
  let tree = app.render();
  assert.ok(text(tree).includes(dictionary.translator('ar')('groupPhotoUpdated')));
  assert.equal(nodes(tree).some(node => node.type === 'ManagementSheet'), false);
  app.engine.accountScope = 'synthetic-actor/epoch:2';
  finish({scope, room, status: 'failed', error: {code: 'avatar_uncertain', private: 'UNSAFE-PRIVATE-ERROR'}});
  tree = app.render();
  assert.equal(text(tree).includes(dictionary.translator('ar')('groupPhotoUpdated')), false);
  assert.equal(text(tree).includes(dictionary.translator('ar')('avatarUncertain')), false);
  assert.equal(text(tree).includes('UNSAFE-PRIVATE-ERROR'), false);
  app.chat.rooms = [];
  finish({scope: app.engine.accountScope, room, status: 'saved'});
  assert.equal(text(app.render()).includes(dictionary.translator('ar')('groupPhotoUpdated')), false);
});

test('surviving picker failures render generic translated words only, and a different room or mask hides the notice', () => {
  const app = session();
  const room = {id: 8, company_id: 1, membership_id: 18, is_group: true, name: 'Synthetic group'};
  app.chat.rooms = [room]; app.chat.selected = room;
  one(app.render(), 'TimelineScreen').manage();
  const finish = one(app.render(), 'ManagementSheet').onPhotoOutcome;
  finish({scope: app.engine.accountScope, room, status: 'failed', error: {code: 'avatar_uncertain', uri: 'file:///PRIVATE'}});
  let tree = app.render();
  assert.ok(text(tree).includes(dictionary.translator('ar')('avatarUncertain')));
  assert.equal(text(tree).includes('file:///PRIVATE'), false);
  assert.equal(text(tree).includes(dictionary.translator('ar')('groupPhotoUpdated')), false);
  app.chat.selected = {...room, id: 9};
  assert.equal(text(app.render()).includes(dictionary.translator('ar')('avatarUncertain')), false);
  app.chat.selected = room; app.chat.presentationReady = false;
  assert.equal(text(app.render()).includes(dictionary.translator('ar')('avatarUncertain')), false);
});

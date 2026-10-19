/** Actual React shell tests with host surfaces, never native appearance or real requests. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const ts = require('typescript');
const React = require('react');
const renderer = require('react-test-renderer');

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
function harness() {
  const calls = [];
  const appState = { currentState: 'active' };
  const source = ts.transpileModule(readFileSync(join(__dirname, 'OrdersOnlyShell.tsx'), 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const engine = { logout: async () => { calls.push('logout'); } }, orders = {};
  let refreshError;
  let workspaceMounts = 0;
  function OrdersProbe(props) {
    const [draft, setDraft] = React.useState(() => { workspaceMounts++; return ''; });
    return React.createElement('OrdersScreen', { ...props, fixtureDraft: draft, fixtureEdit: setDraft });
  }
  const modules = {
    react: React, 'react/jsx-runtime': require('react/jsx-runtime'),
    'react-native': { View: 'View', AppState: appState }, 'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' },
    '../runtime': { getEngine: () => { calls.push('getEngine'); return engine; }, getOrdersEngine: () => { calls.push('getOrdersEngine'); return orders; },
      refreshOrdersOnlySession: async () => { calls.push('refresh'); if (refreshError) throw refreshError; }, ordersOnlySnapshot: () => props.snapshot },
    '../orders/ui/OrdersScreen': { OrdersScreen: OrdersProbe },
    '../ui/components': { Button: 'Button', IconButton: 'IconButton', Label: 'Label', styles: {}, colors: { white: 'white' } },
    '../ui/Brand': { Brand: 'Brand' }, '../ui/NavigationDrawer': { NavigationDrawer: 'NavigationDrawer' },
    '../ui/dictionary': { translator: language => word => `${language}:${word}`, errorWord: () => 'error' },
  };
  const module = { exports: {} };
  vm.runInNewContext(source, { module, exports: module.exports, require: name => {
    if (!(name in modules)) throw new Error(`Unexpected import: ${name}; orders shell must not import chat hooks`);
    return modules[name];
  } });
  const props = { snapshot: { identity: { database: 'fixture', user_id: 9, company_ids: [1], permissions: { order_view: true, chat_view: false } }, verified: true, generation: 4, revision: 2 },
    language: 'ar', online: true, setLanguage: value => calls.push(['language', value]) };
  let mounted;
  const render = async () => { await renderer.act(async () => { if (!mounted) mounted = renderer.create(React.createElement(module.exports.OrdersOnlyShell, props)); else mounted.update(React.createElement(module.exports.OrdersOnlyShell, props)); }); };
  return { props, calls, orders, engine, appState, render, nodes: type => mounted.root.findAllByType(type),
    workspaceMounts: () => workspaceMounts,
    async act(callback) { await renderer.act(async () => { await callback(); }); },
    error(value) { refreshError = value; }, async unmount() { await renderer.act(() => mounted?.unmount()); } };
}

test('orders-only shell retains its same-authority workspace behind a private verification cover and never imports useChat', async () => {
  const app = harness();
  try {
    await app.render();
    const screen = app.nodes('OrdersScreen')[0].props;
    assert.equal(screen.engine, app.orders); assert.equal(screen.identity.permissions.chat_view, false);
    assert.equal(screen.scopeKey.includes('fixture'), true); assert.equal(screen.language, 'ar'); assert.equal(screen.online, true);
    app.props.snapshot = { ...app.props.snapshot, verified: false }; await app.render();
    assert.equal(app.nodes('OrdersScreen').length, 1);
    assert.equal(app.nodes('OrdersScreen')[0].props.presented, false);
    assert.equal(app.nodes('Label').some(node => node.props.children === 'ar:loading'), false);
    assert.equal(app.nodes('View').some(node => node.props.testID === 'orders-session-privacy-cover'), true);
    app.props.online = false; await app.render();
    assert.equal(app.nodes('OrdersScreen').length, 1);
    assert.equal(app.nodes('Label')[0].props.children, 'ar:connectionError');
    assert.equal(app.nodes('Button')[0].props.disabled, true);
    assert.equal(app.nodes('NavigationDrawer')[0].props.canManage, false);
    assert.equal(app.nodes('NavigationDrawer')[0].props.offline, true);
    assert.equal(app.nodes('NavigationDrawer')[0].props.identity, null);
    assert.equal(app.nodes('NavigationDrawer')[0].props.visible, false);
  } finally { await app.unmount(); }
});

test('orders-only verification revisions preserve mounted cart state, but changed authority remounts it', async () => {
  const app = harness();
  try {
    await app.render(); const initial = app.nodes('OrdersScreen')[0].props.scopeKey;
    await app.act(() => app.nodes('OrdersScreen')[0].props.fixtureEdit('retained cart'));
    app.props.snapshot = { ...app.props.snapshot, verified: false, revision: 3 }; await app.render();
    assert.equal(app.nodes('OrdersScreen')[0].props.fixtureDraft, 'retained cart');
    assert.equal(app.nodes('OrdersScreen')[0].props.presented, false);
    app.props.online = false; await app.render();
    app.props.online = true; app.props.snapshot = { ...app.props.snapshot, verified: true, revision: 4 }; await app.render();
    assert.equal(app.workspaceMounts(), 1);
    assert.equal(app.nodes('OrdersScreen')[0].props.scopeKey, initial);
    assert.equal(app.nodes('OrdersScreen')[0].props.fixtureDraft, 'retained cart');
    app.props.snapshot = { ...app.props.snapshot, identity: { ...app.props.snapshot.identity, company_ids: [2] } }; await app.render();
    assert.equal(app.workspaceMounts(), 2); assert.equal(app.nodes('OrdersScreen')[0].props.fixtureDraft, '');
  } finally { await app.unmount(); }
});

test('retained shell handlers reject changed generation/revision and background state; locking closes the drawer', async () => {
  for (const change of ['generation', 'revision', 'background']) {
    const app = harness();
    try {
      await app.render();
      const staleMenu = app.nodes('IconButton')[0].props.onPress;
      const staleAction = app.nodes('NavigationDrawer')[0].props.onAction;
      if (change === 'background') app.appState.currentState = 'background';
      else app.props.snapshot = { ...app.props.snapshot, [change]: app.props.snapshot[change] + 1 };
      await app.act(() => { staleMenu(); staleAction('en'); staleAction('refresh'); staleAction('logout'); });
      assert.equal(app.calls.some(call => Array.isArray(call) || call === 'refresh' || call === 'logout'), false, change);
      assert.equal(app.nodes('NavigationDrawer')[0].props.visible, false);
      app.appState.currentState = 'active'; await app.render();
      await app.act(() => app.nodes('IconButton')[0].props.onPress());
      assert.equal(app.nodes('NavigationDrawer')[0].props.visible, true);
      app.props.snapshot = { ...app.props.snapshot, verified: false }; await app.render();
      assert.equal(app.nodes('NavigationDrawer')[0].props.visible, false);
      assert.equal(app.nodes('NavigationDrawer')[0].props.identity, null);
    } finally { await app.unmount(); }
  }
});

test('orders-only shell menu, language, refresh, failure and logout use their explicit actions', async () => {
  const app = harness();
  try {
    await app.render();
    await app.act(() => app.nodes('IconButton')[0].props.onPress());
    assert.equal(app.nodes('NavigationDrawer')[0].props.visible, true);
    await app.act(() => app.nodes('NavigationDrawer')[0].props.onAction('en'));
    assert.deepEqual(app.calls.find(call => Array.isArray(call)), ['language', 'en']);
    await app.act(() => app.nodes('NavigationDrawer')[0].props.close());
    assert.equal(app.nodes('NavigationDrawer')[0].props.visible, false);
    await app.act(() => app.nodes('NavigationDrawer')[0].props.onAction('refresh'));
    assert.equal(app.calls.filter(call => call === 'refresh').length, 1);
    app.props.snapshot = { ...app.props.snapshot, verified: false }; await app.render();
    app.error(new Error('fixture refresh failure'));
    await app.act(() => app.nodes('Button')[0].props.onPress());
    assert.equal(app.nodes('Label')[0].props.children, 'ar:error');
    app.props.online = false; await app.render();
    await app.act(() => app.nodes('NavigationDrawer')[0].props.onAction('refresh'));
    assert.equal(app.calls.filter(call => call === 'refresh').length, 2, 'offline refresh is gated');
    await app.act(() => app.nodes('NavigationDrawer')[0].props.onAction('logout'));
    assert.equal(app.calls.filter(call => call === 'logout').length, 1);
  } finally { await app.unmount(); }
});

test('an absent orders-only identity renders no domain surface', async () => {
  const app = harness();
  try { app.props.snapshot.identity = null; await app.render(); assert.equal(app.nodes('OrdersScreen').length, 0); assert.equal(app.nodes('NavigationDrawer').length, 0); }
  finally { await app.unmount(); }
});

test('orders-only company selection is explicit, authorized and cannot survive another actor or retained callbacks', async () => {
  const app = harness();
  try {
    await app.render(); assert.equal(app.nodes('OrdersScreen')[0].props.selectedCompanyId, 0);
    await app.act(() => app.nodes('OrdersScreen')[0].props.onCompanyChange(1));
    assert.equal(app.nodes('OrdersScreen')[0].props.selectedCompanyId, 1);
    await app.act(() => app.nodes('OrdersScreen')[0].props.onCompanyChange(99));
    assert.equal(app.nodes('OrdersScreen')[0].props.selectedCompanyId, 1);
    const stale = app.nodes('OrdersScreen')[0].props.onCompanyChange;
    app.props.snapshot = { ...app.props.snapshot, generation: 5, identity: { ...app.props.snapshot.identity, user_id: 10 } }; await app.render();
    assert.equal(app.nodes('OrdersScreen')[0].props.selectedCompanyId, 0);
    await app.act(() => stale(1)); assert.equal(app.nodes('OrdersScreen')[0].props.selectedCompanyId, 0);
    app.appState.currentState = 'background';
    await app.act(() => app.nodes('OrdersScreen')[0].props.onCompanyChange(1));
    assert.equal(app.nodes('OrdersScreen')[0].props.selectedCompanyId, 0);
  } finally { await app.unmount(); }
});

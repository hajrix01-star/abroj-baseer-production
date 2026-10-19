/** Actual CompanySelector render/effect seams; not a native visual or accessibility audit. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

function compile(file, modules) {
  const code = ts.transpileModule(readFileSync(join(__dirname, file), 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
  }).outputText;
  const mod = { exports: {} };
  vm.runInNewContext(code, {
    module: mod,
    exports: mod.exports,
    require: name => modules[name] ?? {},
  });
  return mod.exports;
}
function walk(node, predicate) {
  if (!node || typeof node !== 'object') return undefined;
  if (predicate(node)) return node;
  for (const child of [node.props?.children].flat(3)) {
    const found = walk(child, predicate);
    if (found) return found;
  }
}
function nodes(node, predicate) {
  const found = [];
  function visit(item) {
    if (!item || typeof item !== 'object') return;
    if (predicate(item)) found.push(item);
    [item.props?.children].flat(3).forEach(visit);
  }
  visit(node);
  return found;
}
function harness(initial = {}) {
  const slots = [];
  let index = 0;
  let background;
  const react = {
    useState(value) {
      const at = index++;
      if (!(at in slots)) slots[at] = value;
      return [
        slots[at],
        next => {
          slots[at] = next;
        },
      ];
    },
    useRef(value) {
      const at = index++;
      return slots[at] ?? (slots[at] = { current: value });
    },
    useEffect(callback, deps) {
      const at = index++;
      const prior = slots[at];
      if (!prior || deps.some((value, i) => value !== prior.deps[i])) {
        prior?.cleanup?.();
        slots[at] = { deps, cleanup: callback() };
      }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const names = compile('companyNames.ts', {});
  const component = compile('CompanySelector.tsx', {
    react,
    'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'Fragment' },
    'react-native': {
      Pressable: 'Pressable',
      Text: 'Text',
      View: 'View',
      AppState: {
        currentState: 'active',
        addEventListener(event, cb) {
          background = cb;
          return { remove() {} };
        },
      },
    },
    './companyNames': names,
    './components': {
      colors: {},
      styles: {},
      direction: language => ({ writingDirection: language === 'ar' ? 'rtl' : 'ltr' }),
      Icon: 'Icon',
      Field: 'Field',
      Label: 'Label',
      Sheet: 'Sheet',
    },
  }).CompanySelector;
  const chosen = [];
  let props = {
    identity: {
      database: 'synthetic',
      user_id: 7,
      company_ids: [1, 2, 3],
      permissions: { chat_view: true, revision: 1 },
      profile: {
        companies: [
          {
            id: 1,
            name: ' Fallback One ',
            name_ar: ' مطعم عربي طويل للاختبار ',
            name_en: ' Long English Restaurant Company Name ',
          },
          { id: 2, name: ' Fallback Two ', name_ar: '  ', name_en: '' },
          { id: 3, name: ' ', name_ar: '', name_en: ' ' },
          { id: 999, name: 'Unauthorized company' },
        ],
      },
    },
    companyId: 1,
    language: 'ar',
    t: key => key,
    onSelect: id => chosen.push(id),
    ...initial,
  };
  return {
    names,
    chosen,
    render(next = {}) {
      props = { ...props, ...next };
      index = 0;
      return component(props);
    },
    props: () => props,
    background() {
      background('background');
    },
  };
}
function button(tree) {
  return walk(tree, item => item.props?.testID === 'company-selector');
}
function option(tree, id) {
  return walk(tree, item => item.props?.testID === `company-option-${id}`);
}
function open(app) {
  button(app.render()).props.onPress();
  return app.render();
}

test('actual dropdown uses interface language, trimmed fallback and authorized IDs only', () => {
  const app = harness();
  const tree = open(app);
  assert.equal(option(tree, 1).props.accessibilityLabel, 'مطعم عربي طويل للاختبار');
  assert.equal(option(tree, 2).props.accessibilityLabel, 'Fallback Two');
  assert.equal(option(tree, 3).props.accessibilityLabel, '3');
  assert.equal(option(tree, 999), undefined);
  assert.equal(option(tree, 1).props.accessibilityState.selected, true);
  app.render({ language: 'en' });
  const english = open(app);
  assert.equal(option(english, 1).props.accessibilityLabel, 'Long English Restaurant Company Name');
  assert.equal(nodes(english, item => item.type === 'Sheet').length, 1);
});

test('explicit task company selector uses task rights without granting chat access or expanding companies', () => {
  const app = harness({ permission: 'task_view' });
  const identity = app.props().identity;
  identity.permissions = { chat_view: false, task_view: true, revision: 1 };
  app.render({ identity });
  const tree = open(app);
  assert.ok(option(tree, 1)); assert.equal(option(tree, 999), undefined);
  const old = option(tree, 2).props.onPress;
  identity.permissions = { chat_view: false, task_view: false, revision: 2 };
  app.render({ identity }); old();
  assert.deepEqual(app.chosen, []); assert.equal(button(app.render()).props.disabled, true);
  const chatDefault = harness({ identity: { ...identity, permissions: { chat_view: false, task_view: true } } });
  assert.equal(button(chatDefault.render()).props.disabled, true, 'default consumers still require chat_view');
});

test('local search and normal selection work without an extra API', () => {
  const app = harness();
  let tree = open(app);
  walk(tree, item => item.type === 'Field').props.onChangeText('Fallback');
  tree = app.render();
  assert.equal(option(tree, 1), undefined);
  assert.ok(option(tree, 2));
  option(tree, 2).props.onPress();
  assert.deepEqual(app.chosen, [2]);
  assert.equal(nodes(app.render(), item => item.type === 'Sheet').length, 0);
});

test('list/user/rights changes and background invalidate old choices and close the modal', () => {
  for (const change of [
    'company-list',
    'selected-company',
    'language',
    'user',
    'rights',
    'background',
    'close',
  ]) {
    const app = harness();
    const tree = open(app);
    const stale = option(tree, 2).props.onPress;
    const identity = app.props().identity;
    if (change === 'company-list') app.render({ identity: { ...identity, company_ids: [1] } });
    if (change === 'selected-company') app.render({ companyId: 2 });
    if (change === 'language') app.render({ language: 'en' });
    if (change === 'user') app.render({ identity: { ...identity, user_id: 8 } });
    if (change === 'rights')
      app.render({ identity: { ...identity, permissions: { chat_view: false, revision: 2 } } });
    if (change === 'background') app.background();
    if (change === 'close') walk(tree, item => item.type === 'Sheet').props.close();
    stale();
    assert.deepEqual(app.chosen, [], change);
    assert.equal(nodes(app.render(), item => item.type === 'Sheet').length, 0, change);
  }
});

test('synthetic all-companies option is opt-in, local and counted from authorized IDs only', () => {
  const app = harness({ companyId: 0, allowAll: true });
  const tree = open(app);
  assert.equal(option(tree, 0).props.accessibilityLabel, 'allCompanies (3)');
  assert.equal(option(tree, 0).props.accessibilityState.selected, true);
  option(tree, 0).props.onPress();
  assert.deepEqual(app.chosen, [0]);
  const normal = harness();
  assert.equal(option(open(normal), 0), undefined, 'operation selector never adds 0 by default');
  const empty = harness({ allowAll: true });
  empty.render({ identity: { ...empty.props().identity, company_ids: [] } });
  assert.equal(option(open(empty), 0), undefined);
});

test('operation-only picker opens directly, restricts to intersection, and invalidates a retained choice', () => {
  const app = harness({ companyId: 0, pickerOnly: true, companyIds: [2, 999] });
  let tree = app.render();
  assert.equal(button(tree), undefined);
  assert.ok(option(tree, 2));
  assert.equal(option(tree, 0), undefined);
  assert.equal(option(tree, 1), undefined);
  assert.equal(option(tree, 999), undefined);
  const stale = option(tree, 2).props.onPress;
  app.render({ companyIds: [1] });
  stale();
  assert.deepEqual(app.chosen, []);
  assert.equal(nodes(app.render(), item => item.type === 'Sheet').length, 0);
  const selected = harness({ companyId: 0, pickerOnly: true, companyIds: [2] });
  option(selected.render(), 2).props.onPress();
  assert.deepEqual(selected.chosen, [2]);
});

function inbox() {
  const ref = { current: undefined };
  const names = compile('companyNames.ts', {});
  const component = compile('RoomsScreen.tsx', {
    react: { useRef: value => { ref.current ??= value; return ref; } },
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    'react-native': { Pressable: 'Pressable', Text: 'Text', View: 'View' },
    '@shopify/flash-list': { FlashList: 'FlashList' },
    './CompanySelector': { CompanySelector: 'CompanySelector' },
    './companyNames': names,
    './viewModel': compile('viewModel.ts', {}),
    './components': { Icon: 'Icon', IconButton: 'IconButton', Label: 'Label', styles: {}, colors: {}, direction: () => ({}) },
  }).RoomsScreen;
  const calls = [];
  let props = {
    identity: { database: 'synthetic', user_id: 7, company_ids: [1, 2],
      permissions: { chat_view: true, group_create: true, revision: 1 },
      profile: { companies: [{ id: 1, name: 'Fallback1', name_ar: 'شركة ألف', name_en: 'Company A' },
        { id: 2, name: 'Fallback2', name_ar: 'شركة باء', name_en: 'Company B' },
        { id: 99, name: 'Unauthorized company' }] } },
    rooms: [{ id: 1, company_id: 1, membership_id: 10, name: 'Same room', is_group: true },
      { id: 2, company_id: 2, membership_id: 20, name: 'Same room', is_group: true },
      { id: 99, company_id: 99, membership_id: 99, name: 'Hidden room', is_group: true }],
    companyId: 0, language: 'ar', t: key => key, offline: false, selected: null,
    select: room => calls.push(['select', room.id]), manage: mode => calls.push(['manage', mode]),
    selectCompany: id => calls.push(['filter', id]),
  };
  return { calls, props: () => props, render(next = {}) { props = { ...props, ...next }; return component(props); } };
}
const list = tree => walk(tree, node => node.type === 'FlashList').props;

test('actual unified room list filters authorization before all/local filter and labels duplicate rooms by localized company', () => {
  const app = inbox();
  const tree = app.render();
  assert.deepEqual(Array.from(list(tree).data, room => room.id), [1, 2]);
  assert.equal(walk(tree, node => node.type === 'CompanySelector').props.allowAll, true);
  const rows = list(tree).data.map(item => list(tree).renderItem({ item }));
  assert.equal(rows[0].props.accessibilityLabel, 'Same room · شركة ألف');
  assert.equal(rows[1].props.accessibilityLabel, 'Same room · شركة باء');
  rows[1].props.onPress();
  assert.deepEqual(app.calls, [['select', 2]]);
  let filtered = app.render({ companyId: 1, language: 'en' });
  assert.deepEqual(Array.from(list(filtered).data, room => room.id), [1]);
  assert.equal(list(filtered).renderItem({ item: list(filtered).data[0] }).props.accessibilityLabel,
    'Same room · Company A');
  assert.deepEqual(Array.from(list(app.render({ companyId: 99 })).data), []);
  assert.deepEqual(Array.from(list(app.render({ companyId: 0,
    identity: { ...app.props().identity, permissions: { chat_view: false } } })).data), []);
});

test('retained room rows/action closures fail closed after membership, identity, rights or company changes', () => {
  for (const scenario of ['membership', 'user', 'view', 'companies', 'offline']) {
    const app = inbox();
    const tree = app.render();
    const staleRoom = list(tree).renderItem({ item: list(tree).data[1] }).props.onPress;
    const staleManage = walk(tree, node => node.type === 'IconButton' && node.props.label === 'group').props.onPress;
    const identity = app.props().identity;
    if (scenario === 'membership') app.render({ rooms: app.props().rooms.filter(room => room.id !== 2) });
    if (scenario === 'user') app.render({ identity: { ...identity, user_id: 8 } });
    if (scenario === 'view') app.render({ identity: { ...identity, permissions: { chat_view: false } } });
    if (scenario === 'companies') app.render({ identity: { ...identity, company_ids: [1] } });
    if (scenario === 'offline') app.render({ offline: true });
    staleRoom();
    assert.deepEqual(app.calls, [], `${scenario}: no old room opens`);
    if (scenario !== 'membership') {
      staleManage();
      assert.deepEqual(app.calls, [], `${scenario}: no old action runs`);
    }
  }
});

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
function harness() {
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

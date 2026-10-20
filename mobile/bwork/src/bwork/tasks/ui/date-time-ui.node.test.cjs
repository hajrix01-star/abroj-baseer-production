const { test } = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const renderer = require('react-test-renderer');
const ts = require('typescript');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const { resolve, dirname } = require('node:path');
const { nodes, byId, button, text } = require('./tasks-harness.cjs');
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
function harness(language) {
  const cache = new Map(), calls = []; let mounted;
  function load(filename) {
    const output = { exports: {} }; if (cache.has(filename)) return cache.get(filename);
    const raw = readFileSync(filename, 'utf8'); cache.set(filename, output.exports);
    vm.runInNewContext(ts.transpileModule(raw, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText,
      { module: output, exports: output.exports, Date, Intl, require(name) {
        if (name === 'react' || name === 'react/jsx-runtime') return require(name);
        if (name === 'react-native') return { View: 'View', Pressable: 'Pressable', Text: 'Text', AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) } };
        if (name === './components') return { Button: 'Button', IconButton: 'IconButton', Label: 'Label', Field: 'Field', Icon: 'Icon', Sheet: 'Sheet', colors: { blue: '#1256da' }, styles: { text: {}, input: {}, muted: {} }, direction: value => ({ writingDirection: value === 'ar' ? 'rtl' : 'ltr' }) };
        if (name === './dictionary') return { translator: () => word => word };
        return load(resolve(dirname(filename), `${name}.ts`));
      } }, { filename }); cache.set(filename, output.exports); return output.exports;
  }
  const DateTimeField = load(resolve(__dirname, '../../ui/DateTimeField.tsx')).DateTimeField;
  const props = { label: 'Due date', language, value: '2027-02-28T09:00:00Z', onChange: value => calls.push(value), disabled: false, testID: 'due' };
  const tree = node => !node || typeof node !== 'object' ? node : Array.isArray(node) ? node.map(tree) : { type: node.type, props: { ...node.props, children: tree(node.children) } };
  const render = () => tree(mounted?.toJSON());
  const flush = async () => { await renderer.act(async () => { if (!mounted) mounted = renderer.create(React.createElement(DateTimeField, props)); else mounted.update(React.createElement(DateTimeField, props)); }); return render(); };
  return { props, calls, render, flush, async act(callback) { await renderer.act(callback); return flush(); }, async unmount() { await renderer.act(() => mounted.unmount()); } };
}
test('date field uses accessible narrow inputs and a measured 44px Gregorian calendar in both languages', async () => {
  for (const language of ['ar', 'en']) { const app = harness(language); try { await app.flush(); await app.act(() => byId(app.render(), 'due').onPress());
    await app.act(() => byId(app.render(), 'due-picker').onLayout({ nativeEvent: { layout: { width: 272 } } }));
    assert.equal(nodes(app.render()).some(node => node.props?.testID?.startsWith('due-day-')), false);
    for (const key of ['year', 'month', 'day', 'hour', 'minute']) { const field = byId(app.render(), `due-${key}`); assert.equal(field.style.minHeight, 44); assert.equal(field.style.writingDirection, 'ltr'); }
    await app.act(() => byId(app.render(), 'due-picker').onLayout({ nativeEvent: { layout: { width: 540 } } }));
    const day = byId(app.render(), 'due-day-28'); assert.equal(day.style({ pressed: false }).minHeight, 44); assert.equal(day.style({ pressed: false }).minWidth, 44);
    assert.equal(/[٠-٩۰-۹]/.test(text(app.render())), false);
  } finally { await app.unmount(); } }
});
test('invalid dates do not save; disabled or hidden owner cannot commit an old date callback', async () => {
  const app = harness('en'); try { await app.flush(); await app.act(() => byId(app.render(), 'due').onPress());
    await app.act(() => byId(app.render(), 'due-day').onChangeText('29'));
    await app.act(() => button(app.render(), 'Use date').onPress()); assert.equal(app.calls.length, 0); assert.match(text(app.render()), /valid date/);
    await app.act(() => byId(app.render(), 'due-year').onChangeText('2028'));
    const stale = button(app.render(), 'Use date').onPress; app.props.disabled = true; await app.flush(); await app.act(stale); assert.equal(app.calls.length, 0);
    app.props.disabled = false; await app.flush(); await app.act(() => byId(app.render(), 'due').onPress());
    await app.act(() => button(app.render(), 'Use date').onPress()); assert.equal(app.calls.length, 1); assert.match(app.calls[0], /^2027-02-/);
  } finally { await app.unmount(); }
});

/** React hook/effect renderer with native host doubles; no browser/native layout claim. */
const React = require('react'), renderer = require('react-test-renderer'), ts = require('typescript'), vm = require('node:vm');
const { readFileSync } = require('node:fs'), { resolve, dirname, extname } = require('node:path');
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
function harness(initial = {}) {
  const cache = new Map(), calls = []; let mounted;
  const load = filename => {
    filename = resolve(filename); if (cache.has(filename)) return cache.get(filename);
    const raw = readFileSync(filename, 'utf8'), output = { exports: {} }; cache.set(filename, output.exports);
    const code = ts.transpileModule(raw, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    vm.runInNewContext(code, { module: output, exports: output.exports, Date, Intl, Math, JSON, console, setTimeout, clearTimeout, require(name) {
      if (['react', 'react/jsx-runtime'].includes(name)) return require(name);
      if (name === 'react-native') return { ...Object.fromEntries(['View', 'Text', 'Pressable', 'ScrollView', 'ActivityIndicator'].map(n => [n, n])), StyleSheet: { create: value => value } };
      if (name === 'react-native-svg') return { __esModule: true, default: 'Svg', Line: 'Line', Path: 'Path' };
      if (name.endsWith('/ui/components')) return { ...Object.fromEntries(['Button', 'IconButton', 'Label', 'Sheet'].map(n => [n, n])), colors: { blue: '#1256da', white: '#fff', background: '#f4f7fd', pale: '#edf2fc', ink: '#101b36', border: '#dce5ec', muted: '#54697b', warning: '#fff4d6', success: '#167447', danger: '#a12a32' }, direction: language => ({ writingDirection: language === 'ar' ? 'rtl' : 'ltr' }) };
      if (name.endsWith('/ui/CompanySelector')) return { CompanySelector: 'CompanySelector' };
      if (name.endsWith('/ui/DateTimeField')) return { DateTimeField: 'DateTimeField' };
      if (name.endsWith('/ui/dictionary')) return { translator: () => word => word };
      const target = resolve(dirname(filename), name);
      if (extname(target)) return load(target);
      for (const extension of ['.tsx', '.ts']) { try { return load(target + extension); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
      throw new Error(`Unexpected import ${name}`);
    } }, { filename }); cache.set(filename, output.exports); return output.exports;
  };
  const fixtures = load(resolve(__dirname, '../tests/fixtures.ts'));
  const options = JSON.parse(JSON.stringify(fixtures.options));
  const engine = { async options() { calls.push(['options']); return options; }, async read(query) { calls.push(['read', query]); return fixtures.report(query.companyId, query.month, query.period, query.date || `${query.month}-10`); }, cancelReads() { calls.push(['cancelReads']); }, clear() { calls.push(['clear']); } };
  const props = { engine, identity: { database: 'fixture', user_id: 9, company_ids: [1, 2], permissions: { dashboard_view: true, chat_view: false, task_view: false, revision: 1 } }, language: 'en', presented: true, scopeKey: 'fixture-user', ...initial };
  const Screen = load(resolve(__dirname, 'LeadershipScreen.tsx')).LeadershipScreen;
  const tree = value => value == null || typeof value !== 'object' ? value : Array.isArray(value) ? value.map(tree) : { type: value.type, props: { ...value.props, children: tree(value.children) } };
  const render = () => tree(mounted?.toJSON());
  const flush = async () => { await renderer.act(async () => { if (!mounted) mounted = renderer.create(React.createElement(Screen, props)); else mounted.update(React.createElement(Screen, props)); }); return render(); };
  return { props, engine, options, calls, fixtures, presentation: load(resolve(__dirname, 'presentation.ts')), render, flush, async act(callback) { await renderer.act(async () => { await callback(); }); return flush(); }, async unmount() { if (mounted) await renderer.act(async () => mounted.unmount()); } };
}
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const one = (value, type, predicate = () => true) => { const node = nodes(value).find(n => n.type === type && predicate(n.props)); if (!node) throw new Error(`Missing ${type}`); return node.props; };
const byId = (value, id) => { const node = nodes(value).find(n => n.props.testID === id); if (!node) throw new Error(`Missing ${id}`); return node.props; };
const text = value => nodes(value).flatMap(n => [n.props.children].flat(Infinity).filter(v => typeof v === 'string')).join(' ');
module.exports = { harness, nodes, one, byId, text };

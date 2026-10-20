/** Actual React hook/effect tests for task TSX; not a native layout certificate. */
const React = require('react');
const renderer = require('react-test-renderer');
const ts = require('typescript');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const { resolve, dirname } = require('node:path');
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
function harness(initial = {}) {
  const cache = new Map(), calls = [], timers = new Map(); let nextTimer = 0, mounted;
  const hosts = Object.fromEntries(['View', 'Text', 'Pressable', 'ScrollView', 'ActivityIndicator', 'KeyboardAvoidingView', 'TextInput'].map(name => [name, name]));
  const components = Object.fromEntries(['Button', 'IconButton', 'Field', 'Icon', 'Label', 'Sheet'].map(name => [name, name]));
  const load = filename => {
    filename = resolve(filename); if (cache.has(filename)) return cache.get(filename);
    const raw = readFileSync(filename, 'utf8');
    const output = { exports: {} }; cache.set(filename, output.exports);
    const input = ts.transpileModule(raw, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    vm.runInNewContext(input, { module: output, exports: output.exports, Date, Intl, setTimeout(callback) { const id = ++nextTimer; timers.set(id, callback); return id; }, clearTimeout(id) { timers.delete(id); }, require(name) {
      if (name === 'react') return React;
      if (name === 'react/jsx-runtime') return require(name);
      if (name === 'react-native') return { ...hosts, Platform: { OS: 'android' }, StyleSheet: { create: value => value }, AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) },
        FlatList: props => React.createElement('FlatList', props, props.ListHeaderComponent, props.data.map(item => React.createElement(React.Fragment, { key: props.keyExtractor(item) }, props.renderItem({ item }))), props.data.length ? null : props.ListEmptyComponent, props.ListFooterComponent) };
      if (name.endsWith('/ui/components')) return { ...components, colors: { blue: '#1256da', white: '#fff', background: '#f4f7fd', pale: '#edf2fc', ink: '#101b36', border: '#dce5ec', muted: '#54697b' }, styles: { input: {}, text: {}, muted: {} }, direction: language => ({ writingDirection: language === 'ar' ? 'rtl' : 'ltr' }) };
      if (name.endsWith('/ui/CompanySelector')) return { CompanySelector: 'CompanySelector' };
      if (name.endsWith('/ui/DateTimeField')) return { DateTimeField: 'DateTimeField' };
      if (name.endsWith('/ui/dictionary')) return { translator: () => word => word };
      const path = resolve(dirname(filename), name);
      for (const extension of ['.tsx', '.ts']) { try { return load(path + extension); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
      throw new Error(`Unexpected import: ${name}`);
    } }, { filename }); cache.set(filename, output.exports); return output.exports;
  };
  const task = (id = 7, company = 2, overrides = {}) => ({ id, company_id: company, company_name: `Company ${company}`, room_id: null, title: `Task ${id}`, description: 'Repair equipment', state: 'new', creator_id: 9, creator_name: 'Manager', assignee_id: 9, assignee_name: 'Worker', due_at: '2026-11-19T09:00:00Z', created_at: '2026-10-19T09:00:00Z', updated_at: '2026-10-19T09:00:00Z', revision: 1, last_actor_id: null, last_changed_at: null, last_note: '', started_at: null, done_at: null, cancelled_at: null, completion_note: '', done_by_id: null, done_by_name: '', reminder_at: null, reminder_emitted_at: null, reminder_due: false, origin_api: 'work_tasks_v1', allowed_actions: ['start', 'done', 'cancel', 'reassign'], ...overrides });
  const options = { api_version: 2, work_tasks_version: 1, server_now: '2026-10-19T09:00:00Z', companies: [{ id: 1, name: 'Company 1' }, { id: 2, name: 'Company 2' }], default_company_id: null, can_view: true, can_manage: true, capabilities: { direct_done: true, reminders: true } };
  const result = item => ({ api_version: 2, work_tasks_version: 1, server_now: options.server_now, task: item, client_uuid: 'fixture-uuid', replayed: false, operation_revision: item.revision });
  const engine = {
    async options() { calls.push(['options']); return options; },
    async list(query) { calls.push(['list', query]); return { tasks: [task(7, query.companyId || 2)], next_before_id: null }; },
    async detail(id, company) { calls.push(['detail', id, company]); return { task: task(id, company) }; },
    async assignees(company, query) { calls.push(['assignees', company, query]); return { company_id: company, assignees: [{ id: 11, name: 'Eligible employee' }], next_after_id: null }; },
    async create(input) { calls.push(['create', input]); return result(task(13, input.company_id, { assignee_id: input.assignee_id, title: input.title, due_at: input.due_at, reminder_at: input.reminder_at })); },
    async transition(item, input) { calls.push(['transition', item, input]); return result({ ...item, state: input.action === 'done' ? 'done' : 'in_progress', revision: item.revision + 1, allowed_actions: [], done_at: '2026-10-19T10:00:00Z', done_by_name: 'Canonical actor', completion_note: input.note || '' }); },
    async pending() { calls.push(['pending']); return []; },
    async retry(uuid) { calls.push(['retry', uuid]); return result(task()); }, cancelReads() { calls.push(['cancelReads']); }, subscribe() { return () => {}; },
  };
  const props = { engine, identity: { database: 'fixture', user_id: 9, company_ids: [1, 2], permissions: { task_view: true, task_manage: true, chat_view: false, order_view: false, revision: 1 } }, language: 'en', presented: true, scopeKey: 'fixture-user', ...initial };
  const Screen = load(resolve(__dirname, 'TasksScreen.tsx')).TasksScreen;
  const tree = node => !node || typeof node !== 'object' ? node : Array.isArray(node) ? node.map(tree) : ({ type: node.type, props: { ...node.props, children: tree(node.children) } });
  const render = () => tree(mounted?.toJSON());
  const flush = async (runTimers = true) => {
    await renderer.act(async () => { if (!mounted) mounted = renderer.create(React.createElement(Screen, props)); else mounted.update(React.createElement(Screen, props)); });
    if (runTimers) await renderer.act(async () => { for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } });
    return render();
  };
  return { props, options, engine, task, result, calls, render, flush, module: load,
    async act(callback, runTimers = true) { await renderer.act(async () => { await callback(); }); return flush(runTimers); }, async unmount() { if (mounted) await renderer.act(async () => mounted.unmount()); } };
}
const nodes = value => !value || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const one = (value, type, predicate = () => true) => { const node = nodes(value).find(item => item.type === type && predicate(item.props)); if (!node) throw new Error(`Missing ${type}`); return node.props; };
const byId = (value, id) => one(value, nodes(value).find(item => item.props?.testID === id)?.type, props => props.testID === id);
const button = (value, title) => one(value, 'Button', props => props.title === title);
const text = value => nodes(value).flatMap(node => [node.props?.children].flat(Infinity).filter(item => typeof item === 'string')).join(' ');
module.exports = { harness, nodes, one, byId, button, text };

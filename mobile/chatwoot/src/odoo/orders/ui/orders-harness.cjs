/** Host render/effect seams for the real TSX. Does not emulate native layout or keyboard. */
const { readFileSync } = require('node:fs');
const { join, dirname, resolve } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function harness(initial = {}, realReact = false, realComponents = false) {
  const instances = new Map(), cache = new Map(), timers = new Map();
  let active, slots, seen, effects, nextTimer = 0, stateWrites = 0;
  const react = realReact ? require('react') : {
    useState(initial) {
      const slot = slots++;
      if (!(slot in active.slots)) active.slots[slot] = typeof initial === 'function' ? initial() : initial;
      const instance = active;
      return [instance.slots[slot], value => { stateWrites++; instance.slots[slot] = typeof value === 'function' ? value(instance.slots[slot]) : value; }];
    },
    useRef(value) { const slot = slots++; return active.slots[slot] ?? (active.slots[slot] = { current: value }); },
    useEffect(effect, deps) {
      const slot = slots++, instance = active, previous = instance.slots[slot];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        instance.slots[slot] = { deps, cleanup: previous?.cleanup };
        effects.push(() => { previous?.cleanup?.(); instance.slots[slot].cleanup = effect(); });
      }
    },
  };
  const jsx = (type, props, key) => ({ type, props: props ?? {}, key });
  const hosts = Object.fromEntries(['View', 'Text', 'TextInput', 'Modal', 'ScrollView', 'Pressable', 'ActivityIndicator', 'KeyboardAvoidingView'].map(name => [name, name]));
  const components = Object.fromEntries(['Button', 'IconButton', 'Label', 'Field', 'Icon', 'Sheet'].map(name => [name, name]));
  let width = 320;
  const load = filename => {
    filename = resolve(filename);
    if (cache.has(filename)) return cache.get(filename);
    const input = readFileSync(filename, 'utf8');
    const module = { exports: {} }; cache.set(filename, module.exports);
    const source = ts.transpileModule(input, { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    } }).outputText;
    vm.runInNewContext(source, { module, exports: module.exports,
      require(name) {
        if (name === 'react') return react;
        if (name === 'react/jsx-runtime') return realReact ? require('react/jsx-runtime') : { jsx, jsxs: jsx, Fragment: 'Fragment' };
        if (name === 'react-native') return { ...hosts, StyleSheet: { create: value => value }, Platform: { OS: 'android' }, useWindowDimensions: () => ({ width, height: 760 }) };
        if (name === 'react-native-safe-area-context') return { SafeAreaView: 'View' };
        if (name === 'react-native-svg') return { __esModule: true, default: 'Svg', Path: 'Path' };
        if (!realComponents && name.endsWith('/ui/components')) return { ...components, colors: { blue: '#1256da' }, direction: language => ({ writingDirection: language === 'ar' ? 'rtl' : 'ltr' }) };
        if (!realComponents && name.endsWith('/ui/dictionary')) return { translator: () => key => key };
        const path = resolve(dirname(filename), name);
        for (const extension of ['.tsx', '.ts']) { try { return load(path + extension); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
        throw new Error(`Unexpected import ${name}`);
      },
      setTimeout(callback) { const id = ++nextTimer; timers.set(id, callback); return id; }, clearTimeout(id) { timers.delete(id); },
    }, { filename });
    cache.set(filename, module.exports); return module.exports;
  };
  function expand(node, path) {
    if (Array.isArray(node)) return node.map((item, i) => expand(item, `${path}/${item?.key ?? i}`));
    if (!node || typeof node !== 'object') return node;
    if (typeof node.type === 'function') {
      const id = `${path}/${node.type.name}/${node.key ?? ''}`;
      const instance = instances.get(id) ?? { slots: [] }; instances.set(id, instance); seen.add(id);
      active = instance; slots = 0;
      const result = node.type(node.props);
      return expand(result, id);
    }
    return { ...node, props: { ...node.props, children: expand(node.props.children, `${path}/children`) } };
  }
  const calls = [];
  const item = { id: 81, product_id: 22, product_name: 'Fixture product', option_name: 'Case', uom_name: 'Box', packaging_note: '8 units', category_id: 4, category_name: 'Category', last_price: '17.30', currency_symbol: 'SAR', image_url: '' };
  const summary = (id = 12, company_id = 2) => ({ id, name: `PR-${id}`, company_id, company_name: `Company ${company_id}`, requester_id: 9, requester_name: 'Fixture requester', state: 'sent', purchase_route: 'cash', purchase_route_name: 'Cash', representative_id: null, representative_name: '', requested_total: '999.12', currency_symbol: 'SAR', submitted_at: '2026-10-19', room_id: 55 });
  const receiptDetail = { api_version: 2, order: { ...summary(12, 1), warehouse_name: 'Fixture warehouse' }, lines: [1, 2].map(line_id => ({ line_id, product_name: `Fixture ${line_id}`, option_name: 'Case', uom_name: 'Box', requested_qty: '2', manager_received_qty: '2' })) };
  const options = { api_version: 2, access: 'operator', can_view: true, can_create: true, can_receive: true, companies: [{ id: 1, name: 'Company 1' }, { id: 2, name: 'Company 2' }], warehouses: [{ id: 7, name: 'Fixture warehouse' }], default_warehouse_id: 7, representatives: [{ id: 9, name: 'Representative' }], categories: [{ id: 4, name: 'Category' }], purchase_routes: [{ code: 'representative', name: 'Representative' }, { code: 'cash', name: 'Cash' }] };
  const engine = {
    async options(companyId) { calls.push(['options', companyId]); return options; },
    async catalog(companyId, query) { calls.push(['catalog', companyId, query]); return { api_version: 2, items: [item], next_after_id: null }; },
    async quote(input) { calls.push(['quote', input]); return { api_version: 2, company_id: input.company_id, cart_revision: input.cart_revision, lines: input.lines.map(line => ({ ...line, unit_price: '29.81', line_total: '61.13' })), estimated_total: '991.73', currency_symbol: 'SAR', currency_code: 'SAR', quoted_at: '2026-10-19' }; },
    invalidateQuote() { calls.push(['invalidateQuote']); }, cancelReads() { calls.push(['cancelReads']); },
    async list(before, companyId) { calls.push(['list', before, companyId]); return { api_version: 2, orders: [summary(12, companyId || 2)], next_before_id: null }; },
    async detail(companyId, id) { calls.push(['detail', companyId, id]); return { api_version: 2, order: { ...summary(id, companyId), warehouse_id: 7 }, lines: [] }; },
    async receipts(companyId, before) { calls.push(['receipts', companyId, before]); return { api_version: 2, orders: [{ ...summary(12, companyId), warehouse_name: 'Fixture warehouse' }], next_before_id: null }; },
    async receiptDetail(companyId, id) { calls.push(['receiptDetail', companyId, id]); return { ...receiptDetail, order: { ...receiptDetail.order, company_id: companyId } }; },
    async pending() { calls.push(['pending']); return []; },
    async create(input) { calls.push(['create', input]); return { api_version: 2, order: { ...summary(14, input.company_id), room_id: null }, client_uuid: 'fixture-uuid', replayed: false }; },
    async confirm(id, input, expected) { calls.push(['confirm', id, input, expected]); return { api_version: 2, client_uuid: 'fixture-receipt-uuid', replayed: false, receipt: { order_id: id, company_id: input.company_id, name: `PR-${id}`, state: 'purchased', actual_total: '831.49', currency_symbol: 'SAR', picking_id: null, confirmed_at: null, confirmed_by_id: 9 } }; },
    async share(companyId, id) { calls.push(['share', companyId, id]); return { shared: true }; },
    async savedRoom(companyId) { calls.push(['savedRoom', companyId]); return null; },
    async saveRoom(companyId, id) { calls.push(['saveRoom', companyId, id]); },
    async rooms(companyId, query) { calls.push(['rooms', companyId, query]); return { api_version: 2, company_id: companyId, rooms: [{ id: 55, name: 'Eligible room' }], next_after_id: null, preferred_room: null }; },
    async shareOrder(companyId, id, roomId) { calls.push(['shareOrder', companyId, id, roomId]); return { shared: true }; },
    async retry(uuid) { calls.push(['retry', uuid]); return { api_version: 2, order: summary(), client_uuid: uuid, replayed: true }; },
  };
  options.workflow_version = 1;
  const props = { engine, identity: { api_version: 2, database: 'fixture', user_id: 9, company_ids: [1, 2], permissions: { chat_view: false, chat_send: false, order_view: true, order_create: true, order_receive: true, revision: 1 } }, language: 'en', online: true, rooms: [], ...initial };
  props.selectedCompanyId = initial.selectedCompanyId ?? 1;
  props.onCompanyChange = initial.onCompanyChange ?? (id => { props.selectedCompanyId = id; });
  const Screen = load(join(__dirname, 'OrdersScreen.tsx')).OrdersScreen;
  const renderer = realReact ? require('react-test-renderer') : null;
  let mounted;
  const hostTree = json => !json || typeof json !== 'object' ? json : Array.isArray(json) ? json.map(hostTree)
    : { type: json.type, props: { ...json.props, children: hostTree(json.children) } };
  const render = () => {
    if (realReact) return hostTree(mounted?.toJSON());
    seen = new Set(); effects = [];
    const tree = expand(jsx(Screen, props), 'root');
    for (const [id, instance] of instances) if (!seen.has(id)) { for (const slot of instance.slots) slot?.cleanup?.(); instances.delete(id); }
    for (const effect of effects) effect();
    return tree;
  };
  const flush = async (runTimers = true) => {
    if (realReact) {
      globalThis.IS_REACT_ACT_ENVIRONMENT = true;
      await renderer.act(async () => { if (!mounted) mounted = renderer.create(react.createElement(Screen, props)); else mounted.update(react.createElement(Screen, props)); });
      if (runTimers) await renderer.act(async () => { for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } });
      return render();
    }
    for (let i = 0; i < 16; i++) { render(); await Promise.resolve(); }
    if (runTimers) { for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } }
    for (let i = 0; i < 16; i++) { render(); await Promise.resolve(); }
    return render();
  };
  return { props, engine, options, item, calls, summary, receiptDetail, render, flush, setWidth(value) { width = value; },
    module: name => load(join(__dirname, name)), timers,
    async act(callback, runTimers = true) { if (!realReact) throw new Error('Requires actual React harness'); await renderer.act(async () => { await callback(); }); return flush(runTimers); },
    writes: () => stateWrites,
    async unmount() {
      if (mounted) await renderer.act(() => mounted.unmount());
      else { for (const instance of instances.values()) for (const slot of instance.slots) slot?.cleanup?.(); instances.clear(); }
    },
  };
}
function nodes(node) { return !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)]; }
function one(tree, type, predicate = () => true) { const result = nodes(tree).find(node => node.type === type && predicate(node.props)); if (!result) throw new Error(`Missing ${type}`); return result.props; }
const text = tree => nodes(tree).flatMap(node => [node.props?.children].flat(2).filter(value => typeof value === 'string')).join(' ').replace(/\s+/g, ' ');
const byId = (tree, id) => { const node = nodes(tree).find(node => node.props.testID === id); if (!node) throw new Error(`Missing testID ${id}`); return node.props; };
const button = (tree, title) => one(tree, 'Button', props => props.title === title);
module.exports = { harness, nodes, one, text, byId, button };

// Run from the repository root: node docs/build-governance/fl1-ui/frontend-checks.mjs
// Isolated component behavior; browser/rendering evidence is recorded separately.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

let count = 0;
const checks = [];
const ok = (value, label) => { assert.ok(value, label); count++; checks.push(label); };
const native = fs.readFileSync('odoo/addons/web/static/src/core/utils/concurrency.js', 'utf8');
const start = native.indexOf('export class KeepLast');
const keepCode = native.slice(start, native.indexOf('\n/**', start + 1)).replace('export class', 'class');
const destroys = [], buses = [], calls = [], pending = [], views = {};
const orm = { call(...args) {
    calls.push(args);
    return new Promise((resolve, reject) => pending.push({ resolve, reject }));
} };
const context = {
    Component: class {}, onMounted: () => {}, onWillDestroy: fn => destroys.push(fn),
    useState: x => x, useService: () => orm, useBus: (bus, event, fn) => buses.push([bus, event, fn]),
    Domain: class { constructor(domain) { this.domain = domain; } toString() { return JSON.stringify(this.domain); } },
    _t: text => text, registry: { category: () => ({ add: (key, view) => { views[key] = view; } }) },
    ListRenderer: class {}, KanbanRenderer: class {}, listView: { native: true }, kanbanView: { native: true },
    Promise, JSON, Set,
};
vm.createContext(context);
const source = fs.readFileSync('custom_addons/baseer_financial_register/static/src/financial_register.js', 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/export class /g, 'class ');
vm.runInContext(keepCode + '\n' + source + '\nthis.Kpis = FinancialRegisterKpis;', context);
const filters = [{ name: 'date', groupId: 1, isActive: true }, { name: 'partner', groupId: 2, isActive: true }];
let activeDomain = [['state', '=', 'posted']];
const activeContext = { allowed_company_ids: [4], lang: 'ar_001' };
const search = {
    get domain() { return structuredClone(activeDomain); },
    get context() { return structuredClone(activeContext); },
    getSearchItems: predicate => filters.filter(predicate),
    deactivateGroup: id => filters.forEach(filter => { if (filter.groupId === id) filter.isActive = false; }),
    createNewFilters: newFilters => newFilters.forEach(filter => filters.push({ ...filter, groupId: filters.length + 1, isActive: true })),
};
const component = new context.Kpis();
component.env = { searchModel: search };
component.props = { list: { model: { bus: {} } } };
component.setup();
const settle = () => new Promise(resolve => setImmediate(resolve));
const payload = value => ({ currency_groups: [{ currency_id: 1, currency_name: value, sections: [] }], as_of: '2026-09-10' });

ok(views.baseer_financial_register_list.native && views.baseer_financial_register_kanban.native, 'native views retained');
ok(buses.length === 2, 'search and model reload hooks');
const first = component.refresh();
ok(calls[0][0] === 'account.move' && calls[0][1] === 'baseer_financial_register_kpis', 'correct endpoint');
ok(JSON.stringify(calls[0][2]) === JSON.stringify([activeDomain]), 'native domain passthrough');
ok(JSON.stringify(calls[0][3]) === JSON.stringify({ context: activeContext }), 'native context passthrough');
pending[0].resolve(payload('SAR'));
await first;
ok(component.state.currencyGroups[0].currency_name === 'SAR' && !component.state.loading, 'loaded payload');
const currency = { currency_id: 1, currency_name: 'SAR' }, section = { key: 'customer', label: 'Customers' };
const total = { key: 'total', label: 'Total', display: '1,234.50', domain: [['move_type', '=', 'out_invoice']] };
const overdue = { key: 'overdue', label: 'Overdue', display: '500.00', domain: [['invoice_date_due', '<', '2026-09-10']] };
component.selectCard(currency, section, total);
ok(filters.filter(filter => filter.isActive).length === 3, 'card facet added');
ok(filters.slice(0, 2).every(filter => filter.isActive), 'native filters retained');
component.selectCard(currency, section, overdue);
ok(filters.filter(filter => filter.isActive && filter.name === 'baseer_financial_register_kpi').length === 1, 'only owned facet replaced');
ok(component.state.selected === '1:customer:overdue', 'selected key');
component.selectCard(currency, section, overdue);
ok(!filters.some(filter => filter.isActive && filter.name === 'baseer_financial_register_kpi'), 'repeat click toggles off');
ok(filters.slice(0, 2).every(filter => filter.isActive), 'native filters retained after toggle');
await settle();
pending.at(-1).resolve(payload('AFTER_CLICK'));
await settle();
void component.refresh();
const oldPending = pending.at(-1);
const newest = component.refresh();
pending.at(-1).resolve(payload('LATEST'));
await newest;
oldPending.resolve(payload('OLD'));
await settle();
ok(component.state.currencyGroups[0].currency_name === 'LATEST', 'stale response ignored');
const fail = component.refresh();
ok(component.state.currencyGroups.length === 0 && component.state.loading, 'loading clears stale data');
pending.at(-1).reject(Error('backend'));
await fail;
ok(component.state.error && !component.state.loading && component.state.currencyGroups.length === 0, 'latest failure clears data');
const snapshot = component.refresh();
activeDomain = [['state', '=', 'posted'], ['partner_id', '=', 3]];
pending.at(-1).resolve(payload('WRONG_SNAPSHOT'));
await snapshot;
await settle();
ok(component.state.currencyGroups.length === 0, 'changed snapshot discarded');
ok(JSON.stringify(calls.at(-1)[2][0]) === JSON.stringify(activeDomain), 'changed snapshot refetched');
pending.at(-1).resolve(payload('NEW_SNAPSHOT'));
await settle();
ok(component.cardLabel(currency, section, total).includes('1,234.50 SAR'), 'server display preserved');
ok(!component.cardLabel(currency, section, { ...total, is_count: true }).endsWith('SAR'), 'count omits currency');
const dying = component.refresh();
destroys[0]();
pending.at(-1).resolve(payload('DESTROYED'));
await dying;
ok(component.state.currencyGroups.length === 0, 'destroyed component ignores response');
const result = {
    result: 'PASS', assertions: count,
    scope: 'Isolated frontend component behavior with actual native KeepLast; mocked OWL hooks, services, SearchModel and Domain serialization. Browser evidence is separate.',
    checks,
};
fs.writeFileSync('docs/build-governance/fl1-ui/frontend-checks.json', JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result));

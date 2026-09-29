// Run from repository root. FL3 coverage state only; mocked services, no DB writes.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
let count = 0;
const checks = [];
const ok = (value, label) => { assert.ok(value, label); count++; checks.push(label); };
const calls = [], pending = [], actions = [];
let onDestroy;
const orm = { call(...args) {
    calls.push(args);
    return new Promise((resolve, reject) => pending.push({ resolve, reject }));
} };
const action = { async doAction(value) { actions.push(value); } };
const source = fs.readFileSync('custom_addons/baseer_financial_register/static/src/financial_register.js', 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/export class /g, 'class ');
const context = {
    Component: class {}, onMounted: () => {}, onWillDestroy: fn => { onDestroy = fn; },
    useState: x => x, useService: name => name === 'orm' ? orm : action, useBus: () => {},
    Domain: class {}, _t: text => text, registry: { category: () => ({ add: () => {} }) },
    ListRenderer: class {}, KanbanRenderer: class {}, listView: {}, kanbanView: {},
    KeepLast: class { add(promise) { return promise; } }, Promise, JSON, Set,
    user: { activeCompanies: [{ id: 4 }, { id: 9 }] },
};
vm.createContext(context);
vm.runInContext(source + '\nthis.Kpis = FinancialRegisterKpis;', context);
const scope = { baseer_register_cash_month: '2026-09', allowed_company_ids: [4], lang: 'ar_001' };
const component = new context.Kpis();
component.env = { searchModel: { get context() { return { ...scope }; }, domain: [['state', '=', 'posted']], getSearchItems: () => [] } };
component.props = { list: { model: { bus: {} } } };
component.setup();

delete scope.baseer_register_cash_month;
const warning = 'Incomplete receivable classification';
const response = { currency_groups: [{ currency_id: 1, sections: [] }], as_of: '2026-09-10', coverage_warning: warning };
const initial = component.refresh();
pending.at(-1).resolve(response);
await initial;
ok(component.state.coverageWarning === warning, 'server warning is displayed without client financial calculations');
const reload = component.refresh();
ok(component.state.coverageWarning === '' && component.state.loading, 'loading clears prior coverage warning immediately');
pending.at(-1).resolve({ ...response, coverage_warning: '' });
await reload;
ok(component.state.coverageWarning === '', 'complete response clears warning');
const warnAgain = component.refresh();
pending.at(-1).resolve(response);
await warnAgain;
const failed = component.refresh();
pending.at(-1).reject(Error('denied'));
await failed;
ok(component.state.error && component.state.coverageWarning === '', 'failed refresh cannot retain previous warning');
const old = component.refresh();
const oldRequest = pending.at(-1);
const current = component.refresh();
pending.at(-1).resolve({ ...response, coverage_warning: '' });
await current;
oldRequest.resolve(response);
await old;
ok(component.state.coverageWarning === '', 'late stale response cannot restore warning');
scope.baseer_register_cash_month = '2026-09';
const cash = component.refresh();
ok(calls.at(-1)[1] === 'baseer_financial_register_cash_kpis', 'cash endpoint remains unchanged');
pending.at(-1).resolve({ currency_groups: [], as_of: '2026-09-30', company_name: 'ARZ' });
await cash;
ok(component.state.coverageWarning === '' && !component.state.error, 'cash payload without coverage metadata remains valid');
const result = { result: 'PASS', assertions: count, scope: 'FL3 coverage-warning state and unchanged Cash response compatibility; mocked frontend only.', checks };
fs.mkdirSync('docs/build-governance/fl3-ui', { recursive: true });
fs.writeFileSync('docs/build-governance/fl3-ui/frontend-checks.json', JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result));

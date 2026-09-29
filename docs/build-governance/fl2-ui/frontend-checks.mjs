// Run from the repository root. Isolated FL2 mode/month behavior; browser QA is separate.
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
ok(component.isCashMode && component.cashMonth === '2026-09', 'cash context selects cash mode');
const refresh = component.refresh();
ok(calls.at(-1)[1] === 'baseer_financial_register_cash_kpis', 'cash endpoint selected');
pending.at(-1).resolve({ currency_groups: [], as_of: '2026-09-10', cash_month: '2026-09', company_name: 'ARZ' });
await refresh;
ok(component.state.companyName === 'ARZ', 'server company displayed');
const open = component.openMode(true, '2026-08');
ok(calls.at(-1)[1] === 'action_open_register_cash' && calls.at(-1)[2][0] === '2026-08', 'month supplied only to server action');
ok(calls.at(-1)[3].context.allowed_company_ids[0] === 4, 'native company context forwarded');
const before = calls.length;
await component.openMode(false);
ok(calls.length === before, 'duplicate action blocked');
const payload = { type: 'ir.actions.act_window', context: { baseer_register_cash_month: '2026-08' } };
pending.at(-1).resolve(payload);
await open;
ok(actions[0] === payload, 'server action passed unchanged to action service');
const all = component.openMode(false);
ok(calls.at(-1)[1] === 'action_open_financial_register' && calls.at(-1)[2].length === 0, 'all operations uses native server action');
ok(JSON.stringify(calls.at(-1)[3].context.allowed_company_ids) === '[4,9]', 'all operations restores header-selected companies');
ok(JSON.stringify(scope.allowed_company_ids) === '[4]', 'cash context is not mutated');
pending.at(-1).resolve({ type: 'ir.actions.act_window', context: {} });
await all;
const target = { value: 'bad-month' };
await component.onMonthChange({ target });
ok(target.value === '2026-09', 'invalid input reset');
const failTarget = { value: '2026-07' };
const fail = component.onMonthChange({ target: failTarget });
pending.at(-1).reject(Error('denied'));
await fail;
ok(component.state.actionError && !component.state.changingMode && failTarget.value === '2026-09', 'failed navigation restores month and visible error');
const dying = component.openMode(true);
const previous = actions.length;
onDestroy();
pending.at(-1).resolve({ type: 'ir.actions.act_window' });
await dying;
ok(actions.length === previous, 'destroyed component cannot navigate');
const result = { result: 'PASS', assertions: count,
    scope: 'Isolated FL2 mode and month behavior with mocked hooks/services; FL1 native KeepLast suite is separate.', checks };
fs.writeFileSync('docs/build-governance/fl2-ui/frontend-checks.json', JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result));

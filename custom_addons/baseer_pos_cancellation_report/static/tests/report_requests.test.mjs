import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../src/report.js', import.meta.url), 'utf8')
    .replace(/^import .*;\s*$/gm, '').replace('export class ', 'class ');
const sandbox = {
    Component: class {}, Pager: class {}, DateTimeInput: class {}, luxon: { DateTime: {} },
    registry: { category: () => ({ add() {} }) }, _t: text => text,
};
vm.createContext(sandbox);
vm.runInContext(source + '\nthis.Report = CancellationFollowupReport;', sandbox);
const selection = { preset: 'month', month: '2026-10', day: '2026-10-01',
    date_from: '2026-10-01T00:00', date_to: '2026-11-01T00:00',
    morning_start: '06:00', evening_start: '18:00', pos_config_id: '', cashier_id: '',
    shift: 'all', event_type: 'all', review_only: false, offset: 0, limit: 50 };
const payload = (patch = {}) => ({ filters: { ...selection, ...patch }, pagination: { total: 123, offset: 0, limit: 50 }, marker: patch.marker });
function component(call, initial = payload()) {
    const report = Object.create(sandbox.Report.prototype);
    report.sequence = 0; report.disposed = false;
    report.state = { loading: false, error: '', filters: { ...selection }, payload: initial };
    report.orm = { call }; return report;
}
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }

let passed = 0;
{
    let requested;
    const report = component(async (_model, _method, [filters]) => { requested = filters; return payload({ offset: 50 }); });
    report.state.filters.cashier_id = '99'; report.state.filters.month = '2026-09';
    await report.updatePage({ offset: 50, limit: 50 });
    assert.equal(requested.cashier_id, false); assert.equal(requested.month, '2026-10'); assert.equal(requested.offset, 50);
    assert.equal(report.state.filters.cashier_id, '99'); assert.equal(report.state.filters.month, '2026-09'); passed++;
}
{
    const pending = deferred(); const report = component(() => pending.promise);
    const loading = report.load(); report.state.filters.cashier_id = '78';
    pending.resolve(payload()); await loading;
    assert.equal(report.state.filters.cashier_id, '78'); passed++;
}
{
    const first = deferred(), second = deferred(); let calls = 0;
    const report = component(() => (++calls === 1 ? first : second).promise);
    const one = report.load(), two = report.load();
    second.resolve(payload({ marker: 'new' })); await two;
    first.reject({ data: { name: 'odoo.exceptions.AccessError', message: 'old error' } }); await one;
    assert.equal(report.state.payload.marker, 'new'); assert.equal(report.state.error, ''); assert.equal(report.state.loading, false); passed++;
}
{
    const pending = deferred(), initial = payload({ marker: 'initial' }); const report = component(() => pending.promise, initial);
    const loading = report.load(); report.disposed = true; report.sequence++;
    pending.resolve(payload({ marker: 'after disposal' })); await loading;
    assert.equal(report.state.payload.marker, 'initial'); passed++;
}
{
    let requested; const report = component(async (_model, _method, [filters]) => { requested = filters; return payload({ cashier_id: 42 }); });
    report.state.filters.cashier_id = '42'; report.state.filters.offset = 50;
    await report.load(true); assert.equal(requested.cashier_id, 42); assert.equal(requested.offset, 0); assert.equal(report.state.filters.cashier_id, '42'); passed++;
}
{
    const report = component(async () => { throw { data: { name: 'odoo.exceptions.ValidationError', message: 'Invalid period' } }; });
    await report.load(); assert.equal(report.state.error, 'Invalid period'); assert.equal(report.state.loading, false); passed++;
}
{
    const requested = []; let fail = true;
    const report = component(async (_model, _method, [filters]) => {
        requested.push({ ...filters });
        if (fail) { fail = false; throw new Error('network'); }
        return payload(filters);
    });
    report.state.filters.month = '2026-09';
    await report.updatePage({ offset: 50, limit: 50 });
    await report.retry();
    assert.equal(requested[1].month, '2026-10');
    assert.equal(requested[1].offset, 50);
    assert.equal(report.state.filters.month, '2026-09');
    assert.equal(report.state.error, ''); passed++;
}
console.log(`REPORT_REQUEST_TESTS=PASS CASES=${passed}`);

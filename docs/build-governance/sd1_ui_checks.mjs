import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const path = 'custom_addons/baseer_sales_dashboard/static/src/sales_dashboard.js';
const original = fs.readFileSync(path, 'utf8');
const source = original.replace(/^import .*;\r?\n/gm, '').replace(/export (class|function) /g, '$1 ');
let services, unmounts;
const createdCharts = [];
class ChartStub {
    constructor(element, config) { this.element = element; this.config = config; createdCharts.push(this); }
    destroy() { this.destroyed = true; }
}
const { Dashboard, coordinate } = new Function(
    'Component', 'onWillStart', 'onWillUnmount', 'useRef', 'useState', 'useEffect', '_t', 'useService',
    'DateTimeInput', 'deserializeDate', 'serializeDate', 'localization', 'getColor', 'Chart', 'getComputedStyle',
    source + '\nreturn {Dashboard: BaseerSalesDashboard, coordinate: chartCoordinate};',
)(class {}, () => {}, fn => unmounts.push(fn), name => ({ el: { name } }), value => value, () => {},
    value => value, name => services[name], class {}, value => ({ iso: value }), value => value.iso,
    { direction: 'rtl' }, index => ['#123456', '#654321'][index], ChartStub, () => ({ fontFamily: 'native-font' }));

function deferred() {
    let resolve, reject;
    const promise = new Promise((r, j) => { resolve = r; reject = j; });
    return { promise, resolve, reject };
}
function fixture() {
    const calls = [], requests = [], actions = [];
    services = {
        orm: { call(...args) { calls.push(args); const request = deferred(); requests.push(request); return request.promise; } },
        action: { doAction(action) { actions.push(action); } },
    };
    unmounts = [];
    const dashboard = new Dashboard();
    dashboard.props = { dashboardId: 88 };
    dashboard.setup();
    return { dashboard, calls, requests, actions, unmounts: [...unmounts] };
}
function payload(tag = 'current', granularity = 'day') {
    const card = { value: '57.50', display: 'SERVER 57.50', available: true,
        comparison: { direction: 'up', display: 'SERVER 12.34%', available: true, previous_display: 'SERVER 51.18' } };
    return {
        tag, company: { id: 1, name: 'Company', currency: 'SAR' },
        filters: { preset: 'this_month', date_from: '2026-09-01', date_to: '2026-09-09', granularity },
        comparison_period: { date_from: '2026-08-01', date_to: '2026-08-09' },
        cards: Object.fromEntries(['sales', 'customers', 'daily_sales', 'daily_customers', 'average_bill'].map(k => [k, { ...card }])),
        coverage: { operating_days: 1, incomplete_days: 1, closed_days: 1, missing_days: 1 },
        issues: { missing_customers: false, missing_complete_customers: false },
        timeline: { granularity, points: [
            { key: 'first', label: '2026-09-01', sales: '0.00', sales_display: '0.00', customers: 0, customers_display: '0', status: 'complete' },
            { key: 'partial', label: '2026-09-02', sales: '115.15', sales_display: '115.15', customers: 5, customers_display: '5', status: 'incomplete' },
            { key: 'missing', label: '2026-09-03', sales: null, sales_display: '—', customers: null, customers_display: '—', status: 'missing' },
        ] },
        source_action: { type: 'ir.actions.act_window', res_model: 'baseer.pos.summary', domain: [['company_id', '=', 1]] },
    };
}
const R = { status: 'running', checks: [], source: path,
    source_sha256: crypto.createHash('sha256').update(original).digest('hex'),
    scope: 'Production Owl component methods with stubbed services/hooks/canvas and deferred ORM. Verifies UI concurrency and faithful presentation, not business formulas or browser layout/lifecycle.' };
async function check(name, fn) {
    try { await fn(); R.checks.push({ name, passed: true }); }
    catch (error) { R.checks.push({ name, passed: false }); throw error; }
}

try {
    const f = fixture();
    const first = f.dashboard.load();
    await check('native record endpoint receives only preset and dashboard record id', () => {
        assert.deepEqual(f.calls, [['spreadsheet.dashboard', 'get_baseer_sales_metrics', [[88], { preset: 'this_month' }]]]);
        assert.equal(f.dashboard.state.loading, true);
        assert.equal(f.dashboard.state.payload, null);
    });
    const initial = payload();
    f.requests[0].resolve(initial); await first;
    await check('five cards preserve backend values formatting and comparison without arithmetic', () => {
        assert.equal(f.dashboard.cards.length, 5);
        for (const card of f.dashboard.cards) {
            assert.equal(card.value, '57.50');
            assert.equal(card.display, 'SERVER 57.50');
            assert.deepEqual(card.comparison, initial.cards[card.key].comparison);
        }
        assert.equal(f.dashboard.periodLabel, '2026-09-01 — 2026-09-09');
        assert.equal(f.dashboard.comparisonLabel, '2026-08-01 — 2026-08-09');
        assert.equal(f.dashboard.state.loading, false);
    });
    f.dashboard.openSources();
    await check('source action opens the exact server domain', () => assert.deepEqual(f.actions, [initial.source_action]));
    const slow = f.dashboard.onPresetChange({ target: { value: 'this_year' } });
    await check('changing period removes previous payload immediately', () => {
        assert.equal(f.dashboard.state.payload, null);
        assert.equal(f.dashboard.state.loading, true);
        assert.deepEqual(f.calls[1][2][1], { preset: 'this_year' });
    });
    const fast = f.dashboard.onPresetChange({ target: { value: 'last_year' } });
    const newest = payload('newest', 'month');
    newest.timeline.points = [{ ...newest.timeline.points[1], key: '2025-01', label: '2025-01' }];
    f.requests[2].resolve(newest); await fast;
    f.requests[1].resolve(payload('obsolete')); await slow;
    await check('reversed response order cannot replace the latest selected period', () => {
        assert.equal(f.dashboard.state.payload.tag, 'newest');
        assert.equal(f.dashboard.state.preset, 'last_year');
        assert.equal(f.dashboard.state.loading, false);
    });
    await check('monthly grouping and exact backend point count pass through unchanged', () => {
        assert.equal(f.dashboard.granularityLabel, 'Monthly');
        assert.equal(f.dashboard.points.length, 1);
        assert.equal(f.dashboard.points[0].label, '2025-01');
    });
    const obsoleteError = f.dashboard.load();
    const latestSuccess = f.dashboard.load();
    f.requests[4].resolve(payload('latest-success')); await latestSuccess;
    f.requests[3].reject(new Error('obsolete server failure')); await obsoleteError;
    await check('obsolete failure cannot replace a newer successful result', () => {
        assert.equal(f.dashboard.state.payload.tag, 'latest-success');
        assert.equal(f.dashboard.state.error, '');
    });
    const interrupted = f.dashboard.load();
    f.dashboard.onPresetChange({ target: { value: 'custom' } });
    f.requests[5].resolve(payload('stale-during-date-edit')); await interrupted;
    await check('custom date draft invalidates a pending preset request without a new query', () => {
        assert.equal(f.calls.length, 6);
        assert.equal(f.dashboard.state.payload, null);
        assert.equal(f.dashboard.state.draft, true);
        assert.equal(f.dashboard.state.loading, false);
    });
    f.dashboard.onDateFrom({ iso: '2026-01-03' });
    f.dashboard.onDateTo({ iso: '2026-02-17' });
    const custom = f.dashboard.load();
    await check('custom dates serialize raw ISO input and leave period policy to backend', () => {
        assert.deepEqual(f.calls[6][2][1], { preset: 'custom', date_from: '2026-01-03', date_to: '2026-02-17' });
        assert.equal(f.dashboard.state.draft, false);
    });
    f.requests[6].reject({ data: { name: 'odoo.exceptions.ValidationError', message: 'Select no more than 366 days.' } });
    await custom;
    await check('current validation error is visible and leaves no stale numeric payload', () => {
        assert.equal(f.dashboard.state.error, 'Select no more than 366 days.');
        assert.equal(f.dashboard.state.payload, null);
        assert.equal(f.dashboard.state.loading, false);
    });
    const retry = f.dashboard.load();
    f.requests[7].resolve(payload('retry')); await retry;
    await check('refresh recovers after error with the same raw filters', () => {
        assert.equal(f.dashboard.state.payload.tag, 'retry');
        assert.equal(f.dashboard.state.error, '');
        assert.deepEqual(f.calls[7][2][1], f.calls[6][2][1]);
    });
    const disposed = f.dashboard.load();
    f.unmounts.forEach(fn => fn());
    f.requests[8].resolve(payload('after-navigation')); await disposed;
    await check('navigation away ignores an in-flight reply', () => {
        assert.equal(f.dashboard.disposed, true);
        assert.equal(f.dashboard.state.payload, null);
    });

    const chart = fixture();
    chart.dashboard.state.payload = payload();
    chart.dashboard.drawCharts();
    const [salesChart, customersChart] = chart.dashboard.charts;
    await check('chart coordinate adapter preserves null gaps and true zero values', () => {
        assert.equal(coordinate(null), null);
        assert.equal(coordinate('0.00'), 0);
        assert.deepEqual(salesChart.config.data.datasets[0].data, [0, 115.15, null]);
        assert.deepEqual(customersChart.config.data.datasets[0].data, [0, 5, null]);
        assert.equal(salesChart.config.data.datasets[0].spanGaps, false);
        assert.equal(salesChart.config.options.animation, false);
    });
    await check('partial periods use a distinct marker and tooltips use backend display strings', () => {
        assert.deepEqual(salesChart.config.data.datasets[0].pointStyle, ['circle', 'triangle', 'circle']);
        assert.equal(salesChart.config.options.plugins.tooltip.callbacks.label({ dataIndex: 1 }), 'Sales: 115.15');
        assert.equal(salesChart.config.options.plugins.tooltip.callbacks.afterLabel({ dataIndex: 1 }), 'Partial');
        assert.equal(salesChart.config.options.plugins.tooltip.rtl, true);
        assert.equal(salesChart.config.options.scales.y.ticks.callback(125), '125');
    });
    chart.dashboard.drawCharts();
    await check('redrawing destroys prior chart objects', () => {
        assert.equal(salesChart.destroyed, true);
        assert.equal(customersChart.destroyed, true);
        assert.equal(chart.dashboard.charts.length, 2);
    });
    chart.dashboard.state.payload.timeline.points = [{ ...payload().timeline.points[2] }];
    chart.dashboard.drawCharts();
    await check('empty periods draw no chart and do not turn gaps into zero', () => {
        assert.equal(chart.dashboard.hasRecordedData, false);
        assert.equal(chart.dashboard.charts.length, 0);
        assert.equal(chart.dashboard.points[0].sales, null);
    });
    await check('comparison arrows are labels only and do not recalculate percentages', () => {
        assert.equal(chart.dashboard.directionIcon('up'), 'fa-arrow-up');
        assert.equal(chart.dashboard.directionIcon('down'), 'fa-arrow-down');
        assert.equal(chart.dashboard.directionIcon('flat'), 'fa-minus');
        assert.equal(chart.dashboard.directionLabel('none'), 'Comparison unavailable');
    });
    R.status = 'passed';
} catch (error) {
    R.status = 'failed'; R.error = error.stack; process.exitCode = 1;
} finally {
    fs.writeFileSync('docs/build-governance/sd1-ui-checks.json', JSON.stringify(R, null, 2) + '\n');
    console.log(`${R.checks.filter(c => c.passed).length}/${R.checks.length} UI component checks ${R.status}`);
    if (R.error) { console.error(R.error); }
}

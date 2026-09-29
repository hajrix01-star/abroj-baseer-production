import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const path = 'custom_addons/baseer_sales_dashboard/static/src/sales_dashboard.js';
const original = fs.readFileSync(path, 'utf8');
const source = original.replace(/^import .*;\r?\n/gm, '').replace(/export (class|function) /g, '$1 ');
let services, unmounts, updates, effects;
const createdCharts = [];
class ChartStub {
    constructor(element, config) { this.element = element; this.config = config; createdCharts.push(this); }
    destroy() { this.destroyed = true; }
}
const { Dashboard, coordinate } = new Function(
    'Component', 'onWillStart', 'onWillUnmount', 'onWillUpdateProps', 'useRef', 'useState', 'useEffect', '_t', 'useService',
    'DateTimeInput', 'deserializeDate', 'serializeDate', 'localization', 'getColor', 'Chart', 'getComputedStyle',
    source + '\nreturn {Dashboard: BaseerSalesDashboard, coordinate: chartCoordinate};',
)(class {}, () => {}, fn => unmounts.push(fn), fn => updates.push(fn), name => ({ el: { name } }), value => value, (run, dependencies) => effects.push({ run, dependencies }),
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
    unmounts = []; updates = []; effects = [];
    const dashboard = new Dashboard();
    dashboard.props = { dashboardId: 88, dateFilter: { type: 'relative', period: 'month_to_date' } };
    dashboard.setup();
    return { dashboard, calls, requests, actions, unmounts: [...unmounts], effects: [...effects], update(dateFilter) {
        const next = { ...dashboard.props, dateFilter };
        updates.forEach(fn => fn(next)); dashboard.props = next;
    } };
}
function payload(tag = 'current', granularity = 'day') {
    const card = { value: '57.50', display: 'SERVER 57.50', available: true,
        comparison: { direction: 'up', display: 'SERVER 12.34%', available: true, previous_display: 'SERVER 51.18' } };
    return {
        tag, has_data: true, company: { id: 1, name: 'Company', currency: 'SAR' },
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
    scope: 'SD3 affected UI behavior only: tab/chart lifecycle, keyboard navigation, native filter races and server category formatting. Stubbed Owl/services/canvas; browser layout and actual DOM mounting remain separate QA.' };
async function check(name, fn) {
    try { await fn(); R.checks.push({ name, passed: true }); }
    catch (error) { R.checks.push({ name, passed: false }); throw error; }
}

try {
    const f = fixture(); f.dashboard.state.payload = payload();
    const card = (value, display) => ({ value, display, available: true });
    const current = f.dashboard.state.payload;
    current.shift_performance = { rows: [{ key: 'morning', label: 'Morning', has_data: true,
        cards: { sales: card('115.15', 'SERVER 115.15'), customers: card(5, 'SERVER 5'), average_bill: card('23.03', 'SERVER 23.03') } }] };
    current.payment_performance = { rows: [{ method_id: 9, name: 'Cash', sales: card('115.15', 'SERVER 115.15') }],
        coverage: { complete: true }, categories: [{ category_id: 2, name: 'Cash category', kind: 'cash', sales: card('115.15', 'SERVER 115.15') }] };
    await check('both cards default to Chart with accessible translated tab labels', () => {
        assert.equal(f.dashboard.state.shiftTab, 'chart'); assert.equal(f.dashboard.state.paymentTab, 'chart');
        assert.deepEqual(f.dashboard.tabs, [{ key: 'chart', label: 'Chart view' }, { key: 'details', label: 'Details' }]);
        assert.notEqual(f.dashboard.tabId('shift', 'chart'), f.dashboard.tabId('payment', 'chart'));
        assert.notEqual(f.dashboard.panelId('shift'), f.dashboard.panelId('payment'));
    });
    f.dashboard.drawCharts(); const initialCharts = [...f.dashboard.charts];
    await check('default panels create one timeline and the two real source charts', () => {
        assert.equal(initialCharts.length, 3);
        assert.deepEqual(initialCharts[1].config.data.datasets[0].data, [115.15]);
        assert.deepEqual(initialCharts[2].config.data.datasets[0].data, [115.15]);
    });
    const beforeDeps = f.effects[0].dependencies();
    f.dashboard.selectTab('shift', 'details'); f.dashboard.drawCharts();
    await check('Details destroys old instances and excludes hidden shift canvas even if a ref remains', () => {
        assert.ok(initialCharts.every(chart => chart.destroyed));
        assert.equal(f.dashboard.charts.length, 2);
        assert.ok(!f.dashboard.charts.some(chart => chart.element.name === 'shiftChart'));
        assert.notDeepEqual(f.effects[0].dependencies(), beforeDeps);
    });
    f.dashboard.selectTab('payment', 'details'); f.dashboard.drawCharts();
    await check('both Details panels retain only timeline without ORM requests or payload mutation', () => {
        assert.equal(f.dashboard.charts.length, 1); assert.equal(f.calls.length, 0);
        assert.equal(f.dashboard.state.payload, current); assert.equal(f.dashboard.categoryRows, current.payment_performance.categories);
    });
    f.dashboard.onShiftMetricChange({ target: { value: 'customers' } });
    f.dashboard.selectTab('shift', 'chart'); f.dashboard.selectTab('payment', 'chart'); f.dashboard.drawCharts();
    await check('returning to Chart recreates current selected metric from existing server values', () => {
        assert.equal(f.dashboard.charts.length, 3);
        assert.ok(f.dashboard.charts.every(chart => !initialCharts.includes(chart)));
        assert.deepEqual(f.dashboard.charts[1].config.data.datasets[0].data, [5]);
        assert.equal(f.calls.length, 0);
    });
    let focused = '', prevented = 0;
    const key = (name) => ({ key: name, preventDefault() { prevented++; }, currentTarget: {
        parentElement: { querySelector(selector) { return { focus() { focused = selector; } }; } },
    } });
    await check('tab keyboard End Home and arrows select and focus a local tab', () => {
        f.dashboard.onTabKeydown(key('End'), 'shift');
        assert.equal(f.dashboard.state.shiftTab, 'details'); assert.equal(focused, '[data-view="details"]');
        f.dashboard.onTabKeydown(key('Home'), 'shift'); assert.equal(f.dashboard.state.shiftTab, 'chart');
        f.dashboard.onTabKeydown(key('ArrowLeft'), 'shift'); assert.equal(f.dashboard.state.shiftTab, 'details');
        f.dashboard.onTabKeydown(key('ArrowRight'), 'shift'); assert.equal(f.dashboard.state.shiftTab, 'chart');
        assert.equal(prevented, 4); assert.equal(f.dashboard.state.paymentTab, 'chart');
    });
    await check('unknown tab values and unrelated keys leave state and normal navigation unchanged', () => {
        f.dashboard.selectTab('shift', '__proto__'); f.dashboard.selectTab('unknown', 'details');
        f.dashboard.onTabKeydown(key('Tab'), 'shift');
        assert.equal(f.dashboard.state.shiftTab, 'chart'); assert.equal(f.dashboard.state.unknownTab, undefined);
        assert.equal(prevented, 4);
    });
    await check('category footer preserves authoritative identity formatting and no client totals', () => {
        assert.equal(f.dashboard.categoryRows, current.payment_performance.categories);
        assert.equal(f.dashboard.categoryRows[0].sales.display, 'SERVER 115.15');
        current.payment_performance.categories = [];
        assert.deepEqual(f.dashboard.categoryRows, []);
    });
    const race = fixture(); race.dashboard.selectTab('payment', 'details');
    const old = race.dashboard.load(); race.update({ type: 'relative', period: 'last_month' });
    race.requests[1].resolve(payload('new')); await Promise.resolve(); await Promise.resolve();
    race.requests[0].resolve(payload('old')); await old;
    await check('native date changes preserve local tabs while stale replies cannot revive old data', () => {
        assert.equal(race.dashboard.state.payload.tag, 'new'); assert.equal(race.dashboard.state.paymentTab, 'details');
        assert.equal(race.calls.length, 2); assert.equal(race.dashboard.state.loading, false);
    });
    await check('template replaces chart with details and retains warnings while removing permanent prose and method category', () => {
        const xml = fs.readFileSync('custom_addons/baseer_sales_dashboard/static/src/sales_dashboard.xml', 'utf8');
        R.xml_sha256 = crypto.createHash('sha256').update(xml).digest('hex');
        assert.match(xml, /state.shiftTab === 'chart'/); assert.match(xml, /state.paymentTab === 'chart'/);
        assert.match(xml, /role="tablist"/); assert.match(xml, /role="tabpanel"/); assert.match(xml, /t-att-aria-selected=/);
        assert.match(xml, /t-esc="labels.paymentIncomplete"/); assert.match(xml, /t-esc="labels.customerWarning"/);
        assert.doesNotMatch(xml, /labels\.(basis|shiftNote|paymentNote|timelineNote)|row.category.name/);
        assert.match(xml, /t-esc="category.sales.display"/);
        assert.ok(xml.indexOf('o_baseer_sales_category_footer') > xml.indexOf('</details>'));
    });
    const empty = fixture(); empty.dashboard.state.payload = { ...payload(), has_data: false }; empty.dashboard.drawCharts();
    await check('empty report keeps Chart defaults and creates no decorative data instances', () => {
        assert.equal(empty.dashboard.charts.length, 0); assert.equal(empty.dashboard.state.shiftTab, 'chart');
        assert.equal(empty.dashboard.state.paymentTab, 'chart'); assert.deepEqual(empty.dashboard.categoryRows, []);
    });
    R.status = 'passed';
} catch (error) {
    R.status = 'failed'; R.error = error.stack; process.exitCode = 1;
} finally {
    fs.writeFileSync('docs/build-governance/sd3-ui-checks.json', JSON.stringify(R, null, 2) + '\n');
    console.log(`${R.checks.filter(c => c.passed).length}/${R.checks.length} SD3 component checks ${R.status}`);
    if (R.error) { console.error(R.error); }
}

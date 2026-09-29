import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const path = 'custom_addons/baseer_sales_dashboard/static/src/sales_dashboard.js';
const original = fs.readFileSync(path, 'utf8');
const source = original.replace(/^import .*;\r?\n/gm, '').replace(/export (class|function) /g, '$1 ');
let services, unmounts, updates;
const createdCharts = [];
class ChartStub {
    constructor(element, config) { this.element = element; this.config = config; createdCharts.push(this); }
    destroy() { this.destroyed = true; }
}
const { Dashboard, coordinate } = new Function(
    'Component', 'onWillStart', 'onWillUnmount', 'onWillUpdateProps', 'useRef', 'useState', 'useEffect', '_t', 'useService',
    'DateTimeInput', 'deserializeDate', 'serializeDate', 'localization', 'getColor', 'Chart', 'getComputedStyle',
    source + '\nreturn {Dashboard: BaseerSalesDashboard, coordinate: chartCoordinate};',
)(class {}, () => {}, fn => unmounts.push(fn), fn => updates.push(fn), name => ({ el: { name } }), value => value, () => {},
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
    unmounts = []; updates = [];
    const dashboard = new Dashboard();
    dashboard.props = { dashboardId: 88, dateFilter: { type: 'relative', period: 'month_to_date' } };
    dashboard.setup();
    return { dashboard, calls, requests, actions, unmounts: [...unmounts], update(dateFilter) {
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
    scope: 'Production Owl component methods with stubbed services/hooks/canvas and deferred ORM. Verifies UI concurrency and faithful presentation, not business formulas or browser layout/lifecycle.' };
async function check(name, fn) {
    try { await fn(); R.checks.push({ name, passed: true }); }
    catch (error) { R.checks.push({ name, passed: false }); throw error; }
}

try {
    const settle = async () => { await Promise.resolve(); await Promise.resolve(); };
    const f = fixture();
    const first = f.dashboard.load();
    await check('native record endpoint receives unmodified native date intent', () => {
        assert.deepEqual(f.calls, [['spreadsheet.dashboard', 'get_baseer_sales_metrics', [[88], { native: { type: 'relative', period: 'month_to_date' } }]]]);
        assert.equal(f.dashboard.state.loading, true);
        assert.equal(f.dashboard.state.payload, null);
    });
    const initial = payload(); f.requests[0].resolve(initial); await first;
    await check('five cards preserve backend values formatting and comparison without arithmetic', () => {
        assert.equal(f.dashboard.cards.length, 5);
        for (const card of f.dashboard.cards) {
            assert.equal(card.value, '57.50'); assert.equal(card.display, 'SERVER 57.50');
            assert.deepEqual(card.comparison, initial.cards[card.key].comparison);
        }
        assert.equal(f.dashboard.periodLabel, '2026-09-01 — 2026-09-09');
        assert.equal(f.dashboard.comparisonLabel, '2026-08-01 — 2026-08-09');
    });
    f.dashboard.openSources();
    await check('source action opens exact server domain', () => assert.deepEqual(f.actions, [initial.source_action]));
    f.update({ type: 'year', year: 2025 });
    await check('native prop update clears stale payload immediately and loads next props', () => {
        assert.equal(f.dashboard.state.payload, null); assert.equal(f.dashboard.state.loading, true);
        assert.deepEqual(f.calls[1][2][1], { native: { type: 'year', year: 2025 } });
    });
    f.update({ type: 'relative', period: 'last_30_days' });
    const newest = payload('newest', 'month');
    newest.timeline.points = [{ ...newest.timeline.points[1], key: '2025-01', label: '2025-01' }];
    f.requests[2].resolve(newest); await settle();
    f.requests[1].resolve(payload('obsolete')); await settle();
    await check('reversed native filter replies cannot replace latest payload', () => {
        assert.equal(f.dashboard.state.payload.tag, 'newest'); assert.equal(f.dashboard.state.loading, false);
        assert.equal(f.dashboard.granularityLabel, 'Monthly'); assert.equal(f.dashboard.points.length, 1);
    });
    f.update(f.dashboard.props.dateFilter);
    await check('unchanged filter reference does not query again', () => assert.equal(f.calls.length, 3));
    f.update(undefined);
    await check('native all time sends explicit null without client date truncation', () => assert.deepEqual(f.calls[3][2][1], { native: null }));
    f.update({ type: 'range', from: '2020-01-01' });
    f.requests[4].resolve(payload('open-range')); await settle();
    f.requests[3].reject(new Error('obsolete failure')); await settle();
    await check('open native range passes through and obsolete failure stays hidden', () => {
        assert.deepEqual(f.calls[4][2][1], { native: { type: 'range', from: '2020-01-01' } });
        assert.equal(f.dashboard.state.error, ''); assert.equal(f.dashboard.state.payload.tag, 'open-range');
    });
    const failed = f.dashboard.load();
    f.requests[5].reject({ data: { name: 'odoo.exceptions.ValidationError', message: 'Narrow this date range.' } }); await failed;
    await check('capacity or validation failure remains an error rather than empty preview', () => {
        assert.equal(f.dashboard.state.error, 'Narrow this date range.');
        assert.equal(f.dashboard.state.payload, null); assert.equal(f.dashboard.state.loading, false);
    });
    const retry = f.dashboard.load(); f.requests[6].resolve(payload('retry')); await retry;
    await check('refresh retains native intent after a failure', () => {
        assert.deepEqual(f.calls[6][2][1], f.calls[5][2][1]); assert.equal(f.dashboard.state.error, '');
    });
    const disposed = f.dashboard.load(); f.unmounts.forEach(fn => fn());
    f.requests[7].resolve(payload('after-navigation')); await disposed;
    await check('navigation ignores an in-flight reply', () => {
        assert.equal(f.dashboard.disposed, true); assert.equal(f.dashboard.state.payload, null);
    });

    const chart = fixture();
    chart.dashboard.state.payload = payload();
    chart.dashboard.drawCharts();
    const [salesChart] = chart.dashboard.charts;
    const sales = salesChart.config.data.datasets[0];
    const customers = salesChart.config.data.datasets[1];
    await check('chart coordinate adapter preserves null gaps and true zero values', () => {
        assert.equal(coordinate(null), null);
        assert.equal(coordinate('0.00'), 0);
        assert.deepEqual(salesChart.config.data.datasets[0].data, [0, 115.15, null]);
        assert.deepEqual(customers.data, [0, 5, null]);
        assert.equal(salesChart.config.data.datasets[0].spanGaps, false);
        assert.equal(salesChart.config.options.animation, false);
    });
    await check('partial periods use a distinct marker and tooltips use backend display strings', () => {
        assert.deepEqual(customers.pointStyle, ['circle', 'triangle', 'circle']);
        assert.equal(salesChart.config.options.plugins.tooltip.callbacks.label({ dataIndex: 1, dataset: sales }), 'Sales (SAR): 115.15');
        assert.equal(salesChart.config.options.plugins.tooltip.callbacks.afterLabel({ dataIndex: 1 }), 'Partial');
        assert.equal(salesChart.config.options.plugins.tooltip.rtl, true);
        assert.equal(salesChart.config.options.scales.sales.ticks.callback(125), '125');
    });
    chart.dashboard.drawCharts();
    await check('redrawing destroys prior chart objects', () => {
        assert.equal(salesChart.destroyed, true);
        assert.equal(chart.dashboard.charts.length, 1);
    });
    chart.dashboard.state.payload.timeline.points = [{ ...payload().timeline.points[2] }];
    chart.dashboard.state.payload.has_data = false;
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
    await check('mixed chart has bar and line series with separately named currency and count axes', () => {
        assert.equal(sales.type, 'bar'); assert.equal(customers.type, 'line');
        assert.equal(sales.yAxisID, 'sales'); assert.equal(customers.yAxisID, 'customers');
        assert.equal(salesChart.config.options.scales.sales.position, 'left');
        assert.equal(salesChart.config.options.scales.customers.position, 'right');
        assert.equal(salesChart.config.options.scales.sales.title.text, 'Sales (SAR)');
        assert.equal(salesChart.config.options.scales.customers.title.text, 'Customers (count)');
        assert.equal(salesChart.config.options.plugins.legend.display, true);
        assert.equal(salesChart.config.options.plugins.tooltip.callbacks.label({ dataIndex: 1, dataset: customers }), 'Customers (count): 5');
    });
    await check('empty cards cannot expose sample or stale amounts and illustration never creates a chart', () => {
        assert.ok(chart.dashboard.cards.every(card => card.display === '—'));
        assert.equal(chart.dashboard.charts.length, 0);
        assert.equal(chart.dashboard.state.payload.cards.sales.display, 'SERVER 57.50');
        assert.equal(chart.dashboard.labels.preview, 'No data yet — illustrative preview');
    });
    await check('approved true zero uses real chart rather than preview', () => {
        chart.dashboard.state.payload = payload();
        chart.dashboard.state.payload.timeline.points = [{ ...payload().timeline.points[0] }];
        chart.dashboard.drawCharts();
        assert.equal(chart.dashboard.hasRecordedData, true);
        assert.equal(chart.dashboard.charts.length, 1);
        assert.deepEqual(chart.dashboard.charts[0].config.data.datasets[0].data, [0]);
        assert.deepEqual(chart.dashboard.charts[0].config.data.datasets[1].data, [0]);
        assert.equal(chart.dashboard.cards[0].display, 'SERVER 57.50');
    });
    await check('empty preview markup is decorative and independent of numeric payload', () => {
        const xml = fs.readFileSync('custom_addons/baseer_sales_dashboard/static/src/sales_dashboard.xml', 'utf8');
        const svg = xml.match(/<svg[\s\S]*?<\/svg>/)[0];
        assert.match(svg, /aria-hidden="true"/);
        assert.match(svg, /focusable="false"/);
        assert.doesNotMatch(svg, /t-esc|t-on-|<text|canvas|title=/);
        assert.match(xml, /t-esc="labels.preview"/);
    });
    const shift = fixture(); shift.dashboard.state.payload = payload();
    const money = (value, display, available = true) => ({ value, display, available });
    const rows = [
        { key: 'morning', label: 'Morning', has_data: true, cards: { sales: money('115.15', 'SERVER 115.15'), customers: money(5, 'SERVER 5'), average_bill: money('23.03', 'SERVER 23.03') }, source_action: { domain: [['period_scope', '=', 'morning']] } },
        { key: 'evening', label: 'Evening', has_data: true, cards: { sales: money('0.00', '0.00'), customers: money(0, '0'), average_bill: money(null, '—', false) } },
        { key: 'all', label: 'Full day', has_data: false, cards: { sales: money(null, '—', false), customers: money(null, '—', false), average_bill: money(null, '—', false) } },
    ];
    shift.dashboard.state.payload.shift_performance = { rows };
    shift.dashboard.drawCharts();
    await check('shift chart preserves source categories nulls and approved zero', () => {
        assert.equal(shift.dashboard.shiftRows, rows);
        const c = shift.dashboard.charts[1].config;
        assert.deepEqual(c.data.labels, ['Morning', 'Evening', 'Full day']);
        assert.deepEqual(c.data.datasets[0].data, [115.15, 0, null]);
        assert.equal(c.options.plugins.tooltip.callbacks.label({ dataIndex: 0 }), 'Sales (SAR): SERVER 115.15');
    });
    shift.dashboard.onShiftMetricChange({ target: { value: 'average_bill' } });
    shift.dashboard.drawCharts();
    await check('shift metric switch uses server ratio without a request or arithmetic', () => {
        assert.equal(shift.calls.length, 0);
        assert.deepEqual(shift.dashboard.charts[1].config.data.datasets[0].data, [23.03, null, null]);
        assert.equal(shift.dashboard.charts[1].config.options.plugins.tooltip.callbacks.label({ dataIndex: 0 }), 'Average bill (SAR): SERVER 23.03');
    });
    shift.dashboard.onShiftMetricChange({ target: { value: 'customers' } }); shift.dashboard.drawCharts();
    await check('customer shift view uses count axis and exact server values', () => {
        assert.deepEqual(shift.dashboard.charts[1].config.data.datasets[0].data, [5, 0, null]);
        assert.equal(shift.dashboard.charts[1].config.options.scales.y.ticks.precision, 0);
        shift.dashboard.onShiftMetricChange({ target: { value: '__proto__' } });
        assert.equal(shift.dashboard.state.shiftMetric, 'customers');
    });
    shift.dashboard.openShiftSources(rows[0]); shift.dashboard.openShiftSources(rows[2]);
    await check('shift source navigation uses server action only for a recorded category', () => assert.deepEqual(shift.actions, [rows[0].source_action]));
    await check('empty all-time date bounds and unavailable comparison never render null text', () => {
        const empty = fixture(); empty.dashboard.state.payload = payload();
        empty.dashboard.state.payload.filters = { date_from: null, date_to: null };
        empty.dashboard.state.payload.comparison_period = { date_from: null, date_to: null };
        assert.equal(empty.dashboard.periodLabel, ''); assert.equal(empty.dashboard.comparisonLabel, '');
    });
    const payment = fixture(); payment.dashboard.state.payload = payload();
    const paymentRows = [
        { method_id: 7, name: 'Cash', category: { id: 1, name: 'Cash', kind: 'cash' }, sales: money('80.00', 'SERVER 80.00'), share: money('69.47', 'SERVER 69.47'), source_action: { res_model: 'baseer.pos.summary.allocation', domain: [['payment_method_id', '=', 7]] } },
        { method_id: 8, name: 'Card', category: { id: 2, name: 'Card', kind: 'bank' }, sales: money('35.15', 'SERVER 35.15'), share: money('30.53', 'SERVER 30.53') },
    ];
    const coverage = { complete: true, summary_count: 2, covered_summary_count: 2,
        missing_summary_count: 0, mismatched_summary_count: 0,
        covered_sales: money('115.15', 'SERVER 115.15'), uncovered_sales: money('0.00', '0.00') };
    payment.dashboard.state.payload.payment_performance = { rows: paymentRows, coverage };
    payment.dashboard.drawCharts();
    await check('payment chart uses recorded method identity and exact server allocation amounts', () => {
        assert.equal(payment.dashboard.paymentRows, paymentRows);
        assert.equal(payment.dashboard.paymentCoverage, coverage);
        const c = payment.dashboard.charts[1].config;
        assert.equal(c.options.indexAxis, 'y'); assert.deepEqual(c.data.labels, ['Cash', 'Card']);
        assert.deepEqual(c.data.datasets[0].data, [80, 35.15]);
        assert.equal(c.options.plugins.tooltip.callbacks.label({ dataIndex: 1 }), 'Sales (SAR): SERVER 35.15');
        assert.equal(paymentRows[0].share.display, 'SERVER 69.47'); assert.equal(payment.calls.length, 0);
    });
    payment.dashboard.openPaymentSources(paymentRows[0]);
    await check('payment navigation preserves exact server allocation action', () => assert.deepEqual(payment.actions, [paymentRows[0].source_action]));
    coverage.complete = false; coverage.missing_summary_count = 1;
    paymentRows.forEach(row => { row.share = money(null, '—', false); });
    payment.dashboard.drawCharts();
    await check('partial coverage retains verified amounts and unavailable server shares with visible warning', () => {
        assert.equal(payment.dashboard.paymentCoverage.complete, false);
        assert.ok(payment.dashboard.paymentRows.every(row => row.share.display === '—'));
        assert.deepEqual(payment.dashboard.charts[1].config.data.datasets[0].data, [80, 35.15]);
        const xml = fs.readFileSync('custom_addons/baseer_sales_dashboard/static/src/sales_dashboard.xml', 'utf8');
        assert.match(xml, /t-if="!paymentCoverage.complete"/);
        assert.match(xml, /t-esc="labels.paymentIncomplete"/);
        assert.match(xml, /t-esc="paymentCoverage.uncovered_sales.display"/);
    });
    payment.dashboard.state.payload.payment_performance.rows = [];
    payment.dashboard.drawCharts();
    await check('missing allocation rows create neither fake methods nor a payment chart', () => {
        assert.equal(payment.dashboard.paymentRows.length, 0);
        assert.equal(payment.dashboard.charts.length, 1);
        assert.equal(payment.dashboard.paymentCoverage.missing_summary_count, 1);
    });
    payment.dashboard.state.payload.payment_performance.rows = [{ ...paymentRows[0], sales: money('0.00', '0.00') }];
    payment.dashboard.drawCharts();
    await check('recorded zero allocation remains a real zero coordinate', () => assert.deepEqual(payment.dashboard.charts[1].config.data.datasets[0].data, [0]));
    const integrationPath = 'custom_addons/baseer_sales_dashboard/static/src/dashboard_integration.js';
    const integration = fs.readFileSync(integrationPath, 'utf8');
    R.integration_sha256 = crypto.createHash('sha256').update(integration).digest('hex');
    const adapterSource = integration.slice(0, integration.indexOf('patch(DashboardLoader.prototype'))
        .replace(/^import .*;\r?\n/gm, '').replace(/export (class|function) /g, '$1 ');
    const originalDate = { iso: '2026-09-01', numberingSystem: 'arab', reconfigure(config) { return { ...this, ...config }; } };
    class NativeDateDropdown {
        getDescription() { return 'سبتمبر ٢٠٢٦'; }
        dateFrom() { return originalDate; }
        dateTo() { return undefined; }
        update(value) { return value; }
    }
    class NativeDashboardDate {
        static components = { DateFilterDropdown: NativeDateDropdown };
        get inputValue() { return '٠١/٠٩/٢٠٢٦ — ۳۰/۰۹/۲۰۲۶'; }
    }
    const adapters = new Function('DashboardDateFilter', 'DateFilterDropdown', adapterSource +
        '\nreturn {westernDateDigits, BaseerDateFilterDropdown, BaseerDashboardDateFilter};')(NativeDashboardDate, NativeDateDropdown);
    await check('scoped native filter normalizes Arabic and Persian digits without translating month text', () => {
        assert.equal(new adapters.BaseerDateFilterDropdown().getDescription('month'), 'سبتمبر 2026');
        assert.equal(new adapters.BaseerDashboardDateFilter().inputValue, '01/09/2026 — 30/09/2026');
        assert.equal(adapters.westernDateDigits('September 2026'), 'September 2026');
    });
    await check('native range dates retain ISO semantics while configuring display digits immutably', () => {
        const dropdown = new adapters.BaseerDateFilterDropdown();
        assert.equal(dropdown.dateFrom().iso, '2026-09-01');
        assert.equal(dropdown.dateFrom().numberingSystem, 'latn');
        assert.equal(originalDate.numberingSystem, 'arab');
        assert.equal(dropdown.dateTo(), undefined);
        const raw = { type: 'range', from: '2026-09-01', to: '' };
        assert.equal(dropdown.update(raw), raw);
    });
    await check('format adapter replaces only its own native child without patching shared picker classes', () => {
        assert.equal(NativeDashboardDate.components.DateFilterDropdown, NativeDateDropdown);
        assert.equal(adapters.BaseerDashboardDateFilter.components.DateFilterDropdown, adapters.BaseerDateFilterDropdown);
        assert.equal(adapters.BaseerDateFilterDropdown.prototype.update, NativeDateDropdown.prototype.update);
    });
    await check('local native range template keys changed dates to discard retained locale editing text', () => {
        assert.equal(adapters.BaseerDateFilterDropdown.template, 'baseer_sales_dashboard.DateFilterDropdown');
        const xml = fs.readFileSync('custom_addons/baseer_sales_dashboard/static/src/dashboard_integration.xml', 'utf8');
        R.integration_xml_sha256 = crypto.createHash('sha256').update(xml).digest('hex');
        assert.match(xml, /t-name="baseer_sales_dashboard.DateFilterDropdown" t-inherit="spreadsheet.DateFilterDropdown" t-inherit-mode="primary"/);
        assert.match(xml, /name="t-key">selectedValues.range.from</);
        assert.match(xml, /name="t-key">selectedValues.range.to</);
    });
    R.status = 'passed';
} catch (error) {
    R.status = 'failed'; R.error = error.stack; process.exitCode = 1;
} finally {
    fs.writeFileSync('docs/build-governance/sd2-ui-checks.json', JSON.stringify(R, null, 2) + '\n');
    console.log(`${R.checks.filter(c => c.passed).length}/${R.checks.length} UI component checks ${R.status}`);
    if (R.error) { console.error(R.error); }
}

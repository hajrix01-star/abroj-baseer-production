import { after, expect, getFixture, globals, test, withFetch, click, press } from '@odoo/hoot';
import { animationFrame } from '@odoo/hoot-mock';
import { App, Component, useState, xml } from '@odoo/owl';
import { DashboardTooltip, dashboardTooltip } from '../src/js/tooltip';
import { monthLabel, plainCsvText, periodRange, hourLabel, hasDisplayValues, multiplePoints, formatNumber, formatTable, formatPnlAmount, hasPnlValues, formatTablePct, formatPercent, formatPoints, ratioDifference, formatTargetPercent, chartX, miniX, timelineYear, customerCutoverLabel, pnlTaxLabel, Dashboard2, DashboardPnlDetails, InfoPopup, LineChart, niceStep, KpiCard, Sparkline, Badge, Gauge } from '../src/js/main';

test('other expense is drillable and exported after operating profit', async () => {
    const row = (key, name, amount) => ({key, name, months:[amount], total:amount, pct:null, children:[]});
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        state = {view:'pnl', pnl_view:'month', closed:{}, data:{pnl_columns:[{month:'2026-10'}], rows:[
            row('operating_profit', 'الربح التشغيلي', 83),
            row('other_expense', 'المصروفات الأخرى', -13), row('net_profit', 'صافي الربح', 72.36)]}};
        trend = []; hasPnlValues = hasPnlValues; hasDisplayValues = hasDisplayValues;
        pnlFmt = formatPnlAmount; tableFmt = formatTable; tablePct = formatTablePct;
        name = v => v; monthName = v => v; pnlDrillable = Dashboard2.prototype.pnlDrillable;
        toggleRow() {} exportCsv() {} choose() {} drillPnl() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Pnl, {templates: await response.text(), test:true});
    after(() => app.destroy());
    await app.mount(getFixture());
    const table = getFixture().querySelector('.export-table');
    expect(table.textContent).toInclude('المصروفات الأخرى');
    expect(Dashboard2.prototype.pnlDrillable('other_expense', null)).toBe(true);
    getFixture().classList.add('o_bd2');
    const createUrl = URL.createObjectURL, anchorClick = HTMLAnchorElement.prototype.click;
    let exported;
    try {
        URL.createObjectURL = blob => { exported = blob; return 'blob:test'; };
        HTMLAnchorElement.prototype.click = () => {};
        Dashboard2.prototype.exportCsv.call({state:{view:'pnl'}, pnlTaxLabel:'شامل الضريبة'});
        const csv = await exported.text();
        expect(csv).toInclude('المصروفات الأخرى');
        expect(csv).toInclude('(13.00)');
        expect(csv.indexOf('الربح التشغيلي') < csv.indexOf('المصروفات الأخرى')).toBe(true);
        expect(csv.indexOf('المصروفات الأخرى') < csv.indexOf('صافي الربح')).toBe(true);
    } finally {
        URL.createObjectURL = createUrl;
        HTMLAnchorElement.prototype.click = anchorClick;
        getFixture().classList.remove('o_bd2');
    }
});

test('month labels support full, short, year, bidi isolation and plain CSV', () => {
    expect(monthLabel('2026-10')).toBe('October');
    expect(monthLabel('2026-11', { short: true, year: true })).toBe('Nov 2026');
    const mixed = monthLabel('2026-11', { partial: true, isolate: true });
    expect(mixed).toBe('\u2068November (جزئي)\u2069');
    expect(plainCsvText(mixed)).toBe('November (جزئي)');
});

test('mini chart drills use the plotted month and exclude mixed sources and averages', () => {
    const context = {state: {period: {mode: 'range', date_to: '2026-10-20'}, data: {sales: {trend: [{source_counts: {summary: 1, pos: 1}}, {source_counts: {summary: 1, pos: 0}}]}}}};
    expect(Dashboard2.prototype.monthPeriod.call(context, '2026-10')).toEqual({mode:'range', date_from:'2026-10-01', date_to:'2026-10-20'});
    expect(Dashboard2.prototype.miniDrillable.call(context, 1, 0, false)).toBe(false);
    expect(Dashboard2.prototype.miniDrillable.call(context, 1, 1, false)).toBe(true);
    expect(Dashboard2.prototype.miniDrillable.call(context, 2, 1, true)).toBe(false);
});

test('P&L renders without in/out months', async () => {
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        pnlDrillable = Dashboard2.prototype.pnlDrillable;
        state = useState({ view: 'pnl', tax_inclusive: true, data: { rows: [] }, closed: {} });
        trend = [];
        get pnlTaxLabel() { return pnlTaxLabel(this.state.tax_inclusive, 'ar_001'); }
        choose(key, value) { this.state[key] = value; }
        exportCsv() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    expect(response.ok).toBe(true);
    const app = new App(Pnl, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.export-table')).not.toBe(null);
    const toggle = getFixture().querySelector('[role="switch"]');
    expect(toggle.textContent.trim()).toBe('شامل الضريبة');
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    await click(toggle);
    await animationFrame();
    expect(toggle.textContent.trim()).toBe('غير شامل الضريبة');
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(pnlTaxLabel(true, 'en_US')).toBe('Tax inclusive');
    expect(pnlTaxLabel(false, 'en_US')).toBe('Tax exclusive');
});

test('ratios render a numeric gauge target', async () => {
    class Ratios extends Component {
        static template = 'baseer_dashboard2.Ratios';
        static components = { Badge, Gauge, Sparkline, LineChart };
        state = { period: { month: '2026-10' }, data: { targets: { food_pct: { value: 32.25, operator: 'le', status: 'ok' } }, previous: { ratios: {} } } };
        current = { ratios: { food_pct: 30 } };
        trend = []; trendLabels = [];
        name = (v) => v; monthName = (v) => v; pct = formatPercent; fmt = formatNumber; ratioDifference = ratioDifference; targetPercent = formatTargetPercent;
        changeValue() { return null; }
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Ratios, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.gauge-target').textContent).toInclude('≤32.3%');
    const scale = getFixture().querySelector('.gauge-scale');
    expect([...scale.children].map(el => el.textContent)).toEqual(['50%', '0%']);
});

test('numbers use Western digits without abbreviating calendar values', () => {
    expect(formatNumber(26827)).toBe('26,827');
    expect(formatNumber(null)).toBe('—');
});
test('chart time positions run from right to left', () => {
    expect(chartX(0, 6)).toBeGreaterThan(chartX(5, 6));
});

test('table values use accounting notation', () => {
    expect(formatTable(0)).toBe('—');
    expect(formatTable(-1234)).toBe('(1,234)');
    expect(formatTable(null)).toBe('—');
    expect(formatTable(undefined)).toBe('—');
    expect(formatTable(NaN)).toBe('—');
    expect(formatNumber(NaN)).toBe('—');
    expect(formatNumber(-0.1)).toBe('0');
    expect(formatTable(-0)).toBe('—');
    expect(formatTable(-0.1)).toBe('—');
    expect(formatTable(-1234, true)).toBe('-1,234');
    expect(formatTablePct(-0)).toBe('—');
    expect(formatTablePct(-0.01)).toBe('—');
    expect(formatTablePct(-12.3)).toBe('−12.3%');
    expect(formatPercent(-38)).toBe('−38.0%');
});

test('in/out keeps cumulative notes in chips outside the numeric table', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const pnl = doc.querySelector('[t-name="baseer_dashboard2.Pnl"]');
    expect(pnl.querySelector('.inout-table').textContent.includes('الرصيد التراكمي أكبر')).toBe(false);
    expect(pnl.textContent.includes('الرصيد التراكمي أكبر')).toBe(true);
});

test('in/out numeric cells never contain the VAT basis label', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const table = doc.querySelector('[t-name="baseer_dashboard2.Pnl"] .inout-table');
    expect(table.querySelector('tr.group th').textContent).toInclude('شامل الضريبة');
    for (const cell of table.querySelectorAll('td')) {
        expect(cell.outerHTML.includes('شامل الضريبة')).toBe(false);
    }
});

test('in/out renders before cash drill availability and ignores stale responses', async () => {
    const month = { month: '2026-10', incoming: { available: true, gross: 1234, channels: {}, warnings: [], apps_unreceived: { available: false, breakdown: [] } }, outgoing: { available: true, total: 567, items: {}, sources: {} }, sales_vat: { value: 0 }, unpaid_bills: { value: 0 }, net: 667 };
    const data = { months: [month], total: { incoming: 1234, outgoing: 567, channels: {}, items: {}, sources: {}, apps_unreceived: { available: false, breakdown: [] }, sales_vat: 0, unpaid_bills: { value: 0 }, net: 667 } };
    const pending = [];
    let instance;
    class InOut extends Component {
        static template = xml`<div><div t-if="state.loading" class="loading">Loading</div><t t-else="" t-call="baseer_dashboard2.Pnl"/></div>`;
        static components = { Sparkline };
        setup() {
            instance = this;
            this.loadToken = 0;
            this.state = useState({ loading: true, error: '', page: 'pnl', view: 'inout', company: 'a', period: { mode: 'month', month: '2026-10' }, timeline: 'monthly', cashDrills: {}, data: null, closed: {} });
            this.orm = { call: (_model, method) => method === 'get_section' ? Promise.resolve(data) : new Promise((resolve, reject) => pending.push({ resolve, reject })) };
        }
        load = Dashboard2.prototype.load;
        loadCashDrills = Dashboard2.prototype.loadCashDrills;
        objectKeys = Object.keys; fmt = formatNumber; tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct; hasDisplayValues = hasDisplayValues; hasPnlValues = hasPnlValues; multiplePoints = multiplePoints; monthName = (v) => v; name = (v) => v;
        exportCsv() {} drill() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(InOut, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    await instance.load();
    await animationFrame();
    expect(getFixture().querySelector('.loading')).toBe(null);
    expect(getFixture().querySelector('.inout-table').textContent).toInclude('1,234');
    expect(getFixture().querySelector('.inout-table').textContent).toInclude('567');
    expect(getFixture().querySelector('.inout-table .bd2-drill')).toBe(null);
    expect(pending.length).toBe(1);
    pending[0].resolve({ total: { '2026-10': ['total'], all: ['total'] } });
    await animationFrame();
    expect(getFixture().querySelector('.inout-table .bd2-drill').textContent).toInclude('567');

    await instance.load();
    instance.state.company = 'b';
    await instance.load();
    pending[1].resolve({ total: { '2026-10': ['total'] } });
    await animationFrame();
    expect(getFixture().querySelector('.inout-table .bd2-drill')).toBe(null);
    pending[2].reject(new Error('unavailable'));
    await animationFrame();
    expect(instance.state.error).toBe('');
    expect(getFixture().querySelector('.inout-table .bd2-drill')).toBe(null);
});

test('in/out unavailable unreceived values use dashes with tooltips', async () => {
    const label = 'غير متوفر';
    const unavailable = { available: false, label, breakdown: [] };
    const available = { available: true, value: 50, breakdown: [{ key: 'app', name: 'تطبيق', value: 50 }] };
    const month = (name, apps) => ({ month: name, incoming: { available: true, gross: 100, channels: {}, warnings: [], apps_unreceived: apps }, outgoing: { available: true, total: 0, items: {}, sources: {} }, sales_vat: { value: 0 }, unpaid_bills: { value: 0 }, net: 100 });
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        pnlDrillable = Dashboard2.prototype.pnlDrillable;
        static components = { Sparkline };
        state = { view: 'inout', data: { months: [month('2026-10', unavailable), month('2026-11', available)], total: { incoming: 200, outgoing: 0, channels: {}, items: {}, sources: {}, apps_unreceived: available, sales_vat: 0, unpaid_bills: { value: 0 }, net: 200 } } };
        objectKeys = Object.keys; fmt = formatNumber; tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct; hasDisplayValues = hasDisplayValues; hasPnlValues = hasPnlValues; multiplePoints = multiplePoints; monthName = (v) => v; name = (v) => v;
        exportCsv() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const templates = await response.text();
    const app = new App(Pnl, { templates, test: true });
    await app.mount(getFixture());
    const rows = getFixture().querySelectorAll('.unreceived-row, .unreceived-app-row');
    expect(rows.length).toBe(2);
    for (const row of rows) {
        const cell = row.children[2];
        expect(cell.textContent.trim()).toBe('—');
        expect(cell.title).toBe(label);
        for (const value of Array.from(row.children).slice(2)) {
            expect(value.textContent.includes(label)).toBe(false);
        }
    }
    expect(rows[0].querySelector('.unreceived-reason').textContent).toBe(label);
    // An unavailable total uses the same presentation, even with app rows present.
    app.destroy();
    class UnavailableTotal extends Pnl {
        state = { view: 'inout', data: { months: [month('2026-10', unavailable), month('2026-11', available)], total: { incoming: 200, outgoing: 0, channels: {}, items: {}, sources: {}, apps_unreceived: { ...available, available: false, label }, sales_vat: 0, unpaid_bills: { value: 0 }, net: 200 } } };
    }
    const secondApp = new App(UnavailableTotal, { templates, test: true });
    after(() => secondApp.destroy());
    await secondApp.mount(getFixture());
    for (const row of getFixture().querySelectorAll('.unreceived-row, .unreceived-app-row')) {
        expect(row.children[row.children.length - 2].textContent.trim()).toBe('—');
        expect(row.children[row.children.length - 2].title).toBe(label);
    }
    expect(getFixture().querySelector('.unreceived-reason').textContent).toBe(label);
    secondApp.destroy();
    class EmptyDetails extends Pnl {
        state = { view: 'inout', data: { months: [month('2026-10', unavailable)], total: { incoming: 100, outgoing: 0, channels: {}, items: {}, sources: {}, apps_unreceived: unavailable, sales_vat: 0, unpaid_bills: { value: 0 }, net: 100 } } };
    }
    const emptyApp = new App(EmptyDetails, { templates, test: true });
    after(() => emptyApp.destroy());
    await emptyApp.mount(getFixture());
    expect(getFixture().querySelector('.unreceived-row')).toBe(null);
    expect(getFixture().querySelector('.unreceived-app-row')).toBe(null);
    expect(getFixture().querySelector('.inout-table').textContent.includes('منها ضريبة القيمة المضافة')).toBe(false);
});

test('heatmap renders occasion badges for an event day', async () => {
    const day = { date: '2026-10-03', gross: 100, customers: 1, events: [{ id: 1, name: 'عرض' }], warnings: [] };
    class Heatmap extends Component {
        static template = 'baseer_dashboard2.Heatmap';
        static components = { Badge };
        state = { metric: 'gross', period: { month: '2026-10' }, meta: {}, data: {
            period: { date_from: '2026-10-01', date_to: '2026-10-31' }, daily_average: {}, days: [day], best_day: day, weekday_month: [], weekday_ytd: [],
            year_calendar: [{ month: '2026-10', days: [day] }], events: [], hours: { available: false, period: { date_from: '2026-10-01', date_to: '2026-10-31' } },
        } };
        tip = { leave() {} }; dayTip() { return []; }
        number = Number; weekdayName = () => ""; months = []; weekdays = []; calendarCells = [day]; hasCustomers = true;
        fmt = formatNumber; dateName = (v) => v; monthName = (v) => v; periodRange = periodRange;
        changeValue() { return null; }
        level() { return 1; } dayValue(d) { return d.gross; } yearPadding() { return []; }
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Heatmap, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.calendar .occasion-badge').textContent).toBe('عرض');
    expect(getFixture().querySelector('.year-days i').getAttribute('aria-label')).toBe('2026-10-03');
    expect(getFixture().querySelector('.year-occasion').hasAttribute('title')).toBe(false);
    expect(getFixture().textContent).toInclude('عدد الطلبات · 1/10 – 31/10/2026');
});

test('glossary explanation opens and closes on outside click and Escape', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(InfoPopup, { templates: await response.text(), props: { title: 'المبيعات', explanation: 'شرح المبيعات' }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    await click('.info-button');
    await animationFrame();
    expect(getFixture().querySelector('.info-panel').textContent).toInclude('شرح المبيعات');
    await press('Escape');
    await animationFrame();
    expect(getFixture().querySelector('.info-panel')).toBe(null);
    await click('.info-button');
    await animationFrame();
    await click(getFixture());
    await animationFrame();
    expect(getFixture().querySelector('.info-panel')).toBe(null);
});

test('chart scales use rounded steps and null values break paths', async () => {
    expect(niceStep(300000)).toBe(100000);
    expect(niceStep(100000)).toBe(25000);
    const chart = { y: (v) => v };
    expect((LineChart.prototype.path.call(chart, [100, null, 200]).match(/M/g) || []).length).toBe(2);
});

test('chart legend excludes series with no points', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(LineChart, { templates: await response.text(), props: { series: [
        { name: '2026', values: [1, null, 2], gold: true },
        { name: '2025', values: [null, null, null], dashed: true },
    ] }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelectorAll('.chart-legend span').length).toBe(1);
    expect(getFixture().querySelector('.chart-legend').textContent).toInclude('2026');
});

test('timeline keeps twelve labels, integer K values and emphasizes its peak', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const values = [null, 269400, null, 508000, ...Array(8).fill(null)];
    const app = new App(LineChart, { templates: await response.text(), props: {
        labels: Array.from({ length: 12 }, (_, i) => String(i + 1)),
        series: [{ name: '2026', values, gold: true, area: true }, { name: '2025', values: Array(12).fill(null), dashed: true }],
    }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const svg = getFixture().querySelector('svg');
    expect(svg.textContent).toInclude('269K');
    expect(svg.textContent).toInclude('508K');
    expect(svg.querySelectorAll('circle').length).toBe(2);
    expect(svg.querySelectorAll('circle[r="5"]').length).toBe(1);
    expect(getFixture().querySelectorAll('.chart-legend span').length).toBe(1);
    expect(svg.textContent).toInclude('12');
});


test('KPI sparkline renders one series and change badge', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(KpiCard, { templates: await response.text(), props: { title: 'Sales', value: 100, change: 10, trend: [50, null, 100], previousTrend: [null, 50, null] }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelectorAll('.bd2-spark path').length).toBe(1);
    expect(getFixture().querySelector('.bd2-badge').textContent).toInclude('10.0%');
});

test('customer KPI displays orders rather than currency', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(KpiCard, { templates: await response.text(), props: { title: 'الطلبات', value: 1471, unit: 'orders' }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.kpi-value').textContent).toInclude('1,471');
    expect(getFixture().querySelector('.kpi-value').textContent).toInclude('طلب');
    expect(getFixture().querySelector('.kpi-value').textContent.includes('ر.س')).toBe(false);
});


test('partial chart month uses a dashed segment and an unclipped axis label', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(LineChart, { templates: await response.text(), props: { series: [
        { name: 'Sales', values: [100000, 161000], partial: [false, true], firstLabel: true },
        { name: 'Profit', values: [90000, 154000], partial: [false, true], firstLabel: true },
    ], labels: ['October', 'November (جزئي)'] }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('[stroke-dasharray="5 4"]')).not.toBe(null);
    const svg = getFixture().querySelector('svg');
    const texts = [...svg.querySelectorAll('text')];
    const axis = texts.find(el => el.textContent === 'November (جزئي)');
    expect(axis.getAttribute('text-anchor')).toBe('start');
    expect(texts.filter(el => el.textContent === 'جزئي').length).toBe(0);
    const sales = texts.find(el => el.textContent === '161K');
    const profit = texts.find(el => el.textContent === '154K');
    expect(Math.abs(Number(sales.getAttribute('y')) - Number(profit.getAttribute('y')))).toBeGreaterThan(9);
});


test('mini charts use non-scaling strokes and avoid stretched SVG labels', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const spark = doc.querySelector('[t-name="baseer_dashboard2.Sparkline"]');
    expect(spark.querySelector('path[vector-effect="non-scaling-stroke"]').getAttribute('stroke-width')).toBe('2');
    expect(spark.querySelector('.spark-label')).not.toBe(null);
});


test('mini labels round amounts and retain one decimal for percentages', () => {
    const short = Sparkline.prototype.short;
    expect(short(125395)).toBe('125K');
    expect(short(46.55, true)).toBe('46.6');
    expect(short(1471, false, true)).toBe('1.5K');
});

test('food progress follows its target and clamps to the track', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(KpiCard, { templates: await response.text(), props: { title: 'الأكل', foodProgress: 150 }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.food-progress i').style.width).toBe('75%');
    expect(getFixture().querySelector('.food-target')).not.toBe(null);
});

test('accounting explanations and gross sales basis are visible in templates', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const pnl = doc.querySelector('[t-name="baseer_dashboard2.Pnl"]');
    expect(pnl.querySelector('.inout-note').textContent).toInclude('مبيعات تطبيقات لم تُستلم بعد');
    expect(pnl.textContent).toInclude('تقريب نوركس');
    expect(doc.querySelector('.heatmap-basis').textContent).toInclude('شاملة الضريبة');
    expect(doc.querySelector('[t-name="baseer_dashboard2.Overview"]').outerHTML).toInclude('غير منتظمة بين الفترات');
});

test('timeline legend year comes from the selected period', () => {
    expect(timelineYear({ mode: 'month', month: '2026-10' })).toBe('2026');
    expect(timelineYear({ mode: 'range', date_to: '2025-12-31' })).toBe('2025');
});


test('displayed rows hide values which round to zero', () => {
    expect(hasDisplayValues([null, 0, -0.4])).toBe(false);
    expect(hasDisplayValues([0, -0.5])).toBe(true);
    expect(multiplePoints([null, 10, null])).toEqual([]);
    expect(multiplePoints([0, 10])).toEqual([0, 10]);
});

test('P&L hides all-zero groups and account rows across displayed months', async () => {
    const row = (key, months, children = []) => ({ key, name: key, months, total: months.reduce((a, b) => a + (b || 0), 0), pct: 0, children });
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        pnlDrillable = Dashboard2.prototype.pnlDrillable;
        static components = { Sparkline };
        state = { view: 'pnl', closed: {}, data: { rows: [row('empty', [0, null]), row('active', [0, 20], [row('empty child', [0, 0]), row('active child', [3, 0])])] } };
        trend = []; hasDisplayValues = hasDisplayValues; hasPnlValues = hasPnlValues; name = v => v; monthName = v => v;
        tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct; toggleRow() {} exportCsv() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Pnl, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const table = getFixture().querySelector('.export-table');
    expect(table.textContent).not.toInclude('empty');
    expect(table.textContent).toInclude('active child');
});

test('in/out hides zero detail rows and keeps nonzero monthly values', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const table = doc.querySelector('[t-name="baseer_dashboard2.Pnl"] .inout-table');
    expect(table.querySelector('.unreceived-row').getAttribute('t-if')).toInclude('hasDisplayValues');
    expect(table.querySelector('.unreceived-app-row').getAttribute('t-if')).toInclude('hasDisplayValues');
    expect(table.textContent).toInclude('٪ من الداخل');
});

test('break-even labels have space inside the plot and a five-tick scale', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(LineChart, { templates: await response.text(), props: { fiveTicks: true, series: [
        { values: [200000, 252000], firstLabel: true },
        { values: [120000, 240000], dashed: true, endpoint: true },
        { values: [50000, 100000], firstLabel: true, gold: true },
    ] }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const labels = [...getFixture().querySelectorAll('svg text[text-anchor="start"]')].filter(el => ['252K', '240K', '100K'].includes(el.textContent));
    expect(labels.length).toBe(3);
    expect(Number(labels[0].getAttribute('x'))).toBeGreaterThan(chartX(1, 2));
    expect(labels[0].getAttribute('y')).not.toBe(labels[1].getAttribute('y'));
    expect(getFixture().querySelectorAll('svg line').length).toBeGreaterThan(3);
});

test('hour labels follow the Riyadh clock', () => {
    expect(hourLabel(12)).toBe('12م');
    expect(hourLabel(13)).toBe('1م');
    expect(hourLabel(0)).toBe('12ص');
    expect(hourLabel(1)).toBe('1ص');
});


test('latest chart points are filled and labelled', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const templates = await response.text();
    const app = new App(Sparkline, { templates, props: { values: [10, 20, 30], mini: true }, test: true });
    await app.mount(getFixture());
    const circles = getFixture().querySelectorAll('circle');
    expect(circles[1].getAttribute('fill')).toBe('var(--bd2-c1)');
    expect(getFixture().querySelector('text').textContent).toBe('30');
    app.destroy();
    const chart = new App(LineChart, { templates, props: { series: [{ values: [10, 20, 30], firstLabel: true }] }, test: true });
    after(() => chart.destroy());
    await chart.mount(getFixture());
    const latest = getFixture().querySelector('circle[r="5"]');
    expect(Number(latest.getAttribute('cx'))).toBe(chartX(2, 3));
    expect(getFixture().querySelector('svg').textContent).toInclude('30');
});

test('revenue apps chart aligns ten month labels and points, preserving gaps', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const source = await response.text();
    const doc = new DOMParser().parseFromString(source, 'text/xml');
    const card = doc.querySelector('[t-name="baseer_dashboard2.Revenue"] .apps-combo');
    const templates = source.replace('</templates>', `<t t-name="test.AppsChart">${new XMLSerializer().serializeToString(card)}</t></templates>`);
    class AppsChart extends Component {
        static template = 'test.AppsChart';
        static components = { Sparkline };
        state = { data: { apps_trend: Array.from({ length: 10 }, (_, i) => ({ month: `2026-${String(i + 1).padStart(2, '0')}`, has_data: i !== 4, data: { apps: i === 9 ? 108000 : 1000 * (i + 1), apps_pct: i === 9 ? 34.9 : i + 1 } })) } };
        trend = []; miniX = miniX; monthName = (month) => month;
    }
    const app = new App(AppsChart, { templates, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const labels = [...getFixture().querySelectorAll('.mini-labels span')];
    const svg = getFixture().querySelector('svg');
    const latest = getFixture().querySelectorAll('.spark-dot.gold')[1];
    expect(labels.length).toBe(5);
    expect(labels.map(label => parseFloat(label.style.left))).toEqual(Array.from({ length: 5 }, (_, i) => miniX(i * 2 + 1, 10)));
    expect(parseFloat(latest.style.left)).toBe(miniX(9, 10));
    expect(parseFloat(latest.style.left)).toBeLessThan(parseFloat(labels[0].style.left));
    expect(getFixture().querySelector('.spark-label.gold').textContent).toBe('34.9%');
    for (const color of ['gold', 'navy']) {
        const label = getFixture().querySelector(`.spark-label.${color}`);
        expect(label.style.left).toInclude('+ 10px');
        expect(label.style.top).toInclude('- 6px');
        expect(label.style.transform).toBe('translate(0px, -100%)');
    }
    expect(Sparkline.prototype.miniLabelStyle.call({ miniPoint: () => ({ x: 95, y: 10 }) }, [1], 0)).toInclude('- 10px');
    for (const [path, color] of [[1, 'var(--bd2-c1)'], [2, 'var(--bd2-gold)']]) {
        const points = [...svg.querySelectorAll('path')[path].getAttribute('d').matchAll(/[ML]([\d.]+),([\d.]+)/g)];
        const dots = getFixture().querySelectorAll(`.spark-dot.${color === 'var(--bd2-c1)' ? 'navy' : 'gold'}`);
        for (const [dot, point] of [[dots[0], points[0]], [dots[1], points.at(-1)]]) {
            expect(parseFloat(dot.style.left)).toBe(Number(point[1]));
            expect(parseFloat(dot.style.top)).toBe(Number(point[2]) / 32 * 100);
        }
    }
    expect(svg.getAttribute('preserveAspectRatio')).toBe('none');
    expect(svg.querySelectorAll('path')[2].getAttribute('d').split('M').length).toBe(3);
});

test('stretched sparkline endpoint centers align with SVG paths', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Sparkline, { templates: await response.text(), props: { mini: true, stretch: true, values: [10, 20, 30], previous: [30, 10, 20] }, test: true });
    after(() => app.destroy());
    const cssResponse = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/scss/main.scss'));
    const style = document.createElement('style');
    style.textContent = await cssResponse.text();
    expect((style.textContent.match(/\.o_bd2 \.spark-dot \{/g) || []).length).toBe(1);
    for (const transform of ['translate(-50%, -50%)', 'translate(-50%, -100%)', 'translateX(-50%)']) {
        expect(style.textContent.replaceAll(`/*rtl:ignore*/ transform: ${transform}`, '').includes(`transform: ${transform}`)).toBe(false);
    }
    document.head.append(style);
    after(() => style.remove());
    const host = document.createElement('div');
    host.className = 'o_bd2';
    host.style.cssText = 'width:700px;height:auto';
    host.innerHTML = '<div class="revenue-combo apps-combo"></div>';
    getFixture().append(host);
    await app.mount(host.firstElementChild);
    const wrap = host.querySelector('.spark-wrap');
    const svg = wrap.querySelector('svg');
    for (const [pathIndex, series] of [[1, 'navy'], [2, 'gold']]) {
        const path = svg.querySelectorAll('path')[pathIndex];
        const points = [...path.getAttribute('d').matchAll(/[ML]([\d.]+),([\d.]+)/g)];
        const dots = wrap.querySelectorAll(`.spark-dot.${series}`);
        for (const [dot, point] of [[dots[0], points[0]], [dots[1], points.at(-1)]]) {
            const projected = new DOMPoint(Number(point[1]), Number(point[2])).matrixTransform(path.getScreenCTM());
            const rect = dot.getBoundingClientRect();
            expect(Math.abs(rect.left + rect.width / 2 - projected.x) < 0.5).toBe(true);
            expect(Math.abs(rect.top + rect.height / 2 - projected.y) < 0.5).toBe(true);
        }
    }
});

test('customer chart aligns every month with its plotted point and formats orders', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const source = await response.text();
    const doc = new DOMParser().parseFromString(source, 'text/xml');
    const card = doc.querySelector('[t-name="baseer_dashboard2.Revenue"] .customer-combo');
    card.removeAttribute('t-else');
    const templates = source.replace('</templates>', `<t t-name="test.CustomerChart">${new XMLSerializer().serializeToString(card)}</t></templates>`);
    class CustomerChart extends Component {
        static template = 'test.CustomerChart';
        static components = { Sparkline };
        trend = Array.from({ length: 6 }, (_, i) => ({ has_data: true, data: { customers: { value: i === 0 ? null : i === 5 ? 1471 : 100 * (i + 1), avg_ticket: i === 0 ? null : 80 } } }));
        trendLabels = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'];
        miniX = miniX;
    }
    const app = new App(CustomerChart, { templates, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const labels = [...getFixture().querySelectorAll('.mini-labels span')];
    const values = [100, 200, 300, 400, 500, 1471];
    labels.forEach((label, i) => expect(parseFloat(label.style.left)).toBe(Sparkline.prototype.miniPoint(values, i).x));
    expect(parseFloat(labels[5].style.left)).toBeLessThan(parseFloat(labels[0].style.left));
    expect(getFixture().querySelector('.spark-label.navy').textContent).toBe('1.5K');
    expect(getFixture().querySelectorAll('.spark-dot.navy').length).toBe(2);
    expect(getFixture().querySelector('path[stroke="var(--bd2-c1)"]').getAttribute('d')).toInclude(`M${miniX(1, 6)},`);
});

test('partial overview marks ratios and neutralizes company comparisons', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const source = await response.text();
    const doc = new DOMParser().parseFromString(source, 'text/xml');
    const overview = doc.querySelector('[t-name="baseer_dashboard2.Overview"]');
    const mini = overview.querySelector('.grid.three');
    const bridge = overview.querySelector('[t-foreach="state.data.bridge"]').parentElement;
    const templates = source.replace('</templates>', `<t t-name="test.PartialOverview"><t t-set="partialMonth" t-value="state.period.mode === 'month' and trend.at(-1)?.partial"/>${new XMLSerializer().serializeToString(mini)}${new XMLSerializer().serializeToString(bridge)}<t t-call="baseer_dashboard2.Compare"/></t><t t-name="test.Track"><div/></t></templates>`);
    class Track extends Component { static template = 'test.Track'; static props = { value: {optional: true}, max: {optional: true}, date: {optional: true}, customers: {optional: true}, occasion: {optional: true} }; }
    let partial = true;
    class PartialOverview extends Component {
        static template = 'test.PartialOverview'; static components = { Sparkline, Track };
        state = { period: { mode: 'month', month: '2026-11' }, company: '1', data: {
            purchases: { available: true, value: 10, pct: 1.6, trend: [] },
            sales: { apps: 20, apps_pct: 2, customers: { available: true, value: 100, avg_ticket: 80, cutover_date: '2026-11-19' }, trend: [] },
            bridge: [{ key: 'commissions', amount: -1, pct: -1 }, { key: 'other_opex', amount: -11, pct: -11 }, { key: 'operating_profit', amount: 96, pct: 96 }, { key: 'net_profit', amount: 95, pct: 95.5 }],
            companies_compare: ['1', '2'].map(key => ({ key, name: key, sales_net: 100, food_pct: 1.6, salaries_pct: 0.4, net_margin_pct: -5, targets: { food_pct: { status: 'ok' }, salaries_pct: { status: 'bad' } } }))
        } };
        current = { tax: {} };
        trend = [{ partial }]; monthName = (v, short, year, isPartial) => monthLabel(v, { short, year, partial: isPartial }); fmt = formatNumber; pct = formatPercent; tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct; customerCutoverLabel = customerCutoverLabel;
        iconPath() { return ''; } name(v) { return v; } bridgeStyle() { return ''; } bridgeDrillKey = Dashboard2.prototype.bridgeDrillKey; miniDrillable = Dashboard2.prototype.miniDrillable; miniDrill = Dashboard2.prototype.miniDrill;
    }
    const app = new App(PartialOverview, { templates, test: true });
    after(() => app.destroy());
    const fixture = getFixture();
    await app.mount(fixture);
    expect(fixture.querySelector('.tax-note').textContent).toInclude('ضريبة قيمة مضافة مستحقة للهيئة');
    expect(fixture.querySelectorAll('.mini')[2].textContent).toInclude('من 19/11');
    expect([...fixture.querySelectorAll('.mini-pill')].every(el => el.textContent.includes('(جزئي)'))).toBe(true);
    expect(fixture.querySelector('.bridge-row').parentElement.querySelector('h3').textContent).toInclude('(جزئي)');
    expect([...fixture.querySelectorAll('.bridge-row')].every(row => !row.textContent.includes('(جزئي)'))).toBe(true);
    expect([...fixture.querySelectorAll('.bridge-row')].map(row => row.textContent).some(text => text.includes('other_opex'))).toBe(true);
    expect([...fixture.querySelectorAll('.bridge-row')].map(row => row.querySelector('b').textContent)).toEqual(['commissions', 'other_opex', 'operating_profit', 'net_profit']);
    expect(fixture.querySelectorAll('.compare-pill.neutral').length).toBe(6);
    expect([...fixture.querySelectorAll('.compare-pill')].every(el => el.title === 'الشهر لم يكتمل')).toBe(true);
    expect(fixture.textContent.match(/November 2026 \(جزئي\)/g).length).toBe(2);
    app.destroy();
    partial = false;
    const completed = new App(PartialOverview, { templates, test: true });
    after(() => completed.destroy());
    await completed.mount(fixture);
    expect(fixture.querySelectorAll('.compare-pill.neutral').length).toBe(0);
    expect(fixture.querySelectorAll('.compare-pill.bad').length).toBe(4);
    expect(fixture.querySelector('.bridge-row span').textContent.includes('(جزئي)')).toBe(false);
    expect([...fixture.querySelectorAll('.mini-pill')].every(el => !el.textContent.includes('(جزئي)'))).toBe(true);
});

test('commission card uses recorded amount and salary badges explain suppression', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const revenue = doc.querySelector('[t-name="baseer_dashboard2.Revenue"]');
    const card = revenue.querySelector('[t-if="state.data.commissions.available"]');
    expect(card.querySelector('Money').getAttribute('value')).toBe('state.data.commissions.amount');
    expect(revenue.textContent.includes('عمولة X%')).toBe(false);
    expect(revenue.innerHTML.includes('commission_rate')).toBe(false);
    expect(revenue.querySelectorAll('KpiCard[headingSubtitle*="customerCutoverLabel"]').length).toBe(2);
    expect(doc.querySelector('[t-name="baseer_dashboard2.Badge"] [t-if="props.warning"]').getAttribute('title')).toInclude('رواتب الشهر السابق');
    const overview = doc.querySelector('[t-name="baseer_dashboard2.BreakEven"]');
    expect(overview.querySelector('.break-progress').getAttribute('t-if')).toBe('state.data.breakeven?.available');
    expect(overview.querySelector('.break-legend').getAttribute('t-if')).toBe('state.data.breakeven?.available');
});

test('customer cutover labels show the configured date', async () => {
    expect(customerCutoverLabel('2026-10-03')).toBe('من 3/10');
    expect(customerCutoverLabel(false)).toBe(null);
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(KpiCard, { templates: await response.text(), props: { title: 'الطلبات', value: 2, unit: 'orders', headingSubtitle: customerCutoverLabel('2026-11-19') }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.kpi-subtitle').textContent).toBe('من 19/11');
});


test('partial KPI badge hides the comparison with an explanation', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const templates = await response.text();
    const app = new App(Badge, { templates, props: { value: 142.6, partial: true }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().textContent.trim()).toBe('—');
    expect(getFixture().querySelector('[title]').title).toBe('الشهر لم يكتمل');
    const doc = new DOMParser().parseFromString(templates, 'text/xml');
    expect(doc.querySelector('[t-name="baseer_dashboard2.Overview"] .safety-chips').outerHTML).toInclude('m.partial');
});

test('overview hides only the current incomplete-costs margin with an explanation', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const source = await response.text();
    const doc = new DOMParser().parseFromString(source, 'text/xml');
    const chips = doc.querySelector('[t-name="baseer_dashboard2.Overview"] .safety-chips');
    const templates = source.replace('</templates>', `<t t-name="test.MarginChips">${new XMLSerializer().serializeToString(chips)}</t></templates>`);
    class MarginChips extends Component {
        static template = 'test.MarginChips';
        state = { data: { breakeven: { available: false, reason: 'incomplete_costs' }, breakeven_series: [
            { month: '2026-10', margin_pct: 23.5 }, { month: '2026-11', partial: true, margin_pct: 95.5 },
        ] } };
        monthName = (month) => month; pct = formatPercent;
    }
    const app = new App(MarginChips, { templates, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const values = getFixture().querySelectorAll('.safety-chips bdi');
    expect(values[0].textContent).toBe('23.5%');
    expect(values[1].textContent).toBe('—');
    expect(values[1].title).toBe('الشهر لم يكتمل');
});

test('food percentage uses the same formatting in mini charts and cards', () => {
    expect(formatPercent(46.6)).toBe('46.6%');
    expect(Sparkline.prototype.short(46.6, true) + '%').toBe(formatPercent(46.6));
    expect(formatTablePct(46.6)).toBe(formatPercent(46.6));
});

test('expense distribution displays the aggregated other row', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const row = doc.querySelector('[t-name="baseer_dashboard2.Expenses"] .rank-row');
    expect(row.getAttribute('t-foreach')).toBe('expenses.filter(r=>r.amount)');
    expect(row.querySelector('b').getAttribute('t-esc')).toBe('name(row.key)');
});

test('P&L displays the merged other expense and its accounts in one row', async () => {
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        pnlDrillable = Dashboard2.prototype.pnlDrillable;
        static components = { Sparkline };
        state = { view: 'pnl', closed: {}, data: { rows: [{ key: 'other_opex', name: false, months: [-1250.18], total: -1250.18, pct: -1, children: [{ code: '400032', name: 'حساب', months: [-1250.18], total: -1250.18, pct: -1 }] }] } };
        trend = [{ month: '2026-10' }];
        name = () => 'مصاريف أخرى'; monthName = (v) => v; hasDisplayValues = hasDisplayValues; hasPnlValues = hasPnlValues;
        tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct;
        toggleRow() {} exportCsv() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Pnl, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const table = getFixture().querySelector('.export-table');
    expect(table.textContent.match(/مصاريف أخرى/g).length).toBe(1);
    expect(table.textContent).toInclude('(1,250.18)');
    expect(table.querySelector('.account').textContent).toInclude('400032');
});


test('review layouts show period totals and separate KPI details', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const heat = doc.querySelector('.hours-table');
    expect(heat.textContent).toInclude('المتوسط');
    expect(heat.closest('.card').querySelector('[t-esc="periodRange(state.data.hours.period)"]')).not.toBe(null);
    const compare = doc.querySelector('[t-name="baseer_dashboard2.Compare"]');
    expect(compare.innerHTML).toInclude("co.net_margin_pct &lt; 0 ? 'bad'");
    expect(compare.innerHTML).toInclude('co.targets?.food_pct?.status');
    const kpi = doc.querySelector('[t-name="baseer_dashboard2.KpiCard"]');
    expect(kpi.querySelector('.kpi-subtitle')).not.toBe(null);
    expect(kpi.querySelector('.kpi-share').previousElementSibling.textContent).toInclude('عن الشهر السابق');
});


test('ratio changes are percentage points and targets omit unnecessary decimals', async () => {
    expect(ratioDifference(0, 8.5)).toBe(-8.5);
    expect(ratioDifference(null, 8.5)).toBe(null);
    expect(formatPoints(-8.5)).toBe('−8.5');
    expect(formatTargetPercent(33)).toBe('33%');
    expect(formatTargetPercent(25.5)).toBe('25.5%');
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Badge, { templates: await response.text(), props: { value: -8.5, points: true }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().textContent).toInclude('−8.5 نقطة');
});

test('small display details and commission data are wired correctly', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    expect(doc.querySelector('[t-name="baseer_dashboard2.Timeline"] b[t-att-class*="muted"]').getAttribute('t-att-class')).toInclude('muted');
    expect(doc.querySelector('[t-name="baseer_dashboard2.Ratios"]').outerHTML).toInclude('targetPercent(');
    expect(doc.querySelector('[t-name="baseer_dashboard2.BreakEven"] Money').getAttribute('value')).toBe('state.data.breakeven.value');
});


test('previous gauge marker stays inside both ends of the track', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Gauge, { templates: await response.text(), props: { value: 46.6, previous: 50.9, target: 25, max: 50 }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const gauge = getFixture().querySelector('.bd2-gauge');
    expect(gauge.querySelector('i').style.width).toBe('93.2%');
    expect(gauge.querySelector('b').getAttribute('style')).toInclude('clamp(0px, calc(50% - 1.5px), calc(100% - 3px))');
    expect(gauge.querySelector('em').getAttribute('style')).toInclude('clamp(0px, calc(100% - 5px), calc(100% - 10px))');
    gauge.style.cssText = 'position:relative;width:200px;height:12px';
    for (const [marker, width] of [[gauge.querySelector('b'), 3], [gauge.querySelector('em'), 10]]) {
        marker.style.position = 'absolute';
        marker.style.boxSizing = 'border-box';
        marker.style.width = `${width}px`;
        const track = gauge.getBoundingClientRect();
        for (const pct of [0, 50, 100]) {
            marker.style.right = `clamp(0px, calc(${pct}% - ${width / 2}px), calc(100% - ${width}px))`;
            const rect = marker.getBoundingClientRect();
            expect(rect.left >= track.left && rect.right <= track.right).toBe(true);
            if (pct === 50) expect(Math.abs((rect.left + rect.right) / 2 - (track.left + track.right) / 2) < 0.5).toBe(true);
        }
    }
    expect(Gauge.prototype.pos.call({ props: { max: 50 } }, -1)).toBe(0);
    expect(Gauge.prototype.pos.call({ props: { max: 50 } }, 25)).toBe(50);
});

test('partial month break-even labels are separated', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(LineChart, { templates: await response.text(), props: { fiveTicks: true, series: [
        { values: [100000, 161000], firstLabel: true, partial: [false, true] },
        { values: [50000, 154000], firstLabel: true, partial: [false, true], gold: true },
        { values: [110000, 124000], dashed: true, endpoint: true },
    ] }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const labels = [...getFixture().querySelectorAll('text[text-anchor="start"]')].filter(el => ['161K', '154K'].includes(el.textContent));
    expect(labels.length).toBe(2);
    const circles = [...getFixture().querySelectorAll('circle[r="5"]')];
    expect(Number(labels[0].getAttribute('y'))).toBeLessThan(Number(circles[0].getAttribute('cy')) - 9);
    expect(Number(labels[1].getAttribute('y'))).toBeGreaterThan(Number(circles[1].getAttribute('cy')) + 18);
    const breakLabel = [...getFixture().querySelectorAll('text')].find(el => el.textContent === '124K');
    expect(Number(breakLabel.getAttribute('y'))).toBeLessThan(Number(circles[2].getAttribute('cy')) - 9);
});

test('peak hours subtitle uses the effective selected date range', async () => {
    expect(periodRange({ date_from: '2026-11-01', date_to: '2026-11-20' })).toBe('1/11 – 20/11/2026');
    expect(periodRange({ date_from: '2025-12-30', date_to: '2026-01-02' })).toBe('30/12/2025 – 2/1/2026');
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    expect(doc.querySelector('[t-esc="periodRange(state.data.hours.period)"]')).not.toBe(null);
});


test('peak hours subtitle uses the actual partial data range', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const card = [...doc.querySelectorAll('[t-name="baseer_dashboard2.Heatmap"] .card')].find(el => el.textContent.includes('أوقات الذروة'));
    expect(card.outerHTML).toInclude('periodRange(state.data.hours.period)');
    expect(card.outerHTML).toInclude('state.data.hours.partial');
    expect(periodRange({ date_from: '2026-11-01', date_to: '2026-11-20' })).toBe('1/11 – 20/11/2026');
});


test('mobile navigation opens and closes on page selection and Escape', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    class Dashboard extends Dashboard2 {
        async init() { this.state.meta = { companies: [{ key: "all", label: "المجموع" }] }; }
        async load() {}
    }
    const app = new App(Dashboard, { templates: await response.text(), env: { services: { orm: {}, action: {}, dialog: {} } }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const root = getFixture().querySelector('.o_bd2');
    expect(root.querySelector('.tax-basis-badge').textContent).toBe('شامل الضريبة');
    expect(root.querySelector('.company-label-fallback').textContent).toBe('المجموع');
    root.querySelector('.bd2-menu-toggle').click();
    await animationFrame();
    expect(root.classList.contains('bd2-nav-open')).toBe(true);
    root.querySelector('.bd2-sidebar nav button').click();
    await animationFrame();
    expect(root.classList.contains('bd2-nav-open')).toBe(false);
    root.querySelector('.bd2-menu-toggle').click();
    await animationFrame();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await animationFrame();
    expect(root.classList.contains('bd2-nav-open')).toBe(false);
});

test('wide dashboard content has horizontal scroll containers', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    for (const selector of ['.export-table', '.inout-table', '.calendar', '.year-grid', '.hours-table']) {
        expect(doc.querySelector(selector).closest('.bd2-scroll-x')).not.toBe(null);
    }
});

test('long chart axes mark alternating labels for the phone layout', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(LineChart, { templates: await response.text(), props: {
        labels: Array.from({ length: 12 }, (_, i) => String(i + 1)),
        series: [{ values: Array.from({ length: 12 }, (_, i) => i) }],
    }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelectorAll('.bd2-axis-label').length).toBe(6);
    expect(getFixture().querySelectorAll('.bd2-axis-alternate').length).toBe(6);
});

test('P&L period selector controls columns and hides a single-column sparkline', async () => {
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        pnlDrillable = Dashboard2.prototype.pnlDrillable;
        static components = { Sparkline };
        state = { view: 'pnl', pnl_view: 'month', closed: {}, data: { pnl_columns: [{month: '2026-10'}], rows: [{key:'revenue', name:'مبيعات', months:[100], total:100, pct:100, children:[]}] } };
        trend = []; hasDisplayValues = hasDisplayValues; hasPnlValues = hasPnlValues; name = v => v; monthName = v => v; tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct;
        toggleRow() {} exportCsv() {} choose() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Pnl, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelectorAll('.pnl-period-seg button').length).toBe(4);
    expect(getFixture().querySelector('.export-table').textContent.includes('الاتجاه')).toBe(false);
});


test('P&L section request includes view and custom dates', async () => {
    let args;
    const context = { state: { company: '2', page: 'pnl', view: 'pnl', tax_inclusive: false, pnl_view: 'range', pnl_range: {date_from:'2026-08-15', date_to:'2026-10-20'}, period: {mode:'month', month:'2026-10'}, timeline:'monthly' }, orm: { async call(...values) { args = values; return {}; } } };
    await Dashboard2.prototype.load.call(context);
    expect(args[2][1].pnl_view).toBe('range');
    expect(args[2][1].pnl_range.date_from).toBe('2026-08-15');
    expect(args[2][1].pnl_range.date_to).toBe('2026-10-20');
    expect(args[2][1].tax_inclusive).toBe(false);
});

test('P&L displays and exports halalas and hides genuinely zero rows', async () => {
    expect(formatPnlAmount(100.49)).toBe('100.49');
    expect(formatPnlAmount(0.49)).toBe('0.49');
    expect(formatPnlAmount(-0.49)).toBe('(0.49)');
    expect(formatPnlAmount(0)).toBe('—');
    expect(hasPnlValues([null, 0])).toBe(false);
    expect(hasPnlValues([0, 0.49])).toBe(true);
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        static components = { Sparkline };
        state = { view:'pnl', pnl_view:'month', closed:{}, data:{pnl_columns:[{month:'2026-10'}], rows:[
            {key:'a', name:'large', months:[100.49], total:100.49, pct:null, children:[]},
            {key:'b', name:'small', months:[0.49], total:0.49, pct:null, children:[]},
            {key:'c', name:'zero', months:[0], total:0, pct:null, children:[]},
        ]} };
        trend = []; hasPnlValues = hasPnlValues; pnlFmt = formatPnlAmount; tablePct = formatTablePct;
        name = v => v; monthName = v => v; pnlDrillable() { return false; }
        toggleRow() {} exportCsv() {} choose() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Pnl, { templates: await response.text(), test:true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const table = getFixture().querySelector('.export-table');
    expect(table.textContent).toInclude('100.49');
    expect(table.textContent).toInclude('0.49');
    expect(table.textContent.includes('zero')).toBe(false);
    getFixture().classList.add('o_bd2');
    const createUrl = URL.createObjectURL, anchorClick = HTMLAnchorElement.prototype.click;
    let exported;
    try {
        URL.createObjectURL = blob => { exported = blob; return 'blob:test'; };
        HTMLAnchorElement.prototype.click = () => {};
        Dashboard2.prototype.exportCsv.call({state:{view:'pnl'}, pnlTaxLabel:'شامل الضريبة'});
        const csv = await exported.text();
        expect(csv).toInclude('100.49');
        expect(csv).toInclude('0.49');
        expect(csv.includes('zero')).toBe(false);
    } finally {
        URL.createObjectURL = createUrl;
        HTMLAnchorElement.prototype.click = anchorClick;
        getFixture().classList.remove('o_bd2');
    }
});

test('P&L verified detail requests retain the selected company and tax basis', async () => {
    let args;
    const descriptor = {section:'pnl', key:'salaries', company_key:'2', tax_inclusive:true};
    const context = {
        props: {descriptor}, alive: true, epoch: 0,
        state: {data:null, busy:false, error:'', selector:{kind:'account', company_id:2, account_id:9}, page:2},
        orm: {async call(...value) {args = value; return {rows:[], page:2};}},
    };
    await DashboardPnlDetails.prototype.load.call(context);
    expect(args[0]).toBe('baseer.dashboard2.service');
    expect(args[1]).toBe('get_pnl_details');
    expect(args[2][0]).toEqual(descriptor);
    expect(args[2][1]).toEqual({kind:'account', company_id:2, account_id:9});
    expect(args[2][2]).toBe(2);
    expect(context.state.data.page).toBe(2);
    expect(context.state.busy).toBe(false);
});

test('P&L shows sparklines with multiple displayed columns', async () => {
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        pnlDrillable = Dashboard2.prototype.pnlDrillable;
        static components = { Sparkline };
        state = { view:'pnl', pnl_view:'year', closed:{}, data:{pnl_columns:[{month:'2026-09'}, {month:'2026-10'}], rows:[{key:'revenue', name:'مبيعات', months:[20,100], total:120, pct:100, children:[]}]} };
        trend = []; hasDisplayValues = hasDisplayValues; hasPnlValues = hasPnlValues; name = v => v; monthName = v => v; tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct;
        toggleRow() {} exportCsv() {} choose() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Pnl, { templates: await response.text(), test:true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.export-table').textContent).toInclude('الاتجاه');
    expect(getFixture().querySelector('.export-table .bd2-spark')).not.toBe(null);
});


test('P&L drill opens verified details with the selected basis without changing CSV text', async () => {
    let dialogComponent, dialogProps, toggles = 0;
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        static components = { Sparkline };
        state = { view:'pnl', tax_inclusive: true, pnl_view:'month', company:'2', period:{mode:'month', month:'2026-10'}, closed:{}, data:{pnl_columns:[{month:'2026-10'}], rows:[{key:'salaries', name:'رواتب', months:[-120], total:-120, pct:1, children:[]}]} };
        trend = []; hasDisplayValues = hasDisplayValues; hasPnlValues = hasPnlValues; name = v => v; monthName = v => v; tableFmt = formatTable; pnlFmt = formatPnlAmount; tablePct = formatTablePct;
        pnlDrillable = Dashboard2.prototype.pnlDrillable; drillPnl = Dashboard2.prototype.drillPnl;
        closePnlDetails = Dashboard2.prototype.closePnlDetails;
        dialog = { add(component, props) { dialogComponent = component; dialogProps = props; return () => {}; } };
        toggleRow() { toggles++; } exportCsv() {} choose() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Pnl, { templates: await response.text(), env: {services: {action: {async doAction(value) { opened = value; }}}}, test:true });
    after(() => app.destroy());
    await app.mount(getFixture());
    const cell = getFixture().querySelector('.export-table tbody td');
    expect(plainCsvText(cell.textContent.trim())).toBe('(120.00)');
    await click(cell.querySelector('.bd2-drill'));
    expect(toggles).toBe(0);
    expect(dialogComponent).toBe(DashboardPnlDetails);
    expect(dialogProps.descriptor.key).toBe('salaries');
    expect(dialogProps.descriptor.tax_inclusive).toBe(true);
    expect(plainCsvText(cell.textContent.trim())).toBe('(120.00)');
    getFixture().classList.add('o_bd2');
    const createUrl = URL.createObjectURL;
    const anchorClick = HTMLAnchorElement.prototype.click;
    let exported;
    try {
        URL.createObjectURL = (blob) => { exported = blob; return 'blob:test'; };
        HTMLAnchorElement.prototype.click = () => {};
        Dashboard2.prototype.exportCsv.call({state: {view: 'pnl'}, pnlTaxLabel: 'شامل الضريبة'});
        const csv = await exported.text();
        expect(csv).toInclude('شامل الضريبة');
        expect(csv).toInclude('"(120.00)"');
    } finally {
        URL.createObjectURL = createUrl;
        HTMLAnchorElement.prototype.click = anchorClick;
        getFixture().classList.remove('o_bd2');
    }
});

test('shared line tooltip shows a full month, current and prior values, and drills', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    let drilled = 0;
    const host = document.createElement('div');
    host.className = 'o_bd2';
    getFixture().append(host);
    const app = new App(LineChart, { templates: await response.text(), props: {
        months: ['2026-10'], labels: ['Oct'], series: [{ values: [12000], previousYear: [10000], drill: () => drilled++ }],
    }, test: true });
    after(() => { dashboardTooltip.destroy(); app.destroy(); });
    await app.mount(host);
    const slot = host.querySelector('.bd2-chart-slot');
    const svg = slot.ownerSVGElement;
    const point = new DOMPoint(chartX(0, 1), 80).matrixTransform(svg.getScreenCTM());
    slot.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse', clientX: point.x, clientY: point.y }));
    await animationFrame();
    const tip = host.querySelector('.bd2-tooltip');
    expect(tip.textContent).toInclude('October 2026');
    expect(tip.textContent).toInclude('12,000');
    expect(tip.textContent).toInclude('10,000');
    expect(tip.textContent).toInclude('20.0%');
    expect(host.querySelector('circle').hasAttribute('title')).toBe(false);
    tip.querySelector('button').click();
    expect(drilled).toBe(1);
});

test('shared tooltip toggles on touch and clamps to a 375px viewport', async () => {
    const tip = new DashboardTooltip();
    const root = document.createElement('div');
    root.className = 'o_bd2';
    const anchor = document.createElement('button');
    root.append(anchor); getFixture().append(root);
    after(() => tip.destroy());
    const rect = { left: 360, right: 370, top: 200, bottom: 210, width: 10, height: 10 };
    const oldWidth = Object.getOwnPropertyDescriptor(window, 'innerWidth');
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 375 });
    try {
        tip.toggle(anchor, [['المبلغ', '12,000 ر.س']], { rect });
        const box = tip.element.getBoundingClientRect();
        expect(box.left >= 0 && box.right <= 375).toBe(true);
        expect(box.bottom <= rect.top || box.top >= rect.bottom || box.right <= rect.left || box.left >= rect.right).toBe(true);
        tip.toggle(anchor, [['المبلغ', '12,000 ر.س']], { rect });
        expect(tip.element.hidden).toBe(true);
    } finally { if (oldWidth) Object.defineProperty(window, 'innerWidth', oldWidth); else delete window.innerWidth; }
});

test('bounded line tooltip stays below the comparison panel and clears the point', () => {
    const tip = new DashboardTooltip();
    const root = document.createElement('div'); root.className = 'o_bd2';
    const panel = document.createElement('div');
    const plot = document.createElement('div');
    const anchor = document.createElement('button');
    panel.style.cssText = 'position:fixed;left:10px;top:80px;width:350px;height:80px';
    plot.style.cssText = 'position:fixed;left:10px;top:160px;width:350px;height:200px';
    plot.append(anchor); root.append(panel, plot); getFixture().append(root);
    after(() => tip.destroy());
    const point = { left: 180, right: 188, top: 170, bottom: 178, width: 8, height: 8 };
    tip.show(anchor, [['القيمة', '12,000 ر.س']], { rect: point, bounds: plot });
    const box = tip.element.getBoundingClientRect(), above = panel.getBoundingClientRect();
    expect(box.top >= plot.getBoundingClientRect().top).toBe(true);
    expect(box.top >= above.bottom).toBe(true);
    expect(box.bottom <= point.top || box.top >= point.bottom || box.right <= point.left || box.left >= point.right).toBe(true);
});

test('touch on a chart slot toggles the shared tooltip without firing the drill', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    let drilled = 0;
    const host = document.createElement('div'); host.className = 'o_bd2'; getFixture().append(host);
    const app = new App(LineChart, { templates: await response.text(), props: {
        months: ['2026-10'], series: [{ values: [12000], previousYear: [10000], drill: () => drilled++ }],
    }, test: true });
    after(() => { dashboardTooltip.destroy(); app.destroy(); });
    await app.mount(host);
    const slot = host.querySelector('.bd2-chart-slot');
    const p = new DOMPoint(chartX(0, 1), 100).matrixTransform(slot.ownerSVGElement.getScreenCTM());
    const touch = () => slot.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerType: 'touch', clientX: p.x, clientY: p.y }));
    touch(); expect(host.querySelector('.bd2-tooltip').hidden).toBe(false);
    expect(drilled).toBe(0);
    touch(); expect(host.querySelector('.bd2-tooltip').hidden).toBe(true);
    touch(); document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch' }));
    expect(host.querySelector('.bd2-tooltip').hidden).toBe(true);
});

test('calendar tooltip includes the full date, amount, customers and occasion', () => {
    const rows = Dashboard2.prototype.dayTip.call({dateName: () => '3 October'}, {
        date: '2026-10-03', gross: 26827, customers: 42, events: [{name: 'عرض'}],
    });
    expect(rows).toEqual([['التاريخ', '3 October 2026'], ['المبلغ', '26,827 ر.س'], ['العملاء', '42'], ['المناسبة', 'عرض']]);
});

test('inclusive basis, waterfall tax note and P&L basis are identified', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'application/xml');
    expect(doc.querySelector('.tax-basis-badge').textContent).toBe('شامل الضريبة');
    const overview = doc.querySelector('[t-name="baseer_dashboard2.Overview"]');
    expect(overview.querySelector('.tax-note').textContent).toInclude('ضريبة قيمة مضافة مستحقة للهيئة');
    const revenue = doc.querySelector('[t-name="baseer_dashboard2.Revenue"]');
    expect(revenue.querySelector('KpiCard').getAttribute('value')).toBe('current.gross');
    const pnl = doc.querySelector('[t-name="baseer_dashboard2.Pnl"]');
    expect(pnl.querySelector('.pnl-tax-switch').getAttribute('role')).toBe('switch');
    expect(pnl.querySelector('.pnl-tax-switch').getAttribute('t-att-aria-checked')).toInclude('state.tax_inclusive');
});

test('inclusive revenue drills through accounting and adjustments are not drillable', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'application/xml');
    const revenue = doc.querySelector('[t-name="baseer_dashboard2.Revenue"]');
    expect(revenue.querySelector('KpiCard').getAttribute('onDrill')).toInclude("'revenue','gross'");
    expect(revenue.outerHTML).toInclude("row.key !== 'accounting_adjustments'");
    const overview = doc.querySelector('[t-name="baseer_dashboard2.Overview"]');
    const percentage = overview.querySelector('[t-foreach="state.data.bridge"] span.muted bdi');
    expect(percentage.hasAttribute('t-on-click')).toBe(false);
});

import { after, expect, getFixture, globals, test, withFetch, click, press } from '@odoo/hoot';
import { animationFrame } from '@odoo/hoot-mock';
import { App, Component } from '@odoo/owl';
import { hourLabel, hasDisplayValues, multiplePoints, formatNumber, formatTable, formatTablePct, formatPercent, chartX, miniX, timelineYear, InfoPopup, LineChart, niceStep, KpiCard, Sparkline, Badge, Gauge } from '../src/js/main';

test('P&L renders without in/out months', async () => {
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        state = { view: 'pnl', data: { rows: [] }, closed: {} };
        trend = [];
        exportCsv() {}
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    expect(response.ok).toBe(true);
    const app = new App(Pnl, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.export-table')).not.toBe(null);
});

test('ratios render a numeric gauge target', async () => {
    class Ratios extends Component {
        static template = 'baseer_dashboard2.Ratios';
        static components = { Badge, Gauge, Sparkline, LineChart };
        state = { period: { month: '2026-10' }, data: { targets: { food_pct: { value: 32.25, operator: 'le', status: 'ok' } }, previous: { ratios: {} } } };
        current = { ratios: { food_pct: 30 } };
        trend = []; trendLabels = [];
        name = (v) => v; monthName = (v) => v; pct = formatPercent; fmt = formatNumber;
        changeValue() { return null; }
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Ratios, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.gauge-target').textContent).toInclude('≤32.3%');
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

test('in/out unavailable unreceived values use dashes with tooltips', async () => {
    const label = 'غير متوفر';
    const unavailable = { available: false, label, breakdown: [] };
    const available = { available: true, value: 50, breakdown: [{ key: 'app', name: 'تطبيق', value: 50 }] };
    const month = (name, apps) => ({ month: name, incoming: { available: true, gross: 100, channels: {}, warnings: [], apps_unreceived: apps }, outgoing: { available: true, total: 0, items: {}, sources: {} }, sales_vat: { value: 0 }, unpaid_bills: { value: 0 }, net: 100 });
    class Pnl extends Component {
        static template = 'baseer_dashboard2.Pnl';
        static components = { Sparkline };
        state = { view: 'inout', data: { months: [month('2026-10', unavailable), month('2026-11', available)], total: { incoming: 200, outgoing: 0, channels: {}, items: {}, sources: {}, apps_unreceived: available, sales_vat: 0, unpaid_bills: { value: 0 }, net: 200 } } };
        objectKeys = Object.keys; fmt = formatNumber; tableFmt = formatTable; tablePct = formatTablePct; hasDisplayValues = hasDisplayValues; multiplePoints = multiplePoints; monthName = (v) => v; name = (v) => v;
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
            daily_average: {}, days: [day], best_day: day, weekday_month: [], weekday_ytd: [],
            year_calendar: [{ month: '2026-10', days: [day] }], events: [], hours: { available: false },
        } };
        number = Number; weekdayName = () => ""; months = []; weekdays = []; calendarCells = [day]; hasCustomers = true;
        fmt = formatNumber; dateName = (v) => v; monthName = (v) => v;
        changeValue() { return null; }
        level() { return 1; } dayValue(d) { return d.gross; } yearPadding() { return []; }
    }
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(Heatmap, { templates: await response.text(), test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('.calendar .occasion-badge').textContent).toBe('عرض');
    expect(getFixture().querySelector('.year-occasion').title).toBe('عرض');
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


test('partial chart month uses a dashed segment and label', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(LineChart, { templates: await response.text(), props: { series: [
        { name: 'Sales', values: [100, 200], partial: [false, true] },
    ] }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelector('[stroke-dasharray="5 4"]')).not.toBe(null);
    expect(getFixture().textContent).toInclude('جزئي');
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
    expect(getFixture().querySelector('.food-progress i').style.width).toBe('100%');
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
        static components = { Sparkline };
        state = { view: 'pnl', closed: {}, data: { rows: [row('empty', [0, null]), row('active', [0, 20], [row('empty child', [0, 0]), row('active child', [3, 0])])] } };
        trend = []; hasDisplayValues = hasDisplayValues; name = v => v; monthName = v => v;
        tableFmt = formatTable; tablePct = formatTablePct; toggleRow() {} exportCsv() {}
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
    const latest = getFixture().querySelector('.spark-dot.gold.filled');
    expect(labels.length).toBe(10);
    expect(labels.map(label => parseFloat(label.style.left))).toEqual(Array.from({ length: 10 }, (_, i) => miniX(i, 10)));
    expect(parseFloat(latest.style.left)).toBe(miniX(9, labels.length));
    expect(parseFloat(latest.style.left)).toBeLessThan(parseFloat(labels[0].style.left));
    expect(getFixture().querySelector('.spark-label.gold').textContent).toBe('34.9%');
    expect(svg.getAttribute('preserveAspectRatio')).toBe('none');
    expect(svg.querySelectorAll('path')[2].getAttribute('d').split('M').length).toBe(3);
});

test('commission card uses recorded amount and salary badges explain suppression', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const doc = new DOMParser().parseFromString(await response.text(), 'text/xml');
    const revenue = doc.querySelector('[t-name="baseer_dashboard2.Revenue"]');
    const card = revenue.querySelector('[t-if="state.data.commissions.available"]');
    expect(card.querySelector('Money').getAttribute('value')).toBe('state.data.commissions.amount');
    expect(revenue.textContent.includes('عمولة X%')).toBe(false);
    expect(revenue.innerHTML.includes('commission_rate')).toBe(false);
    expect(doc.querySelector('[t-name="baseer_dashboard2.Badge"] [t-if="props.warning"]').getAttribute('title')).toInclude('رواتب الشهر السابق');
    const overview = doc.querySelector('[t-name="baseer_dashboard2.BreakEven"]');
    expect(overview.querySelector('.break-progress').getAttribute('t-if')).toBe('state.data.breakeven?.available');
    expect(overview.querySelector('.break-legend').getAttribute('t-if')).toBe('state.data.breakeven?.available');
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
    expect(doc.querySelector('[t-name="baseer_dashboard2.Overview"] .safety-chips').outerHTML).toInclude('(جزئي)');
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

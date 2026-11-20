import { after, expect, getFixture, globals, test, withFetch, click, press } from '@odoo/hoot';
import { animationFrame } from '@odoo/hoot-mock';
import { App, Component } from '@odoo/owl';
import { hourLabel, hasDisplayValues, formatNumber, formatTable, formatTablePct, chartX, timelineYear, InfoPopup, LineChart, niceStep, KpiCard, Sparkline } from '../src/js/main';

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
    expect(formatTablePct(-12.3)).toBe('-12.3%');
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
        fmt = formatNumber; tableFmt = formatTable; hasDisplayValues = hasDisplayValues; monthName = (v) => v; name = (v) => v;
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
        state = { view: 'inout', data: { months: [month('2026-10', unavailable)], total: { incoming: 100, outgoing: 0, channels: {}, items: {}, sources: {}, apps_unreceived: { ...available, available: false, label }, sales_vat: 0, unpaid_bills: { value: 0 }, net: 100 } } };
    }
    const secondApp = new App(UnavailableTotal, { templates, test: true });
    after(() => secondApp.destroy());
    await secondApp.mount(getFixture());
    for (const row of getFixture().querySelectorAll('.unreceived-row, .unreceived-app-row')) {
        expect(row.lastElementChild.textContent.trim()).toBe('—');
        expect(row.lastElementChild.title).toBe(label);
    }
    expect(getFixture().querySelector('.stats').textContent).toInclude(label);
});

test('heatmap renders occasion badges for an event day', async () => {
    const day = { date: '2026-10-03', gross: 100, customers: 1, events: [{ id: 1, name: 'عرض' }], warnings: [] };
    class Heatmap extends Component {
        static template = 'baseer_dashboard2.Heatmap';
        state = { metric: 'gross', period: { month: '2026-10' }, meta: {}, data: {
            daily_average: {}, days: [day], best_day: day, weekday_month: [], weekday_ytd: [],
            year_calendar: [{ month: '2026-10', days: [day] }], events: [], hours: { available: false },
        } };
        Number = Number; months = []; weekdays = []; calendarCells = [day]; hasCustomers = true;
        fmt = formatNumber; dateName = (v) => v; monthName = (v) => v;
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
});

test('hour labels follow the Riyadh clock', () => {
    expect(hourLabel(12)).toBe('12م');
    expect(hourLabel(13)).toBe('1م');
    expect(hourLabel(0)).toBe('12ص');
    expect(hourLabel(1)).toBe('1ص');
});

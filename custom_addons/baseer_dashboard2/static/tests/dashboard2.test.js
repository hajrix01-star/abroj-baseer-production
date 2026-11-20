import { after, expect, getFixture, globals, test, withFetch, click, press } from '@odoo/hoot';
import { animationFrame } from '@odoo/hoot-mock';
import { App, Component } from '@odoo/owl';
import { formatNumber, formatTable, formatTablePct, chartX, InfoPopup, LineChart, niceStep, KpiCard } from '../src/js/main';

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
        level() { return 1; } dayValue(d) { return d.gross; }
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


test('KPI sparkline renders two series and change badge', async () => {
    const response = await withFetch(globals.fetch, () => fetch('/baseer_dashboard2/static/src/xml/main.xml'));
    const app = new App(KpiCard, { templates: await response.text(), props: { title: 'Sales', value: 100, change: 10, trend: [50, null, 100], previousTrend: [null, 50, null] }, test: true });
    after(() => app.destroy());
    await app.mount(getFixture());
    expect(getFixture().querySelectorAll('.bd2-spark path').length).toBe(2);
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

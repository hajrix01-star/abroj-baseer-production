import { after, expect, getFixture, globals, test, withFetch } from '@odoo/hoot';
import { App, Component } from '@odoo/owl';
import { formatNumber, formatTable, formatTablePct, chartX } from '../src/js/main';

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

/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { BaseerTobaccoReport } from "@baseer_pos_tobacco_report/js/tobacco_report";

test("changing filters invalidates an in-flight preview before it can enable PDF", async () => {
    let resolvePreview;
    const pending = new Promise((resolve) => { resolvePreview = resolve; });
    const report = {
        requestToken: 0,
        state: {
            filters: { company_id: 1, period: "month", month: 9, year: 2026,
                date_from: "2026-09-01", date_to: "2026-09-30", show_products: false, page: 1 },
            loading: false, error: "", data: null,
        },
        orm: { call: () => pending },
    };
    const loading = BaseerTobaccoReport.prototype.load.call(report, 1);
    expect(report.state.loading).toBe(true);
    BaseerTobaccoReport.prototype.updateFilter.call(report, {
        target: { name: "month", value: "10" },
    });
    expect(report.state.filters.month).toBe(10);
    expect(report.state.loading).toBe(false);
    resolvePreview({ rows: [{ order: "SEPTEMBER" }], overflow: false });
    await loading;
    expect(report.state.data).toBe(null);
    expect(report.state.loading).toBe(false);
});

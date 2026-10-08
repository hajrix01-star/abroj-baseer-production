/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { BaseerTobaccoReport } from "@baseer_pos_tobacco_report/js/tobacco_report";

test("changing filters invalidates an in-flight preview before it can enable PDF", async () => {
    let resolvePreview;
    const pending = new Promise((resolve) => { resolvePreview = resolve; });
    const report = {
        requestToken: 0,
        companyGeneration: 0,
        activeCompanyId: 1,
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

test("monthly tobacco caption uses the applied full month only", () => {
    const report = { labels: { monthName: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"] },
        state: { data: { period_kind: "month", date_from: "2026-10-01", date_to: "2026-10-31", from_text: "01-10-2026", to_text: "31-10-2026" } } };
    const caption = Object.getOwnPropertyDescriptor(BaseerTobaccoReport.prototype, "periodCaption").get;
    expect(caption.call(report)).toBe("October 2026");
    report.state.data.period_kind = "custom";
    expect(caption.call(report)).toBe("01-10-2026 — 31-10-2026");
});

test("tobacco A-to-B-to-A ignores late context responses", async () => {
    let active = 1;
    const pending = [];
    const report = Object.create(BaseerTobaccoReport.prototype);
    Object.defineProperty(report, "activeCompanyId", { get: () => active });
    Object.assign(report, {
        companyGeneration: 0, requestToken: 0, lang: "en",
        state: { filters: { company_id: 0, page: 1 }, data: null, error: "", loading: false },
        orm: { call: () => new Promise((resolve) => pending.push(resolve)) },
        load: async () => { report.state.data = { company_id: report.state.filters.company_id }; },
    });
    const firstA = report.refreshActiveCompany();
    active = 2;
    const B = report.refreshActiveCompany();
    active = 1;
    const secondA = report.refreshActiveCompany();
    pending[2]({ company_id: 1, month: 10, year: 2026 });
    await secondA;
    pending[0]({ company_id: 1, month: 9, year: 2026 });
    pending[1]({ company_id: 2, month: 8, year: 2026 });
    await Promise.all([firstA, B]);
    expect(report.state.filters.company_id).toBe(1);
    expect(report.state.filters.month).toBe(10);
    expect(report.state.data.company_id).toBe(1);
});

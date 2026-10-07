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

test("tobacco Excel export sends full-period filters even from preview page two", async () => {
    const calls = [];
    const report = {
        state: {
            loading: false, exporting: false, error: "",
            data: { rows: [], overflow: false },
            filters: { company_id: 3, period: "month", month: 9, year: 2026,
                date_from: "2026-09-01", date_to: "2026-09-30", show_products: true, page: 2 },
        },
        orm: { call: async (...args) => {
            calls.push(args);
            return { type: "ir.actions.act_url", target: "download", url: "/baseer/pos/tobacco/export/1?company_id=3" };
        } },
        action: { doAction: async (action) => calls.push(action) },
    };
    await BaseerTobaccoReport.prototype.exportXlsx.call(report);
    expect(calls[0][0]).toBe("baseer.pos.tobacco.report.wizard");
    expect(calls[0][1]).toBe("export_hub_xlsx");
    expect(calls[0][2][0].page).toBe(2);
    expect(calls[1].target).toBe("download");
    expect(report.state.exporting).toBe(false);
});

test("tobacco Excel export clears busy state and surfaces a server busy message", async () => {
    const report = {
        state: { loading: false, exporting: false, error: "", data: { overflow: false }, filters: {} },
        labels: { exportError: "Could not export Excel" },
        orm: { call: async () => { throw { data: { message: "Export is running; retry." } }; } },
        action: { doAction: async () => {} },
    };
    await BaseerTobaccoReport.prototype.exportXlsx.call(report);
    expect(report.state.error).toBe("Export is running; retry.");
    expect(report.state.exporting).toBe(false);
});

test("tobacco Excel export does not start for overflow or missing preview", async () => {
    let called = false;
    const report = {
        state: { loading: false, exporting: false, error: "", data: { overflow: true }, filters: {} },
        orm: { call: async () => { called = true; } },
    };
    await BaseerTobaccoReport.prototype.exportXlsx.call(report);
    report.state.data = null;
    await BaseerTobaccoReport.prototype.exportXlsx.call(report);
    expect(called).toBe(false);
});

/** @odoo-module **/

import { after, expect, getFixture, globals, test, withFetch } from "@odoo/hoot";
import { click, queryOne, waitUntil } from "@odoo/hoot-dom";
import { App } from "@odoo/owl";
import { BaseerTobaccoReport } from "@baseer_pos_tobacco_report/js/tobacco_report";

test("clicking the rendered XLSX button exports the selected period and disables it while busy", async () => {
    const calls = [];
    const downloads = [];
    let resolveExport;
    const orm = {
        async call(model, method, args) {
            calls.push({ model, method, args });
            if (model !== "baseer.pos.tobacco.report.wizard") {
                throw new Error(`Unexpected model: ${model}`);
            }
            if (method === "get_hub_context") {
                return {
                    companies: [{ id: 3, name: "Test Company" }], company_id: 3,
                    month: 9, year: 2026, date_from: "2026-09-01", date_to: "2026-09-30",
                };
            }
            if (method === "get_hub_report") {
                return {
                    company_name: "Test Company", from_text: "2026-09-01", to_text: "2026-09-30",
                    opening: "0.00", debit_total: "0.00", credit_total: "100.00", closing: "100.00",
                    first_row: 1, last_row: 1, row_count: 2, currency: "SAR", page: args[0].page,
                    pages: 2, show_products: false, overflow: false, exception_count: "0", exceptions: [],
                    rows: [{ date: "2026-09-05 18:30", order: "POS-1", type: "Sale",
                        debit: "0.00", credit: "100.00", running: "100.00" }],
                };
            }
            if (method === "export_hub_xlsx") {
                return new Promise((resolve) => { resolveExport = resolve; });
            }
            throw new Error(`Unexpected RPC: ${model}.${method}`);
        },
    };
    const response = await withFetch(globals.fetch, () =>
        fetch("/baseer_pos_tobacco_report/static/src/xml/tobacco_report.xml")
    );
    expect(response.ok).toBe(true);
    const app = new App(BaseerTobaccoReport, {
        env: { services: { orm, action: { doAction: async (action) => downloads.push(action) } } },
        templates: await response.text(),
        props: {},
        test: true,
    });
    after(() => app.destroy());

    await app.mount(getFixture());
    const button = queryOne(".o_baseer_report_xlsx");
    expect(button.textContent.trim()).toBe("XLSX");
    expect(button.disabled).toBe(false);

    await click(".o_baseer_tobacco_pager button:last-child");
    expect(calls.filter((call) => call.method === "get_hub_report").at(-1).args[0].page).toBe(2);
    await click(".o_baseer_report_xlsx");
    const exportCalls = calls.filter((call) => call.method === "export_hub_xlsx");
    expect(exportCalls.length).toBe(1);
    expect(exportCalls[0].model).toBe("baseer.pos.tobacco.report.wizard");
    expect(exportCalls[0].args[0]).toEqual({
        company_id: 3, period: "month", month: 9, year: 2026,
        date_from: "2026-09-01", date_to: "2026-09-30", show_products: false, page: 2,
    });
    await waitUntil(() => queryOne(".o_baseer_report_xlsx").disabled);
    const busyButton = queryOne(".o_baseer_report_xlsx");
    expect(busyButton.disabled).toBe(true);
    busyButton.click();
    expect(calls.filter((call) => call.method === "export_hub_xlsx").length).toBe(1);

    const download = { type: "ir.actions.act_url", target: "download", url: "/baseer/pos/tobacco/export/1" };
    resolveExport(download);
    await waitUntil(() => !queryOne(".o_baseer_report_xlsx").disabled);
    expect(downloads).toEqual([download]);
    expect(queryOne(".o_baseer_report_xlsx").disabled).toBe(false);
});

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

/** @odoo-module **/

import { after, expect, getFixture, globals, test, withFetch } from "@odoo/hoot";
import { click, queryOne, waitUntil } from "@odoo/hoot-dom";
import { App } from "@odoo/owl";
import { download } from "@web/core/network/download";
import { user } from "@web/core/user";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerTobaccoReport } from "@baseer_pos_tobacco_report/js/tobacco_report";

async function tobaccoTemplates() {
    const [reportResponse, exportResponse] = await Promise.all([
        withFetch(globals.fetch, () => fetch("/baseer_pos_tobacco_report/static/src/xml/tobacco_report.xml")),
        withFetch(globals.fetch, () => fetch("/baseer_reports_menu/static/src/report_export.xml")),
    ]);
    expect(reportResponse.ok).toBe(true);
    expect(exportResponse.ok).toBe(true);
    const extra = (await exportResponse.text())
        .replace(/^\s*<\?xml[^>]*>\s*<templates[^>]*>/, "")
        .replace(/<\/templates>\s*$/, "");
    return (await reportResponse.text()).replace("</templates>", `${extra}</templates>`);
}

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
            loading: false, error: "", data: null, appliedFilters: null,
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

test("unified export retains exactly the last applied tobacco options", async () => {
    const filters = { company_id: 1, period: "month", month: 9, year: 2026,
        date_from: "2026-09-01", date_to: "2026-09-30", show_products: false, page: 1 };
    const report = {
        requestToken: 0, companyGeneration: 0, activeCompanyId: 1,
        state: { filters, loading: false, error: "", data: null, appliedFilters: null },
        orm: { call: async () => ({ overflow: false, rows: [] }) },
    };
    await BaseerTobaccoReport.prototype.load.call(report, 1);
    expect(report.state.appliedFilters).toEqual(filters);
    BaseerTobaccoReport.prototype.updateFilter.call(report, {
        target: { name: "month", value: "10" },
    });
    expect(report.state.filters.month).toBe(10);
    expect(report.state.appliedFilters.month).toBe(9);
    expect(report.state.data).toBe(null);
});

test("tobacco shared export button uses the applied report options", async () => {
    patchWithCleanup(user, { lang: "en_US", activeCompany: { id: 1 } });
    const requests = [];
    patchWithCleanup(download, { _download: async (request) => requests.push(request) });
    const orm = { call: async (_model, method) => {
        if (method === "get_hub_context") {
            return { company_id: 1, month: 10, year: 2026, date_from: "2026-10-01", date_to: "2026-10-31" };
        }
        if (method === "get_hub_report") {
            return { overflow: false, company_name: "Test Company", period_kind: "month",
                date_from: "2026-10-01", date_to: "2026-10-31", from_text: "01-10-2026", to_text: "31-10-2026",
                currency: "SAR", show_products: false, rows: [], exceptions: [], opening: "0.00",
                debit_total: "0.00", credit_total: "2.50", closing: "2.50", exception_count: "0",
                row_count: 0, page: 1, pages: 1, first_row: 0, last_row: 0 };
        }
        throw new Error(`Unexpected ${method}`);
    } };
    const app = new App(BaseerTobaccoReport, {
        env: { services: { orm, action: { doAction: async () => {} }, notification: { add: () => {} }, dialog: { add: () => {} } } },
        templates: await tobaccoTemplates(), props: {}, test: true,
    });
    after(() => app.destroy());
    await app.mount(getFixture());
    await waitUntil(() => !queryOne(".o_baseer_report_xlsx").disabled);
    await click(".o_baseer_report_xlsx");
    await waitUntil(() => requests.length === 1);
    expect(requests[0].data.report_key).toBe("tobacco");
    expect(JSON.parse(requests[0].data.filters)).toEqual({
        company_id: 1, period: "month", month: 10, year: 2026,
        date_from: "2026-10-01", date_to: "2026-10-31", show_products: false, page: 1,
    });
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

/** @odoo-module **/

import { after, expect, getFixture, globals, test, withFetch } from "@odoo/hoot";
import { click, queryOne, waitUntil } from "@odoo/hoot-dom";
import { App } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { SaudiVatReport } from "@baseer_tax_report/js/saudi_vat_report";

async function mountVisualReport(lang) {
    patchWithCleanup(user, { lang });
    const orm = {
        async call(model, method) {
            if (model !== "baseer.tax.report.wizard") {
                throw new Error(`Unexpected model: ${model}`);
            }
            if (method === "get_hub_options") {
                return {
                    companies: [{ id: 3, name: "Test Company" }], journals: [],
                    default_company_id: 3, default_year: 2026, default_quarter: "3",
                };
            }
            if (method === "get_hub_report") {
                return {
                    company: "Test Company", date_from: "2026-07-01", date_to: "2026-09-30",
                    currency: "SAR", exception: { count: 0, other_count: 0 },
                    rows: [
                        {
                            number: "1", name: "Taxed sales", base_text: "1,150.00", base_state: "",
                            tax_text: "0.00", tax_state: "zero",
                            direct: { base: true, tax: true }, components: { base: [], tax: [] },
                        },
                        {
                            number: "6", name: "Sales adjustment", base_text: "-15.00",
                            base_state: "negative", tax_text: "0.00", tax_state: "zero",
                            direct: { base: true, tax: true }, components: { base: [], tax: [] },
                        },
                        {
                            number: "13", name: "Net VAT", base_text: "0.00", base_state: "zero",
                            tax_text: "0.00", tax_state: "zero",
                            direct: { base: false, tax: false },
                            components: {
                                base: [{ number: "1", column: "tax", name: "Zero component",
                                    amount_text: "0.00", state: "zero" }],
                                tax: [],
                            },
                        },
                    ],
                };
            }
            throw new Error(`Unexpected RPC: ${model}.${method}`);
        },
    };
    const response = await withFetch(globals.fetch, () =>
        fetch("/baseer_tax_report/static/src/xml/saudi_vat_report.xml")
    );
    expect(response.ok).toBe(true);
    const app = new App(SaudiVatReport, {
        env: { services: { orm, action: { doAction: async () => {} } } },
        templates: await response.text(), props: {}, test: true,
    });
    after(() => app.destroy());
    await app.mount(getFixture());
    await waitUntil(() => Boolean(queryOne(".o_baseer_vat_table")));
}

test("clicking VAT XLSX exports the selected quarter, detailed view, and journals once", async () => {
    const calls = [];
    const downloads = [];
    let resolveExport;
    const orm = {
        async call(model, method, args) {
            calls.push({ model, method, args });
            if (model !== "baseer.tax.report.wizard") {
                throw new Error(`Unexpected model: ${model}`);
            }
            if (method === "get_hub_options") {
                return {
                    companies: [{ id: 3, name: "Test Company" }],
                    journals: [
                        { id: 5, name: "Sales", company_id: 3 },
                        { id: 7, name: "Purchases", company_id: 3 },
                    ],
                    default_company_id: 3, default_year: 2026, default_quarter: "3",
                };
            }
            if (method === "get_hub_report") {
                return {
                    company: "Test Company", date_from: "2026-07-01", date_to: "2026-09-30",
                    currency: "SAR", rows: [], exception: { count: 0, other_count: 0 },
                };
            }
            if (method === "export_hub_xlsx") {
                return new Promise((resolve) => { resolveExport = resolve; });
            }
            throw new Error(`Unexpected RPC: ${model}.${method}`);
        },
    };
    const response = await withFetch(globals.fetch, () =>
        fetch("/baseer_tax_report/static/src/xml/saudi_vat_report.xml")
    );
    expect(response.ok).toBe(true);
    const app = new App(SaudiVatReport, {
        env: { services: { orm, action: { doAction: async (action) => downloads.push(action) } } },
        templates: await response.text(), props: {}, test: true,
    });
    after(() => app.destroy());

    await app.mount(getFixture());
    await waitUntil(() => !queryOne(".o_baseer_report_apply").disabled);
    const display = queryOne('select:has(option[value="detailed"])');
    display.value = "detailed";
    display.dispatchEvent(new Event("change", { bubbles: true }));
    await waitUntil(() => queryOne(".o_baseer_report_xlsx").disabled);
    await click(".o_baseer_vat_journals summary");
    await click('.o_baseer_vat_journals input[value="5"]');
    await click('.o_baseer_vat_journals input[value="7"]');
    await click(".o_baseer_report_apply");
    await waitUntil(() => !queryOne(".o_baseer_report_xlsx").disabled);

    const button = queryOne(".o_baseer_report_xlsx");
    expect(button.textContent.trim()).toBe("XLSX");
    await click(".o_baseer_report_xlsx");
    const exports = calls.filter((call) => call.method === "export_hub_xlsx");
    expect(exports.length).toBe(1);
    expect(exports[0].args[0]).toEqual({
        company_id: 3, period_type: "quarter", year: 2026, month: "1", quarter: "3",
        display_mode: "detailed", journal_ids: [5, 7],
    });
    await waitUntil(() => queryOne(".o_baseer_report_xlsx").disabled);
    button.click();
    expect(calls.filter((call) => call.method === "export_hub_xlsx").length).toBe(1);

    const download = { type: "ir.actions.act_url", target: "download", url: "/baseer/tax/vat/export/1" };
    resolveExport(download);
    await waitUntil(() => !queryOne(".o_baseer_report_xlsx").disabled);
    expect(downloads).toEqual([download]);
    expect(queryOne(".o_baseer_report_xlsx").disabled).toBe(false);
});

test("VAT registers its real report component, not the legacy wizard form", () => {
    const descriptor = registry.category("baseer_reports").get("vat");
    expect(descriptor.kind).toBe("component");
    expect(descriptor.component).toBe(SaudiVatReport);
});

test("VAT request copies primitive filter values and never returns report data", () => {
    const state = {
        companyId: 3, periodType: "quarter", year: 2026, month: "9", quarter: "3",
        displayMode: "detailed", journalIds: [5, 7], data: { amount: "not an input" },
    };
    const payload = SaudiVatReport.prototype.payload.call({ state });
    expect(payload).toEqual({
        company_id: 3, period_type: "quarter", year: 2026, month: "9", quarter: "3",
        display_mode: "detailed", journal_ids: [5, 7],
    });
    state.journalIds.push(9);
    expect(payload.journal_ids).toEqual([5, 7]);
});

test("VAT visual amount states preserve muted zero and red negative", () => {
    expect(SaudiVatReport.prototype.amountClass("zero")).toBe("is-zero");
    expect(SaudiVatReport.prototype.amountClass("negative")).toBe("is-negative");
    expect(SaudiVatReport.prototype.amountClass("empty")).toBe("");
});

test("Arabic VAT paper renders RTL, isolated numbers, and a faint zero in expanded components", async () => {
    await mountVisualReport("ar_001");
    const root = queryOne(".o_baseer_vat_report");
    const paper = queryOne(".o_baseer_vat_paper");
    const canvas = queryOne(".o_baseer_report_canvas");
    expect(root.getAttribute("dir")).toBe("rtl");
    expect(queryOne(".o_baseer_vat_table caption").textContent).toBe("تقرير ضريبة القيمة المضافة");
    expect(window.getComputedStyle(paper).maxWidth).toBe("840px");
    const paperBox = paper.getBoundingClientRect();
    const canvasBox = canvas.getBoundingClientRect();
    expect(paperBox.width <= canvasBox.width + 1).toBe(true);
    expect(Math.abs((paperBox.left + paperBox.right) - (canvasBox.left + canvasBox.right)) <= 2).toBe(true);

    const zero = queryOne(".o_baseer_vat_table tbody tr:first-child .o_baseer_vat_cell_button.is-zero");
    const negative = queryOne(".o_baseer_vat_total .o_baseer_vat_cell_button.is-negative");
    expect(zero.getAttribute("dir")).toBe("ltr");
    expect(negative.textContent).toBe("-15.00");
    expect(window.getComputedStyle(zero).color).not.toBe(window.getComputedStyle(negative).color);

    await click('.o_baseer_vat_total .o_baseer_vat_cell_button[aria-expanded="false"]');
    const componentZero = queryOne(".o_baseer_vat_components .o_baseer_vat_cell_button.is-zero");
    expect(componentZero.textContent).toBe("0.00");
    expect(componentZero.getAttribute("dir")).toBe("ltr");
});

test("English VAT paper renders LTR and keeps the same server-provided amounts", async () => {
    await mountVisualReport("en_US");
    expect(queryOne(".o_baseer_vat_report").getAttribute("dir")).toBe("ltr");
    expect(queryOne(".o_baseer_vat_table caption").textContent).toBe("Saudi VAT Report");
    expect(queryOne(".o_baseer_vat_table tbody tr:first-child .o_baseer_vat_cell_button").textContent).toBe("1,150.00");
    expect(queryOne(".o_baseer_vat_total .o_baseer_vat_cell_button.is-negative").textContent).toBe("-15.00");
});

test("VAT Excel export sends current filters and opens the private download action", async () => {
    const calls = [];
    const instance = {
        state: { data: {}, exporting: false, error: "" },
        labels: { error: "Export failed" },
        payload: () => ({ company_id: 3, period_type: "quarter", year: 2026 }),
        orm: { call: async (...args) => {
            calls.push(args);
            return { type: "ir.actions.act_url", url: "/baseer/tax/vat/export/1?company_id=3", target: "download" };
        } },
        action: { doAction: async (action) => calls.push(action) },
    };
    await SaudiVatReport.prototype.exportXlsx.call(instance);
    expect(calls[0]).toEqual([
        "baseer.tax.report.wizard", "export_hub_xlsx",
        [{ company_id: 3, period_type: "quarter", year: 2026 }],
    ]);
    expect(calls[1].target).toBe("download");
    expect(instance.state.exporting).toBe(false);
});

test("VAT Excel export gives an export-specific failure and clears busy state", async () => {
    const instance = {
        state: { data: {}, exporting: false, error: "" },
        labels: { exportError: "Excel export failed" },
        payload: () => ({}),
        orm: { call: async () => { throw new Error("server failure"); } },
        action: { doAction: async () => {} },
    };
    await SaudiVatReport.prototype.exportXlsx.call(instance);
    expect(instance.state.error).toBe("Excel export failed");
    expect(instance.state.exporting).toBe(false);
});

/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";
import { SaudiVatReport } from "@baseer_tax_report/js/saudi_vat_report";

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

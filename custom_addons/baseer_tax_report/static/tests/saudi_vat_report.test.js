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

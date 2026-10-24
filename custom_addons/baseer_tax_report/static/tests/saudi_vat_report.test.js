/** @odoo-module **/

import { after, expect, getFixture, globals, test, withFetch } from "@odoo/hoot";
import { click, queryOne, waitUntil } from "@odoo/hoot-dom";
import { App } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";
import { user } from "@web/core/user";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { SaudiVatReport } from "@baseer_tax_report/js/saudi_vat_report";

async function vatTemplates() {
    const [reportResponse, exportResponse] = await Promise.all([
        withFetch(globals.fetch, () => fetch("/baseer_tax_report/static/src/xml/saudi_vat_report.xml")),
        withFetch(globals.fetch, () => fetch("/baseer_reports_menu/static/src/report_export.xml")),
    ]);
    expect(reportResponse.ok).toBe(true);
    expect(exportResponse.ok).toBe(true);
    const extra = (await exportResponse.text())
        .replace(/^\s*<\?xml[^>]*>\s*<templates[^>]*>/, "")
        .replace(/<\/templates>\s*$/, "");
    return (await reportResponse.text()).replace("</templates>", `${extra}</templates>`);
}

async function mountVisualReport(lang, withWarnings = false) {
    patchWithCleanup(user, { lang, activeCompany: { id: 3 } });
    const dialogs = [];
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
                    currency: "SAR", exception: withWarnings
                        ? { count: 1, amount_text: "-42.13", amount_state: "negative",
                            other_count: 1, other_amount_text: "-100.00", other_amount_state: "negative" }
                        : { count: 0, other_count: 0 },
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
                            number: "13", name: "Net VAT", base_text: "—", base_state: "empty",
                            tax_text: "0.00", tax_state: "zero",
                            direct: { base: false, tax: false },
                            components: {
                                tax: [{ number: "1", column: "tax", name: "Zero component",
                                    amount_text: "0.00", state: "zero" }],
                                base: [],
                            },
                        },
                    ],
                };
            }
            throw new Error(`Unexpected RPC: ${model}.${method}`);
        },
    };
    const app = new App(SaudiVatReport, {
        env: { services: { orm, action: { doAction: async () => {} }, notification: { add: () => {} },
            dialog: { add: (component, props) => dialogs.push({ component, ...props }) } } },
        templates: await vatTemplates(), props: {}, test: true,
    });
    after(() => app.destroy());
    await app.mount(getFixture());
    await waitUntil(() => Boolean(queryOne(".o_baseer_vat_table")));
    return dialogs;
}

test("VAT warning keeps untagged VAT distinct from other fees in Arabic", async () => {
    await mountVisualReport("ar_001", true);
    const warnings = document.querySelectorAll(".o_baseer_report_warning");
    expect(warnings.length).toBe(2);
    expect(warnings[0].textContent.includes("قيود ضريبة القيمة المضافة غير المصنفة")).toBe(true);
    expect(warnings[0].textContent.includes("راجع وسومها الضريبية")).toBe(true);
    expect(warnings[0].querySelector(".o_baseer_vat_warning_help").title.includes("راجع وسومها الضريبية")).toBe(true);
    expect(warnings[1].textContent.includes("قيود رسوم وضرائب أخرى بلا وسوم")).toBe(true);
    expect(warnings[1].textContent.includes("راجع تصنيف الضرائب والرسوم الأخرى غير الموسومة")).toBe(true);
    expect(warnings[1].querySelector(".o_baseer_vat_warning_help").title.includes("راجع تصنيف الضرائب والرسوم الأخرى غير الموسومة")).toBe(true);
});

test("VAT warning describes remaining untagged fees in English", async () => {
    await mountVisualReport("en_US", true);
    const warnings = document.querySelectorAll(".o_baseer_report_warning");
    expect(warnings.length).toBe(2);
    expect(warnings[1].textContent.includes("Other untagged fees and taxes")).toBe(true);
    expect(warnings[1].textContent.includes("Review the classification of the remaining untagged taxes and fees")).toBe(true);
    expect(warnings[1].querySelector(".o_baseer_vat_warning_help").title.includes("Review the classification of the remaining untagged taxes and fees")).toBe(true);
});

test("VAT unified export captures the applied detailed quarter and journals once", async () => {
    patchWithCleanup(user, { activeCompany: { id: 3 } });
    const calls = [];
    const requests = [];
    patchWithCleanup(download, { _download: async (request) => requests.push(request) });
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
            throw new Error(`Unexpected RPC: ${model}.${method}`);
        },
    };
    const app = new App(SaudiVatReport, {
        env: { services: { orm, action: { doAction: async () => {} }, notification: { add: () => {} }, dialog: { add: () => {} } } },
        templates: await vatTemplates(), props: {}, test: true,
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
    expect(button.textContent.trim()).toBe("Excel");
    await click(".o_baseer_report_xlsx");
    await waitUntil(() => requests.length === 1);
    expect(requests[0].data.report_key).toBe("vat");
    expect(requests[0].data.file_format).toBe("xlsx");
    expect(JSON.parse(requests[0].data.filters)).toEqual({
        company_id: 3, period_type: "quarter", year: 2026, month: "1", quarter: "3",
        display_mode: "detailed", journal_ids: [5, 7],
    });
    expect(calls.filter((call) => call.method === "export_hub_xlsx").length).toBe(0);
    await waitUntil(() => !queryOne(".o_baseer_report_xlsx").disabled);
    expect(queryOne(".o_baseer_report_xlsx").disabled).toBe(false);
    expect(document.querySelector('select[aria-label="Company"]')).toBe(null);
});

test("VAT month caption is based on applied report dates and not pending filters", () => {
    const context = { lang: "ar", labels: { months: ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"] },
        state: { data: { period_type: "month", date_from: "2026-10-01", date_to: "2026-10-31" } } };
    const caption = Object.getOwnPropertyDescriptor(SaudiVatReport.prototype, "periodCaption").get;
    expect(caption.call(context)).toBe("أكتوبر 2026");
    context.state.data.date_to = "2026-10-20";
    expect(caption.call(context)).toBe("2026-10-01 — 2026-10-20");
});

test("VAT A-to-B-to-A company changes ignore late option responses", async () => {
    let active = 1;
    const pending = [];
    const report = Object.create(SaudiVatReport.prototype);
    Object.defineProperty(report, "activeCompanyId", { get: () => active });
    Object.assign(report, {
        companyGeneration: 0, epoch: 0, lang: "en",
        state: { companyId: 0, journals: [], journalIds: [], data: null, expanded: {}, loading: false, error: "" },
        orm: { call: () => new Promise((resolve) => pending.push(resolve)) },
        apply: async () => { report.state.data = { company_id: report.state.companyId }; },
    });
    const firstA = report.loadOptions();
    active = 2;
    const B = report.loadOptions();
    active = 1;
    const secondA = report.loadOptions();
    pending[2]({ default_company_id: 1, journals: [{ id: 30 }], default_year: 2026, default_quarter: "3" });
    await secondA;
    pending[0]({ default_company_id: 1, journals: [{ id: 10 }] });
    pending[1]({ default_company_id: 2, journals: [{ id: 20 }] });
    await Promise.all([firstA, B]);
    expect(report.state.companyId).toBe(1);
    expect(report.state.journals).toEqual([{ id: 30 }]);
    expect(report.state.data.company_id).toBe(1);
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

test("Arabic VAT paper preserves RTL, isolated numbers and faint zero while composites open shared details", async () => {
    const dialogs = await mountVisualReport("ar_001");
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

    const compositeZero = queryOne(".o_baseer_vat_table tbody tr:last-child .o_baseer_vat_cell_button");
    expect(compositeZero.textContent).toBe("0.00");
    expect(compositeZero.getAttribute("dir")).toBe("ltr");
    expect(compositeZero.classList.contains("is-zero")).toBe(true);
    expect(compositeZero.hasAttribute("aria-expanded")).toBe(false);
    compositeZero.click();
    await waitUntil(() => dialogs.length === 1);
    expect(dialogs[0].selector).toEqual({ kind: "cell", box: "13", column: "tax" });
    expect(dialogs[0].reportKey).toBe("vat");
    expect(document.querySelector(".o_baseer_vat_components")).toBe(null);
    expect(queryOne(".o_baseer_vat_table tbody tr:last-child td:nth-child(2)").textContent.includes("—")).toBe(true);
    expect(queryOne(".o_baseer_vat_table tbody tr:last-child td:nth-child(2)").querySelector("button")).toBe(null);
});

test("VAT direct, composite and warning amounts use one dialog with captured applied scope", async () => {
    const dialogs = await mountVisualReport("en_US", true);
    const buttons = [...document.querySelectorAll(".o_baseer_vat_table .o_baseer_vat_cell_button")];
    expect(buttons.length).toBe(5);
    for (const button of buttons) { button.click(); }
    const warnings = [...document.querySelectorAll(".o_baseer_report_warning .o_baseer_report_amount")];
    expect(warnings.length).toBe(2);
    expect(warnings.map((button) => button.textContent)).toEqual(["-42.13", "-100.00"]);
    for (const button of warnings) {
        expect(button.tagName).toBe("BUTTON");
        expect(button.getAttribute("dir")).toBe("ltr");
        button.click();
    }
    await waitUntil(() => dialogs.length === 7);
    expect(dialogs.map((dialog) => dialog.selector)).toEqual([
        { kind: "cell", box: "1", column: "base" }, { kind: "cell", box: "1", column: "tax" },
        { kind: "cell", box: "6", column: "base" }, { kind: "cell", box: "6", column: "tax" },
        { kind: "cell", box: "13", column: "tax" },
        { kind: "exception", class: "vat" }, { kind: "exception", class: "other" },
    ]);
    for (const dialog of dialogs) {
        expect(dialog.component).toBe(dialogs[0].component);
        expect(dialog.reportKey).toBe("vat");
        expect(dialog.filters).toEqual({ company_id: 3, period_type: "quarter", year: 2026,
            month: "1", quarter: "3", display_mode: "simple", journal_ids: [] });
    }
    patchWithCleanup(user, { activeCompany: { id: 4 } });
    buttons[0].click();
    expect(dialogs.length).toBe(7);
});

test("English VAT paper renders LTR and keeps the same server-provided amounts", async () => {
    await mountVisualReport("en_US");
    expect(queryOne(".o_baseer_vat_report").getAttribute("dir")).toBe("ltr");
    expect(queryOne(".o_baseer_vat_table caption").textContent).toBe("Saudi VAT Report");
    expect(queryOne(".o_baseer_vat_table tbody tr:first-child td:nth-child(2) .o_baseer_vat_cell_button").textContent).toBe("1,150.00");
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

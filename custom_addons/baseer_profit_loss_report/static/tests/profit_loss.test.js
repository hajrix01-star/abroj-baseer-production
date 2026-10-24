/** @odoo-module **/

import { expect, globals, test, withFetch } from "@odoo/hoot";
import { click, waitUntil } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { download } from "@web/core/network/download";
import { mockService, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerProfitLossReport } from "@baseer_profit_loss_report/profit_loss";

const MODEL = "baseer.profit.loss.report";
defineMailModels();
const filters = {
    company_id: 1,
    period: { kind: "month", anchor_date: "2026-10-15", direction: 0, date_from: "", date_to: "" },
    comparison: { kind: "previous_period", order: "descending", count: 1, date_from: "", date_to: "" },
    journal_ids: [],
};
const periods = [
    { key: "current", role: "primary", label: "2026-10-01 — 2026-10-31", display_label: "Oct 2026", date_from: "2026-10-01", date_to: "2026-10-31" },
    { key: "previous_1", role: "comparison", label: "2026-09-01 — 2026-09-30", display_label: "Sep 2026", date_from: "2026-09-01", date_to: "2026-09-30" },
];

function mockReportRequests(calls) {
    const handlers = {};
    const onRequest = (method, handler) => { handlers[method] = handler; };
    onRequest("get_context", () => ({
        companies: [{ id: 1, name: "Baseer" }], journals: [],
        default_filters: filters,
    }));
    onRequest("get_report", ({ args }) => {
        calls.push(["get_report", args]);
        return {
            company: { name: "Baseer", currency_code: "SAR" }, periods,
            period_controls: { kind: "month", anchor_date: "2026-10-15", direction: 0, options: [
                { kind: "month", display_label: "Oct 2026" }, { kind: "quarter", display_label: "Q4 2026" },
                { kind: "fiscal_year", display_label: "2026" }, { kind: "custom", display_label: "Custom Dates" },
            ] },
            is_partial_journals: false,
            rows: [
                { key: "income", kind: "section", section: "income", label: "Income", expandable: true,
                    amounts: { current: { amount: "1,150.00", negative: false }, previous_1: { amount: "900.00", negative: false } } },
                { key: "total_income", kind: "subtotal", label: "Total Income",
                    amounts: { current: { amount: "1,150.00", negative: false }, previous_1: { amount: "900.00", negative: false } } },
                { key: "expense_direct_cost", kind: "subtotal", label: "Cost of Sales",
                    amounts: { current: { amount: "0.00", negative: false }, previous_1: { amount: "0.00", negative: false } } },
                { key: "gross_profit", kind: "subtotal", label: "Gross Profit",
                    amounts: { current: { amount: "1,150.00", negative: false }, previous_1: { amount: "900.00", negative: false } } },
                { key: "expense", kind: "section", section: "expense", label: "Expense", expandable: true,
                    amounts: { current: { amount: "-1,200.00", negative: true }, previous_1: { amount: "-750.00", negative: true } } },
                { key: "total_expense", kind: "subtotal", label: "Total Expense",
                    amounts: { current: { amount: "-1,200.00", negative: true }, previous_1: { amount: "-750.00", negative: true } } },
                { key: "net_profit", kind: "result", label: "Net Income",
                    amounts: { current: { amount: "-50.00", negative: true }, previous_1: { amount: "150.00", negative: false } } },
            ],
        };
    });
    onRequest("get_accounts", ({ args }) => {
        calls.push(["get_accounts", args]);
        return { accounts: [{ id: 7, code: "400000", name: "Sales", move_line_counts: { current: 1, previous_1: 0 },
            amounts: { current: { amount: "1,150.00", negative: false }, previous_1: { amount: "0.00", negative: false } } }], page: 1, page_size: 100, total_count: 1 };
    });
    onRequest("get_account_action", ({ args }) => {
        calls.push(["get_account_action", args]);
        return { type: "ir.actions.act_window", name: "Journal Items", res_model: "account.move.line", target: "current", domain: [["account_id", "=", 7]] };
    });
    return { async call(model, method, args) {
        if (model !== MODEL || !handlers[method]) { throw new Error(`Unexpected report RPC: ${model}.${method}`); }
        return handlers[method]({ args });
    } };
}

async function mountReport(calls) {
    patchWithCleanup(user, { activeCompany: { id: 1 } });
    const response = await withFetch(globals.fetch, () => fetch("/baseer_profit_loss_report/static/src/profit_loss.xml"));
    expect(response.ok).toBe(true);
    const shared = await withFetch(globals.fetch, () => fetch("/baseer_reports_menu/static/src/report_export.xml"));
    expect(shared.ok).toBe(true);
    const templates = "<templates>" + [await response.text(), await shared.text()].map((text) =>
        text.replace(/<\?xml[^>]*>/, "").replace(/<templates[^>]*>/, "").replace("</templates>", "")).join("") + "</templates>";
    mockService("orm", mockReportRequests(calls));
    mockService("notification", { add() {} });
    const dialogs = [];
    mockService("dialog", { add: (_component, props) => dialogs.push(props) });
    await mountWithCleanup(BaseerProfitLossReport, { templates, props: {} });
    await waitUntil(() => document.querySelector(".o_baseer_report_title"));
    return dialogs;
}

test("profit and loss summary, account name, nonzero and zero amounts open the same applied-scope details", async () => {
    const calls = [];
    const dialogs = await mountReport(calls);
    await click(".o_baseer_pl_income td .o_baseer_amount_link");
    expect(dialogs[0].selector).toEqual({ kind: "row", row_key: "income", period_key: "current" });
    expect(dialogs[0].filters.company_id).toBe(1);
    await click(".o_baseer_pl_income .o_baseer_pl_toggle");
    await waitUntil(() => document.querySelectorAll(".o_baseer_pl_account_amount").length === 2);
    const buttons = document.querySelectorAll(".o_baseer_pl_account_amount");
    expect(buttons[1].disabled).toBe(false);
    buttons[1].click();
    await waitUntil(() => dialogs.length === 2);
    expect(dialogs[1].selector).toEqual({ kind: "account", account_id: 7, period_key: "previous_1" });
    buttons[0].click();
    await waitUntil(() => dialogs.length === 3);
    expect(dialogs[2].selector).toEqual({ kind: "account", account_id: 7, period_key: "current" });
    await click(".o_baseer_pl_account th .o_baseer_amount_link");
    await waitUntil(() => dialogs.length === 4);
    expect(dialogs[3].selector).toEqual(dialogs[2].selector);
    for (const dialog of dialogs) {
        expect(dialog.reportKey).toBe("profit_loss");
        expect(dialog.filters).toEqual(filters);
    }
    expect(calls.filter(([method]) => method === "get_account_action")).toEqual([]);
});

test("profit and loss remains a real accounting-only report component", () => {
    const descriptor = registry.category("baseer_reports").get("profit_loss");
    expect(descriptor.kind).toBe("component");
    expect(descriptor.component).toBe(BaseerProfitLossReport);
    expect(descriptor.groups).toEqual(["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"]);
});

test("profit and loss shared exports send only the applied report filters", async () => {
    const requests = [];
    patchWithCleanup(download, { _download: async (request) => requests.push(request) });
    await mountReport([]);
    await click(".o_baseer_report_exports .o_baseer_report_xlsx");
    await waitUntil(() => requests.length === 1);
    expect(requests[0].data.report_key).toBe("profit_loss");
    expect(requests[0].data.file_format).toBe("xlsx");
    const selected = JSON.parse(requests[0].data.filters);
    expect(selected.company_id).toBe(1);
    expect(selected.period.anchor_date).toBe("2026-10-15");
    expect(Object.keys(requests[0].data).sort()).toEqual(["file_format", "filters", "report_key"]);
});

test("amount styling receives only server-formatted values", () => {
    const classify = BaseerProfitLossReport.prototype.amountClass;
    expect(classify({ amount: "0.00", negative: false })).toBe("is-zero");
    expect(classify({ amount: "0.000", negative: true })).toBe("is-zero");
    expect(classify({ amount: "-1,200.00", negative: true })).toBe("is-negative");
    expect(classify({ amount: "1,200.00", negative: false })).toBe("");
});

test("period navigation delegates calendar movement to the server", async () => {
    const calls = [];
    const instance = Object.create(BaseerProfitLossReport.prototype);
    Object.assign(instance, {
        state: { filters: structuredClone(filters), loading: false, error: "", report: null, expanded: {}, pages: {}, accountLoading: {} },
        requestToken: 0, appliedFilters: null, lang: "en", orm: { call: async (_model, method, args) => {
            calls.push([method, args]);
            return { company: { name: "Baseer", currency_code: "SAR" }, periods, rows: [], period_controls: { anchor_date: "2026-09-15" } };
        } },
    });
    await instance.navigatePeriod(-1);
    expect(calls[0][0]).toBe("get_report");
    expect(calls[0][1][0].period.direction).toBe(-1);
    expect(calls[0][1][0].period.anchor_date).toBe("2026-10-15");
    expect(instance.state.filters.period.anchor_date).toBe("2026-09-15");
});

test("changing from three prior periods resets the server count for every single-period comparison", async () => {
    for (const kind of ["none", "same_period_last_year", "custom"]) {
        const context = {
            state: { filters: { comparison: { kind: "previous_period", count: 3 } } },
            apply: async () => {},
        };
        await BaseerProfitLossReport.prototype.setComparisonKind.call(context, kind);
        expect(context.state.filters.comparison.kind).toBe(kind);
        expect(context.state.filters.comparison.count).toBe(1);
    }
});

test("custom dates do not send an unsupported navigation direction", async () => {
    let applied = false;
    const context = {
        state: { filters: { period: { kind: "custom" } } },
        apply: async () => { applied = true; },
    };
    await BaseerProfitLossReport.prototype.navigatePeriod.call(context, -1);
    expect(applied).toBe(false);
});

test("custom period and comparison prepare real dates before their first RPC", async () => {
    let applied = 0;
    const periodContext = {
        primaryPeriod: { date_from: "2026-10-01", date_to: "2026-10-31" },
        state: { filters: { period: { kind: "month", direction: 0, date_from: "", date_to: "" } } },
        apply: async () => applied++,
    };
    await BaseerProfitLossReport.prototype.setPeriodKind.call(periodContext, "custom");
    expect(periodContext.state.filters.period.date_from).toBe("2026-10-01");
    expect(periodContext.state.filters.period.date_to).toBe("2026-10-31");
    const comparisonContext = {
        primaryPeriod: { date_from: "2026-10-01", date_to: "2026-10-31" },
        state: { filters: { comparison: { kind: "none", count: 1, date_from: "", date_to: "" } } },
        apply: async () => applied++,
    };
    await BaseerProfitLossReport.prototype.setComparisonKind.call(comparisonContext, "custom");
    expect(comparisonContext.state.filters.comparison.date_from).toBe("2026-10-01");
    expect(comparisonContext.state.filters.comparison.date_to).toBe("2026-10-31");
    expect(applied).toBe(0);
});

test("a period-menu arrow changes its own server period kind before navigating", async () => {
    const directions = [];
    const context = {
        state: { filters: { period: { kind: "month", direction: 0 } } },
        apply: async (direction) => directions.push(direction),
    };
    await BaseerProfitLossReport.prototype.navigatePeriodKind.call(context, "quarter", -1);
    expect(context.state.filters.period.kind).toBe("quarter");
    expect(context.state.filters.period.direction).toBe(0);
    expect(directions).toEqual([-1]);
});

test("account clicks route to details for the exact period without a direct source RPC", async () => {
    const calls = [];
    const actions = [];
    const dialogs = [];
    const context = { appliedFilters: structuredClone(filters),
        drill: { open: (selector) => dialogs.push(selector) },
        orm: { call: async (...args) => calls.push(args) },
        env: { services: { action: { doAction: async (action) => actions.push(action) } } } };
    for (const count of [0, 1]) {
        await BaseerProfitLossReport.prototype.openAccount.call(context,
            { id: 7, code: "400000", move_line_counts: { previous_1: count } }, "previous_1");
    }
    expect(dialogs).toEqual([
        { kind: "account", account_id: 7, period_key: "previous_1" },
        { kind: "account", account_id: 7, period_key: "previous_1" },
    ]);
    context.appliedFilters = null;
    await BaseerProfitLossReport.prototype.openAccount.call(context, { id: 7 }, "current");
    expect(dialogs.length).toBe(2);
    expect(calls).toEqual([]);
    expect(actions).toEqual([]);
});

test("mounted report displays comparison columns without inline journal entries", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [];
    await mountReport(calls);
    expect(document.querySelector(".o_baseer_pl_report").getAttribute("dir")).toBe("ltr");
    expect(document.querySelectorAll(".o_baseer_pl_table thead .is-number").length).toBe(4);
    expect(document.querySelector(".o_baseer_pl_result .is-negative").textContent).toBe("-50.00");
    expect(document.querySelector(".o_baseer_pl_table td").getAttribute("data-label")).toBe("Oct 2026");
    expect(document.querySelector('select[aria-label="Company"]')).toBe(null);
    expect(document.querySelector(".o_baseer_report_period").textContent.includes("Baseer")).toBe(true);
    expect(document.querySelector(".o_baseer_report_period").textContent.includes("Oct 2026")).toBe(true);
    await click('.o_baseer_pl_section button[aria-label="Income"]');
    await waitUntil(() => document.querySelector(".o_baseer_pl_account"));
    expect(calls.map(([method]) => method)).toEqual(["get_report", "get_accounts"]);
    expect(document.querySelector(".o_baseer_pl_lines_row")).toBe(null);
});

test("PDF prints applied filters and rejects a late action after company change", async () => {
    let active = 1;
    const calls = [];
    const actions = [];
    let finish;
    const report = Object.create(BaseerProfitLossReport.prototype);
    Object.defineProperty(report, "activeCompanyId", { get: () => active });
    Object.assign(report, {
        appliedFilters: structuredClone(filters), requestToken: 4, companyGeneration: 2, lang: "en",
        state: { report: {}, loading: false, printing: false, error: "" },
        orm: { call: (...args) => { calls.push(args); return new Promise((resolve) => { finish = resolve; }); } },
        env: { services: { action: { doAction: async (action) => actions.push(action) } } },
    });
    const pending = report.printReport();
    expect(calls[0][1]).toBe("action_print");
    expect(calls[0][2][0].company_id).toBe(1);
    active = 2;
    report.requestToken += 1;
    report.companyGeneration += 1;
    active = 1;
    report.requestToken += 1;
    report.companyGeneration += 1;
    finish({ type: "ir.actions.report", report_name: "baseer_profit_loss_report.profit_loss_pdf_portrait" });
    await pending;
    expect(actions).toEqual([]);
});

test("PDF opens the server action only for the current report generation", async () => {
    const actions = [];
    const report = Object.create(BaseerProfitLossReport.prototype);
    Object.defineProperty(report, "activeCompanyId", { get: () => 1 });
    Object.assign(report, {
        appliedFilters: structuredClone(filters), requestToken: 7, companyGeneration: 3, lang: "en",
        state: { report: {}, loading: false, printing: false, error: "" },
        orm: { call: async (_model, method, args) => {
            expect(method).toBe("action_print");
            expect(args[0].company_id).toBe(1);
            return { type: "ir.actions.report", report_name: "baseer_profit_loss_report.profit_loss_pdf_portrait" };
        } },
        env: { services: { action: { doAction: async (action) => actions.push(action) } } },
    });
    await report.printReport();
    expect(actions.length).toBe(1);
    expect(report.state.printing).toBe(false);
});

test("monthly paper caption keeps explicit dates for a partial month", () => {
    const context = {
        primaryPeriod: { date_from: "2026-10-07", date_to: "2026-10-31", display_label: "Oct 2026", label: "2026-10-07 — 2026-10-31" },
        appliedFilters: { period: { kind: "month" } },
    };
    expect(Object.getOwnPropertyDescriptor(BaseerProfitLossReport.prototype, "reportPeriodCaption").get.call(context)).toBe("2026-10-07 — 2026-10-31");
});

test("profit and loss A-to-B-to-A ignores stale contexts", async () => {
    let active = 1;
    const pending = [];
    const report = Object.create(BaseerProfitLossReport.prototype);
    Object.defineProperty(report, "activeCompanyId", { get: () => active });
    Object.assign(report, {
        companyGeneration: 0, requestToken: 0, appliedFilters: null, lang: "en",
        state: { filters: structuredClone(filters), journals: [], report: null, error: "", loading: false,
            expanded: {}, pages: {}, accountLoading: {} },
        orm: { call: () => new Promise((resolve) => pending.push(resolve)) },
        apply: async () => { report.state.report = { company_id: report.state.filters.company_id }; },
    });
    const firstA = report.refreshActiveCompany();
    active = 2;
    const B = report.refreshActiveCompany();
    active = 1;
    const secondA = report.refreshActiveCompany();
    pending[2]({ default_company_id: 1, journals: [{ id: 30 }] });
    await secondA;
    pending[0]({ default_company_id: 1, journals: [{ id: 10 }] });
    pending[1]({ default_company_id: 2, journals: [{ id: 20 }] });
    await Promise.all([firstA, B]);
    expect(report.state.filters.company_id).toBe(1);
    expect(report.state.journals).toEqual([{ id: 30 }]);
    expect(report.state.report.company_id).toBe(1);
});

test("applied export scope never adopts an unfinished draft edited during report load", async () => {
    patchWithCleanup(user, { activeCompany: { id: 1 } });
    let resolve;
    const report = Object.create(BaseerProfitLossReport.prototype);
    Object.assign(report, {
        companyGeneration: 0, requestToken: 0, appliedFilters: null, lang: "en",
        state: { filters: structuredClone(filters), journals: [], report: null, error: "", loading: false,
            expanded: {}, pages: {}, accountLoading: {} },
        orm: { call: () => new Promise((done) => { resolve = done; }) },
    });
    const pending = report.apply();
    report.state.filters.period.kind = "custom";
    report.state.filters.period.date_from = "2026-12-01";
    report.state.filters.journal_ids.push(99);
    resolve({ rows: [], periods, period_controls: { anchor_date: "2026-10-15" } });
    await pending;
    expect(report.appliedFilters.period.kind).toBe("month");
    expect(report.appliedFilters.period.date_from).toBe("");
    expect(report.appliedFilters.journal_ids).toEqual([]);
    expect(report.state.filters.period.kind).toBe("custom");
});

test("native period and comparison controls open Odoo popovers", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [];
    await mountReport(calls);
    await click('.o_baseer_pl_filter_chip[aria-label="Period"]');
    await waitUntil(() => document.querySelector(".o_baseer_pl_native_dropdown.o_baseer_pl_period_menu"));
    expect(document.querySelectorAll(".o_baseer_pl_period_popover .o_baseer_pl_menu_row").length).toBe(4);
    expect(document.querySelector(".o_baseer_pl_period_popover .o_baseer_pl_menu_value").textContent).toBe("Oct 2026");
    await click('.o_baseer_pl_filter_chip[aria-label="Comparison"]');
    await waitUntil(() => document.querySelector(".o_baseer_pl_native_dropdown.o_baseer_pl_comparison_menu"));
    expect(document.querySelectorAll(".o_baseer_pl_comparison_popover .dropdown-item").length).toBe(4);
});

test("mounted Arabic report keeps backend values and exposes Arabic period filters", async () => {
    patchWithCleanup(user, { lang: "ar_001" });
    await mountReport([]);
    expect(document.querySelector(".o_baseer_pl_report").getAttribute("dir")).toBe("rtl");
    expect(document.querySelector(".o_baseer_report_title").textContent).toBe("الربح والخسارة");
    expect(document.querySelector('.o_baseer_pl_filter_chip[aria-label="المقارنة"]').textContent.includes("دون مقارنة") || document.querySelector('.o_baseer_pl_filter_chip[aria-label="المقارنة"]').textContent.includes("الفترات السابقة")).toBe(true);
    expect(document.querySelector(".o_baseer_pl_result .is-negative").textContent).toBe("-50.00");
});

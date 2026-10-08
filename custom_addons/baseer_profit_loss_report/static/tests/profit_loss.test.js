/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { mountWithCleanup, mockService, onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerProfitLossReport } from "@baseer_profit_loss_report/profit_loss";

const MODEL = "baseer.profit.loss.report";

function mockReportRequests(calls) {
    const filters = { company_id: 1, date_from: "2026-10-01", date_to: "2026-10-31", journal_ids: [] };
    onRpc("get_context", MODEL, () => ({
        companies: [{ id: 1, name: "Baseer" }], journals: [],
        default_company_id: 1, default_date_from: filters.date_from, default_date_to: filters.date_to,
    }));
    onRpc("get_report", MODEL, ({ args }) => {
        calls.push(["get_report", args]);
        return {
            company: { name: "Baseer", currency_code: "SAR" },
            period: { date_from: filters.date_from, date_to: filters.date_to },
            is_partial_journals: false,
            sections: [
                { key: "income", amount: "1,150.00", negative: false },
                { key: "expense_direct_cost", amount: "0.00", negative: false },
                { key: "expense", amount: "-1,200.00", negative: true },
            ],
            gross_profit: { amount: "1,150.00", negative: false },
            net_profit: { amount: "-50.00", negative: true },
        };
    });
    onRpc("get_accounts", MODEL, ({ args }) => {
        calls.push(["get_accounts", args]);
        return {
            accounts: [{ id: 7, code: "400000", name: "Sales", amount: "1,150.00", negative: false }],
            page: 1, page_size: 50, total_count: 1,
        };
    });
    onRpc("get_lines", MODEL, ({ args }) => {
        calls.push(["get_lines", args]);
        return {
            lines: [{ id: 42, date: "2026-10-07", move_name: "INV/42", label: "Sale",
                debit: "0.00", credit: "1,150.00", amount: "1,150.00", negative: false }],
            page: 1, page_size: 50, total_count: 1,
        };
    });
    onRpc("get_source_line", MODEL, ({ args }) => {
        calls.push(["get_source_line", args]);
        return { line_id: 42, move_id: 9 };
    });
}

test("profit and loss is a real accounting-only report component", () => {
    const descriptor = registry.category("baseer_reports").get("profit_loss");
    expect(descriptor.kind).toBe("component");
    expect(descriptor.component).toBe(BaseerProfitLossReport);
    expect(descriptor.groups).toEqual([
        "account.group_account_readonly", "account.group_account_user", "account.group_account_manager",
    ]);
});

test("zero is faint and negative amounts are red without client financial arithmetic", () => {
    const classify = BaseerProfitLossReport.prototype.amountClass;
    expect(classify(false, "0.00")).toBe("is-zero");
    expect(classify(true, "0.000")).toBe("is-zero");
    expect(classify(true, "-1,200.00")).toBe("is-negative");
    expect(classify(false, "1,200.00")).toBe("");
});

test("source click verifies the exact line server-side before opening a filtered journal-item list", async () => {
    const calls = [];
    const actions = [];
    const context = {
        appliedFilters: { company_id: 1, date_from: "2041-01-01", date_to: "2041-01-31", journal_ids: [] },
        requestToken: 0,
        state: { lineOpening: {}, error: "" },
        labels: { source: "View entries", error: "Could not open" },
        orm: { call: async (...args) => {
            calls.push(args);
            return { line_id: 42, move_id: 9 };
        } },
        action: { doAction: async (action) => actions.push(action) },
    };
    await BaseerProfitLossReport.prototype.openLine.call(context, { id: 42, move_name: "MISC/42" });
    expect(calls[0][1]).toBe("get_source_line");
    expect(calls[0][2][1]).toBe(42);
    expect(actions[0].res_model).toBe("account.move.line");
    expect(actions[0].domain).toEqual([["id", "=", 42]]);
    expect(context.state.lineOpening[42]).toBe(false);
});

test("mounted report expands real QWeb rows and opens only the verified source line", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [];
    const actions = [];
    mockReportRequests(calls);
    mockService("action", {
        doAction: async (action) => actions.push(action),
    });

    await mountWithCleanup(BaseerProfitLossReport);
    expect(document.querySelector(".o_baseer_pl_report").getAttribute("dir")).toBe("ltr");
    expect(document.querySelector(".o_baseer_report_title").textContent).toBe("Profit and Loss");
    expect(document.querySelector(".o_baseer_pl_net .o_baseer_report_amount").classList.contains("is-negative")).toBe(true);
    expect(document.querySelector(".o_baseer_pl_section .o_baseer_report_amount").textContent).toBe("1,150.00");
    expect(document.querySelectorAll(".o_baseer_pl_section .o_baseer_report_amount")[1].classList.contains("is-zero")).toBe(true);

    await click('.o_baseer_pl_section button[aria-label="Revenue"]');
    expect(document.querySelector('.o_baseer_pl_section button[aria-label="Revenue"]').getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector(".o_baseer_pl_account").textContent).toContain("400000");
    await click('.o_baseer_pl_account button[aria-label="View entries 400000 Sales"]');
    expect(document.querySelector('.o_baseer_pl_source[aria-label="View entries INV/42"]')).not.toBe(null);
    await click('.o_baseer_pl_source[aria-label="View entries INV/42"]');

    expect(calls.map(([method]) => method)).toEqual([
        "get_report", "get_accounts", "get_lines", "get_source_line",
    ]);
    expect(calls[3][1][1]).toBe(42);
    expect(actions[0].res_model).toBe("account.move.line");
    expect(actions[0].domain).toEqual([["id", "=", 42]]);
});

test("mounted Arabic report uses RTL labels without changing server-provided amounts", async () => {
    patchWithCleanup(user, { lang: "ar_001" });
    mockReportRequests([]);

    await mountWithCleanup(BaseerProfitLossReport);
    expect(document.querySelector(".o_baseer_pl_report").getAttribute("dir")).toBe("rtl");
    expect(document.querySelector(".o_baseer_report_title").textContent).toBe("الربح والخسارة");
    expect(document.querySelector('.o_baseer_pl_section button[aria-label="الإيرادات"]')).not.toBe(null);
    expect(document.querySelector(".o_baseer_pl_net .o_baseer_report_amount").textContent).toBe("-50.00");
});

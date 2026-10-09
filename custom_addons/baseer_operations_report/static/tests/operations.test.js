/** @odoo-module **/

import { expect, globals, test, withFetch } from "@odoo/hoot";
import { click, waitUntil } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { user } from "@web/core/user";
import { mockService, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerOperationsPreview, prepareOperationsSnapshot } from "@baseer_operations_report/operations";

defineMailModels();

test("operations preview preserves server amounts, row order, and detail fingerprints", () => {
    const fingerprint = "a".repeat(64);
    const snapshot = {
        complete: false, currency_code: "SAR", periods: [{
            key: "current", label: "2026-10-01 — 2026-10-31",
            rows: ["income", "cost_of_sales", "gross_profit", "expense",
                "net_operating_income", "other_income", "other_expense",
                "net_other_income", "net_income"].map((key) => ({
                    key, amount: key === "income" ? "115.00" : key === "net_income" ? "-7.50" : "0.00",
                    negative: key === "net_income",
                })),
            accounts: { income: [{ account_id: 7, account_code: "400000",
                account_name: "Sales", amount: "115.00", negative: false,
                source_count: 1, fingerprint }], cost_of_sales: [], expense: [],
                other_income: [], other_expense: [] },
        }],
    };
    const output = prepareOperationsSnapshot(snapshot, "Baseer", false, {
        income: "Income", net_income: "Net operations",
    });
    expect(output.report.complete).toBe(false);
    expect(output.report.rows.map((row) => row.key)).toEqual([
        "income", "cost_of_sales", "gross_profit", "expense",
        "net_operating_income", "other_income", "other_expense",
        "net_other_income", "net_income",
    ]);
    expect(output.report.rows[0].amounts.current.amount).toBe("115.00");
    expect(output.report.rows[8].amounts.current.amount).toBe("-7.50");
    expect(output.accounts.income[0].fingerprints.current).toBe(fingerprint);
    expect(output.accounts.income[0].sourceCounts.current).toBe(1);
});

test("operations preview rejects a missing financial row instead of showing zero", () => {
    expect(() => prepareOperationsSnapshot({ periods: [{
        key: "current", rows: [{ key: "income", amount: "115.00", negative: false }],
        accounts: { income: [], cost_of_sales: [], expense: [],
            other_income: [], other_expense: [] },
    }] }, "Baseer", false, { income: "Income" })).toThrow();
});

test("operations preview opens a separate source page and preserves the warning", async () => {
    const fingerprint = "b".repeat(64);
    const calls = [];
    patchWithCleanup(user, { activeCompany: { id: 1 } });
    // POS services are loaded by this module's dependencies, but this test
    // mounts only the accounting preview. Do not initialize a POS session.
    mockService("pos_data", {});
    mockService("pos", {});
    mockService("orm", { async call(model, method, args) {
        calls.push([model, method, args]);
        if (model === "baseer.profit.loss.report" && method === "get_context") {
            return { companies: [{ id: 1, name: "Baseer" }], journals: [],
                default_filters: { company_id: 1, period: { kind: "month", anchor_date: "2026-06-15" },
                    comparison: { kind: "none", count: 1, order: "descending" }, journal_ids: [] } };
        }
        if (model === "baseer.operations.report" && method === "get_source_snapshot") {
            return { company_id: 1, complete: false, currency_code: "SAR",
                period_controls: { kind: "month", anchor_date: "2026-06-15", options: [
                    { kind: "month", display_label: "Jun 2026" },
                    { kind: "quarter", display_label: "Q2 2026" },
                    { kind: "fiscal_year", display_label: "2026" },
                    { kind: "custom", display_label: "Custom Dates" },
                ] }, periods: [{ key: "current", label: "2026-06-01 — 2026-06-30",
                    display_label: "Jun 2026", date_from: "2026-06-01", date_to: "2026-06-30",
                    unconfirmed_count: 1, excluded: { unassigned_native_payment: 1 },
                    rows: ["income", "cost_of_sales", "gross_profit", "expense",
                        "net_operating_income", "other_income", "other_expense",
                        "net_other_income", "net_income"].map((key) => ({
                            key, amount: key === "expense" ? "50.00" : "0.00", negative: false,
                        })),
                    accounts: { income: [], cost_of_sales: [],
                        expense: [{ account_id: 7, account_code: "600000", account_name: "Purchases",
                            amount: "50.00", negative: false, source_count: 1, fingerprint }],
                        other_income: [], other_expense: [] },
                }] };
        }
        if (model === "baseer.operations.report" && method === "get_account_events") {
            return { page: 1, page_size: 50, total_count: 1,
                events: [{ date: "2026-06-15", amount: "50.00", source_model: "account.payment",
                    source_id: 9, link_status: "unconfirmed" }] };
        }
        throw new Error(`Unexpected report RPC: ${model}.${method}`);
    } });
    const response = await withFetch(globals.fetch, () =>
        fetch("/baseer_operations_report/static/src/operations.xml"));
    expect(response.ok).toBe(true);
    await mountWithCleanup(BaseerOperationsPreview, {
        templates: await response.text(), props: {},
    });
    await waitUntil(() => document.querySelector(".o_baseer_report_title"));
    expect(document.querySelector(".o_baseer_go_incomplete").textContent.includes("1")).toBe(true);
    await click(".o_baseer_pl_expense .o_baseer_pl_toggle");
    await waitUntil(() => document.querySelector(".o_baseer_pl_account_amount"));
    await click(".o_baseer_pl_account_amount");
    await waitUntil(() => document.querySelector(".o_baseer_go_detail_page .o_baseer_go_events"));
    expect(document.querySelector(".o_baseer_go_events").textContent.includes("50.00")).toBe(true);
    expect(document.querySelector(".o_baseer_go_uncertain").textContent.length > 0).toBe(true);
    expect(calls.some(([model, method, args]) => model === "baseer.operations.report" &&
        method === "get_account_events" && args[4] === fingerprint)).toBe(true);
    await click(".o_baseer_go_back");
    await waitUntil(() => document.querySelector(".o_baseer_pl_expense"));
});

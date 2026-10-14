/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { prepareOperationsSnapshot } from "@baseer_operations_report/operations";

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
                source_count: 1, fingerprint, channels: [
                    { key: "cash", name: "Cash", amount: "50.00", negative: false },
                    { key: "card", name: "Card", amount: "65.00", negative: false },
                ] }], cost_of_sales: [], expense: [],
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
    expect(output.accounts.income[0].channels[0].amounts.current.amount).toBe("50.00");
    expect(output.accounts.income[0].channels[1].amounts.current.amount).toBe("65.00");
    const comparison = structuredClone(snapshot.periods[0]);
    comparison.key = "previous";
    comparison.accounts.income[0].channels = [
        { key: "card", name: "Card", amount: "-7.50", negative: true },
    ];
    const compared = prepareOperationsSnapshot({ ...snapshot,
        periods: [snapshot.periods[0], comparison] }, "Baseer", false, {});
    expect(compared.accounts.income[0].channels).toHaveLength(2);
    expect(compared.accounts.income[0].channels[1].amounts.previous).toEqual({ amount: "-7.50", negative: true });
    expect(compared.accounts.income[0].channels[0].amounts.previous).toBe(undefined);
    expect(compared.accounts.income[0].amounts.current.amount).toBe("115.00");
    const completeOutput = prepareOperationsSnapshot({ ...snapshot, complete: true },
        "Baseer", false, { income: "Income", net_income: "Net operations" });
    expect(completeOutput.report.complete).toBe(true);
});

test("operations preview rejects a missing financial row instead of showing zero", () => {
    expect(() => prepareOperationsSnapshot({ complete: false, periods: [{
        key: "current", rows: [{ key: "income", amount: "115.00", negative: false }],
        accounts: { income: [], cost_of_sales: [], expense: [],
            other_income: [], other_expense: [] },
    }] }, "Baseer", false, { income: "Income" })).toThrow();
});

test("operations preview rejects a missing completeness state", () => {
    expect(() => prepareOperationsSnapshot({ periods: [] }, "Baseer", false, {})).toThrow();
});

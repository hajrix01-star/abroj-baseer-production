/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { prepareOperationsSnapshot } from "@baseer_operations_report/operations";

test("operations preview preserves server amounts, row order, and detail fingerprints", () => {
    const fingerprint = "a".repeat(64);
    const snapshot = {
        complete: false, currency_code: "SAR", periods: [{
            key: "current", label: "2026-10-01 — 2026-10-31",
            rows: [
                { key: "income", amount: "115.00", negative: false },
                { key: "net_income", amount: "-7.50", negative: true },
            ],
            accounts: { income: [{ account_id: 7, account_code: "400000",
                account_name: "Sales", amount: "115.00", negative: false,
                source_count: 1, fingerprint }] },
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

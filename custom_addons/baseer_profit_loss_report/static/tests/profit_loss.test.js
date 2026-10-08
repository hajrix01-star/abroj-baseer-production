/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";
import { BaseerProfitLossReport } from "@baseer_profit_loss_report/profit_loss";

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

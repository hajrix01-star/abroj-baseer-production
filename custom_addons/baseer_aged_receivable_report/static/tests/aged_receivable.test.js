/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";
import { BaseerAgedReceivableReport } from "@baseer_aged_receivable_report/aged_receivable";

const MODEL = "baseer.aged.receivable.report";

function instance(call) {
    const report = Object.create(BaseerAgedReceivableReport.prototype);
    Object.defineProperty(report, "activeCompanyId", { get: () => 1 });
    Object.assign(report, {
        lang: "en", requestToken: 0, linesToken: 0, appliedCutoff: null,
        state: {
            cutoffDate: "2026-10-09", report: null, loading: false, printing: false,
            error: "", expandedPartnerId: null, lines: null, linesLoading: false,
            openingLineId: null,
        },
        orm: { call }, action: { doAction: async () => {} },
    });
    return report;
}

test("aged receivables is registered for accounting readers after the general ledger", () => {
    const descriptor = registry.category("baseer_reports").get("aged_receivable");
    expect(descriptor.kind).toBe("component");
    expect(descriptor.sequence).toBe(60);
    expect(descriptor.component).toBe(BaseerAgedReceivableReport);
    expect(descriptor.groups).toEqual([
        "account.group_account_readonly", "account.group_account_user", "account.group_account_manager",
    ]);
});

test("cutoff, partner pages, and PDF pass backend options without calculating money", async () => {
    const calls = [];
    const actions = [];
    const report = instance(async (model, method, args) => {
        calls.push([model, method, args]);
        if (method === "get_report") {
            return { cutoff_date: "2026-10-09", summary: { receivables: "1,000.00", credits: "200.00", net: "800.00" },
                partners: [{ id: 7, name: "A", receivables: "1,000.00", credits: "200.00", net: "800.00", open_count: 2 }],
                page: args[0].page, page_count: 2, partner_count: 101 };
        }
        if (method === "get_partner_lines") {
            return { lines: [{ id: 9, open: "-200.00", kind: "unapplied_credit", bucket: "credit" }], page: 1, page_count: 1 };
        }
        return { type: "ir.actions.report" };
    });
    report.action.doAction = async (action) => actions.push(action);
    await report.loadReport("2026-10-09", 1);
    await report.changePage(2);
    await report.togglePartner(7);
    await report.printReport();
    expect(calls.map((call) => call[1])).toEqual(["get_report", "get_report", "get_partner_lines", "action_print"]);
    expect(calls[1]).toEqual([MODEL, "get_report", [{ cutoff_date: "2026-10-09", page: 2 }]]);
    expect(calls[2]).toEqual([MODEL, "get_partner_lines", [{ cutoff_date: "2026-10-09", partner_id: 7, page: 1 }]]);
    expect(calls[3]).toEqual([MODEL, "action_print", [{ cutoff_date: "2026-10-09" }]]);
    expect(report.state.lines.lines[0].open).toBe("-200.00");
    expect(actions.length).toBe(1);
});

test("late report responses are ignored after the cutoff changes", async () => {
    let finish;
    const report = instance(() => new Promise((resolve) => { finish = resolve; }));
    const pending = report.loadReport("2026-10-09", 1);
    report.onDateChange({ target: { value: "2026-10-08" } });
    finish({ cutoff_date: "2026-10-09", partners: [], page: 1, page_count: 1 });
    await pending;
    expect(report.state.report).toBe(null);
    expect(report.appliedCutoff).toBe(null);
    expect(report.state.cutoffDate).toBe("2026-10-08");
});

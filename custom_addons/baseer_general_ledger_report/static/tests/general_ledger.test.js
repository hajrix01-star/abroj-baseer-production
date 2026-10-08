/** @odoo-module **/

import { after, expect, getFixture, globals, test, withFetch } from "@odoo/hoot";
import { click, waitUntil } from "@odoo/hoot-dom";
import { App } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerGeneralLedgerReport } from "@baseer_general_ledger_report/general_ledger";

function mockOrm(calls) {
    const result = {
        company: { id: 1, name: "Baseer", currency_code: "SAR" },
        period: { date_from: "2026-10-01", date_to: "2026-10-31", fiscal_start: "2026-01-01" },
        is_partial_journals: false, page: 1, page_size: 100, page_count: 1,
        account_count: 1,
        accounts: [{ id: 7, code: "101000", name: "Bank", opening: "0.00",
            debit: "1,150.00", credit: "1,200.00", closing: "-50.00",
            opening_negative: false, closing_negative: true }],
        rbf: { amount: "0.00", negative: false, source_line_count: 0 },
        total: { opening: "0.00", debit: "1,150.00", credit: "1,200.00",
            closing: "-50.00", opening_negative: false, closing_negative: true },
    };
    return {
        async call(model, method, args) {
            if (model !== "baseer.general.ledger.report") { throw new Error(`Unexpected ${model}`); }
            calls.push([method, args]);
            if (method === "get_context") {
                return { companies: [{ id: 1, name: "Baseer" }], journals: [],
                    default_company_id: 1, default_date_from: "2026-10-01",
                    default_date_to: "2026-10-31" };
            }
            if (method === "get_report") { return result; }
            if (method === "get_lines") {
                return { lines: [{ id: 42, date: "2026-10-07", move_name: "BNK/42",
                    label: "Bank payment", debit: "0.00", credit: "1,200.00",
                    running: "-50.00", running_negative: true }], next_cursor: null };
            }
            if (method === "get_source_line") { return { line_id: 42, move_id: 9 }; }
            throw new Error(`Unexpected ${method}`);
        },
    };
}

async function mount(calls, actions) {
    const response = await withFetch(globals.fetch, () =>
        fetch("/baseer_general_ledger_report/static/src/general_ledger.xml")
    );
    expect(response.ok).toBe(true);
    const app = new App(BaseerGeneralLedgerReport, {
        env: { services: {
            orm: mockOrm(calls), action: { doAction: async (action) => actions.push(action) },
        } },
        templates: await response.text(), props: {}, test: true,
    });
    after(() => app.destroy());
    await app.mount(getFixture());
    await waitUntil(() => document.querySelector(".o_baseer_gl_account"));
}

test("ledger is accounting-only and never exposes a placeholder PDF or XLSX", () => {
    const descriptor = registry.category("baseer_reports").get("general_ledger");
    expect(descriptor.component).toBe(BaseerGeneralLedgerReport);
    expect(descriptor.groups).toEqual([
        "account.group_account_readonly", "account.group_account_user", "account.group_account_manager",
    ]);
    const amountClass = BaseerGeneralLedgerReport.prototype.amountClass;
    expect(amountClass(false, "0.00")).toBe("is-zero");
    expect(amountClass(true, "-1,200.00")).toBe("is-negative");
});

test("ledger opens the exact verified source in a drilldown", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [], actions = [];
    await mount(calls, actions);
    expect(document.querySelector(".o_baseer_gl_report").getAttribute("dir")).toBe("ltr");
    expect(document.querySelector(".o_baseer_report_title").textContent).toBe("General Ledger");
    expect(document.querySelector(".o_baseer_gl_account .o_baseer_report_amount").classList.contains("is-zero")).toBe(true);
    expect(document.querySelectorAll(".o_baseer_gl_account .o_baseer_report_amount")[3].classList.contains("is-negative")).toBe(true);
    expect(document.querySelector(".o_baseer_gl_report .o_baseer_report_pdf")).toBe(null);
    expect(document.querySelector(".o_baseer_gl_report .o_baseer_report_xlsx")).toBe(null);
    await click('.o_baseer_gl_account button[aria-label="View entry 101000 Bank"]');
    await waitUntil(() => document.querySelector('.o_baseer_gl_source[aria-label="View entry BNK/42"]'));
    await click('.o_baseer_gl_source[aria-label="View entry BNK/42"]');
    expect(calls.map(([method]) => method)).toEqual([
        "get_context", "get_report", "get_lines", "get_source_line",
    ]);
    expect(actions[0].res_model).toBe("account.move.line");
    expect(actions[0].domain).toEqual([["id", "=", 42]]);
});

test("Arabic ledger is RTL while source amounts keep western digits", async () => {
    patchWithCleanup(user, { lang: "ar_001" });
    await mount([], []);
    expect(document.querySelector(".o_baseer_gl_report").getAttribute("dir")).toBe("rtl");
    expect(document.querySelector(".o_baseer_report_title").textContent).toBe("دفتر الأستاذ العام");
    expect(document.querySelector(".o_baseer_gl_account").textContent).toContain("1,150.00");
});

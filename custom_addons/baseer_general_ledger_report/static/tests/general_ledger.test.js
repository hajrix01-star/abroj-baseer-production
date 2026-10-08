/** @odoo-module **/

import { after, expect, getFixture, globals, test, withFetch } from "@odoo/hoot";
import { click, waitUntil } from "@odoo/hoot-dom";
import { App } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerGeneralLedgerReport } from "@baseer_general_ledger_report/general_ledger";

function mockOrm(calls, accountOverrides = {}) {
    const result = {
        company: { id: 1, name: "Baseer", currency_code: "SAR" },
        period: { date_from: "2026-10-01", date_to: "2026-10-31", fiscal_start: "2026-01-01" },
        is_partial_journals: false, page: 1, page_size: 100, page_count: 1,
        account_count: 1,
        accounts: [{ id: 7, code: "101000", name: "Bank", opening: "0.00",
            debit: "1,150.00", credit: "1,200.00", closing: "-50.00",
            opening_negative: false, closing_negative: true,
            period_line_count: 2, opening_source_count: 0, ...accountOverrides }],
        rbf: { amount: "0.00", negative: false, source_line_count: 0 },
        total: { opening: "0.00", debit: "1,150.00", credit: "1,200.00",
            closing: "-50.00", opening_negative: false, closing_negative: true },
    };
    return {
        async call(model, method, args) {
            if (model !== "baseer.general.ledger.report") { throw new Error(`Unexpected ${model}`); }
            calls.push([method, args]);
            if (method === "get_context") {
                return { journals: [{ id: 11, code: "MISC", name: "Miscellaneous" }],
                    default_company_id: 1, default_date_from: "2026-10-01",
                    default_date_to: "2026-10-31",
                    default_period: { kind: "month", anchor_date: "2026-10-15", date_from: "2026-10-01",
                        date_to: "2026-10-31", display_label: "October 2026", is_full_calendar_month: true } };
            }
            if (method === "resolve_period") {
                const options = args[0];
                if (options.kind === "custom") {
                    return { kind: "custom", anchor_date: options.date_from,
                        date_from: options.date_from, date_to: options.date_to,
                        display_label: `${options.date_from} — ${options.date_to}`,
                        is_full_calendar_month: false };
                }
                const month = options.direction === 1 ? "11" : "10";
                return { kind: options.kind, anchor_date: `2026-${month}-15`,
                    date_from: `2026-${month}-01`, date_to: `2026-${month === "11" ? "30" : "31"}`,
                    display_label: month === "11" ? "November 2026" : "October 2026",
                    is_full_calendar_month: true };
            }
            if (method === "get_report") {
                return { ...result, period: { ...result.period,
                    date_from: args[0].date_from, date_to: args[0].date_to } };
            }
            if (method === "get_account_action") {
                return { type: "ir.actions.act_window", name: "Journal Items",
                    res_model: "account.move.line", target: "current",
                    domain: [["account_id", "=", 7]] };
            }
            throw new Error(`Unexpected ${method}`);
        },
    };
}

async function mount(calls, actions, accountOverrides = {}) {
    patchWithCleanup(user, { activeCompany: { id: 1 } });
    const response = await withFetch(globals.fetch, () =>
        fetch("/baseer_general_ledger_report/static/src/general_ledger.xml")
    );
    expect(response.ok).toBe(true);
    const app = new App(BaseerGeneralLedgerReport, {
        env: { services: {
            orm: mockOrm(calls, accountOverrides), action: { doAction: async (action) => actions.push(action) },
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

test("ledger opens a native journal-items page instead of inserting entries", async () => {
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
    await waitUntil(() => actions.length === 1);
    expect(calls.map(([method]) => method)).toEqual([
        "get_context", "get_report", "get_account_action",
    ]);
    expect(actions[0].res_model).toBe("account.move.line");
    expect(actions[0].target).toBe("current");
    expect(actions[0].domain).toEqual([["account_id", "=", 7]]);
    expect(document.querySelector(".o_baseer_gl_details")).toBe(null);
});

test("Arabic ledger is RTL while source amounts keep western digits", async () => {
    patchWithCleanup(user, { lang: "ar_001" });
    await mount([], []);
    expect(document.querySelector(".o_baseer_gl_report").getAttribute("dir")).toBe("rtl");
    expect(document.querySelector(".o_baseer_report_title").textContent).toBe("دفتر الأستاذ العام");
    expect(document.querySelector(".o_baseer_gl_account").textContent.includes("1,150.00")).toBe(true);
});

test("period control uses a full month label and sends server-resolved navigation dates", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [];
    await mount(calls, []);
    expect(document.querySelector('select[aria-label="Company"]')).toBe(null);
    expect(document.querySelector(".o_baseer_report_period").textContent.includes("October 2026")).toBe(true);
    await click('button[aria-label="Next Period"]');
    await waitUntil(() => document.querySelector(".o_baseer_report_period").textContent.includes("November 2026"));
    const periodCall = calls.find(([method]) => method === "resolve_period");
    expect(periodCall[1][0]).toEqual({ company_id: 1, kind: "month", anchor_date: "2026-10-31",
        direction: 1, date_from: "", date_to: "" });
    expect(calls.at(-1)[1][0].date_from).toBe("2026-11-01");
});

test("journal selection changes the actual report filters", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [];
    await mount(calls, []);
    await click(".o_baseer_gl_journals summary");
    await click('.o_baseer_gl_journal_list input[value="11"]');
    await waitUntil(() => calls.filter(([method]) => method === "get_report").length === 2);
    expect(calls.at(-1)[1][0].journal_ids).toEqual([11]);
});

test("a journal change with custom dates first resolves those dates", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [];
    await mount(calls, []);
    await click(".o_baseer_gl_period summary");
    await click(".o_baseer_gl_period_list > button:last-of-type");
    await click(".o_baseer_gl_journals summary");
    await click('.o_baseer_gl_journal_list input[value="11"]');
    await waitUntil(() => calls.filter(([method]) => method === "get_report").length === 2);
    expect(calls.at(-2)[0]).toBe("resolve_period");
    expect(calls.at(-2)[1][0].kind).toBe("custom");
    expect(calls.at(-1)[1][0].journal_ids).toEqual([11]);
    expect(document.querySelector(".o_baseer_report_period").textContent.includes("2026-10-01 — 2026-10-31")).toBe(true);
});

test("A to B to A company switch rejects the delayed original A report", async () => {
    const active = { id: 1 };
    patchWithCleanup(user, { activeCompany: active });
    let releaseOldA;
    let aRequests = 0;
    const instance = Object.create(BaseerGeneralLedgerReport.prototype);
    Object.assign(instance, {
        lang: "en", requestToken: 0, appliedFilters: null,
        state: { loading: false, error: "", journals: [], report: null, period: null,
            periodKind: "month", customFrom: "", customTo: "",
            filters: { company_id: 0, date_from: "", date_to: "", journal_ids: [] },
            rbfOpen: false, rbfLoading: false, rbfAccounts: null, accountOpening: {} },
        orm: { async call(_model, method, args) {
            const companyId = method === "get_context" ? args[0] : args[0].company_id;
            if (method === "get_context") {
                return { journals: [], default_period: { kind: "month", anchor_date: "2026-10-15",
                    date_from: "2026-10-01", date_to: "2026-10-31", display_label: "October 2026" } };
            }
            if (companyId === 1 && ++aRequests === 1) {
                return new Promise((resolve) => { releaseOldA = resolve; });
            }
            return { company: { id: companyId, name: `fresh ${companyId}` } };
        } },
    });
    const first = instance.refreshCompany();
    await waitUntil(() => !!releaseOldA);
    active.id = 2;
    await instance.refreshCompany();
    expect(instance.state.report.company.name).toBe("fresh 2");
    active.id = 1;
    await instance.refreshCompany();
    expect(instance.state.report.company.name).toBe("fresh 1");
    releaseOldA({ company: { id: 1, name: "stale 1" } });
    await first;
    expect(instance.state.report.company.name).toBe("fresh 1");
});

test("opening balance opens its own native source even with period movements", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [], actions = [];
    await mount(calls, actions, { opening: "140.00", opening_source_count: 2 });
    await click('.o_baseer_gl_account button[aria-label="View opening balance source 101000 Bank"]');
    await waitUntil(() => actions.length === 1);
    expect(calls.at(-1)[0]).toBe("get_account_action");
    expect(calls.at(-1)[1][2]).toBe("opening");
    expect(actions[0].res_model).toBe("account.move.line");
});

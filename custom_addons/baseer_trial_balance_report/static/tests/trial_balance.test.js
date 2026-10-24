/** @odoo-module **/

import { after, expect, getFixture, globals, test, withFetch } from "@odoo/hoot";
import { click, waitUntil } from "@odoo/hoot-dom";
import { App } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { download } from "@web/core/network/download";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerTrialBalanceReport } from "@baseer_trial_balance_report/trial_balance";

function mockOrm(calls) {
    return {
        async call(model, method, args) {
            expect(model).toBe("baseer.trial.balance.report");
            calls.push([method, args]);
            if (method === "get_context") {
                return {
                    journals: [{ id: 11, code: "MISC", name: "Miscellaneous" }],
                    default_period: { kind: "month", anchor_date: "2026-10-15",
                        date_from: "2026-10-01", date_to: "2026-10-31",
                        display_label: "October 2026" },
                };
            }
            if (method === "resolve_period") {
                const options = args[0];
                if (options.kind === "custom") {
                    return { kind: "custom", anchor_date: options.date_from,
                        date_from: options.date_from, date_to: options.date_to,
                        display_label: `${options.date_from} — ${options.date_to}` };
                }
                const month = options.direction === 1 ? "11" : "10";
                return { kind: options.kind, anchor_date: `2026-${month}-15`,
                    date_from: `2026-${month}-01`, date_to: `2026-${month === "11" ? "30" : "31"}`,
                    display_label: month === "11" ? "November 2026" : "October 2026" };
            }
            if (method === "get_report") {
                return {
                    company: { id: 1, name: "Baseer", currency_code: "SAR" },
                    period: { date_from: args[0].date_from, date_to: args[0].date_to,
                        fiscal_start: "2026-01-01" },
                    is_partial_journals: args[0].journal_ids.length > 0,
                    page: 1, page_size: 100, page_count: 1, account_count: 1,
                    accounts: [{ id: 7, code: "101000", name: "Bank", opening_debit: "100.00",
                        opening_credit: "0.00", debit: "20.00", credit: "10.00",
                        closing_debit: "110.00", closing_credit: "0.00",
                        period_line_count: 2, opening_source_count: 1 }],
                    rbf: { opening_debit: "0.00", opening_credit: "0.00",
                        closing_debit: "0.00", closing_credit: "0.00", source_line_count: 0 },
                    total: { opening_debit: "100.00", opening_credit: "100.00",
                        debit: "20.00", credit: "20.00",
                        closing_debit: "110.00", closing_credit: "110.00" },
                };
            }
            if (method === "action_print") {
                return { type: "ir.actions.report",
                    report_name: "baseer_trial_balance_report.trial_balance_pdf" };
            }
            if (method === "get_account_action") {
                return { type: "ir.actions.act_window", res_model: "account.move.line",
                    target: "current", domain: [["account_id", "=", 7]] };
            }
            throw new Error(`Unexpected ${method}`);
        },
    };
}

async function mount(calls, actions, dialogs = []) {
    patchWithCleanup(user, { activeCompany: { id: 1 } });
    const response = await withFetch(globals.fetch, () =>
        fetch("/baseer_trial_balance_report/static/src/trial_balance.xml")
    );
    expect(response.ok).toBe(true);
    const shared = await withFetch(globals.fetch, () => fetch("/baseer_reports_menu/static/src/report_export.xml"));
    expect(shared.ok).toBe(true);
    const templates = "<templates>" + [await response.text(), await shared.text()].map((text) =>
        text.replace(/<\?xml[^>]*>/, "").replace(/<templates[^>]*>/, "").replace("</templates>", "")).join("") + "</templates>";
    const app = new App(BaseerTrialBalanceReport, {
        env: { services: { orm: mockOrm(calls),
            action: { doAction: async (action) => actions.push(action) }, notification: { add() {} }, dialog: { add(_component, props) { dialogs.push(props); } } } },
        templates, props: {}, test: true,
    });
    after(() => app.destroy());
    await app.mount(getFixture());
    await waitUntil(() => document.querySelector(".o_baseer_tb_table .o_baseer_gl_account"));
}

test("trial balance is an accounting-only report with six amount columns", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const descriptor = registry.category("baseer_reports").get("trial_balance");
    expect(descriptor.component).toBe(BaseerTrialBalanceReport);
    expect(descriptor.groups).toEqual([
        "account.group_account_readonly", "account.group_account_user", "account.group_account_manager",
    ]);
    await mount([], []);
    expect(document.querySelectorAll(".o_baseer_tb_table thead tr:last-child th").length).toBe(6);
    expect(document.querySelector(".o_baseer_gl_account").textContent.includes("110.00")).toBe(true);
    expect(document.querySelector('select[aria-label="Company"]')).toBe(null);
    expect(document.querySelector(".o_baseer_tb_report").getAttribute("dir")).toBe("ltr");
});

test("period and journals change server filters", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const calls = [];
    await mount(calls, []);
    expect(document.querySelector(".o_baseer_report_period").textContent.includes("October 2026")).toBe(true);
    await click('button[aria-label="Next Period"]');
    await waitUntil(() => document.querySelector(".o_baseer_report_period").textContent.includes("November 2026"));
    expect(calls.find(([method]) => method === "resolve_period")[1][0].direction).toBe(1);
    await click(".o_baseer_gl_journals summary");
    await click('.o_baseer_gl_journal_list input[value="11"]');
    await waitUntil(() => calls.at(-1)[0] === "get_report" && calls.at(-1)[1][0].journal_ids.length === 1);
    expect(calls.at(-1)[1][0].journal_ids).toEqual([11]);
});

test("account drill-down opens native journal items and PDF uses applied filters", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const requests = [];
    patchWithCleanup(download, { _download: async (request) => requests.push(request) });
    const calls = [], actions = [];
    await mount(calls, actions);
    await click('.o_baseer_gl_account button[aria-label="View entries 101000 Bank"]');
    await waitUntil(() => actions.length === 1);
    expect(actions[0].res_model).toBe("account.move.line");
    expect(actions[0].target).toBe("current");
    await click(".o_baseer_report_exports .o_baseer_pl_pdf");
    await waitUntil(() => requests.length === 1);
    expect(requests[0].data.report_key).toBe("trial_balance");
    expect(requests[0].data.file_format).toBe("pdf");
    expect(JSON.parse(requests[0].data.filters).date_from).toBe("2026-10-01");
    expect(actions.length).toBe(1);
});

test("Arabic layout is RTL while numbers stay western", async () => {
    patchWithCleanup(user, { lang: "ar_001" });
    await mount([], []);
    expect(document.querySelector(".o_baseer_tb_report").getAttribute("dir")).toBe("rtl");
    expect(document.querySelector(".o_baseer_report_title").textContent).toBe("ميزان المراجعة");
    expect(document.querySelector(".o_baseer_gl_account").textContent.includes("110.00")).toBe(true);
});


test("trial_balance every visible amount opens a scoped shared drill including zero", async () => {
    patchWithCleanup(user, { lang: "en_US" });
    const dialogs = [];
    await mount([], [], dialogs);
    const buttons = [...document.querySelectorAll(".o_baseer_amount_link")];
    expect(buttons.length).toBe(12);
    expect(buttons.some((button) => button.textContent.trim() === "0.00")).toBe(true);
    for (const button of buttons) {
        expect(button.tagName).toBe("BUTTON");
        expect(button.disabled).toBe(false);
        await click(button);
    }
    expect(dialogs.length).toBe(12);
    for (const props of dialogs) {
        expect(props.reportKey).toBe("trial_balance");
        expect(props.filters).toEqual({ company_id: 1, date_from: "2026-10-01", date_to: "2026-10-31", journal_ids: [] });
        expect(Object.hasOwn(props.selector, "amount")).toBe(false);
        expect(Object.hasOwn(props.selector, "domain")).toBe(false);
    }
    patchWithCleanup(user, { activeCompany: { id: 2 } });
    await click(buttons[0]);
    expect(dialogs.length).toBe(12);
});

/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";
import { AccountActivity } from "@baseer_account_activity/account_activity";

test("account activity registers only its real report component", () => {
    const descriptor = registry.category("baseer_reports").get("activity");
    expect(descriptor.kind).toBe("component");
    expect(descriptor.component).toBe(AccountActivity);
    expect(descriptor.label.ar).toBe("حركة حساب");
});

test("the legacy direct action returns to the unified report page", () => {
    const actions = [];
    const context = { action: { doAction: (id) => actions.push(id) } };
    AccountActivity.prototype.goToReports.call(context);
    expect(actions).toEqual(["baseer_reports_menu.action_baseer_reports_hub"]);
});

test("account activity labels a full applied month, but not a partial date range", () => {
    const report = { lang: "en", state: { appliedPeriod: {
        kind: "month", dateFrom: "2026-10-01", dateTo: "2026-10-31",
    } } };
    const caption = Object.getOwnPropertyDescriptor(AccountActivity.prototype, "periodCaption").get;
    expect(caption.call(report)).toBe("October 2026");
    report.state.appliedPeriod.dateTo = "2026-10-15";
    expect(caption.call(report)).toBe("2026-10-01 — 2026-10-15");
});

test("account activity A-to-B-to-A ignores late account lists", async () => {
    let active = 1;
    const pending = [];
    const report = Object.create(AccountActivity.prototype);
    Object.defineProperty(report, "activeCompanyId", { get: () => active });
    Object.assign(report, {
        companyGeneration: 0, accountEpoch: 0, requestEpoch: 0, lang: "en",
        state: { accounts: [], accountId: 0, companyId: 0, accountsLoading: false,
            data: null, loading: false, error: "", cursors: [null], page: 0, appliedPeriod: null },
        orm: { searchRead: () => new Promise((resolve) => pending.push(resolve)) },
    });
    const firstA = report.loadOptions();
    active = 2;
    const B = report.loadOptions();
    active = 1;
    const secondA = report.loadOptions();
    pending[2]([{ id: 30, display_name: "Latest A" }]);
    await secondA;
    pending[0]([{ id: 10, display_name: "Old A" }]);
    pending[1]([{ id: 20, display_name: "Old B" }]);
    await Promise.all([firstA, B]);
    expect(report.state.companyId).toBe(1);
    expect(report.state.accounts).toEqual([{ id: 30, display_name: "Latest A" }]);
    expect(report.state.accountId).toBe(30);
});

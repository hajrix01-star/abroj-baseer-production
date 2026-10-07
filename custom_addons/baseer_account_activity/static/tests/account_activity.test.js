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

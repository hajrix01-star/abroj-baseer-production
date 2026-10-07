/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { AccountActivity } from "@baseer_account_activity/account_activity";

test("report switcher includes visible real menus but not the sample preview", () => {
    const activity = { id: 1, xmlid: "baseer_account_activity.menu_account_activity", name: "Account Activity", actionID: 939 };
    const tax = { id: 2, xmlid: "baseer_tax_report.menu_tax_report", name: "VAT", actionID: 936 };
    const preview = { id: 3, xmlid: "baseer_report_ui_preview.menu_report_ui_preview", name: "Sample", actionID: 938 };
    const tobacco = { id: 4, xmlid: "baseer_pos_tobacco_report.menu_pos_tobacco_report", name: "Tobacco", actionID: 933 };
    const group = { id: 5, name: "Group", childrenTree: [tobacco] };
    const root = { id: 6, xmlid: "baseer_reports_menu.menu_baseer_reports", childrenTree: [activity, tax, preview, group] };
    const context = { menu: { getApps: () => [root], getMenuAsTree: () => root } };
    const options = Object.getOwnPropertyDescriptor(AccountActivity.prototype, "reportOptions").get.call(context);
    expect(options.map((item) => item.id)).toEqual([1, 2, 4]);
});

test("report switcher delegates navigation to Odoo's access-filtered menu service", () => {
    const selected = [];
    const context = { menu: { selectMenu: (item) => selected.push(item.id) } };
    AccountActivity.prototype.openReport.call(context, { id: 1, xmlid: "baseer_account_activity.menu_account_activity" });
    AccountActivity.prototype.openReport.call(context, { id: 2, xmlid: "baseer_tax_report.menu_tax_report" });
    expect(selected).toEqual([2]);
});

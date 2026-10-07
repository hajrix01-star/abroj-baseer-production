/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("baseer_reports").add("tobacco", {
    key: "tobacco",
    label: { ar: "كشف رسوم التبغ من نقاط البيع", en: "POS Tobacco Fee Register" },
    sequence: 20,
    kind: "form",
    actionXmlId: "baseer_pos_tobacco_report.action_pos_tobacco_report_wizard",
    groups: [
        "account.group_account_readonly",
        "account.group_account_invoice",
        "account.group_account_user",
        "account.group_account_manager",
    ],
});

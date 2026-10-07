/** @odoo-module **/

import { registry } from "@web/core/registry";
import { BaseerTobaccoReport } from "./tobacco_report";

registry.category("baseer_reports").add("tobacco", {
    key: "tobacco",
    label: { ar: "كشف رسوم التبغ من نقاط البيع", en: "POS Tobacco Fee Register" },
    sequence: 20,
    kind: "component",
    component: BaseerTobaccoReport,
    groups: [
        "account.group_account_readonly",
        "account.group_account_invoice",
        "account.group_account_user",
        "account.group_account_manager",
    ],
    requiredGroups: ["point_of_sale.group_pos_user", "point_of_sale.group_pos_manager"],
});

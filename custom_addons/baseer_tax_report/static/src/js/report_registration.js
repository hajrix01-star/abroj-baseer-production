/** @odoo-module **/

import { registry } from "@web/core/registry";
import { SaudiVatReport } from "./saudi_vat_report";

registry.category("baseer_reports").add("vat", {
    key: "vat",
    label: { ar: "تقرير ضريبة القيمة المضافة", en: "Saudi VAT Report" },
    sequence: 10,
    kind: "component",
    component: SaudiVatReport,
    groups: [
        "account.group_account_readonly",
        "account.group_account_user",
        "account.group_account_manager",
    ],
});

/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("baseer_reports").add("vat", {
    key: "vat",
    label: { ar: "تقرير ضريبة القيمة المضافة", en: "Saudi VAT Report" },
    sequence: 10,
    kind: "form",
    actionXmlId: "baseer_tax_report.action_tax_report_wizard",
    groups: [
        "account.group_account_readonly",
        "account.group_account_user",
        "account.group_account_manager",
    ],
});

/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { allowedReports } from "@baseer_reports_menu/report_hub";
import { ReportSelector } from "@baseer_reports_menu/report_selector";

class ReportComponent {}

test("the shared selector uses the permitted report title in the current language", () => {
    const context = {
        props: { options: [{ key: "vat", label: { ar: "ضريبة القيمة المضافة", en: "VAT" } }],
            selectedKey: "vat", label: "اختر تقريرًا", lang: "ar" },
        reportName: ReportSelector.prototype.reportName,
    };
    expect(ReportSelector.prototype.selectedName.call(context)).toBe("ضريبة القيمة المضافة");
    context.props.selectedKey = "missing";
    expect(ReportSelector.prototype.selectedName.call(context)).toBe("اختر تقريرًا");
});

test("the shared selector forwards the selected report key to the hub", () => {
    const selected = [];
    ReportSelector.prototype.selectReport.call({ props: { onSelect: (key) => selected.push(key) } }, "tobacco");
    expect(selected).toEqual(["tobacco"]);
});

test("the report selector shows only allowed real registrations in a stable order", async () => {
    const reports = [
        { key: "tobacco", sequence: 20, kind: "component", component: ReportComponent,
            groups: ["invoice"], requiredGroups: ["pos"] },
        { key: "activity", sequence: 30, kind: "component", component: ReportComponent,
            groups: ["accounting"] },
        { key: "vat", sequence: 10, kind: "component", component: ReportComponent,
            groups: ["accounting"] },
    ];
    const result = await allowedReports(reports, async (group) => group === "accounting");
    expect(result.map((report) => report.key)).toEqual(["vat", "activity"]);
});

test("POS reporting requires both an accounting and a POS group", async () => {
    const report = [{ key: "tobacco", sequence: 20, kind: "component",
        component: ReportComponent, groups: ["accounting", "invoice"],
        requiredGroups: ["pos_user", "pos_manager"] }];
    const invoiceOnly = await allowedReports(report, async (group) => group === "invoice");
    expect(invoiceOnly).toEqual([]);
    const invoiceAndPos = await allowedReports(report,
        async (group) => ["invoice", "pos_user"].includes(group));
    expect(invoiceAndPos.map((item) => item.key)).toEqual(["tobacco"]);
});

test("legacy wizard forms are never mounted as report pages", async () => {
    const reports = [{ key: "vat", sequence: 10, kind: "form", actionXmlId: "legacy",
        groups: ["accounting"] }];
    expect(await allowedReports(reports, async () => true)).toEqual([]);
});

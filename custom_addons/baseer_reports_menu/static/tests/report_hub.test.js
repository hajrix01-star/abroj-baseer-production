/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { allowedReports, formViewProps } from "@baseer_reports_menu/report_hub";

test("the report selector shows only allowed real registrations in a stable order", async () => {
    const reports = [
        { key: "tobacco", sequence: 20, groups: ["invoice"] },
        { key: "activity", sequence: 30, groups: ["accounting"] },
        { key: "vat", sequence: 10, groups: ["accounting"] },
    ];
    const result = await allowedReports(reports, async (group) => group === "accounting");
    expect(result.map((report) => report.key)).toEqual(["vat", "activity"]);
});

test("native form view receives the source action's model, view and context", () => {
    const props = formViewProps({
        type: "ir.actions.act_window", res_model: "baseer.tax.report.wizard",
        views: [[47, "form"]], context: { default_period_type: "quarter" },
    });
    expect(props.resModel).toBe("baseer.tax.report.wizard");
    expect(props.viewId).toBe(47);
    expect(props.resId).toBe(false);
    expect(props.context.default_period_type).toBe("quarter");
    expect(props.display.controlPanel).toBe(false);
});

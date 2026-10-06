/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { filterItems, flattenRows, ReportDesignPreview, SAMPLE_ITEMS, SAMPLE_REPORTS } from "@baseer_report_ui_preview/report_preview";

test.tags("desktop");

test("sample rows are collapsed until explicitly opened", () => {
    const rows = SAMPLE_REPORTS.profit.rows;
    expect(flattenRows(rows, {}).length).toBe(4);
    expect(flattenRows(rows, { expenses: true }).length).toBe(6);
    expect(flattenRows(rows, { expenses: true })[4].depth).toBe(1);
});

test("only negative sample amounts use the red tone and carry a minus sign", () => {
    for (const report of Object.values(SAMPLE_REPORTS)) {
        const visit = (rows) => {
            for (const row of rows) {
                for (const amount of row.amounts) {
                    if (amount.tone === "negative") {
                        expect(amount.text.startsWith("−")).toBe(true);
                    }
                }
                visit(row.children);
            }
        };
        visit(report.rows);
    }
    expect(SAMPLE_REPORTS.ledger.rows[0].amounts[1].tone).toBe("normal");
    expect(SAMPLE_ITEMS[5].credit.tone).toBe("outflow");
    expect(SAMPLE_ITEMS[4].credit.tone).toBe("normal");
});

test("preview switching resets the expanded rows and never opens a real action", () => {
    const context = { state: { report: "profit", expanded: { income: true }, screen: "items", query: "old", page: 1 } };
    ReportDesignPreview.prototype.selectReport.call(context, "tax");
    expect(context.state.report).toBe("tax");
    expect(Object.keys(context.state.expanded).length).toBe(0);
    expect(context.state.screen).toBe("report");
    ReportDesignPreview.prototype.openItems.call(context);
    expect(context.state.screen).toBe("items");
    expect(context.state.query).toBe("");
    ReportDesignPreview.prototype.back.call(context);
    expect(context.state.screen).toBe("report");
});

test("journal item search uses only synthetic local fixtures", () => {
    expect(filterItems(SAMPLE_ITEMS, "DEMO/003", "en").length).toBe(1);
    expect(filterItems(SAMPLE_ITEMS, "الصندوق", "ar").length).toBe(2);
    expect(filterItems(SAMPLE_ITEMS, "missing", "en").length).toBe(0);
});

/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { BaseerFinancialDashboard } from "@baseer_financial_dashboard/financial_dashboard";
import { SalesPaymentsDashboard } from "@baseer_financial_dashboard/financial_sales_payments";

function component(language = "en") {
    const instance = Object.create(BaseerFinancialDashboard.prototype);
    instance.lang = language;
    instance.state = { active: "profit_loss" };
    instance.props = { dashboardId: 42 };
    return instance;
}

test("financial dashboard tabs keep roving focus after a real event is released", async () => {
    const dashboard = component("ar");
    let focused = null;
    const tablist = { querySelector: (selector) => ({ focus: () => { focused = selector; } }) };
    const event = {
        key: "ArrowRight",
        currentTarget: { parentElement: tablist },
        preventDefault: () => {},
    };

    dashboard.onTabKeydown(event);
    // Browsers clear Event.currentTarget after dispatch; the dashboard must
    // have already captured the tablist before its deferred focus operation.
    event.currentTarget = null;
    await Promise.resolve();

    expect(dashboard.state.active).toBe("sales_payments");
    expect(focused).toBe('[data-financial-tab="sales_payments"]');
});

test("financial dashboard keyboard home and end select the expected tab", async () => {
    const dashboard = component();
    const focused = [];
    const eventFor = (key) => ({
        key,
        currentTarget: { parentElement: { querySelector: (selector) => ({ focus: () => focused.push(selector) }) } },
        preventDefault: () => {},
    });

    dashboard.onTabKeydown(eventFor("End"));
    await Promise.resolve();
    expect(dashboard.state.active).toBe("sales_payments");
    dashboard.onTabKeydown(eventFor("Home"));
    await Promise.resolve();
    expect(dashboard.state.active).toBe("profit_loss");
    expect(focused).toEqual([
        '[data-financial-tab="sales_payments"]',
        '[data-financial-tab="profit_loss"]',
    ]);
});

test("sales dashboard cards preserve the server-owned amounts without calculation", () => {
    const sales = { key: "total:incoming_total", label: "Sales", amounts: { current: { amount: "100.00", negative: false }, previous: { amount: "75.00", negative: false } }, children: [] };
    const payments = { key: "total:cash_total", label: "Payments", amounts: { current: { amount: "40.00", negative: false } }, children: [{ key: "current-row", amounts: { current: { amount: "40.00", negative: false } } }, { key: "comparison-only", amounts: { previous: { amount: "10.00", negative: false } } }] };
    const difference = { key: "total:difference", label: "Difference", amounts: { current: { amount: "60.00", negative: false } } };
    const dashboard = Object.create(SalesPaymentsDashboard.prototype);
    dashboard.lang = "en";
    dashboard.state = { report: { complete: true, periods: [{ key: "current", label: "November", display_label: "November" }, { key: "previous", label: "October", display_label: "October" }] } };
    Object.defineProperty(dashboard, "ownerTable", { value: { sections: [sales, payments], difference } });
    dashboard.ownerValue = (row, key) => row.amounts[key];

    const view = dashboard.salesDashboard;
    expect(view.cards.map((card) => card.value.amount)).toEqual(["100.00", "40.00", "60.00"]);
    expect(view.cards.map((card) => card.row.key)).toEqual([sales.key, payments.key, difference.key]);
    expect(view.cards[0].comparisons.map((comparison) => comparison.value.amount)).toEqual(["75.00"]);
    expect(view.paymentRows.map((row) => row.key)).toEqual(["current-row"]);
    dashboard.state.report.complete = false;
    expect(dashboard.salesDashboard).toBe(null);
});

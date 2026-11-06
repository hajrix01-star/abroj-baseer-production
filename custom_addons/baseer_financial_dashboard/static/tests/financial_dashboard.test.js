/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { BaseerFinancialDashboard } from "@baseer_financial_dashboard/financial_dashboard";

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

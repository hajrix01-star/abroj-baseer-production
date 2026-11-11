/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { user } from "@web/core/user";
import { IsolatedFinancialProfitLoss } from "./isolated_profit_loss";
import { SalesPaymentsDashboard } from "./financial_sales_payments";

const TABS = Object.freeze([
    { key: "profit_loss", ar: "الأداء المالي — الربح والخسارة", en: "Financial performance — Profit and Loss", component: IsolatedFinancialProfitLoss },
    { key: "sales_payments", ar: "ملخص المبيعات والمدفوعات", en: "Sales and Payments Summary", component: SalesPaymentsDashboard },
]);

export class BaseerFinancialDashboard extends Component {
    static template = "baseer_financial_dashboard.Dashboard";
    static props = { dashboardId: Number };

    setup() {
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({ active: "profit_loss" });
    }

    get tabs() { return TABS; }
    get activeTab() { return TABS.find((tab) => tab.key === this.state.active) || TABS[0]; }
    get activeComponent() { return this.activeTab.component; }
    label(tab) { return tab[this.lang]; }
    tabId(tab) { return `baseer_financial_dashboard_${this.props.dashboardId}_${tab.key}`; }
    panelId(tab) { return `${this.tabId(tab)}_panel`; }

    select(key) {
        if (TABS.some((tab) => tab.key === key)) { this.state.active = key; }
    }

    onTabKeydown(event) {
        const index = TABS.findIndex((tab) => tab.key === this.state.active);
        const rtl = this.lang === "ar";
        let next = null;
        if (event.key === "Home") { next = 0; }
        if (event.key === "End") { next = TABS.length - 1; }
        if (event.key === "ArrowRight") { next = (index + (rtl ? -1 : 1) + TABS.length) % TABS.length; }
        if (event.key === "ArrowLeft") { next = (index + (rtl ? 1 : -1) + TABS.length) % TABS.length; }
        if (next === null) { return; }
        event.preventDefault();
        // DOM events clear currentTarget after dispatch.  Preserve the tablist
        // before Owl re-renders the active panel, then restore roving focus.
        const tablist = event.currentTarget.parentElement;
        this.select(TABS[next].key);
        queueMicrotask(() => tablist?.querySelector(`[data-financial-tab="${TABS[next].key}"]`)?.focus());
    }
}

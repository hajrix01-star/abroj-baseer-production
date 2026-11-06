/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SpreadsheetDashboardAction } from "@spreadsheet_dashboard/bundle/dashboard_action/dashboard_action";
import { BaseerFinancialDashboard } from "./financial_dashboard";

patch(SpreadsheetDashboardAction, {
    components: { ...SpreadsheetDashboardAction.components, BaseerFinancialDashboard },
});

patch(SpreadsheetDashboardAction.prototype, {
    get isBaseerFinancialDashboard() {
        return this.loader.getActiveDashboard()?.data.baseer_dashboard_kind === "financial_dashboard";
    },
});

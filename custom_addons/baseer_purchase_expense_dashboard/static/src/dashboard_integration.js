import { patch } from "@web/core/utils/patch";
import { SpreadsheetDashboardAction } from "@spreadsheet_dashboard/bundle/dashboard_action/dashboard_action";
import { BaseerPurchaseExpenseDashboard } from "./purchase_expense_dashboard";

patch(SpreadsheetDashboardAction, {
    components: { ...SpreadsheetDashboardAction.components, BaseerPurchaseExpenseDashboard },
});

patch(SpreadsheetDashboardAction.prototype, {
    get isBaseerPurchasesDashboard() {
        return this.loader.getActiveDashboard()?.data.baseer_dashboard_kind === "supplier_bills";
    },
});

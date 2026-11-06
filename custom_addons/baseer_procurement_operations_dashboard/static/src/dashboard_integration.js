import { patch } from "@web/core/utils/patch";
import { SpreadsheetDashboardAction } from "@spreadsheet_dashboard/bundle/dashboard_action/dashboard_action";
import { BaseerProcurementOperationsDashboard } from "./procurement_dashboard";


patch(SpreadsheetDashboardAction, {
    components: { ...SpreadsheetDashboardAction.components, BaseerProcurementOperationsDashboard },
});

patch(SpreadsheetDashboardAction.prototype, {
    get isBaseerProcurementOperationsDashboard() {
        return this.loader.getActiveDashboard()?.data.baseer_dashboard_kind === "procurement_operations";
    },
});

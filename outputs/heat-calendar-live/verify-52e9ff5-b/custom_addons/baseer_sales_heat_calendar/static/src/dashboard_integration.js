import { patch } from "@web/core/utils/patch";
import { SpreadsheetDashboardAction } from "@spreadsheet_dashboard/bundle/dashboard_action/dashboard_action";
import { BaseerHeatCalendar } from "./heat_calendar";

patch(SpreadsheetDashboardAction, {
    components: { ...SpreadsheetDashboardAction.components, BaseerHeatCalendar },
});

patch(SpreadsheetDashboardAction.prototype, {
    get isBaseerHeatCalendar() {
        return this.loader.getActiveDashboard()?.data.baseer_dashboard_kind === "sales_heat_calendar";
    },
});

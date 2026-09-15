import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

export class BaseerPurchaseExpenseDashboard extends Component {
    static template = "baseer_purchase_expense_dashboard.PurchaseExpenseDashboard";
    static props = { dashboardId: Number, dateFilter: { type: [Object, { value: null }], optional: true } };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ payload: null, loading: true, error: "" });
        this.generation = 0;
        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (nextProps.dashboardId !== this.props.dashboardId || nextProps.dateFilter !== this.props.dateFilter) {
                this.load(nextProps);
            }
        });
    }

    get labels() {
        return {
            title: _t("Supplier bills and expenses"),
            subtitle: _t("Posted supplier bills and refunds in the active company"),
            count: _t("Documents"), total: _t("Net purchases and expenses"),
            residual: _t("Unpaid balance"), paid: _t("Paid"),
            timeline: _t("Monthly movement"), vendors: _t("Top suppliers"),
            amount: _t("Amount"), refresh: _t("Refresh"), source: _t("View source bills"),
            loading: _t("Loading supplier bills…"), retry: _t("Try again"),
            empty: _t("No posted supplier bills or refunds in this period."),
            currencyNotice: _t("supplier bills in a foreign currency are excluded because this view does not mix currencies."),
            period: _t("Period"),
        };
    }

    get hasData() { return (this.state.payload?.cards?.count?.value || 0) > 0; }
    get period() {
        const value = this.state.payload?.filters;
        return value ? `${value.date_from} — ${value.date_to}` : "";
    }
    barHeight(row) { return `${row.height_percent}%`; }

    async load(props = this.props) {
        const generation = ++this.generation;
        this.state.loading = true;
        this.state.error = "";
        try {
            const payload = await this.orm.call("spreadsheet.dashboard", "get_baseer_supplier_bill_metrics", [
                [props.dashboardId], { native: props.dateFilter ?? null },
            ]);
            if (generation === this.generation) { this.state.payload = payload; }
        } catch (error) {
            if (generation === this.generation) {
                const businessError = ["odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError"].includes(error?.data?.name);
                this.state.error = (businessError && error.data.message) || _t("The dashboard could not be loaded. Please try again.");
            }
        } finally {
            if (generation === this.generation) { this.state.loading = false; }
        }
    }

    openSources() {
        if (this.state.payload?.source_action) { return this.action.doAction(this.state.payload.source_action); }
    }
}

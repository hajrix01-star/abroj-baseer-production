import { Component, onWillStart, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";


export class BaseerProcurementOperationsDashboard extends Component {
    static template = "baseer_procurement_operations_dashboard.ProcurementOperationsDashboard";
    static props = { dashboardId: Number, dateFilter: { type: [Object, { value: null }], optional: true } };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ payload: null, loading: true, error: "" });
        this.generation = 0;
        this.disposed = false;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.load());
        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (nextProps.dashboardId !== this.props.dashboardId || nextProps.dateFilter !== this.props.dateFilter) {
                this.load(nextProps);
            }
        });
        onWillUnmount(() => {
            this.disposed = true;
            this.generation++;
        });
    }

    get labels() {
        return {
            title: _t("Procurement operations"),
            subtitle: _t("Request workflow only; supplier bills, payments, and expenses remain in Finance."),
            requests: _t("Requests created in period"),
            draft: _t("Draft"), sent: _t("Sent for purchase"),
            received: _t("Cashier receipt confirmed"), purchased: _t("Quantity receipt completed"),
            completion: _t("Completed in the selected period"),
            completionNote: _t("Completion is recorded when quantity receipt is confirmed; it does not mean a supplier bill or payment was posted."),
            dailyStates: _t("Request states by creation date"),
            dailyStatesNote: _t("Current state of requests created on each date"),
            actionQueue: _t("Pending action queue"),
            actionQueueNote: _t("Oldest pending requests created in the selected period"),
            route: _t("Purchase route"), warehouse: _t("Warehouse"),
            breakdown: _t("Operational breakdown"), date: _t("Date"), state: _t("State"),
            request: _t("Request"), noWarehouse: _t("No warehouse"),
            source: _t("View requests"), refresh: _t("Refresh"), loading: _t("Loading procurement operations…"),
            retry: _t("Try again"), empty: _t("No procurement requests were created in this period."),
            noCompleted: _t("No quantity receipts were completed in this period."),
            noPending: _t("No pending requests in this period."),
            count: _t("Count"),
        };
    }

    get period() {
        const filters = this.state.payload?.filters;
        return filters ? `${filters.date_from} — ${filters.date_to}` : "";
    }
    get cards() {
        const cards = this.state.payload?.cards || {};
        return [
            { key: "total", title: this.labels.requests, icon: "fa-list-alt", tone: "neutral" },
            { key: "draft", title: this.labels.draft, icon: "fa-pencil", tone: "muted" },
            { key: "sent", title: this.labels.sent, icon: "fa-paper-plane", tone: "info" },
            { key: "received", title: this.labels.received, icon: "fa-inbox", tone: "warning" },
            { key: "purchased", title: this.labels.purchased, icon: "fa-check-circle", tone: "success" },
        ].map((spec) => ({ ...spec, display: cards[spec.key]?.display || "0" }));
    }
    get queue() { return this.state.payload?.pending_queue || []; }
    get completionRows() { return (this.state.payload?.completion_timeline || []).slice(-10).reverse(); }
    get cohortRows() { return (this.state.payload?.cohort_timeline || []).slice(-10).reverse(); }
    get dimensions() { return this.state.payload?.dimensions || { routes: [], warehouses: [] }; }

    async load(props = this.props) {
        const generation = ++this.generation;
        this.state.loading = true;
        this.state.error = "";
        try {
            const payload = await this.orm.call("spreadsheet.dashboard", "get_baseer_procurement_operations_metrics", [
                [props.dashboardId], { native: props.dateFilter ?? null },
            ]);
            if (!this.disposed && generation === this.generation) {
                this.state.payload = payload;
            }
        } catch (error) {
            if (!this.disposed && generation === this.generation) {
                const expected = ["odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError"].includes(error?.data?.name);
                this.state.error = (expected && error.data.message) || _t("The dashboard could not be loaded. Please try again.");
            }
        } finally {
            if (!this.disposed && generation === this.generation) {
                this.state.loading = false;
            }
        }
    }

    openSource() {
        if (this.state.payload?.source_action) {
            return this.action.doAction(this.state.payload.source_action);
        }
    }

    openRequest(row) {
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: "baseer.procurement.request", res_id: row.id,
            view_mode: "form", views: [[false, "form"]],
            context: { create: false, allowed_company_ids: [this.state.payload.company.id] },
        });
    }
}

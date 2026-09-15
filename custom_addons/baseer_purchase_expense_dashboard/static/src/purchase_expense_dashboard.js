import { Component, onWillStart, onWillUnmount, onWillUpdateProps, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { useService } from "@web/core/utils/hooks";

const coordinate = (value) => value === null || value === undefined ? null : Number(value);

export class BaseerPurchaseExpenseDashboard extends Component {
    static template = "baseer_purchase_expense_dashboard.PurchaseExpenseDashboard";
    static props = { dashboardId: Number, dateFilter: { type: [Object, { value: null }], optional: true } };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ payload: null, loading: true, error: "" });
        this.rootRef = useRef("dashboard");
        this.movementRef = useRef("movementChart");
        this.generation = 0;
        this.chart = null;
        this.disposed = false;
        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (nextProps.dashboardId !== this.props.dashboardId || nextProps.dateFilter !== this.props.dateFilter) {
                this.load(nextProps);
            }
        });
        useEffect(() => {
            this.drawMovementChart();
            return () => this.destroyChart();
        }, () => [this.state.payload]);
        onWillUnmount(() => {
            this.disposed = true;
            this.generation++;
            this.destroyChart();
        });
    }

    get labels() {
        return {
            title: _t("Supplier bills and expenses"),
            subtitle: _t("Posted supplier bills and refunds in the active company"),
            count: _t("Documents"), total: _t("Total purchases and expenses (tax included)"),
            residual: _t("Unpaid balance"), paid: _t("Paid"),
            timeline: _t("Monthly movement"), timelineNote: _t("Tax-included posted purchase totals and paid amounts"),
            timelineAccessible: _t("Monthly tax-included purchases and paid amounts"),
            vendors: _t("Top suppliers"), vendor: _t("Supplier"), categories: _t("Purchase categories"), category: _t("Category"),
            netAmount: _t("Net amount before tax"), salesRatio: _t("Share of net approved sales before tax"),
            ratioBasis: _t("Net supplier cost before tax ÷ net approved sales before tax"),
            categoryNote: _t("Native product categories; tax and display lines are excluded"),
            ratioUnavailable: _t("No approved net sales were recorded for this period, so purchase-to-sales percentages are unavailable."),
            noVendors: _t("No suppliers in the selected period."), noCategories: _t("No categorized product lines in the selected period."),
            month: _t("Month"), refresh: _t("Refresh"), source: _t("View source bills"),
            loading: _t("Loading supplier bills…"), retry: _t("Try again"),
            empty: _t("No posted supplier bills or refunds in this period."),
            currencyNotice: _t("supplier bills in a foreign currency are excluded because this view does not mix currencies."),
        };
    }

    get hasData() { return (this.state.payload?.cards?.count?.value || 0) > 0; }
    get canRenderChart() { return Boolean(globalThis.Chart); }
    get period() {
        const value = this.state.payload?.filters;
        return value ? `${value.date_from} — ${value.date_to}` : "";
    }

    async load(props = this.props) {
        const generation = ++this.generation;
        this.state.loading = true;
        this.state.error = "";
        try {
            const payload = await this.orm.call("spreadsheet.dashboard", "get_baseer_supplier_bill_metrics", [
                [props.dashboardId], { native: props.dateFilter ?? null },
            ]);
            if (!this.disposed && generation === this.generation) { this.state.payload = payload; }
        } catch (error) {
            if (!this.disposed && generation === this.generation) {
                const businessError = ["odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError"].includes(error?.data?.name);
                this.state.error = (businessError && error.data.message) || _t("The dashboard could not be loaded. Please try again.");
            }
        } finally {
            if (!this.disposed && generation === this.generation) { this.state.loading = false; }
        }
    }

    destroyChart() {
        this.chart?.destroy();
        this.chart = null;
    }

    drawMovementChart() {
        this.destroyChart();
        const ChartConstructor = globalThis.Chart;
        const rows = this.state.payload?.timeline || [];
        if (!ChartConstructor || !this.movementRef.el || !this.hasData || !rows.length || this.disposed) { return; }
        const rtl = localization.direction === "rtl";
        const font = getComputedStyle(this.rootRef.el).fontFamily;
        const currency = this.state.payload.company.currency;
        this.chart = new ChartConstructor(this.movementRef.el, {
            type: "bar",
            data: {
                labels: rows.map((row) => row.label),
                datasets: [{
                    type: "bar", label: this.labels.total, metric: "total", order: 2,
                    data: rows.map((row) => coordinate(row.total.value)),
                    borderColor: "#3385c4", backgroundColor: "#69afe5",
                    borderWidth: 0, borderRadius: 2, maxBarThickness: 42, spanGaps: false,
                }, {
                    type: "line", label: this.labels.paid, metric: "paid", order: 1,
                    data: rows.map((row) => coordinate(row.paid.value)),
                    borderColor: "#ba7428", backgroundColor: "#ba7428", borderWidth: 2,
                    pointRadius: 2, pointHoverRadius: 6, tension: 0, fill: false, spanGaps: false,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                font: { family: font }, interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { display: true, position: "top", rtl, textDirection: rtl ? "rtl" : "ltr", onClick: () => {}, labels: { boxWidth: 18, boxHeight: 8, padding: 18, font: { family: font, size: 12 } } },
                    tooltip: {
                        rtl, textDirection: rtl ? "rtl" : "ltr", titleFont: { family: font }, bodyFont: { family: font },
                        callbacks: { label: (context) => `${context.dataset.label}: ${rows[context.dataIndex][context.dataset.metric].display} ${currency}` },
                    },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 7, font: { family: font, size: 11 } } },
                    y: { beginAtZero: true, grid: { color: "rgba(128,128,128,0.12)" }, ticks: { callback: (value) => String(value), font: { family: font, size: 11 } } },
                },
            },
        });
    }

    openSources() {
        if (this.state.payload?.source_action) { return this.action.doAction(this.state.payload.source_action); }
    }
}

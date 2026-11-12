/** @odoo-module **/

import { BaseerOperationsPreview } from "@baseer_operations_report/operations";
import { ReportExportButtons } from "@baseer_reports_menu/report_export";
import { download } from "@web/core/network/download";
import { user } from "@web/core/user";

const DASHBOARD_MODEL = "baseer.financial.dashboard.operations";
const REPORT_MODEL = "baseer.operations.report";

// Scope the model substitution to this one component instance. The shared ORM
// service and the billing-report client action retain their original model.
export function dashboardOperationsOrm(orm, getRevisions = () => []) {
    return new Proxy(orm, {
        get(target, property) {
            if (property === "call") {
                return (model, method, args, ...rest) => target.call(
                    model === REPORT_MODEL ? DASHBOARD_MODEL : model,
                    method,
                    model === REPORT_MODEL && method === "action_print_owner" ? [...args, getRevisions()] : args,
                    ...rest,
                );
            }
            const value = Reflect.get(target, property, target);
            return typeof value === "function" ? value.bind(target) : value;
        },
    });
}

// The generic report-download route has a deliberately fixed provider map.
// This component uses the dashboard's own fixed route instead of changing it.
export class FinancialDashboardExportButtons extends ReportExportButtons {
    static props = { ...ReportExportButtons.props, revisions: Array };

    async exportFile(format) {
        if (this.disabled || !this.props.revisions.length || !["xlsx", "pdf"].includes(format)) { return; }
        const companyId = Number(user.activeCompany?.id) || 0;
        if (this.props.filters.company_id !== companyId) { return; }
        this.state.busy = true;
        try {
            await download({ url: "/baseer/financial-dashboard/export", data: {
                file_format: format, filters: JSON.stringify(this.props.filters),
                revisions: JSON.stringify(this.props.revisions),
            } });
        } catch {
            this.notification.add(this.labels.error, { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}

const labels = {
    ar: {
        sales: "المبيعات المسجلة",
        payments: "المدفوعات الفعلية",
        difference: "الفرق بين المبيعات والمدفوعات",
        salesCaption: "تشمل المبيعات غير المحصلة حسب المصدر المعتمد.",
        paymentsCaption: "مدفوعات مثبتة حسب تصنيف المصدر، وليست مصروفات محاسبية بالضرورة.",
        differenceCaption: "ليس صافي الربح المحاسبي ولا رصيد النقدية.",
        channels: "طرق دفع المبيعات",
        channelsCaption: "التوزيع المعتمد للمبيعات حسب طريقة الدفع.",
        outflows: "المدفوعات حسب الفئة",
        outflowsCaption: "تصنيف المدفوعات الفعلية كما يعيده المصدر.",
        noChannels: "لا توجد طرق دفع مثبتة لهذه الفترة.",
        noOutflows: "لا توجد مدفوعات مثبتة لهذه الفترة.",
        sourceBasis: "نطاق البيانات والتحقق",
    },
    en: {
        sales: "Recorded sales",
        payments: "Actual payments",
        difference: "Sales and payments difference",
        salesCaption: "Includes uncollected sales according to the approved source.",
        paymentsCaption: "Verified payments by source category; not necessarily accounting expenses.",
        differenceCaption: "Not accounting net profit or a cash balance.",
        channels: "Sales payment channels",
        channelsCaption: "Approved sales distribution by payment channel.",
        outflows: "Payments by category",
        outflowsCaption: "Actual-payment classification returned by the source.",
        noChannels: "No proven payment channels for this period.",
        noOutflows: "No proven payments for this period.",
        sourceBasis: "Data scope and verification",
    },
};

// This class owns no financial contract.  It retains the operations report's
// company guard, filters, snapshot revision, export and drilldown behavior;
// only the canvas template is replaced for the Financial dashboard.
export class SalesPaymentsDashboard extends BaseerOperationsPreview {
    static template = "baseer_financial_dashboard.SalesPayments";
    static components = { ...BaseerOperationsPreview.components, ReportExportButtons: FinancialDashboardExportButtons };

    setup() {
        super.setup();
        this.orm = dashboardOperationsOrm(this.orm, () =>
            (this.state.report?.periods || []).map(({ key, revision }) => ({ key, revision })));
    }

    get salesDashboardLabels() {
        return labels[this.lang];
    }

    get salesDashboard() {
        const period = this.state.report?.periods?.find((item) => item.key === "current") ||
            this.state.report?.periods?.[0];
        if (!period) {
            return null;
        }
        const [sales, payments] = this.ownerTable.sections;
        const difference = this.ownerTable.difference;
        const comparisonPeriods = this.state.report.periods.filter((item) => item.key !== period.key);
        const card = (key, row, icon, tone) => ({
            key,
            row,
            icon,
            tone,
            value: this.ownerValue(row, period.key),
            // Comparison values are displayed as returned.  This dashboard
            // deliberately does not calculate a delta or percentage client-side.
            comparisons: comparisonPeriods.map((item) => ({
                key: item.key,
                label: item.display_label || item.label,
                value: this.ownerValue(row, item.key),
            })).filter((item) => item.value),
        });
        return {
            period,
            sales,
            payments,
            difference,
            salesRows: sales.children.filter((row) => this.ownerValue(row, period.key)),
            paymentRows: payments.children.filter((row) => this.ownerValue(row, period.key)),
            cards: [
                card("sales", sales, "fa-line-chart", "is-income"),
                card("payments", payments, "fa-credit-card", "is-cost_of_sales"),
                card("difference", difference, "fa-balance-scale", "is-gross_margin"),
            ],
        };
    }

    cardLabel(card) {
        return this.salesDashboardLabels[card.key];
    }

    cardCaption(card) {
        return this.salesDashboardLabels[`${card.key}Caption`];
    }
}

/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { BaseerReportEngine } from "@baseer_report_engine/report_engine";

patch(BaseerReportEngine.prototype, {
    plainOptions(direction = 0) {
        return { ...super.plainOptions(direction), ...(this.reportCode === "saudi_vat" ? { tax_grouping: this.state.options.tax_grouping || "grid" } : {}) };
    },
    get periodLabel() {
        if (this.reportCode !== "saudi_vat") return super.periodLabel;
        const { date_from: start, date_to: end } = this.state.options;
        return start && end ? `${start} – ${end}` : this.state.labels.period;
    },
    get vatGroupingLabel() {
        return this.state.options.tax_grouping === "tax" ? _t("Group by: Tax") : _t("VAT return grid");
    },
    async setVatGrouping(value) {
        this.state.options.tax_grouping = value;
        await this.loadReport();
    },
});

/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { BaseerReportEngine } from "@baseer_report_engine/report_engine";

patch(BaseerReportEngine.prototype, {
    get isTobacco() { return this.reportCode === "tobacco_service_fee"; },
    get tobaccoLabels() { return { date: _t("Date and Time"), document: _t("Document"), product: _t("Product and Quantity"), type: _t("Type"), debit: _t("Debit"), credit: _t("Credit"), net: _t("Net"), cumulative: _t("Cumulative"), opening: _t("Cumulative at start"), total: _t("Total for period"), closing: _t("Cumulative at end"), reconciliation: _t("Reconciliation"), register: _t("Register net for period"), movement: _t("Fee account movement in the trial balance"), difference: _t("Difference"), sessions: _t("Open sessions"), manual: _t("Manual journal entries"), exceptions: _t("Order total mismatches"), computed: _t("Recomputed total"), saved: _t("Saved total"), show: _t("Show products") }; },
    plainOptions(direction = 0) { return { ...super.plainOptions(direction), ...(this.isTobacco ? {show_products: !!this.state.options.show_products} : {}) }; },
    async loadReport(direction = 0) {
        const show = this.state.options.show_products;
        await super.loadReport(direction);
        if (this.isTobacco) this.state.options.show_products = !!show;
    },
    tobaccoKey(section, day) { return `${section.company_id}-${section.account_id}-${day.date}`; },
    tobaccoMoney(value) { return this.formatAmount({value: value || 0, key: "net"}); },
    async tobaccoPage(section, day, offset = 0) {
        const key = this.tobaccoKey(section, day);
        const page = await this.orm.call("baseer.report.engine", "get_tobacco_day", [this.plainOptions(), section.company_id, section.account_id, day.date, offset]);
        this.state.accounts[key] = { ...page, rows: [...(offset ? this.state.accounts[key]?.rows || [] : []), ...page.items] };
    },
    async tobaccoToggle(section, day) {
        const key = this.tobaccoKey(section, day);
        this.state.folded[key] = !this.state.folded[key];
        if (this.state.folded[key] && !this.state.accounts[key]) await this.tobaccoPage(section, day);
    },
    async unfoldAll() {
        if (!this.isTobacco) return super.unfoldAll();
        this.state.options.unfold_all = true;
        for (const section of this.state.payload.tobacco_sections) for (const day of section.days) {
            const key = this.tobaccoKey(section, day);
            this.state.folded[key] = true;
            if (!this.state.accounts[key]) await this.tobaccoPage(section, day);
        }
    },
    foldAll() { if (!this.isTobacco) return super.foldAll(); this.state.options.unfold_all = false; this.state.folded = {}; },
    async tobaccoOpen(model, id) {
        const action = await this.orm.call("baseer.report.engine", "get_tobacco_source_action", [this.plainOptions(), model, id]);
        await this.actionService.doAction(action);
    },
    async tobaccoLedger(section) {
        const action = await this.orm.call("baseer.report.engine", "get_tobacco_ledger_action", [this.plainOptions(), section.account_id, section.company_id]);
        await this.actionService.doAction(action);
    },
});

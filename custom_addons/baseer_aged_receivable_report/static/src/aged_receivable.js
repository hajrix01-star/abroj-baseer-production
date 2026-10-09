/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user, userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { ReportSelector } from "@baseer_reports_menu/report_selector";

const MODEL = "baseer.aged.receivable.report";
const copy = {
    ar: {
        title: "أعمار الذمم المدينة", cutoff: "حتى تاريخ", apply: "عرض التقرير", print: "PDF",
        notice: "الأرصدة المفتوحة حتى تاريخ القطع · تُعرض الديون والأرصدة الدائنة غير المطبقة بشكل منفصل",
        loading: "جارٍ تحميل التقرير…", linesLoading: "جارٍ تحميل البنود…",
        error: "تعذر عرض التقرير. تحقق من التاريخ والصلاحيات ثم أعد المحاولة.",
        receivables: "الذمم المدينة", credits: "أرصدة دائنة غير مطبقة", net: "الصافي",
        not_due: "لم تستحق", d1_30: "1–30 يومًا", d31_60: "31–60 يومًا",
        d61_90: "61–90 يومًا", over_90: "أكثر من 90 يومًا", credit: "رصيد دائن",
        partner: "العميل", openCount: "البنود المفتوحة", date: "التاريخ", dueDate: "الاستحقاق",
        entry: "القيد", kind: "النوع", open: "المتبقي", bucket: "فئة التقادم",
        invoice: "فاتورة", credit_note: "إشعار دائن", direct_claim: "مطالبة مباشرة",
        unapplied_credit: "رصيد دائن غير مطبق", unusual: "بند غير معتاد",
        details: "عرض بنود العميل", noPartners: "لا توجد أرصدة مفتوحة في هذا التاريخ.",
        noLines: "لا توجد بنود مفتوحة لهذا العميل.", retry: "إعادة المحاولة", previous: "السابق", next: "التالي",
        page: "صفحة", of: "من", partners: "عميل", openLine: "فتح القيد",
    },
    en: {
        title: "Aged Receivables", cutoff: "As of", apply: "Show report", print: "PDF",
        notice: "Open balances as of the cutoff date · receivables and unapplied credits are shown separately",
        loading: "Loading report…", linesLoading: "Loading open items…",
        error: "Could not load the report. Check the date and your access rights, then retry.",
        receivables: "Receivables", credits: "Unapplied credits", net: "Net",
        not_due: "Not due", d1_30: "1–30 days", d31_60: "31–60 days",
        d61_90: "61–90 days", over_90: "Over 90 days", credit: "Credit",
        partner: "Customer", openCount: "Open items", date: "Date", dueDate: "Due date",
        entry: "Entry", kind: "Type", open: "Open amount", bucket: "Age bucket",
        invoice: "Invoice", credit_note: "Credit note", direct_claim: "Direct claim",
        unapplied_credit: "Unapplied credit", unusual: "Unusual item",
        details: "Show customer items", noPartners: "No open balances on this date.",
        noLines: "No open items for this customer.", retry: "Retry", previous: "Previous", next: "Next",
        page: "Page", of: "of", partners: "customers", openLine: "Open entry",
    },
};

const BUCKET_KEYS = ["not_due", "d1_30", "d31_60", "d61_90", "over_90"];

export class BaseerAgedReceivableReport extends Component {
    static template = "baseer_aged_receivable_report.Report";
    static components = { ReportSelector };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({
            cutoffDate: "", report: null, loading: true, printing: false, error: "",
            expandedPartnerId: null, lines: null, linesLoading: false, openingLineId: null,
        });
        this.appliedCutoff = null;
        this.requestToken = 0;
        this.linesToken = 0;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.refreshCompany());
        onWillStart(() => this.refreshCompany());
    }

    get labels() { return copy[this.lang]; }
    get activeCompanyId() { return Number(user.activeCompany?.id || 0); }
    get buckets() { return BUCKET_KEYS; }
    labelFor(value) { return this.labels[value] || value || ""; }
    amountClass(amount) {
        const value = String(amount || "").replace(/,/g, "");
        return /^-?0(?:\.0+)?$/.test(value) ? "is-zero" : value.startsWith("-") ? "is-negative" : "";
    }
    invalidate() {
        this.requestToken++;
        this.linesToken++;
        this.appliedCutoff = null;
        this.state.report = null;
        this.state.lines = null;
        this.state.expandedPartnerId = null;
        this.state.linesLoading = false;
        this.state.openingLineId = null;
        this.state.printing = false;
        this.state.error = "";
    }
    isCurrent(token, companyId) {
        return token === this.requestToken && companyId === this.activeCompanyId;
    }
    async refreshCompany() {
        this.invalidate();
        const token = this.requestToken;
        const companyId = this.activeCompanyId;
        this.state.cutoffDate = "";
        this.state.loading = true;
        try {
            const context = await this.orm.call(MODEL, "get_context", []);
            if (!this.isCurrent(token, companyId)) { return; }
            this.state.cutoffDate = context.cutoff_date;
            await this.loadReport(context.cutoff_date, 1);
        } catch (error) {
            if (this.isCurrent(token, companyId)) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (this.isCurrent(token, companyId)) { this.state.loading = false; }
        }
    }
    onDateChange(event) {
        this.invalidate();
        this.state.cutoffDate = event.target.value;
        this.state.loading = false;
    }
    async onApplyClick() {
        if (!this.state.cutoffDate || this.state.loading) { return; }
        this.invalidate();
        await this.loadReport(this.state.cutoffDate, 1);
    }
    async loadReport(cutoffDate, page) {
        if (!cutoffDate || this.state.loading && this.state.report) { return; }
        const token = ++this.requestToken;
        const companyId = this.activeCompanyId;
        this.linesToken++;
        this.state.expandedPartnerId = null;
        this.state.lines = null;
        this.state.linesLoading = false;
        this.state.loading = true;
        this.state.error = "";
        try {
            const report = await this.orm.call(MODEL, "get_report", [{ cutoff_date: cutoffDate, page }]);
            if (!this.isCurrent(token, companyId)) { return; }
            this.appliedCutoff = cutoffDate;
            this.state.report = report;
            this.state.expandedPartnerId = null;
            this.state.lines = null;
            this.linesToken++;
        } catch (error) {
            if (this.isCurrent(token, companyId)) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (this.isCurrent(token, companyId)) { this.state.loading = false; }
        }
    }
    async changePage(page) {
        if (!this.appliedCutoff || this.state.loading || page < 1 || page > this.state.report.page_count) { return; }
        await this.loadReport(this.appliedCutoff, page);
    }
    async togglePartner(partnerId) {
        if (this.state.expandedPartnerId === partnerId) {
            this.linesToken++;
            this.state.expandedPartnerId = null;
            this.state.lines = null;
            this.state.linesLoading = false;
            return;
        }
        this.linesToken++;
        this.state.expandedPartnerId = partnerId;
        this.state.lines = null;
        this.state.linesLoading = false;
        await this.loadPartnerLines(partnerId, 1);
    }
    async loadPartnerLines(partnerId, page) {
        if (!this.appliedCutoff || this.state.linesLoading || this.state.loading ||
            this.state.expandedPartnerId !== partnerId) { return; }
        const token = ++this.linesToken;
        const reportToken = this.requestToken;
        const companyId = this.activeCompanyId;
        const cutoffDate = this.appliedCutoff;
        this.state.linesLoading = true;
        this.state.error = "";
        try {
            const lines = await this.orm.call(MODEL, "get_partner_lines", [
                { cutoff_date: cutoffDate, partner_id: partnerId, page },
            ]);
            if (token === this.linesToken && this.isCurrent(reportToken, companyId) &&
                this.state.expandedPartnerId === partnerId) {
                this.state.lines = lines;
            }
        } catch (error) {
            if (token === this.linesToken && this.isCurrent(reportToken, companyId)) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.linesToken && this.isCurrent(reportToken, companyId)) {
                this.state.linesLoading = false;
            }
        }
    }
    async openLine(lineId) {
        if (!this.appliedCutoff || this.state.openingLineId || !lineId) { return; }
        const token = this.requestToken;
        const companyId = this.activeCompanyId;
        const cutoffDate = this.appliedCutoff;
        this.state.openingLineId = lineId;
        try {
            const action = await this.orm.call(MODEL, "action_open_line", [
                { line_id: lineId, cutoff_date: cutoffDate },
            ]);
            if (this.isCurrent(token, companyId)) { await this.action.doAction(action); }
        } catch (error) {
            if (this.isCurrent(token, companyId)) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (this.isCurrent(token, companyId)) { this.state.openingLineId = null; }
        }
    }
    async printReport() {
        if (!this.appliedCutoff || !this.state.report || this.state.loading || this.state.printing) { return; }
        const token = this.requestToken;
        const companyId = this.activeCompanyId;
        const cutoffDate = this.appliedCutoff;
        this.state.printing = true;
        try {
            const action = await this.orm.call(MODEL, "action_print", [{ cutoff_date: cutoffDate }]);
            if (this.isCurrent(token, companyId)) { await this.action.doAction(action); }
        } catch (error) {
            if (this.isCurrent(token, companyId)) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (this.isCurrent(token, companyId)) { this.state.printing = false; }
        }
    }
}

registry.category("baseer_reports").add("aged_receivable", {
    key: "aged_receivable",
    label: { ar: "أعمار الذمم المدينة", en: "Aged Receivables" },
    sequence: 60,
    kind: "component",
    component: BaseerAgedReceivableReport,
    groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"],
});

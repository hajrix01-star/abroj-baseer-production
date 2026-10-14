/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user, userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { ReportSelector } from "@baseer_reports_menu/report_selector";

const MODEL = "baseer.balance.sheet.report";
const copy = {
    ar: {
        title: "الميزانية العمومية", period: "الفترة", month: "شهر", quarter: "ربع سنة",
        fiscalYear: "سنة مالية", custom: "تواريخ مخصصة", from: "من", to: "إلى",
        allJournals: "جميع الدفاتر", partial: "نتيجة الدفاتر المختارة فقط",
        posted: "قيود مرحلة · حسب التاريخ المحاسبي · ليست لقطة تاريخية مجمدة",
        apply: "عرض التقرير", print: "PDF", loading: "جارٍ تحميل الميزانية…",
        error: "تعذر عرض التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        asOf: "كما في", balance: "الرصيد", noAccounts: "لا توجد حسابات في هذا القسم.",
        previous: "السابق", next: "التالي", page: "صفحة", of: "من", source: "عرض القيود",
        assets: "الأصول", liabilities: "الالتزامات", equity: "حقوق الملكية",
        brought_forward: "نتيجة مرحلة من السنة السابقة", current_result: "نتيجة السنة الحالية",
        totalAssets: "إجمالي الأصول", totalOther: "إجمالي الالتزامات والحقوق والنتائج",
    },
    en: {
        title: "Balance Sheet", period: "Period", month: "Month", quarter: "Quarter",
        fiscalYear: "Fiscal year", custom: "Custom dates", from: "From", to: "To",
        allJournals: "All journals", partial: "Selected journals only",
        posted: "Posted entries · accounting date · not a frozen historical snapshot",
        apply: "Show report", print: "PDF", loading: "Loading balance sheet…",
        error: "Could not load the report. Check the period and access rights, then retry.",
        asOf: "As of", balance: "Balance", noAccounts: "No accounts in this section.",
        previous: "Previous", next: "Next", page: "Page", of: "of", source: "View entries",
        assets: "Assets", liabilities: "Liabilities", equity: "Equity",
        brought_forward: "Result Brought Forward", current_result: "Current Year Result",
        totalAssets: "Total Assets", totalOther: "Total Liabilities, Equity and Results",
    },
};

export class BaseerBalanceSheetReport extends Component {
    static template = "baseer_balance_sheet_report.Report";
    static components = { ReportSelector };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({
            loading: true, printing: false, error: "", journals: [], report: null, period: null,
            filters: { company_id: 0, date_from: "", date_to: "", journal_ids: [] },
            periodKind: "month", customFrom: "", customTo: "",
            expanded: {}, accountPages: {}, sectionLoading: {},
        });
        this.appliedFilters = null;
        this.requestToken = 0;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.refreshCompany());
        onWillStart(async () => this.refreshCompany());
    }

    get labels() { return copy[this.lang]; }
    get activeCompanyId() { return Number(user.activeCompany?.id || 0); }
    get periodSummary() {
        return this.state.period?.kind === this.state.periodKind
            ? this.state.period.display_label : this.periodKindLabel(this.state.periodKind);
    }
    periodKindLabel(kind) {
        return { month: this.labels.month, quarter: this.labels.quarter,
            fiscal_year: this.labels.fiscalYear, custom: this.labels.custom }[kind] || kind;
    }
    amountClass(amount, negative = false) {
        if (/^-?0(?:\.0+)?$/.test(String(amount).replace(/,/g, ""))) { return "is-zero"; }
        return negative ? "is-negative" : "";
    }
    invalidate() {
        this.requestToken++;
        this.appliedFilters = null;
        this.state.loading = false;
        this.state.printing = false;
        this.state.report = null;
        this.state.error = "";
        this.state.expanded = {};
        this.state.accountPages = {};
        this.state.sectionLoading = {};
    }
    async refreshCompany() {
        const companyId = this.activeCompanyId;
        this.invalidate();
        const token = this.requestToken;
        this.state.filters.company_id = companyId;
        this.state.filters.journal_ids = [];
        this.state.journals = [];
        this.state.period = null;
        this.state.periodKind = "month";
        this.state.loading = true;
        try {
            const context = await this.orm.call(MODEL, "get_context", [companyId]);
            if (token !== this.requestToken || companyId !== this.activeCompanyId) { return; }
            this.state.journals = context.journals;
            this.state.period = context.default_period;
            this.state.filters.date_from = context.default_period.date_from;
            this.state.filters.date_to = context.default_period.date_to;
            this.state.customFrom = context.default_period.date_from;
            this.state.customTo = context.default_period.date_to;
            await this.apply();
        } catch (error) {
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && companyId === this.activeCompanyId) { this.state.loading = false; }
        }
    }
    async resolveAndApply(kind, anchorDate, direction = 0) {
        this.invalidate();
        const token = this.requestToken;
        const companyId = this.activeCompanyId;
        this.state.loading = true;
        try {
            const period = await this.orm.call(MODEL, "resolve_period", [{
                company_id: companyId, kind, anchor_date: anchorDate, direction,
                date_from: kind === "custom" ? this.state.customFrom : "",
                date_to: kind === "custom" ? this.state.customTo : "",
            }]);
            if (token !== this.requestToken || companyId !== this.activeCompanyId) { return; }
            this.state.period = period;
            this.state.periodKind = kind;
            this.state.filters.date_from = period.date_from;
            this.state.filters.date_to = period.date_to;
            await this.apply();
        } catch (error) {
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && companyId === this.activeCompanyId) { this.state.loading = false; }
        }
    }
    async setPeriodKind(kind) {
        if (!["month", "quarter", "fiscal_year", "custom"].includes(kind)) { return; }
        const anchorDate = this.state.period?.date_to || this.state.filters.date_to;
        this.state.periodKind = kind;
        if (kind === "custom") {
            this.state.customFrom = this.state.period?.date_from || this.state.filters.date_from;
            this.state.customTo = this.state.period?.date_to || this.state.filters.date_to;
            this.invalidate();
            return;
        }
        await this.resolveAndApply(kind, anchorDate);
    }
    async navigatePeriod(direction) {
        if (![-1, 1].includes(direction) || this.state.periodKind === "custom" || !this.state.period) { return; }
        const anchor = direction < 0 ? this.state.period.date_from : this.state.period.date_to;
        await this.resolveAndApply(this.state.periodKind, anchor, direction);
    }
    onDateChange(event) {
        if (event.target.name === "date_from") { this.state.customFrom = event.target.value; }
        if (event.target.name === "date_to") { this.state.customTo = event.target.value; }
        this.invalidate();
    }
    async onApplyClick() {
        if (this.state.periodKind === "custom") { await this.resolveAndApply("custom", this.state.customFrom); }
        else { await this.apply(); }
    }
    onJournalChange(event) {
        const id = Number(event.target.value);
        const selected = new Set(this.state.filters.journal_ids);
        if (event.target.checked) { selected.add(id); } else { selected.delete(id); }
        this.state.filters.journal_ids = [...selected];
        this.onApplyClick();
    }
    async apply() {
        if (!this.activeCompanyId || this.state.filters.company_id !== this.activeCompanyId) {
            await this.refreshCompany();
            return;
        }
        const filters = { ...this.state.filters, journal_ids: [...this.state.filters.journal_ids] };
        this.invalidate();
        const token = this.requestToken;
        this.state.loading = true;
        try {
            const report = await this.orm.call(MODEL, "get_report", [filters]);
            if (token === this.requestToken && filters.company_id === this.activeCompanyId) {
                this.appliedFilters = filters;
                this.state.report = report;
            }
        } catch (error) {
            if (token === this.requestToken && filters.company_id === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && filters.company_id === this.activeCompanyId) { this.state.loading = false; }
        }
    }
    async toggleSection(key) {
        this.state.expanded[key] = !this.state.expanded[key];
        if (this.state.expanded[key] && !this.state.accountPages[key]) { await this.loadSection(key, 1); }
    }
    async loadSection(key, page) {
        if (!this.appliedFilters || this.state.sectionLoading[key] ||
            this.appliedFilters.company_id !== this.activeCompanyId) { return; }
        const token = this.requestToken;
        this.state.sectionLoading[key] = true;
        try {
            const result = await this.orm.call(MODEL, "get_section_accounts", [this.appliedFilters, key, page]);
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) {
                this.state.accountPages[key] = result;
            }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.sectionLoading[key] = false; }
        }
    }
    async openAccount(accountId, section) {
        if (!this.appliedFilters || this.appliedFilters.company_id !== this.activeCompanyId) { return; }
        const token = this.requestToken;
        const companyId = this.activeCompanyId;
        try {
            const action = await this.orm.call(MODEL, "get_account_action", [this.appliedFilters, accountId, section]);
            if (token === this.requestToken && companyId === this.activeCompanyId) { await this.action.doAction(action); }
        } catch (error) {
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        }
    }
    async printReport() {
        if (!this.appliedFilters || !this.state.report || this.state.loading || this.state.printing ||
            this.appliedFilters.company_id !== this.activeCompanyId) { return; }
        const token = this.requestToken;
        const companyId = this.activeCompanyId;
        const filters = { ...this.appliedFilters, journal_ids: [...this.appliedFilters.journal_ids] };
        this.state.printing = true;
        try {
            const action = await this.orm.call(MODEL, "action_print", [filters]);
            if (token === this.requestToken && companyId === this.activeCompanyId) { await this.action.doAction(action); }
        } catch (error) {
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && companyId === this.activeCompanyId) { this.state.printing = false; }
        }
    }
}

registry.category("baseer_reports").add("balance_sheet", {
    key: "balance_sheet", label: { ar: "الميزانية العمومية", en: "Balance Sheet" },
    sequence: 70, kind: "component", component: BaseerBalanceSheetReport,
    groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"],
});

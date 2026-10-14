/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user, userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { ReportSelector } from "@baseer_reports_menu/report_selector";

const MODEL = "baseer.general.ledger.report";
const copy = {
    ar: {
        title: "دفتر الأستاذ العام", from: "من", to: "إلى", period: "الفترة",
        month: "شهر", quarter: "ربع سنة", fiscalYear: "سنة مالية", custom: "تواريخ مخصصة",
        journals: "الدفاتر", allJournals: "جميع الدفاتر", partial: "نتيجة الدفاتر المختارة فقط",
        posted: "قيود مرحلة · حسب التاريخ المحاسبي · ليست لقطة تاريخية مجمدة",
        apply: "عرض التقرير", loading: "جارٍ تحميل التقرير…", error: "تعذر عرض التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        print: "PDF",
        account: "الحساب", opening: "الرصيد الافتتاحي", debit: "مدين", credit: "دائن", closing: "الرصيد الختامي",
        rbf: "نتيجة مرحلة من السنة السابقة", rbfSources: "مصادر نتيجة السنوات السابقة", total: "إجمالي دفتر الأستاذ",
        date: "التاريخ", entry: "القيد", label: "البيان", running: "الرصيد الجاري",
        source: "عرض القيد", openingSource: "عرض مصدر الرصيد الافتتاحي", linesLoading: "جارٍ تحميل القيود…", accountsLoading: "جارٍ تحميل الحسابات…",
        noAccounts: "لا توجد حسابات ذات حركة لهذه الفترة.", noLines: "لا توجد قيود في هذا القسم.",
        more: "تحميل المزيد", previous: "السابق", next: "التالي", page: "صفحة", of: "من",
    },
    en: {
        title: "General Ledger", from: "From", to: "To", period: "Period",
        month: "Month", quarter: "Quarter", fiscalYear: "Fiscal year", custom: "Custom dates",
        journals: "Journals", allJournals: "All journals", partial: "Selected journals only",
        posted: "Posted entries · accounting date · not a frozen historical snapshot",
        apply: "Show report", loading: "Loading report…", error: "Could not load the report. Check the period and your access rights, then retry.",
        print: "PDF",
        account: "Account", opening: "Opening Balance", debit: "Debit", credit: "Credit", closing: "Closing Balance",
        rbf: "Result Brought Forward", rbfSources: "Prior-year result sources", total: "Total General Ledger",
        date: "Date", entry: "Entry", label: "Label", running: "Running Balance",
        source: "View entry", openingSource: "View opening balance source", linesLoading: "Loading entries…", accountsLoading: "Loading accounts…",
        noAccounts: "No accounts with activity were found.", noLines: "No entries in this section.",
        more: "Load more", previous: "Previous", next: "Next", page: "Page", of: "of",
    },
};

export class BaseerGeneralLedgerReport extends Component {
    static template = "baseer_general_ledger_report.Report";
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
            rbfOpen: false, rbfLoading: false, rbfAccounts: null,
            accountOpening: {},
        });
        this.appliedFilters = null;
        this.requestToken = 0;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.refreshCompany());
        onWillStart(async () => {
            await this.refreshCompany();
        });
    }

    get labels() { return copy[this.lang]; }
    get activeCompanyId() { return Number(user.activeCompany?.id || 0); }
    get periodSummary() {
        return this.state.period?.kind === this.state.periodKind &&
            (this.state.periodKind !== "custom" || this.state.report)
            ? this.state.period.display_label : this.periodKindLabel(this.state.periodKind);
    }
    periodKindLabel(kind) { return { month: this.labels.month, quarter: this.labels.quarter, fiscal_year: this.labels.fiscalYear, custom: this.labels.custom }[kind] || kind; }
    amountClass(negative, amount) {
        if (/^-?0(?:\.0+)?$/.test(String(amount).replace(/,/g, ""))) { return "is-zero"; }
        return negative ? "is-negative" : "";
    }
    lineKey(accountId, scope) { return `${scope}:${accountId}`; }
    invalidate() {
        this.requestToken++;
        this.appliedFilters = null;
        this.state.loading = false;
        this.state.printing = false;
        this.state.report = null;
        this.state.error = "";
        this.state.rbfOpen = false;
        this.state.rbfLoading = false;
        this.state.rbfAccounts = null;
        this.state.accountOpening = {};
    }
    async refreshCompany() {
        const id = this.activeCompanyId;
        this.invalidate();
        const token = this.requestToken;
        this.state.filters.company_id = id;
        this.state.filters.journal_ids = [];
        this.state.journals = [];
        this.state.period = null;
        this.state.periodKind = "month";
        this.state.loading = true;
        try {
            const context = await this.orm.call(MODEL, "get_context", [id]);
            if (token !== this.requestToken || id !== this.activeCompanyId) { return; }
            this.state.journals = context.journals;
            this.state.period = context.default_period;
            this.state.filters.date_from = context.default_period.date_from;
            this.state.filters.date_to = context.default_period.date_to;
            this.state.customFrom = context.default_period.date_from;
            this.state.customTo = context.default_period.date_to;
            await this.apply();
        } catch (error) {
            if (token === this.requestToken && id === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && id === this.activeCompanyId) { this.state.loading = false; }
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
        const anchorDate = direction < 0 ? this.state.period.date_from : this.state.period.date_to;
        await this.resolveAndApply(this.state.periodKind, anchorDate, direction);
    }
    onDateChange(event) {
        if (event.target.name === "date_from") { this.state.customFrom = event.target.value; }
        if (event.target.name === "date_to") { this.state.customTo = event.target.value; }
        this.invalidate();
    }
    async onApplyClick() {
        if (this.state.periodKind === "custom") {
            await this.resolveAndApply("custom", this.state.customFrom);
        } else {
            await this.apply();
        }
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
        const filters = {
            company_id: this.state.filters.company_id,
            date_from: this.state.filters.date_from,
            date_to: this.state.filters.date_to,
            journal_ids: [...this.state.filters.journal_ids],
        };
        this.invalidate();
        const token = this.requestToken;
        this.state.loading = true;
        try {
            const report = await this.orm.call(MODEL, "get_report", [filters, 1]);
            if (token === this.requestToken && filters.company_id === this.activeCompanyId) {
                this.appliedFilters = filters;
                this.state.report = report;
            }
        } catch (error) {
            if (token === this.requestToken && filters.company_id === this.activeCompanyId) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken && filters.company_id === this.activeCompanyId) { this.state.loading = false; }
        }
    }
    async loadAccounts(page) {
        if (!this.appliedFilters || this.state.loading || this.appliedFilters.company_id !== this.activeCompanyId) { return; }
        const token = this.requestToken;
        this.state.loading = true;
        try {
            const report = await this.orm.call(MODEL, "get_report", [this.appliedFilters, page]);
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) {
                this.state.report = report;
                this.state.accountOpening = {};
            }
        } catch (error) {
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) { this.state.loading = false; }
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
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                await this.action.doAction(action);
            }
        } catch (error) {
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                this.state.printing = false;
            }
        }
    }
    async toggleRbf() {
        this.state.rbfOpen = !this.state.rbfOpen;
        if (this.state.rbfOpen && !this.state.rbfAccounts) { await this.loadRbfAccounts(1); }
    }
    async loadRbfAccounts(page) {
        if (!this.appliedFilters || this.state.rbfLoading || this.appliedFilters.company_id !== this.activeCompanyId) { return; }
        const token = this.requestToken;
        this.state.rbfLoading = true;
        try {
            const rows = await this.orm.call(MODEL, "get_rbf_accounts", [this.appliedFilters, page]);
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) {
                this.state.rbfAccounts = rows;
                this.state.accountOpening = {};
            }
        } catch (error) {
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) { this.state.rbfLoading = false; }
        }
    }
    async openAccount(accountId, scope) {
        const key = this.lineKey(accountId, scope);
        if (!this.appliedFilters || this.state.accountOpening[key] || this.appliedFilters.company_id !== this.activeCompanyId) { return; }
        const token = this.requestToken;
        this.state.accountOpening[key] = true;
        try {
            const action = await this.orm.call(MODEL, "get_account_action", [
                this.appliedFilters, accountId, scope,
            ]);
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) { await this.action.doAction(action); }
        } catch (error) {
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken && this.appliedFilters?.company_id === this.activeCompanyId) { this.state.accountOpening[key] = false; }
        }
    }
}

registry.category("baseer_reports").add("general_ledger", {
    key: "general_ledger",
    label: { ar: "دفتر الأستاذ العام", en: "General Ledger" },
    sequence: 50,
    kind: "component",
    component: BaseerGeneralLedgerReport,
    groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"],
});

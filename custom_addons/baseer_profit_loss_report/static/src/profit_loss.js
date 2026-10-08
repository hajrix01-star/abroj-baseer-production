/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { ReportSelector } from "@baseer_reports_menu/report_selector";

const MODEL = "baseer.profit.loss.report";
const ZERO = Object.freeze({ amount: "0.00", negative: false });
const copy = {
    ar: {
        title: "الربح والخسارة", company: "الشركة", journals: "الدفاتر", allJournals: "جميع الدفاتر", selectedJournals: "الدفاتر المختارة",
        posted: "قيود مرحلة · حسب التاريخ المحاسبي · ليست لقطة تاريخية مجمدة", loading: "جارٍ تحميل التقرير…", accountsLoading: "جارٍ تحميل الحسابات…",
        error: "تعذر عرض التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.", account: "الحساب", balance: "الرصيد",
        income: "الإيرادات", income_other: "إيرادات أخرى", expense_direct_cost: "تكلفة المبيعات", expense: "المصروفات", expense_other: "مصروفات أخرى", expense_depreciation: "الاستهلاك",
        gross: "إجمالي الربح", totalIncome: "إجمالي الإيرادات", totalExpense: "إجمالي المصروفات", operating: "صافي الربح التشغيلي", otherNet: "صافي الإيرادات الأخرى", net: "صافي الربح",
        source: "عرض قيود اليومية", previous: "السابق", next: "التالي", page: "صفحة", noAccounts: "لا توجد حسابات في هذا القسم.", debit: "مدين", credit: "دائن",
        period: "الفترة", comparison: "المقارنة", month: "شهر", quarter: "ربع سنة", fiscalYear: "سنة مالية", customDates: "تواريخ مخصصة", noComparison: "دون مقارنة", previousPeriods: "الفترات السابقة", samePeriodLastYear: "الفترة نفسها العام الماضي", periods: "فترات", periodOrder: "ترتيب الفترات", descending: "تنازلي", ascending: "تصاعدي", from: "من", to: "إلى", current: "الحالية",
    },
    en: {
        title: "Profit and Loss", company: "Company", journals: "Journals", allJournals: "All journals", selectedJournals: "Selected journals only",
        posted: "Posted entries · accounting date · not a frozen historical snapshot", loading: "Loading report…", accountsLoading: "Loading accounts…",
        error: "Could not load the report. Check the period and your access rights, then retry.", account: "Account", balance: "Balance",
        income: "Income", income_other: "Other income", expense_direct_cost: "Cost of sales", expense: "Expenses", expense_other: "Other expenses", expense_depreciation: "Depreciation",
        gross: "Gross profit", totalIncome: "Total income", totalExpense: "Total expense", operating: "Net operating income", otherNet: "Net other income", net: "Net income",
        source: "View journal items", previous: "Previous", next: "Next", page: "Page", noAccounts: "No accounts in this section.", debit: "Debit", credit: "Credit",
        period: "Period", comparison: "Comparison", month: "Month", quarter: "Quarter", fiscalYear: "Fiscal year", customDates: "Custom dates", noComparison: "No comparison", previousPeriods: "Previous periods", samePeriodLastYear: "Same period last year", periods: "Periods", periodOrder: "Period order", descending: "Descending", ascending: "Ascending", from: "From", to: "To", current: "Current",
    },
};

const PERIOD_KINDS = ["month", "quarter", "fiscal_year", "custom"];
const COMPARISON_KINDS = ["none", "previous_period", "same_period_last_year", "custom"];

export class BaseerProfitLossReport extends Component {
    static template = "baseer_profit_loss_report.Report";
    static components = { ReportSelector, Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({ loading: true, error: "", companies: [], journals: [], report: null,
            filters: this.emptyFilters(), expanded: {}, pages: {}, accountLoading: {}, accountOpening: {} });
        this.appliedFilters = null;
        this.requestToken = 0;
        onWillStart(async () => {
            try {
                this.installContext(await this.orm.call(MODEL, "get_context", []));
                await this.apply();
            } catch (error) {
                this.state.error = error?.data?.message || this.labels.error;
                this.state.loading = false;
            }
        });
    }

    emptyFilters() { return { company_id: 0, period: { kind: "month", anchor_date: "", direction: 0, date_from: "", date_to: "" }, comparison: { kind: "none", order: "descending", count: 1, date_from: "", date_to: "" }, journal_ids: [] }; }
    get labels() { return copy[this.lang]; }
    get reportPeriods() { return this.state.report?.periods || []; }
    get primaryPeriod() { return this.reportPeriods.find((period) => period.role === "primary") || this.reportPeriods[0]; }
    get periodSummary() { return this.primaryPeriod?.display_label || this.primaryPeriod?.label || this.periodKindLabel(this.state.filters.period.kind); }
    get periodOptions() {
        return this.state.report?.period_controls?.options || PERIOD_KINDS.map((kind) => ({ kind, display_label: this.periodKindLabel(kind) }));
    }
    get comparisonSummary() {
        const comparison = this.state.filters.comparison;
        if (comparison.kind === "previous_period") {
            return `${this.labels.comparison}: ${comparison.count} ${this.labels.previousPeriods}`;
        }
        return `${this.labels.comparison}: ${this.comparisonKindLabel(comparison.kind)}`;
    }
    periodKindLabel(kind) { return { month: this.labels.month, quarter: this.labels.quarter, fiscal_year: this.labels.fiscalYear, custom: this.labels.customDates }[kind] || kind; }
    comparisonKindLabel(kind) { return { none: this.labels.noComparison, previous_period: this.labels.previousPeriods, same_period_last_year: this.labels.samePeriodLastYear, custom: this.labels.customDates }[kind] || kind; }
    amountClass(value) {
        const amount = value?.amount || ZERO.amount;
        if (/^-?0(?:\.0+)?$/.test(String(amount).replace(/,/g, ""))) { return "is-zero"; }
        return value?.negative ? "is-negative" : "";
    }
    amountFor(entity, periodKey) { return entity?.amounts?.[periodKey] || ZERO; }
    rowClass(row) { return `o_baseer_pl_${row.kind || "detail"} o_baseer_pl_${row.key}`; }
    sectionLabel(key) { return this.labels[key] || key; }
    accountKey(account, periodKey) { return `${account.id}:${periodKey}`; }
    rowColspan() { return Math.max(2, this.reportPeriods.length + 1); }
    cloneFilters(direction = 0) {
        const { period, comparison } = this.state.filters;
        return { company_id: this.state.filters.company_id, period: { ...period, direction }, comparison: { ...comparison }, journal_ids: [...this.state.filters.journal_ids] };
    }
    installContext(context) {
        this.state.companies = context.companies || [];
        this.state.journals = context.journals || [];
        const defaults = context.default_filters || {};
        const period = defaults.period || { kind: "month", anchor_date: context.default_date_to || "", date_from: context.default_date_from || "", date_to: context.default_date_to || "" };
        const comparison = defaults.comparison || { kind: "none", order: "descending" };
        Object.assign(this.state.filters, this.emptyFilters(), { company_id: defaults.company_id || context.default_company_id || 0, period: { ...this.emptyFilters().period, ...period, direction: 0 }, comparison: { ...this.emptyFilters().comparison, ...comparison }, journal_ids: [...(defaults.journal_ids || [])] });
    }
    invalidate() {
        this.requestToken += 1;
        this.state.loading = false;
        this.state.report = null;
        this.state.error = "";
        this.state.expanded = {};
        this.state.pages = {};
        this.state.accountLoading = {};
        this.state.accountOpening = {};
        this.appliedFilters = null;
    }
    async onCompanyChange(event) {
        this.invalidate();
        const token = this.requestToken;
        try {
            const context = await this.orm.call(MODEL, "get_context", [Number(event.target.value)]);
            if (token === this.requestToken) { this.installContext(context); await this.apply(); }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        }
    }
    async setPeriodKind(kind) {
        if (!PERIOD_KINDS.includes(kind) || this.state.filters.period.kind === kind) { return; }
        this.state.filters.period.kind = kind;
        this.state.filters.period.direction = 0;
        if (kind === "custom") {
            this.state.filters.period.date_from = this.primaryPeriod?.date_from || this.state.filters.period.date_from;
            this.state.filters.period.date_to = this.primaryPeriod?.date_to || this.state.filters.period.date_to;
            return;
        }
        await this.apply();
    }
    async navigatePeriod(direction) { if ([-1, 1].includes(direction) && this.state.filters.period.kind !== "custom") { await this.apply(direction); } }
    async navigatePeriodKind(kind, direction) {
        if (!PERIOD_KINDS.includes(kind) || kind === "custom" || ![-1, 1].includes(direction)) { return; }
        this.state.filters.period.kind = kind;
        this.state.filters.period.direction = 0;
        await this.apply(direction);
    }
    async onPeriodDateChange(event) {
        this.state.filters.period[event.target.name] = event.target.value;
        if (this.state.filters.period.date_from && this.state.filters.period.date_to) { await this.apply(); }
    }
    async setComparisonKind(kind) {
        if (!COMPARISON_KINDS.includes(kind) || this.state.filters.comparison.kind === kind) { return; }
        this.state.filters.comparison.kind = kind;
        if (kind !== "previous_period") { this.state.filters.comparison.count = 1; }
        if (kind === "custom") {
            this.state.filters.comparison.date_from = this.primaryPeriod?.date_from || this.state.filters.comparison.date_from;
            this.state.filters.comparison.date_to = this.primaryPeriod?.date_to || this.state.filters.comparison.date_to;
            return;
        }
        await this.apply();
    }
    async onComparisonChange(event) {
        const { name, value } = event.target;
        this.state.filters.comparison[name] = name === "count" ? Number(value) : value;
        const comparison = this.state.filters.comparison;
        if (comparison.kind !== "custom" || (comparison.date_from && comparison.date_to)) { await this.apply(); }
    }
    onJournalChange(event) {
        const id = Number(event.target.value);
        const next = new Set(this.state.filters.journal_ids);
        if (event.target.checked) { next.add(id); } else { next.delete(id); }
        this.state.filters.journal_ids = [...next];
        this.apply();
    }
    legacyReport(report) {
        if (report.rows) { return report; }
        const current = "current";
        const rows = [];
        for (const section of report.sections || []) {
            rows.push({ key: section.key, kind: "section", level: 0, section: section.key, label: this.sectionLabel(section.key), expandable: true, amounts: { [current]: section } });
            if (section.key === "expense_direct_cost") { rows.push({ key: "gross_profit", kind: "subtotal", label: this.labels.gross, amounts: { [current]: report.gross_profit || ZERO } }); }
        }
        rows.push({ key: "net_profit", kind: "result", level: 0, label: this.labels.net, amounts: { [current]: report.net_profit || ZERO } });
        return { ...report, periods: [{ key: current, role: "primary", label: this.labels.current, display_label: this.labels.current, date_from: report.period?.date_from, date_to: report.period?.date_to }], rows };
    }
    async apply(direction = 0) {
        const filters = this.cloneFilters(direction);
        this.invalidate();
        const token = this.requestToken;
        this.state.loading = true;
        try {
            const response = await this.orm.call(MODEL, "get_report", [filters]);
            if (token === this.requestToken) {
                const report = this.legacyReport(response);
                this.state.report = report;
                if (report.period_controls?.anchor_date) { this.state.filters.period.anchor_date = report.period_controls.anchor_date; }
                this.state.filters.period.direction = 0;
                this.appliedFilters = this.cloneFilters();
            }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.loading = false; }
        }
    }
    async toggleSection(row) {
        const section = row.section || row.key;
        if (!row.expandable || !section) { return; }
        if (this.state.expanded[section]) { this.state.expanded[section] = false; return; }
        this.state.expanded[section] = true;
        if (!this.state.pages[section]) { await this.loadAccounts(section, 1); }
    }
    async loadAccounts(section, page) {
        if (!this.appliedFilters || this.state.accountLoading[section]) { return; }
        const token = this.requestToken;
        this.state.accountLoading[section] = true;
        try {
            const result = await this.orm.call(MODEL, "get_accounts", [this.appliedFilters, section, page]);
            if (token === this.requestToken) { this.state.pages[section] = result; }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.accountLoading[section] = false; }
        }
    }
    async openAccount(account, periodKey) {
        const key = this.accountKey(account, periodKey);
        if (!this.appliedFilters || this.state.accountOpening[key]) { return; }
        const token = this.requestToken;
        this.state.accountOpening[key] = true;
        try {
            const action = await this.orm.call(MODEL, "get_account_action", [this.appliedFilters, account.id, periodKey]);
            if (token === this.requestToken) { await this.env.services.action.doAction(action); }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.accountOpening[key] = false; }
        }
    }
}

registry.category("baseer_reports").add("profit_loss", { key: "profit_loss", label: { ar: "الربح والخسارة", en: "Profit and Loss" }, sequence: 40, kind: "component", component: BaseerProfitLossReport, groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"] });

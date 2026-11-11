/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";

import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { user, userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { ReportSelector } from "@baseer_reports_menu/report_selector";
import { ReportExportButtons } from "@baseer_reports_menu/report_export";
import { useReportDrill } from "@baseer_reports_menu/report_drill";

const MODEL = "baseer.profit.loss.report";
const ZERO = Object.freeze({ amount: "0.00", negative: false });
const copy = {
    ar: {
        title: "الأداء المالي — الربح والخسارة", financialPerformance: "المالية", keyIndicators: "المؤشرات المالية الرئيسية", company: "الشركة", journals: "الدفاتر", allJournals: "جميع الدفاتر", selectedJournals: "الدفاتر المختارة",
        posted: "قيود مرحلة · حسب التاريخ المحاسبي · ليست لقطة تاريخية مجمدة", loading: "جارٍ تحميل التقرير…", accountsLoading: "جارٍ تحميل الحسابات…",
        error: "تعذر عرض التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.", account: "الحساب", balance: "الرصيد",
        income: "الإيرادات", income_other: "إيرادات أخرى", expense_direct_cost: "تكلفة المبيعات", expense: "المصروفات", expense_other: "مصروفات أخرى", expense_depreciation: "الاستهلاك",
        gross: "إجمالي الربح", totalIncome: "إجمالي الإيرادات", totalExpense: "إجمالي المصروفات", operating: "صافي الربح التشغيلي", otherNet: "صافي الإيرادات الأخرى", net: "صافي الربح",
        source: "عرض قيود اليومية", previous: "السابق", next: "التالي", page: "صفحة", noAccounts: "لا توجد حسابات في هذا القسم.", debit: "مدين", credit: "دائن",
        period: "الفترة", comparison: "المقارنة", month: "شهر", quarter: "ربع سنة", fiscalYear: "سنة مالية", customDates: "تواريخ مخصصة", noComparison: "دون مقارنة", previousPeriods: "الفترة السابقة", samePeriodLastYear: "الفترة نفسها العام الماضي", periods: "فترات", periodOrder: "ترتيب الفترات", descending: "تنازلي", ascending: "تصاعدي", from: "من", to: "إلى", current: "الحالية",
        waterfallTitle: "جسر الربحية", waterfallCaption: "من الإيرادات إلى صافي الربح", waterfallAccessible: "تسلسل صافي الربح: الإيرادات، تكلفة المبيعات، المصروفات التشغيلية، صافي الإيرادات الأخرى، ثم صافي الربح.", statementTitle: "قائمة الربح والخسارة", statementCaption: "تفصيل موثّق قابل للوصول إلى القيود", revenueAccountsTitle: "أعلى حسابات الإيراد", revenueAccountsCaption: "أكبر خمسة حسابات ضمن الفترة", financialNotesTitle: "ملاحظات مالية", financialNotesCaption: "نطاق البيانات والتحقق", postedShort: "قيود مُرحّلة", vsComparison: "مقارنة", noComparisonData: "لا توجد مقارنة", noRevenueAccounts: "لا توجد حسابات إيراد ضمن الفترة", unavailable: "غير متاح",
        cost_of_sales: "تكلفة المبيعات", gross_profit: "إجمالي الربح", gross_margin: "هامش الربح الإجمالي", net_other_income: "صافي الإيرادات الأخرى", net_income: "صافي الربح", posted_only: "الأرقام من القيود المُرحّلة فقط.", partial_journals: "النتائج مقصورة على الدفاتر المختارة.", comparison_available: "المقارنة مبنية على فترة واحدة محددة.", comparison_unavailable: "اختر مقارنة لإظهار اتجاه الفترة.", gross_margin_unavailable: "هامش الربح غير متاح عندما لا يكون صافي الإيراد موجبًا.", revenue_share_unavailable: "حصة حسابات الإيراد غير متاحة عندما لا يكون إجمالي الإيراد موجبًا.",
    },
    en: {
        title: "Financial Performance — Profit and Loss", financialPerformance: "Finance", keyIndicators: "Key financial indicators", company: "Company", journals: "Journals", allJournals: "All journals", selectedJournals: "Selected journals only",
        posted: "Posted entries · accounting date · not a frozen historical snapshot", loading: "Loading report…", accountsLoading: "Loading accounts…",
        error: "Could not load the report. Check the period and your access rights, then retry.", account: "Account", balance: "Balance",
        income: "Income", income_other: "Other income", expense_direct_cost: "Cost of sales", expense: "Expenses", expense_other: "Other expenses", expense_depreciation: "Depreciation",
        gross: "Gross profit", totalIncome: "Total income", totalExpense: "Total expense", operating: "Net operating income", otherNet: "Net other income", net: "Net income",
        source: "View journal items", previous: "Previous", next: "Next", page: "Page", noAccounts: "No accounts in this section.", debit: "Debit", credit: "Credit",
        period: "Period", comparison: "Comparison", month: "Month", quarter: "Quarter", fiscalYear: "Fiscal year", customDates: "Custom dates", noComparison: "No comparison", previousPeriods: "Previous period", samePeriodLastYear: "Same period last year", periods: "Periods", periodOrder: "Period order", descending: "Descending", ascending: "Ascending", from: "From", to: "To", current: "Current",
        waterfallTitle: "Profit bridge", waterfallCaption: "From revenue to net income", waterfallAccessible: "Net income sequence: revenue, cost of sales, operating expenses, net other income, then net income.", statementTitle: "Profit and loss statement", statementCaption: "Auditable detail with journal access", revenueAccountsTitle: "Top revenue accounts", revenueAccountsCaption: "Five largest accounts in the period", financialNotesTitle: "Financial notes", financialNotesCaption: "Data scope and verification", postedShort: "Posted entries", vsComparison: "vs comparison", noComparisonData: "No comparison", noRevenueAccounts: "No revenue accounts in this period", unavailable: "Unavailable",
        cost_of_sales: "Cost of sales", gross_profit: "Gross profit", gross_margin: "Gross margin", net_other_income: "Net other income", net_income: "Net income", posted_only: "Amounts come from posted entries only.", partial_journals: "Results are limited to the selected journals.", comparison_available: "Comparison is based on one selected period.", comparison_unavailable: "Choose a comparison to show the period trend.", gross_margin_unavailable: "Gross margin is unavailable when net revenue is not positive.", revenue_share_unavailable: "Revenue-account share is unavailable when total revenue is not positive.",
    },
};

const PERIOD_KINDS = ["month", "quarter", "fiscal_year", "custom"];
const COMPARISON_KINDS = ["none", "previous_period", "same_period_last_year", "custom"];

export class IsolatedFinancialProfitLoss extends Component {
    static template = "baseer_financial_dashboard.ProfitLoss";
    static components = { ReportSelector, ReportExportButtons, Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({ loading: true, printing: false, error: "", journals: [], report: null,
            filters: this.emptyFilters(), expanded: {}, pages: {}, accountLoading: {} });
        this.appliedFilters = null;
        this.drill = useReportDrill("profit_loss", () => this.appliedFilters, () => this.lang);
        this.requestToken = 0;
        this.companyGeneration = 0;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.refreshActiveCompany());
        onWillStart(() => this.refreshActiveCompany());
    }

    emptyFilters() { return { company_id: 0, period: { kind: "month", anchor_date: "", direction: 0, date_from: "", date_to: "" }, comparison: { kind: "none", order: "descending", count: 1, date_from: "", date_to: "" }, journal_ids: [] }; }
    get labels() { return copy[this.lang]; }
    get dashboard() { return this.state.report?.dashboard || { cards: [], waterfall: [], revenue_accounts: [], notes: [] }; }
    get reportPeriods() { return this.state.report?.periods || []; }
    get primaryPeriod() { return this.reportPeriods.find((period) => period.role === "primary") || this.reportPeriods[0]; }
    get periodSummary() { return this.primaryPeriod ? this.reportPeriodCaption : this.periodKindLabel(this.state.filters.period.kind); }
    get activeCompanyId() { return Number(user.activeCompany?.id) || 0; }
    get reportPeriodCaption() {
        const period = this.primaryPeriod;
        if (!period) { return ""; }
        if (this.appliedFilters?.period.kind === "month") {
            const match = /^(\d{4})-(\d{2})-01$/.exec(period.date_from || "");
            if (!match || period.date_to !== `${match[1]}-${match[2]}-${String(new Date(Date.UTC(Number(match[1]), Number(match[2]), 0)).getUTCDate()).padStart(2, "0")}`) {
                return period.label || `${period.date_from} — ${period.date_to}`;
            }
        }
        return period.display_label || period.label || `${period.date_from} — ${period.date_to}`;
    }
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
    dashboardLabel(key) { return this.labels[key] || key; }
    dashboardValue(card) { return card?.value?.available === false ? this.labels.unavailable : (card?.value?.display || card?.value?.amount || ZERO.amount); }
    dashboardIcon(key) { return ({ income: "fa-line-chart", cost_of_sales: "fa-cubes", gross_profit: "fa-pie-chart", gross_margin: "fa-percent", expense: "fa-credit-card", net_income: "fa-trophy" })[key] || "fa-bar-chart"; }
    noteLabel(key) { return this.labels[key] || key; }
    rowClass(row) { return `o_baseer_pl_${row.kind || "detail"} o_baseer_pl_${row.key}`; }
    sectionLabel(key) { return this.labels[key] || key; }
    rowColspan() { return Math.max(2, this.reportPeriods.length + 1); }
    cloneFilters(direction = 0) {
        const { period, comparison } = this.state.filters;
        return { company_id: this.activeCompanyId, period: { ...period, direction }, comparison: { ...comparison }, journal_ids: [...this.state.filters.journal_ids] };
    }
    installContext(context) {
        this.state.journals = context.journals || [];
        const defaults = context.default_filters || {};
        const period = defaults.period || { kind: "month", anchor_date: context.default_date_to || "", date_from: context.default_date_from || "", date_to: context.default_date_to || "" };
        const comparison = defaults.comparison || { kind: "none", order: "descending" };
        Object.assign(this.state.filters, this.emptyFilters(), { company_id: defaults.company_id || context.default_company_id || 0, period: { ...this.emptyFilters().period, ...period, direction: 0 }, comparison: { ...this.emptyFilters().comparison, ...comparison }, journal_ids: [...(defaults.journal_ids || [])] });
    }
    invalidate() {
        this.requestToken += 1;
        this.state.loading = false;
        this.state.printing = false;
        this.state.report = null;
        this.state.error = "";
        this.state.expanded = {};
        this.state.pages = {};
        this.state.accountLoading = {};
        this.appliedFilters = null;
    }
    async refreshActiveCompany() {
        this.invalidate();
        const generation = ++this.companyGeneration;
        const companyId = this.activeCompanyId;
        this.state.filters.company_id = 0;
        this.state.journals = [];
        if (!companyId) { this.state.error = this.labels.error; return; }
        this.state.loading = true;
        try {
            const context = await this.orm.call(MODEL, "get_context", [companyId]);
            if (generation !== this.companyGeneration || companyId !== this.activeCompanyId) { return; }
            if (companyId && (context.default_company_id || context.default_filters?.company_id) !== companyId) {
                throw new Error("Active company mismatch");
            }
            this.installContext(context);
            await this.apply();
        } catch (error) {
            if (generation === this.companyGeneration) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (generation === this.companyGeneration) { this.state.loading = false; }
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
        this.state.filters.comparison.count = 1;
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
        const generation = this.companyGeneration;
        const companyId = this.activeCompanyId;
        this.state.loading = true;
        try {
            const response = await this.orm.call("baseer.financial.dashboard.report", "get_dashboard_report", [filters]);
            if (token === this.requestToken && generation === this.companyGeneration && companyId === this.activeCompanyId) {
                const report = this.legacyReport(response);
                this.state.report = report;
                if (report.period_controls?.anchor_date) { this.state.filters.period.anchor_date = report.period_controls.anchor_date; }
                this.state.filters.period.direction = 0;
                this.appliedFilters = {
                    ...filters,
                    period: { ...filters.period, direction: 0,
                        anchor_date: report.period_controls?.anchor_date || filters.period.anchor_date },
                    comparison: { ...filters.comparison }, journal_ids: [...filters.journal_ids],
                };
            }
        } catch (error) {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.loading = false; }
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
        const companyId = this.activeCompanyId;
        this.state.accountLoading[section] = true;
        try {
            const result = await this.orm.call(MODEL, "get_accounts", [this.appliedFilters, section, page]);
            if (token === this.requestToken && companyId === this.activeCompanyId) { this.state.pages[section] = result; }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.accountLoading[section] = false; }
        }
    }
    async openAccount(account, periodKey) {
        if (!this.appliedFilters) { return; }
        return this.drill.open({ kind: "account", account_id: account.id, period_key: periodKey });
    }

    async printReport() {
        if (!this.appliedFilters || !this.state.report || this.state.loading || this.state.printing) { return; }
        const token = this.requestToken;
        const generation = this.companyGeneration;
        const companyId = this.activeCompanyId;
        this.state.printing = true;
        try {
            const action = await this.orm.call(MODEL, "action_print", [{ ...this.appliedFilters, company_id: companyId }]);
            if (token === this.requestToken && generation === this.companyGeneration && companyId === this.activeCompanyId) {
                await this.env.services.action.doAction(action);
            }
        } catch (error) {
            if (token === this.requestToken && generation === this.companyGeneration) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.printing = false; }
        }
    }
}

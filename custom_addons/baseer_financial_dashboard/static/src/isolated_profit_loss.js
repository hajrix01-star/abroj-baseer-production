/** @odoo-module **/

import { BaseerProfitLossReport } from "@baseer_profit_loss_report/profit_loss";

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

const COMPARISON_KINDS = ["none", "previous_period", "same_period_last_year", "custom"];

export class IsolatedFinancialProfitLoss extends BaseerProfitLossReport {
    static template = "baseer_financial_dashboard.ProfitLoss";

    get labels() { return copy[this.lang]; }
    get dashboard() { return this.state.report?.dashboard || { cards: [], waterfall: [], revenue_accounts: [], notes: [] }; }
    dashboardLabel(key) { return this.labels[key] || key; }
    dashboardValue(card) { return card?.value?.available === false ? this.labels.unavailable : (card?.value?.display || card?.value?.amount || ZERO.amount); }
    dashboardIcon(key) { return ({ income: "fa-line-chart", cost_of_sales: "fa-cubes", gross_profit: "fa-pie-chart", gross_margin: "fa-percent", expense: "fa-credit-card", net_income: "fa-trophy" })[key] || "fa-bar-chart"; }
    noteLabel(key) { return this.labels[key] || key; }
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
}

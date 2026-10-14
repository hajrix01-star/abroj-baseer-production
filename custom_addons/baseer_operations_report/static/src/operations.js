/** @odoo-module **/

import { BaseerProfitLossReport } from "@baseer_profit_loss_report/profit_loss";
import { registry } from "@web/core/registry";

const MODEL = "baseer.operations.report";
const ACCOUNT_PAGE_SIZE = 50;
const ROWS = [
    "income", "cost_of_sales", "gross_profit", "expense",
    "net_operating_income", "other_income", "other_expense",
    "net_other_income", "net_income",
];
const SECTIONS = new Set(["income", "cost_of_sales", "expense", "other_income", "other_expense"]);
const labels = {
    ar: {
        title: "العمليات الإجمالية شاملة الضريبة", company: "الشركة", journals: "الدفاتر",
        allJournals: "جميع الدفاتر", selectedJournals: "الدفاتر المختارة",
        incomplete: "لا يمكن عرض أرقام هذه الفترة قبل التحقق من جميع مصادر الحركة.",
        unconfirmed: "ارتباط الدفعة بالفاتورة غير مؤكد تاريخيًا",
        unconfirmedCount: "ظهور دفعات مرتبطة غير مؤكدة عبر الفترات",
        excludedNativeCount: "حالات دفع مستبعدة عبر الفترات لعدم اكتمال الدليل",
        unprovenLiquidityCount: "خروج سيولة غير مثبت المصدر عبر الفترات",
        loading: "جارٍ تحميل المعاينة…", accountsLoading: "جارٍ تحميل الحسابات…",
        eventsLoading: "جارٍ تحميل الأحداث…", error: "تعذر عرض المعاينة. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        account: "الحساب", balance: "المبلغ", income: "الإيرادات", cost_of_sales: "تكلفة المبيعات",
        gross_profit: "إجمالي العمليات بعد تكلفة المبيعات", expense: "المصروفات",
        net_operating_income: "رصيد العمليات التشغيلية", other_income: "إيرادات أخرى",
        other_expense: "مصروفات أخرى", net_other_income: "رصيد العمليات الأخرى",
        net_income: "صافي العمليات", source: "عرض أحداث الحساب", previous: "السابق",
        next: "التالي", page: "صفحة", noAccounts: "لا توجد حسابات في هذا القسم.",
        noEvents: "لا توجد أحداث في هذه الصفحة.", date: "التاريخ", eventSource: "المصدر",
        back: "العودة للتقرير", period: "الفترة", comparison: "المقارنة", month: "شهر",
        quarter: "ربع سنة", fiscalYear: "سنة مالية", customDates: "تواريخ مخصصة",
        noComparison: "دون مقارنة", previousPeriods: "الفترات السابقة",
        samePeriodLastYear: "الفترة نفسها العام الماضي", periods: "فترات",
        periodOrder: "ترتيب الفترات", descending: "تنازلي", ascending: "تصاعدي",
        from: "من", to: "إلى", current: "الحالية",
    },
    en: {
        title: "Gross Operations Including VAT", company: "Company", journals: "Journals",
        allJournals: "All journals", selectedJournals: "Selected journals only",
        incomplete: "This period cannot show amounts until all movement sources are verified.",
        unconfirmed: "Historical payment-to-bill link unconfirmed",
        unconfirmedCount: "Unconfirmed payment occurrences across periods",
        excludedNativeCount: "Excluded payment cases across periods",
        unprovenLiquidityCount: "Cash outflows without proven source across periods",
        loading: "Loading preview…", accountsLoading: "Loading accounts…",
        eventsLoading: "Loading events…", error: "Could not load the preview. Check the period and access rights, then retry.",
        account: "Account", balance: "Amount", income: "Income", cost_of_sales: "Cost of sales",
        gross_profit: "Gross operations after cost of sales", expense: "Expenses",
        net_operating_income: "Operating balance", other_income: "Other income",
        other_expense: "Other expenses", net_other_income: "Other operations balance",
        net_income: "Net operations", source: "View account events", previous: "Previous",
        next: "Next", page: "Page", noAccounts: "No accounts in this section.",
        noEvents: "No events on this page.", date: "Date", eventSource: "Source",
        back: "Back to report", period: "Period", comparison: "Comparison", month: "Month",
        quarter: "Quarter", fiscalYear: "Fiscal year", customDates: "Custom dates",
        noComparison: "No comparison", previousPeriods: "Previous periods",
        samePeriodLastYear: "Same period last year", periods: "Periods",
        periodOrder: "Period order", descending: "Descending", ascending: "Ascending",
        from: "From", to: "To", current: "Current",
    },
};

// This adapter reshapes server amounts for the existing P&L table. It never
// derives, adds, subtracts, or reclassifies a financial value in the browser.
export function prepareOperationsSnapshot(snapshot, companyName, selectedJournals, translate) {
    if (typeof snapshot.complete !== "boolean") {
        throw new Error("Missing operations completeness state");
    }
    if (!Array.isArray(snapshot.periods) || !snapshot.periods.length) {
        throw new Error("Incomplete operations periods");
    }
    for (const period of snapshot.periods) {
        const keys = (period.rows || []).map((row) => row.key);
        if (keys.length !== ROWS.length || new Set(keys).size !== ROWS.length ||
            ROWS.some((key) => !keys.includes(key)) ||
            [...SECTIONS].some((section) => !Array.isArray(period.accounts?.[section]))) {
            throw new Error("Incomplete operations rows");
        }
    }
    const periods = (snapshot.periods || []).map((period) => ({
        ...period, role: period.key === "current" ? "primary" : "comparison",
        display_label: period.display_label || period.label,
    }));
    const rowsByKey = new Map(ROWS.map((key) => [key, {
        key, section: key, kind: SECTIONS.has(key) ? "section" : key === "net_income" ? "result" : "subtotal",
        label: translate[key], expandable: SECTIONS.has(key), amounts: {},
    }]));
    const accountsBySection = Object.fromEntries([...SECTIONS].map((key) => [key, new Map()]));
    for (const period of periods) {
        for (const row of period.rows || []) {
            const display = rowsByKey.get(row.key);
            if (display) {
                display.amounts[period.key] = { amount: row.amount, negative: row.negative };
            }
        }
        for (const [section, accounts] of Object.entries(period.accounts || {})) {
            const sectionMap = accountsBySection[section];
            if (!sectionMap) { continue; }
            for (const account of accounts) {
                let display = sectionMap.get(account.account_id);
                if (!display) {
                    display = { id: account.account_id, code: account.account_code,
                        name: account.account_name, amounts: {}, sourceCounts: {}, fingerprints: {}, channels: [] };
                    sectionMap.set(account.account_id, display);
                }
                display.amounts[period.key] = { amount: account.amount, negative: account.negative };
                display.sourceCounts[period.key] = account.source_count;
                display.fingerprints[period.key] = account.fingerprint;
                for (const channel of account.channels || []) {
                    let displayChannel = display.channels.find((item) => item.key === channel.key);
                    if (!displayChannel) {
                        displayChannel = { key: channel.key, name: channel.name, amounts: {} };
                        display.channels.push(displayChannel);
                    }
                    displayChannel.amounts[period.key] = { amount: channel.amount, negative: channel.negative };
                }
            }
        }
    }
    return {
        report: {
            complete: snapshot.complete === true,
            company: { name: companyName, currency_code: snapshot.currency_code },
            period_controls: snapshot.period_controls,
            periods, rows: ROWS.map((key) => rowsByKey.get(key)),
            is_partial_journals: selectedJournals,
        },
        accounts: Object.fromEntries(Object.entries(accountsBySection).map(([key, accounts]) => [
            key, [...accounts.values()].sort((a, b) => {
                const left = String(a.code || "");
                const right = String(b.code || "");
                return left < right ? -1 : left > right ? 1 : a.id - b.id;
            }),
        ])),
    };
}

export class BaseerOperationsPreview extends BaseerProfitLossReport {
    static template = "baseer_operations_report.Preview";

    setup() {
        super.setup();
        this.state.detail = null;
        this.state.incomplete = false;
        this.state.incompletePeriod = null;
        this.state.incompleteControls = null;
        this.snapshotAccounts = {};
        this.detailRequestToken = 0;
    }

    get labels() { return labels[this.lang]; }
    get periodSummary() { return this.state.incompletePeriod?.display_label || super.periodSummary; }
    get periodOptions() { return this.state.incompleteControls?.options || super.periodOptions; }
    get unconfirmedCount() {
        return this.reportPeriods.reduce((count, period) => count + (period.unconfirmed_count || 0), 0);
    }
    get excludedNativeCount() {
        return this.reportPeriods.reduce((count, period) => count +
            (period.excluded?.unsupported_native_payment || 0) +
            (period.excluded?.unassigned_native_payment || 0) +
            (period.excluded?.unsupported_native_bill || 0), 0);
    }
    get unprovenLiquidityCount() {
        return this.reportPeriods.reduce((count, period) => count +
            (period.excluded?.unproven_liquidity_outflow || 0), 0);
    }

    installContext(context) {
        super.installContext(context);
        this.companyName = (context.companies || []).find(
            (company) => company.id === this.activeCompanyId)?.name || "";
    }

    invalidate() {
        super.invalidate();
        this.state.detail = null;
        this.state.incomplete = false;
        this.state.incompletePeriod = null;
        this.state.incompleteControls = null;
        this.snapshotAccounts = {};
        this.detailRequestToken += 1;
    }

    async apply(direction = 0) {
        const filters = this.cloneFilters(direction);
        this.invalidate();
        const token = this.requestToken;
        const generation = this.companyGeneration;
        const companyId = this.activeCompanyId;
        this.state.loading = true;
        try {
            const snapshot = await this.orm.call(MODEL, "get_source_snapshot", [filters]);
            if (token !== this.requestToken || generation !== this.companyGeneration || companyId !== this.activeCompanyId) { return; }
            if (snapshot.company_id !== companyId || typeof snapshot.complete !== "boolean") { throw new Error("Unexpected source contract"); }
            if (snapshot.period_controls?.anchor_date) {
                this.state.filters.period.anchor_date = snapshot.period_controls.anchor_date;
            }
            this.state.filters.period.direction = 0;
            if (!snapshot.complete) {
                this.state.incomplete = true;
                this.state.incompleteControls = snapshot.period_controls || null;
                this.state.incompletePeriod = snapshot.periods?.find((period) => period.role === "primary") || snapshot.periods?.[0] || null;
                if (this.state.incompletePeriod) {
                    this.state.filters.period.date_from = this.state.incompletePeriod.date_from;
                    this.state.filters.period.date_to = this.state.incompletePeriod.date_to;
                }
                this.state.report = null;
                this.snapshotAccounts = {};
                this.appliedFilters = null;
                return;
            }
            const prepared = prepareOperationsSnapshot(snapshot, this.companyName || "",
                !!filters.journal_ids.length, this.labels);
            this.state.report = prepared.report;
            this.snapshotAccounts = prepared.accounts;
            this.appliedFilters = this.cloneFilters();
        } catch (error) {
            if (token === this.requestToken && generation === this.companyGeneration) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.loading = false; }
        }
    }

    async loadAccounts(section, page) {
        const accounts = this.snapshotAccounts[section] || [];
        if (!Number.isInteger(page) || page < 1) { return; }
        this.state.pages[section] = {
            accounts: accounts.slice((page - 1) * ACCOUNT_PAGE_SIZE, page * ACCOUNT_PAGE_SIZE),
            page, page_size: ACCOUNT_PAGE_SIZE, total_count: accounts.length,
        };
    }

    async openAccount(account, periodKey, section) {
        if (!this.appliedFilters || !account.sourceCounts[periodKey] || !account.fingerprints[periodKey]) { return; }
        const periodLabel = this.reportPeriods.find((period) => period.key === periodKey)?.label || periodKey;
        this.state.detail = { account, periodKey, periodLabel, section, page: 1,
            loading: false, error: "", result: null };
        await this.loadEventPage(1);
    }

    async loadEventPage(page) {
        const detail = this.state.detail;
        if (!detail || !Number.isInteger(page) || page < 1 || detail.loading) { return; }
        const token = ++this.detailRequestToken;
        const companyId = this.activeCompanyId;
        detail.loading = true;
        detail.error = "";
        try {
            const result = await this.orm.call(MODEL, "get_account_events", [
                this.appliedFilters, detail.section, detail.account.id, detail.periodKey,
                detail.account.fingerprints[detail.periodKey], page,
            ]);
            if (token === this.detailRequestToken && companyId === this.activeCompanyId && this.state.detail === detail) {
                detail.result = result;
                detail.page = page;
            }
        } catch (error) {
            if (token === this.detailRequestToken && this.state.detail === detail) {
                detail.error = error?.data?.message || this.labels.error;
            }
        } finally {
            if (token === this.detailRequestToken && this.state.detail === detail) { detail.loading = false; }
        }
    }

    closeDetail() {
        this.detailRequestToken += 1;
        this.state.detail = null;
    }

    async printReport() {
        if (!this.appliedFilters || !this.state.report?.complete || this.state.loading || this.state.printing) { return; }
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

registry.category("baseer_reports").add("operations_gross", {
    key: "operations_gross", label: { ar: "العمليات الإجمالية", en: "Gross Operations" },
    sequence: 45, kind: "component", component: BaseerOperationsPreview,
    groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"],
});

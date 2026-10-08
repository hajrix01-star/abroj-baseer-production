/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { ReportSelector } from "@baseer_reports_menu/report_selector";

const MODEL = "baseer.profit.loss.report";
const copy = {
    ar: {
        title: "الربح والخسارة", company: "الشركة", from: "من", to: "إلى",
        journals: "الدفاتر", allJournals: "جميع الدفاتر", selectedJournals: "نتيجة الدفاتر المختارة",
        posted: "قيود مرحلة · حسب التاريخ المحاسبي · ليست لقطة تاريخية مجمدة",
        apply: "عرض التقرير", loading: "جارٍ تحميل التقرير…", accountsLoading: "جارٍ تحميل الحسابات…",
        error: "تعذر عرض التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        noData: "لا توجد حركة مرحلة لهذه الفترة.", account: "الحساب", balance: "الرصيد",
        income: "الإيرادات", income_other: "إيرادات أخرى", expense_direct_cost: "تكلفة المبيعات",
        expense: "المصروفات", expense_other: "مصروفات أخرى", expense_depreciation: "الاستهلاك", gross: "إجمالي الربح",
        net: "صافي الربح", source: "عرض القيود", previous: "السابق", next: "التالي",
        page: "صفحة", of: "من", noAccounts: "لا توجد حسابات في هذا القسم.",
        date: "التاريخ", entry: "القيد", label: "البيان", debit: "مدين", credit: "دائن",
        linesLoading: "جارٍ تحميل القيود…", noLines: "لا توجد قيود لهذا الحساب في الفترة.",
    },
    en: {
        title: "Profit and Loss", company: "Company", from: "From", to: "To",
        journals: "Journals", allJournals: "All journals", selectedJournals: "Selected journals only",
        posted: "Posted entries · accounting date · not a frozen historical snapshot",
        apply: "Show report", loading: "Loading report…", accountsLoading: "Loading accounts…",
        error: "Could not load the report. Check the period and your access rights, then retry.",
        noData: "No posted activity was found for this period.", account: "Account", balance: "Balance",
        income: "Revenue", income_other: "Other income", expense_direct_cost: "Cost of sales",
        expense: "Expenses", expense_other: "Other expenses", expense_depreciation: "Depreciation", gross: "Gross profit",
        net: "Net profit", source: "View entries", previous: "Previous", next: "Next",
        page: "Page", of: "of", noAccounts: "No accounts in this section.",
        date: "Date", entry: "Entry", label: "Label", debit: "Debit", credit: "Credit",
        linesLoading: "Loading entries…", noLines: "No entries for this account in the period.",
    },
};

export class BaseerProfitLossReport extends Component {
    static template = "baseer_profit_loss_report.Report";
    static components = { ReportSelector };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({
            loading: true, error: "", companies: [], journals: [], report: null,
            filters: { company_id: 0, date_from: "", date_to: "", journal_ids: [] },
            expanded: {}, pages: {}, accountLoading: {}, expandedAccounts: {},
            linePages: {}, lineLoading: {}, lineOpening: {},
        });
        this.appliedFilters = null;
        this.requestToken = 0;
        onWillStart(async () => {
            try {
                const context = await this.orm.call(MODEL, "get_context", []);
                this.state.companies = context.companies;
                this.state.journals = context.journals;
                Object.assign(this.state.filters, {
                    company_id: context.default_company_id,
                    date_from: context.default_date_from,
                    date_to: context.default_date_to,
                });
                await this.apply();
            } catch (error) {
                this.state.error = error?.data?.message || this.labels.error;
                this.state.loading = false;
            }
        });
    }

    get labels() { return copy[this.lang]; }
    sectionLabel(key) { return this.labels[key] || key; }
    amountClass(negative, amount) {
        if (/^-?0(?:\.0+)?$/.test(String(amount).replace(/,/g, ""))) { return "is-zero"; }
        return negative ? "is-negative" : "";
    }
    invalidate() {
        this.requestToken += 1;
        this.state.loading = false;
        this.state.report = null;
        this.state.error = "";
        this.state.expanded = {};
        this.state.pages = {};
        this.state.expandedAccounts = {};
        this.state.linePages = {};
        this.state.lineOpening = {};
        this.appliedFilters = null;
    }
    async onCompanyChange(event) {
        const companyId = Number(event.target.value);
        this.state.filters.company_id = companyId;
        this.state.filters.journal_ids = [];
        this.state.journals = [];
        this.invalidate();
        const token = this.requestToken;
        try {
            const context = await this.orm.call(MODEL, "get_context", [companyId]);
            if (token === this.requestToken) { this.state.journals = context.journals; }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        }
    }
    onDateChange(event) {
        this.state.filters[event.target.name] = event.target.value;
        this.invalidate();
    }
    onJournalChange(event) {
        const id = Number(event.target.value);
        const next = new Set(this.state.filters.journal_ids);
        if (event.target.checked) { next.add(id); } else { next.delete(id); }
        this.state.filters.journal_ids = [...next];
        this.invalidate();
    }
    async apply() {
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
            const report = await this.orm.call(MODEL, "get_report", [filters]);
            if (token === this.requestToken) {
                this.appliedFilters = filters;
                this.state.report = report;
            }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.loading = false; }
        }
    }
    async toggleSection(key) {
        if (this.state.expanded[key]) {
            this.state.expanded[key] = false;
            return;
        }
        this.state.expanded[key] = true;
        if (!this.state.pages[key]) { await this.loadAccounts(key, 1); }
    }
    async loadAccounts(key, page) {
        if (!this.appliedFilters || this.state.accountLoading[key]) { return; }
        const token = this.requestToken;
        this.state.accountLoading[key] = true;
        try {
            const result = await this.orm.call(MODEL, "get_accounts", [this.appliedFilters, key, page]);
            if (token === this.requestToken) { this.state.pages[key] = result; }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.accountLoading[key] = false; }
        }
    }
    async toggleAccount(account) {
        const id = account.id;
        if (this.state.expandedAccounts[id]) {
            this.state.expandedAccounts[id] = false;
            return;
        }
        this.state.expandedAccounts[id] = true;
        if (!this.state.linePages[id]) { await this.loadLines(id, 1); }
    }
    async loadLines(accountId, page) {
        if (!this.appliedFilters || this.state.lineLoading[accountId]) { return; }
        const token = this.requestToken;
        this.state.lineLoading[accountId] = true;
        try {
            const result = await this.orm.call(MODEL, "get_lines", [this.appliedFilters, accountId, page]);
            if (token === this.requestToken) { this.state.linePages[accountId] = result; }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.lineLoading[accountId] = false; }
        }
    }
    async openLine(line) {
        if (!this.appliedFilters || this.state.lineOpening[line.id]) { return; }
        const token = this.requestToken;
        this.state.lineOpening[line.id] = true;
        try {
            const source = await this.orm.call(MODEL, "get_source_line", [this.appliedFilters, line.id]);
            if (token !== this.requestToken || source.line_id !== line.id) { return; }
            await this.action.doAction({
                type: "ir.actions.act_window", name: this.labels.source,
                res_model: "account.move.line", views: [[false, "list"], [false, "form"]],
                target: "current", domain: [["id", "=", source.line_id]],
            });
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.lineOpening[line.id] = false; }
        }
    }
}

registry.category("baseer_reports").add("profit_loss", {
    key: "profit_loss",
    label: { ar: "الربح والخسارة", en: "Profit and Loss" },
    sequence: 40,
    kind: "component",
    component: BaseerProfitLossReport,
    groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"],
});

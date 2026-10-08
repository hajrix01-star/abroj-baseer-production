/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { ReportSelector } from "@baseer_reports_menu/report_selector";

const MODEL = "baseer.general.ledger.report";
const copy = {
    ar: {
        title: "دفتر الأستاذ العام", company: "الشركة", from: "من", to: "إلى",
        journals: "الدفاتر", allJournals: "جميع الدفاتر", partial: "نتيجة الدفاتر المختارة فقط",
        posted: "قيود مرحلة · حسب التاريخ المحاسبي · ليست لقطة تاريخية مجمدة",
        apply: "عرض التقرير", loading: "جارٍ تحميل التقرير…", error: "تعذر عرض التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        account: "الحساب", opening: "الرصيد الافتتاحي", debit: "مدين", credit: "دائن", closing: "الرصيد الختامي",
        rbf: "نتيجة مرحلة من السنة السابقة", rbfSources: "مصادر نتيجة السنوات السابقة", total: "إجمالي دفتر الأستاذ",
        date: "التاريخ", entry: "القيد", label: "البيان", running: "الرصيد الجاري",
        source: "عرض القيد", openingSource: "عرض مصدر الرصيد الافتتاحي", linesLoading: "جارٍ تحميل القيود…", accountsLoading: "جارٍ تحميل الحسابات…",
        noAccounts: "لا توجد حسابات ذات حركة لهذه الفترة.", noLines: "لا توجد قيود في هذا القسم.",
        more: "تحميل المزيد", previous: "السابق", next: "التالي", page: "صفحة", of: "من",
    },
    en: {
        title: "General Ledger", company: "Company", from: "From", to: "To",
        journals: "Journals", allJournals: "All journals", partial: "Selected journals only",
        posted: "Posted entries · accounting date · not a frozen historical snapshot",
        apply: "Show report", loading: "Loading report…", error: "Could not load the report. Check the period and your access rights, then retry.",
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
            loading: true, error: "", companies: [], journals: [], report: null,
            filters: { company_id: 0, date_from: "", date_to: "", journal_ids: [] },
            rbfOpen: false, rbfLoading: false, rbfAccounts: null,
            accountOpening: {},
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
    amountClass(negative, amount) {
        if (/^-?0(?:\.0+)?$/.test(String(amount).replace(/,/g, ""))) { return "is-zero"; }
        return negative ? "is-negative" : "";
    }
    lineKey(accountId, scope) { return `${scope}:${accountId}`; }
    invalidate() {
        this.requestToken++;
        this.appliedFilters = null;
        this.state.loading = false;
        this.state.report = null;
        this.state.error = "";
        this.state.rbfOpen = false;
        this.state.rbfLoading = false;
        this.state.rbfAccounts = null;
        this.state.accountOpening = {};
    }
    async onCompanyChange(event) {
        const id = Number(event.target.value);
        this.state.filters.company_id = id;
        this.state.filters.journal_ids = [];
        this.state.journals = [];
        this.invalidate();
        const token = this.requestToken;
        try {
            const context = await this.orm.call(MODEL, "get_context", [id]);
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
        const selected = new Set(this.state.filters.journal_ids);
        if (event.target.checked) { selected.add(id); } else { selected.delete(id); }
        this.state.filters.journal_ids = [...selected];
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
            const report = await this.orm.call(MODEL, "get_report", [filters, 1]);
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
    async loadAccounts(page) {
        if (!this.appliedFilters || this.state.loading) { return; }
        const token = this.requestToken;
        this.state.loading = true;
        try {
            const report = await this.orm.call(MODEL, "get_report", [this.appliedFilters, page]);
            if (token === this.requestToken) {
                this.state.report = report;
                this.state.accountOpening = {};
            }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.loading = false; }
        }
    }
    async toggleRbf() {
        this.state.rbfOpen = !this.state.rbfOpen;
        if (this.state.rbfOpen && !this.state.rbfAccounts) { await this.loadRbfAccounts(1); }
    }
    async loadRbfAccounts(page) {
        if (!this.appliedFilters || this.state.rbfLoading) { return; }
        const token = this.requestToken;
        this.state.rbfLoading = true;
        try {
            const rows = await this.orm.call(MODEL, "get_rbf_accounts", [this.appliedFilters, page]);
            if (token === this.requestToken) {
                this.state.rbfAccounts = rows;
                this.state.accountOpening = {};
            }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.rbfLoading = false; }
        }
    }
    async openAccount(accountId, scope) {
        const key = this.lineKey(accountId, scope);
        if (!this.appliedFilters || this.state.accountOpening[key]) { return; }
        const token = this.requestToken;
        this.state.accountOpening[key] = true;
        try {
            const action = await this.orm.call(MODEL, "get_account_action", [
                this.appliedFilters, accountId, scope,
            ]);
            if (token === this.requestToken) { await this.action.doAction(action); }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.accountOpening[key] = false; }
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

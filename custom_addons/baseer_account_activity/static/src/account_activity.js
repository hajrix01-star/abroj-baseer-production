/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { ReportSelector } from "@baseer_reports_menu/report_selector";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { user, userBus } from "@web/core/user";

const copy = {
    ar: {
        title: "حركة حساب", scope: "قيود مرحلة · شركة واحدة · سنة مالية واحدة",
        company: "الشركة", account: "الحساب", period: "الفترة", month: "الشهر السابق",
        quarter: "الربع السابق", custom: "فترة مخصصة", from: "من", to: "إلى",
        apply: "عرض التقرير", opening: "الرصيد الافتتاحي", debit: "مدين",
        credit: "دائن", closing: "الرصيد الختامي", date: "التاريخ", entry: "القيد",
        label: "البيان", running: "الرصيد الجاري", empty: "لا توجد قيود مرحلة في هذه الفترة.",
        choose: "اختر الحساب ثم اعرض التقرير.", next: "التالي", previous: "السابق",
        page: "صفحة", loadError: "تعذر تحميل التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        noAccounts: "لا توجد حسابات متاحة لهذه الشركة.", source: "افتح القيد الأصلي",
        backToReports: "تقارير بصير", periodTotals: "ملخص الفترة كاملة",
    },
    en: {
        title: "Account Activity", scope: "Posted entries · one company · one fiscal year",
        company: "Company", account: "Account", period: "Period", month: "Previous month",
        quarter: "Previous quarter", custom: "Custom dates", from: "From", to: "To",
        apply: "View report", opening: "Opening balance", debit: "Debit",
        credit: "Credit", closing: "Closing balance", date: "Date", entry: "Journal entry",
        label: "Label", running: "Running balance", empty: "No posted entries in this period.",
        choose: "Choose an account, then view the report.", next: "Next", previous: "Previous",
        page: "Page", loadError: "Could not load the report. Check the dates and access, then retry.",
        noAccounts: "No accounts available for this company.", source: "Open source entry",
        backToReports: "Baseer Reports", periodTotals: "Full-period summary",
    },
};

function dateString(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function completedPeriod(kind) {
    const today = new Date();
    const year = today.getFullYear();
    const month = today.getMonth();
    if (kind === "quarter") {
        const startMonth = Math.floor(month / 3) * 3 - 3;
        return [dateString(new Date(year, startMonth, 1)), dateString(new Date(year, startMonth + 3, 0))];
    }
    return [dateString(new Date(year, month - 1, 1)), dateString(new Date(year, month, 0))];
}

export class AccountActivity extends Component {
    static components = { ReportSelector };
    static template = "baseer_account_activity.Report";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.requestEpoch = 0;
        this.accountEpoch = 0;
        this.companyGeneration = 0;
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        const [dateFrom, dateTo] = completedPeriod("month");
        this.state = useState({
            accounts: [], companyId: 0, accountId: 0, accountsLoading: false,
            period: "month", dateFrom, dateTo, data: null, loading: false,
            error: "", cursors: [null], page: 0, appliedPeriod: null,
        });
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.loadOptions());
        onWillStart(() => this.loadOptions());
    }

    get labels() { return copy[this.lang]; }
    get activeCompanyId() { return Number(user.activeCompany?.id) || 0; }
    get periodCaption() {
        const period = this.state.appliedPeriod;
        if (!period) { return ""; }
        const match = /^(\d{4})-(\d{2})-01$/.exec(period.dateFrom);
        if (period.kind === "month" && match &&
            period.dateTo === `${match[1]}-${match[2]}-${String(new Date(Date.UTC(Number(match[1]), Number(match[2]), 0)).getUTCDate()).padStart(2, "0")}`) {
            return new Intl.DateTimeFormat(this.lang === "ar" ? "ar-SA-u-ca-gregory-nu-latn" : "en-US", {
                month: "long", year: "numeric", timeZone: "UTC",
            }).format(new Date(`${period.dateFrom}T00:00:00Z`));
        }
        return `${period.dateFrom} — ${period.dateTo}`;
    }

    goToReports() { return this.action.doAction("baseer_reports_menu.action_baseer_reports_hub"); }

    invalidateReport() {
        this.requestEpoch += 1;
        this.state.data = null;
        this.state.loading = false;
        this.state.cursors = [null];
        this.state.page = 0;
        this.state.appliedPeriod = null;
    }

    async loadOptions() {
        const generation = ++this.companyGeneration;
        this.accountEpoch += 1;
        this.invalidateReport();
        this.state.accounts = [];
        this.state.accountId = 0;
        this.state.companyId = this.activeCompanyId;
        this.state.error = "";
        if (!this.state.companyId) {
            this.state.error = this.labels.loadError;
            return;
        }
        try {
            await this.loadAccounts();
        } catch (error) {
            if (generation === this.companyGeneration) { this.state.error = this.labels.loadError; }
        }
    }

    async loadAccounts() {
        const companyId = this.state.companyId;
        const epoch = ++this.accountEpoch;
        const generation = this.companyGeneration;
        this.state.accounts = [];
        this.state.accountId = 0;
        this.state.accountsLoading = true;
        this.invalidateReport();
        try {
            const accounts = await this.orm.searchRead(
                "account.account", [["company_ids", "in", companyId]],
                ["display_name", "code"], { order: "code, id" }
            );
            if (epoch !== this.accountEpoch || generation !== this.companyGeneration ||
                companyId !== this.state.companyId || companyId !== this.activeCompanyId) { return; }
            this.state.accounts = accounts;
            this.state.accountId = accounts[0]?.id || 0;
        } finally {
            if (epoch === this.accountEpoch) { this.state.accountsLoading = false; }
        }
    }

    onAccountChange(event) {
        this.state.accountId = Number(event.target.value);
        this.invalidateReport();
    }

    onPeriodChange(event) {
        this.state.period = event.target.value;
        if (this.state.period !== "custom") {
            [this.state.dateFrom, this.state.dateTo] = completedPeriod(this.state.period);
        }
        this.invalidateReport();
    }

    onDateChange(event) {
        this.state[event.target.name] = event.target.value;
        this.state.period = "custom";
        this.invalidateReport();
    }

    async loadPage(page = 0) {
        if (this.state.accountsLoading || !this.state.companyId || this.state.companyId !== this.activeCompanyId ||
            !this.state.accountId || !this.state.dateFrom || !this.state.dateTo) { return; }
        const epoch = ++this.requestEpoch;
        const generation = this.companyGeneration;
        const companyId = this.state.companyId;
        const accountId = this.state.accountId;
        const dateFrom = this.state.dateFrom;
        const dateTo = this.state.dateTo;
        const cursor = this.state.cursors[page];
        this.state.loading = true;
        this.state.error = "";
        try {
            const data = await this.orm.call("baseer.account.activity", "get_activity", [
                companyId, accountId, dateFrom, dateTo,
                cursor?.date || null, cursor?.id || null,
            ]);
            if (epoch !== this.requestEpoch || generation !== this.companyGeneration ||
                companyId !== this.activeCompanyId || companyId !== this.state.companyId ||
                accountId !== this.state.accountId || dateFrom !== this.state.dateFrom ||
                dateTo !== this.state.dateTo) { return; }
            this.state.data = data;
            this.state.appliedPeriod = { kind: this.state.period, dateFrom, dateTo };
            this.state.page = page;
            if (data.next_cursor) { this.state.cursors[page + 1] = data.next_cursor; }
            else { this.state.cursors.splice(page + 1); }
        } catch (error) {
            if (epoch !== this.requestEpoch || generation !== this.companyGeneration) { return; }
            this.state.data = null;
            this.state.error = error?.data?.message || error?.message || this.labels.loadError;
        } finally {
            if (epoch === this.requestEpoch && generation === this.companyGeneration) { this.state.loading = false; }
        }
    }

    async apply() {
        this.state.cursors = [null];
        await this.loadPage(0);
    }

    openMove(line) {
        this.action.doAction({
            type: "ir.actions.act_window", name: this.labels.entry,
            res_model: "account.move", res_id: line.move_id,
            views: [[false, "form"]], target: "current",
        });
    }

    formatAmount(text) {
        const raw = String(text ?? "0");
        const sign = raw.startsWith("-") ? "−" : "";
        const [whole, fraction] = raw.replace(/^-/, "").split(".");
        const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        return `${sign}${grouped}${fraction === undefined ? "" : "." + fraction}`;
    }

    amountClass(text) {
        if (String(text).startsWith("-")) { return "is-negative"; }
        return /^0(?:\.0+)?$/.test(String(text)) ? "is-zero" : "";
    }
}

registry.category("actions").add("baseer_account_activity", AccountActivity);
registry.category("baseer_reports").add("activity", {
    key: "activity",
    label: { ar: "حركة حساب", en: "Account Activity" },
    sequence: 30,
    kind: "component",
    component: AccountActivity,
    groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"],
});

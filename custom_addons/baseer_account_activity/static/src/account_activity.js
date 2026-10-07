/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

const copy = {
    ar: {
        title: "حركة حساب", scope: "قيود مرحلة · شركة واحدة · سنة مالية واحدة",
        company: "الشركة", account: "الحساب", period: "الفترة", month: "الشهر السابق",
        quarter: "الربع السابق", custom: "فترة مخصصة", from: "من", to: "إلى",
        apply: "عرض التقرير", opening: "الرصيد الافتتاحي", debit: "مدين",
        credit: "دائن", closing: "الرصيد الختامي", date: "التاريخ", entry: "القيد",
        label: "البيان", running: "الرصيد الجاري", empty: "لا توجد قيود مرحلة في هذه الفترة.",
        choose: "اختر الشركة والحساب ثم اعرض التقرير.", next: "التالي", previous: "السابق",
        page: "صفحة", loadError: "تعذر تحميل التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        noAccounts: "لا توجد حسابات متاحة لهذه الشركة.", source: "افتح القيد الأصلي",
        chooseReport: "اختر تقريرًا من تقارير بصير", periodTotals: "ملخص الفترة كاملة",
    },
    en: {
        title: "Account Activity", scope: "Posted entries · one company · one fiscal year",
        company: "Company", account: "Account", period: "Period", month: "Previous month",
        quarter: "Previous quarter", custom: "Custom dates", from: "From", to: "To",
        apply: "View report", opening: "Opening balance", debit: "Debit",
        credit: "Credit", closing: "Closing balance", date: "Date", entry: "Journal entry",
        label: "Label", running: "Running balance", empty: "No posted entries in this period.",
        choose: "Choose a company and account, then view the report.", next: "Next", previous: "Previous",
        page: "Page", loadError: "Could not load the report. Check the dates and access, then retry.",
        noAccounts: "No accounts available for this company.", source: "Open source entry",
        chooseReport: "Choose a Baseer report", periodTotals: "Full-period summary",
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
    static template = "baseer_account_activity.Report";
    static components = { Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.menu = useService("menu");
        this.requestEpoch = 0;
        this.accountEpoch = 0;
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        const [dateFrom, dateTo] = completedPeriod("month");
        this.state = useState({
            companies: [], accounts: [], companyId: 0, accountId: 0, accountsLoading: false,
            period: "month", dateFrom, dateTo, data: null, loading: false,
            error: "", cursors: [null], page: 0,
        });
        onWillStart(() => this.loadOptions());
    }

    get labels() { return copy[this.lang]; }

    get reportOptions() {
        const app = this.menu.getApps().find((item) => item.xmlid === "baseer_reports_menu.menu_baseer_reports");
        if (!app) { return []; }
        const options = [];
        const visit = (item) => {
            if (item.actionID && item.xmlid !== "baseer_report_ui_preview.menu_report_ui_preview") {
                options.push(item);
            }
            for (const child of item.childrenTree || []) { visit(child); }
        };
        visit(this.menu.getMenuAsTree(app.id));
        return options;
    }

    openReport(option) {
        if (option.xmlid !== "baseer_account_activity.menu_account_activity") {
            this.menu.selectMenu(option);
        }
    }

    invalidateReport() {
        this.requestEpoch += 1;
        this.state.data = null;
        this.state.loading = false;
        this.state.cursors = [null];
        this.state.page = 0;
    }

    async loadOptions() {
        try {
            const allowed = user.context?.allowed_company_ids || [];
            if (!allowed.length) {
                this.state.error = this.labels.loadError;
                return;
            }
            this.state.companies = await this.orm.searchRead(
                "res.company", [["id", "in", allowed]], ["name"], { order: "name, id" }
            );
            if (this.state.companies.length) {
                this.state.companyId = this.state.companies.find((company) => company.id === allowed[0])?.id || this.state.companies[0].id;
                await this.loadAccounts();
            }
        } catch (error) {
            this.state.error = this.labels.loadError;
        }
    }

    async loadAccounts() {
        const companyId = this.state.companyId;
        const epoch = ++this.accountEpoch;
        this.state.accounts = [];
        this.state.accountId = 0;
        this.state.accountsLoading = true;
        this.invalidateReport();
        try {
            const accounts = await this.orm.searchRead(
                "account.account", [["company_ids", "in", companyId]],
                ["display_name", "code"], { order: "code, id" }
            );
            if (epoch !== this.accountEpoch || companyId !== this.state.companyId) { return; }
            this.state.accounts = accounts;
            this.state.accountId = accounts[0]?.id || 0;
        } finally {
            if (epoch === this.accountEpoch) { this.state.accountsLoading = false; }
        }
    }

    async onCompanyChange(event) {
        this.state.companyId = Number(event.target.value);
        const requestedEpoch = this.accountEpoch + 1;
        this.state.error = "";
        try { await this.loadAccounts(); }
        catch (error) {
            if (requestedEpoch === this.accountEpoch) { this.state.error = this.labels.loadError; }
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
        if (this.state.accountsLoading || !this.state.companyId || !this.state.accountId || !this.state.dateFrom || !this.state.dateTo) { return; }
        const epoch = ++this.requestEpoch;
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
            if (epoch !== this.requestEpoch || companyId !== this.state.companyId ||
                accountId !== this.state.accountId || dateFrom !== this.state.dateFrom ||
                dateTo !== this.state.dateTo) { return; }
            this.state.data = data;
            this.state.page = page;
            if (data.next_cursor) { this.state.cursors[page + 1] = data.next_cursor; }
            else { this.state.cursors.splice(page + 1); }
        } catch (error) {
            if (epoch !== this.requestEpoch) { return; }
            this.state.data = null;
            this.state.error = error?.data?.message || error?.message || this.labels.loadError;
        } finally {
            if (epoch === this.requestEpoch) { this.state.loading = false; }
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

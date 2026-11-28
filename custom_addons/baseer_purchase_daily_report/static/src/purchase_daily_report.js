/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { detectPreset, rangeForPreset } from "./date_range";

const MODEL = "baseer.purchase.daily.report";
const PAGE_SIZE = 50;
const PRESETS = ["today", "yesterday", "this_month", "last_month"];

export class PurchaseDailyReport extends Component {
    static template = "baseer_purchase_daily_report.Report";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const initial = rangeForPreset("this_month");
        this.requestId = 0;
        this.state = useState({
            from: initial.from,
            to: initial.to,
            preset: "this_month",
            payment: "all",
            method: "all",
            applied: null,
            payload: null,
            loading: true,
            error: "",
            expanded: null,
            dayData: null,
            dayLoading: false,
            dayError: "",
            invoice: null,
            invoiceLoading: false,
            invoiceError: "",
            exporting: false,
            exportError: "",
        });
        onWillStart(() => this.applyFilters());
        onWillUnmount(() => { this.requestId++; });
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.applyFilters());
    }

    get labels() {
        return {
            title: _t("Daily purchases"),
            subtitle: _t("Posted supplier bills, grouped by invoice date"),
            from: _t("From"), to: _t("To"), payment: _t("Payment status"),
            all: _t("All statuses"), not_paid: _t("Unpaid"), partial: _t("Partially paid"),
            in_payment: _t("In payment"), paid: _t("Paid"), reversed: _t("Reversed"),
            blocked: _t("Blocked"), invoicing_legacy: _t("Legacy"),
            draft: _t("Draft"), drafts: _t("Drafts"),
            apply: _t("Show"), loading: _t("Loading purchases…"),
            error: _t("We could not load this report. Please try again."), retry: _t("Try again"),
            empty: _t("No purchases found for these filters."), emptyHint: _t("Try another date range or payment status."),
            dateNote: _t("Grouped by invoice date · Payment status is current"),
            total: _t("Total"), paidAmount: _t("Paid amount"), residual: _t("Outstanding"),
            paidUnavailable: _t("Unavailable"), paidPending: _t("Pending payment excluded"),
            documents: _t("documents"), show: _t("Show transactions"), hide: _t("Hide transactions"),
            invoice: _t("Supplier bill"), refund: _t("Supplier credit note"),
            vendor: _t("Supplier"), reference: _t("Reference"), date: _t("Invoice date"),
            enteredBy: _t("Entered by"), batchEntry: _t("Batch line creator"), invoiceEntry: _t("Invoice creator"),
            due: _t("Due date"), details: _t("Invoice details"), back: _t("Back to report"),
            open: _t("View details"), beforeTax: _t("Before tax"), tax: _t("Tax"),
            items: _t("Items"), quantity: _t("Quantity"), unitPrice: _t("Unit price"), discount: _t("Discount"),
            subtotal: _t("Subtotal"), itemTotal: _t("Total including tax"),
            noItems: _t("No invoice items."), adjustments: _t("Adjustments and rounding"), previous: _t("Previous"), next: _t("Next"),
            page: _t("Page"), companyCurrency: _t("Company currency"), activeCompany: _t("Active company"),
            amountCurrency: _t("Original invoice currency"),
            paidNote: _t("Confirmed payments allocated to these invoices are shown. Other settlements can reduce the outstanding amount."),
            paidUnavailableNote: _t("An amount is unavailable when the cash payment cannot be verified, including some foreign currency payments."),
            liveNote: _t("The default view shows posted bills. Use Drafts to include unposted bills."),
            today: _t("Today"), yesterday: _t("Yesterday"),
            thisMonth: _t("This month"), lastMonth: _t("Last month"),
            datePresets: _t("Date presets"),
            paymentMethods: _t("Payment methods"), statusFilters: _t("Status filters"),
            documentsShort: _t("documents"),
            custody: _t("Representative custody"), custodyIn: _t("Custody in"),
            custodyOut: _t("Spent from custody"), custodyRemaining: _t("Remaining"),
            custodySince: _t("Since"), custodyBalanceNow: _t("Current balance"),
            custodyOpen: _t("Open the custody screen"),
            tableDate: _t("Date"), currencyNote: _t("Amounts in"),
            purchaseTotal: _t("Total"), custodyTransfer: _t("Transferred to custody"),
            tableTotals: _t("Totals"),
            transferNote: _t("Custody transfers are shown for reference and are not part of the purchase total."),
            totalPurchases: _t("Total purchases"), invoices: _t("bills"),
            custodyBalance: _t("Custody balance"), custodyBalanceCol: _t("Custody balance"),
            paymentStatus: _t("Payment status"), allPaid: _t("All bills are paid"),
            noOpenBills: _t("No unpaid or draft bills"),
            byDay: _t("Purchases by day"), purchases: _t("Purchases"), custodyGroup: _t("Custody fund"),
            invoiceCount: _t("Bills"), invoiceCountShort: _t("Bills"),
            dateBasis: _t("Date = invoice date · Balance counted from"),
            exportPdf: _t("Export PDF"),
            exportExcel: _t("Export Excel"),
            exporting: _t("Preparing the file…"),
            exportError: _t("We could not export this report. Please try again."),
        };
    }

    get presetLabels() {
        return {
            today: this.labels.today,
            yesterday: this.labels.yesterday,
            this_month: this.labels.thisMonth,
            last_month: this.labels.lastMonth,
        };
    }

    get presets() {
        return PRESETS;
    }

    statusLabel(status) { return this.labels[status] || status || "—"; }
    statusCardLabel(card) {
        const labels = { not_paid: this.labels.not_paid, draft: this.labels.drafts };
        return labels[card.key] || card.label;
    }
    kindLabel(kind) { return kind === "in_refund" ? this.labels.refund : this.labels.invoice; }
    errorMessage(error) {
        const known = ["odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError"];
        return (known.includes(error?.data?.name) && error.data.message) || this.labels.error;
    }

    syncDates(from, to, extra = {}) {
        this.state.from = from;
        this.state.to = to;
        this.state.preset = extra.preset || detectPreset(from, to);
    }

    applyPreset(preset) {
        const range = rangeForPreset(preset);
        this.syncDates(range.from, range.to, { preset });
        return this.applyFilters();
    }

    onFromToChanged() {
        this.syncDates(this.state.from, this.state.to);
    }

    toggleMethod(key) {
        this.state.method = this.state.method === key ? "all" : key;
        return this.applyFilters();
    }

    toggleStatus(key) {
        this.state.payment = this.state.payment === key ? "all" : key;
        return this.applyFilters();
    }

    onPaymentChanged() {
        return this.applyFilters();
    }

    isMethodActive(key) { return this.state.applied?.method === key; }
    isStatusActive(key) { return this.state.applied?.payment === key; }
    isPresetActive(preset) { return this.state.preset === preset; }

    async applyFilters() {
        const request = ++this.requestId;
        const applied = {
            from: this.state.from,
            to: this.state.to,
            payment: this.state.payment,
            method: this.state.method,
        };
        this.state.loading = true;
        this.state.error = "";
        this.state.expanded = null;
        this.state.dayData = null;
        this.state.invoice = null;
        this.state.invoiceLoading = false;
        this.state.invoiceError = "";
        try {
            const result = await this.orm.call(MODEL, "get_days", [applied.from, applied.to, applied.payment, applied.method]);
            if (request !== this.requestId) { return; }
            this.state.payload = result;
            this.state.applied = applied;
        } catch (error) {
            if (request !== this.requestId) { return; }
            this.state.payload = null;
            this.state.error = this.errorMessage(error);
        } finally {
            if (request === this.requestId) { this.state.loading = false; }
        }
    }

    async toggleDay(day) {
        if (this.state.expanded === day) {
            this.requestId++;
            this.state.expanded = null;
            this.state.dayData = null;
            this.state.dayLoading = false;
            return;
        }
        this.state.expanded = day;
        this.state.dayData = null;
        await this.loadDay(0);
    }

    async loadDay(offset) {
        const request = ++this.requestId;
        const day = this.state.expanded;
        this.state.dayLoading = true;
        this.state.dayError = "";
        try {
            const result = await this.orm.call(MODEL, "get_day", [day, this.state.applied.payment, offset, this.state.applied.method]);
            if (request === this.requestId) { this.state.dayData = result; }
        } catch (error) {
            if (request === this.requestId) { this.state.dayError = this.errorMessage(error); }
        } finally {
            if (request === this.requestId) { this.state.dayLoading = false; }
        }
    }

    async openInvoice(id) {
        const request = ++this.requestId;
        this.state.invoiceLoading = true;
        this.state.invoiceError = "";
        this.state.invoice = null;
        try {
            const invoice = await this.orm.call(MODEL, "get_invoice", [id]);
            if (request === this.requestId) { this.state.invoice = invoice; }
        } catch (error) {
            if (request === this.requestId) { this.state.invoiceError = this.errorMessage(error); }
        } finally {
            if (request === this.requestId) { this.state.invoiceLoading = false; }
        }
    }

    backToReport() {
        this.requestId++;
        this.state.invoice = null;
        this.state.invoiceError = "";
        this.state.invoiceLoading = false;
    }

    async openCustody() {
        if (!this.state.payload?.custody?.can_open) { return; }
        const action = await this.orm.call(MODEL, "open_custody_screen", []);
        return this.action.doAction(action);
    }

    get purchaseColspan() {
        return 3 + (this.state.payload?.table?.columns.length || 0);
    }

    get billRowspan() {
        const data = this.state.dayData;
        return (data?.rows.length || 0) + (data && (data.offset || data.has_more) ? 1 : 0);
    }

    get splitParts() {
        const table = this.state.payload?.table;
        if (!table) { return []; }
        const number = (value) => Number(String(value || "0").replace(/,/g, "")) || 0;
        const total = table.columns.reduce((sum, column) => sum + Math.max(number(table.totals[column.key]), 0), 0);
        return table.columns
            .filter((column) => number(table.totals[column.key]))
            .map((column) => ({
                key: column.key, label: column.label, amount: table.totals[column.key],
                width: total ? (Math.max(number(table.totals[column.key]), 0) / total * 100).toFixed(2) : 0,
            }));
    }

    get allSettled() {
        return (this.state.payload?.statuses || []).every((card) => !card.count);
    }

    get spentPercentLabel() {
        return _t("Spent %s%% of the transferred amount", this.state.payload?.custody?.spent_percent || 0);
    }

    async exportPdf() {
        return this.exportReport("action_export_pdf");
    }

    async exportXlsx() {
        return this.exportReport("action_export_xlsx");
    }

    async exportReport(methodName) {
        if (!this.state.applied || this.state.exporting) { return; }
        this.state.exporting = true;
        this.state.exportError = "";
        try {
            const action = await this.orm.call(MODEL, methodName, [
                this.state.applied.from,
                this.state.applied.to,
                this.state.applied.payment,
                this.state.applied.method,
            ]);
            if (action) {
                return this.action.doAction(action);
            }
        } catch (error) {
            this.state.exportError = this.errorMessage(error);
        } finally {
            this.state.exporting = false;
        }
    }

    shortDate(value) { return (value || "").slice(5); }
    shortNumber(value) { return (value || "").split("/").pop(); }

    tableAmount(row, key) {
        return (row.amounts && row.amounts[key]) || "";
    }

    previousPage() { return this.loadDay(Math.max(0, this.state.dayData.offset - PAGE_SIZE)); }
    nextPage() { return this.loadDay(this.state.dayData.offset + PAGE_SIZE); }
    get pageNumber() { return String(Math.floor((this.state.dayData?.offset || 0) / PAGE_SIZE) + 1); }
}

registry.category("actions").add("baseer_purchase_daily_report.action", PurchaseDailyReport);

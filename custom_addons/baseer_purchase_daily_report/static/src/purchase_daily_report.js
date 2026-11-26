/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { detectPreset, monthValue, rangeForDay, rangeForMonth, rangeForPreset, riyadhYmd } from "./date_range";

const MODEL = "baseer.purchase.daily.report";
const PAGE_SIZE = 50;
const PRESETS = ["today", "yesterday", "this_week", "this_month", "last_month"];

export class PurchaseDailyReport extends Component {
    static template = "baseer_purchase_daily_report.Report";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        const initial = rangeForPreset("this_month");
        this.requestId = 0;
        this.state = useState({
            from: initial.from,
            to: initial.to,
            day: initial.day,
            month: initial.month,
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
        });
        onWillStart(() => this.applyFilters());
        onWillUnmount(() => { this.requestId++; });
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.applyFilters());
    }

    get labels() {
        return {
            eyebrow: _t("PURCHASE INSIGHTS"), title: _t("Daily purchases"),
            subtitle: _t("Every supplier bill, organized by day."),
            from: _t("From"), to: _t("To"), payment: _t("Payment status"),
            all: _t("All statuses"), not_paid: _t("Unpaid"), partial: _t("Partially paid"),
            in_payment: _t("In payment"), paid: _t("Paid"), reversed: _t("Reversed"),
            blocked: _t("Blocked"), invoicing_legacy: _t("Legacy"),
            draft: _t("Draft"), drafts: _t("Drafts"), unapproved: _t("Unapproved"),
            apply: _t("Show purchases"), loading: _t("Loading purchases…"),
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
            liveNote: _t("Posted supplier bills and credit notes only."),
            today: _t("Today"), yesterday: _t("Yesterday"), thisWeek: _t("This week"),
            thisMonth: _t("This month"), lastMonth: _t("Last month"),
            pickDay: _t("Day"), pickMonth: _t("Month"),
            paymentMethods: _t("Payment methods"), statusFilters: _t("Status filters"),
            documentsShort: _t("documents"),
        };
    }

    get presetLabels() {
        return {
            today: this.labels.today,
            yesterday: this.labels.yesterday,
            this_week: this.labels.thisWeek,
            this_month: this.labels.thisMonth,
            last_month: this.labels.lastMonth,
        };
    }

    get presets() {
        return PRESETS;
    }

    statusLabel(status) { return this.labels[status] || status || "—"; }
    kindLabel(kind) { return kind === "in_refund" ? this.labels.refund : this.labels.invoice; }
    errorMessage(error) {
        const known = ["odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError"];
        return (known.includes(error?.data?.name) && error.data.message) || this.labels.error;
    }

    syncDates(from, to, extra = {}) {
        const today = riyadhYmd();
        this.state.from = from;
        this.state.to = to;
        this.state.preset = extra.preset || detectPreset(from, to);
        this.state.day = extra.day || (from === to ? from : today.iso);
        this.state.month = extra.month || (from && from.slice(0, 7)) || monthValue(today.year, today.month);
    }

    applyPreset(preset) {
        const range = rangeForPreset(preset);
        this.syncDates(range.from, range.to, { preset, day: range.day, month: range.month });
        return this.applyFilters();
    }

    onDayPicked(event) {
        const iso = event.target.value;
        if (!iso) { return; }
        const range = rangeForDay(iso);
        this.syncDates(range.from, range.to, { preset: detectPreset(range.from, range.to), day: iso });
        return this.applyFilters();
    }

    onMonthPicked(event) {
        const value = event.target.value;
        if (!value) { return; }
        const range = rangeForMonth(value);
        this.syncDates(range.from, range.to, { preset: detectPreset(range.from, range.to), month: value });
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

    previousPage() { return this.loadDay(Math.max(0, this.state.dayData.offset - PAGE_SIZE)); }
    nextPage() { return this.loadDay(this.state.dayData.offset + PAGE_SIZE); }
    get pageNumber() { return String(Math.floor((this.state.dayData?.offset || 0) / PAGE_SIZE) + 1); }
}

registry.category("actions").add("baseer_purchase_daily_report.action", PurchaseDailyReport);

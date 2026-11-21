/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";

const MODEL = "baseer.purchase.daily.report";
const PAGE_SIZE = 50;

function localDate(date) {
    return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

export class PurchaseDailyReport extends Component {
    static template = "baseer_purchase_daily_report.Report";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        const now = new Date();
        this.requestId = 0;
        this.state = useState({
            from: localDate(new Date(now.getFullYear(), now.getMonth(), 1)),
            to: localDate(now),
            payment: "all",
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
        };
    }

    statusLabel(status) { return this.labels[status] || status || "—"; }
    kindLabel(kind) { return kind === "in_refund" ? this.labels.refund : this.labels.invoice; }
    errorMessage(error) {
        const known = ["odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError"];
        return (known.includes(error?.data?.name) && error.data.message) || this.labels.error;
    }

    async applyFilters() {
        const request = ++this.requestId;
        const applied = { from: this.state.from, to: this.state.to, payment: this.state.payment };
        this.state.loading = true;
        this.state.error = "";
        this.state.expanded = null;
        this.state.dayData = null;
        this.state.invoice = null;
        this.state.invoiceLoading = false;
        this.state.invoiceError = "";
        try {
            const result = await this.orm.call(MODEL, "get_days", [applied.from, applied.to, applied.payment]);
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
            const result = await this.orm.call(MODEL, "get_day", [day, this.state.applied.payment, offset]);
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

/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Pager } from "@web/core/pager/pager";
import { DateTimeInput } from "@web/core/datetime/datetime_input";

const { DateTime } = luxon;

export class CancellationFollowupReport extends Component {
    static template = "baseer_pos_cancellation_report.Report";
    static components = { Pager, DateTimeInput };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.sequence = 0;
        this.disposed = false;
        this.state = useState({
            loading: true, error: "", payload: null, sessions: {},
            filters: {
                preset: "today", day: "", month: "", date_from: "", date_to: "",
                morning_start: "06:00", evening_start: "18:00", pos_config_id: "",
                cashier_id: "", shift: "all", event_type: "all", review_only: false,
                offset: 0, limit: 50, group_offset: 0, group_limit: 50,
            },
        });
        onWillStart(() => this.load());
        onWillUnmount(() => { this.disposed = true; this.sequence++; });
    }

    get labels() {
        return {
            title: _t("Cancellation follow-up report"),
            subtitle: _t("Substitutions, documented cancellations and cases to review"),
            period: _t("Period"), today: _t("Today"), day: _t("Day"), month: _t("Month"),
            custom: _t("Date and time range"), from: _t("From"), to: _t("To (exclusive)"),
            morning: _t("Morning starts"), evening: _t("Evening starts"),
            register: _t("Point of sale"), cashier: _t("Cashier"), all: _t("All"),
            shift: _t("Shift"), morningShift: _t("Morning"), eveningShift: _t("Evening"),
            type: _t("Operation"), substitution: _t("Substitution"),
            itemCancel: _t("Item cancellation"), orderCancel: _t("Order cancellation"),
            reduce: _t("Quantity reduction"), reviewOnly: _t("Cases to review only"),
            show: _t("Show report"), loading: _t("Loading report…"), retry: _t("Try again"),
            timezone: _t("Report timezone"), reasons: _t("Cancellation reasons"),
            shiftDistribution: _t("Operations by shift"),
            reasonBasis: _t("Documented cancellation operations grouped by reason"),
            timeline: _t("Operations over the selected period"),
            cashiers: _t("By cashier"), registers: _t("By point of sale"),
            substitutions: _t("Substitutions"), cancellations: _t("Cancellations"),
            reviews: _t("Cases to review"), details: _t("Operation details"),
            noData: _t("No documented operations match this period and these filters."),
            noReasons: _t("No documented cancellations in this selection."),
            noGroups: _t("No operations in this selection."),
            time: _t("Date and time"), order: _t("Order"), product: _t("Original item / replacements"),
            quantity: _t("Recorded quantity"), reason: _t("Reason"), indicator: _t("Review indicator"),
            source: _t("View record"), sourceUnavailable: _t("Source record unavailable"),
            reviewNote: _t("Substitution followed by cancellation is a review indicator; it does not establish misconduct."),
            totalNote: _t("Totals cover the full selection. Details are paginated."),
            shiftNote: _t("Morning runs until evening starts. Evening runs until the next morning."),
            selectedFilters: _t("Report filters"),
            sessions: _t("Sessions"), operations: _t("Documented operations"),
            sessionNote: _t("Totals cover the full selection. Open a session to see its operations."),
            groupPages: _t("Sessions and their details are paginated."),
            sessionError: _t("The session details could not be loaded. Please try again."),
            metricLabels: { substitution: _t("Substitutions"), cancellation: _t("Cancellations"), reduction: _t("Quantity reduction") },
            metricOperations: _t("Operations"), metricQuantity: _t("Quantity"),
            knownAmount: _t("Recorded amount including tax"), noAmount: _t("Amount not recorded"),
            noOperations: _t("No operations"), unpricedRows: _t("Audit rows without an amount"),
            unknownQuantity: _t("Audit rows without a quantity"),
            amountNote: _t("Substitution amounts refer to the original items. Amounts include tax and recorded discounts; currencies are kept separate. These categories are not a combined loss total."),
        };
    }

    get fromValue() { return this.parseDate(this.state.filters.date_from); }
    get toValue() { return this.parseDate(this.state.filters.date_to); }
    parseDate(value) {
        if (!value) { return false; }
        const date = DateTime.fromISO(value, { zone: this.state.payload?.filters.timezone || "local" });
        return date.isValid ? date.reconfigure({ numberingSystem: "latn" }) : false;
    }
    setDate(key, value) {
        this.state.filters[key] = value ? value.reconfigure({ numberingSystem: "latn" }).toFormat("yyyy-MM-dd'T'HH:mm") : "";
    }

    async load(reset = false, appliedFilters = null) {
        const request = ++this.sequence;
        if (reset) { this.state.filters.offset = 0; this.state.filters.group_offset = 0; }
        const inputSnapshot = JSON.stringify(this.state.filters);
        const filters = { ...(appliedFilters || this.state.filters) };
        for (const key of ["pos_config_id", "cashier_id"]) {
            filters[key] = filters[key] ? Number(filters[key]) : false;
        }
        this.lastRequestFilters = { ...filters };
        this.state.loading = true;
        this.state.error = "";
        this.state.sessions = {};
        try {
            const payload = await this.orm.call("baseer.pos.cancellation.report", "get_report", [filters]);
            if (this.disposed || request !== this.sequence) { return; }
            this.state.payload = payload;
            if (!appliedFilters && JSON.stringify(this.state.filters) === inputSnapshot) {
                Object.assign(this.state.filters, payload.filters);
                // Preserve edits made while a request was in flight.
                this.state.filters.pos_config_id = String(payload.filters.pos_config_id || "");
                this.state.filters.cashier_id = String(payload.filters.cashier_id || "");
            }
        } catch (error) {
            if (this.disposed || request !== this.sequence) { return; }
            const businessError = ["odoo.exceptions.AccessError", "odoo.exceptions.ValidationError"].includes(error.data?.name);
            this.state.error = businessError ? error.data.message : _t("The report could not be loaded. Please try again.");
        } finally {
            if (!this.disposed && request === this.sequence) { this.state.loading = false; }
        }
    }

    async updatePage({ offset, limit }) {
        // Pagination belongs to the displayed selection; leave unapplied edits intact.
        const filters = { ...this.state.payload.filters, offset, limit };
        await this.load(false, filters);
    }

    async updateGroupPage({ offset, limit }) {
        await this.load(false, { ...this.state.payload.filters, preset: "custom", group_offset: offset, group_limit: limit });
    }

    async toggleSession(group) {
        const current = this.state.sessions[group.key];
        if (current?.expanded) { current.expanded = false; return; }
        // Only one session page is retained; switching groups bounds memory and cancels stale replies.
        this.state.sessions = {
            [group.key]: current || { expanded: false, loading: false, error: "", payload: null, request: 0 },
        };
        const entry = this.state.sessions[group.key];
        entry.expanded = true;
        if (!entry.payload && !entry.loading) { await this.loadSession(group); }
    }

    async loadSession(group, offset = 0, limit = 50) {
        const entry = this.state.sessions[group.key];
        if (!entry) { return; }
        const generation = this.sequence;
        const request = ++entry.request;
        entry.loading = true;
        entry.error = "";
        entry.lastPage = { offset, limit };
        const identity = { date: group.date, company_id: group.company_id,
            pos_config_id: group.pos_config_id, session_id: group.session_id };
        try {
            const payload = await this.orm.call("baseer.pos.cancellation.report", "get_session_details",
                [{ ...this.state.payload.filters, preset: "custom" }, identity, offset, limit]);
            if (this.disposed || generation !== this.sequence || this.state.sessions[group.key] !== entry || request !== entry.request) { return; }
            entry.payload = payload;
        } catch (error) {
            if (this.disposed || generation !== this.sequence || this.state.sessions[group.key] !== entry || request !== entry.request) { return; }
            const businessError = ["odoo.exceptions.AccessError", "odoo.exceptions.ValidationError"].includes(error.data?.name);
            entry.error = businessError ? error.data.message : this.labels.sessionError;
        } finally {
            if (!this.disposed && generation === this.sequence && this.state.sessions[group.key] === entry && request === entry.request) { entry.loading = false; }
        }
    }

    updateSessionPage(group, { offset, limit }) { return this.loadSession(group, offset, limit); }
    retrySession(group) { return this.loadSession(group, this.state.sessions[group.key].lastPage.offset, this.state.sessions[group.key].lastPage.limit); }

    retry() {
        return this.load(false, this.lastRequestFilters);
    }

    openSource(row) {
        if (!row.source_record_id || !row.source_model) { return; }
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: row.source_model,
            res_id: row.source_record_id, views: [[false, "form"]], target: "current",
            context: { create: false, edit: false, delete: false },
        });
    }
}

registry.category("actions").add("baseer_pos_cancellation_report", CancellationFollowupReport);

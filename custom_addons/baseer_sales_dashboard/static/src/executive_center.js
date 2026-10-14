import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Presentation only. Money, comparisons, periods and coverage belong to the server.
export class BaseerExecutiveCenter extends Component {
    static template = "baseer_sales_dashboard.ExecutiveCenter";
    static props = { dashboardId: Number };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ companies: [], selected: [], cards: [], loading: true, error: "", loaded: 0, point: null,
            preset: "last_complete_day", dateFrom: "", dateTo: "", period: null, sessionLoading: {}, sessionErrors: {}, daySessions: {}, activeCompany: null });
        this.generation = 0;
        onWillStart(() => { this.initialize(); });
        onWillUnmount(() => { this.disposed = true; this.generation++; });
    }

    get labels() {
        return {
            title: _t("Command center"), subtitle: _t("Point of Sale · net sales including tax"),
            companies: _t("Choose companies"), all: _t("All companies"), clear: _t("Clear selection"),
            refresh: _t("Refresh"), loading: _t("Loading companies"), retry: _t("Try again"),
            empty: _t("Choose a company to display its executive overview."),
            noCompanies: _t("No authorized companies are available."),
            unavailable: _t("No Point of Sale sales are recorded in this period."), unsupportedCurrency: _t("This overview supports SAR only"),
            daily: _t("Last selected session opening day's sales"), change: _t("Change from previous closed session day"), chart: _t("Sales trend"),
            noData: _t("Unavailable"), snapshotNote: _t("All confirmed sales belong to their session opening date in Riyadh time, including sales after midnight. Refunds belong to their own session. This is not an accounting cutoff."),
            period: _t("Period"), from: _t("From session opening date"), to: _t("To session opening date"), apply: _t("Apply filters"),
            lastComplete: _t("Yesterday"), currentDay: _t("Today"), thisMonth: _t("This month · through today"),
            lastMonth: _t("Previous month"), last30: _t("Last 30 days · through today"), custom: _t("Custom period"),
            current: _t("Contributing sessions still open"), ended: _t("Contributing sessions closed · not an accounting approval"), selected: _t("By session opening date · Riyadh time"),
            total: _t("Period net sales including tax"), orders: _t("Paid orders including refunds"), sessions: _t("Sessions with sales in this period"),
            latestSale: _t("Latest recorded POS sale · Riyadh time"), sessionDetails: _t("Sales by session within selected period"),
            openingDay: _t("Session opening day"),
            noSessions: _t("No sessions are recorded in this period."), next: _t("Next page"), previousPage: _t("Previous page"),
            page: _t("Page"), sessionError: _t("Unable to load session details. Please try again."),
            sales: _t("Net sales including tax"), customers: _t("Customers"), saleOrders: _t("Sales orders"),
            averageOrder: _t("Average per order"), averageCustomer: _t("Average per customer"),
            days: _t("Daily sessions"), cancelledOrders: _t("Cancelled orders"), itemCancellations: _t("Cancelled items"),
            substitutions: _t("Product substitutions"), allSessions: _t("Sessions"), loadingSessions: _t("Loading sessions"),
        };
    }

    async initialize() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const result = await this.orm.call("spreadsheet.dashboard", "get_baseer_executive_companies", [[this.props.dashboardId]]);
            if (this.disposed) return;
            this.state.companies = result.companies;
            this.storageKey = `baseer.executive.companies:${result.db}:${result.user_id}`;
            let saved;
            try { saved = JSON.parse(localStorage.getItem(this.storageKey)); } catch { /* Storage can be blocked. */ }
            const allowed = new Set(result.companies.map((company) => company.id));
            this.state.selected = Array.isArray(saved) ? [...new Set(saved.filter((id) => allowed.has(id)))] : result.companies.slice(0, 3).map((company) => company.id);
            await this.loadCards();
        } catch {
            if (!this.disposed) { this.state.error = _t("Unable to load the executive overview. Please try again."); this.state.loading = false; }
        }
    }

    async loadCards() {
        const generation = ++this.generation;
        this.state.loading = true;
        this.state.error = "";
        this.state.cards = [];
        this.state.loaded = 0;
        this.state.point = null;
        this.state.period = null;
        this.state.sessionLoading = {};
        this.state.sessionErrors = {};
        this.state.daySessions = {};
        const ids = [...this.state.selected];
        const filters = this.filters();
        try {
            // Bound each request, while allowing every authorized company to be displayed.
            for (let offset = 0; offset < ids.length; offset += 3) {
                const result = await this.orm.call("spreadsheet.dashboard", "get_baseer_executive_cards", [[this.props.dashboardId], ids.slice(offset, offset + 3)], filters);
                if (this.disposed || generation !== this.generation) return;
                this.state.cards.push(...result.cards);
                if (!this.state.cards.some((card) => card.company.id === this.state.activeCompany)) this.state.activeCompany = this.state.cards[0]?.company.id || null;
                this.state.period = result.period;
                this.state.loaded = Math.min(offset + 3, ids.length);
            }
        } catch (error) {
            if (!this.disposed && generation === this.generation) this.state.error = this.errorMessage(error);
        } finally {
            if (!this.disposed && generation === this.generation) this.state.loading = false;
        }
    }

    filters() {
        return { period: this.state.preset, date_from: this.state.preset === "custom" ? this.state.dateFrom : null,
            date_to: this.state.preset === "custom" ? this.state.dateTo : null };
    }
    errorMessage(error) {
        if (error?.data?.name === "odoo.exceptions.ValidationError" && typeof error.data.message === "string") return error.data.message;
        return _t("Some companies could not be loaded. Please try again.");
    }
    applyFilters(event) {
        event?.preventDefault();
        if (this.state.preset === "custom" && (!this.state.dateFrom || !this.state.dateTo)) {
            this.generation++;
            this.state.cards = []; this.state.period = null; this.state.loading = false;
            this.state.error = _t("Choose both session opening dates for the custom period.");
            return;
        }
        this.loadCards();
    }
    dayKey(card, day) { return `${card.company.id}:${day.date}`; }
    sessionsFor(card, day) { return this.state.daySessions[this.dayKey(card, day)]; }
    async onDayToggle(event, card, day) {
        if (event.target.open && !this.sessionsFor(card, day)) await this.loadSessionPage(card, day, 1);
    }
    async loadSessionPage(card, day, page) {
        const id = card.company.id;
        const key = this.dayKey(card, day);
        if (this.state.sessionLoading[key]) return;
        const generation = this.generation;
        this.state.sessionLoading[key] = true; this.state.sessionErrors[key] = "";
        // Displayed period, not unapplied form edits.
        const filters = { period: "custom", date_from: day.date, date_to: day.date, page };
        try {
            const result = await this.orm.call("spreadsheet.dashboard", "get_baseer_executive_sessions", [[this.props.dashboardId], id], filters);
            if (this.disposed || generation !== this.generation) return;
            this.state.daySessions[key] = result;
        } catch {
            if (!this.disposed && generation === this.generation) this.state.sessionErrors[key] = this.labels.sessionError;
        } finally {
            if (!this.disposed && generation === this.generation) this.state.sessionLoading[key] = false;
        }
    }

    selectCompany(id, event) {
        this.state.selected = event.target.checked ? [...new Set([...this.state.selected, id])] : this.state.selected.filter((value) => value !== id);
        this.selectionChanged();
    }
    selectAll() { this.state.selected = this.state.companies.map((company) => company.id); this.selectionChanged(); }
    clearSelection() { this.state.selected = []; this.selectionChanged(); }
    selectionChanged() {
        try { localStorage.setItem(this.storageKey, JSON.stringify(this.state.selected)); } catch { /* Selection still works without storage. */ }
        this.loadCards();
    }
    metrics(card) {
        return [
            { key: "orders", label: this.labels.saleOrders, value: card.sale_order_count },
            { key: "customers", label: this.labels.customers, value: card.customer_count?.display || "—" },
            { key: "averageOrder", label: this.labels.averageOrder, value: card.average_order?.display || "—" },
            { key: "averageCustomer", label: this.labels.averageCustomer, value: card.average_customer?.display || "—" },
        ];
    }
    activateCompany(id) { this.state.activeCompany = id; this.state.point = null; }
    get activeCards() { return this.state.cards.filter((card) => card.company.id === this.state.activeCompany); }
    counterDisplay(counter) { return counter?.available ? counter.display : this.labels.noData; }
    barStyle(point) {
        return `height:${point.bar_height || "0"}%;`;
    }
    pointKey(card, point) { return `${card.company.id}:${point.date}`; }
    togglePoint(card, point) { const key = this.pointKey(card, point); this.state.point = this.state.point === key ? null : key; }
    onPointKeydown(event) { if (event.key === "Escape") this.state.point = null; }
    pointLabel(point) { return `${point.date}: ${point.display} · ${this.pointStatus(point)} · ${point.change.display}`; }
    pointStatus(point) {
        return { complete: this.labels.ended, current: this.labels.current, incomplete: this.labels.current,
            missing: _t("No recorded POS sales"), no_orders: _t("No recorded POS sales") }[point.status] || this.labels.noData;
    }
    periodStatus(period) { return { complete: this.labels.ended, current: this.labels.current, selected: this.labels.selected }[period?.status] || this.labels.noData; }
    sessionStatus(state) { return { opening_control: _t("Opening"), opened: _t("Open"), closing_control: _t("Closing"), closed: _t("Closed") }[state] || this.labels.noData; }
    arrow(direction) { return direction === "up" ? "↑" : direction === "down" ? "↓" : "→"; }
}

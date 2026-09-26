import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Presentation only. Money, comparisons, periods and coverage belong to the server.
export class BaseerExecutiveCenter extends Component {
    static template = "baseer_sales_dashboard.ExecutiveCenter";
    static props = { dashboardId: Number };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ companies: [], selected: [], cards: [], loading: true, error: "", loaded: 0, point: null });
        this.generation = 0;
        onWillStart(() => { this.initialize(); });
        onWillUnmount(() => { this.disposed = true; this.generation++; });
    }

    get labels() {
        return {
            title: _t("Command center"), subtitle: _t("Executive overview · approved sales summaries"),
            companies: _t("Choose companies"), all: _t("All companies"), clear: _t("Clear selection"),
            refresh: _t("Refresh"), loading: _t("Loading companies"), retry: _t("Try again"),
            empty: _t("Choose a company to display its executive overview."),
            noCompanies: _t("No authorized companies are available."),
            unavailable: _t("No completed approved sales day is available."),
            unsupportedCurrency: _t("Sales summaries support SAR only"),
            lastDay: _t("Last completed day"), daily: _t("Daily sales"), change: _t("Daily change"),
            chart: _t("Daily sales · last 14 days"), mtd: _t("Month to date"), average: _t("Daily average"),
            forecast: _t("Month-end forecast (estimated)"), previous: _t("Compared with equal previous period"),
            customers: _t("Average registered customers per operating day"), channels: _t("Payment channels · month to date"),
            coverage: _t("Completed operating days"), closed: _t("Closed days"), missing: _t("Missing days"),
            incomplete: _t("Incomplete days"), noPayments: _t("No payment channel data available."),
            noData: _t("Unavailable"), zero: _t("Recorded zero"), partial: _t("Partial month: forecast unavailable"),
            paymentIncomplete: _t("Some approved summaries have missing or inconsistent payment allocations. The breakdown is partial and percentages are unavailable."),
            snapshotNote: _t("Snapshots through each company's last completed day."),
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
        const ids = [...this.state.selected];
        try {
            // Bound each request, while allowing every authorized company to be displayed.
            for (let offset = 0; offset < ids.length; offset += 3) {
                const result = await this.orm.call("spreadsheet.dashboard", "get_baseer_executive_cards", [[this.props.dashboardId], ids.slice(offset, offset + 3)]);
                if (this.disposed || generation !== this.generation) return;
                this.state.cards.push(...result.cards);
                this.state.loaded = Math.min(offset + 3, ids.length);
            }
        } catch {
            if (!this.disposed && generation === this.generation) this.state.error = _t("Some companies could not be loaded. Please try again.");
        } finally {
            if (!this.disposed && generation === this.generation) this.state.loading = false;
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
            { key: "mtd", label: this.labels.mtd, value: card.month_to_date.display },
            { key: "average", label: this.labels.average, value: card.daily_average.display },
            { key: "forecast", label: this.labels.forecast, value: card.forecast.display },
            { key: "previous", label: this.labels.previous, value: card.period_change.display, detail: card.previous_period ? `${card.previous_period.from} — ${card.previous_period.to}` : "" },
            { key: "customers", label: this.labels.customers, value: card.customer_average.display },
        ];
    }
    barStyle(point, timeline) {
        // Coordinates only; never derive business totals or ratios on the client.
        const maximum = Math.max(1, ...timeline.map((item) => Number(item.value) || 0));
        const height = point.value === null ? 0 : Math.max(0, Number(point.value) || 0) / maximum * 100;
        return `height:${height}%;`;
    }
    pointKey(card, point) { return `${card.company.id}:${point.date}`; }
    togglePoint(card, point) { const key = this.pointKey(card, point); this.state.point = this.state.point === key ? null : key; }
    onPointKeydown(event) { if (event.key === "Escape") this.state.point = null; }
    pointLabel(point) { return `${point.date}: ${point.display} · ${this.pointStatus(point)} · ${point.change.display}`; }
    pointStatus(point) {
        return { complete: _t("Complete"), closed: _t("Closed"), incomplete: _t("Partial"), missing: _t("Not recorded") }[point.status] || this.labels.noData;
    }
    arrow(direction) { return direction === "up" ? "↑" : direction === "down" ? "↓" : "→"; }
}

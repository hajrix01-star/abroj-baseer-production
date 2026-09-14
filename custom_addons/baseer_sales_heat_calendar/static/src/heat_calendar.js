import { Component, onMounted, onWillStart, onWillUnmount, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const monthShift = (value, shift) => {
    const [year, month] = value.split("-").map(Number);
    const next = new Date(Date.UTC(year, month - 1 + shift, 1));
    return `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, "0")}`;
};

export class HeatDayDetails extends Component {
    static template = "baseer_sales_heat_calendar.HeatDayDetails";
    static props = {
        day: Object,
        currency: String,
        labels: Object,
        openSources: Function,
        close: Function,
        restoreFocus: Function,
    };

    setup() {
        this.detailsPanel = useRef("detailsPanel");
        this.closeButton = useRef("closeButton");
        this._handleKeydown = this._handleKeydown.bind(this);
        onMounted(() => {
            this.closeButton.el?.focus({ preventScroll: true });
            document.addEventListener("keydown", this._handleKeydown);
        });
        onWillUnmount(() => {
            document.removeEventListener("keydown", this._handleKeydown);
            this.props.restoreFocus();
        });
    }

    _focusableElements() {
        if (!this.detailsPanel.el) {
            return [];
        }
        return [...this.detailsPanel.el.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )].filter((element) => element.tabIndex >= 0);
    }

    _handleKeydown(event) {
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            this.props.close();
            return;
        }
        if (event.key !== "Tab") {
            return;
        }
        const focusable = this._focusableElements();
        if (!focusable.length) {
            event.preventDefault();
            return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const activeElement = document.activeElement;
        if (event.shiftKey && (activeElement === first || !this.detailsPanel.el.contains(activeElement))) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && (activeElement === last || !this.detailsPanel.el.contains(activeElement))) {
            event.preventDefault();
            first.focus();
        }
    }

    get basisLabel() {
        return this.props.labels[`basis_${this.props.day.basis_kind}`];
    }
}

export class BaseerHeatCalendar extends Component {
    static template = "baseer_sales_heat_calendar.HeatCalendar";
    static props = { dashboardId: Number };
    static components = { HeatDayDetails };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            month: null,
            loading: false,
            error: "",
            payload: null,
            selectedDay: null,
        });
        this._openedDayButton = null;
        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (nextProps.dashboardId !== this.props.dashboardId) {
                this.state.payload = null;
                this.load(nextProps.dashboardId);
            }
        });
        this.labels = {
            title: _t("Heat calendar"),
            subtitle: _t("Approved daily sales summaries, including VAT"),
            previous: _t("Previous month"),
            next: _t("Next month"),
            refresh: _t("Refresh"),
            loading: _t("Loading the heat calendar…"),
            retry: _t("Retry"),
            details: _t("Day details"),
            status: _t("Operating status"),
            performance: _t("Performance"),
            source: _t("Open approved sales summaries"),
            sourceLink: _t("Source"),
            approvedShifts: _t("Approved shifts"),
            manage: _t("Manage occasions"),
            targets: _t("Manage targets"),
            feed: _t("Feed Saudi occasions"),
            feedHelp: _t("Adds fixed official holidays and clearly labelled Eid estimates. Confirm published dates before relying on them."),
            close: _t("Close"),
            empty: _t("No sales summary has been approved for this day."),
            partial: _t("The day is not evaluated until its operating status is complete."),
            noOccasion: _t("No occasion"),
        };
    }

    async load(dashboardId = this.props.dashboardId, allowWhileLoading = false) {
        if (this.state.loading && !allowWhileLoading) {
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.payload = await this.orm.call("spreadsheet.dashboard", "get_baseer_heat_calendar", [
                [dashboardId], this.state.month,
            ]);
            this.state.month = this.state.payload.month;
            this.state.selectedDay = null;
        } catch (error) {
            this.state.error = error?.message || _t("The heat calendar could not be loaded.");
        } finally {
            this.state.loading = false;
        }
    }

    changeMonth(shift) {
        if (this.state.loading) {
            return;
        }
        this.state.month = monthShift(this.state.month, shift);
        this.load();
    }

    openDay(day, event) {
        this._openedDayButton = event.currentTarget;
        this.state.selectedDay = day;
    }

    closeDay() {
        this.state.selectedDay = null;
    }

    restoreDayFocus() {
        const opener = this._openedDayButton;
        this._openedDayButton = null;
        if (opener?.isConnected) {
            requestAnimationFrame(() => opener.focus({ preventScroll: true }));
        }
    }

    get detailLabels() {
        return {
            ...this.state.payload.labels,
            status: this.labels.status,
            performance: this.labels.performance,
            source: this.labels.source,
            source_link: this.labels.sourceLink,
            approved_shifts: this.labels.approvedShifts,
            close: this.labels.close,
            partial: this.labels.partial,
        };
    }

    openSources(action) {
        if (action) {
            this.action.doAction(action);
        }
    }

    manageOccasions() {
        this.action.doAction("baseer_sales_heat_calendar.action_baseer_official_occasion", { onClose: () => this.load() });
    }

    manageTargets() {
        this.action.doAction("baseer_sales_heat_calendar.action_baseer_heat_calendar_target", { onClose: () => this.load() });
    }

    async feedFixedHolidays() {
        if (this.state.loading) {
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        try {
            await this.orm.call("baseer.official.occasion", "action_seed_saudi_fixed_holidays", []);
            await this.load(this.props.dashboardId, true);
        } catch (error) {
            this.state.error = error?.message || _t("Official occasions could not be fed.");
        } finally {
            this.state.loading = false;
        }
    }
}

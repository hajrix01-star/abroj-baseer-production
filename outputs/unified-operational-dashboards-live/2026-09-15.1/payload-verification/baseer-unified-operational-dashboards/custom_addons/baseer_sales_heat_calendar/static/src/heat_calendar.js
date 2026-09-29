import { Component, onMounted, onWillStart, onWillUnmount, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
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

const TARGET_MONTHS = [
    [1, _t("January")], [2, _t("February")], [3, _t("March")], [4, _t("April")],
    [5, _t("May")], [6, _t("June")], [7, _t("July")], [8, _t("August")],
    [9, _t("September")], [10, _t("October")], [11, _t("November")], [12, _t("December")],
];

const TARGET_WEEKDAYS = [
    [0, _t("Monday")], [1, _t("Tuesday")], [2, _t("Wednesday")], [3, _t("Thursday")],
    [4, _t("Friday")], [5, _t("Saturday")], [6, _t("Sunday")],
];

const targetCellKey = (month, weekday) => `${month}:${weekday}`;

/**
 * A deliberately small, client-side matrix editor.  The server owns all target
 * validation and writes; this component only holds unsaved input as raw strings.
 */
export class HeatTargetBatchDialog extends Component {
    static template = "baseer_sales_heat_calendar.HeatTargetBatchDialog";
    static components = { Dialog };
    static props = {
        initialYear: Number,
        initialMonth: Number,
        close: Function,
        onSaved: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        const currentYear = Number(this.props.initialYear);
        this._initialMonth = Number(this.props.initialMonth);
        this.state = useState({
            company: null,
            year: currentYear,
            version: null,
            loading: true,
            saving: false,
            error: "",
            commonAmount: "",
            months: TARGET_MONTHS.map(([value, label]) => ({ value, label })),
            weekdays: TARGET_WEEKDAYS.map(([value, label]) => ({ value, label })),
            selectedMonths: [this.monthFromInitialYearContext],
            selectedWeekdays: TARGET_WEEKDAYS.map(([value]) => value),
            cells: {},
        });
        this.labels = {
            title: _t("Manage heat calendar targets"),
            company: _t("Company"),
            year: _t("Year"),
            months: _t("Months"),
            weekdays: _t("Weekdays"),
            selectAll: _t("Select all"),
            clear: _t("Clear"),
            target: _t("Target amount"),
            active: _t("Active"),
            commonAmount: _t("Common target amount"),
            applyCommon: _t("Apply to selected cells"),
            selectedCells: _t("Selected cells"),
            untouched: _t("Unselected values will not change."),
            noChanges: _t("Choose a target amount or activate an existing target to save a change."),
            amountRequired: _t("Enter a target amount for every active or configured selected cell."),
            scopeHelp: _t("Start with the displayed month. Select the months and days you want to manage, then set each target independently."),
            loading: _t("Loading targets…"),
            saving: _t("Saving…"),
            save: _t("Save targets"),
            cancel: _t("Cancel"),
            noSelection: _t("Select at least one month and one weekday."),
            commonRequired: _t("Enter a common amount before applying it."),
            saveError: _t("Targets could not be saved."),
            loadError: _t("Targets could not be loaded."),
            noTarget: _t("No target is active for this day."),
        };
        onWillStart(() => this.loadTargets());
    }

    get monthFromInitialYearContext() {
        // The dashboard opens this dialog with its visible year.  Selecting the
        // current calendar month is a safer default than exposing an empty form.
        return this._initialMonth || new Date().getMonth() + 1;
    }

    get yearOptions() {
        const years = new Set([this.state.year]);
        for (let year = this.state.year - 3; year <= this.state.year + 3; year += 1) {
            years.add(year);
        }
        return [...years].sort((left, right) => left - right);
    }

    get visibleMonths() {
        return this.state.months.filter((month) => this.isMonthSelected(month.value));
    }

    get visibleWeekdays() {
        return this.state.weekdays.filter((weekday) => this.isWeekdaySelected(weekday.value));
    }

    get selectedCellCount() {
        return this.state.selectedMonths.length * this.state.selectedWeekdays.length;
    }

    get hasActionableSelection() {
        const { entries, missingAmounts } = this.prepareEntries();
        return entries.length > 0 || missingAmounts.length > 0;
    }

    get companyName() {
        const company = this.state.company;
        if (Array.isArray(company)) {
            return company[1] || "—";
        }
        return typeof company === "string" ? company : company?.name || "—";
    }

    async loadTargets() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const payload = await this.orm.call("baseer.heat.calendar.target.batch", "get_target_batch", [this.state.year]);
            this.state.company = payload.company;
            this.state.year = Number(payload.year || this.state.year);
            this.state.version = payload.version ?? null;
            this._initialMonth = Number(payload.month || this._initialMonth || new Date().getMonth() + 1);
            if (!this.state.selectedMonths.length) {
                this.state.selectedMonths = [this._initialMonth];
            }
            if (Array.isArray(payload.months) && payload.months.length) {
                this.state.months = payload.months.map((month) => ({
                    value: Number(month.value ?? month.month ?? month.id),
                    label: month.label ?? month.name ?? String(month.value ?? month.month ?? month.id),
                }));
            }
            if (Array.isArray(payload.weekdays) && payload.weekdays.length) {
                this.state.weekdays = payload.weekdays.map((weekday) => ({
                    value: Number(weekday.value ?? weekday.weekday ?? weekday.id),
                    label: weekday.label ?? weekday.name ?? String(weekday.value ?? weekday.weekday ?? weekday.id),
                }));
            }
            const cells = {};
            for (const sourceCell of payload.cells || []) {
                const month = Number(sourceCell.month);
                const weekday = Number(sourceCell.weekday);
                if (!Number.isInteger(month) || !Number.isInteger(weekday)) {
                    continue;
                }
                const amount = sourceCell.target_amount ?? sourceCell.amount ?? "";
                cells[targetCellKey(month, weekday)] = {
                    configured: Boolean(sourceCell.configured),
                    active: Boolean(sourceCell.active),
                    amount: amount === false || amount === null || amount === undefined ? "" : String(amount),
                };
            }
            this.state.cells = cells;
        } catch (error) {
            this.state.error = error?.message || this.labels.loadError;
        } finally {
            this.state.loading = false;
        }
    }

    cellFor(month, weekday) {
        const key = targetCellKey(month, weekday);
        if (!this.state.cells[key]) {
            this.state.cells[key] = { configured: false, active: false, amount: "" };
        }
        return this.state.cells[key];
    }

    isMonthSelected(month) {
        return this.state.selectedMonths.includes(month);
    }

    isWeekdaySelected(weekday) {
        return this.state.selectedWeekdays.includes(weekday);
    }

    toggleMonth(month) {
        this.state.selectedMonths = this.toggleSelection(this.state.selectedMonths, month);
    }

    toggleWeekday(weekday) {
        this.state.selectedWeekdays = this.toggleSelection(this.state.selectedWeekdays, weekday);
    }

    toggleSelection(values, value) {
        const next = new Set(values);
        if (next.has(value)) {
            next.delete(value);
        } else {
            next.add(value);
        }
        return [...next].sort((left, right) => left - right);
    }

    selectAllMonths() {
        this.state.selectedMonths = this.state.months.map((month) => month.value);
    }

    clearMonths() {
        this.state.selectedMonths = [];
    }

    selectAllWeekdays() {
        this.state.selectedWeekdays = this.state.weekdays.map((weekday) => weekday.value);
    }

    clearWeekdays() {
        this.state.selectedWeekdays = [];
    }

    onYearChange(event) {
        const year = Number(event.target.value);
        if (Number.isInteger(year) && year !== this.state.year) {
            this.state.year = year;
            this.loadTargets();
        }
    }

    setCellAmount(month, weekday, event) {
        const cell = this.cellFor(month, weekday);
        cell.amount = event.target.value;
        // A newly typed target should work immediately.  Existing inactive
        // rows stay inactive when their stored amount is revised deliberately.
        if (!cell.configured) {
            cell.active = Boolean(String(event.target.value).trim());
        }
        this.state.error = "";
    }

    setCellActive(month, weekday, event) {
        this.cellFor(month, weekday).active = event.target.checked;
        this.state.error = "";
    }

    setCommonAmount(event) {
        this.state.commonAmount = event.target.value;
        this.state.error = "";
    }

    applyCommonAmount() {
        if (!this.selectedCellCount) {
            this.state.error = this.labels.noSelection;
            return;
        }
        if (!String(this.state.commonAmount).trim()) {
            this.state.error = this.labels.commonRequired;
            return;
        }
        for (const month of this.state.selectedMonths) {
            for (const weekday of this.state.selectedWeekdays) {
                const cell = this.cellFor(month, weekday);
                cell.amount = this.state.commonAmount;
                cell.active = true;
            }
        }
        this.state.error = "";
    }

    prepareEntries() {
        const entries = [];
        const missingAmounts = [];
        for (const month of this.state.selectedMonths) {
            for (const weekday of this.state.selectedWeekdays) {
                const cell = this.state.cells[targetCellKey(month, weekday)] || {
                    configured: false, active: false, amount: "",
                };
                const amount = String(cell.amount ?? "").trim();
                if (!cell.configured && !amount && !cell.active) {
                    continue;
                }
                if (!amount) {
                    missingAmounts.push({ month, weekday });
                    continue;
                }
                entries.push({
                    month,
                    weekday,
                    active: Boolean(cell.active),
                    target_amount: amount,
                });
            }
        }
        return { entries, missingAmounts };
    }

    async save() {
        const { entries, missingAmounts } = this.prepareEntries();
        if (missingAmounts.length) {
            this.state.error = this.labels.amountRequired;
            return;
        }
        if (!entries.length) {
            this.state.error = this.labels.noChanges;
            return;
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.orm.call("baseer.heat.calendar.target.batch", "apply_target_batch", [
                this.state.year, entries, this.state.version,
            ]);
            this.props.onSaved?.();
            this.props.close();
        } catch (error) {
            this.state.error = error?.message || this.labels.saveError;
        } finally {
            this.state.saving = false;
        }
    }
}

export class BaseerHeatCalendar extends Component {
    static template = "baseer_sales_heat_calendar.HeatCalendar";
    static props = { dashboardId: Number };
    static components = { HeatDayDetails };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
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
        const [year, month] = this.state.month.split("-").map(Number);
        this.dialog.add(HeatTargetBatchDialog, {
            initialYear: year,
            initialMonth: month,
            onSaved: () => this.load(),
        });
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

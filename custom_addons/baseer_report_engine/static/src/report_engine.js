/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { formatFloat } from "@web/views/fields/formatters";
import { useSetupAction } from "@web/search/action_hook";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { user, userBus } from "@web/core/user";

export class BaseerReportEngine extends Component {
    static template = "baseer_report_engine.Report";
    static props = ["*"];
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.reportCode = this.props.action?.context?.report_code
            || this.props.action?.params?.report_code;
        this.state = useState({
            loading: true,
            exporting: false,
            error: "",
            labels: {},
            presets: [],
            units: [],
            journals: [],
            analyticAccounts: [],
            analyticEnabled: false,
            reportName: "",
            dateMode: "as_of",
            options: {},
            payload: null,
            folded: {},
            accounts: {},
            search: "",
        });
        this.restoredState = this.props.state?.baseerReport;
        useSetupAction({ getLocalState: () => ({ baseerReport: {
            options: this.plainOptions(), folded: { ...this.state.folded },
            accounts: JSON.parse(JSON.stringify(this.state.accounts)), search: this.state.search,
        } }) });
        this.requestToken = 0;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.reload());
        onWillStart(() => this.reload());
    }

    get rtl() {
        return (user.lang || "").startsWith("ar");
    }

    get isGrid() { return this.state.payload?.report.report_kind === "account_grid"; }

    get lines() {
        const search = this.state.search.trim().toLocaleLowerCase();
        return (this.state.payload?.lines || []).filter((line) => !this.isHidden(line) && (!this.isGrid || !search || line.display === "total" || line.name.toLocaleLowerCase().includes(search)));
    }

    get byCode() {
        const map = {};
        for (const line of this.state.payload?.lines || []) {
            map[line.code] = line;
        }
        return map;
    }

    isHidden(line) {
        let parent = line.parent_code;
        while (parent) {
            if (this.state.folded[parent]) {
                return true;
            }
            parent = this.byCode[parent]?.parent_code;
        }
        return false;
    }

    plainOptions(direction = 0) {
        const options = this.state.options || {};
        return {
            preset: options.preset || "this_month",
            as_of: options.as_of || false,
            date_from: options.date_from || false,
            date_to: options.date_to || false,
            anchor_date: options.anchor_date || false,
            comparison: Number(options.comparison || 0),
            comparison_unit: options.comparison_unit || "month",
            comparison_mode: options.comparison_mode || "previous",
            posted_only: !!options.posted_only,
            hide_zero: !!options.hide_zero,
            journal_ids: [...(options.journal_ids || [])],
            analytic_account_ids: [...(options.analytic_account_ids || [])],
            direction,
        };
    }

    async reload() {
        if (!this.reportCode) {
            this.state.loading = false;
            this.state.error = "Missing report.";
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        this.state.accounts = {};
        try {
            const bootstrap = await this.orm.call(
                "baseer.report.engine", "get_bootstrap", [this.reportCode],
            );
            this.state.labels = bootstrap.labels;
            this.state.presets = bootstrap.presets;
            this.state.units = bootstrap.units;
            this.state.journals = bootstrap.journals;
            this.state.analyticAccounts = bootstrap.analytic_accounts;
            this.state.analyticEnabled = bootstrap.analytic_enabled;
            this.state.reportName = bootstrap.report.name;
            this.state.dateMode = bootstrap.report.date_mode;
            this.state.options = this.restoredState?.options || bootstrap.defaults;
            this.state.search = this.restoredState?.search || "";
            await this.loadReport();
            if (this.restoredState) {
                this.state.folded = this.restoredState.folded || {};
                this.state.accounts = this.restoredState.accounts || {};
                this.restoredState = null;
            }
        } catch (error) {
            this.state.loading = false;
            this.state.error = error?.data?.message || this.state.labels.error || "Error";
        }
    }

    async loadReport(direction = 0) {
        const token = ++this.requestToken;
        const options = this.plainOptions(direction);
        this.state.loading = true;
        this.state.error = "";
        try {
            const payload = await this.orm.call(
                "baseer.report.engine", "get_report", [this.reportCode, options],
            );
            if (token !== this.requestToken) {
                return;
            }
            this.state.payload = payload;
            this.state.options = payload.options;
            this.state.reportName = payload.report.name;
            this.state.dateMode = payload.report.date_mode;
            const folded = {};
            for (const line of payload.lines) {
                if (line.foldable && line.has_accounts) {
                    folded[line.code] = true;
                }
            }
            this.state.folded = folded;
            this.state.accounts = {};
        } catch (error) {
            if (token === this.requestToken) {
                this.state.error = error?.data?.message || this.state.labels.error || "Error";
            }
        } finally {
            if (token === this.requestToken) {
                this.state.loading = false;
            }
        }
    }

    onPreset(event) {
        this.state.options.preset = event.target.value;
        this.state.options.anchor_date = false;
        this.loadReport();
    }

    onDate(event) {
        this.state.options[event.target.name] = event.target.value;
        this.state.options.preset = "custom";
        this.state.options.anchor_date = false;
        if (this.state.dateMode === "as_of") this.loadReport();
    }

    onComparison(event) {
        const value = Number(event.target.value);
        this.state.options.comparison = Math.max(0, Math.min(12, Number.isInteger(value) ? value : 0));
        this.loadReport();
    }

    onUnit(event) {
        this.state.options.comparison_unit = event.target.value;
        this.loadReport();
    }

    onToggle(name, event) {
        this.state.options[name] = event.target.checked;
        this.loadReport();
    }

    onJournal(event) {
        const id = Number(event.target.value);
        const selected = new Set(this.state.options.journal_ids || []);
        if (event.target.checked) {
            selected.add(id);
        } else {
            selected.delete(id);
        }
        this.state.options.journal_ids = [...selected];
        this.loadReport();
    }

    onAnalytic(event) {
        const id = Number(event.target.value);
        const selected = new Set(this.state.options.analytic_account_ids || []);
        if (event.target.checked) {
            selected.add(id);
        } else {
            selected.delete(id);
        }
        this.state.options.analytic_account_ids = [...selected];
        this.loadReport();
    }

    async toggleLine(line) {
        this.state.folded[line.code] = !this.state.folded[line.code];
        if (!this.state.folded[line.code] && line.has_accounts && !this.state.accounts[line.code]) {
            await this.loadAccounts(line.code);
        }
    }

    async loadAccounts(code) {
        this.state.accounts[code] = { loading: true, rows: [] };
        try {
            const result = await this.orm.call(
                "baseer.report.engine", "get_line_accounts",
                [this.reportCode, this.plainOptions(), code],
            );
            this.state.accounts[code] = { loading: false, rows: result.accounts };
        } catch (error) {
            this.state.accounts[code] = { loading: false, rows: [] };
            this.state.error = error?.data?.message || this.state.labels.error || "Error";
        }
    }

    accountRows(line) {
        if (this.state.folded[line.code]) {
            return [];
        }
        return this.state.accounts[line.code]?.rows || [];
    }

    async openAmount(line, amount, accountId = false, companyId = false) {
        if (!amount.drill) {
            return;
        }
        const action = await this.orm.call(
            "baseer.report.engine", "get_move_line_action",
            [this.reportCode, this.plainOptions(), line.source_code || line.code, amount.key, accountId ?? false, companyId ?? false],
        );
        await this.actionService.doAction(action);
    }

    async exportPdf() {
        this.state.exporting = true;
        try {
            const action = await this.orm.call(
                "baseer.report.engine", "export_pdf", [this.reportCode, this.plainOptions()],
            );
            await this.actionService.doAction(action);
        } catch (error) {
            this.state.error = error?.data?.message || this.state.labels.error || "Error";
        } finally {
            this.state.exporting = false;
        }
    }

    async exportXlsx() {
        this.state.exporting = true;
        try {
            const result = await this.orm.call(
                "baseer.report.engine", "export_xlsx", [this.reportCode, this.plainOptions()],
            );
            const binary = atob(result.content);
            const bytes = new Uint8Array(binary.length);
            for (let index = 0; index < binary.length; index++) {
                bytes[index] = binary.charCodeAt(index);
            }
            const url = URL.createObjectURL(new Blob([bytes], { type: result.mimetype }));
            const link = document.createElement("a");
            link.href = url;
            link.download = result.filename;
            link.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            this.state.error = error?.data?.message || this.state.labels.error || "Error";
        } finally {
            this.state.exporting = false;
        }
    }

    get periodLabel() {
        const column = this.state.payload?.columns[0];
        if (!column) return this.state.labels.period;
        if (this.isGrid) {
            const date = new Date(`${this.state.options.date_to}T12:00:00`);
            const locale = (user.lang || "en_US").replace("_", "-");
            const start = new Date(`${this.state.options.date_from}T12:00:00`);
            if (this.state.options.preset === "custom") {
                const format = new Intl.DateTimeFormat(locale);
                return `${format.format(start)} – ${format.format(date)}`;
            }
            if (this.state.options.preset === "this_year") return String(date.getFullYear());
            if (this.state.options.preset === "this_quarter") {
                return `${new Intl.DateTimeFormat(locale, { month: "short" }).format(start)} – ${new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(date)}`;
            }
            return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(date);
        }
        if (this.state.dateMode === "as_of") {
            const locale = (user.lang || "en_US").replace("_", "-");
            return this.rtl ? `${this.state.labels.as_of} ${column.date_to.split("-").reverse().join("/")}` : `${this.state.labels.as_of} ${new Intl.DateTimeFormat(locale).format(new Date(`${column.date_to}T12:00:00`))}`;
        }
        if (this.state.options.preset === "custom") return column.label;
        const date = new Date(`${column.date_to}T12:00:00`);
        const locale = (user.lang || "en_US").replace("_", "-");
        const unit = this.state.options.comparison_unit;
        if (unit === "year") return String(date.getFullYear());
        if (unit === "quarter") {
            const start = new Date(`${column.fiscal_start}T12:00:00`);
            const months = (date.getFullYear() - start.getFullYear()) * 12 + date.getMonth() - start.getMonth();
            return `Q${Math.floor(months / 3) + 1} ${date.getFullYear()}`;
        }
        return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(date);
    }

    get dateRows() {
        const keys = this.state.dateMode === "as_of" ? ["today", "this_month", "this_quarter", "this_year"] : ["this_month", "this_quarter", "this_year"];
        return keys.map((key) => ({ key, label: key === "today" ? this.state.presets.find(p => p.key === key)?.label : this.state.dateMode === "as_of" ? (key === "this_month" ? _t("End of Month") : this.state.labels[{this_quarter: "end_quarter", this_year: "end_year"}[key]]) : this.state.units.find(p => p.key === key.replace("this_", ""))?.label }));
    }

    dateRowPeriod(key) {
        const anchor = new Date(`${this.state.options.anchor_date || this.state.options.date_to}T12:00:00`);
        const locale = (user.lang || "en_US").replace("_", "-");
        const fmt = (date, options) => new Intl.DateTimeFormat(locale, options).format(date);
        if (key === "this_month") return fmt(anchor, {month: "long", year: "numeric"});
        const col = this.state.payload?.columns[0];
        const fiscal = new Date(`${col?.fiscal_start || this.state.options.date_to}T12:00:00`);
        if (key === "this_year") {
            const end = new Date(fiscal); end.setFullYear(end.getFullYear() + 1); end.setDate(end.getDate() - 1);
            return fiscal.getFullYear() === end.getFullYear() ? String(end.getFullYear()) : `${fiscal.getFullYear()} - ${end.getFullYear()}`;
        }
        const months = (anchor.getFullYear() - fiscal.getFullYear()) * 12 + anchor.getMonth() - fiscal.getMonth();
        const start = new Date(fiscal); start.setMonth(start.getMonth() + Math.floor(months / 3) * 3);
        const end = new Date(start); end.setMonth(end.getMonth() + 3); end.setDate(end.getDate() - 1);
        return `${fmt(start, {month: "short"})} - ${fmt(end, {month: "short", year: "numeric"})}`;
    }

    chooseDate(key, direction = 0) {
        this.state.options.preset = key;
        if (key === "today") this.state.options.anchor_date = false;
        this.loadReport(direction);
    }

    async openDraftEntries() {
        const action = await this.orm.call("baseer.report.engine", "get_draft_entries_action", [this.reportCode, this.plainOptions()]);
        await this.actionService.doAction(action);
    }

    selectPreset(key) {
        this.state.options.preset = key;
        this.state.options.anchor_date = false;
        this.loadReport();
    }

    setComparison(mode) {
        this.state.options.comparison_mode = mode === "year" ? "year" : "previous";
        this.state.options.comparison = mode === "none" ? 0 : Math.max(1, this.state.options.comparison || 0);
        this.loadReport();
    }

    async unfoldAll() {
        const lines = this.state.payload?.lines || [];
        this.state.folded = {};
        const codes = lines.filter((line) => line.has_accounts).map((line) => line.code);
        if (!codes.length) return;
        try {
            const results = await this.orm.call("baseer.report.engine", "get_lines_accounts",
                [this.reportCode, this.plainOptions(), codes]);
            for (const result of results) {
                this.state.accounts[result.line_code] = { loading: false, rows: result.accounts };
            }
        } catch (error) {
            this.state.error = error?.data?.message || this.state.labels.error || "Error";
        }
    }

    foldAll() {
        this.state.folded = Object.fromEntries((this.state.payload?.lines || []).filter((line) => line.foldable && line.has_accounts).map((line) => [line.code, true]));
    }

    rowClass(line) {
        return `o_bre_${line.display} o_bre_level_${line.level}` +
            (line.foldable ? " o_bre_foldable" : "") +
            (line.has_accounts && !this.state.folded[line.code] ? " o_bre_open" : "") +
            (this.state.dateMode === "range" && line.display === "total" ? " o_bre_band" : "");
    }

    columnLabel(column) {
        if (this.state.dateMode === "range" && column.kind === "period" && this.state.options.preset === "this_year") {
            const start = column.date_from?.slice(0, 4);
            const end = column.date_to?.slice(0, 4);
            if (start === end) return end;
        }
        return column.label;
    }

    formatAmount(amount) {
        if (amount.value === null) return "—";
        const percent = amount.key === "variation_percent";
        const digits = percent ? 2 : this.state.payload.currency.decimals;
        return formatFloat(Number(amount.value), { digits: [16, digits] }) + (percent ? "%" : "");
    }

    amountClass(amount) {
        if (amount.negative) {
            return "is-negative";
        }
        if (amount.zero) {
            return "is-zero";
        }
        return "";
    }
}

registry.category("actions").add("baseer_report_engine", BaseerReportEngine);

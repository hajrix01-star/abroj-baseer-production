/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { user, userBus } from "@web/core/user";

export class BaseerReportEngine extends Component {
    static template = "baseer_report_engine.Report";
    static props = ["*"];

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
        });
        this.requestToken = 0;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.reload());
        onWillStart(() => this.reload());
    }

    get rtl() {
        return (user.lang || "").startsWith("ar");
    }

    get lines() {
        return (this.state.payload?.lines || []).filter((line) => !this.isHidden(line));
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
        this.state.payload = null;
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
            this.state.options = bootstrap.defaults;
            await this.loadReport();
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
                if (line.foldable && line.level > 0) {
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
    }

    onDate(event) {
        this.state.options[event.target.name] = event.target.value;
        this.state.options.preset = "custom";
        this.state.options.anchor_date = false;
    }

    onComparison(event) {
        const value = Number(event.target.value);
        this.state.options.comparison = Number.isInteger(value) ? value : 0;
    }

    onUnit(event) {
        this.state.options.comparison_unit = event.target.value;
    }

    onToggle(name, event) {
        this.state.options[name] = event.target.checked;
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

    async openAmount(line, amount, accountId = false) {
        if (!amount.drill) {
            return;
        }
        const action = await this.orm.call(
            "baseer.report.engine", "get_move_line_action",
            [this.reportCode, this.plainOptions(), line.code, amount.key, accountId || false],
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

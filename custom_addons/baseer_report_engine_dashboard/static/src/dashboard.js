/** @odoo-module **/
import { Component, onWillStart, onWillUnmount, useExternalListener, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

function normalizeAction(action) {
    if (action.type === "ir.actions.act_window" && !action.views && action.view_mode) {
        return {
            ...action,
            views: action.view_mode.split(",").map((mode) => [action.view_id || false, mode.trim()]),
        };
    }
    return action;
}

export class AccountingDashboard extends Component {
    static template = "baseer_report_engine_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true, error: "", journals: [], reports: [], favorites: true,
            search: "", menu: null, is_manager: false, is_user: false,
        });
        useExternalListener(document, "click", (event) => {
            if (!event.target.closest(".o_bre_menu_wrap")) this.state.menu = null;
        });
        useExternalListener(document, "keydown", (event) => {
            if (event.key === "Escape") this.state.menu = null;
        });
        onWillStart(() => this.load());
        onWillUnmount(() => clearTimeout(this.timer));
    }

    async load() {
        const request = this.request = (this.request || 0) + 1;
        this.state.loading = true;
        this.state.error = "";
        try {
            const data = await this.orm.call("baseer.accounting.dashboard", "get_dashboard", [{
                favorites_only: this.state.favorites, search: this.state.search,
            }]);
            if (request === this.request) Object.assign(this.state, data);
        } catch (error) {
            if (request === this.request) this.state.error = error.message || _t("Unable to load dashboard");
        } finally {
            if (request === this.request) this.state.loading = false;
        }
    }

    async call(card, method, context = {}) {
        this.state.menu = null;
        try {
            const action = await this.orm.call("account.journal", method, [[card.id]], { context });
            if (action) await this.action.doAction(normalizeAction(action));
        } catch (error) {
            this.state.error = error.message || _t("Unable to open action");
        }
    }

    async openAnalysis(card) {
        this.state.menu = null;
        const xmlid = card.type === "sale"
            ? "account.action_account_invoice_report_all"
            : "account.action_account_invoice_report_all_supp";
        const action = await this.action.loadAction(xmlid);
        action.domain = [...(Array.isArray(action.domain) ? action.domain : []), ["journal_id", "=", card.id]];
        return this.action.doAction(action, { additionalContext: { active_id: card.id, active_model: "account.journal" } });
    }

    configure(card) {
        this.state.menu = null;
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: "account.journal",
            res_id: card.id, views: [[false, "form"]],
        });
    }

    statement(card) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "account.bank.statement",
            res_id: card.dashboard.last_statement_id, views: [[false, "form"]],
        });
    }

    payments(card) {
        this.action.doAction("account.action_account_all_payments", {
            additionalContext: {
                search_default_unmatched: true, search_default_journal_id: card.id,
                search_default_state_posted: true,
            },
        });
    }

    toggleFavorites() {
        this.state.favorites = !this.state.favorites;
        this.load();
    }

    search(event) {
        this.state.search = event.target.value;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.load(), 250);
    }

    graph(card) {
        const series = card.graph?.[0];
        if (!series?.values?.length) return null;
        const values = series.values;
        const nums = values.map((value) => Number(value.value ?? value.y) || 0);
        const min = Math.min(0, ...nums);
        const max = Math.max(0, ...nums);
        const span = max - min || 1;
        const y = (number) => 85 - (number - min) / span * 70;
        const step = 300 / values.length;
        const points = nums.map((number, index) => ({
            x: values.length === 1 ? 150 : index * 300 / (values.length - 1),
            y: y(number),
        }));
        return {
            sample: series.is_sample_data,
            bars: values.map((value, index) => ({
                x: index * step + 4, width: Math.max(1, step - 8),
                y: Math.min(y(nums[index]), y(0)),
                height: Math.max(1, Math.abs(y(nums[index]) - y(0))),
                label: value.label, type: value.type,
            })),
            points: points.map((point) => `${point.x},${point.y}`).join(" "),
            first: points[0], last: points[points.length - 1],
        };
    }
}
registry.category("actions").add("baseer_accounting_dashboard", AccountingDashboard);

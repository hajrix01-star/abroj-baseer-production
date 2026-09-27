/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const today = new Date();
const asDate = (value) => [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, "0"),
    String(value.getDate()).padStart(2, "0"),
].join("-");

export class BaseerBankSmsDashboard extends Component {
    static template = "baseer_bank_sms.AnalysisDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dashboardRef = useRef("dashboard");
        this.state = useState({
            loading: true,
            error: false,
            data: false,
            filters: {
                from: asDate(new Date(today.getFullYear(), today.getMonth(), 1)),
                to: asDate(today),
            },
        });
        onMounted(() => {
            this.actionManager = this.dashboardRef.el?.closest(".o_action_manager");
            this.actionManager?.classList.add("o_bank_sms_dashboard_action");
        });
        onWillUnmount(() => this.actionManager?.classList.remove("o_bank_sms_dashboard_action"));
        onWillStart(() => this.load());
    }

    formatAmount(metric) {
        const amount = metric || {};
        return amount.currency_position === "before"
            ? `${amount.currency_symbol || amount.currency} ${amount.display}`
            : `${amount.display} ${amount.currency_symbol || amount.currency}`;
    }

    onDateChanged(event) {
        this.state.filters[event.target.name] = event.target.value;
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "baseer.bank.sms.message",
                "get_analysis_dashboard",
                [this.state.filters.from, this.state.filters.to]
            );
        } catch {
            this.state.error = _t("تعذّر تحميل لوحة التحليل. حاول مرة أخرى.");
        } finally {
            this.state.loading = false;
        }
    }

    openMessages(identifierId) {
        const from = `${this.state.filters.from} 00:00:00`;
        const until = new Date(`${this.state.filters.to}T00:00:00`);
        until.setDate(until.getDate() + 1);
        const to = `${asDate(until)} 00:00:00`;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("رسائل المعرّف"),
            res_model: "baseer.bank.sms.message",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["instrument_id", "=", identifierId],
                ["analysis_at", ">=", from],
                ["analysis_at", "<", to],
                ["state", "not in", ["trash", "rejected"]],
            ],
        });
    }

    openIdentifier(identifierId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("المعرّف"),
            res_model: "baseer.bank.sms.instrument",
            res_id: identifierId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("baseer_bank_sms.dashboard", BaseerBankSmsDashboard);

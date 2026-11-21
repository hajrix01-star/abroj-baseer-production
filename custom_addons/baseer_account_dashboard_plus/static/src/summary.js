import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";
import { onWillStart, useState } from "@odoo/owl";
import { DashboardKanbanRenderer } from "@account/views/account_dashboard_kanban/account_dashboard_kanban_renderer";

patch(DashboardKanbanRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.baseerOrm = useService("orm");
        this.baseerAction = useService("action");
        this.baseerNotification = useService("notification");
        this.baseer = useState({ data: null, open: (localStorage.getItem("baseer.summary.open") === null ? !window.matchMedia("(max-width: 767px)").matches : localStorage.getItem("baseer.summary.open") === "true"), companiesOpen: false });
        onWillStart(async () => {
            this.baseer.data = await this.baseerOrm.call("account.journal", "baseer_dashboard_summary", []);
        });
    },
    get baseerTiles() {
        return [["bank", _t("Bank ledger")], ["cash", _t("Cash ledger")], ["custody", _t("Custody")], ["delivery", _t("Delivery apps")], ["receivable", _t("Receivables")], ["payable", _t("Payables")]];
    },
    get baseerTotals() {
        const totals = new Map();
        for (const company of this.baseer.data.companies) {
            if (!totals.has(company.currency_id)) {
                totals.set(company.currency_id, {currency_id: company.currency_id, bank: 0, cash: 0, custody: 0, delivery: 0, receivable: 0, payable: 0, vat: 0, draft_amount: 0, draft_count: 0, apps: {}});
            }
            const total = totals.get(company.currency_id);
            for (const key of ["bank", "cash", "custody", "delivery", "receivable", "payable", "vat", "draft_amount", "draft_count"]) total[key] += company[key];
            for (const [app, amount] of Object.entries(company.apps)) total.apps[app] = (total.apps[app] || 0) + amount;
        }
        return [...totals.values()];
    },
    baseerMoney(value, currencyId) { return formatMonetary(value, { currencyId }); },
    baseerToggle() {
        this.baseer.open = !this.baseer.open;
        localStorage.setItem("baseer.summary.open", String(this.baseer.open));
    },
    async baseerDoAction(action) {
        if (!action || !action.type ||
            (action.type === "ir.actions.act_window" && !action.res_model) ||
            (action.type === "ir.actions.client" && !action.tag)) {
            this.baseerNotification.add(_t("Unable to open this dashboard action."), { type: "warning" });
            return;
        }
        if (action.type === "ir.actions.act_window" && !Array.isArray(action.views)) {
            action = { ...action, views: (action.view_mode || "list,form").split(",").map(mode => [false, mode.trim()]).filter(([, mode]) => mode) };
        }
        await this.baseerAction.doAction(action);
    },
    async baseerOpen(kind) {
        const action = await this.baseerOrm.call("account.journal", "baseer_summary_action", [kind]);
        await this.baseerDoAction(action);
    },
    async baseerReport(key) {
        const action = await this.baseerOrm.call("account.journal", "baseer_report_action", [key]);
        await this.baseerDoAction(action);
    },
});

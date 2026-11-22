/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { localization } from "@web/core/l10n/localization";
import { user } from "@web/core/user";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

function newClientToken() {
    return globalThis.crypto.randomUUID();
}

function today() {
    const values = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
        timeZone: "Asia/Riyadh", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date()).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
}

export function formatRequestDateTime(value, locale = user.lang, timeZone = user.tz) {
    if (!value || typeof value !== "string") return "";
    // Odoo serializes this datetime without an offset. The server contract is
    // UTC, so parse it explicitly instead of inheriting the browser timezone.
    const timestamp = new Date(`${value.replace(" ", "T")}Z`);
    if (Number.isNaN(timestamp.valueOf())) return "";
    const normalizedLocale = typeof locale === "string" ? locale.replaceAll("_", "-") : "en-US";
    let formatter;
    const options = {
        calendar: "gregory",
        day: "2-digit",
        month: "2-digit",
        numberingSystem: "latn",
        timeZone: timeZone || "UTC",
        year: "numeric",
    };
    try {
        formatter = new Intl.DateTimeFormat(normalizedLocale, options);
    } catch (_error) {
        formatter = new Intl.DateTimeFormat("en-US", options);
    }
    return formatter.format(timestamp);
}

function serverErrorMessage(error, fallback) {
    // The RPC title is often just "Odoo Server Error". Only display the
    // deliberate business errors emitted by Odoo; never expose a technical
    // exception message, traceback, SQL detail, or debug payload.
    const safeExceptions = new Set([
        "odoo.exceptions.AccessError",
        "odoo.exceptions.UserError",
        "odoo.exceptions.ValidationError",
    ]);
    if (!safeExceptions.has(error?.data?.name)) return fallback;
    const candidates = [error?.data?.arguments?.[0], error?.data?.message, error?.message];
    return candidates.find((message) => (
        typeof message === "string" && message.trim() && message !== "Odoo Server Error"
    )) || fallback;
}

export class PettyCashEntryDialog extends Component {
    static template = "baseer_procurement_requests.PettyCashEntryDialog";
    static components = { Dialog, Dropdown, DropdownItem };
    static props = { close: Function, owner: Object, mode: String };

    setup() { this.state = useState(this.props.owner.state); }

    get title() { return this.props.mode === "return" ? _t("Return remaining") : _t("Add petty cash"); }
    async submit() {
        const saved = this.props.mode === "return" ? await this.props.owner.saveReturn() : await this.props.owner.save();
        if (saved) this.props.close();
    }
}

export class PettyCashSettlementDialog extends Component {
    static template = "baseer_procurement_requests.PettyCashSettlementDialog";
    static components = { Dialog };
    static props = { close: Function, owner: Object, representativeId: Number };
    get title() { return _t("Settle carried balance"); }
    returnCash() { this.props.close(); this.props.owner.openEntry("return", this.props.representativeId); }
    purchases() {
        this.props.close();
        this.props.owner.openPurchases(this.props.representativeId);
    }
}

export class PettyCashReversalDialog extends Component {
    static template = "baseer_procurement_requests.PettyCashReversalDialog";
    static components = { Dialog };
    static props = { close: Function, owner: Object, fundingId: Number };
    setup() { this.state = useState({ reason: "", date: today(), saving: false, token: newClientToken() }); }
    get title() { return _t("Reverse petty cash entry"); }
    async reverse() {
        if (this.state.saving) return;
        if (!this.state.reason.trim() || !this.state.date) {
            this.props.owner.notification.add(_t("Enter a reason and reversal date."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            await this.props.owner.orm.call("baseer.procurement.representative.advance", "submit_funding_reversal", [
                this.props.fundingId, this.state.reason.trim(), this.state.date, this.state.token,
            ]);
            await this.props.owner.load();
            this.props.owner.notification.add(_t("The entry was reversed. You can record the correct petty cash entry."), { type: "success" });
            this.props.close();
        } catch (error) {
            this.props.owner.notification.add(serverErrorMessage(error, _t("Could not reverse the entry.")), { type: "danger" });
        } finally { this.state.saving = false; }
    }
}

export class RepresentativePettyCash extends Component {
    static template = "baseer_procurement_requests.RepresentativePettyCash";
    static props = ["*"];
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        const params = this.props.action?.params || {};
        this.state = useState({
            loading: true, saving: false, error: false, data: false, tab: "movements", search: "", movementType: "", movementOffset: 0,
            representativeId: "", monthStart: "", destinationId: "", requestId: "", paymentPointId: "", amount: "", movementDate: today(), clientToken: newClientToken(),
            returnRepresentativeId: "", returnPaymentPointId: "", returnAmount: "", returnClientToken: newClientToken(),
        });
        this.state.representativeId = params.representative_id ? String(params.representative_id) : "";
        this.state.monthStart = params.month_start || `${today().slice(0, 7)}-01`;
        // Render the shell and its loading state immediately. Waiting in
        // onWillStart leaves a blank mobile page until the dashboard RPC ends.
        onMounted(() => this.load());
    }

    async load() {
        const sequence = this.dashboardSequence = (this.dashboardSequence || 0) + 1;
        this.movementSequence = (this.movementSequence || 0) + 1;
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "baseer.procurement.representative.advance", "dashboard_data", [this.state.representativeId || false, this.state.monthStart || false],
            );
            if (sequence !== this.dashboardSequence) return;
            this.state.data = data;
            this.state.error = false;
            this.state.movementOffset = 0;
            if (this.state.search || this.state.movementType) await this.loadMovements();
        } catch (error) {
            if (sequence !== this.dashboardSequence) return;
            // Odoo wraps a UserError in a generic RPC "Odoo Server Error". Keep
            // the safe server-side message visible instead of discarding it.
            this.state.error = serverErrorMessage(error, _t("Could not load Representative Petty Cash."));
        } finally {
            if (sequence === this.dashboardSequence) this.state.loading = false;
        }
    }

    openEntry(mode = "funding", representativeId = false) {
        if (representativeId) this.state.returnRepresentativeId = String(representativeId);
        this.dialog.add(PettyCashEntryDialog, { owner: this, mode });
    }

    openSettlement(representativeId) {
        this.dialog.add(PettyCashSettlementDialog, { owner: this, representativeId });
    }

    openReversal(fundingId) {
        this.dialog.add(PettyCashReversalDialog, { owner: this, fundingId });
    }

    async openBillReversal(settlementId) {
        try {
            const action = await this.orm.call(
                "baseer.procurement.representative.advance", "action_open_direct_bill_custody_reversal",
                [settlementId],
            );
            await this.action.doAction(action, { onClose: () => this.load() });
        } catch (error) {
            this.notification.add(serverErrorMessage(error, _t("Could not open supplier bill reversal.")), { type: "danger" });
        }
    }

    async openPurchases(representativeId = false) {
        try {
            const action = await this.orm.call(
                "baseer.procurement.representative.advance", "action_open_direct_bill_custody_payment",
                [representativeId || this.state.representativeId || false],
            );
            await this.action.doAction(action, { onClose: () => this.load() });
        } catch (error) {
            this.notification.add(serverErrorMessage(error, _t("Could not open supplier bill settlement.")), { type: "danger" });
        }
    }

    async loadMovements(offset = 0) {
        const sequence = this.movementSequence = (this.movementSequence || 0) + 1;
        this.state.movementOffset = offset;
        try {
            const result = await this.orm.call("baseer.procurement.representative.advance", "dashboard_daily_movements", [
                this.state.representativeId || false, this.state.monthStart || false,
                this.state.search.trim(), this.state.movementType, offset,
            ]);
            if (sequence !== this.movementSequence) return;
            this.state.data.daily_movements = result.daily_movements;
            this.state.data.daily_movements_truncated = result.daily_movements_truncated;
        } catch (error) {
            this.notification.add(serverErrorMessage(error, _t("Could not load movements.")), { type: "danger" });
        }
    }

    searchMovements(event) { event.preventDefault(); this.loadMovements(0); }
    filterMovements(event) { this.state.movementType = event.target.value; this.loadMovements(0); }

    selectRepresentative(representativeId) {
        this.state.representativeId = representativeId ? String(representativeId) : "";
        this.state.destinationId = "";
        this.state.requestId = "";
        this.load();
    }

    async openRequest(requestId) {
        if (!requestId) return;
        await this.action.doAction({
            type: "ir.actions.act_window", res_model: "baseer.procurement.request",
            res_id: requestId, views: [[false, "form"]], target: "current",
        });
    }

    onMonthChange(event) {
        this.state.monthStart = event.target.value ? `${event.target.value}-01` : `${today().slice(0, 7)}-01`;
        this.load();
    }

    selectRequest(requestId) {
        this.state.requestId = requestId ? String(requestId) : "";
        const request = this.selectedRequest();
        if (request) this.state.destinationId = String(request.representative_id);
    }

    selectedRequest() {
        return this.state.data?.requests.find((request) => request.id === Number(this.state.requestId));
    }

    selectionLabel(items, id, placeholder, field = "display_name") {
        const selected = (items || []).find((item) => item.id === Number(id));
        return selected ? selected[field] : placeholder;
    }

    representativeLabel() {
        return this.selectionLabel(this.state.data?.representatives, this.state.representativeId, _t("All representatives"));
    }

    requestLabel() {
        const request = this.selectedRequest();
        return request ? `${request.name} — ${request.representative_name}` : _t("Choose a purchase request");
    }

    requestDateTimeLabel(request = this.selectedRequest()) {
        return formatRequestDateTime(request?.request_date);
    }

    paymentPointLabel() {
        return this.selectionLabel(this.state.data?.payment_points, this.state.paymentPointId, _t("Choose a bank or cash point"), "name");
    }

    destinationLabel() {
        return this.selectionLabel(this.state.data?.representatives, this.state.destinationId, _t("Choose a purchasing representative"));
    }

    returnRepresentativeLabel() {
        return this.selectionLabel(this.state.data?.representatives, this.state.returnRepresentativeId, _t("Choose a purchasing representative"));
    }

    returnPaymentPointLabel() {
        return this.selectionLabel(this.state.data?.payment_points, this.state.returnPaymentPointId, _t("Choose a bank or cash point"), "name");
    }

    money(amount) {
        const value = Number(amount || 0).toLocaleString("en-US-u-nu-latn", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        const { currency_symbol: symbol, currency_position: position } = this.state.data || {};
        return position === "before" ? `${symbol} ${value}` : `${value} ${symbol || ""}`;
    }

    languageDirection() {
        return localization.direction === "rtl" ? "rtl" : "ltr";
    }

    get movementColumnLabels() {
        return {
            date: _t("Date"),
            movement: _t("Movement number"),
            request: _t("Purchase request"),
            from: _t("From"),
            to: _t("To"),
            amount: _t("Amount"),
        };
    }

    get carryoverColumnLabels() {
        return { representative: _t("Representative"), from: _t("From month"), to: _t("To month"), amount: _t("Carried forward"), action: _t("Action") };
    }

    get dailyColumnLabels() {
        return { date: _t("Date"), type: _t("Movement"), representative: _t("Representative"), reference: _t("Reference"), amount: _t("Amount") };
    }

    dailyMovementLabel(type) {
        return { funding: _t("Petty cash given"), purchase: _t("Purchase"), purchase_reversal: _t("Supplier bill payment reversal"), return: _t("Cash returned"), reversal: _t("Petty cash reversal") }[type] || "—";
    }

    selectPaymentPoint(paymentPointId) { this.state.paymentPointId = String(paymentPointId); }
    selectDestination(destinationId) { this.state.destinationId = String(destinationId); }
    selectReturnRepresentative(representativeId) { this.state.returnRepresentativeId = String(representativeId); }
    selectReturnPaymentPoint(paymentPointId) { this.state.returnPaymentPointId = String(paymentPointId); }
    onAmountInput(event) { this.state.amount = event.target.value; }
    onMovementDateInput(event) { this.state.movementDate = event.target.value; }
    async save() {
        if (this.state.saving) return;
        if (!this.state.paymentPointId || !this.state.destinationId || !this.state.amount || !this.state.movementDate) {
            this.notification.add(_t("Complete the payment point, representative, amount, and transfer date."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("baseer.procurement.representative.advance", "submit_funding", [
                false, Number(this.state.paymentPointId), Number(this.state.destinationId), this.state.amount, this.state.clientToken,
                this.state.movementDate,
            ]);
            this.state.requestId = "";
            this.state.paymentPointId = "";
            this.state.destinationId = "";
            this.state.amount = "";
            this.state.movementDate = today();
            this.state.clientToken = newClientToken();
            await this.load();
            this.notification.add(_t("Representative Petty Cash was saved."), { type: "success" });
            return true;
        } catch (error) {
            this.notification.add(serverErrorMessage(error, _t("Could not save Representative Petty Cash.")), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    async saveReturn() {
        if (this.state.saving) return;
        if (!this.state.returnRepresentativeId || !this.state.returnPaymentPointId || !this.state.returnAmount) {
            this.notification.add(_t("Choose the purchasing representative, payment point, and amount."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("baseer.procurement.representative.advance", "submit_aggregate_return", [
                Number(this.state.returnRepresentativeId), Number(this.state.returnPaymentPointId), this.state.returnAmount, this.state.returnClientToken,
            ]);
            this.state.returnRepresentativeId = "";
            this.state.returnPaymentPointId = "";
            this.state.returnAmount = "";
            this.state.returnClientToken = newClientToken();
            await this.load();
            this.notification.add(_t("Returned cash was saved."), { type: "success" });
            return true;
        } catch (error) {
            this.notification.add(serverErrorMessage(error, _t("Could not save returned cash.")), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add("baseer_procurement_requests.representative_petty_cash", RepresentativePettyCash);

/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

function newClientToken() {
    return globalThis.crypto.randomUUID();
}

function today() {
    const values = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
        timeZone: "Asia/Riyadh", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date()).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
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

export class RepresentativePettyCash extends Component {
    static template = "baseer_procurement_requests.RepresentativePettyCash";
    static props = ["*"];
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true, saving: false, error: false, data: false,
            representativeId: "", monthStart: "", destinationId: "", requestId: "", paymentPointId: "", amount: "", movementDate: today(), clientToken: newClientToken(),
            returnOriginId: "", returnPaymentPointId: "", returnAmount: "", returnClientToken: newClientToken(),
        });
        // Render the shell and its loading state immediately. Waiting in
        // onWillStart leaves a blank mobile page until the dashboard RPC ends.
        onMounted(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "baseer.procurement.representative.advance", "dashboard_data", [this.state.representativeId || false, this.state.monthStart || false],
            );
            this.state.error = false;
        } catch (error) {
            // Odoo wraps a UserError in a generic RPC "Odoo Server Error". Keep
            // the safe server-side message visible instead of discarding it.
            this.state.error = serverErrorMessage(error, _t("Could not load Representative Petty Cash."));
        } finally {
            this.state.loading = false;
        }
    }

    selectRepresentative(representativeId) {
        this.state.representativeId = representativeId ? String(representativeId) : "";
        this.state.destinationId = "";
        this.state.requestId = "";
        this.load();
    }

    onMonthChange(event) {
        this.state.monthStart = event.target.value ? `${event.target.value}-01` : "";
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

    paymentPointLabel() {
        return this.selectionLabel(this.state.data?.payment_points, this.state.paymentPointId, _t("Choose a bank or cash point"), "name");
    }

    destinationLabel() {
        return this.selectionLabel(this.state.data?.representatives, this.state.destinationId, _t("Choose a purchasing representative"));
    }

    returnOriginLabel() {
        const funding = (this.state.data?.open_fundings || []).find((item) => item.id === Number(this.state.returnOriginId));
        return funding ? `${funding.name} — ${funding.representative_name}` : _t("Choose an existing petty cash movement");
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

    selectPaymentPoint(paymentPointId) { this.state.paymentPointId = String(paymentPointId); }
    selectDestination(destinationId) { this.state.destinationId = String(destinationId); }
    selectReturnOrigin(originId) { this.state.returnOriginId = String(originId); }
    selectReturnPaymentPoint(paymentPointId) { this.state.returnPaymentPointId = String(paymentPointId); }
    onAmountInput(event) { this.state.amount = event.target.value; }
    onMovementDateInput(event) { this.state.movementDate = event.target.value; }
    async save() {
        if (this.state.saving) return;
        if (!this.state.requestId || !this.state.paymentPointId || !this.state.destinationId || !this.state.amount || !this.state.movementDate) {
            this.notification.add(_t("Complete the request, payment point, destination, amount, and transfer date."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("baseer.procurement.representative.advance", "submit_funding", [
                Number(this.state.requestId), Number(this.state.paymentPointId), Number(this.state.destinationId), this.state.amount, this.state.clientToken,
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
        } catch (error) {
            this.notification.add(serverErrorMessage(error, _t("Could not save Representative Petty Cash.")), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    async saveReturn() {
        if (this.state.saving) return;
        if (!this.state.returnOriginId || !this.state.returnPaymentPointId || !this.state.returnAmount) {
            this.notification.add(_t("Choose the original movement, payment point, and amount."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("baseer.procurement.representative.advance", "submit_return", [
                Number(this.state.returnOriginId), Number(this.state.returnPaymentPointId), this.state.returnAmount, this.state.returnClientToken,
            ]);
            this.state.returnOriginId = "";
            this.state.returnPaymentPointId = "";
            this.state.returnAmount = "";
            this.state.returnClientToken = newClientToken();
            await this.load();
            this.notification.add(_t("Returned cash was saved."), { type: "success" });
        } catch (error) {
            this.notification.add(serverErrorMessage(error, _t("Could not save returned cash.")), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add("baseer_procurement_requests.representative_petty_cash", RepresentativePettyCash);

/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
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

export class RepresentativePettyCash extends Component {
    static template = "baseer_procurement_requests.RepresentativePettyCash";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.proofInput = useRef("proofInput");
        this.state = useState({
            loading: true, saving: false, error: false, data: false,
            representativeId: "", monthStart: "", destinationId: "", requestId: "", paymentPointId: "", amount: "", movementDate: today(), externalReference: "", proof: false, proofName: "", proofLoading: false, clientToken: newClientToken(),
            returnOriginId: "", returnPaymentPointId: "", returnAmount: "", returnClientToken: newClientToken(),
        });
        onWillStart(() => this.load());
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
            this.state.error = error?.data?.message || error?.data?.arguments?.[0]
                || error.message || _t("Could not load Representative Petty Cash.");
        } finally {
            this.state.loading = false;
        }
    }

    onRepresentativeChange(event) {
        this.state.representativeId = event.target.value;
        this.state.destinationId = "";
        this.state.requestId = "";
        this.load();
    }

    onMonthChange(event) {
        this.state.monthStart = event.target.value ? `${event.target.value}-01` : "";
        this.load();
    }

    onRequestChange(event) {
        this.state.requestId = event.target.value;
        const request = this.selectedRequest();
        if (request) this.state.destinationId = String(request.representative_id);
    }

    selectedRequest() {
        return this.state.data?.requests.find((request) => request.id === Number(this.state.requestId));
    }

    money(amount) {
        const value = Number(amount || 0).toLocaleString("en-US-u-nu-latn", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        const { currency_symbol: symbol, currency_position: position } = this.state.data || {};
        return position === "before" ? `${symbol} ${value}` : `${value} ${symbol || ""}`;
    }

    onPaymentPointChange(event) { this.state.paymentPointId = event.target.value; }
    onAmountInput(event) { this.state.amount = event.target.value; }
    onMovementDateInput(event) { this.state.movementDate = event.target.value; }
    onExternalReferenceInput(event) { this.state.externalReference = event.target.value; }

    onProofChange(event) {
        const [file] = event.target.files || [];
        this.state.proof = false;
        this.state.proofName = file?.name || "";
        if (!file) return;
        this.state.proofLoading = true;
        const reader = new FileReader();
        reader.onload = () => {
            this.state.proof = String(reader.result || "").split(",")[1] || false;
            this.state.proofLoading = false;
        };
        reader.onerror = () => {
            this.state.proof = false;
            this.state.proofLoading = false;
            this.notification.add(_t("Could not read the transfer proof."), { type: "danger" });
        };
        reader.readAsDataURL(file);
    }

    async save() {
        if (this.state.saving) return;
        if (!this.state.requestId || !this.state.paymentPointId || !this.state.destinationId || !this.state.amount || !this.state.movementDate || !this.state.externalReference || !this.state.proof || this.state.proofLoading) {
            this.notification.add(_t("Complete the request, payment point, destination, amount, transfer date, reference, and proof."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("baseer.procurement.representative.advance", "submit_funding", [
                Number(this.state.requestId), Number(this.state.paymentPointId), Number(this.state.destinationId), this.state.amount, this.state.clientToken,
                this.state.movementDate, this.state.externalReference, this.state.proof, this.state.proofName,
            ]);
            this.state.requestId = "";
            this.state.paymentPointId = "";
            this.state.destinationId = "";
            this.state.amount = "";
            this.state.movementDate = today();
            this.state.externalReference = "";
            this.state.proof = false;
            this.state.proofName = "";
            if (this.proofInput.el) this.proofInput.el.value = "";
            this.state.clientToken = newClientToken();
            await this.load();
            this.notification.add(_t("Representative Petty Cash was saved."), { type: "success" });
        } catch (error) {
            this.notification.add(error.message || _t("Could not save Representative Petty Cash."), { type: "danger" });
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
            this.notification.add(error.message || _t("Could not save returned cash."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add("baseer_procurement_requests.representative_petty_cash", RepresentativePettyCash);

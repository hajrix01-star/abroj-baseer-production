import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useAutofocus } from "@web/core/utils/hooks";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { discountStorageKey, pendingDiscount, needsDiscountRefund, executeDiscountIntent, submitDiscount } from "./discount_flow";

const frozenMessage = () => _t("Remove the invoice discount before changing items, prices or customer details.");
const pendingMessage = () => _t("The discount needs verification. Reconnect and check its result before payment.");
function isDiscountFrozen(order) {
    return Boolean(order && (order.baseer_global_discount_locked || (order.config_id && localStorage.getItem(
        discountStorageKey(session.db || "", order.config_id.id, order.uuid)
    ))));
}
function explainFrozen(pos) {
    pos.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: frozenMessage() });
}

export class BaseerGlobalDiscountDialog extends Component {
    static template = "baseer_pos_global_discount.Dialog";
    static components = { Dialog };
    static props = { close: Function, getPayload: Function, locked: Boolean, refund: Boolean };
    setup() {
        this.state = useState({ kind: "fixed", value: "" });
        useAutofocus({ mobile: true });
    }
    confirm() {
        this.props.getPayload({ kind: this.state.kind, value: this.state.value });
        this.props.close();
    }
    onValueKeydown(event) {
        if (event.key === "Enter" && !event.repeat) {
            event.preventDefault();
            this.confirm();
        }
    }
    remove() {
        this.props.getPayload({ kind: "remove", value: "0" });
        this.props.close();
    }
}

patch(PosStore.prototype, {
    baseerDiscountKey(order) { return discountStorageKey(session.db || "", this.config.id, order.uuid); },
    async setup() {
        await super.setup(...arguments);
        const prefix = discountStorageKey(session.db || "", this.config.id, "");
        for (const key of Object.keys(localStorage).filter((item) => item.startsWith(prefix))) {
            try { await executeDiscountIntent(this, JSON.parse(localStorage.getItem(key))); }
            catch { this.notification.add(pendingMessage(), { type: "warning", sticky: true }); }
        }
    },
    async baseerSubmitDiscount(order, request) {
        if (this._baseerDiscountRunning) return false;
        this._baseerDiscountRunning = true;
        this.env.services.ui.block();
        try {
            return await submitDiscount(this, order, request);
        } catch (error) {
            // A definite Odoo rejection cannot have committed this transaction.
            // Read canonical state before dropping its durable recovery intent.
            if (error?.data?.name?.startsWith("odoo.exceptions.")) {
                try {
                    const result = await this.data.call("pos.order", "baseer_read_global_discount_state", [[order.id]]);
                    await this.baseerReconcileProtectedState(result, order.uuid);
                    localStorage.removeItem(this.baseerDiscountKey(order));
                } catch { /* Keep the payment block when the read also fails. */ }
            }
            this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: error?.data?.message || error?.message || pendingMessage() });
            return false;
        } finally {
            this.env.services.ui.unblock();
            this._baseerDiscountRunning = false;
        }
    },
    async applyDiscount(percent, order = this.getOrder()) {
        // Historical native discounts keep their own native refund behavior,
        // even after the shop enables this new command for subsequent sales.
        if (isDiscountFrozen(order) || needsDiscountRefund(order)) return;
        return super.applyDiscount(...arguments);
    },
    async addLineToOrder(vals, order, ...args) {
        if (isDiscountFrozen(order)) {
            explainFrozen(this);
            return false;
        }
        return super.addLineToOrder(vals, order, ...args);
    },
    async selectPartner(order = this.getOrder()) {
        if (isDiscountFrozen(order)) { explainFrozen(this); return false; }
        return super.selectPartner(...arguments);
    },
    setPartnerToCurrentOrder() {
        if (isDiscountFrozen(this.getOrder())) { explainFrozen(this); return; }
        return super.setPartnerToCurrentOrder(...arguments);
    },
    async selectPreset(preset = false, order = this.getOrder()) {
        if (isDiscountFrozen(order)) { explainFrozen(this); return false; }
        return super.selectPreset(...arguments);
    },
});

patch(ControlButtons.prototype, {
    async clickBaseerGlobalDiscount() {
        const order = this.pos.getOrder();
        if (pendingDiscount(this.pos, order)) return this.pos.baseerSubmitDiscount(order, {});
        const request = await makeAwaitable(this.dialog, BaseerGlobalDiscountDialog, {
            locked: Boolean(order.baseer_global_discount_locked), refund: Boolean(order.is_refund),
        });
        if (request) await this.pos.baseerSubmitDiscount(order, request);
    },
    async clickDiscount() {
        const order = this.pos.getOrder();
        if (this.pos.config.baseer_global_discount_enabled || isDiscountFrozen(order)) return this.clickBaseerGlobalDiscount();
        return super.clickDiscount(...arguments);
    },
    async clickFiscalPosition() {
        if (isDiscountFrozen(this.currentOrder)) { explainFrozen(this.pos); return; }
        return super.clickFiscalPosition(...arguments);
    },
    async clickPricelist() {
        if (isDiscountFrozen(this.currentOrder)) { explainFrozen(this.pos); return; }
        return super.clickPricelist(...arguments);
    },
});

patch(PosOrder.prototype, {
    serializeForORM() {
        const key = discountStorageKey(session.db || "", this.config_id.id, this.uuid);
        if (localStorage.getItem(key)) throw new Error(pendingMessage());
        return super.serializeForORM(...arguments);
    },
    removeOrderline(line) {
        if (isDiscountFrozen(this)) return false;
        return super.removeOrderline(...arguments);
    },
    setPartner(partner) {
        if (isDiscountFrozen(this) && partner !== this.partner_id) return;
        return super.setPartner(...arguments);
    },
    setPricelist(pricelist) {
        if (isDiscountFrozen(this) && pricelist !== this.pricelist_id) return;
        return super.setPricelist(...arguments);
    },
    setPreset() {
        if (isDiscountFrozen(this)) return;
        return super.setPreset(...arguments);
    },
});

patch(PosOrderline.prototype, {
    setQuantity(quantity) {
        if (isDiscountFrozen(this.order_id) && quantity !== this.qty) return false;
        return super.setQuantity(...arguments);
    },
    setUnitPrice(price) {
        if (isDiscountFrozen(this.order_id) && price !== this.price_unit) return;
        return super.setUnitPrice(...arguments);
    },
    setDiscount(discount) {
        if (isDiscountFrozen(this.order_id) && discount !== this.discount) return;
        return super.setDiscount(...arguments);
    },
});

patch(TicketScreen.prototype, {
    _onUpdateSelectedOrderline() {
        const line = this.getSelectedOrder()?.lines.find((item) => item.id === this.getSelectedOrderlineId());
        if (line?.baseer_global_discount_line) {
            this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: _t("Select the original item to refund. Its discount is included automatically.") });
            return;
        }
        return super._onUpdateSelectedOrderline(...arguments);
    },
    _getRefundableDetails() {
        return super._getRefundableDetails(...arguments).filter((detail) => !detail.line.baseer_global_discount_line);
    },
    async addAdditionalRefundInfo(original, destination) {
        await super.addAdditionalRefundInfo(...arguments);
        if (original.baseer_global_discount_locked) {
            const prepared = await this.pos.baseerSubmitDiscount(destination, { refund: true });
            if (!prepared) throw new Error(pendingMessage());
        }
    },
});

patch(OrderSummary.prototype, {
    async updateSelectedOrderline() {
        if (isDiscountFrozen(this.currentOrder)) { this.numberBuffer.reset(); explainFrozen(this.pos); return; }
        return super.updateSelectedOrderline(...arguments);
    },
    _setValue() {
        if (isDiscountFrozen(this.currentOrder)) { this.numberBuffer.reset(); explainFrozen(this.pos); return; }
        return super._setValue(...arguments);
    },
});

patch(PaymentScreen.prototype, {
    async validateOrder() {
        const order = this.currentOrder;
        if (this.pos._baseerDiscountRunning || pendingDiscount(this.pos, order)
            || (needsDiscountRefund(order) && !order.baseer_global_discount_locked)) {
            this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: pendingMessage() });
            return;
        }
        return super.validateOrder(...arguments);
    },
});

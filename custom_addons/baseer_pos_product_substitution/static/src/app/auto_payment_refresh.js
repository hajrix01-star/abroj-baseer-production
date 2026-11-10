/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosPayment } from "@point_of_sale/app/models/pos_payment";

// Ephemeral provenance, deliberately excluded from both order and server state.
// Losing it (reload or eviction) always disables automatic changes.
const automaticPayments = new Map();
const internalOrders = new Set();
const MAX_ORIGINS = 200;

function clearAutomatic(order) {
    if (order?.uuid && !internalOrders.has(order.uuid)) automaticPayments.delete(order.uuid);
}

function internally(order, action) {
    if (!order?.uuid) return action();
    const alreadyInternal = internalOrders.has(order.uuid);
    internalOrders.add(order.uuid);
    try { return action(); }
    finally { if (!alreadyInternal) internalOrders.delete(order.uuid); }
}

function methodIsPlain(method) {
    return !!method && method.type === "bank" && !method.is_cash_count && !method.is_online_payment &&
        !method.use_payment_terminal && !method.payment_terminal &&
        (!method.payment_method_type || method.payment_method_type === "none");
}

function isEligible(screen, order, line, method) {
    const methods = screen.payment_methods_from_config || [];
    const configId = screen.pos.config?.id;
    const sessionId = order?.session_id?.id;
    return !!(order?.uuid && order.state === "draft" && !order.isRefund &&
        !order.isRefundInProcess?.() && configId && sessionId &&
        order.config_id?.id === configId && methods.some((item) => item.id === method?.id) &&
        (screen.pos.config.payment_method_ids || []).some((item) => item.id === method?.id) && methodIsPlain(method) &&
        order.payment_ids?.length === 1 && order.payment_ids[0] === line &&
        line?.uuid && !line.payment_status && !line.is_change &&
        Number.isFinite(line.getAmount()));
}

function rememberAutomatic(screen, order) {
    const line = order?.payment_ids?.[0];
    const method = line?.payment_method_id;
    if (!isEligible(screen, order, line, method)) return;
    automaticPayments.delete(order.uuid);
    automaticPayments.set(order.uuid, {
        orderUuid: order.uuid, paymentUuid: line.uuid, methodId: method.id,
        configId: screen.pos.config.id, sessionId: order.session_id.id,
        amount: line.getAmount(), confirmed: false,
    });
    while (automaticPayments.size > MAX_ORIGINS) automaticPayments.delete(automaticPayments.keys().next().value);
}

function refreshAutomatic(screen, order) {
    const origin = automaticPayments.get(order?.uuid);
    if (!origin) return false;
    if (!origin.confirmed) return false;
    const line = order.payment_ids?.[0];
    const method = line?.payment_method_id;
    if (!isEligible(screen, order, line, method) || origin.orderUuid !== order.uuid ||
        origin.paymentUuid !== line.uuid || origin.methodId !== method.id ||
        origin.configId !== screen.pos.config.id || origin.sessionId !== order.session_id.id ||
        origin.amount !== line.getAmount()) {
        automaticPayments.delete(order.uuid);
        return false;
    }
    const original = line.getAmount();
    let next;
    try {
        // Synchronous only. This is the same native setAmount(0) pattern used by
        // Odoo's payment screen; no backend or ORM operation occurs here.
        internally(order, () => {
            let committed = false;
            try {
                line.setAmount(0);
                next = order.getDefaultAmountDueToPayIn(method);
                if (!Number.isFinite(next) || next < 0) throw new Error("Invalid automatic payment amount");
                line.setAmount(next);
                screen.numberBuffer.set(line.getAmount().toString());
                committed = true;
            } finally {
                if (!committed) line.setAmount(original);
            }
        });
    } catch {
        automaticPayments.delete(order.uuid);
        return false;
    }
    origin.amount = line.getAmount();
    return true;
}

patch(PosPayment.prototype, {
    setAmount() {
        clearAutomatic(this.pos_order_id);
        return super.setAmount(...arguments);
    },
});

patch(PosOrder.prototype, {
    addPaymentline() { clearAutomatic(this); return super.addPaymentline(...arguments); },
    removePaymentline() { clearAutomatic(this); return super.removePaymentline(...arguments); },
});

patch(PaymentScreen.prototype, {
    onMounted() {
        const order = this.currentOrder;
        if (!order || this.pos.getOrder()?.uuid !== order.uuid) {
            return super.onMounted(...arguments);
        }
        const hadPayment = order.payment_ids.length > 0;
        const result = internally(order, () => super.onMounted(...arguments));
        if (hadPayment) refreshAutomatic(this, order);
        return result;
    },
    addNewPaymentLine(method) {
        const order = this.currentOrder;
        const startedEmpty = order?.payment_ids?.length === 0;
        clearAutomatic(order);
        // QA's native implementation creates the line synchronously before
        // returning its promise. An online payment is never eligible.
        const result = super.addNewPaymentLine(...arguments);
        if (startedEmpty && methodIsPlain(method) && result?.then &&
            order.payment_ids?.[0]?.payment_method_id?.id === method.id) {
            rememberAutomatic(this, order);
            const origin = automaticPayments.get(order.uuid);
            if (origin) {
                void result.then((success) => {
                    if (automaticPayments.get(order.uuid) !== origin) return;
                    if (success === true) origin.confirmed = true;
                    else automaticPayments.delete(order.uuid);
                }, () => {
                    if (automaticPayments.get(order.uuid) === origin) automaticPayments.delete(order.uuid);
                });
            }
        }
        return result;
    },
    updateSelectedPaymentline() { clearAutomatic(this.currentOrder); return super.updateSelectedPaymentline(...arguments); },
    deletePaymentLine() { clearAutomatic(this.currentOrder); return super.deletePaymentLine(...arguments); },
});

patch(OrderPaymentValidation.prototype, {
    async isOrderValid() {
        const order = this.order;
        clearAutomatic(order);
        const hasConfiguredCash = (this.pos.config.payment_method_ids || []).some((method) => method.is_cash_count);
        if (!order.isRefund && !hasConfiguredCash && !this.pos.currency.isZero(order.change)) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Cannot return change without a cash payment method"),
                body: _t("There is no cash payment method available in this point of sale to handle the change.\n\n Please pay the exact amount or add a cash payment method in the point of sale configuration"),
            });
            return false;
        }
        return super.isOrderValid(...arguments);
    },
});

import { _t } from "@web/core/l10n/translation";

export function discountStorageKey(database, configId, orderUuid) {
    return `baseer.discount.v1:${database}:${configId}:${orderUuid}`;
}

export function pendingDiscount(pos, order) {
    if (!order) return null;
    const raw = localStorage.getItem(pos.baseerDiscountKey(order));
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return { invalid: true }; }
}

export function needsDiscountRefund(order) {
    return Boolean(order?.is_refund && order.lines?.some((line) =>
        line.refunded_orderline_id?.order_id?.baseer_global_discount_locked
    ));
}

export async function executeDiscountIntent(pos, intent) {
    if (!intent || intent.invalid) throw new Error(_t("The discount needs verification. Reconnect and reload this order."));
    const args = intent.method === "baseer_prepare_global_discount_refund"
        ? [[intent.orderId], intent.actionUuid, intent.revision]
        : [[intent.orderId], intent.kind, intent.value, intent.reason, intent.actionUuid, intent.revision];
    const result = await pos.data.call("pos.order", intent.method, args);
    if (!result?.accepted || result.action_uuid !== intent.actionUuid) {
        throw new Error(_t("The server did not confirm the discount. Check its result before payment."));
    }
    // Reuse the established canonical loader, including acknowledged deletions
    // and durable IndexedDB persistence. Never reconstruct financial values here.
    const order = await pos.baseerReconcileProtectedState(result, intent.orderUuid);
    localStorage.removeItem(pos.baseerDiscountKey(order));
    return order;
}

export async function submitDiscount(pos, order, request) {
    if (pos.data.network.offline) throw new Error(_t("Reconnect before applying, removing or refunding a discount."));
    if (pendingDiscount(pos, order)) return executeDiscountIntent(pos, pendingDiscount(pos, order));
    if (order.payment_ids?.length || pos.paymentTerminalInProgress || order.electronicPaymentInProgress?.()) {
        throw new Error(_t("Remove payment lines before changing the discount."));
    }
    if (pos.baseerHasPendingProtectedAction(order) || !(await pos.baseerResolvePendingKitchenAction(order))) {
        throw new Error(_t("Confirm pending item or kitchen changes first."));
    }
    // The installed Saudi anonymous-consumer policy normally runs at payment.
    // Resolve it before the fiscal snapshot freezes the customer/tax identity.
    if (!request.refund && !order.baseer_global_discount_locked) order.baseerAssignAnonymousB2cPartner?.();
    const synced = await pos.syncAllOrders({ orders: [order], force: true, throw: true });
    const acknowledged = synced?.find((item) => item.uuid === order.uuid);
    const revision = acknowledged?.baseer_protected_revision || acknowledged?.raw?.baseer_protected_revision;
    if (!acknowledged?.isSynced || !revision) throw new Error(_t("The draft is still saving. Wait, then try again."));
    const intent = {
        orderId: acknowledged.id, orderUuid: order.uuid, revision,
        actionUuid: crypto.randomUUID(),
        method: request.refund ? "baseer_prepare_global_discount_refund" : "baseer_apply_global_discount",
        kind: request.kind, value: request.value || "0", reason: request.reason || "",
    };
    // The intent must survive a lost response and browser restart.
    localStorage.setItem(pos.baseerDiscountKey(order), JSON.stringify(intent));
    return executeDiscountIntent(pos, intent);
}

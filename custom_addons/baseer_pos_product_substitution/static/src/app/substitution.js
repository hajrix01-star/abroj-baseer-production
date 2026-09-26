/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { PosData } from "@point_of_sale/app/services/data_service";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";

function pendingPrefix(configId) {
    return `baseer.protected.v2:${session.db || ""}:${configId}:`;
}

function pendingKey(order) {
    return `${pendingPrefix(order.config_id.id)}${order.uuid}`;
}

function readPending(order) {
    if (!order?.config_id?.id || !order.uuid) return null;
    const value = localStorage.getItem(pendingKey(order));
    if (!value) return null;
    try {
        return JSON.parse(value);
    } catch {
        // Never turn an unreadable recovery record into permission to pay.
        return { invalid: true };
    }
}

function unsettledMessage() {
    return _t("The previous edit has not been confirmed. Reconnect and check its result before changing or paying this order.");
}

export class BaseerSubstitutionPopup extends Component {
    static template = "baseer_pos_product_substitution.SubstitutionPopup";
    static components = { Dialog };
    static props = { line: Object, products: Array, getPayload: Function, close: Function };

    setup() {
        this.state = useState({ quantities: {}, note: "" });
    }
    get selectedProducts() {
        return this.props.products
            .map((product) => ({ product, quantity: Number(this.state.quantities[product.id] || 0) }))
            .filter((item) => item.quantity > 0);
    }
    increase(product) {
        this.state.quantities[product.id] = Number(this.state.quantities[product.id] || 0) + 1;
    }
    decrease(product) {
        this.state.quantities[product.id] = Math.max(0, Number(this.state.quantities[product.id] || 0) - 1);
    }
    confirm() {
        this.props.getPayload({ replacements: this.selectedProducts, reasonNote: this.state.note.trim() });
        this.props.close();
    }
}

function productFromId(pos, value) {
    const products = pos?.data?.models?.["product.product"] || pos?.models?.["product.product"];
    return products?.get(typeof value === "number" ? value : value?.id) || (value?.id ? value : null);
}

function substitutionPolicy(line, pos) {
    const id = typeof line?.product_id === "number" ? line.product_id : line?.product_id?.id;
    return (pos?.config?.baseer_substitution_policies || []).find((item) => item.source_product_id === id);
}

function isProtectedLine(line, pos) {
    const product = productFromId(pos, line?.product_id);
    const enabled = pos?.config?.baseer_substitution_enabled ?? line?.order_id?.config_id?.baseer_substitution_enabled;
    return Boolean(enabled && line?.order_id && !line.order_id.finalized && (
        substitutionPolicy(line, pos) || product?.baseer_substitution_enabled || product?.product_tmpl_id?.baseer_substitution_enabled
    ));
}

function substitutionLock(line, pos) {
    if (!line?.uuid) return null;
    if (Number(line.baseer_substitution_minimum_quantity) > 0) return Number(line.baseer_substitution_minimum_quantity);
    const order = line.order_id;
    const policies = order?.baseer_protected_line_policy || order?.raw?.baseer_protected_line_policy;
    const current = policies?.[line.uuid]?.minimum_quantity;
    if (Number(current) > 0) return Number(current);
    // Compatibility with older drafts; accepted locks outlive the feature switch.
    const previous = line.uiState?.baseerSubstitutionMinimumQuantity;
    if (Number(previous) > 0) return Number(previous);
    const stored = (pos?.config?.baseer_substitution_locked_lines || []).find((item) => item.line_uuid === line.uuid);
    return Number(stored?.minimum_quantity) > 0 ? Number(stored.minimum_quantity) : null;
}

function isSubstitutionOutputLine(line, pos) {
    return Boolean(substitutionLock(line, pos) && line?.order_id && !line.order_id.finalized);
}

function isBelowSubstitutionMinimum(line, quantity, pos) {
    const minimum = substitutionLock(line, pos);
    return minimum !== null && (!Number.isFinite(quantity) || quantity < minimum - 0.000001);
}

patch(PosData.prototype, {
    async getCachedServerDataFromIndexedDB() {
        return (await super.getCachedServerDataFromIndexedDB(...arguments)) || {};
    },
});

patch(PosOrder.prototype, {
    serializeForORM() {
        if (readPending(this)) throw new Error(unsettledMessage());
        const data = super.serializeForORM(...arguments);
        // Legacy transient intents must never be replayed by payment/autosync.
        delete data.baseer_substitution_action;
        delete data.baseer_protected_item_cancellation_action;
        return data;
    },
});

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        await this.baseerRecoverProtectedActions();
    },

    baseerHasPendingProtectedAction(order) {
        return Boolean(readPending(order));
    },

    async baseerResolvePendingKitchenAction(order) {
        if (!order?.uiState?.baseerPreparationOutcomeUnknown) {
            return true;
        }
        if (await this.baseerResolvePreparationOutcome(order)) {
            return true;
        }
        this.dialog.add(AlertDialog, {
            title: _t("Confirmation required"),
            body: _t("Confirm the pending kitchen action before editing or cancelling this item."),
        });
        return false;
    },

    async syncAllOrders(options = {}) {
        const pending = this.getPendingOrder();
        const requested = options.orders || [...pending.orderToCreate, ...pending.orderToUpdate];
        const blocked = requested.filter((order) => readPending(order));
        if (blocked.length && options.throw) throw new Error(unsettledMessage());
        return super.syncAllOrders({ ...options, orders: requested.filter((order) => !readPending(order)) });
    },

    async pay() {
        if (readPending(this.getOrder())) {
            await this.baseerRetryProtectedAction(this.getOrder());
            return;
        }
        return super.pay(...arguments);
    },

    async addLineToOrder(vals, order) {
        if (!(await this.baseerResolvePendingKitchenAction(order))) {
            return;
        }
        if (readPending(order)) {
            await this.baseerRetryProtectedAction(order);
            return;
        }
        return super.addLineToOrder(...arguments);
    },

    async baseerRecoverProtectedActions() {
        const prefix = pendingPrefix(this.config.id);
        const keys = Object.keys(localStorage).filter((key) => key.startsWith(prefix));
        for (const key of keys) {
            try {
                const intent = JSON.parse(localStorage.getItem(key));
                if (!intent?.orderId || !intent.action?.action_uuid) continue;
                await this.baseerExecuteProtectedIntent(intent, key, false);
            } catch {
                this.notification.add(unsettledMessage(), { type: "warning", sticky: true });
            }
        }
    },

    async baseerRetryProtectedAction(order) {
        const intent = readPending(order);
        if (!intent || intent.invalid) {
            this.dialog.add(AlertDialog, { title: _t("Confirmation required"), body: unsettledMessage() });
            return false;
        }
        return this.baseerExecuteProtectedIntent(intent, pendingKey(order));
    },

    async baseerReconcileProtectedState(result, orderUuid) {
        const data = result.data;
        const rawOrder = data?.["pos.order"]?.find((item) => item.uuid === orderUuid);
        if (!rawOrder || !Array.isArray(data["pos.order.line"])) throw new Error(_t("The server did not return the complete order. Check the result again."));
        const localOrder = this.models["pos.order"].getBy("uuid", orderUuid);
        const serverLineUuids = new Set(data["pos.order.line"].map((line) => line.uuid));
        const stale = [...(localOrder?.lines || [])].filter((line) => !serverLineUuids.has(line.uuid));
        const complete = await this.data.missingRecursive(data);
        for (const line of stale) {
            await this.data.deleteRecordsInIndexedDB("pos.order.line", [line.uuid]);
            line.delete({ silent: true });
        }
        // Native model deletion still records relation commands even when silent.
        // Drain those acknowledged commands BEFORE canonical loading, as Odoo's
        // syncAllOrders does, so they cannot leak into the next payment payload.
        if (localOrder) this.models["pos.order"].serializeForORM(localOrder);
        const loaded = this.models.loadConnectedData(complete);
        const order = loaded["pos.order"].find((item) => item.uuid === orderUuid);
        delete order.uiState.baseerSubstitutionAction;
        delete order.uiState.baseerProtectedItemCancellationAction;
        delete order.uiState.baseerPreparationAction;
        order.uiState.selected_orderline_uuid = order.lines[0]?.uuid;
        this.removePendingOrder(order);
        // Keep acknowledgement durable before releasing the pending intent.
        await this.data.synchronizeLocalDataInIndexedDB();
        if (order.state === "cancel" && this.getOrder()?.uuid === order.uuid) {
            this.showDefault();
        }
        return order;
    },

    async baseerExecuteProtectedIntent(intent, key, showFeedback = true) {
        if (this._baseerProtectedCommandRunning) return false;
        this._baseerProtectedCommandRunning = true;
        this.env.services.ui.block();
        try {
            const result = await this.data.call("pos.order", "baseer_apply_protected_action", [
                [intent.orderId], intent.kind, intent.action, intent.expectedRevision,
            ]);
            if (!result?.accepted || result.action_uuid !== intent.action.action_uuid) {
                throw new Error(_t("The server did not confirm this action. Check the result again."));
            }
            await this.baseerReconcileProtectedState(result, intent.orderUuid);
            localStorage.removeItem(key);
            if (showFeedback) this.notification.add(intent.kind === "cancel" ? _t("The cancellation was recorded.") : _t("The edit was recorded."), { type: "success" });
            return true;
        } catch (error) {
            // An explicit Odoo transaction rejection is distinct from an unknown
            // transport outcome. Read the canonical order; never restore an old copy.
            if (error?.data?.name?.startsWith("odoo.exceptions.")) {
                try {
                    const state = await this.data.call("pos.order", "baseer_read_protected_state", [[intent.orderId]]);
                    await this.baseerReconcileProtectedState(state, intent.orderUuid);
                    localStorage.removeItem(key);
                } catch { /* Keep recovery record and payment block until confirmed. */ }
            }
            if (showFeedback) this.dialog.add(AlertDialog, {
                title: _t("Action requires verification"),
                body: error?.data?.message || error?.message || unsettledMessage(),
            });
            else this.notification.add(unsettledMessage(), { type: "warning", sticky: true });
            return false;
        } finally {
            this._baseerProtectedCommandRunning = false;
            this.env.services.ui.unblock();
        }
    },

    async baseerSubmitProtectedAction(line, kind, action) {
        const order = line.order_id;
        if (readPending(order)) return this.baseerRetryProtectedAction(order);
        if (this._baseerProtectedSubmissionRunning) return false;
        if (!(await this.baseerResolvePendingKitchenAction(order))) {
            return false;
        }
        if (order.uiState?.baseerPreparationAction) {
            this.dialog.add(AlertDialog, { title: _t("Confirmation required"), body: _t("Confirm the pending kitchen action before editing or cancelling this item.") });
            return false;
        }
        if (this.data.network.offline) {
            this.dialog.add(AlertDialog, { title: _t("Connection required"), body: _t("Reconnect before editing or cancelling this item.") });
            return false;
        }
        this._baseerProtectedSubmissionRunning = true;
        try {
            // Persist ordinary draft changes first, without modifying the source.
            // Native sync can skip in-flight orders: require a real acknowledgement.
            const synced = await this.syncAllOrders({ orders: [order], force: true, throw: true });
            const acknowledged = synced?.find((item) => item.uuid === order.uuid);
            const revision = acknowledged?.baseer_protected_revision || acknowledged?.raw?.baseer_protected_revision;
            if (!acknowledged?.isSynced || !revision) throw new Error(_t("The draft is still saving. Wait, then try again."));
            const intent = {
                orderId: acknowledged.id, orderUuid: order.uuid, kind,
                action: { ...action, action_uuid: crypto.randomUUID(), source_line_uuid: line.uuid },
                expectedRevision: revision,
            };
            // A durable intent is required before the command can leave the device.
            const key = pendingKey(acknowledged);
            localStorage.setItem(key, JSON.stringify(intent));
            return await this.baseerExecuteProtectedIntent(intent, key);
        } catch (error) {
            this.dialog.add(AlertDialog, { title: _t("Draft order was not saved"), body: error?.data?.message || error?.message || _t("The draft is still saving. Wait, then try again.") });
            return false;
        } finally {
            this._baseerProtectedSubmissionRunning = false;
        }
    },

    async baseerAskProtectedCancellationReason() {
        const reasonCode = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Cancellation reason"),
            list: [
                ["customer_cancelled", _t("Customer cancelled")], ["wrong_order", _t("Wrong order")],
                ["duplicate_order", _t("Duplicate order")], ["unavailable_item", _t("Item unavailable")],
                ["staff_error", _t("Staff error")], ["other", _t("Other")],
            ].map(([id, label]) => ({ id, label, item: id })),
        });
        if (!reasonCode) return null;
        let reasonNote = "";
        if (reasonCode === "other") {
            reasonNote = await makeAwaitable(this.dialog, TextInputPopup, { title: _t("Cancellation reason"), placeholder: _t("Describe the reason"), startingValue: "" });
            if (!reasonNote?.trim()) return null;
        }
        return { reason_code: reasonCode, reason_note: reasonNote.trim() };
    },

    async baseerOpenProtectedItemActions(line) {
        if (readPending(line.order_id)) return this.baseerRetryProtectedAction(line.order_id);
        const action = await makeAwaitable(this.dialog, SelectionPopup, {
            title: line.getFullProductName(),
            list: [{ id: "edit", label: _t("Edit"), item: "edit" }, { id: "cancel", label: _t("Cancel item"), item: "cancel" }],
        });
        if (action === "edit") return this.baseerOpenSubstitution(line);
        if (action === "cancel") return this.baseerCancelProtectedItem(line);
        return false;
    },

    async baseerCancelProtectedItem(line) {
        if (!isProtectedLine(line, this)) return false;
        const reason = await this.baseerAskProtectedCancellationReason();
        return reason ? this.baseerSubmitProtectedAction(line, "cancel", reason) : false;
    },

    async baseerOpenSubstitution(line) {
        if (!isProtectedLine(line, this)) return false;
        if (readPending(line.order_id)) return this.baseerRetryProtectedAction(line.order_id);
        const source = productFromId(this, line.product_id);
        const ids = source?.baseer_substitution_product_ids_json || source?.product_tmpl_id?.baseer_substitution_product_ids_json || substitutionPolicy(line, this)?.replacement_product_ids || [];
        const products = ids.map((id) => productFromId(this, id)).filter(Boolean);
        if (!products.length) {
            this.dialog.add(AlertDialog, { title: _t("No allowed alternatives"), body: _t("Ask a manager to configure allowed alternatives for this item.") });
            return false;
        }
        const choice = await makeAwaitable(this.dialog, BaseerSubstitutionPopup, { line, products });
        if (!choice?.replacements?.length) return false;
        return this.baseerSubmitProtectedAction(line, "edit", {
            reason_note: choice.reasonNote,
            replacements: choice.replacements.map(({ product, quantity }) => ({ product_id: product.id, quantity, line_uuid: crypto.randomUUID() })),
        });
    },

    async baseerOpenLineActions(line) {
        if (readPending(line?.order_id)) return this.baseerRetryProtectedAction(line.order_id);
        if (isSubstitutionOutputLine(line, this)) {
            this.dialog.add(AlertDialog, { title: _t("Approved alternative"), body: _t("This item is part of an approved edit. It cannot be removed or edited again.") });
            return false;
        }
        if (isProtectedLine(line, this)) return this.baseerOpenProtectedItemActions(line);
        return super.baseerOpenLineActions(...arguments);
    },
    baseerIsSubstitutionProtected(line) { return isProtectedLine(line, this); },
    baseerIsSubstitutionOutputLine(line) { return isSubstitutionOutputLine(line, this); },
});

patch(PaymentScreen.prototype, {
    async validateOrder() {
        if (!(await this.pos.baseerResolvePendingKitchenAction(this.pos.getOrder()))) {
            return;
        }
        if (this.pos.baseerHasPendingProtectedAction(this.pos.getOrder())) {
            await this.pos.baseerRetryProtectedAction(this.pos.getOrder());
            return;
        }
        return super.validateOrder(...arguments);
    },
});

patch(OrderSummary.prototype, {
    async updateSelectedOrderline({ buffer, key }) {
        let line = this.currentOrder?.getSelectedOrderline();
        if (line?.combo_parent_id) line = line.combo_parent_id;
        if (!(await this.pos.baseerResolvePendingKitchenAction(line?.order_id))) {
            this.numberBuffer.reset();
            return;
        }
        if (readPending(line?.order_id)) {
            this.numberBuffer.reset();
            await this.pos.baseerRetryProtectedAction(line.order_id);
            return;
        }
        const quantity = buffer === null ? 0 : Number(buffer);
        if (isSubstitutionOutputLine(line, this.pos) && (this.pos.numpadMode !== "quantity" || isBelowSubstitutionMinimum(line, quantity, this.pos))) {
            this.numberBuffer.reset();
            this.pos.dialog.add(AlertDialog, { title: _t("Approved alternative"), body: _t("The approved price, discount and minimum quantity are protected.") });
            return;
        }
        if (isProtectedLine(line, this.pos) && this.pos.numpadMode === "quantity" && (key === "Backspace" || buffer === null || !Number.isFinite(quantity) || quantity < line.getQuantity())) {
            this.numberBuffer.reset();
            await this.pos.baseerOpenProtectedItemActions(line);
            return;
        }
        return super.updateSelectedOrderline(...arguments);
    },
    _setValue(value) {
        let line = this.currentOrder?.getSelectedOrderline();
        if (line?.combo_parent_id) line = line.combo_parent_id;
        if (readPending(line?.order_id)) { this.numberBuffer.reset(); return; }
        if (line?.order_id?.uiState?.baseerPreparationOutcomeUnknown) {
            this.numberBuffer.reset();
            void this.pos.baseerResolvePendingKitchenAction(line.order_id);
            return;
        }
        const quantity = value === "remove" ? 0 : Number(value);
        if (isSubstitutionOutputLine(line, this.pos) && (this.pos.numpadMode !== "quantity" || isBelowSubstitutionMinimum(line, quantity, this.pos))) {
            this.numberBuffer.reset();
            return;
        }
        if (isProtectedLine(line, this.pos) && this.pos.numpadMode === "quantity" && (!Number.isFinite(quantity) || quantity < line.getQuantity())) {
            this.numberBuffer.reset();
            void this.pos.baseerOpenProtectedItemActions(line);
            return;
        }
        return super._setValue(...arguments);
    },
});

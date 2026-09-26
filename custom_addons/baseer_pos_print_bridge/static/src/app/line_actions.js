/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog, AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ask, makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

const CANCELLATION_REASONS = [
    ["customer_cancelled", _t("Customer cancelled")],
    ["wrong_order", _t("Wrong order")],
    ["duplicate_order", _t("Duplicate order")],
    ["unavailable_item", _t("Item unavailable")],
    ["staff_error", _t("Staff error")],
    ["other", _t("Other")],
];

function clonePreparationState(order) {
    return JSON.parse(JSON.stringify(order.last_order_preparation_change || { lines: {} }));
}

function preparationLine(order, line) {
    const entries = Object.entries(order?.last_order_preparation_change?.lines || {});
    return entries.find(
        ([key, value]) => key === line?.uuid || key.startsWith(`${line?.uuid} `) || value?.uuid === line?.uuid
    )?.[1];
}

export function getBaseerSentQuantity(order, line) {
    const quantity = Number(preparationLine(order, line)?.quantity || 0) - getBaseerSilentQuantity(line);
    return Number.isFinite(quantity) ? Math.max(0, quantity) : 0;
}

function getBaseerSilentQuantity(line) {
    return Math.max(0, Number(line?.baseer_substitution_silent_quantity || 0));
}

function lineChangedSincePreparation(order, line, oldLine) {
    if (!oldLine) {
        return line.getQuantity() - getBaseerSilentQuantity(line) !== 0;
    }
    return line.getQuantity() !== Number(oldLine.quantity || 0);
}

export function buildBaseerPreparationAction(order, actionType = "send", explicitLines = null) {
    let lines = explicitLines;
    if (!lines) {
        // The browser reports quantity intent only. Odoo remains the sole
        // authority that decides whether a line has a kitchen route.
        const currentLines = order.getOrderlines().filter((line) => !line.refunded_orderline_id);
        const currentUuids = new Set(currentLines.map((line) => line.uuid));
        lines = currentLines
            .filter((line) => lineChangedSincePreparation(order, line, preparationLine(order, line)))
            .map((line) => ({
                line_uuid: line.uuid,
                expected_quantity: getBaseerSentQuantity(order, line),
                new_quantity: Math.max(0, line.getQuantity() - getBaseerSilentQuantity(line)),
                reason_code: "",
                reason_note: "",
            }));
        // Never let a line removed through an unexpected native/internal path
        // disappear silently. The server rejects this cancellation without a
        // reason, leaving the durable order untouched for recovery.
        const missingUuids = new Set();
        for (const oldLine of Object.values(order.last_order_preparation_change?.lines || {})) {
            const lineUuid = oldLine?.uuid;
            if (
                lineUuid &&
                !currentUuids.has(lineUuid) &&
                !missingUuids.has(lineUuid) &&
                Number(oldLine.quantity || 0) > 0
            ) {
                missingUuids.add(lineUuid);
                lines.push({
                    line_uuid: lineUuid,
                    expected_quantity: Number(oldLine.quantity),
                    new_quantity: 0,
                    reason_code: "",
                    reason_note: "",
                });
            }
        }
    }

    return {
        action_uuid: crypto.randomUUID(),
        action_type: actionType,
        lines,
    };
}

patch(PosOrder.prototype, {
    serializeForORM(opts = {}) {
        const data = super.serializeForORM(...arguments);
        const action = this.uiState?.baseerPreparationAction;
        if (action) {
            // Strip OWL proxies before the payload crosses the RPC boundary.
            data.baseer_preparation_action = JSON.parse(JSON.stringify(action));
        }
        return data;
    },
});

patch(Orderline.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
    },

    get baseerLineActionsVisible() {
        const substitutionProtected = this.pos.baseerIsSubstitutionProtected?.(this.line) || false;
        return (
            this.props.mode === "display" &&
            (this.pos.config.baseer_direct_print_enabled || substitutionProtected) &&
            this.pos.baseerCanManageLine(this.line)
        );
    },

    get baseerLineActionsLabel() {
        return _t("Item actions");
    },

    async openBaseerLineActions(event) {
        event.preventDefault();
        event.stopPropagation();
        await this.pos.baseerOpenLineActions(this.line);
    },
});

patch(PosStore.prototype, {
    baseerCanManageLine(line) {
        const order = line?.order_id;
        return Boolean(
            order &&
            !order.finalized &&
            !line.refunded_orderline_id &&
            !order.isRefund &&
            !line.isPartOfCombo()
        );
    },

    baseerIsSentLine(line) {
        return this.baseerCanManageLine(line) && getBaseerSentQuantity(line.order_id, line) > 0;
    },

    async _baseerShowLineAlert(title, body) {
        this.dialog.add(AlertDialog, { title, body });
    },

    async _baseerAskLineQuantity(line, { title, startingValue, validate }) {
        const value = await makeAwaitable(this.dialog, NumberPopup, {
            title,
            startingValue,
            confirmButtonLabel: _t("Apply"),
        });
        if (value === undefined || value === null || value === false) {
            return null;
        }
        const quantity = Number(value);
        if (!Number.isFinite(quantity) || !validate(quantity)) {
            await this._baseerShowLineAlert(
                _t("Invalid quantity"),
                _t("Enter a valid quantity greater than zero.")
            );
            return null;
        }
        return quantity;
    },

    async _baseerAskLineCancellationReason() {
        const reasonCode = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Cancel kitchen item"),
            list: CANCELLATION_REASONS.map(([id, label]) => ({ id, label, item: id })),
        });
        if (!reasonCode) {
            return null;
        }
        let reasonNote = "";
        if (reasonCode === "other") {
            reasonNote = await makeAwaitable(this.dialog, TextInputPopup, {
                title: _t("Cancellation reason"),
                placeholder: _t("Describe the reason"),
                startingValue: "",
            });
            if (!reasonNote?.trim()) {
                return null;
            }
        }
        return { reasonCode, reasonNote: reasonNote?.trim() || "" };
    },

    async _baseerRunSentLineAction(line, action) {
        const order = line?.order_id;
        if (!order) return false;
        if (order.uiState.baseerKitchenLineActionPending) {
            this.notification.add(
                _t("Wait for the current kitchen item change to finish before changing another item."),
                { type: "warning" }
            );
            return false;
        }
        order.uiState.baseerKitchenLineActionPending = true;
        try {
            return await action();
        } finally {
            delete order.uiState.baseerKitchenLineActionPending;
        }
    },

    async _baseerCommitSentLineQuantity(line, newQuantity, cancellation = null) {
        const order = line.order_id;
        if (order.uiState.baseerPreparationAction) {
            this.notification.add(_t("The kitchen result is still unknown. Reconnect and check it before retrying."), { type: "warning" });
            return false;
        }
        if (this.data.network.offline) {
            this.notification.add(
                _t("Connect to the internet before changing a kitchen item."),
                { type: "warning" }
            );
            return false;
        }

        const previousQuantity = line.getQuantity();
        const previousPreparation = clonePreparationState(order);
        const expectedQuantity = getBaseerSentQuantity(order, line);
        const result = line.setQuantity(newQuantity, Boolean(line.combo_line_ids?.length));
        if (result !== true) {
            this.dialog.add(AlertDialog, result);
            return false;
        }

        order.uiState.baseerPreparationAction = buildBaseerPreparationAction(order, "line_change", [{
            line_uuid: line.uuid,
            expected_quantity: expectedQuantity,
            new_quantity: Math.max(0, newQuantity - getBaseerSilentQuantity(line)),
            reason_code: cancellation?.reasonCode || "",
            reason_note: cancellation?.reasonNote || "",
        }]);

        this.env.services.ui.block();
        try {
            await this.sendOrderInPreparation(order, { byPassPrint: true });
            if (newQuantity === 0 && line.order_id) {
                order.removeOrderline(line);
            }
            // Only native sync's authoritative cancelled state permits local
            // retirement. Empty drafts can still hold deposits or refunds.
            if (order.state === "cancel") {
                this.removePendingOrder(order);
                this.data.localDeleteCascade(order);
                this.showDefault();
            } else {
                this.addPendingOrder([order.id]);
            }
            return true;
        } catch (error) {
            if (error?.baseerPreparationOutcomeUnknown) {
                this.notification.add(
                    _t("The kitchen result is still unknown. Reconnect and check it before retrying."),
                    { type: "warning" }
                );
                return false;
            }
            order.last_order_preparation_change = previousPreparation;
            if (line.order_id) {
                line.setQuantity(previousQuantity, Boolean(line.combo_line_ids?.length));
            }
            this.notification.add(
                _t("The kitchen change was not saved. The item was kept in the order."),
                { type: "danger" }
            );
            return false;
        } finally {
            if (!order.uiState.baseerPreparationOutcomeUnknown) {
                delete order.uiState.baseerPreparationAction;
                delete order.uiState.baseerPreparationPreviousChange;
            }
            await this.data.synchronizeLocalDataInIndexedDB();
            this.env.services.ui.unblock();
        }
    },

    async baseerCancelSentLine(line) {
        return await this._baseerRunSentLineAction(line, async () => {
            if (!this.baseerIsSentLine(line)) return false;
            const cancellation = await this._baseerAskLineCancellationReason();
            if (!cancellation) return false;
            const confirmed = await ask(this.dialog, {
                title: _t("Cancel item?"),
                body: _t(
                    "%s × %s will be cancelled and the reason will be recorded for the kitchen.",
                    getBaseerSentQuantity(line.order_id, line),
                    line.getFullProductName()
                ),
                confirmLabel: _t("Cancel item"),
                confirmClass: "btn-danger",
                cancelLabel: _t("Keep item"),
            }, {}, ConfirmationDialog);
            return confirmed
                ? await this._baseerCommitSentLineQuantity(line, 0, cancellation)
                : false;
        });
    },

    async baseerChangeSentLineQuantity(line, newQuantity) {
        if (newQuantity <= 0) {
            return await this.baseerCancelSentLine(line);
        }
        return await this._baseerRunSentLineAction(line, async () => {
            const sentQuantity = getBaseerSentQuantity(line.order_id, line);
            if (newQuantity === line.getQuantity()) return true;
            // Dropping only an unsent increment does not require a kitchen event.
            if (newQuantity >= sentQuantity + getBaseerSilentQuantity(line) && newQuantity < line.getQuantity()) {
                line.setQuantity(newQuantity, Boolean(line.combo_line_ids?.length));
                return true;
            }
            return await this._baseerCommitSentLineQuantity(line, newQuantity);
        });
    },

    async baseerOpenLineActions(line) {
        if (!this.baseerCanManageLine(line)) {
            return;
        }
        // The controlled-substitution add-on deliberately owns deletion for
        // protected products.  Keep this guard here as well as in that module:
        // this menu is the common entry point and must never expose a normal
        // remove action while the substitution asset is present.
        const substitutionProtected = Boolean(
            this.config?.baseer_substitution_enabled
            && (line?.product_id?.baseer_substitution_enabled
                || line?.product_id?.product_tmpl_id?.baseer_substitution_enabled)
        );
        if (substitutionProtected && typeof this.baseerOpenSubstitution === "function") {
            await this.baseerOpenSubstitution(line);
            return;
        }
        const sent = this.baseerIsSentLine(line);
        const action = await makeAwaitable(this.dialog, SelectionPopup, {
            title: line.getFullProductName(),
            list: (sent
                ? [
                    ["reduce", _t("Reduce quantity")],
                    ["cancel", _t("Cancel item")],
                ]
                : [
                    ["quantity", _t("Change quantity")],
                    ["note", _t("Add note")],
                    ["remove", _t("Remove item")],
                ]
            ).map(([id, label]) => ({ id, label, item: id })),
        });
        if (!action) {
            return;
        }

        if (action === "cancel") {
            await this.baseerCancelSentLine(line);
            return;
        }
        if (action === "reduce") {
            const quantity = await this._baseerAskLineQuantity(line, {
                title: _t("Reduce quantity"),
                startingValue: Math.max(1, line.getQuantity() - 1),
                validate: (value) => value > 0 && value < line.getQuantity(),
            });
            if (quantity !== null) {
                await this.baseerChangeSentLineQuantity(line, quantity);
            }
            return;
        }
        if (action === "quantity") {
            const quantity = await this._baseerAskLineQuantity(line, {
                title: _t("Change quantity"),
                startingValue: line.getQuantity(),
                validate: (value) => value > 0,
            });
            if (quantity !== null) {
                line.setQuantity(quantity, Boolean(line.combo_line_ids?.length));
            }
            return;
        }
        if (action === "note") {
            const note = await makeAwaitable(this.dialog, TextInputPopup, {
                title: _t("Item note"),
                startingValue: line.getCustomerNote(),
                rows: 3,
            });
            if (typeof note === "string") {
                line.setCustomerNote(note);
            }
            return;
        }
        if (action === "remove") {
            line.order_id.removeOrderline(line);
        }
    },
});

patch(OrderSummary.prototype, {
    async updateSelectedOrderline({ buffer, key }) {
        let line = this.currentOrder?.getSelectedOrderline();
        if (line?.combo_parent_id) {
            line = line.combo_parent_id;
        }
        const protectedQuantity =
            this.pos.config.baseer_direct_print_enabled &&
            this.pos.numpadMode === "quantity" &&
            this.pos.baseerIsSentLine(line);
        const managedUnsentLine =
            this.pos.config.baseer_direct_print_enabled &&
            this.pos.numpadMode === "quantity" &&
            this.pos.baseerCanManageLine(line) &&
            !this.pos.baseerIsSentLine(line);
        const requestedQuantity = buffer === null ? 0 : Number(buffer);
        const destructiveKey = key === "Backspace" || buffer === null;
        if (
            managedUnsentLine &&
            (buffer === null || !Number.isFinite(requestedQuantity) || requestedQuantity <= 0)
        ) {
            this.numberBuffer.reset();
            line.order_id.removeOrderline(line);
            return;
        }
        if (!protectedQuantity) {
            return await super.updateSelectedOrderline(...arguments);
        }

        if (destructiveKey || !Number.isFinite(requestedQuantity) || requestedQuantity <= 0) {
            this.numberBuffer.reset();
            await this.pos.baseerCancelSentLine(line);
            return;
        }
        if (requestedQuantity < line.getQuantity()) {
            this.numberBuffer.reset();
            await this.pos.baseerChangeSentLineQuantity(line, requestedQuantity);
            return;
        }
        return await super.updateSelectedOrderline(...arguments);
    },

    _setValue(value) {
        let line = this.currentOrder?.getSelectedOrderline();
        if (line?.combo_parent_id) {
            line = line.combo_parent_id;
        }
        const protectedQuantity =
            this.pos.config.baseer_direct_print_enabled &&
            this.pos.numpadMode === "quantity" &&
            this.pos.baseerIsSentLine(line);
        const managedUnsentLine =
            this.pos.config.baseer_direct_print_enabled &&
            this.pos.numpadMode === "quantity" &&
            this.pos.baseerCanManageLine(line) &&
            !this.pos.baseerIsSentLine(line);
        if (managedUnsentLine) {
            const requestedQuantity = value === "remove" ? 0 : Number(value);
            if (!Number.isFinite(requestedQuantity) || requestedQuantity <= 0) {
                this.numberBuffer.reset();
                line.order_id.removeOrderline(line);
                return;
            }
        }
        if (protectedQuantity) {
            const requestedQuantity = value === "remove" ? 0 : Number(value);
            if (!Number.isFinite(requestedQuantity) || requestedQuantity <= 0) {
                this.numberBuffer.reset();
                void this.pos.baseerCancelSentLine(line);
                return;
            }
            if (requestedQuantity < line.getQuantity()) {
                this.numberBuffer.reset();
                void this.pos.baseerChangeSentLineQuantity(line, requestedQuantity);
                return;
            }
        }
        return super._setValue(...arguments);
    },
});

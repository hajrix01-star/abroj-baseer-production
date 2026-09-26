/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";

// Presentation/pending-save filter only. The server rechecks under lock before
// releasing any saved table. Zero-price goods and refunds are NOT empty.
export function baseerTableHasContent(order) {
    return Boolean(order && (
        order.lines.length || order.payment_ids.length || order.account_move || order.is_refund ||
        [order.amount_total, order.amount_paid, order.amount_return].some((value) =>
            value !== undefined && value !== null && Number(value) !== 0
        ) ||
        order.uiState?.baseerSubstitutionAction ||
        order.uiState?.baseerProtectedItemCancellationAction ||
        order.uiState?.baseerPreparationAction ||
        Object.values(order.last_order_preparation_change?.lines || {}).some(
            (line) => Number(line.quantity) !== 0
        )
    ));
}

patch(PosStore.prototype, {
    tableHasOrders(table) {
        // Do not filter RestaurantTable.getOrders(): native setTable uses it
        // to restore an existing draft rather than creating a duplicate.
        return table.getOrders().some((order) =>
            baseerTableHasContent(order) || this.baseerHasPendingProtectedAction?.(order)
        );
    },

    shouldCreatePendingOrder(order) {
        if (this.config.module_pos_restaurant && order.table_id
                && !baseerTableHasContent(order)
                && !this.baseerHasPendingProtectedAction?.(order)) {
            return false;
        }
        return super.shouldCreatePendingOrder(...arguments);
    },

    async unsetTable() {
        const order = this.getOrder();
        if (!this.config.module_pos_restaurant || !order?.table_id || order.finalized
                || baseerTableHasContent(order)
                || this.baseerHasPendingProtectedAction?.(order)) {
            return await super.unsetTable(...arguments);
        }
        // A concurrent synchronization owns this order for now. Keep it until
        // its authoritative response arrives instead of losing another device's work.
        if (this.syncingOrders.has(order.uuid)) {
            return;
        }
        try {
            if (order.isSynced) {
                const result = await this.data.call('pos.order', 'baseer_release_empty_table', [[order.id]]);
                const missing = await this.data.missingRecursive(result.data);
                this.models.loadConnectedData(missing);
                if (!result.released) {
                    return;
                }
            }
            if (this.getOrder()?.uuid === order.uuid) {
                this.setOrder(null);
            }
            this.removePendingOrder(order);
            this.data.localDeleteCascade(order);
        } catch (error) {
            // Offline/uncertain: retain the draft for reconciliation, never
            // silently enqueue a deletion against potentially newer server data.
            this.notification.add(
                error?.data?.message || _t('The empty table could not be released. Reconnect and reopen it to retry.'),
                {type: 'warning'}
            );
        }
    },
});

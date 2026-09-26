/** @odoo-module **/

import { ConnectionLostError } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

/*
 * pos_restaurant defaults every new order to one guest.  For a restaurant
 * that reports covers, that default cannot distinguish a confirmed single
 * guest from a cashier who skipped the question.  Keep Odoo's own
 * customer_count field, but collect a positive value before opening a new
 * table order.
 */
patch(PosStore.prototype, {
    async baseerConfirmGuestCount(order) {
        const rawCount = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Guests"),
            startingValue: "",
            feedback: (buffer) => {
                const count = Number.parseInt(buffer, 10);
                if (!Number.isInteger(count) || count < 1) {
                    return "";
                }
                return `${this.env.utils.formatCurrency(order.amountPerGuest(count))} / ${_t("Guest")}`;
            },
        });
        const guestCount = Number.parseInt(rawCount, 10);
        if (!Number.isInteger(guestCount) || guestCount < 1) {
            return false;
        }
        order.setCustomerCount(guestCount);
        // pos_restaurant uses this device-local marker to avoid asking again.
        order.uiState.guestSetted = true;
        this.addPendingOrder([order.id]);
        return true;
    },

    async setTableFromUi(table, orderUuid = null) {
        const rootTable = table.parent_id ? table.getParent() : table;
        const hasExistingOrder = rootTable.getOrders().some((order) => {
            if (orderUuid ? order.uuid !== orderUuid : order.finalized) {
                return false;
            }
            // Odoo can create an empty, unsynchronised order when the POS
            // starts.  It still has the restaurant default of one guest, but
            // it has never been confirmed by a cashier and must not bypass
            // the mandatory prompt.
            return order.isSynced || order.lines.length || order.uiState.guestSetted;
        });

        // Existing orders retain the standard Odoo restaurant behavior.  The
        // mandatory question is only for a genuinely new table order.
        if (hasExistingOrder || orderUuid || this.getOrder()?.isFilledDirectSale) {
            return super.setTableFromUi(...arguments);
        }
        if (this.isOrderSyncing(rootTable.getOrder())) {
            return;
        }

        this.tableSyncing = true;
        try {
            await this.setTable(rootTable);
            const order = this.getOrder();
            if (!(await this.baseerConfirmGuestCount(order))) {
                if (!order.isSynced && !order.lines.length) {
                    this.removeOrder(order);
                }
                this.navigate("FloorScreen");
                return;
            }
            this.setOrder(order);
            this.navigate("ProductScreen", { orderUuid: order.uuid });
        } catch (error) {
            if (!(error instanceof ConnectionLostError)) {
                throw error;
            }
            Promise.reject(error);
        } finally {
            this.tableSyncing = false;
        }
    },
});

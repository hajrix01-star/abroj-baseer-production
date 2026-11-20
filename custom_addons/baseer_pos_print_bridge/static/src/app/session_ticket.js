/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import "@pos_restaurant/app/models/pos_order";
import "./native_split";
import "./preparation_bridge";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

function awaitsTicket(order) {
    return Boolean(order && !order.baseer_ticket_number && (
        order.baseer_ticket_session_id || (!order.isSynced && order.session_id?.baseer_ticket_enabled)
    ));
}

patch(PosOrder.prototype, {
    getName() {
        if (!this.table_id && this.baseer_ticket_number) {
            return String(this.baseer_ticket_number);
        }
        if (!this.table_id && awaitsTicket(this)) {
            return _t("Awaiting number");
        }
        return super.getName(...arguments);
    },
});

patch(ReceiptHeader.prototype, {
    get order() {
        const order = super.order;
        if (!order.baseer_ticket_label && !awaitsTicket(order)) {
            return order;
        }
        // All installed headers keep their own size and placement. Substitute
        // only their displayed tracking value, never the persisted device ID.
        return new Proxy(order, {
            get(target, field) {
                if (field === "tracking_number") {
                    return target.baseer_ticket_label || "";
                }
                const value = Reflect.get(target, field);
                return typeof value === "function" ? value.bind(target) : value;
            },
        });
    },
});

patch(PosStore.prototype, {
    async addLineToOrder(vals, order) {
        const firstLine = !order.lines.length;
        const result = await super.addLineToOrder(...arguments);
        if (firstLine && result && awaitsTicket(order) && !order.uiState.splittedOrderUuid) {
            this.addPendingOrder([order.id]);
            // Odoo's restaurant preSync books a floating direct sale; let its
            // normal Save/Send/Print perform that transition.
            if (!this.data.network.offline && !order.isDirectSale) {
                await this.syncAllOrders({ orders: [order] });
            }
        }
        return result;
    },

    async baseerEnsureTicketForPrint(order) {
        if (!awaitsTicket(order)) {
            return true;
        }
        if (order.lines.length && !this.data.network.offline && order.state === "draft") {
            try {
                await this.syncAllOrders({ orders: [order], throw: true });
            } catch (error) {
                this.notification.add(error?.data?.message || _t("Sync the order before printing its number."), { type: "warning" });
                return false;
            }
        }
        if (!order.baseer_ticket_label) {
            this.notification.add(_t("Sync the order before printing its number."), { type: "warning" });
            return false;
        }
        return true;
    },

    async printReceipt(options = {}) {
        if (!await this.baseerEnsureTicketForPrint(options.order || this.getOrder())) {
            return { successful: false };
        }
        return super.printReceipt(...arguments);
    },

    async sendOrderInPreparation(order) {
        if (!this.config.baseer_direct_print_enabled && !await this.baseerEnsureTicketForPrint(order)) {
            return false;
        }
        return super.sendOrderInPreparation(...arguments);
    },

    getOrderData(order) {
        const data = super.getOrderData(...arguments);
        if (order.baseer_ticket_label) {
            data.tracking_number = order.baseer_ticket_label;
        }
        return data;
    },
});

patch(TicketScreen.prototype, {
    _getSearchFields() {
        const fields = super._getSearchFields(...arguments);
        const nativeRepr = fields.REFERENCE.repr;
        fields.REFERENCE.repr = (order) => order.baseer_ticket_label
            ? [nativeRepr(order), order.floating_order_name, order.baseer_ticket_label].filter(Boolean).join(" ")
            : nativeRepr(order);
        return fields;
    },

    _computeSyncedOrdersDomain() {
        const domain = super._computeSyncedOrdersDomain(...arguments);
        const { fieldName, searchTerm } = this.state.search;
        if (fieldName !== "REFERENCE" || !domain.length || !/^[1-9][0-9]{0,9}(-[1-9][0-9]{0,9})?$/.test(searchTerm)) {
            return domain;
        }
        const parts = searchTerm.split("-").map(Number);
        if (parts.some((value) => value > 2147483647)) {
            return domain;
        }
        const number = ["baseer_ticket_number", "=", parts.at(-1)];
        const ticket = parts.length === 1 ? [number]
            : ["&", ["baseer_ticket_session_id", "=", parts[0]], number];
        // Extend only the native tracking lookup, preserving other constraints.
        return domain.flatMap((leaf) => Array.isArray(leaf) && leaf[0] === "tracking_number" && leaf[1] === "ilike"
            ? ["|", leaf, ...ticket] : [leaf]);
    },
});

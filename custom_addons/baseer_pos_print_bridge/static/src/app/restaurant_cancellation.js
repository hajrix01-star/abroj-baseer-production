/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";

/**
 * Odoo's restaurant action blocks the UI before it delegates to deleteOrders.
 * Baseer's cancellation reason is a dialog, so request it first through the
 * normal POS guard, then let deleteOrders execute the already-authorized,
 * atomic server cancellation. This keeps native table behaviour while never
 * allowing a kitchen-sent order to disappear without an audit record.
 */
patch(OrderSummary.prototype, {
    async unbookTable() {
        const order = this.pos.getOrder();
        const allowed = await this.pos.beforeDeleteOrder(order);
        if (!allowed) {
            return;
        }
        this.env.services.ui.block();
        try {
            const deleted = await this.pos.deleteOrders([order]);
            if (deleted) {
                this.pos.showDefault();
            }
        } finally {
            this.env.services.ui.unblock();
        }
    },
});

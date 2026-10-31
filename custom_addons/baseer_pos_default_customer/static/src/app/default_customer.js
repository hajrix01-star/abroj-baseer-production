/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    getDefaultPartnerId() {
        return this.config.baseer_default_customer_id || super.getDefaultPartnerId(...arguments);
    },

    getEmptyOrder() {
        const order = super.getEmptyOrder(...arguments);
        const defaultPartnerId = this.config.baseer_default_customer_id;

        // Odoo reuses the first empty draft loaded with a POS session.  Assign
        // the configured customer only to that truly empty draft; never alter
        // a ticket that already has a customer, a payment, or synced state.
        if (
            defaultPartnerId &&
            order?.isEmpty() &&
            !order.partner_id &&
            !order.finalized &&
            !order.isSynced &&
            order.payment_ids.length === 0
        ) {
            const partner = this.models["res.partner"].find(
                (candidate) => candidate.id === defaultPartnerId
            );
            if (partner) {
                order.setPartner(partner);
            }
        }
        return order;
    },
});

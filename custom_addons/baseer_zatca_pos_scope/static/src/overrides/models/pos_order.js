/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    isInvoiceMandatoryForSA() {
        return super.isInvoiceMandatoryForSA(...arguments) && this.config_id.baseer_zatca_phase2_enabled;
    },
});

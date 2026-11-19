import { PosStore } from "@point_of_sale/app/services/pos_store";
import "@pos_restaurant/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    isContinueSplitting(order) {
        if (!this.config.module_pos_restaurant && this.config.iface_splitbill) {
            const original = order.originalSplittedOrder;
            return Boolean(original && !original.finalized);
        }
        return super.isContinueSplitting(...arguments);
    },
});

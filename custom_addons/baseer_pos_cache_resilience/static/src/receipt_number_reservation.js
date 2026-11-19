/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import DeviceIdentifierSequence from "@point_of_sale/app/utils/devices_identifier_sequence";
import { PosStore } from "@point_of_sale/app/services/pos_store";

// Odoo 19.0 fd7af53e3be801e25fe7556022b37ff76c577b5d (LGPL-3).
// Port through existing hooks: the pinned image already recycles synchronously.
if (!DeviceIdentifierSequence.prototype.removeUsedNumbers) {
    patch(DeviceIdentifierSequence.prototype, {
        removeUsedNumbers(orders) {
            const data = this.data;
            if (!data?.unsynced_number_stack?.length) {
                return;
            }
            const prefix = `${data.device_identifier}-${odoo.pos_config_id}-`;
            const used = new Set(
                orders
                    .filter((o) => o.pos_reference?.slice(2).startsWith(prefix))
                    .map((o) => this.extractNumberFromReference(o.pos_reference))
            );
            this.save({
                device_identifier: data.device_identifier,
                next_number: data.next_number,
                unsynced_number_stack: data.unsynced_number_stack.filter((n) => !used.has(n)),
            });
        },
    });

    patch(PosStore.prototype, {
        setNextOrderRefs(order) {
            this.device.removeUsedNumbers(this.models["pos.order"].getAll());
            return super.setNextOrderRefs(...arguments);
        },
        postSyncAllOrders(orders) {
            this.device.removeUsedNumbers(orders);
            return super.postSyncAllOrders(...arguments);
        },
    });
}

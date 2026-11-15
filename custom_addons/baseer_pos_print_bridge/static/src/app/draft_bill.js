/** @odoo-module **/

import { Component } from "@odoo/owl";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import "@pos_restaurant/app/screens/product_screen/control_buttons/control_buttons";
import { formatCurrency } from "@web/core/currency";
import { patch } from "@web/core/utils/patch";

export class DraftBill extends Component {
    static template = "baseer_pos_print_bridge.DraftBill";
    static props = { order: Object };

    formatAmount(amount) {
        return formatCurrency(amount, this.props.order.currency.id);
    }
}

export function usesBaseerDraftBill(config) {
    return config.module_pos_restaurant && config.baseer_direct_print_enabled;
}

patch(ControlButtons.prototype, {
    async clickPrintBill() {
        if (!usesBaseerDraftBill(this.pos.config)) {
            return super.clickPrintBill(...arguments);
        }
        return this.pos.printReceipt({
            order: this.currentOrder,
            printBillActionTriggered: true,
        });
    },
});

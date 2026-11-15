/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import "@pos_restaurant/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";

export class DraftBill extends OrderReceipt {
    setup() {
        super.setup(...arguments);
        // The shared template includes installed layout extensions. Its
        // Saudi header reads the tax QR directly from the order.
        this.draftOrder = new Proxy(this.props.order, {
            get(order, field) {
                if (field === "generateQrcode") {
                    return () => false;
                }
                // The draft banner replaces the Saudi warning on this paper.
                // The original order and final receipt keep their own flag.
                if (field === "showChange" || field === "notLegal") {
                    return false;
                }
                const value = Reflect.get(order, field);
                return typeof value === "function" ? value.bind(order) : value;
            },
        });
    }

    get isBaseerDraftBill() {
        return true;
    }

    get order() {
        return this.draftOrder;
    }

    get paymentLines() {
        return [];
    }

    get qrCode() {
        return false;
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

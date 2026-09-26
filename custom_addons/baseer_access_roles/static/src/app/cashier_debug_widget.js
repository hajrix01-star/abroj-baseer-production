/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DebugWidget } from "@point_of_sale/app/utils/debug/debug_widget";

// The diagnostic widget can alter browser-local POS data.  It is useful to a
// POS manager in developer mode, but must never be exposed to a cashier.
patch(DebugWidget.prototype, {
    get isDisabled() {
        return super.isDisabled || this.pos.cashier?._role === "cashier";
    },
});

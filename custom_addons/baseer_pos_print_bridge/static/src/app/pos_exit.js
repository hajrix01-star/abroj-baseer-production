/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

const BASEER_POS_BACKEND_URL = "/odoo/action-point_of_sale.action_pos_config_kanban";

patch(PosStore.prototype, {
    redirectToBackend() {
        // Native POS returns to its sales command center.  Baseer uses that
        // page for reporting, not as a cashier exit destination: return to
        // the ordinary POS configurations instead.
        window.location.href = BASEER_POS_BACKEND_URL;
    },
});

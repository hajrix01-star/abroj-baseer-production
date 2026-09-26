/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(TicketScreen.prototype, {
    _getFilterOptions() {
        const filters = super._getFilterOptions(...arguments);
        if (this.pos.user?.baseer_hide_pos_history) {
            filters.delete("SYNCED");
        }
        return filters;
    },
});

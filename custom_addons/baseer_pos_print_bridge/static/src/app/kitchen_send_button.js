/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";

/**
 * Restaurant's native Send control is hidden when no IoT/Epson printer is
 * configured. Baseer deliberately does not populate those browser printers,
 * so expose the same familiar control from the server-owned Baseer bindings.
 */
patch(ActionpadWidget.prototype, {
    setup() {
        super.setup();
        this.doBaseerSubmitOrder = useTrackedAsync(async () => {
            try {
                return await this.pos.baseerSendCurrentOrder();
            } catch (error) {
                // useTrackedAsync consumes ordinary exceptions; make a failed
                // send visible so it cannot look like kitchen success.
                if (odoo.debug) {
                    console.warn("Kitchen send failed:", error?.data?.message || error?.message || "unknown");
                }
                this.pos.notification.add(
                    _t("The kitchen order could not be sent. Keep it open and ask a manager for help."),
                    { type: "danger", sticky: true }
                );
                return false;
            }
        });
    },

    get baseerPreparationCategoryCount() {
        return this.pos.baseerCategoryCount.slice(0, 4);
    },

    get baseerPreparationCategoryOverflow() {
        return this.pos.baseerCategoryCount.length > 4;
    },

    get baseerKitchenSendLabel() {
        if (this.currentOrder?.uiState.baseerPreparationOutcomeUnknown) {
            return _t("Check kitchen change");
        }
        if (!this.pos.config.baseer_direct_print_enabled) {
            return _t("Send");
        }
        const previousLines = this.currentOrder?.last_order_preparation_change?.lines || {};
        return Object.keys(previousLines).length ? _t("Update kitchen") : _t("Send to kitchen");
    },
});

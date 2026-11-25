import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

export function hasLegacyDiscount(order) {
    return !!(order?.baseer_global_discount_locked || order?.lines?.some((line) => line.baseer_global_discount_line));
}

patch(TicketScreen.prototype, {
    async onDoRefund() {
        if (hasLegacyDiscount(this.getSelectedOrder())) {
            this.dialog.add(AlertDialog, {
                title: _t("Invoice discount"),
                body: _t("This order used the old invoice discount and cannot be refunded in the POS. Ask accounting to issue a credit note on its invoice."),
            });
            return;
        }
        return super.onDoRefund(...arguments);
    },
    _getRefundableDetails() {
        return super._getRefundableDetails(...arguments).filter((detail) => !detail.line.baseer_global_discount_line);
    },
});

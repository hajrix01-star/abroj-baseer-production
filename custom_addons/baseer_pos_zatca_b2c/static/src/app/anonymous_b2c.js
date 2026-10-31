/** @odoo-module */

import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    baseerAssignAnonymousB2cPartner() {
        const config = this.config;
        const partnerId = config.baseer_zatca_anonymous_partner_id?.id;
        const isEligible =
            config.baseer_zatca_allow_anonymous_b2c &&
            this.company?.country_id?.code === "SA" &&
            this.isInvoiceMandatoryForSA?.() &&
            !this.getPartner() &&
            !this.getShippingDate() &&
            partnerId;
        if (!isEligible) {
            return false;
        }
        const partner = this.models["res.partner"].get(partnerId);
        if (!partner) {
            return false;
        }
        this.setPartner(partner);
        return true;
    },
});

patch(OrderPaymentValidation.prototype, {
    async validateOrder(isForceValidate) {
        // Assign before every native payment validation. This deliberately makes
        // no distinction between cash, card, terminal, or other payment methods.
        this.order.baseerAssignAnonymousB2cPartner();
        return super.validateOrder(...arguments);
    },
});

patch(PaymentScreen.prototype, {
    onMounted() {
        super.onMounted(...arguments);
        // Odoo computes `canBeValidated()` before `validateOrder()` is invoked.
        // Assign the configured generic B2C partner on entry to payment so the
        // native Saudi invoice requirement does not disable the Confirm button.
        this.currentOrder.baseerAssignAnonymousB2cPartner();
    },
});

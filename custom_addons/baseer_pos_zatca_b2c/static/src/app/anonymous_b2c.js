/** @odoo-module */

import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    baseerCanUseAnonymousB2c() {
        // This mirrors the eligibility test used when assigning the internal
        // consumer, without mutating the order while the payment screen is
        // deciding whether its confirmation button may be enabled.
        const config = this.config_id || this.config;
        const configuredPartner = config?.baseer_zatca_anonymous_partner_id;
        const partnerId = configuredPartner?.id ?? configuredPartner;
        return Boolean(
            config?.baseer_zatca_allow_anonymous_b2c &&
                this.company?.country_id?.code === "SA" &&
                this.isInvoiceMandatoryForSA?.() &&
                !this.getPartner() &&
                !this.getShippingDate() &&
                partnerId
        );
    },

    baseerAssignAnonymousB2cPartner() {
        // ``config_id`` is the order's own POS configuration.  Reading it
        // avoids relying on the store-wide first config when POS data is
        // bootstrapped with the legacy empty-fields marker.
        const config = this.config_id || this.config;
        const configuredPartner = config?.baseer_zatca_anonymous_partner_id;
        const partnerId = configuredPartner?.id ?? configuredPartner;
        if (!this.baseerCanUseAnonymousB2c()) {
            return false;
        }
        const partner = this.models["res.partner"].get(partnerId);
        if (!partner) {
            return false;
        }
        this.setPartner(partner);
        return true;
    },

    canBeValidated() {
        // Odoo evaluates this before OrderPaymentValidation runs.  The sale
        // will receive the configured internal consumer immediately before
        // native validation, so only bypass the customer prerequisite here;
        // every payment and order-line prerequisite stays native.
        if (this.baseerCanUseAnonymousB2c()) {
            return this.isPaid() && this._isValidEmptyOrder();
        }
        return super.canBeValidated(...arguments);
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

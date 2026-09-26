/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { PosStore } from "@point_of_sale/app/services/pos_store";

const arabicDigits = {
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
};

function saudiMobileKey(value) {
    let digits = String(value || "")
        .replace(/[٠-٩]/g, (character) => arabicDigits[character])
        .replace(/\D/g, "");
    if (digits.startsWith("00966")) {
        digits = digits.slice(2);
    }
    let national = digits.startsWith("966") ? digits.slice(3) : digits;
    if (national.startsWith("0")) {
        national = national.slice(1);
    }
    return /^5\d{8}$/.test(national) ? `966${national}` : false;
}

function partnerCategory(partner) {
    if (partner.employee) {
        return "employee";
    }
    return partner.is_company ? "company" : "individual";
}

patch(PartnerList.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.baseerCustomerCategory = "individual";
    },

    setBaseerCustomerCategory(category) {
        this.state.baseerCustomerCategory = category;
    },

    getPartners(partners) {
        const key = saudiMobileKey(this.state.query);
        const exactMobileMatches = key
            ? partners.filter((partner) => partner.baseer_pos_phone_key === key)
            : [];
        const candidates = exactMobileMatches.length ? exactMobileMatches : super.getPartners(...arguments);
        return candidates.filter(
            (partner) => partnerCategory(partner) === this.state.baseerCustomerCategory
        );
    },
});

patch(PosStore.prototype, {
    async editPartner(partner) {
        this.baseerCustomerEditCapability = await this.data.silentCall(
            "pos.config",
            "baseer_prepare_customer_form",
            [this.config.id, partner?.id || false],
            {},
            false
        );
        try {
            return await super.editPartner(partner);
        } finally {
            this.baseerCustomerEditCapability = null;
        }
    },

    editPartnerContext(partner) {
        return {
            ...super.editPartnerContext(partner),
            baseer_pos_config_id: this.config.id,
            baseer_pos_customer_capability: this.baseerCustomerEditCapability,
        };
    },
});

/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const settlementChoicesCache = new Map();

function relationId(value) {
    if (Array.isArray(value)) {
        return value[0] || false;
    }
    return value?.id || value || false;
}

function fetchChoices(orm, companyId) {
    if (!settlementChoicesCache.has(companyId)) {
        const request = orm.call("baseer.purchase.batch.line", "payment_settlement_choices", [companyId])
            .catch((error) => {
                settlementChoicesCache.delete(companyId);
                throw error;
            });
        settlementChoicesCache.set(companyId, request);
    }
    return settlementChoicesCache.get(companyId);
}

// The picker deliberately translates its single visual choice back to the
// existing three-field accounting contract.  It never calculates balance or
// decides whether an invoice may post; that remains server-side.
export class PaymentSettlementSelector extends Component {
    static template = "baseer_procurement_requests.PaymentSettlementSelector";
    static components = { Dropdown, DropdownItem };
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            unlockingCredit: false,
            choices: { payment_points: [], representatives: [], can_use_representative: false },
        });
        // Do not block a newly-created inline x2many record from rendering
        // while its presentation-only choices are fetched.  In particular,
        // the parent batch can be saved immediately before Odoo mounts the
        // new row, so this request belongs after the row is mounted.
        onMounted(async () => {
            const companyId = relationId(this.props.record.data.company_id);
            if (!companyId) {
                this.state.loading = false;
                return;
            }
            try {
                this.state.choices = await fetchChoices(this.orm, companyId);
            } finally {
                this.state.loading = false;
            }
        });
    }

    get paymentMethodId() {
        return relationId(this.props.record.data.payment_method_line_id);
    }

    get representativeId() {
        return relationId(this.props.record.data.representative_petty_cash_representative_id);
    }

    get selectedPaymentPoint() {
        return this.state.choices.payment_points.find((point) => point.id === this.paymentMethodId);
    }

    get selectedRepresentative() {
        return this.state.choices.representatives.find((representative) => representative.id === this.representativeId);
    }

    get label() {
        if (this.state.unlockingCredit) {
            return _t("Choose a settlement method");
        }
        if (this.props.record.data.payment_source_type === "representative_petty_cash") {
            return this.selectedRepresentative?.name || _t("Purchasing representative");
        }
        if (this.props.record.data.payment_source_type === "credit") {
            return _t("Credit");
        }
        return this.selectedPaymentPoint?.name || _t("Choose a settlement method");
    }

    get isCredit() {
        return this.props.record.data.payment_source_type === "credit" && !this.state.unlockingCredit;
    }

    get representativeBalance() {
        const amount = this.selectedRepresentative?.available_balance;
        if (amount === undefined) {
            return false;
        }
        return this.formatAmount(amount);
    }

    formatAmount(amount) {
        return Number(amount || 0).toLocaleString("en-US-u-nu-latn", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    async choosePaymentPoint(point) {
        this.state.unlockingCredit = false;
        await this.props.record.update({
            payment_source_type: "payment_method",
            payment_method_line_id: [point.id, point.name],
            representative_petty_cash_representative_id: false,
            is_credit: false,
        });
    }

    async chooseRepresentative(representative) {
        this.state.unlockingCredit = false;
        await this.props.record.update({
            payment_source_type: "representative_petty_cash",
            payment_method_line_id: false,
            representative_petty_cash_representative_id: [representative.id, representative.name],
            is_credit: true,
        });
    }

    async toggleCredit(event) {
        if (!event.target.checked) {
            // Preserve the saved credit source until the accountant actually
            // picks a replacement. This avoids an invalid half-saved row.
            this.state.unlockingCredit = true;
            return;
        }
        this.state.unlockingCredit = false;
        await this.props.record.update({
            payment_source_type: "credit",
            payment_method_line_id: false,
            representative_petty_cash_representative_id: false,
            is_credit: true,
        });
    }
}

registry.category("fields").add("baseer_payment_settlement_selector", {
    component: PaymentSettlementSelector,
    supportedTypes: ["selection"],
});

/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Share a request while identical picker cells mount together, but never keep
// monetary balances after it finishes. Funding and returns can happen in
// another Odoo action without a full browser reload.
const settlementChoicesInFlight = new Map();

function relationId(value) {
    if (Array.isArray(value)) {
        return value[0] || false;
    }
    return value?.id || value || false;
}

function fetchChoices(orm, companyId) {
    if (!settlementChoicesInFlight.has(companyId)) {
        const request = orm.call("baseer.purchase.batch.line", "payment_settlement_choices", [companyId]);
        settlementChoicesInFlight.set(companyId, request);
        request.then(
            () => settlementChoicesInFlight.delete(companyId),
            () => settlementChoicesInFlight.delete(companyId)
        );
    }
    return settlementChoicesInFlight.get(companyId);
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

    get isRepresentativePettyCash() {
        return Boolean(this.representativeId) && this.props.record.data.is_credit;
    }

    get isActualCredit() {
        return this.props.record.data.payment_source_type === "credit" && !this.representativeId;
    }

    get label() {
        if (this.state.unlockingCredit) {
            return _t("Choose a settlement method");
        }
        if (this.isRepresentativePettyCash) {
            return this.selectedRepresentative?.name || _t("Purchasing representative");
        }
        if (this.props.record.data.payment_source_type === "credit") {
            return _t("Credit");
        }
        return this.selectedPaymentPoint?.name || _t("Choose a settlement method");
    }

    get representativeBalance() {
        const amount = this.selectedRepresentative?.available_balance;
        if (amount === undefined) {
            return false;
        }
        return this.formatAmount(amount);
    }

    async refreshChoices() {
        const companyId = relationId(this.props.record.data.company_id);
        if (!companyId) {
            return;
        }
        this.state.loading = true;
        try {
            this.state.choices = await fetchChoices(this.orm, companyId);
        } finally {
            this.state.loading = false;
        }
    }

    formatAmount(amount) {
        return Number(amount || 0).toLocaleString("en-US-u-nu-latn", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    async choosePaymentPoint(point) {
        // A fresh invoice row already has this source.  When changing from
        // Credit or Representative Petty Cash, however, the replacement
        // source and its payment point must be saved together.  Saving the
        // source first would create an invalid intermediate row (no payment
        // point) and the server correctly rejects it.
        const values = {
            payment_method_line_id: { id: point.id, display_name: point.name },
        };
        if (this.props.record.data.payment_source_type !== "payment_method"
                || this.props.record.data.is_credit
                || this.representativeId) {
            Object.assign(values, {
                payment_source_type: "payment_method",
                representative_petty_cash_representative_id: false,
                is_credit: false,
            });
        }
        await this.props.record.update(values);
    }

    async chooseRepresentative(representative) {
        // Refresh here as well: a funding or return may have been posted while
        // this draft batch remained open in the same browser session.
        await this.refreshChoices();
        const currentRepresentative = this.state.choices.representatives.find(
            (item) => item.id === representative.id
        ) || representative;
        // This is a complete settlement route, so save it atomically.  Saving
        // its technical is_credit marker before the representative lets the
        // regular credit onchange normalize the intermediate row back to
        // actual Credit, which then disables this picker.
        await this.props.record.update({
            payment_source_type: "representative_petty_cash",
            payment_method_line_id: false,
            is_credit: true,
            representative_petty_cash_representative_id: {
                id: currentRepresentative.id,
                display_name: currentRepresentative.name,
            },
        });
    }

}

// The credit switch has its own table cell so it can remain visible without
// competing with the settlement picker.  Unticking only unlocks the picker;
// the server keeps the saved credit source unless the accountant selects a
// complete replacement, which prevents an invalid half-saved invoice row.
export class PaymentCreditToggle extends Component {
    static template = "baseer_procurement_requests.PaymentCreditToggle";
    static props = { ...standardFieldProps };

    get isCredit() {
        return this.props.record.data.is_credit;
    }

    get isRepresentativePettyCash() {
        return Boolean(relationId(this.props.record.data.representative_petty_cash_representative_id))
            && this.props.record.data.is_credit;
    }

    async toggleCredit(event) {
        if (!event.target.checked) {
            await this.props.record.update({ is_credit: false });
            return;
        }
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
    supportedTypes: ["many2one"],
});

registry.category("fields").add("baseer_payment_credit_toggle", {
    component: PaymentCreditToggle,
    supportedTypes: ["boolean"],
});

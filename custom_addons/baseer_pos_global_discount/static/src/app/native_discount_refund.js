import { patch } from "@web/core/utils/patch";
import { roundPrecision } from "@web/core/utils/numbers";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

const pendingRefunds = new WeakMap();

const key = (taxes) => taxes.map((tax) => tax.id).sort((a, b) => a - b).join("_");

export function refundShare(original, previous, qty, rounding) {
    const round = (value) => roundPrecision(value, rounding);
    const final = previous.reduce((sum, line) => sum + Math.abs(line.qty), 0) + Math.abs(qty) >= Math.abs(original.qty) - 1e-8;
    return Object.fromEntries(["baseer_discount_share_excl", "baseer_discount_share_incl"].map((field) => [field,
        final ? round(-original[field] - previous.reduce((sum, line) => sum + (line[field] || 0), 0))
            : round(-original[field] * Math.abs(qty / original.qty)),
    ]));
}

patch(PosStore.prototype, {
    applyDiscount(percent, order = this.getOrder()) {
        const sources = order?.lines?.filter((line) => line.refunded_orderline_id) || [];
        if (!order?.is_refund || order.baseer_global_discount_locked ||
            !sources.some((line) => line.refunded_orderline_id.baseer_discount_share_incl || line.refunded_orderline_id.baseer_discount_share_excl) ||
            sources.some((line) => line.refunded_orderline_id.order_id.baseer_global_discount_locked)) {
            return super.applyDiscount(...arguments);
        }
        if (pendingRefunds.has(order)) return pendingRefunds.get(order);
        const pending = this.baseerBuildRefundDiscount(order, sources).finally(() => pendingRefunds.delete(order));
        pendingRefunds.set(order, pending);
        return pending;
    },
    async baseerBuildRefundDiscount(order, sources) {
        const groups = new Map();
        const rounding = order.currency.rounding;
        for (const line of sources) {
            const original = line.refunded_orderline_id;
            const previous = original.refund_orderline_ids.filter((item) => item !== line && item.order_id.state !== "cancel" && (item.order_id !== order || item.id < line.id));
            const shares = refundShare(original, previous, line.qty, rounding);
            line.update(shares);
            const taxes = line.prepareBaseLineForTaxesComputationExtraValues().tax_ids;
            const group = groups.get(key(taxes)) || { taxes, excl: 0, incl: 0 };
            group.excl = roundPrecision(group.excl + shares.baseer_discount_share_excl, rounding);
            group.incl = roundPrecision(group.incl + shares.baseer_discount_share_incl, rounding);
            groups.set(key(taxes), group);
        }
        for (const line of [...(order.discountLines || [])]) line.delete();
        for (const group of groups.values()) {
            if (!group.excl && !group.incl) continue;
            const product = this.config.discount_product_id;
            const line = await this.addLineToOrder({ product_id: product, product_tmpl_id: product.product_tmpl_id,
                qty: -1, price_unit: -group.excl, tax_ids: [["link", ...group.taxes]] }, order, { force: true }, false);
            const base = accountTaxHelpers.prepare_base_line_for_taxes_computation(line, line.prepareBaseLineForTaxesComputationExtraValues());
            accountTaxHelpers.add_tax_details_in_base_lines([base], order.company_id);
            accountTaxHelpers.round_base_lines_tax_details([base], order.company_id);
            const details = base.tax_details;
            const excludedDelta = group.excl - details.total_excluded_currency - details.delta_total_excluded_currency;
            details.delta_total_excluded_currency += excludedDelta;
            details.delta_total_excluded = (details.delta_total_excluded || 0) + excludedDelta / (base.rate || 1);
            const tax = details.taxes_data.find((item) => !item.is_reverse_charge);
            if (tax) {
                const delta = group.incl - group.excl - (details.total_included_currency - details.total_excluded_currency);
                tax.tax_amount_currency += delta;
                tax.tax_amount += delta / (base.rate || 1);
            }
            accountTaxHelpers.fix_base_lines_tax_details_on_manual_tax_amounts([base], order.company_id);
            line.update({ extra_tax_data: accountTaxHelpers.export_base_line_extra_tax_data(base) });
        }
    },
});

patch(TicketScreen.prototype, {
    async onDoRefund() {
        await super.onDoRefund(...arguments);
        const pending = pendingRefunds.get(this.pos.getOrder());
        if (pending) await pending;
    },
});

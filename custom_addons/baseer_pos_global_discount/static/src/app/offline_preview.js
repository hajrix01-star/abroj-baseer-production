import { accountTaxHelpers } from "@account/helpers/account_tax";
import { _t } from "@web/core/l10n/translation";

/** Validate and price the preview without mutating the order or its intent. */
export function calculateOfflineDiscount(pos, order, intent) {
    const previous = new Set(intent.preview_line_uuids || []);
    const sources = order.lines.filter((line) => !line.baseer_global_discount_line && !previous.has(line.uuid));
    const product = pos.config.baseer_global_discount_product_id;
    const fiscalId = order.fiscal_position_id?.id || 0;
    const accountProof = intent.account_proofs?.[String(fiscalId)];
    if (typeof accountProof !== "string" || !/^[a-f0-9]{64}$/.test(accountProof)) {
        throw new Error(_t("The discount account needs verification. Reconnect and ask a manager before payment."));
    }
    if (!product || !sources.length || sources.length > 200) throw new Error(_t("Add products before applying an invoice discount."));
    for (const line of sources) {
        const tracking = line.product_id.tracking ?? line.product_id.product_tmpl_id?.tracking;
        if (tracking !== 'none' || line.pack_lot_ids?.length) {
            throw new Error(_t('Tracked products are not supported with this invoice discount. Remove the discount or tracked items before payment.'));
        }
        const comboHeader = line.product_id.type === "combo";
        const locks = order.baseer_protected_line_policy || order.raw?.baseer_protected_line_policy || {};
        const protectedReplacement = Number(line.baseer_substitution_minimum_quantity) > 0 ||
            Number(line.uiState?.baseerSubstitutionMinimumQuantity) > 0 ||
            Number(locks[line.uuid]?.minimum_quantity) > 0 ||
            (pos.config.baseer_substitution_locked_lines || []).some((item) => item.line_uuid === line.uuid && Number(item.minimum_quantity) > 0);
        if (line.qty <= 0 || line.refunded_orderline_id || line.price_unit < 0 ||
            line.product_id === pos.config.tip_product_id || line.product_id.baseer_substitution_enabled || protectedReplacement ||
            Object.keys(line.extra_tax_data || {}).length || (!comboHeader && !line.tax_ids.length) ||
            line.tax_ids.some((tax) => tax.amount_type !== "percent")) {
            throw new Error(_t("This basket contains protected items or unsupported taxes."));
        }
    }
    const priced = sources.filter((line) => line.product_id.type !== "combo");
    const bases = priced.map((line) => accountTaxHelpers.prepare_base_line_for_taxes_computation(
        line, line.prepareBaseLineForTaxesComputationExtraValues()
    ));
    accountTaxHelpers.add_tax_details_in_base_lines(bases, order.company_id);
    accountTaxHelpers.round_base_lines_tax_details(bases, order.company_id);
    const gross = bases.reduce((sum, base) => sum + base.tax_details.total_included_currency, 0);
    const value = Number(intent.value);
    const discount = intent.kind === "percent" ? gross * value / 100 : value;
    const maxPercent = Number(pos.config.baseer_global_discount_max_percent);
    const maxAmount = Number(pos.config.baseer_global_discount_max_amount);
    if (!Number.isFinite(gross) || !Number.isFinite(maxPercent) || !Number.isFinite(maxAmount) || gross <= 0 || discount > gross || value <= 0 ||
        (intent.kind === "percent" && value > 100) || discount * 100 > gross * maxPercent ||
        (maxAmount > 0 && discount > maxAmount)) {
        throw new Error(_t("The discount exceeds the permitted amount or invoice total."));
    }
    const discountBases = accountTaxHelpers.prepare_global_discount_lines(
        bases, order.company_id, intent.kind, value,
        { computation_key: "baseer_global_discount", grouping_function: () => ({
            grouping_key: { product_id: product }, raw_grouping_key: { product_id: product.id },
        }) }
    );
    if (!discountBases.length) throw new Error(_t("The discount could not be calculated for this order."));
    return { product, accountProof, discountBases };
}

/** A POS preview; the server reconstructs and validates every financial line. */
export function refreshOfflineDiscount(pos, order) {
    const intent = order?.uiState?.baseerOfflineDiscount;
    if (!intent || order.state !== "draft") return;
    pos._baseerOfflineRebuilding ||= new Set();
    if (pos._baseerOfflineRebuilding.has(order.uuid)) return;
    pos._baseerOfflineRebuilding.add(order.uuid);
    try {
        const { product, accountProof, discountBases } = calculateOfflineDiscount(pos, order, intent);
        const previous = new Set(intent.preview_line_uuids || []);
        for (const line of [...order.lines]) if (previous.has(line.uuid)) line.delete();
        intent.preview_line_uuids = [];
        intent.account_proof = accountProof;
        for (const base of discountBases) {
            const uuid = crypto.randomUUID();
            intent.preview_line_uuids.push(uuid);
            pos.models["pos.order.line"].create({
                uuid, order_id: order, product_id: product, product_tmpl_id: product.product_tmpl_id,
                price_unit: base.price_unit, qty: base.quantity, discount: 0, price_type: "manual",
                tax_ids: [["link", ...base.tax_ids]],
                extra_tax_data: accountTaxHelpers.export_base_line_extra_tax_data(base),
            });
        }
        if (!intent.preview_line_uuids.length) throw new Error(_t("The discount could not be calculated for this order."));
        order.triggerRecomputeAllPrices();
        intent.expected_total = order.currency.round(order.priceIncl).toFixed(2);
        intent.expected_tax = order.currency.round(order.amountTaxes).toFixed(2);
        intent.error = false;
        order._markDirty();
    } catch (error) {
        intent.error = error?.message || _t("The discount could not be calculated for this order.");
        order.triggerRecomputeAllPrices();
        order._markDirty();
    } finally {
        // Direct uiState mutations do not consistently emit model events.
        order.models?._baseerDraftGenerationTracker?.touch();
        pos._baseerOfflineRebuilding.delete(order.uuid);
    }
}

export function wireOfflineDiscount(intent) {
    const { version, order_uuid, action_uuid, kind, value, expected_total, expected_tax, account_proof, preview_line_uuids } = intent;
    return { version, order_uuid, action_uuid, kind, value, expected_total, expected_tax, account_proof, preview_line_uuids: [...preview_line_uuids] };
}

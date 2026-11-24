/** @odoo-module **/

const numericId = (value) => typeof value === 'number' ? value : value?.id;
// Odoo leaves discount unset on a new local line; its native getter resolves
// that case to 0. Read it through the same API before and after relinking.
const lineDiscount = (line) => typeof line?.getDiscount === 'function' ? line.getDiscount() : line?.discount;
const taxIds = (line) => {
    if (!Array.isArray(line?.tax_ids)) return null;
    const ids = line.tax_ids.map(numericId);
    if (ids.some((id) => !Number.isSafeInteger(id) || id < 1) || new Set(ids).size !== ids.length) return null;
    return ids.sort((left, right) => left - right);
};

/** Relink only the exact acknowledged, unchanged order through native models. */
export async function relinkSharedDraftForKitchen(pos, order) {
    const state = order?.uiState;
    const tracker = order?.models?._baseerDraftGenerationTracker;
    const serverId = state?.baseerSharedDraftServerOrderId;
    const revision = state?.baseerSharedDraftRevision;
    const sessionId = numericId(pos?.config?.current_session_id);
    const configId = numericId(pos?.config);
    const companyId = numericId(pos?.config?.company_id);
    const clean = () => {
        const current = order?.uiState;
        return Boolean(order?.state === 'draft' && tracker &&
            Number.isSafeInteger(current?.baseerSharedDraftGeneration) &&
            tracker.get() === current.baseerSharedDraftGeneration && !current.baseerSharedDraftNeedsSync &&
            !current.baseerSharedDraftPending && !current.baseerSharedDraftCancelPending &&
            !current.baseerSharedDraftCancelAcknowledged && !current.baseerPreparationOutcomeUnknown &&
            !current.baseerSharedDraftRefreshError && !current.baseerSharedDraftHydrationError &&
            !current.baseerSharedDraftContaminated && !current.baseerSharedDraftRemoteDeleted &&
            !current.baseerSharedDraftPaidAckPending && !current.baseerBillSplitPending &&
            !current.baseerRestaurantMergePending && !pos?.data?.network?.offline);
    };
    if (!clean() || typeof pos?.baseerRefreshCleanSharedDraftExperiment !== 'function' ||
        !order?.uuid || !Number.isSafeInteger(serverId) || serverId < 1 ||
        !Number.isSafeInteger(revision) || revision < 1 ||
        !Number.isSafeInteger(sessionId) || !Number.isSafeInteger(configId) ||
        !Number.isSafeInteger(companyId) || numericId(order.session_id) !== sessionId ||
        numericId(order.config_id) !== configId || numericId(order.company_id) !== companyId) {
        throw new Error('The acknowledged shared order identity cannot be verified. Keep the order open.');
    }
    const preview = new Set(state.baseerOfflineDiscount?.preview_line_uuids || []);
    const sources = (order.lines || []).filter((line) => !line.baseer_global_discount_line && !preview.has(line.uuid));
    const lines = sources.map((line) => ({
        uuid: line.uuid, id: state.baseerSharedDraftLineIds?.[line.uuid],
        productId: numericId(line.product_id),
        qty: typeof line.getQuantity === 'function' ? line.getQuantity() : line.qty,
        priceUnit: line.price_unit, discount: lineDiscount(line), taxIds: taxIds(line),
    }));
    const invalid = new Set();
    if (!lines.length) invalid.add('empty');
    if (new Set(lines.map((line) => line.uuid)).size !== lines.length) invalid.add('duplicate');
    for (const line of lines) {
        if (!line.uuid) invalid.add('uuid');
        if (!Number.isSafeInteger(line.id) || line.id < 1) invalid.add('server_id');
        if (!Number.isSafeInteger(line.productId) || line.productId < 1) invalid.add('product');
        if (!Number.isFinite(line.qty)) invalid.add('quantity');
        if (!Number.isFinite(line.priceUnit)) invalid.add('price');
        if (!Number.isFinite(line.discount)) invalid.add('discount');
        if (line.taxIds === null) invalid.add('taxes');
    }
    if (invalid.size) {
        throw new Error(`The acknowledged shared order lines cannot be verified (${[...invalid].join(', ')}). Keep the order open.`);
    }
    const expected = { serverId, revision, uuid: order.uuid, sessionId, configId, companyId, lines };
    if (!await pos.baseerRefreshCleanSharedDraftExperiment(order, { expected })) {
        throw new Error('The shared order changed before kitchen sending. Keep the order open.');
    }
    const current = pos.models?.['pos.order']?.getBy('uuid', expected.uuid);
    const byUuid = new Map((current?.lines || []).map((line) => [line.uuid, line]));
    if (current !== order || pos.getOrder()?.uuid !== expected.uuid || !clean() ||
        !current.isSynced || current.id !== serverId ||
        current.uiState.baseerSharedDraftRevision !== revision ||
        numericId(current.session_id) !== sessionId || numericId(current.config_id) !== configId ||
        numericId(current.company_id) !== companyId ||
        lines.some(({ uuid, id, productId, qty, priceUnit, discount, taxIds: expectedTaxes }) => {
            const line = byUuid.get(uuid);
            const actualQty = typeof line?.getQuantity === 'function' ? line.getQuantity() : line?.qty;
            const actualTaxes = taxIds(line);
            return line?.id !== id || numericId(line?.product_id) !== productId || actualQty !== qty ||
                line?.price_unit !== priceUnit || lineDiscount(line) !== discount || actualTaxes === null ||
                actualTaxes.length !== expectedTaxes.length || actualTaxes.some((tax, index) => tax !== expectedTaxes[index]);
        })) {
        throw new Error('The shared order identity changed during kitchen sending. Keep the order open.');
    }
    return current;
}

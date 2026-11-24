/**
 * Experimental isolated transport for an Odoo draft snapshot.
 * Not registered in POS assets: caller must supply atomic persistence and a
 * guarded acknowledgement commit before this can be integrated.
 */
const draftFlights = new Map();

/** Serialize draft sync and cancel operations per UUID without blocking edits. */
export function singleFlightDraftExperiment(orderUuid, commandUuid, requestBytes, run) {
    if (typeof orderUuid !== 'string' || !orderUuid || typeof commandUuid !== 'string' || !commandUuid || typeof requestBytes !== 'string' || !requestBytes || typeof run !== 'function') throw new Error('Invalid draft flight');
    const current = draftFlights.get(orderUuid);
    if (current) {
        if (current.commandUuid !== commandUuid || current.requestBytes !== requestBytes) throw new Error('Another draft command is pending');
        return current.promise;
    }
    const flight = Promise.resolve().then(run).finally(() => {
        if (draftFlights.get(orderUuid)?.promise === flight) draftFlights.delete(orderUuid);
    });
    draftFlights.set(orderUuid, { commandUuid, requestBytes, promise: flight });
    return flight;
}

export function trackDraftGraphGeneration(models, initialGeneration = 0) {
    // A single epoch is deliberately conservative: a deleted child may have
    // already lost its parent relation when the delete event is delivered.
    // Any dynamic graph change therefore invalidates an in-flight capture.
    const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
    const listeners = [];
    if (!Number.isSafeInteger(initialGeneration) || initialGeneration < 0) throw new Error('Invalid draft graph generation');
    let generation = initialGeneration;
    const changed = () => { generation++; };
    for (const name of names) {
        const model = models[name];
        if (!model?.addEventListener) throw new Error('Draft graph event source unavailable');
    }
    try {
        for (const name of names) {
            const model = models[name];
            for (const event of ['create', 'update', 'delete']) {
                const unsubscribe = model.addEventListener(event, changed);
                if (typeof unsubscribe !== 'function') throw new Error('Draft graph event source cannot be detached');
                listeners.push(unsubscribe);
            }
        }
    } catch (error) {
        for (const release of listeners) release();
        throw error;
    }
    return {
        get: () => generation,
        // uiState edits do not necessarily emit a model update event.
        touch: changed,
        dispose() { for (const release of listeners.splice(0)) release(); },
    };
}

/** Explicit opt-in adapter; caller must install it before the first POS sync. */
export function attachDraftGenerationExperiment(models) {
    if (models._baseerDraftGenerationTracker) return models._baseerDraftGenerationTracker;
    const orders = models['pos.order']?.getAll?.();
    if (!Array.isArray(orders)) throw new Error('Draft orders are unavailable');
    let initial = 0;
    for (const order of orders) {
        for (const value of [order.uiState?.baseerSharedDraftGeneration, order.uiState?.baseerSharedDraftPending?.generation]) {
            if (value !== undefined && (!Number.isSafeInteger(value) || value < 0)) throw new Error('Invalid saved draft generation');
            if (value !== undefined) initial = Math.max(initial, value);
        }
    }
    const tracker = trackDraftGraphGeneration(models, initial);
    try {
        // Models is a model-name registry; don't expose bookkeeping as a model.
        Object.defineProperty(models, '_baseerDraftGenerationTracker', { value: tracker, enumerable: false, configurable: true });
    } catch (error) { tracker.dispose(); throw error; }
    return tracker;
}

/** Prototype only: remove server allowances from the local graph, not the server. */
export function detachServerAllowancesExperiment(order) {
    const lines = (order.lines || []).filter((line) => line.baseer_global_discount_line);
    const commands = order.models?.commands?.['pos.order'];
    if (!commands?.unlink || !commands?.delete) throw new Error('Order relationship commands unavailable');
    const ids = new Set();
    for (const line of lines) {
        if (!Number.isSafeInteger(line.id) || !line.model?.delete || ids.has(line.id)) throw new Error('Invalid server allowance');
        ids.add(line.id);
        for (const kind of ['unlink', 'delete']) {
            if ((commands[kind].get('lines') || []).some((item) => item.parentId === order.id && item.id === line.id)) {
                throw new Error('A server allowance already has a local removal command');
            }
        }
    }
    for (const line of lines) {
        line.model.delete(line, { silent: true });
        // Odoo creates unlink commands even for silent local deletes. Remove
        // only those introduced by this detach, leaving all other edits intact.
        for (const kind of ['unlink', 'delete']) {
            const prior = commands[kind].get('lines') || [];
            const keep = prior.filter((item) => item.parentId !== order.id || item.id !== line.id);
            if (keep.length) commands[kind].set('lines', keep); else commands[kind].delete('lines');
        }
    }
    return [...ids];
}

/**
 * Prototype synchronous graph replacement with explicit rollback. Never call
 * this from POS until full model/event, tax and kitchen behavior is verified.
 */
export function replaceServerAllowancesExperiment({ order, calculate, buildPreview }) {
    if (!order?.models || typeof calculate !== 'function' || typeof buildPreview !== 'function') throw new Error('Draft preview replacement is unavailable');
    // Validation occurs before changing any model or relationship.
    const calculated = calculate();
    const allowances = (order.lines || []).filter((line) => line.baseer_global_discount_line);
    const originals = allowances.map((line) => ({ model: line.model, id: line.id,
        values: JSON.parse(JSON.stringify(line.serializeForIndexedDB())) }));
    const commands = order.models.commands['pos.order'];
    if (!commands?.unlink || !commands?.delete) throw new Error('Order relationship commands unavailable');
    const saved = {};
    for (const kind of ['unlink', 'delete']) {
        saved[kind] = new Map([...commands[kind]].map(([field, entries]) => [field, entries.map((entry) => ({ ...entry }))]));
    }
    const createdUuids = new Set();
    try {
        detachServerAllowancesExperiment(order);
        // Register each UUID before invoking native model.create, including
        // when a synchronous create listener throws after creating a record.
        buildPreview(calculated, (uuid) => {
            if (typeof uuid !== 'string' || !uuid || createdUuids.has(uuid)) throw new Error('Invalid draft preview UUID');
            createdUuids.add(uuid);
        });
        return calculated;
    } catch (error) {
        try {
            for (const line of [...order.lines]) if (createdUuids.has(line.uuid)) line.model.delete(line, { silent: true });
            for (const original of originals) {
                const existing = original.model.read(original.id);
                if (existing) {
                    if (existing.order_id !== order) existing.update({ order_id: order });
                } else {
                    original.model.create({ ...original.values, order_id: order });
                }
            }
            for (const kind of ['unlink', 'delete']) {
                commands[kind].clear();
                for (const [field, entries] of saved[kind]) commands[kind].set(field, entries);
            }
        } catch (rollbackError) {
            throw new Error('Draft preview rollback failed; keep the order for manager review', { cause: rollbackError });
        }
        throw error;
    }
}

/** Prototype hydration of a server draft; callers must guard payment on error. */
export function hydrateSharedDraftExperiment({ pos, order, calculate, exportExtraTaxData }) {
    if (!pos?.config || !order?.uiState || order.state !== 'draft' || typeof calculate !== 'function' || typeof exportExtraTaxData !== 'function') {
        throw new Error('Shared draft hydration is unavailable');
    }
    if (order.uiState.baseerOfflineDiscount || order.uiState.baseerSharedDraftPending) throw new Error('A local draft command already exists');
    if (!['fixed', 'percent'].includes(order.baseer_offline_draft_kind) || !order.baseer_offline_draft_value ||
        !Number.isSafeInteger(order.baseer_offline_draft_revision) || order.baseer_offline_draft_revision < 1) {
        throw new Error('The shared draft discount is invalid');
    }
    const intent = {
        version: 1, order_uuid: order.uuid, action_uuid: crypto.randomUUID(), kind: order.baseer_offline_draft_kind,
        value: order.baseer_offline_draft_value, account_proofs: { ...(pos.config.baseer_offline_discount_account_proofs || {}) },
        preview_line_uuids: [], removed_line_ids: [], removed_payment_ids: [],
    };
    const oldTotal = order.currency.round(order.priceIncl);
    const oldTax = order.currency.round(order.amountTaxes);
    try {
        replaceServerAllowancesExperiment({ order, calculate: () => calculate(pos, order, intent), buildPreview: (result, register) => {
            intent.account_proof = result.accountProof;
            order.uiState.baseerOfflineDiscount = intent;
            for (const base of result.discountBases) {
                const uuid = crypto.randomUUID();
                register(uuid);
                intent.preview_line_uuids.push(uuid);
                pos.models['pos.order.line'].create({ uuid, order_id: order, product_id: result.product,
                    product_tmpl_id: result.product.product_tmpl_id, price_unit: base.price_unit, qty: base.quantity,
                    discount: 0, price_type: 'manual', tax_ids: [['link', ...base.tax_ids]],
                    extra_tax_data: exportExtraTaxData(base) });
            }
            order.triggerRecomputeAllPrices();
            if (order.currency.round(order.priceIncl) !== oldTotal || order.currency.round(order.amountTaxes) !== oldTax) {
                throw new Error('The shared draft discount total does not match the server');
            }
            intent.expected_total = oldTotal.toFixed(2);
            intent.expected_tax = oldTax.toFixed(2);
            intent.error = false;
        } });
        delete order.uiState.baseerSharedDraftHydrationError;
        order.models?._baseerDraftGenerationTracker?.touch();
        return intent;
    } catch (error) {
        delete order.uiState.baseerOfflineDiscount;
        order.uiState.baseerSharedDraftHydrationError = error?.message || 'Shared draft discount needs review';
        order.models?._baseerDraftGenerationTracker?.touch();
        order.triggerRecomputeAllPrices();
        throw error;
    }
}

/** Stage a server graph in native models; caller must persist before publishing. */
export function stageNativeServerGraphExperiment({ order, response, verify, beforeLoad = () => {} }) {
    if (!order?.models?.loadConnectedData || !order.uiState || typeof verify !== 'function' || typeof beforeLoad !== 'function') throw new Error('Server graph reconciliation is unavailable');
    const models = order.models;
    const originalLines = [...(order.lines || [])];
    const originalPayments = [...(order.payment_ids || [])];
    const originalAttrs = [...new Map(originalLines.flatMap((line) => line.custom_attribute_value_ids || []).map((item) => [item.id, item])).values()];
    const serial = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
    const snapshot = { 'pos.order': [serial(order)], 'pos.order.line': originalLines.map(serial),
        'pos.payment': originalPayments.map(serial), 'product.attribute.custom.value': originalAttrs.map(serial) };
    const parents = new Set([order.id, order.uuid, ...originalLines.flatMap((line) => [line.id, line.uuid]),
        ...originalPayments.flatMap((payment) => [payment.id, payment.uuid])].filter((id) => id !== undefined && id !== null));
    for (const row of [...(response?.['pos.order'] || []), ...(response?.['pos.order.line'] || []), ...(response?.['pos.payment'] || [])]) {
        if (row.id !== undefined && row.id !== null) parents.add(row.id);
        if (row.uuid) parents.add(row.uuid);
    }
    const savedCommands = {};
    for (const [model, commands] of Object.entries(models.commands)) {
        savedCommands[model] = {};
        for (const kind of ['unlink', 'delete']) savedCommands[model][kind] = new Map([...commands[kind]].map(([field, rows]) =>
            [field, rows.filter((row) => parents.has(row.parentId)).map((row) => ({ ...row }))]));
    }
    const restore = () => {
        for (const line of [...(order.lines || [])]) line.model.delete(line, { silent: true });
        for (const payment of [...(order.payment_ids || [])]) payment.model.delete(payment, { silent: true });
        models.loadConnectedData(snapshot);
        for (const [model, commands] of Object.entries(models.commands)) {
            for (const kind of ['unlink', 'delete']) {
                const saved = savedCommands[model]?.[kind] || new Map();
                const fields = new Set([...commands[kind].keys(), ...saved.keys()]);
                for (const field of fields) {
                    const keep = (commands[kind].get(field) || []).filter((row) => !parents.has(row.parentId));
                    const rows = [...keep, ...(saved.get(field) || [])];
                    if (rows.length) commands[kind].set(field, rows); else commands[kind].delete(field);
                }
            }
        }
    };
    try {
        const preview = new Set(order.uiState.baseerOfflineDiscount?.preview_line_uuids || []);
        for (const line of [...order.lines]) if (preview.has(line.uuid)) line.model.delete(line, { silent: true });
        beforeLoad(order);
        models.loadConnectedData(response);
        verify(order);
        return { rollback: restore };
    } catch (error) {
        try { restore(); }
        catch (rollbackError) { throw new Error('Paid graph rollback failed; keep the order for manager review', { cause: rollbackError }); }
        throw error;
    }
}

export function stagePaidServerGraphExperiment({ order, response, pending, verify }) {
    if (!['paid', 'done', 'invoiced'].includes(order?.state) || !order.uiState?.baseerSharedDraftPaidAckPending || pending?.order_uuid !== order.uuid) {
        throw new Error('Paid graph reconciliation is unavailable');
    }
    return stageNativeServerGraphExperiment({ order, response, verify });
}

/** Acknowledge deletion events by immutable token, never by record ID alone. */
export function acknowledgeDraftTombstonesExperiment(events, sentTokens) {
    if (!Array.isArray(events) || !Array.isArray(sentTokens) ||
        events.some((event) => !event || typeof event.token !== 'string' || !event.token || !Number.isSafeInteger(event.id)) ||
        new Set(events.map((event) => event.token)).size !== events.length ||
        sentTokens.some((token) => typeof token !== 'string' || !token)) {
        throw new Error('Invalid draft deletion events');
    }
    const acknowledged = new Set(sentTokens);
    return events.filter((event) => !acknowledged.has(event.token));
}

/** Resolve a later deletion of a local-UUID record acknowledged by the server. */
export function mappedDraftDeletionExperiment({ uuid, token, mapping, events }) {
    if (typeof uuid !== 'string' || !uuid || typeof token !== 'string' || !token || !mapping || !Array.isArray(events)) {
        throw new Error('Invalid draft deletion');
    }
    const id = mapping[uuid];
    if (!Number.isSafeInteger(id) || id <= 0) throw new Error('Draft item server identity is unavailable');
    if (events.some((event) => event.token === token)) throw new Error('Duplicate draft deletion token');
    return [...events, { id, token }];
}

/** Plan only; the caller must atomically persist it with the live graph. */
export function planDraftAckExperiment({ pending, revision, serverOrderId, lineIds, paymentIds, current }) {
    if (!pending?.command_uuid || revision !== pending.revision + 1 || current?.order_uuid !== pending.order_uuid ||
        current.pending_command_uuid !== pending.command_uuid || !Number.isSafeInteger(pending.generation) ||
        !Number.isSafeInteger(current.generation) || current.generation < pending.generation || !Number.isSafeInteger(serverOrderId)) {
        throw new Error('Draft acknowledgement is stale');
    }
    const planned = {};
    for (const [kind, ids] of [['line', lineIds], ['payment', paymentIds]]) {
        const sentUuids = pending[`source_${kind}_uuids`] || [];
        const liveUuids = new Set(current[`${kind}_uuids`] || []);
        const liveIds = new Set(current[`${kind}_ids`] || []);
        const sentDeletedIds = pending[`sent_${kind}_deletion_ids`] || [];
        // An acknowledged delete followed by a local relink cannot be sent as
        // UPDATE to a record that the server has already deleted.
        if (sentDeletedIds.some((id) => liveIds.has(id))) throw new Error('A deleted draft item was restored and needs review');
        const events = acknowledgeDraftTombstonesExperiment(current[`${kind}_deletions`] || [], pending[`sent_${kind}_deletion_tokens`] || []);
        const knownIds = new Set(events.map((event) => event.id));
        const liveMap = {};
        for (const uuid of sentUuids) {
            const id = ids?.[uuid];
            if (!Number.isSafeInteger(id)) throw new Error('Draft item acknowledgement cannot be verified');
            if (liveUuids.has(uuid)) { liveMap[uuid] = id; continue; }
            if (!knownIds.has(id)) events.push({ id, token: `${pending.command_uuid}:${kind}:${uuid}` });
        }
        planned[`${kind}_deletions`] = events;
        planned[`${kind}_ids_by_uuid`] = liveMap;
    }
    return { revision, server_order_id: serverOrderId, ...planned, needs_sync: current.generation !== pending.generation };
}

function validateSnapshot(snapshot) {
    if (!snapshot?.order_uuid || !snapshot.command_uuid || !Number.isSafeInteger(snapshot.revision) || snapshot.revision < 0 ||
        !Array.isArray(snapshot.source_line_uuids) || new Set(snapshot.source_line_uuids).size !== snapshot.source_line_uuids.length ||
        snapshot.source_line_uuids.some((uuid) => typeof uuid !== 'string' || !uuid) || typeof snapshot.payload_json !== 'string') {
        throw new Error('Invalid draft snapshot');
    }
    if (snapshot.source_payment_uuids !== undefined && (!Array.isArray(snapshot.source_payment_uuids) ||
        new Set(snapshot.source_payment_uuids).size !== snapshot.source_payment_uuids.length ||
        snapshot.source_payment_uuids.some((uuid) => typeof uuid !== 'string' || !uuid))) throw new Error('Invalid draft snapshot');
    const payload = JSON.parse(snapshot.payload_json);
    const command = payload.baseer_offline_draft_command;
    if (payload.uuid !== snapshot.order_uuid || command?.command_uuid !== snapshot.command_uuid ||
        command?.revision !== snapshot.revision || !['set', 'keep', 'remove'].includes(command?.operation)) {
        throw new Error('Draft snapshot does not match its command');
    }
    return payload;
}

/** Validate server financial identity before retaining a paid ACK for review. */
export function validatePaidAckGraphExperiment(pending, payload, result, serverOrder) {
    if ((result['pos.pack.operation.lot'] || []).length) throw new Error('Tracked product data needs manager review');
    const expected = payload.baseer_offline_discount_intent;
    const cents = (value) => {
        if (value === null || value === undefined || value === '') throw new Error('Paid order totals cannot be verified');
        const number = Number(value);
        if (!Number.isFinite(number)) throw new Error('Paid order totals cannot be verified');
        return Math.round(number * 100);
    };
    if (Boolean(expected) !== Boolean(serverOrder.baseer_global_discount_locked) ||
        cents(serverOrder.amount_total) !== cents(expected?.expected_total ?? payload.amount_total) ||
        cents(serverOrder.amount_tax) !== cents(expected?.expected_tax ?? payload.amount_tax)) {
        throw new Error('Paid order totals cannot be verified');
    }
    const sourceUuids = new Set(pending.source_line_uuids);
    const allowances = (result['pos.order.line'] || []).filter((line) => line.baseer_global_discount_line);
    if (Boolean(expected) !== Boolean(allowances.length)) throw new Error('Paid order discounts cannot be verified');
    for (const line of result['pos.order.line'] || []) {
        if (!line.baseer_global_discount_line && !sourceUuids.has(line.uuid)) throw new Error('Paid order lines cannot be verified');
    }
    if (payload.to_invoice) {
        const moveId = Array.isArray(serverOrder.account_move) ? serverOrder.account_move[0] : serverOrder.account_move;
        const moves = (result['account.move'] || []).filter((move) => move.id === moveId);
        if (!Number.isSafeInteger(moveId) || moveId <= 0 || moves.length !== 1) throw new Error('The server invoice acknowledgement cannot be verified');
    }
}

/** A missing permission or offline server never proves invoice posting. */
export async function verifyPaidInvoiceExperiment({ pending, response, readInvoice }) {
    if (!pending?.payload_json || typeof readInvoice !== 'function') throw new Error('Invoice verification is unavailable');
    const payload = JSON.parse(pending.payload_json);
    if (!payload.to_invoice) return { required: false, confirmed: false };
    const orders = response?.['pos.order'] || [];
    const order = orders.find((row) => row.uuid === pending.order_uuid);
    const moveId = Array.isArray(order?.account_move) ? order.account_move[0] : order?.account_move;
    if (orders.length !== 1 || !Number.isSafeInteger(moveId) || moveId <= 0) return { required: true, confirmed: false };
    try {
        const moves = await readInvoice(moveId);
        return { required: true, confirmed: Array.isArray(moves) && moves.length === 1 && moves[0].id === moveId && moves[0].state === 'posted' };
    } catch {
        return { required: true, confirmed: false };
    }
}

export async function syncDraftSnapshot({ readPending, createSnapshot, persistPending, send, commitAck }) {
    let pending = readPending();
    if (!pending) {
        const snapshot = createSnapshot();
        validateSnapshot(snapshot);
        // This callback must commit the complete native graph and the exact
        // snapshot in the same IndexedDB transaction before resolving.
        await persistPending(snapshot);
        pending = snapshot;
    }
    const payload = validateSnapshot(pending);
    // Raw ORM call only: never pass this response into loadConnectedData.
    const result = await send(payload);
    const orders = result?.['pos.order'] || [];
    const order = orders.find((item) => item.uuid === pending.order_uuid);
    if (orders.length !== 1 || !order || !Number.isSafeInteger(order.id) || order.baseer_offline_draft_revision !== pending.revision + 1) {
        throw new Error('Draft acknowledgement cannot be verified');
    }
    if (pending.target_state === 'draft' && order.state !== 'draft' ||
        pending.target_state === 'paid' && !['paid', 'done', 'invoiced'].includes(order.state)) {
        throw new Error('Order acknowledgement state cannot be verified');
    }
    if (pending.target_state === 'paid') validatePaidAckGraphExperiment(pending, payload, result, order);
    const lines = result['pos.order.line'] || [];
    const lineIds = {};
    for (const uuid of pending.source_line_uuids) {
        const matches = lines.filter((line) => line.uuid === uuid && !line.baseer_global_discount_line);
        if (matches.length !== 1 || !Number.isSafeInteger(matches[0].id)) throw new Error('Draft line acknowledgement cannot be verified');
        lineIds[uuid] = matches[0].id;
    }
    const payments = result['pos.payment'] || [];
    const paymentIds = {};
    for (const uuid of pending.source_payment_uuids || []) {
        const matches = payments.filter((payment) => payment.uuid === uuid);
        if (matches.length !== 1 || !Number.isSafeInteger(matches[0].id)) throw new Error('Draft payment acknowledgement cannot be verified');
        paymentIds[uuid] = matches[0].id;
    }
    // The caller must compare with the live graph under its write guard, record
    // deleted UUIDs as server-ID tombstones, and persist the resulting graph,
    // revision and pending snapshot removal together. No native dirty flags or
    // pending queue entries may be cleared by this transport.
    await commitAck({ pending, revision: order.baseer_offline_draft_revision, serverOrderId: order.id, lineIds, paymentIds,
        serverResponse: pending.target_state === 'paid' ? JSON.parse(JSON.stringify(result)) : null });
}

export function runDraftSnapshotExperiment(adapter) {
    const candidate = adapter.readPending() || adapter.createSnapshot();
    validateSnapshot(candidate);
    return singleFlightDraftExperiment(candidate.order_uuid, candidate.command_uuid, JSON.stringify(candidate),
        () => syncDraftSnapshot({ ...adapter, createSnapshot: () => candidate, readPending: () => {
            const current = adapter.readPending();
            if (current && JSON.stringify(current) !== JSON.stringify(candidate)) throw new Error('Another draft command is pending');
            return current;
        } }));
}

/** Construct an opt-in draft adapter over actual POS order/ORM interfaces. */
export function createDraftSyncAdapterExperiment({ data, order, tracker, protect, prepare, getContext, offlineError }) {
    if (!data?.orm?.call || !data?.network || !order?.serializeForORM || !tracker?.get ||
        typeof protect !== 'function' || typeof prepare !== 'function' || typeof getContext !== 'function' || typeof offlineError !== 'function') {
        throw new Error('Draft sync adapter is unavailable');
    }
    return {
        readPending: () => order.uiState.baseerSharedDraftPending,
        createSnapshot() {
            if (!['draft', 'paid'].includes(order.state)) throw new Error('Shared sync requires a draft or paid order');
            if (order.state === 'paid' && order.uiState.baseerOfflineDiscount?.retry_payload) {
                throw new Error('An existing payment payload needs manager review');
            }
            prepare(order);
            const intent = order.uiState.baseerOfflineDiscount;
            const revision = order.uiState.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision ?? 0;
            const kind = order.uiState.baseerSharedDraftKind ?? order.baseer_offline_draft_kind ?? false;
            const value = order.uiState.baseerSharedDraftValue ?? order.baseer_offline_draft_value ?? false;
            const operation = intent ? (kind === intent.kind && value === intent.value ? 'keep' : 'set') : (kind ? 'remove' : 'keep');
            const commandUuid = crypto.randomUUID();
            const payload = order.serializeForORM({ keepCommands: true });
            // These fields are server-owned results. A shared draft command
            // carries its intent separately and the server reconstructs them.
            for (const field of ['baseer_global_discount_kind', 'baseer_global_discount_value',
                'baseer_global_discount_gross', 'baseer_global_discount_locked', 'baseer_global_discount_reason',
                'baseer_global_discount_snapshot', 'baseer_offline_draft_kind', 'baseer_offline_draft_value',
                'baseer_offline_draft_revision', 'baseer_offline_draft_command_uuid', 'baseer_offline_draft_digest']) delete payload[field];
            payload.baseer_offline_draft_command = { revision, command_uuid: commandUuid, operation };
            const preview = new Set(intent?.preview_line_uuids || []);
            const commandIds = (commands) => new Set((commands || []).filter((command) => [2, 3].includes(command[0])).map((command) => command[1]));
            const sentLineIds = commandIds(payload.lines);
            const sentPaymentIds = commandIds(payload.payment_ids);
            const lineEvents = (order.uiState.baseerSharedDraftLineDeletions || []).filter((event) => sentLineIds.has(event.id));
            const paymentEvents = (order.uiState.baseerSharedDraftPaymentDeletions || []).filter((event) => sentPaymentIds.has(event.id));
            return {
                order_uuid: order.uuid, command_uuid: commandUuid, revision, generation: tracker.get(), target_state: order.state,
                source_line_uuids: (order.lines || []).filter((line) => !line.baseer_global_discount_line && !preview.has(line.uuid)).map((line) => line.uuid),
                source_payment_uuids: (order.payment_ids || []).map((payment) => payment.uuid),
                sent_line_deletion_ids: lineEvents.map((event) => event.id), sent_line_deletion_tokens: lineEvents.map((event) => event.token),
                sent_payment_deletion_ids: paymentEvents.map((event) => event.id), sent_payment_deletion_tokens: paymentEvents.map((event) => event.token),
                sent_legacy_line_deletion_ids: (intent?.removed_line_ids || []).filter((id) => sentLineIds.has(id)),
                sent_legacy_payment_deletion_ids: (intent?.removed_payment_ids || []).filter((id) => sentPaymentIds.has(id)),
                payload_json: JSON.stringify(payload), context_json: JSON.stringify(getContext(order)),
            };
        },
        persistPending: (pending) => persistPendingDraftOrderExperiment({ data, order, tracker, pending, protect }),
        async send(payload) {
            if (data.network.offline) throw offlineError();
            const pending = order.uiState.baseerSharedDraftPending;
            if (!pending || JSON.stringify(payload) !== pending.payload_json) throw new Error('Draft command is no longer current');
            return data.orm.call('pos.order', 'sync_from_ui', [[payload]], { context: JSON.parse(pending.context_json) });
        },
        commitAck: ({ pending, revision, serverOrderId, lineIds, paymentIds, serverResponse }) =>
            persistDraftAckExperiment({ data, order, tracker, pending, revision, serverOrderId, lineIds, paymentIds, serverResponse, protect }),
    };
}

/** Settle a previous draft command first; only then freeze/send the paid graph. */
export async function runPaidAfterDraftExperiment(adapter, order) {
    if (order?.state !== 'paid') throw new Error('A paid order is required');
    const prior = adapter.readPending();
    if (prior && prior.target_state !== 'paid') await runDraftSnapshotExperiment(adapter);
    return runDraftSnapshotExperiment(adapter);
}

/** Cancellation is experimental too; the caller owns atomic graph persistence. */
/** Compare this order's full native graph independently of the shared model generation. */
export function cancelGraphFingerprint(order) {
    if (!order?.uuid || !Array.isArray(order.lines) || !Array.isArray(order.payment_ids) ||
        typeof order.serializeForIndexedDB !== 'function') throw new Error('The order graph is incomplete');
    const serialize = (record) => {
        if (!record || typeof record.serializeForIndexedDB !== 'function') throw new Error('The order graph is incomplete');
        return JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
    };
    const header = serialize(order);
    if (typeof header.JSONuiState !== 'string') throw new Error('The order UI state is incomplete');
    const ui = JSON.parse(header.JSONuiState);
    if (!ui || typeof ui !== 'object' || Array.isArray(ui)) throw new Error('The order UI state is incomplete');
    for (const name of ['baseerSharedDraftCancelPending', 'baseerSharedDraftKitchenCancelIntent',
        'baseerKitchenCancellation', 'baseerSharedDraftGeneration']) delete ui[name];
    header.JSONuiState = ui;
    const canonical = (value) => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
        ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])])) : value;
    const sort = (values) => values.map(serialize).map(canonical).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    const attrs = [...new Map(order.lines.flatMap((line) => line.custom_attribute_value_ids || []).map((record) => [record.id, record])).values()];
    return JSON.stringify(canonical({ header, lines: sort(order.lines), payments: sort(order.payment_ids), attrs: sort(attrs) }));
}

export function cancelGraphUnchanged(order, pending, tracker) {
    if (!Number.isSafeInteger(pending?.generation) || !tracker?.get) return false;
    if (typeof pending.graph_fingerprint === 'string' && pending.graph_fingerprint) {
        try {
            const prior = JSON.parse(pending.graph_fingerprint), current = JSON.parse(cancelGraphFingerprint(order));
            const normalize = (graph) => {
                const ui = graph?.header?.JSONuiState;
                if (!ui || typeof ui !== 'object' || Array.isArray(ui)) throw new Error('Invalid order UI state');
                // Selection is presentation state; it changes on reopening a POS order.
                delete ui.selected_orderline_uuid;
                if (order.uiState?.baseerSharedDraftRemoteDeleted === true && order.uiState?.baseerSharedDraftKitchenCancelIntent) {
                    // A remote-delete notice and the recovery it triggers may be
                    // this very frozen cancellation. The server still verifies
                    // the exact command and reason before any local deletion.
                    delete ui.baseerSharedDraftRemoteDeleted;
                    delete ui.baseerSharedDraftRefreshError;
                    delete ui.baseerSharedDraftNeedsSync;
                }
                return JSON.stringify(graph);
            };
            return normalize(prior) === normalize(current);
        } catch { return false; }
    }
    return false;
}

/** Freeze the kitchen destination and reason before a cancellation can reach the server. */
export function kitchenCancelIntent(saved, selected, sessionId) {
    if (!selected && !saved) return null;
    if (!Number.isSafeInteger(sessionId) || sessionId < 1) throw new Error('The kitchen session is unavailable');
    const current = selected ? { session_id: sessionId, reason_code: selected.reasonCode,
        reason_note: selected.reasonNote || '' } : null;
    if (current && (typeof current.reason_code !== 'string' || !current.reason_code ||
        typeof current.reason_note !== 'string')) throw new Error('A kitchen cancellation reason is required');
    if (saved && current && JSON.stringify(saved) !== JSON.stringify(current)) {
        throw new Error('The previous kitchen cancellation must be resolved with its original reason');
    }
    if (saved && (saved.session_id !== sessionId || typeof saved.reason_code !== 'string' || !saved.reason_code ||
        typeof saved.reason_note !== 'string')) throw new Error('The previous kitchen cancellation needs review');
    return saved || current;
}

export async function cancelDraftSnapshot({ readPending, createCancel, persistPending, sendCancel, commitAck }) {
    let pending = readPending();
    if (!pending) {
        pending = createCancel();
        if (!pending?.order_uuid || !pending.command_uuid || !Number.isSafeInteger(pending.revision) || pending.revision < 1) {
            throw new Error('Invalid draft cancellation');
        }
        await persistPending(pending);
    }
    if (!pending?.order_uuid || !pending.command_uuid || !Number.isSafeInteger(pending.revision) || pending.revision < 1) {
        throw new Error('Invalid draft cancellation');
    }
    const ack = await sendCancel(pending.order_uuid, pending.revision, pending.command_uuid);
    if (ack?.uuid !== pending.order_uuid || ack.state !== 'cancel' || ack.revision !== pending.revision + 1) {
        throw new Error('Draft cancellation acknowledgement cannot be verified');
    }
    // No removal until this callback atomically verifies and commits the ACK.
    await commitAck({ pending, revision: ack.revision });
}

/** Persist cancellation request or ACK without deleting the local order. */
export async function persistDraftCancelExperiment({ data, order, tracker, pending, acknowledgement, protect }) {
    if (!order?.uuid || order.state !== 'draft' || !order.uiState || !tracker?.get || typeof protect !== 'function' ||
        pending?.order_uuid !== order.uuid || !pending.command_uuid || !Number.isSafeInteger(pending.revision) || pending.revision < 1 ||
        !Number.isSafeInteger(pending.generation)) throw new Error('Draft cancellation persistence is unavailable');
    if (order.uiState.baseerSharedDraftPending) throw new Error('Another draft command is pending');
    const expected = JSON.stringify(pending);
    const checkPending = () => {
        const prior = order.uiState.baseerSharedDraftCancelPending;
        if (acknowledgement && JSON.stringify(prior) !== expected || prior && JSON.stringify(prior) !== expected) {
            throw new Error('Draft cancellation command changed');
        }
    };
    if (acknowledgement && (acknowledgement.uuid !== order.uuid || acknowledgement.state !== 'cancel' || acknowledgement.revision !== pending.revision + 1)) {
        throw new Error('Draft cancellation acknowledgement cannot be verified');
    }
    checkPending(); protect(order);
    const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
    for (;;) {
        let needsReview;
        const persisted = await persistDraftGraphExperiment({ data, currentGeneration: () => tracker.get(), capture: () => {
            checkPending();
            const generation = tracker.get();
            const lines = order.lines || [];
            const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((record) => [record.id, record])).values()];
            const serializedOrder = serialize(order);
            const state = serializedOrder.JSONuiState ? JSON.parse(serializedOrder.JSONuiState) : {};
            state.baseerSharedDraftGeneration = generation;
            if (acknowledgement) {
                needsReview = !cancelGraphUnchanged(order, pending, tracker);
                delete state.baseerSharedDraftCancelPending;
                state.baseerSharedDraftCancelAcknowledged = { ...pending, revision: acknowledgement.revision, needs_review: needsReview };
            } else state.baseerSharedDraftCancelPending = pending;
            serializedOrder.JSONuiState = JSON.stringify(state);
            return { generation, orderIds: [order.id, order.uuid], records: {
                'pos.order': [serializedOrder], 'pos.order.line': lines.map(serialize),
                'pos.payment': (order.payment_ids || []).map(serialize), 'product.attribute.custom.value': attrs.map(serialize),
            } };
        } });
        if (persisted.generation !== tracker.get()) continue;
        checkPending();
        order.uiState.baseerSharedDraftGeneration = persisted.generation;
        if (acknowledgement) {
            delete order.uiState.baseerSharedDraftCancelPending;
            order.uiState.baseerSharedDraftCancelAcknowledged = { ...pending, revision: acknowledgement.revision, needs_review: needsReview };
        } else order.uiState.baseerSharedDraftCancelPending = JSON.parse(expected);
        return { needsReview: Boolean(needsReview), generation: persisted.generation };
    }
}

/** Publish a server fence and the complete latest local graph in one local transaction. */
export async function persistCancelFenceRecovery({ data, order, tracker, pending, resolution, protect }) {
    if (!order?.uuid || order.state !== 'draft' || !order.uiState || !tracker?.get || typeof protect !== 'function' ||
        resolution?.outcome !== 'fenced' || resolution.uuid !== order.uuid || resolution.state !== 'draft' ||
        !Number.isSafeInteger(pending?.revision) || resolution.revision !== pending.revision + 1 ||
        pending.order_uuid !== order.uuid || !pending.command_uuid) throw new Error('Cancellation fence cannot be verified');
    const expected = JSON.stringify(pending);
    const check = () => {
        if (JSON.stringify(order.uiState.baseerSharedDraftCancelPending) !== expected ||
            order.uiState.baseerSharedDraftPending || order.state !== 'draft') {
            throw new Error('Cancellation recovery changed while saving');
        }
    };
    check(); protect(order);
    const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
    for (;;) {
        const snapshot = await persistDraftGraphExperiment({ data, currentGeneration: () => tracker.get(), capture: () => {
            check();
            const generation = tracker.get();
            const lines = order.lines || [];
            const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((record) => [record.id, record])).values()];
            const row = serialize(order);
            const state = row.JSONuiState ? JSON.parse(row.JSONuiState) : {};
            delete state.baseerSharedDraftCancelPending;
            delete state.baseerSharedDraftKitchenCancelIntent;
            delete state.baseerKitchenCancellation;
            state.baseerSharedDraftRevision = resolution.revision;
            state.baseerSharedDraftGeneration = generation;
            state.baseerSharedDraftNeedsSync = true;
            state.baseerSharedDraftHydratedOnly = false;
            state.baseerSharedDraftRecoverySync = true;
            row.JSONuiState = JSON.stringify(state);
            return { generation, orderIds: [order.id, order.uuid], records: {
                'pos.order': [row], 'pos.order.line': lines.map(serialize), 'pos.payment': (order.payment_ids || []).map(serialize),
                'product.attribute.custom.value': attrs.map(serialize),
            } };
        } });
        if (snapshot.generation !== tracker.get()) continue;
        check();
        delete order.uiState.baseerSharedDraftCancelPending;
        delete order.uiState.baseerSharedDraftKitchenCancelIntent;
        delete order.uiState.baseerKitchenCancellation;
        Object.assign(order.uiState, { baseerSharedDraftRevision: resolution.revision,
            baseerSharedDraftGeneration: snapshot.generation, baseerSharedDraftNeedsSync: true,
            baseerSharedDraftHydratedOnly: false, baseerSharedDraftRecoverySync: true });
        return snapshot;
    }
}

/**
 * Test-only native-store commit primitive. `capture` must synchronously return
 * complete serialized records and the current mutation generation. A caller
 * may publish an acknowledgement only after this returns with its candidate
 * state included in the records. Not wired to production.
 */
export async function persistDraftGraphExperiment({ data, capture, currentGeneration }) {
    const specs = [
        ['pos.order.line', 'order_id', 'uuid'],
        ['pos.payment', 'pos_order_id', 'uuid'],
    ];
    const attributesName = 'product.attribute.custom.value';
    const names = ['pos.order', ...specs.map(([name]) => name), attributesName];
    if (!data?.indexedDB?.db) throw new Error('IndexedDB unavailable');
    const run = async () => {
        for (let attempt = 0; attempt < 4; attempt++) {
            // Capture only after acquiring the same mutex as native autosave.
            const snapshot = capture();
            if (!Number.isSafeInteger(snapshot?.generation) || !Array.isArray(snapshot.orderIds) || !snapshot.orderIds.length ||
                snapshot.orderIds.some((id) => !(typeof id === 'string' && id || Number.isSafeInteger(id) && id > 0)) ||
                names.some((name) => !Array.isArray(snapshot.records?.[name])) || snapshot.records['pos.order'].length !== 1) {
                throw new Error('Invalid draft graph');
            }
            await new Promise((resolve, reject) => {
                let tx;
                try {
                    tx = data.indexedDB.db.transaction(names, 'readwrite');
                    tx.oncomplete = resolve;
                    tx.onabort = () => reject(tx.error || new Error('Draft transaction aborted'));
                    tx.onerror = () => {};
                    const owners = new Set(snapshot.orderIds);
                    for (const [name, owner, key] of specs) {
                        const store = tx.objectStore(name);
                        const retained = new Set(snapshot.records[name].map((record) => record[key]));
                        const ownedLineIds = new Set();
                        const request = store.openCursor();
                        request.onsuccess = () => {
                            const cursor = request.result;
                            if (!cursor) {
                                if (name === 'pos.order.line') {
                                    const attributes = tx.objectStore(attributesName);
                                    const retainedAttributes = new Set(snapshot.records[attributesName].map((record) => record.id));
                                    const attributesCursor = attributes.openCursor();
                                    attributesCursor.onsuccess = () => {
                                        const item = attributesCursor.result;
                                        if (!item) return;
                                        if ((ownedLineIds.has(item.value.pos_order_line_id) || owners.has(item.value.pos_order_id)) &&
                                            !retainedAttributes.has(item.value.id)) item.delete();
                                        item.continue();
                                    };
                                }
                                return;
                            }
                            if (owners.has(cursor.value[owner])) {
                                const live = data.models?.[name]?.getBy?.('uuid', cursor.value.uuid);
                                const liveOwner = name === 'pos.order.line' ? live?.order_id?.id : live?.pos_order_id?.id;
                                if (live && liveOwner && !owners.has(liveOwner)) { cursor.continue(); return; }
                                if (name === 'pos.order.line') {
                                    if (cursor.value.id !== undefined && cursor.value.id !== null) ownedLineIds.add(cursor.value.id);
                                    if (cursor.value.uuid) ownedLineIds.add(cursor.value.uuid);
                                }
                                if (!retained.has(cursor.value[key])) cursor.delete();
                            }
                            cursor.continue();
                        };
                    }
                    for (const name of names) for (const record of snapshot.records[name]) tx.objectStore(name).put(record);
                } catch (error) { if (tx) tx.abort(); reject(error); }
            });
            if (snapshot.generation === currentGeneration()) return snapshot;
            // A cashier edited during the transaction. Do not publish the ACK;
            // capture and commit the newer graph first.
        }
        throw new Error('The order kept changing while saving; keep the local order and retry.');
    };
    return data.indexedDBMutex ? data.indexedDBMutex.exec(run) : run();
}

/** Persist a frozen draft command alongside a captured native order graph. */
export async function persistPendingDraftOrderExperiment({ data, order, tracker, pending, protect }) {
    if (!order?.uuid || !['draft', 'paid'].includes(order.state) || !order.uiState || !tracker?.get || !tracker?.touch || typeof protect !== 'function') {
        throw new Error('Draft persistence is unavailable');
    }
    validateSnapshot(pending);
    if (pending.order_uuid !== order.uuid) throw new Error('Draft snapshot belongs to another order');
    const expected = JSON.stringify(pending);
    const checkPending = () => {
        const prior = order.uiState.baseerSharedDraftPending;
        if (prior && JSON.stringify(prior) !== expected) throw new Error('Another draft command is pending');
    };
    checkPending();
    protect(order);
    const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
    for (;;) {
        const persisted = await persistDraftGraphExperiment({ data, currentGeneration: () => tracker.get(), capture: () => {
            checkPending();
            const generation = tracker.get();
            const lines = order.lines || [];
            const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((record) => [record.id, record])).values()];
            const serializedOrder = serialize(order);
            const state = serializedOrder.JSONuiState ? JSON.parse(serializedOrder.JSONuiState) : {};
            state.baseerSharedDraftPending = pending;
            state.baseerSharedDraftGeneration = generation;
            serializedOrder.JSONuiState = JSON.stringify(state);
            return { generation, orderIds: [order.id, order.uuid], records: {
                'pos.order': [serializedOrder], 'pos.order.line': lines.map(serialize),
                'pos.payment': (order.payment_ids || []).map(serialize),
                'product.attribute.custom.value': attrs.map(serialize),
            } };
        } });
        // No await between the final generation check and publishing state.
        if (persisted.generation !== tracker.get()) continue;
        checkPending();
        order.uiState.baseerSharedDraftPending = JSON.parse(expected);
        order.uiState.baseerSharedDraftGeneration = persisted.generation;
        // Publishing the already-persisted transport marker is bookkeeping,
        // not a cashier edit; advancing generation here would force a loop.
        return;
    }
}

/** Commit a draft ACK with a fresh capture; no native graph loading is done. */
export async function persistDraftAckExperiment({ data, order, tracker, pending, revision, serverOrderId, lineIds, paymentIds, serverResponse, protect }) {
    if (!order?.uuid || !['draft', 'paid'].includes(order.state) || !order.uiState || !tracker?.get || typeof protect !== 'function') {
        throw new Error('Draft acknowledgement persistence is unavailable');
    }
    const expected = JSON.stringify(pending);
    const sentIntent = JSON.parse(pending.payload_json).baseer_offline_discount_intent;
    const checkPending = () => {
        if (JSON.stringify(order.uiState.baseerSharedDraftPending) !== expected) throw new Error('Draft acknowledgement is stale');
    };
    checkPending();
    protect(order);
    const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
    for (;;) {
        let plan;
        const persisted = await persistDraftGraphExperiment({ data, currentGeneration: () => tracker.get(), capture: () => {
            checkPending();
            const generation = tracker.get();
            const lines = order.lines || [];
            const preview = new Set(order.uiState.baseerOfflineDiscount?.preview_line_uuids || []);
            const source = lines.filter((line) => !line.baseer_global_discount_line && !preview.has(line.uuid));
            const payments = order.payment_ids || [];
            const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((record) => [record.id, record])).values()];
            plan = planDraftAckExperiment({ pending, revision, serverOrderId, lineIds, paymentIds, current: {
                order_uuid: order.uuid, pending_command_uuid: order.uiState.baseerSharedDraftPending.command_uuid, generation,
                line_uuids: source.map((line) => line.uuid), line_ids: source.map((line) => order.uiState.baseerSharedDraftLineIds?.[line.uuid] || line.id),
                payment_uuids: payments.map((payment) => payment.uuid), payment_ids: payments.map((payment) => order.uiState.baseerSharedDraftPaymentIds?.[payment.uuid] || payment.id),
                line_deletions: order.uiState.baseerSharedDraftLineDeletions || [],
                payment_deletions: order.uiState.baseerSharedDraftPaymentDeletions || [],
            } });
            const serializedOrder = serialize(order);
            const state = serializedOrder.JSONuiState ? JSON.parse(serializedOrder.JSONuiState) : {};
            delete state.baseerSharedDraftPending;
            if (state.baseerOfflineDiscount) {
                const sentLines = new Set(pending.sent_legacy_line_deletion_ids || []);
                const sentPayments = new Set(pending.sent_legacy_payment_deletion_ids || []);
                state.baseerOfflineDiscount.removed_line_ids = (state.baseerOfflineDiscount.removed_line_ids || []).filter((id) => !sentLines.has(id));
                state.baseerOfflineDiscount.removed_payment_ids = (state.baseerOfflineDiscount.removed_payment_ids || []).filter((id) => !sentPayments.has(id));
            }
            state.baseerSharedDraftRevision = revision;
            state.baseerSharedDraftGeneration = generation;
            state.baseerSharedDraftNeedsSync = plan.needs_sync;
            if (!plan.needs_sync) delete state.baseerSharedDraftRecoverySync;
            if (pending.target_state === 'draft') state.baseerSharedDraftHydratedOnly = !plan.needs_sync;
            state.baseerSharedDraftLineDeletions = plan.line_deletions;
            state.baseerSharedDraftPaymentDeletions = plan.payment_deletions;
            state.baseerSharedDraftServerOrderId = plan.server_order_id;
            state.baseerSharedDraftLineIds = plan.line_ids_by_uuid;
            state.baseerSharedDraftPaymentIds = plan.payment_ids_by_uuid;
            state.baseerSharedDraftKind = sentIntent?.kind || false;
            state.baseerSharedDraftValue = sentIntent?.value || false;
            if (pending.target_state === 'paid') {
                if (!serverResponse) throw new Error('Paid server response is unavailable');
                state.baseerSharedDraftPaidAckPending = true;
                state.baseerSharedDraftPaidServerResponse = serverResponse;
                state.baseerSharedDraftPaidCommand = pending;
            }
            serializedOrder.JSONuiState = JSON.stringify(state);
            return { generation, orderIds: [order.id, order.uuid], records: {
                'pos.order': [serializedOrder], 'pos.order.line': lines.map(serialize),
                'pos.payment': payments.map(serialize), 'product.attribute.custom.value': attrs.map(serialize),
            } };
        } });
        if (persisted.generation !== tracker.get()) continue;
        checkPending();
        delete order.uiState.baseerSharedDraftPending;
        if (order.uiState.baseerOfflineDiscount) {
            const sentLines = new Set(pending.sent_legacy_line_deletion_ids || []);
            const sentPayments = new Set(pending.sent_legacy_payment_deletion_ids || []);
            order.uiState.baseerOfflineDiscount.removed_line_ids = (order.uiState.baseerOfflineDiscount.removed_line_ids || []).filter((id) => !sentLines.has(id));
            order.uiState.baseerOfflineDiscount.removed_payment_ids = (order.uiState.baseerOfflineDiscount.removed_payment_ids || []).filter((id) => !sentPayments.has(id));
        }
        Object.assign(order.uiState, {
            baseerSharedDraftRevision: revision, baseerSharedDraftGeneration: persisted.generation,
            baseerSharedDraftNeedsSync: plan.needs_sync, baseerSharedDraftLineDeletions: plan.line_deletions,
            baseerSharedDraftPaymentDeletions: plan.payment_deletions,
            baseerSharedDraftServerOrderId: plan.server_order_id, baseerSharedDraftLineIds: plan.line_ids_by_uuid,
            baseerSharedDraftPaymentIds: plan.payment_ids_by_uuid,
            baseerSharedDraftKind: sentIntent?.kind || false, baseerSharedDraftValue: sentIntent?.value || false,
            ...(pending.target_state === 'draft' ? { baseerSharedDraftHydratedOnly: !plan.needs_sync } : {}),
            ...(pending.target_state === 'paid' ? { baseerSharedDraftPaidAckPending: true, baseerSharedDraftPaidServerResponse: serverResponse,
                baseerSharedDraftPaidCommand: pending } : {}),
        });
        if (!plan.needs_sync) delete order.uiState.baseerSharedDraftRecoverySync;
        return plan;
    }
}

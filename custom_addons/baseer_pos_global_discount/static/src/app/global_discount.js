import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useAutofocus } from "@web/core/utils/hooks";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { PosPayment } from "@point_of_sale/app/models/pos_payment";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { discountStorageKey, pendingDiscount, needsDiscountRefund, executeDiscountIntent, submitDiscount } from "./discount_flow";
import { calculateOfflineDiscount, refreshOfflineDiscount, wireOfflineDiscount } from "./offline_preview";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { attachDraftGenerationExperiment, cancelDraftSnapshot, cancelGraphFingerprint, cancelGraphUnchanged, createDraftSyncAdapterExperiment, hydrateSharedDraftExperiment, kitchenCancelIntent, persistCancelFenceRecovery, persistDraftCancelExperiment, persistDraftGraphExperiment, runDraftSnapshotExperiment, runPaidAfterDraftExperiment, singleFlightDraftExperiment, stageNativeServerGraphExperiment, stagePaidServerGraphExperiment, validatePaidAckGraphExperiment, verifyPaidInvoiceExperiment } from "./draft_snapshot_experiment";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { ConnectionLostError, RPCError, rpc } from "@web/core/network/rpc";
import { PosData } from "@point_of_sale/app/services/data_service";
import DevicesSynchronisation from "@point_of_sale/app/utils/devices_synchronisation";
import IndexedDB from "@point_of_sale/app/models/utils/indexed_db";
import { persistNativeOfflinePaidOrder } from "./offline_persistence";

const frozenMessage = () => _t("Remove the invoice discount before changing items, prices or customer details.");
const pendingMessage = () => _t("The discount needs verification. Reconnect and check its result before payment.");
// Keep disabled until shared-draft payment, cancellation and printing have
// passed the full POS acceptance suite. Never enable only part of the contract.
const SHARED_DRAFT_FLOW_ENABLED = true;
const paidReconciliationOrders = new WeakSet();
const sharedRemoteDeleteOrders = new WeakSet();
const restoredSharedDrafts = new WeakSet();
const sharedRevisionChecks = new WeakMap();
const sharedRevisionPromises = new WeakMap();
const sharedRevisionWarningOwners = new WeakMap();
const sharedRefreshOrders = new WeakSet();
const sharedStageOrders = new WeakSet();
function isDiscountFrozen(order) {
    return Boolean(order && (paidReconciliationOrders.has(order) || sharedRemoteDeleteOrders.has(order) || SHARED_DRAFT_FLOW_ENABLED && (order.uiState?.baseerSharedDraftCancelPending || order.uiState?.baseerSharedDraftCancelAcknowledged) || order.baseer_global_discount_locked || (order.config_id && localStorage.getItem(
        discountStorageKey(session.db || "", order.config_id.id, order.uuid)
    ))));
}
function explainFrozen(pos) {
    pos.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: frozenMessage() });
}

function isPendingOfflineDiscount(order) {
    if (SHARED_DRAFT_FLOW_ENABLED && order?.uiState?.baseerSharedDraftPaidAckPending && ['paid', 'done', 'invoiced'].includes(order.state)) return true;
    return Boolean(['draft', 'paid'].includes(order?.state) && !order.baseer_global_discount_locked &&
        (order.uiState?.baseerOfflineDiscount || SHARED_DRAFT_FLOW_ENABLED &&
            (order.uiState?.baseerSharedDraftPending || order.uiState?.baseerSharedDraftRevision || order.baseer_offline_draft_revision)));
}

function isManagedSharedDraft(order) {
    if (SHARED_DRAFT_FLOW_ENABLED && order?.uiState?.baseerSharedDraftPaidAckPending && ['paid', 'done', 'invoiced'].includes(order.state)) return true;
    return Boolean(order && ['draft', 'paid'].includes(order.state) && !order.baseer_global_discount_locked &&
        (order.uiState?.baseerOfflineDiscount || order.uiState?.baseerSharedDraftPending ||
         order.uiState?.baseerSharedDraftRevision || order.baseer_offline_draft_revision));
}

function isCleanHydratedSharedDraft(order) {
    const tracker = order?.models?._baseerDraftGenerationTracker;
    const acknowledgedClean = Number.isSafeInteger(order?.uiState?.baseerSharedDraftServerOrderId) && tracker &&
        Number.isSafeInteger(order.uiState?.baseerSharedDraftGeneration) && tracker.get() === order.uiState.baseerSharedDraftGeneration &&
        !order.uiState.baseerSharedDraftNeedsSync;
    return Boolean(SHARED_DRAFT_FLOW_ENABLED && order?.state === 'draft' &&
        (Number.isSafeInteger(order.id) || Number.isSafeInteger(order.uiState?.baseerSharedDraftServerOrderId)) &&
        (order.uiState?.baseerSharedDraftHydratedOnly || acknowledgedClean) && !order.uiState?.baseerSharedDraftPending &&
        !order.uiState?.baseerSharedDraftCancelPending && !order.uiState?.baseerSharedDraftHydrationError &&
        !order.uiState?.baseerSharedDraftRefreshError);
}

function protectedOfflineRecords(models) {
    const orders = models["pos.order"].getAll().filter(isPendingOfflineDiscount);
    const idSet = (records) => new Set(records.map((record) => record.id).filter((id) => typeof id === "number"));
    const lines = orders.flatMap((order) => order.lines || []);
    const payments = orders.flatMap((order) => order.payment_ids || []);
    const orderIds = idSet(orders), lineIds = idSet(lines), paymentIds = idSet(payments);
    for (const order of orders) {
        if (Number.isSafeInteger(order.uiState?.baseerSharedDraftServerOrderId)) orderIds.add(order.uiState.baseerSharedDraftServerOrderId);
        for (const id of Object.values(order.uiState?.baseerSharedDraftLineIds || {})) if (Number.isSafeInteger(id)) lineIds.add(id);
        for (const id of Object.values(order.uiState?.baseerSharedDraftPaymentIds || {})) if (Number.isSafeInteger(id)) paymentIds.add(id);
    }
    return {
        orders: orderIds,
        orderUuids: new Set(orders.map((order) => order.uuid)),
        lines: lineIds, lineUuids: new Set(lines.map((line) => line.uuid).filter((uuid) => typeof uuid === 'string' && uuid)),
        payments: paymentIds, paymentUuids: new Set(payments.map((payment) => payment.uuid).filter((uuid) => typeof uuid === 'string' && uuid)),
        attributes: idSet(lines.flatMap((line) => line.custom_attribute_value_ids || [])),
    };
}

function relationId(value) {
    return Array.isArray(value) ? value[0] : typeof value === "object" && value ? value.id : value;
}

function cancelRequiresSyncReview(order, pending, tracker) {
    return Boolean(order.uiState?.baseerSharedDraftNeedsSync && !(pending &&
        order.uiState.baseerSharedDraftRemoteDeleted === true && order.uiState.baseerSharedDraftKitchenCancelIntent &&
        cancelGraphUnchanged(order, pending, tracker)));
}

// A preview line is not a kitchen item. Odoo can recompute its visual
// hasChange flag while saving; retain the actual flag in IndexedDB while
// excluding only this derived flag from the in-flight comparison.
function refreshGraphFingerprint(order) {
    const graph = JSON.parse(cancelGraphFingerprint(order));
    if (!graph?.header?.JSONuiState || !Array.isArray(graph.lines)) throw new Error('Incomplete order graph');
    const preview = graph.header.JSONuiState.baseerOfflineDiscount?.preview_line_uuids || [];
    if (!Array.isArray(preview) || new Set(preview).size !== preview.length) throw new Error('Invalid discount preview');
    for (const uuid of preview) {
        const matches = graph.lines.filter((line) => line.uuid === uuid);
        if (matches.length !== 1 || typeof matches[0].JSONuiState !== 'string') throw new Error('Incomplete discount preview');
        const state = JSON.parse(matches[0].JSONuiState);
        if (!state || typeof state !== 'object' || Array.isArray(state) || typeof state.hasChange !== 'boolean') throw new Error('Invalid preview state');
        delete state.hasChange;
        matches[0].JSONuiState = JSON.stringify(state);
    }
    graph.lines.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    return JSON.stringify(graph);
}

function matchesExpectedSharedDraft(row, expected) {
    return Boolean(row && expected && Number.isSafeInteger(expected.serverId) && expected.serverId > 0 &&
        Number.isSafeInteger(expected.revision) && expected.revision > 0 && typeof expected.uuid === 'string' && expected.uuid &&
        ['sessionId', 'configId', 'companyId'].every((key) => Number.isSafeInteger(expected[key]) && expected[key] > 0) &&
        row.id === expected.serverId && row.uuid === expected.uuid && row.state === 'draft' &&
        row.baseer_offline_draft_revision === expected.revision && relationId(row.session_id) === expected.sessionId &&
        relationId(row.config_id) === expected.configId && relationId(row.company_id) === expected.companyId);
}

function matchesExpectedSharedDraftLines(data, server, expected) {
    if (!Array.isArray(expected?.lines) || !expected.lines.length || !Array.isArray(server?.lines) ||
        !Array.isArray(data?.['pos.order.line'])) return false;
    const expectedIds = new Set(), expectedUuids = new Set();
    for (const line of expected.lines) {
        if (!Number.isSafeInteger(line?.id) || line.id < 1 || typeof line.uuid !== 'string' || !line.uuid ||
            !Number.isSafeInteger(line.productId) || line.productId < 1 ||
            ![line.qty, line.priceUnit, line.discount].every((value) => typeof value === 'number' && Number.isFinite(value)) ||
            !Array.isArray(line.taxIds) || line.taxIds.some((id) => !Number.isSafeInteger(id) || id < 1) ||
            new Set(line.taxIds).size !== line.taxIds.length ||
            expectedIds.has(line.id) || expectedUuids.has(line.uuid)) return false;
        expectedIds.add(line.id); expectedUuids.add(line.uuid);
    }
    const orderIds = server.lines.map(relationId);
    if (orderIds.some((id) => !Number.isSafeInteger(id) || id < 1) || new Set(orderIds).size !== orderIds.length) return false;
    const orderIdSet = new Set(orderIds), rows = data['pos.order.line'].filter((row) => orderIdSet.has(row.id));
    if (rows.length !== orderIds.length || new Set(rows.map((row) => row.id)).size !== orderIds.length) return false;
    if (rows.some((row) => relationId(row.order_id) !== expected.serverId || typeof row.baseer_global_discount_line !== 'boolean')) return false;
    const sourceRows = rows.filter((row) => !row.baseer_global_discount_line);
    if (sourceRows.length !== expected.lines.length) return false;
    return expected.lines.every((line) => {
        const row = sourceRows.find((candidate) => candidate.id === line.id);
        return Boolean(row && row.uuid === line.uuid && relationId(row.product_id) === line.productId &&
            row.qty === line.qty && row.price_unit === line.priceUnit && row.discount === line.discount &&
            Array.isArray(row.tax_ids) && row.tax_ids.every((id) => Number.isSafeInteger(id) && id > 0) &&
            new Set(row.tax_ids).size === row.tax_ids.length && row.tax_ids.length === line.taxIds.length &&
            row.tax_ids.every((id) => line.taxIds.includes(id)));
    });
}

function touchExperimentalDraftGraph(order) {
    order?.models?._baseerDraftGenerationTracker?.touch();
}

function clearProvisionalWarning(order) {
    if (order.uiState?.baseerSharedDraftRevisionWarningProvisional === true) {
        delete order.uiState.baseerSharedDraftRevisionWarningProvisional;
        // uiState writes alone do not emit related-model events. An ACK
        // transaction in flight must recapture this conflict before it commits.
        touchExperimentalDraftGraph(order);
    }
}

function markProvisionalWarningConflicted(order) {
    sharedRevisionWarningOwners.delete(order);
    clearProvisionalWarning(order);
}

function noteSharedDraftEdit(order) {
    if (SHARED_DRAFT_FLOW_ENABLED && order?.uiState?.baseerSharedDraftHydratedOnly) {
        order.uiState.baseerSharedDraftHydratedOnly = false;
        touchExperimentalDraftGraph(order);
    }
}

function markPosDisconnected(data) {
    data.network.offline = true;
    if (typeof navigator !== 'undefined' && navigator.onLine && !data.checkConnectivityTimeout) {
        data.checkConnectivityTimeout = setTimeout(() => data.checkConnectivity(), 2000);
    }
}

// A draft acknowledgement stores server IDs without replacing local model
// identities. Native autosave can subsequently persist a child with numeric
// parent/child IDs while the order still references UUIDs. Reconnect only
// relationships proven by the acknowledged mapping, without changing storage.
function reconnectAcknowledgedDraftRows(data) {
    if (!data || !Array.isArray(data['pos.order']) || !Array.isArray(data['pos.order.line'])) return data;
    const linesByUuid = new Map(data['pos.order.line'].filter((line) => line.uuid).map((line) => [line.uuid, line]));
    const paymentsByUuid = new Map((data['pos.payment'] || []).filter((payment) => payment.uuid).map((payment) => [payment.uuid, payment]));
    const claimed = new Set();
    const replacements = new Map();
    const paymentReplacements = new Map();
    const serverOwners = new Map();
    const orders = data['pos.order'].map((order) => {
        let state;
        try { state = JSON.parse(order.JSONuiState || '{}'); } catch { return order; }
        const serverId = state.baseerSharedDraftServerOrderId;
        const lineIds = state.baseerSharedDraftLineIds;
        if (!Number.isSafeInteger(serverId) || order.id === serverId) return order;
        if (serverOwners.has(serverId) && serverOwners.get(serverId) !== order.uuid) throw new Error('Conflicting local draft ownership');
        serverOwners.set(serverId, order.uuid);
        const connect = (keys, rows, ids, owner, updates, type) => (keys || []).map((key) => {
            const child = rows.get(key);
            if (!child || !Number.isSafeInteger(child.id) || child.id !== ids?.[child.uuid] || child[owner] !== serverId) return key;
            const claim = `${type}:${child.uuid}`;
            if (claimed.has(claim)) throw new Error('Conflicting local draft child ownership');
            claimed.add(claim);
            updates.set(child.uuid, { ...child, [owner]: order.id });
            return child.id;
        });
        return { ...order,
            ...(Array.isArray(order.lines) ? { lines: connect(order.lines, linesByUuid, lineIds, 'order_id', replacements, 'line') } : {}),
            ...(Array.isArray(order.payment_ids) ? { payment_ids: connect(order.payment_ids, paymentsByUuid, state.baseerSharedDraftPaymentIds, 'pos_order_id', paymentReplacements, 'payment') } : {}),
        };
    });
    return { ...data, 'pos.order': orders, 'pos.order.line': data['pos.order.line'].map((line) => replacements.get(line.uuid) || line),
        ...(Array.isArray(data['pos.payment']) ? { 'pos.payment': data['pos.payment'].map((payment) => paymentReplacements.get(payment.uuid) || payment) } : {}) };
}

// missingRecursive may append a server copy of a locally edited record with
// the same UUID. Loading both replaces the local identity and disconnects the
// child; retain the complete local rows for protected draft graphs.
function preferLocalDraftRows(resolved, local) {
    if (!resolved || !local) return resolved;
    const protectedOrders = (local['pos.order'] || []).filter((row) => {
        if (!['draft', 'paid'].includes(row.state)) return false;
        let state;
        try { state = JSON.parse(row.JSONuiState || '{}'); }
        catch { throw new Error(_t('The local point-of-sale data cannot be verified. Ask a manager before clearing it.')); }
        return Boolean(state.baseerOfflineDiscount || state.baseerSharedDraftPending || state.baseerSharedDraftPaidAckPending);
    });
    const output = { ...resolved };
    for (const [name, ids] of [['pos.order', new Set(protectedOrders.map((row) => row.uuid))],
        ['pos.order.line', new Set(protectedOrders.flatMap((row) => row.lines || []))],
        ['pos.payment', new Set(protectedOrders.flatMap((row) => row.payment_ids || []))]]) {
        const localRows = (local[name] || []).filter((row) => row.uuid && (ids.has(row.uuid) || ids.has(row.id)));
        const preferred = new Map(localRows.map((row) => [row.uuid, row]));
        if (preferred.size !== localRows.length) throw new Error('Conflicting local draft identities');
        const seen = new Set();
        output[name] = (resolved[name] || []).flatMap((row) => {
            if (!preferred.has(row.uuid)) return [row];
            if (seen.has(row.uuid)) return [];
            seen.add(row.uuid);
            return [preferred.get(row.uuid)];
        });
    }
    return output;
}

function verifyStoredPaidDiscountGraph(local) {
    const lines = new Set((local['pos.order.line'] || []).map((row) => row.uuid));
    const payments = new Set((local['pos.payment'] || []).map((row) => row.uuid));
    for (const order of local['pos.order'] || []) {
        if (!['draft', 'paid'].includes(order.state)) continue;
        let state;
        try { state = JSON.parse(order.JSONuiState || '{}'); }
        catch { throw new Error(_t('The local point-of-sale data cannot be verified. Ask a manager before clearing it.')); }
        if (order.state !== 'paid') continue;
        const command = state.baseerSharedDraftPaidCommand || state.baseerSharedDraftPending;
        if (!command || command.target_state !== 'paid') continue;
        if ((command.source_line_uuids || []).some((uuid) => !lines.has(uuid)) ||
            (command.source_payment_uuids || []).some((uuid) => !payments.has(uuid))) {
            throw new Error(_t('The local order is incomplete on this device. Ask a manager to restore it before continuing.'));
        }
    }
}

function pendingDeletedIds(order, field) {
    const commands = order.models?.commands?.["pos.order"];
    return ["delete", "unlink"].flatMap((kind) => commands?.[kind]?.get(field) || [])
        .filter((item) => item.parentId === order.id && typeof item.id === "number")
        .map((item) => item.id);
}

// Older POS caches can lack the newly loaded config field. Refresh only that
// field, without resetting the cache or rewriting any order/payment record.
async function refreshMissingAccountProofs(pos) {
    const config = pos.config;
    const current = config?.baseer_offline_discount_account_proofs;
    if (!config?.baseer_global_discount_enabled || (current && Object.keys(current).length) || pos.data.network.offline) return;
    const rows = await pos.data.orm.read("pos.config", [config.id], ["baseer_offline_discount_account_proofs"]);
    const proofs = rows?.[0]?.baseer_offline_discount_account_proofs;
    if (rows?.length !== 1 || rows[0].id !== config.id || !proofs || typeof proofs !== "object" || Array.isArray(proofs) ||
        !Object.keys(proofs).length || !Object.entries(proofs).every(([key, value]) => /^\d+$/.test(key) && /^[0-9a-f]{64}$/.test(value))) return;
    const db = pos.data.indexedDB?.db;
    if (!db) throw new Error("POS cache unavailable");
    await new Promise((resolve, reject) => {
        let tx;
        try {
            tx = db.transaction(["pos.config"], "readwrite");
            const request = tx.objectStore("pos.config").openCursor();
            let found = false;
            request.onsuccess = () => {
                const cursor = request.result;
                if (!cursor) { if (!found) tx.abort(); return; }
                if (cursor.value.id === config.id) {
                    found = true;
                    cursor.update({ ...cursor.value, baseer_offline_discount_account_proofs: proofs });
                } else cursor.continue();
            };
            tx.oncomplete = resolve;
            tx.onabort = () => reject(tx.error || new Error("POS config cache update aborted"));
            tx.onerror = () => {};
        } catch (error) { reject(error); }
    });
    config.update({ baseer_offline_discount_account_proofs: proofs });
}

function protectOfflineStorage(indexedDB, order) {
    indexedDB._baseerOfflineProtection ||= new Map();
    indexedDB._baseerOfflineProtection.set(order.uuid, {
        "pos.order": new Set([order.uuid]),
        "pos.order.line": new Set((order.lines || []).map((line) => line.uuid)),
        "pos.payment": new Set((order.payment_ids || []).map((payment) => payment.uuid)),
        "product.attribute.custom.value": new Set((order.lines || []).flatMap((line) => (line.custom_attribute_value_ids || []).map((value) => value.id))),
    });
}

// Native cleanup runs after a detached read; it may have captured an earlier
// draft snapshot. Never let that stale cleanup erase an unacknowledged payment.
patch(IndexedDB.prototype, {
    delete(storeName, keys) {
        if (!this._baseerOfflineProtection?.size || !keys?.length) return super.delete(...arguments);
        const protectedKeys = new Set();
        for (const stores of this._baseerOfflineProtection.values()) {
            for (const key of stores[storeName] || []) protectedKeys.add(key);
        }
        return super.delete(storeName, keys.filter((key) => !protectedKeys.has(key)));
    },
});

// A numeric ID may refer only to an earlier server draft, not confirmation of
// this locally paid state. Do not overwrite it while recovering native POS.
patch(PosData.prototype, {
    async loadServerOrders(domain) {
        if (!SHARED_DRAFT_FLOW_ENABLED || !this.deviceSync?.pos) return super.loadServerOrders(...arguments);
        const raw = await this.execute({ type: 'call', model: 'pos.order', method: 'read_pos_orders', args: [domain], queue: false });
        const expanded = await this.missingRecursive(raw);
        const prepareNativeOrders = (orders) => {
            const config = this.models['pos.config'].get(odoo.pos_config_id), sessionRecord = this.models['pos.session'].get(odoo.pos_session_id);
            for (const order of orders) { order.serializeForORM(); order.config_id = config; order.session_id = sessionRecord; }
            return orders;
        };
        const existing = this.models['pos.order'].getAll().filter(isPendingOfflineDiscount);
        const matched = new Map();
        for (const row of expanded?.['pos.order'] || []) {
            const local = existing.find((order) => order.uuid === row.uuid ||
                Number.isSafeInteger(row.id) && (order.id === row.id || order.uiState?.baseerSharedDraftServerOrderId === row.id));
            if (local) matched.set(row.id, local);
        }
        if (!matched.size) {
            this.deviceSync.dispatch?.(expanded);
            const connected = this.models.connectNewData(expanded);
            this.synchronizeServerDataInIndexedDB(expanded);
            return prepareNativeOrders(connected['pos.order'] || []);
        }
        const localOrders = [...new Set(matched.values())];
        for (const order of localOrders) {
            const server = (expanded['pos.order'] || []).find((row) => matched.get(row.id) === order);
            const localRevision = order.uiState?.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision ?? 0;
            if (!server || server.uuid !== order.uuid || !Number.isSafeInteger(server.baseer_offline_draft_revision) ||
                !Number.isSafeInteger(localRevision) || server.baseer_offline_draft_revision < localRevision) {
                order.uiState.baseerSharedDraftRefreshError = _t('The shared order could not be refreshed. Keep its local copy for review.');
                continue;
            }
            if (isCleanHydratedSharedDraft(order)) {
                try { await this.deviceSync.pos.baseerRefreshCleanSharedDraftExperiment(order); }
                catch { order.uiState.baseerSharedDraftRefreshError ||= _t('The shared order could not be refreshed. Keep its local copy for review.'); }
            } else if (server && Number.isSafeInteger(server.baseer_offline_draft_revision) &&
                server.baseer_offline_draft_revision > localRevision) {
                markProvisionalWarningConflicted(order);
                order.uiState.baseerSharedDraftRefreshError = _t('The shared order changed on another device. Keep your local changes for review.');
            }
        }
        const protectedLines = new Set(), safe = { ...expanded };
        if (expanded['pos.order']) safe['pos.order'] = expanded['pos.order'].filter((row) => !matched.has(row.id));
        if (expanded['pos.order.line']) safe['pos.order.line'] = expanded['pos.order.line'].filter((row) => {
            if (!matched.has(relationId(row.order_id))) return true;
            protectedLines.add(row.id); return false;
        });
        if (expanded['pos.payment']) safe['pos.payment'] = expanded['pos.payment'].filter((row) => !matched.has(relationId(row.pos_order_id)));
        if (expanded['product.attribute.custom.value']) safe['product.attribute.custom.value'] = expanded['product.attribute.custom.value'].filter((row) => !protectedLines.has(relationId(row.pos_order_line_id)));
        this.deviceSync.dispatch?.(safe);
        const connected = this.models.connectNewData(safe);
        this.synchronizeServerDataInIndexedDB(safe);
        return [...localOrders, ...prepareNativeOrders(connected['pos.order'] || [])];
    },
    async loadInitialData() {
        if (!this.network.offline) {
            try { await rpc('/pos/ping'); }
            catch (error) {
                if (!(error instanceof ConnectionLostError)) throw error;
                markPosDisconnected(this);
            }
        }
        let cached;
        if (!this.network.offline) {
            // Native loadInitialData catches its own RPC errors. Observe only
            // connection loss on its two reads so a loss after ping still sets
            // offline before local-order verification runs.
            const originalOrm = this.orm;
            if (!originalOrm) return super.loadInitialData(...arguments);
            const data = this;
            this.orm = new Proxy(originalOrm, {
                get(target, field) {
                    if (field === 'call') return async (...args) => {
                        try { return await target.call(...args); }
                        catch (error) {
                            if (args[0] === 'pos.session' && ['load_data', 'filter_local_data'].includes(args[1]) && error instanceof ConnectionLostError) markPosDisconnected(data);
                            throw error;
                        }
                    };
                    const value = Reflect.get(target, field, target);
                    return typeof value === 'function' ? value.bind(target) : value;
                },
            });
            try { cached = await super.loadInitialData(...arguments); }
            finally { this.orm = originalOrm; }
            if (!this.network.offline) return cached;
        } else {
            cached = await this.getCachedServerDataFromIndexedDB();
        }
        const config = cached?.['pos.config']?.find((record) => record.id === odoo.pos_config_id);
        const session = cached?.['pos.session']?.find((record) => record.id === odoo.pos_session_id);
        if (!config || !session || session.state !== 'opened' || relationId(session.config_id) !== config.id) {
            throw new Error(_t('The local point-of-sale data cannot be verified. Ask a manager before clearing it.'));
        }
        return cached;
    },
    async getLocalDataFromIndexedDB(data = false) {
        this._baseerRestoringLocalData = true;
        try {
            if (SHARED_DRAFT_FLOW_ENABLED && this.indexedDB?.readAll && !data) data = await this.indexedDB.readAll(Object.keys(this.opts.databaseTable));
            const result = await super.getLocalDataFromIndexedDB(SHARED_DRAFT_FLOW_ENABLED ? reconnectAcknowledgedDraftRows(data) : data);
            for (const order of result?.["pos.order"] || []) {
                if (SHARED_DRAFT_FLOW_ENABLED && ['draft', 'paid'].includes(order.state) && order.uiState?.baseerOfflineDiscount) {
                    const preview = new Set(order.uiState.baseerOfflineDiscount.preview_line_uuids || []);
                    const error = _t('A product line could not be restored. Keep this order and ask a manager to review it.');
                    const source = (order.lines || []).filter((line) => !preview.has(line.uuid) && !line.baseer_global_discount_line);
                    const sourceUuids = new Set(source.map((line) => line.uuid));
                    const deleted = new Set([...(order.uiState.baseerOfflineDiscount.removed_line_ids || []),
                        ...(order.uiState.baseerSharedDraftLineDeletions || []).map((item) => item.id)]);
                    const missing = Object.entries(order.uiState.baseerSharedDraftLineIds || {}).some(([uuid, id]) => !sourceUuids.has(uuid) && !deleted.has(id));
                    const paymentUuids = new Set((order.payment_ids || []).map((payment) => payment.uuid));
                    const command = order.uiState.baseerSharedDraftPaidCommand || order.uiState.baseerSharedDraftPending;
                    const missingPayment = order.state === 'paid' && (command?.source_payment_uuids || []).some((uuid) => !paymentUuids.has(uuid));
                    const paymentError = _t('A payment line could not be restored. Keep this order and ask a manager to review it.');
                    if (missingPayment) {
                        order.uiState.baseerSharedDraftHydrationError = paymentError;
                    } else if (!source.length || missing) {
                        order.uiState.baseerSharedDraftHydrationError = error;
                    } else if ([error, paymentError].includes(order.uiState.baseerSharedDraftHydrationError)) {
                        delete order.uiState.baseerSharedDraftHydrationError;
                    }
                }
                if (SHARED_DRAFT_FLOW_ENABLED && order.state === 'draft' && (Number.isSafeInteger(order.id) || Number.isSafeInteger(order.uiState?.baseerSharedDraftServerOrderId)) && isManagedSharedDraft(order)) restoredSharedDrafts.add(order);
                if (SHARED_DRAFT_FLOW_ENABLED && order.uiState?.baseerSharedDraftCancelAcknowledged && !order.uiState.baseerSharedDraftCancelAcknowledged.needs_review) {
                    this.indexedDB?._baseerOfflineProtection?.delete(order.uuid);
                    this.localDeleteCascade(order);
                    continue;
                }
                // A remote deletion marker is evidence for review, not proof
                // that no local edit raced the IndexedDB transaction.
                if (isPendingOfflineDiscount(order)) {
                    protectOfflineStorage(this.indexedDB, order);
                    // A restored numeric ID describes a prior draft, not an
                    // acknowledged payment. Native sync skips clean records.
                    order._markDirty();
                    for (const line of order.lines || []) line._markDirty();
                    for (const payment of order.payment_ids || []) payment._markDirty();
                }
            }
            return result;
        } finally { this._baseerRestoringLocalData = false; }
    },
    async missingRecursive(recordMap, idsMap = {}, acc = {}) {
        if (SHARED_DRAFT_FLOW_ENABLED && this._baseerRestoringLocalData && Object.keys(idsMap).length === 0) verifyStoredPaidDiscountGraph(recordMap);
        if (this._baseerRestoringLocalData && this.network.offline) {
            const pending = (recordMap["pos.order"] || []).filter((order) => {
                if (order.state !== "paid" || order.baseer_global_discount_locked || !order.JSONuiState) return false;
                try { return Boolean(JSON.parse(order.JSONuiState).baseerOfflineDiscount); }
                catch { throw new Error(_t("The local point-of-sale data cannot be verified. Ask a manager before clearing it.")); }
            });
            {
                const orders = recordMap['pos.order'] || [];
                const lines = recordMap["pos.order.line"] || [];
                const payments = recordMap["pos.payment"] || [];
                const lineIds = new Set(lines.map((line) => line.id));
                const paymentIds = new Set(payments.map((payment) => payment.id));
                const products = new Set(this.models["product.product"].getAll().map((product) => product.id));
                for (const product of recordMap["product.product"] || []) products.add(product.id);
                for (const order of orders) {
                    if ((order.lines || []).some((id) => !lineIds.has(id)) ||
                        (order.payment_ids || []).some((id) => !paymentIds.has(id)) ||
                        lines.some((line) => (order.lines || []).includes(line.id) && !products.has(relationId(line.product_id)))) {
                        throw new Error(_t("The local order is incomplete on this device. Ask a manager to restore it before continuing."));
                    }
                }
                const merged = { ...acc };
                for (const [model, records] of Object.entries(recordMap)) merged[model] = [...(merged[model] || []), ...records];
                return merged;
            }
        }
        const restoringTopLevel = SHARED_DRAFT_FLOW_ENABLED && this._baseerRestoringLocalData && Object.keys(idsMap).length === 0;
        let result = await super.missingRecursive(...arguments);
        if (restoringTopLevel) result = preferLocalDraftRows(result, recordMap);
        return result;
    },
    async resetIndexedDB() {
        // Native startup resets the cache when configuration changes. Inspect
        // its persisted paid orders first, before the reset can erase payments.
        const db = this.indexedDB?.db;
        if (!db) throw new Error(_t("The local point-of-sale data cannot be verified. Ask a manager before clearing it."));
        const savedOrders = await new Promise((resolve, reject) => {
            let transaction;
            try {
                transaction = db.transaction(["pos.order"], "readonly");
                const request = transaction.objectStore("pos.order").getAll();
                let values;
                request.onsuccess = () => { values = request.result; };
                request.onerror = () => reject(request.error || new Error("IndexedDB read failed"));
                transaction.oncomplete = () => resolve(values || []);
                transaction.onabort = () => reject(transaction.error || new Error("IndexedDB read aborted"));
                transaction.onerror = () => {};
            } catch (error) { reject(error); }
        });
        for (const saved of savedOrders) {
            // Numeric IDs may still have local edits. IndexedDB does not retain
            // enough dirty/relationship-command information to prove otherwise.
            if (saved.state === 'draft') {
                throw new Error(_t('A locally saved draft is waiting. Synchronize or remove it before refreshing point-of-sale data.'));
            }
            if (saved.state !== "paid" || saved.baseer_global_discount_locked || !saved.JSONuiState) continue;
            let state;
            try { state = JSON.parse(saved.JSONuiState); }
            catch { throw new Error(_t("The local point-of-sale data cannot be verified. Ask a manager before clearing it.")); }
            if (state.baseerOfflineDiscount) {
                throw new Error(_t("A paid offline order is waiting to synchronize. Reconnect or ask a manager before refreshing point-of-sale data."));
            }
        }
        return super.resetIndexedDB(...arguments);
    },
    async checkAndDeleteMissingOrders(results) {
        if (this.network?.offline) return;
        if (!results?.["pos.order"]) return super.checkAndDeleteMissingOrders(...arguments);
        const safe = { ...results, "pos.order": results["pos.order"].filter((order) => !isPendingOfflineDiscount(order)) };
        try { return await super.checkAndDeleteMissingOrders(safe); }
        catch (error) {
            if (!(error instanceof ConnectionLostError)) throw error;
            // The browser can be online while Odoo is unreachable. No server
            // response means no evidence that a locally saved order vanished.
            markPosDisconnected(this);
        }
    },
});

patch(DevicesSynchronisation.prototype, {
    async processDynamicRecords(records) {
        if (SHARED_DRAFT_FLOW_ENABLED && this.pos?.baseerRefreshCleanSharedDraftExperiment) {
            const affected = new Set((records['pos.order'] || []).map((record) => record.id));
            for (const line of records['pos.order.line'] || []) affected.add(relationId(line.order_id));
            for (const payment of records['pos.payment'] || []) affected.add(relationId(payment.pos_order_id));
            for (const order of this.models['pos.order'].getAll()) {
                const serverRecord = (records['pos.order'] || []).find((row) => row.uuid === order.uuid && Number.isSafeInteger(row.id));
                const sourceRecord = (records['pos.order.line'] || []).find((row) => (order.lines || []).some((line) => line.uuid && line.uuid === row.uuid));
                const serverId = Number.isSafeInteger(order.id) ? order.id : order.uiState?.baseerSharedDraftServerOrderId ?? serverRecord?.id ?? relationId(sourceRecord?.order_id);
                const related = affected.has(order.id) || affected.has(serverId) ||
                    (records['pos.order'] || []).some((row) => row.uuid === order.uuid) ||
                    (records['pos.order.line'] || []).some((row) => (order.lines || []).some((line) => line.uuid && line.uuid === row.uuid)) ||
                    (records['pos.payment'] || []).some((row) => (order.payment_ids || []).some((payment) => payment.uuid && payment.uuid === row.uuid));
                if (!related || order.state !== 'draft' || !isManagedSharedDraft(order)) continue;
                try {
                    if (isCleanHydratedSharedDraft(order)) await this.pos.baseerRefreshCleanSharedDraftExperiment(order);
                    else if (Number.isSafeInteger(serverId)) await this.pos.baseerVerifyIncomingSharedRevisionExperiment(order, serverId);
                }
                catch (error) {
                    if (!(error instanceof ConnectionLostError)) this.pos.notification.add(_t('The shared order could not be refreshed. Keep its local copy for review.'), { type: 'warning' });
                }
            }
        }
        const protectedIds = protectedOfflineRecords(this.models);
        if (!protectedIds.orderUuids.size) return super.processDynamicRecords(...arguments);
        const safe = { ...records };
        if (records["pos.order"]) safe["pos.order"] = records["pos.order"].filter((record) =>
            !protectedIds.orders.has(record.id) && !protectedIds.orderUuids.has(record.uuid));
        if (records["pos.order.line"]) safe["pos.order.line"] = records["pos.order.line"].filter((record) =>
            !protectedIds.lines.has(record.id) && !protectedIds.lineUuids.has(record.uuid) && !protectedIds.orders.has(relationId(record.order_id)));
        if (records["pos.payment"]) safe["pos.payment"] = records["pos.payment"].filter((record) =>
            !protectedIds.payments.has(record.id) && !protectedIds.paymentUuids.has(record.uuid) && !protectedIds.orders.has(relationId(record.pos_order_id)));
        if (records["product.attribute.custom.value"]) safe["product.attribute.custom.value"] = records["product.attribute.custom.value"].filter((record) =>
            !protectedIds.attributes.has(record.id) && !protectedIds.orders.has(relationId(record.pos_order_id)));
        return super.processDynamicRecords(safe);
    },
    processDeletedRecords(records) {
        if (SHARED_DRAFT_FLOW_ENABLED && this.pos?.baseerAcceptRemoteSharedDeletionExperiment) {
            const deletedOrders = new Set(records['pos.order'] || []);
            const deletedLines = new Set(records['pos.order.line'] || []);
            const deletedPayments = new Set(records['pos.payment'] || []);
            for (const order of this.models['pos.order'].getAll()) {
                let task;
                if ((deletedOrders.has(order.id) || deletedOrders.has(order.uiState?.baseerSharedDraftServerOrderId)) && order.state === 'draft' && isManagedSharedDraft(order)) {
                    task = this.pos.baseerAcceptRemoteSharedDeletionExperiment(order);
                } else if (order.state === 'draft' && isManagedSharedDraft(order) &&
                    ((order.lines || []).some((line) => deletedLines.has(line.id) || deletedLines.has(order.uiState?.baseerSharedDraftLineIds?.[line.uuid])) ||
                     (order.payment_ids || []).some((payment) => deletedPayments.has(payment.id) || deletedPayments.has(order.uiState?.baseerSharedDraftPaymentIds?.[payment.uuid])))) {
                    if (isCleanHydratedSharedDraft(order)) task = this.pos.baseerRefreshCleanSharedDraftExperiment?.(order);
                    else {
                        const serverId = Number.isSafeInteger(order.id) ? order.id : order.uiState?.baseerSharedDraftServerOrderId;
                        if (Number.isSafeInteger(serverId)) task = this.pos.baseerVerifyIncomingSharedRevisionExperiment?.(order, serverId);
                    }
                }
                task?.catch(() => {
                    this.pos.notification.add(_t('The shared order could not be refreshed. Keep its local copy for review.'), { type: 'warning' });
                });
            }
        }
        const protectedIds = protectedOfflineRecords(this.models);
        if (!protectedIds.orderUuids.size) return super.processDeletedRecords(...arguments);
        const safe = { ...records };
        for (const [model, ids] of [["pos.order", protectedIds.orders], ["pos.order.line", protectedIds.lines],
            ["pos.payment", protectedIds.payments], ["product.attribute.custom.value", protectedIds.attributes]]) {
            if (records[model]) safe[model] = records[model].filter((id) => !ids.has(id));
        }
        return super.processDeletedRecords(safe);
    },
});

export class BaseerGlobalDiscountDialog extends Component {
    static template = "baseer_pos_global_discount.Dialog";
    static components = { Dialog };
    static props = { close: Function, getPayload: Function, locked: Boolean, refund: Boolean };
    setup() {
        this.state = useState({ kind: "fixed", value: "" });
        useAutofocus({ mobile: true });
    }
    confirm() {
        this.props.getPayload({ kind: this.state.kind, value: this.state.value });
        this.props.close();
    }
    onValueKeydown(event) {
        if (event.key === "Enter" && !event.repeat) {
            event.preventDefault();
            this.confirm();
        }
    }
    remove() {
        this.props.getPayload({ kind: "remove", value: "0" });
        this.props.close();
    }
}

patch(PosStore.prototype, {
    baseerDiscountKey(order) { return discountStorageKey(session.db || "", this.config.id, order.uuid); },
    async clickSaveOrder() {
        const order = this.getOrder();
        if (!SHARED_DRAFT_FLOW_ENABLED || !isManagedSharedDraft(order)) return super.clickSaveOrder(...arguments);
        try {
            const acknowledged = await this.syncAllOrders({ orders: [order], throw: true });
            if (!acknowledged?.includes(order) || order.uiState?.baseerSharedDraftPending || order.uiState?.baseerSharedDraftNeedsSync) {
                throw new Error('The current draft has not been acknowledged');
            }
            this.notification.add(_t('Order saved for later'), { type: 'success' });
            this.setOrder(this.getEmptyOrder());
            this.mobile_pane = 'right';
        } catch (error) {
            const tracker = this.models?._baseerDraftGenerationTracker;
            if (error instanceof ConnectionLostError && order.uiState?.baseerSharedDraftPending && tracker &&
                order.uiState.baseerSharedDraftGeneration === tracker.get()) {
                this.notification.add(_t('Order saved locally; it will sync when the connection returns.'), { type: 'warning' });
                this.setOrder(this.getEmptyOrder());
                this.mobile_pane = 'right';
                return;
            }
            this.notification.add(_t('The order could not be synchronized. Keep it for manager review.'), { type: 'danger', sticky: true });
        }
    },
    async baseerSettleSharedDraftBeforePaymentExperiment(order) {
        if (!SHARED_DRAFT_FLOW_ENABLED || order?.state !== 'draft' || !order.uiState?.baseerSharedDraftPending || this.data.network.offline) return true;
        if (sharedRefreshOrders.has(order) || order.uiState.baseerSharedDraftContaminated || order.uiState.baseerSharedDraftRemoteDeleted || order.uiState.baseerSharedDraftHydrationError) return false;
        const warning = _t('The shared order changed on another device. Keep your local changes for review.');
        if (order.uiState.baseerSharedDraftRefreshError && order.uiState.baseerSharedDraftRefreshError !== warning) return false;
        try { await this.baseerRunSharedDraftExperiment(order); }
        catch (error) {
            if (!(error instanceof ConnectionLostError)) throw error;
            markPosDisconnected(this.data);
            return true;
        }
        if (order.uiState.baseerSharedDraftPending) return false;
        if (order.uiState.baseerSharedDraftRefreshError === warning) delete order.uiState.baseerSharedDraftRefreshError;
        return !order.uiState.baseerSharedDraftRefreshError;
    },
    async baseerVerifyIncomingSharedRevisionExperiment(order, serverId) {
        const message = _t('The shared order changed on another device. Keep your local changes for review.');
        const prior = order.uiState.baseerSharedDraftRefreshError;
        if (prior && prior !== message) return false;
        const initialState = order.state;
        const initialRevision = order.uiState.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision ?? 0;
        order.uiState.baseerSharedDraftRefreshError = message;
        const check = (sharedRevisionChecks.get(order) || 0) + 1;
        sharedRevisionChecks.set(order, check);
        if (!prior || order.uiState.baseerSharedDraftRevisionWarningProvisional === true) {
            sharedRevisionWarningOwners.set(order, check);
            order.uiState.baseerSharedDraftRevisionWarningProvisional = true;
        }
        const paidAckArrived = () => {
            if (sharedRevisionChecks.get(order) !== check || !order.uiState?.baseerSharedDraftPaidAckPending ||
                !['paid', 'done', 'invoiced'].includes(order.state)) return false;
            if (sharedRevisionWarningOwners.get(order) === check && order.uiState.baseerSharedDraftRefreshError === message) {
                delete order.uiState.baseerSharedDraftRefreshError;
                clearProvisionalWarning(order);
                sharedRevisionWarningOwners.delete(order);
            }
            return true;
        };
        const verifying = (async () => {
            let raw;
            try { raw = await this.data.orm.call('pos.order', 'read_pos_orders', [[['id', '=', serverId]]]); }
            catch (error) {
                if (paidAckArrived()) return false;
                throw error;
            }
            if (sharedRevisionChecks.get(order) !== check) return false;
            // A paid ACK may have arrived while this draft check was in
            // flight. Its frozen graph must be reconciled, never replaced by
            // a stale draft/deletion response or sent as a new payment.
            if (paidAckArrived()) return false;
            const currentRevision = order.uiState.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision ?? 0;
            const server = raw?.['pos.order']?.find((row) => row.id === serverId && row.uuid === order.uuid);
            const locallyPaidAgainstSameDraft = initialState === 'draft' && order.state === 'paid' &&
                currentRevision === initialRevision && server?.state === 'draft' &&
                server.baseer_offline_draft_revision === initialRevision;
            if ((order.state !== initialState && !locallyPaidAgainstSameDraft) || currentRevision !== initialRevision) {
                // A local paid transition may precede the ACK from that same
                // command. Keep our warning's provenance until ACK or a
                // separately established conflict can settle it.
                if (!(initialState === 'draft' && order.state === 'paid' && currentRevision === initialRevision) &&
                    sharedRevisionWarningOwners.get(order) === check) {
                    markProvisionalWarningConflicted(order);
                }
                return false;
            }
            if (!server || server.state !== 'draft') {
                if (sharedRevisionWarningOwners.get(order) === check) markProvisionalWarningConflicted(order);
                await this.baseerAcceptRemoteSharedDeletionExperiment(order);
                return false;
            }
            const revision = order.uiState.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision ?? 0;
            if (!Number.isSafeInteger(server.baseer_offline_draft_revision) || server.baseer_offline_draft_revision !== revision) {
                if (sharedRevisionWarningOwners.get(order) === check) markProvisionalWarningConflicted(order);
                return false;
            }
            if (sharedRevisionWarningOwners.get(order) === check) {
                if (order.uiState.baseerSharedDraftRefreshError === message) delete order.uiState.baseerSharedDraftRefreshError;
                clearProvisionalWarning(order);
                sharedRevisionWarningOwners.delete(order);
            }
            return true;
        })();
        sharedRevisionPromises.set(order, verifying);
        try { return await verifying; }
        finally { if (sharedRevisionPromises.get(order) === verifying) sharedRevisionPromises.delete(order); }
    },
    async baseerCheckRestoredSharedDraftExperiment(order, { allowFrozenRetry = false } = {}) {
        if (!restoredSharedDrafts.has(order) || this.data.network.offline) return true;
        const serverId = Number.isSafeInteger(order.id) ? order.id : order.uiState?.baseerSharedDraftServerOrderId;
        let raw;
        try { raw = await this.data.orm.call('pos.order', 'read_pos_orders', [[['id', '=', serverId]]]); }
        catch (error) {
            if (!(error instanceof ConnectionLostError)) throw error;
            markPosDisconnected(this.data);
            return true;
        }
        const server = raw?.['pos.order']?.find((record) => record.id === serverId && record.uuid === order.uuid);
        if (!server || server.state !== 'draft') {
            await this.baseerAcceptRemoteSharedDeletionExperiment(order);
            return false;
        }
        const revision = order.uiState.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision ?? 0;
        if (!Number.isSafeInteger(revision) || !Number.isSafeInteger(server.baseer_offline_draft_revision) || server.baseer_offline_draft_revision !== revision) {
            markProvisionalWarningConflicted(order);
            order.uiState.baseerSharedDraftRefreshError = _t('The shared order changed on another device. Keep your local changes for review.');
            return Boolean(Number.isSafeInteger(server.baseer_offline_draft_revision) && Number.isSafeInteger(revision) &&
                server.baseer_offline_draft_revision > revision && allowFrozenRetry && order.uiState.baseerSharedDraftPending);
        }
        restoredSharedDrafts.delete(order);
        return true;
    },
    // Explicit test hook only. Native sync/payment/printing do not call it;
    // this path must not be enabled until the full shared-draft contract passes.
    async baseerRunSharedDraftExperiment(order) {
        if (!isManagedSharedDraft(order)) {
            throw new Error('A managed order is required');
        }
        if (sharedRefreshOrders.has(order) || order.uiState?.baseerSharedDraftContaminated) throw new Error('The shared draft needs refresh');
        if (order.uiState?.baseerSharedDraftRemoteDeleted || !await this.baseerCheckRestoredSharedDraftExperiment(order, { allowFrozenRetry: Boolean(order.uiState?.baseerSharedDraftPending) })) throw new Error('Remote deletion requires review');
        if (order.uiState?.baseerSharedDraftPaidAckPending) throw new Error('The paid order is awaiting server reconciliation');
        if (order.uiState?.baseerSharedDraftCancelPending || order.uiState?.baseerSharedDraftCancelAcknowledged) throw new Error('The draft cancellation needs resolution');
        if (this.syncingOrders.has(order.uuid)) throw new Error('The draft is already synchronizing');
        const tracker = attachDraftGenerationExperiment(this.models);
        if (order.state === 'draft' && order.baseer_offline_draft_kind && !order.uiState.baseerOfflineDiscount &&
            !order.uiState.baseerSharedDraftPending && !order.uiState.baseerSharedDraftRemoveRequested) {
            hydrateSharedDraftExperiment({ pos: this, order, calculate: calculateOfflineDiscount,
                exportExtraTaxData: (base) => accountTaxHelpers.export_base_line_extra_tax_data(base) });
        }
        const adapter = createDraftSyncAdapterExperiment({ data: this.data, order, tracker,
            protect: (record) => protectOfflineStorage(this.data.indexedDB, record),
            prepare: (record) => {
                if (record.state === 'draft' && record.uiState.baseerOfflineDiscount) {
                    refreshOfflineDiscount(this, record);
                    if (record.uiState.baseerOfflineDiscount.error) throw new Error(record.uiState.baseerOfflineDiscount.error);
                }
                record.setOrderPrices();
            },
            getContext: (record) => this.getSyncAllOrdersContext([record], {}),
            offlineError: () => new ConnectionLostError(),
        });
        this.addPendingOrder([order.id]);
        this.syncingOrders.add(order.uuid);
        try { return await (order.state === 'paid' ? runPaidAfterDraftExperiment(adapter, order) : runDraftSnapshotExperiment(adapter)); }
        finally { this.syncingOrders.delete(order.uuid); }
    },
    async baseerRecoverChangedCancellation(order) {
        const pending = order.uiState?.baseerSharedDraftCancelPending;
        const tracker = attachDraftGenerationExperiment(this.models);
        const sessionId = this.config.current_session_id?.id || this.config.current_session_id;
        if (!pending || !Number.isSafeInteger(sessionId) || sessionId < 1 || this.data.network.offline ||
            order.uiState.baseerSharedDraftPending || this.syncingOrders.has(order.uuid)) {
            throw new Error(_t('The previous cancellation needs review. Keep the order open.'));
        }
        // A missing preview is not evidence that the cashier removed the
        // discount. Resume only if the explicit removal intent was retained.
        if (order.baseer_offline_draft_kind && !order.uiState.baseerOfflineDiscount &&
            !order.uiState.baseerSharedDraftRemoveRequested) {
            throw new Error(_t('The local discount change needs review. Keep the order open.'));
        }
        order.uiState.baseerSharedDraftNeedsSync = true;
        await persistDraftCancelExperiment({ data: this.data, order, tracker, pending,
            protect: (record) => protectOfflineStorage(this.data.indexedDB, record) });
        const resolution = await this.data.orm.call('pos.order', 'baseer_resolve_offline_draft_cancel',
            [order.uuid, pending.revision, pending.command_uuid, sessionId]);
        if (resolution?.outcome !== 'fenced') {
            throw new Error(_t('The previous cancellation needs manager review. Keep the local order open.'));
        }
        await persistCancelFenceRecovery({ data: this.data, order, tracker, pending, resolution,
            protect: (record) => protectOfflineStorage(this.data.indexedDB, record) });
        await this.baseerFinishCancellationRecovery(order);
    },
    async baseerFinishCancellationRecovery(order) {
        const tracker = attachDraftGenerationExperiment(this.models);
        await this.baseerRunSharedDraftExperiment(order);
        if (order.uiState.baseerSharedDraftPending || order.uiState.baseerSharedDraftNeedsSync ||
            tracker.get() !== order.uiState.baseerSharedDraftGeneration) {
            throw new Error(_t('The latest order changes are not yet synchronized. Keep the order open.'));
        }
    },
    async beforeDeleteOrder(order) {
        const pending = order?.uiState?.baseerSharedDraftCancelPending;
        if (SHARED_DRAFT_FLOW_ENABLED && !pending && order?.state === 'draft' && isManagedSharedDraft(order) &&
            !order.uiState?.baseerSharedDraftRecoverySync) {
            const tracker = attachDraftGenerationExperiment(this.models);
            const state = order.uiState;
            const generation = state.baseerSharedDraftGeneration;
            const needsSync = state.baseerSharedDraftNeedsSync || state.baseerSharedDraftPending ||
                state.baseerSharedDraftRemoveRequested || state.baseerSharedDraftPaymentDeletions?.length ||
                (Number.isSafeInteger(generation) && generation !== tracker.get());
            if (needsSync) {
                try {
                    let checking;
                    while ((checking = sharedRevisionPromises.get(order))) await checking;
                    if (this.data.network.offline || order.payment_ids?.length || state.baseerSharedDraftPaidAckPending ||
                        state.baseerSharedDraftCancelAcknowledged || state.baseerSharedDraftRefreshError ||
                        state.baseerSharedDraftContaminated || state.baseerSharedDraftRemoteDeleted || state.baseerSharedDraftHydrationError ||
                        (state.baseerSharedDraftPending && state.baseerSharedDraftPending.target_state !== 'draft')) {
                        throw new Error(_t('The order has payment or synchronization activity. Keep it open for review.'));
                    }
                    await this.baseerRunSharedDraftExperiment(order);
                    if (order.state !== 'draft' || order.payment_ids?.length || state.baseerSharedDraftPaidAckPending ||
                        state.baseerSharedDraftPending || state.baseerSharedDraftNeedsSync ||
                        tracker.get() !== state.baseerSharedDraftGeneration) {
                        throw new Error(_t('The latest order changes are not yet synchronized. Keep the order open.'));
                    }
                } catch (error) {
                    this.notification.add(error?.data?.message || error?.message || _t('The order needs review before cancellation.'),
                        { type: 'warning', sticky: true });
                    return false;
                }
            }
        }
        if (SHARED_DRAFT_FLOW_ENABLED && pending) {
            const tracker = attachDraftGenerationExperiment(this.models);
            if (cancelRequiresSyncReview(order, pending, tracker) || !cancelGraphUnchanged(order, pending, tracker)) {
                try {
                    await this.baseerRecoverChangedCancellation(order);
                } catch (error) {
                    this.notification.add(error?.data?.message || error?.message || _t('The order needs review before cancellation.'),
                        { type: 'warning', sticky: true });
                    return false;
                }
            }
        }
        if (SHARED_DRAFT_FLOW_ENABLED && order?.uiState?.baseerSharedDraftRecoverySync &&
            (order.uiState.baseerSharedDraftNeedsSync || order.uiState.baseerSharedDraftPending)) {
            try {
                await this.baseerFinishCancellationRecovery(order);
            } catch (error) {
                this.notification.add(error?.data?.message || error?.message || _t('The order needs review before cancellation.'),
                    { type: 'warning', sticky: true });
                return false;
            }
        }
        // A committed kitchen cancellation may have lost its reply. Its
        // ordinary preview rejects cancelled server orders, so retry only
        // the already-persisted command and original reason before preview.
        if (SHARED_DRAFT_FLOW_ENABLED && order?.uiState?.baseerSharedDraftCancelPending &&
            order.uiState.baseerSharedDraftKitchenCancelIntent) {
            try {
                const tracker = attachDraftGenerationExperiment(this.models);
                const saved = order.uiState.baseerSharedDraftCancelPending;
                const sessionId = this.config.current_session_id?.id || this.config.current_session_id;
                if (order.state !== 'draft' || cancelRequiresSyncReview(order, saved, tracker) ||
                    order.uiState.baseerSharedDraftPending || !cancelGraphUnchanged(order, saved, tracker) ||
                    order.uiState.baseerPreparationOutcomeUnknown || order.uiState.baseerSharedDraftPaidAckPending ||
                    order.uiState.baseerBillSplitPending || order.uiState.baseerRestaurantMergePending || order.payment_ids?.length) {
                    throw new Error(_t('The previous cancellation needs review. Keep the order open.'));
                }
                kitchenCancelIntent(order.uiState.baseerSharedDraftKitchenCancelIntent,
                    order.uiState.baseerKitchenCancellation, sessionId);
                return true;
            } catch (error) {
                this.notification.add(error?.data?.message || error?.message || _t('The order needs review before cancellation.'),
                    { type: 'warning', sticky: true });
                return false;
            }
        }
        const allowed = await super.beforeDeleteOrder(...arguments);
        if (!allowed || !SHARED_DRAFT_FLOW_ENABLED || !this.config.baseer_direct_print_enabled ||
            !isManagedSharedDraft(order) || (order.isSynced && Number.isSafeInteger(order.id))) return allowed;
        try {
            const serverId = order.uiState?.baseerSharedDraftServerOrderId;
            const sessionId = this.config.current_session_id?.id || this.config.current_session_id;
            if (!Number.isSafeInteger(serverId) || serverId < 1 || !Number.isSafeInteger(sessionId) || sessionId < 1 ||
                this.data.network.offline) throw new Error(_t('The shared order identity needs review before cancellation.'));
            const raw = await this.data.orm.call('pos.order', 'read_pos_orders', [[['id', '=', serverId]]]);
            const server = raw?.['pos.order']?.find((row) => row.id === serverId && row.uuid === order.uuid);
            if (!server || server.state !== 'draft') throw new Error(_t('The shared order changed or is unavailable. Keep it open for review.'));
            const preview = await this._baseerCancellationPreview([serverId], sessionId);
            if (!preview?.order_ids?.includes(serverId)) return true;
            const reason = await this._baseerAskCancellationReason(1);
            if (!reason) return false;
            order.uiState.baseerKitchenCancellation = reason;
            return true;
        } catch (error) {
            this.notification.add(error?.data?.message || error?.message || _t('The order needs review before cancellation.'),
                { type: 'warning', sticky: true });
            return false;
        }
    },
    async baseerCancelSharedDraftExperiment(order) {
        if (!isManagedSharedDraft(order) || order.state !== 'draft') throw new Error('A managed draft is required');
        if (order.uiState.baseerSharedDraftPending || this.syncingOrders.has(order.uuid)) throw new Error('Synchronize the previous draft command before cancelling');
        const tracker = attachDraftGenerationExperiment(this.models);
        const sessionId = this.config.current_session_id?.id || this.config.current_session_id;
        const kitchen = kitchenCancelIntent(order.uiState.baseerSharedDraftKitchenCancelIntent,
            order.uiState.baseerKitchenCancellation, sessionId);
        const previousPending = order.uiState.baseerSharedDraftCancelPending;
        const pending = previousPending || { order_uuid: order.uuid,
            revision: order.uiState.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision,
            command_uuid: crypto.randomUUID(), generation: tracker.get(),
            graph_fingerprint: cancelGraphFingerprint(order) };
        if (kitchen && (cancelRequiresSyncReview(order, previousPending, tracker) || !cancelGraphUnchanged(order, pending, tracker) ||
            (!previousPending && Number.isSafeInteger(order.uiState.baseerSharedDraftGeneration) &&
             tracker.get() !== order.uiState.baseerSharedDraftGeneration))) {
            throw new Error(_t('The order has unsynchronized changes. Keep it open and ask a manager to review before cancellation.'));
        }
        const bytes = JSON.stringify({ pending, kitchen });
        let committed;
        await singleFlightDraftExperiment(order.uuid, pending.command_uuid, bytes, async () => {
            if (kitchen) {
                // Also persist for a legacy pending cancellation. Never infer
                // that its previous request failed just because no ACK arrived.
                order.uiState.baseerSharedDraftKitchenCancelIntent = kitchen;
                await persistDraftCancelExperiment({ data: this.data, order, tracker, pending,
                    protect: (record) => protectOfflineStorage(this.data.indexedDB, record) });
            }
            return cancelDraftSnapshot({
            readPending: () => order.uiState.baseerSharedDraftCancelPending,
            createCancel: () => pending,
            persistPending: (value) => persistDraftCancelExperiment({ data: this.data, order, tracker, pending: value,
                protect: (record) => protectOfflineStorage(this.data.indexedDB, record) }),
            sendCancel: (uuid, revision, commandUuid) => {
                if (this.data.network.offline) throw new ConnectionLostError();
                return this.data.orm.call('pos.order', 'baseer_cancel_offline_draft',
                    kitchen ? [uuid, revision, commandUuid, kitchen] : [uuid, revision, commandUuid]);
            },
            commitAck: async ({ pending: value, revision }) => {
                committed = await persistDraftCancelExperiment({ data: this.data, order, tracker, pending: value,
                    acknowledgement: { uuid: order.uuid, state: 'cancel', revision },
                    protect: (record) => protectOfflineStorage(this.data.indexedDB, record) });
            },
            });
        });
        if (!committed || committed.needsReview || tracker.get() !== committed.generation) throw new Error('The cancelled draft has newer local changes and needs manager review');
        return true;
    },
    async baseerRefreshCleanSharedDraftExperiment(order, { expected } = {}) {
        if (!isCleanHydratedSharedDraft(order) || this.data.network.offline || sharedRefreshOrders.has(order)) return false;
        sharedRefreshOrders.add(order);
        try {
        const tracker = attachDraftGenerationExperiment(this.models);
        const before = tracker.get();
        const serverId = Number.isSafeInteger(order.id) ? order.id : order.uiState.baseerSharedDraftServerOrderId;
        if (expected && (serverId !== expected.serverId || order.uuid !== expected.uuid ||
            (order.uiState?.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision) !== expected.revision)) return false;
        const raw = await this.data.orm.call('pos.order', 'read_pos_orders', [[['id', '=', serverId]]]);
        if (tracker.get() !== before || !isCleanHydratedSharedDraft(order)) throw new Error('The shared draft changed while refreshing');
        if (expected && !matchesExpectedSharedDraft((raw?.['pos.order'] || []).find((item) => item.id === serverId), expected)) return false;
        const expanded = await this.data.missingRecursive(raw);
        const server = (expanded?.['pos.order'] || []).find((item) => item.uuid === order.uuid);
        if (expected && !matchesExpectedSharedDraft(server, expected)) return false;
        if (expected && !matchesExpectedSharedDraftLines(expanded, server, expected)) return false;
        const localRevision = order.uiState?.baseerSharedDraftRevision ?? order.baseer_offline_draft_revision ?? 0;
        if (tracker.get() !== before || !isCleanHydratedSharedDraft(order) || !server || server.state !== 'draft' ||
            !Number.isSafeInteger(server.baseer_offline_draft_revision) || !Number.isSafeInteger(localRevision) ||
            server.baseer_offline_draft_revision < Math.max(1, localRevision)) throw new Error('The shared draft response cannot be verified');
        if (expected) {
            // Expansion may fetch related records separately. Re-read the
            // order before replacing the local graph and fail on any change.
            const confirmed = await this.data.orm.call('pos.order', 'read_pos_orders', [[['id', '=', serverId]]]);
            if (tracker.get() !== before || !isCleanHydratedSharedDraft(order) ||
                !matchesExpectedSharedDraft((confirmed?.['pos.order'] || []).find((item) => item.id === serverId), expected)) return false;
        }
        const oldId = order.id;
        protectOfflineStorage(this.data.indexedDB, order);
        const oldProtection = this.data.indexedDB._baseerOfflineProtection.get(order.uuid);
        // Staging builds a fresh preview itself. Invalidate an older queued
        // rebuild and ignore its synchronous model events, not later cashier edits.
        this._baseerOfflineScheduled?.delete(order.uuid);
        sharedStageOrders.add(order);
        let staged;
        try { staged = stageNativeServerGraphExperiment({ order, response: expanded,
            beforeLoad: (record) => { delete record.uiState.baseerOfflineDiscount; },
            verify: (record) => {
                if (record.uuid !== server.uuid || record.state !== 'draft') throw new Error('The shared draft response is invalid');
                if (record.baseer_offline_draft_kind) hydrateSharedDraftExperiment({ pos: this, order: record,
                    calculate: calculateOfflineDiscount, exportExtraTaxData: (base) => accountTaxHelpers.export_base_line_extra_tax_data(base) });
                record.uiState.baseerSharedDraftHydratedOnly = true;
                record.uiState.baseerSharedDraftRevision = server.baseer_offline_draft_revision;
            },
        }); } finally { sharedStageOrders.delete(order); }
        const stagedGeneration = tracker.get();
        // The tracker covers every POS order. Compare this complete order graph
        // as well, so background events for other orders do not block a send.
        // An unavailable fingerprint must fail closed.
        let stagedFingerprint;
        try { stagedFingerprint = expected ? refreshGraphFingerprint(order) : null; }
        catch (error) { staged.rollback(); throw error; }
        const orderChanged = () => {
            try { return refreshGraphFingerprint(order) !== stagedFingerprint; }
            catch { return true; }
        };
        protectOfflineStorage(this.data.indexedDB, order);
        const protection = this.data.indexedDB._baseerOfflineProtection.get(order.uuid);
        for (const [model, keys] of Object.entries(oldProtection || {})) for (const key of keys) protection[model]?.add(key);
        const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
        try {
            let saved, capturedRawFingerprint;
            do {
                saved = await persistDraftGraphExperiment({ data: this.data, currentGeneration: () => tracker.get(), capture: () => {
                    const generation = tracker.get();
                    const lines = order.lines || [];
                    const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((item) => [item.id, item])).values()];
                    const row = serialize(order);
                    const state = row.JSONuiState ? JSON.parse(row.JSONuiState) : {};
                    delete state.baseerSharedDraftContaminated;
                    state.baseerSharedDraftGeneration = generation;
                    if (expected && orderChanged()) {
                        state.baseerSharedDraftNeedsSync = true;
                        state.baseerSharedDraftRefreshError = _t('The shared order changed while saving. Keep its local copy for review.');
                    }
                    row.JSONuiState = JSON.stringify(state);
                    if (expected) capturedRawFingerprint = cancelGraphFingerprint(order);
                    return { generation, orderIds: [oldId, order.id, order.uuid], records: {
                        'pos.order': [row], 'pos.order.line': lines.map(serialize), 'pos.payment': (order.payment_ids || []).map(serialize),
                        'product.attribute.custom.value': attrs.map(serialize),
                    } };
                } });
            } while (tracker.get() !== saved.generation || (expected && cancelGraphFingerprint(order) !== capturedRawFingerprint));
            if (expected && orderChanged()) {
                order.uiState.baseerSharedDraftNeedsSync = true;
                order.uiState.baseerSharedDraftRefreshError = _t('The shared order changed while saving. Keep its local copy for review.');
                throw new Error(order.uiState.baseerSharedDraftRefreshError);
            }
            order.uiState.baseerSharedDraftGeneration = saved.generation;
            delete order.uiState.baseerSharedDraftContaminated;
            return true;
        } catch (error) {
            if (tracker.get() === stagedGeneration && (!expected || !orderChanged())) staged.rollback();
            else order.uiState.baseerSharedDraftRefreshError = _t('The shared order could not be saved after local changes. Keep this screen open and ask a manager.');
            throw error;
        }
        } catch (error) {
            order.uiState.baseerSharedDraftRefreshError ||= _t('The shared order could not be refreshed. Keep its local copy for review.');
            throw error;
        } finally { sharedRefreshOrders.delete(order); }
    },
    async baseerAcceptRemoteSharedDeletionExperiment(order) {
        if (order?.state !== 'draft' || !isManagedSharedDraft(order) || sharedRemoteDeleteOrders.has(order)) return false;
        const tracker = attachDraftGenerationExperiment(this.models);
        sharedRemoteDeleteOrders.add(order);
        order.uiState.baseerSharedDraftRemoteDeleted = true;
        order.uiState.baseerSharedDraftRefreshError = _t('This shared order was removed on another device. Keep this copy and ask a manager to review it.');
        try {
            protectOfflineStorage(this.data.indexedDB, order);
            const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
            const saved = await persistDraftGraphExperiment({ data: this.data, currentGeneration: () => tracker.get(), capture: () => {
                const generation = tracker.get();
                const lines = order.lines || [];
                const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((item) => [item.id, item])).values()];
                const row = serialize(order);
                const state = row.JSONuiState ? JSON.parse(row.JSONuiState) : {};
                state.baseerSharedDraftRemoteDeleted = true;
                state.baseerSharedDraftRefreshError = _t('This shared order was removed on another device. Keep this copy and ask a manager to review it.');
                state.baseerSharedDraftGeneration = generation;
                row.JSONuiState = JSON.stringify(state);
                return { generation, orderIds: [order.id, order.uuid], records: {
                    'pos.order': [row], 'pos.order.line': lines.map(serialize), 'pos.payment': (order.payment_ids || []).map(serialize),
                    'product.attribute.custom.value': attrs.map(serialize),
                } };
            } });
            order.uiState.baseerSharedDraftRemoteDeleted = true;
            order.uiState.baseerSharedDraftRefreshError = _t('This shared order was removed on another device. Keep this copy and ask a manager to review it.');
            if (tracker.get() !== saved.generation) throw new Error('The shared draft changed during deletion');
            return true;
        } catch (error) {
            order.uiState.baseerSharedDraftRefreshError = _t('The shared order could not be saved. Keep this screen open and ask a manager to repair the local storage.');
            throw error;
        } finally { sharedRemoteDeleteOrders.delete(order); }
    },
    async baseerReconcileSharedPaidExperiment(order) {
        if (paidReconciliationOrders.has(order)) throw new Error('Paid reconciliation is already running');
        paidReconciliationOrders.add(order);
        try {
        const state = order?.uiState;
        const pending = state?.baseerSharedDraftPaidCommand;
        const savedResponse = state?.baseerSharedDraftPaidServerResponse;
        if (!state?.baseerSharedDraftPaidAckPending || !pending || !savedResponse || !['paid', 'done', 'invoiced'].includes(order.state)) throw new Error('Paid server acknowledgement is unavailable');
        if (state.baseerSharedDraftNeedsSync) throw new Error('The paid order has newer changes and needs manager review');
        const tracker = attachDraftGenerationExperiment(this.models);
        const before = tracker.get();
        const payload = JSON.parse(pending.payload_json);
        const serverOrder = (savedResponse['pos.order'] || []).find((item) => item.uuid === order.uuid);
        if (!serverOrder) throw new Error('Paid server acknowledgement is unavailable');
        validatePaidAckGraphExperiment(pending, payload, savedResponse, serverOrder);
        const invoice = await verifyPaidInvoiceExperiment({ pending, response: savedResponse,
            readInvoice: (id) => this.data.orm.read('account.move', [id], ['id', 'state']) });
        const expanded = await this.data.missingRecursive(JSON.parse(JSON.stringify(savedResponse)));
        if (tracker.get() !== before || !(expanded?.['pos.order'] || []).some((item) => item.uuid === order.uuid)) throw new Error('The paid order changed during reconciliation');
        const oldId = order.id;
        const expectedTotal = Number(payload.baseer_offline_discount_intent?.expected_total ?? payload.amount_total);
        const expectedTax = Number(payload.baseer_offline_discount_intent?.expected_tax ?? payload.amount_tax);
        const verify = (record) => {
            const paymentUuids = (record.payment_ids || []).map((payment) => payment.uuid);
            if (this.models['pos.order'].getBy('uuid', record.uuid) !== record ||
                record.currency.round(record.priceIncl) !== record.currency.round(expectedTotal) ||
                record.currency.round(record.amountTaxes) !== record.currency.round(expectedTax) ||
                new Set(paymentUuids).size !== paymentUuids.length ||
                (pending.source_payment_uuids || []).some((uuid) => !paymentUuids.includes(uuid)) ||
                (record.lines || []).some((line) => pending.source_line_uuids?.includes(line.uuid) === false &&
                    !line.baseer_global_discount_line)) throw new Error('The paid server graph does not match the saved payment');
        };
        const staged = stagePaidServerGraphExperiment({ order, response: expanded, pending, verify });
        const oldProtection = this.data.indexedDB?._baseerOfflineProtection?.get(order.uuid);
        protectOfflineStorage(this.data.indexedDB, order);
        const protection = this.data.indexedDB._baseerOfflineProtection.get(order.uuid);
        for (const [model, keys] of Object.entries(oldProtection || {})) for (const key of keys) protection[model]?.add(key);
        const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
        let persisted;
        try {
            persisted = await persistDraftGraphExperiment({ data: this.data, currentGeneration: () => tracker.get(), capture: () => {
                verify(order);
                const generation = tracker.get();
                const lines = order.lines || [];
                const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((item) => [item.id, item])).values()];
                const row = serialize(order);
                const ui = row.JSONuiState ? JSON.parse(row.JSONuiState) : {};
                delete ui.baseerOfflineDiscount;
                delete ui.baseerSharedDraftPaidAckPending;
                delete ui.baseerSharedDraftPaidServerResponse;
                delete ui.baseerSharedDraftPaidCommand;
                ui.baseerSharedDraftInvoicePending = Boolean(invoice.required && !invoice.confirmed);
                ui.baseerSharedDraftGeneration = generation;
                row.JSONuiState = JSON.stringify(ui);
                return { generation, orderIds: [oldId, order.id, order.uuid], records: {
                    'pos.order': [row], 'pos.order.line': lines.map(serialize), 'pos.payment': (order.payment_ids || []).map(serialize),
                    'product.attribute.custom.value': attrs.map(serialize),
                } };
            } });
            if (tracker.get() !== persisted.generation) throw new Error('The paid order changed during reconciliation');
        } catch (error) {
            staged.rollback();
            throw error;
        }
        delete order.uiState.baseerOfflineDiscount;
        delete order.uiState.baseerSharedDraftPaidAckPending;
        delete order.uiState.baseerSharedDraftPaidServerResponse;
        delete order.uiState.baseerSharedDraftPaidCommand;
        order.uiState.baseerSharedDraftInvoicePending = Boolean(invoice.required && !invoice.confirmed);
        order.uiState.baseerSharedDraftGeneration = persisted.generation;
        for (const set of Object.values(this.pendingOrder)) { set.delete(oldId); set.delete(order.id); }
        this.data.localUnsyncedPaidOrderUuids?.delete(order.uuid);
        this.data.indexedDB?._baseerOfflineProtection?.delete(order.uuid);
        return { invoicePending: order.uiState.baseerSharedDraftInvoicePending };
        } finally {
            paidReconciliationOrders.delete(order);
        }
    },
    async baseerVerifySharedInvoiceExperiment(order) {
        if (!SHARED_DRAFT_FLOW_ENABLED || !order?.uiState?.baseerSharedDraftInvoicePending) return false;
        if (paidReconciliationOrders.has(order)) return false;
        const moveId = relationId(order.account_move) || relationId(order.raw?.account_move);
        if (!Number.isSafeInteger(moveId) || moveId <= 0) return false;
        paidReconciliationOrders.add(order);
        try {
            const rows = await this.data.orm.read('account.move', [moveId], ['id', 'state']);
            if (rows.length !== 1 || rows[0].id !== moveId || rows[0].state !== 'posted') throw new Error('Invoice confirmation is not yet available.');
            const tracker = attachDraftGenerationExperiment(this.models);
            protectOfflineStorage(this.data.indexedDB, order);
            const serialize = (record) => JSON.parse(JSON.stringify(record.serializeForIndexedDB()));
            const saved = await persistDraftGraphExperiment({ data: this.data, currentGeneration: () => tracker.get(), capture: () => {
                const generation = tracker.get();
                const lines = order.lines || [];
                const attrs = [...new Map(lines.flatMap((line) => line.custom_attribute_value_ids || []).map((item) => [item.id, item])).values()];
                const row = serialize(order);
                const state = row.JSONuiState ? JSON.parse(row.JSONuiState) : {};
                state.baseerSharedDraftInvoicePending = false;
                state.baseerSharedDraftGeneration = generation;
                row.JSONuiState = JSON.stringify(state);
                return { generation, orderIds: [order.id, order.uuid], records: {
                    'pos.order': [row], 'pos.order.line': lines.map(serialize), 'pos.payment': (order.payment_ids || []).map(serialize),
                    'product.attribute.custom.value': attrs.map(serialize),
                } };
            } });
            if (tracker.get() !== saved.generation) throw new Error('The paid order changed during invoice verification');
            order.uiState.baseerSharedDraftInvoicePending = false;
            order.uiState.baseerSharedDraftGeneration = saved.generation;
            this.data.indexedDB?._baseerOfflineProtection?.delete(order.uuid);
            return true;
        } catch {
            this.notification.add(_t('Invoice confirmation is not yet available. Ask a manager if this continues.'), { type: 'warning' });
            return false;
        } finally {
            paidReconciliationOrders.delete(order);
        }
    },
    async baseerPrepareSharedDraftPrintExperiment(order) {
        if (!SHARED_DRAFT_FLOW_ENABLED || !isManagedSharedDraft(order)) return null;
        if (order.state !== 'draft' || order.uiState?.baseerSharedDraftHydrationError ||
            order.uiState?.baseerSharedDraftCancelPending || order.uiState?.baseerSharedDraftCancelAcknowledged) return false;
        try {
            await this.baseerRunSharedDraftExperiment(order);
            const tracker = this.models._baseerDraftGenerationTracker;
            const revision = order.uiState.baseerSharedDraftRevision;
            if (!tracker || !Number.isSafeInteger(revision) || revision < 1 || order.uiState.baseerSharedDraftPending ||
                order.uiState.baseerSharedDraftNeedsSync || tracker.get() !== order.uiState.baseerSharedDraftGeneration) return false;
            return { uuid: order.uuid, revision, generation: tracker.get() };
        } catch (error) {
            this.notification.add(error?.data?.message || error?.message || _t('The shared draft needs synchronization before printing.'), { type: 'warning' });
            return false;
        }
    },
    baseerIsSharedDraftPrintCurrentExperiment(order, marker) {
        if (!marker) return marker === null;
        const tracker = this.models._baseerDraftGenerationTracker;
        return Boolean(tracker && order?.state === 'draft' && order.uuid === marker.uuid &&
            order.uiState?.baseerSharedDraftRevision === marker.revision && tracker.get() === marker.generation &&
            !order.uiState?.baseerSharedDraftPending && !order.uiState?.baseerSharedDraftNeedsSync &&
            !order.uiState?.baseerSharedDraftHydrationError && !order.uiState?.baseerSharedDraftCancelPending);
    },
    async printReceipt(options = {}) {
        const order = options.order || this.getOrder();
        if (SHARED_DRAFT_FLOW_ENABLED && (order?.uiState?.baseerSharedDraftPaidAckPending || order?.uiState?.baseerSharedDraftInvoicePending)) {
            this.notification.add(_t('The paid order is awaiting server confirmation before its final receipt can be printed.'), { type: 'warning' });
            return { successful: false };
        }
        return super.printReceipt(...arguments);
    },
    async deleteOrders(orders, serverIds = [], ignoreChange = false) {
        if (!SHARED_DRAFT_FLOW_ENABLED) return super.deleteOrders(...arguments);
        const managed = (orders || []).filter(isManagedSharedDraft);
        const guardedIds = serverIds.filter((id) => isManagedSharedDraft(this.models['pos.order'].get(id)));
        if (guardedIds.length) throw new Error('A shared draft requires protected cancellation');
        if (!managed.length) return super.deleteOrders(...arguments);
        const ordinary = orders.filter((order) => !isManagedSharedDraft(order));
        if (ordinary.length || serverIds.length) {
            const ok = await super.deleteOrders(ordinary, serverIds, ignoreChange);
            if (!ok) return false;
        }
        for (const order of managed) {
            try {
                if (!(await this._onBeforeDeleteOrder(order))) return false;
                await this.baseerCancelSharedDraftExperiment(order);
                this.data.indexedDB?._baseerOfflineProtection?.delete(order.uuid);
                this.data.localDeleteCascade(order);
                this.removePendingOrder(order);
            } catch (error) {
                this.notification.add(error?.data?.message || error?.message || _t('The shared draft could not be cancelled.'), { type: 'warning', sticky: true });
                return false;
            }
        }
        return true;
    },
    removeOrder(order, removeFromServer = true) {
        if (SHARED_DRAFT_FLOW_ENABLED && isManagedSharedDraft(order) && !order.uiState?.baseerSharedDraftCancelAcknowledged) {
            throw new Error('A shared draft requires protected cancellation');
        }
        return super.removeOrder(...arguments);
    },
    async afterProcessServerData() {
        const hydratedOnly = new Set();
        if (SHARED_DRAFT_FLOW_ENABLED) {
            attachDraftGenerationExperiment(this.models);
            for (const order of this.models['pos.order'].getAll()) {
                const preview = new Set(order.uiState?.baseerOfflineDiscount?.preview_line_uuids || []);
                const contaminated = (order.lines || []).some((line) => preview.has(line.uuid)) &&
                    (order.lines || []).some((line) => line.baseer_global_discount_line);
                if (contaminated) order.uiState.baseerSharedDraftContaminated = true;
                if (contaminated && isCleanHydratedSharedDraft(order) && !this.data?.network?.offline) {
                    try { await this.baseerRefreshCleanSharedDraftExperiment(order); }
                    catch { order.uiState.baseerSharedDraftRefreshError ||= _t('The shared order could not be refreshed. Keep its local copy for review.'); }
                }
                if (order.state !== 'draft' || !order.baseer_offline_draft_kind || order.uiState?.baseerOfflineDiscount ||
                    order.uiState?.baseerSharedDraftPending || order.uiState?.baseerSharedDraftRemoveRequested) continue;
                try {
                    hydrateSharedDraftExperiment({ pos: this, order, calculate: calculateOfflineDiscount,
                        exportExtraTaxData: (base) => accountTaxHelpers.export_base_line_extra_tax_data(base) });
                    order.uiState.baseerSharedDraftHydratedOnly = true;
                    order.uiState.baseerSharedDraftRevision = order.baseer_offline_draft_revision;
                    hydratedOnly.add(order.uuid);
                } catch { /* The hydration error blocks payment and preserves the server graph. */ }
            }
        }
        // Native only queues restored unsynced paid orders. Numeric draft IDs
        // may contain offline edits and need to be queued before its first sync.
        const drafts = this.models['pos.order'].getAll().filter((order) =>
            order.state === 'draft' && isPendingOfflineDiscount(order) && !hydratedOnly.has(order.uuid) &&
            (!SHARED_DRAFT_FLOW_ENABLED || !order.uiState?.baseerSharedDraftHydratedOnly || order.uiState?.baseerSharedDraftPending));
        if (drafts.length) this.addPendingOrder(drafts.map((order) => order.id));
        return super.afterProcessServerData(...arguments);
    },
    async setup() {
        await super.setup(...arguments);
        try { await refreshMissingAccountProofs(this); }
        catch { /* Missing proof remains blocked at payment; do not reset the cache. */ }
        const schedule = (order) => {
            if (!order?.uiState?.baseerOfflineDiscount || order.state !== "draft" || sharedStageOrders.has(order) || this._baseerOfflineRebuilding?.has(order.uuid)) return;
            this._baseerOfflineScheduled ||= new Map();
            if (this._baseerOfflineScheduled.has(order.uuid)) return;
            const ticket = {};
            this._baseerOfflineScheduled.set(order.uuid, ticket);
            queueMicrotask(() => {
                if (this._baseerOfflineScheduled.get(order.uuid) !== ticket) return;
                this._baseerOfflineScheduled.delete(order.uuid);
                refreshOfflineDiscount(this, order);
            });
        };
        this.models["pos.order.line"].addEventListener("create", ({ ids }) => {
            for (const id of ids) schedule(this.models["pos.order.line"].get(id)?.order_id);
        });
        this.models["pos.order.line"].addEventListener("update", ({ id, fields }) => {
            // Native setOrderPrices writes derived subtotals immediately before
            // snapshotting. Rebuilding the preview for those writes changes its
            // UUID after the snapshot even though the cashier changed nothing.
            const inputs = ['qty', 'price_unit', 'discount', 'tax_ids', 'product_id', 'price_type',
                'refunded_orderline_id', 'extra_tax_data', 'combo_line_ids', 'combo_parent_id', 'order_id'];
            if (Array.isArray(fields) && !fields.some((field) => inputs.includes(field))) return;
            schedule(this.models["pos.order.line"].get(id)?.order_id);
        });
        this.models["pos.order.line"].addEventListener("delete", () => {
            // Native delete events no longer contain the deleted parent. A
            // preview rebuild is internal bookkeeping; scheduling every other
            // order here makes two discounted orders rebuild one another forever.
            if (this._baseerOfflineRebuilding?.size) return;
            for (const order of this.models["pos.order"].getAll()) schedule(order);
        });
        this.models["pos.order"].addEventListener("update", ({ id, fields }) => {
            if (fields?.some((field) => ["pricelist_id", "fiscal_position_id"].includes(field))) schedule(this.models["pos.order"].get(id));
        });
        const prefix = discountStorageKey(session.db || "", this.config.id, "");
        for (const key of Object.keys(localStorage).filter((item) => item.startsWith(prefix))) {
            try { await executeDiscountIntent(this, JSON.parse(localStorage.getItem(key))); }
            catch { this.notification.add(pendingMessage(), { type: "warning", sticky: true }); }
        }
    },
    async baseerSubmitDiscount(order, request) {
        if (this._baseerDiscountRunning) return false;
        this._baseerDiscountRunning = true;
        this.env.services.ui.block();
        try {
            if (!request.refund && !order.baseer_global_discount_locked && !pendingDiscount(this, order)) {
                if (order.payment_ids?.length || this.paymentTerminalInProgress || order.electronicPaymentInProgress?.()) {
                    throw new Error(_t("Remove payment lines before changing the discount."));
                }
                if (this.baseerHasPendingProtectedAction(order) || !(await this.baseerResolvePendingKitchenAction(order))) {
                    throw new Error(_t("Confirm pending item or kitchen changes first."));
                }
                const prior = order.uiState.baseerOfflineDiscount;
                noteSharedDraftEdit(order);
                if (request.kind === "remove") {
                    for (const line of [...order.lines]) if (prior?.preview_line_uuids?.includes(line.uuid)) line.delete();
                    if (SHARED_DRAFT_FLOW_ENABLED && prior) {
                        for (const [key, ids] of [['baseerSharedDraftLineDeletions', prior.removed_line_ids], ['baseerSharedDraftPaymentDeletions', prior.removed_payment_ids]]) {
                            const events = order.uiState[key] ||= [];
                            for (const id of ids || []) if (!events.some((event) => event.id === id)) events.push({ id, token: crypto.randomUUID() });
                        }
                    }
                    delete order.uiState.baseerOfflineDiscount;
                    if (SHARED_DRAFT_FLOW_ENABLED && isManagedSharedDraft(order)) order.uiState.baseerSharedDraftRemoveRequested = true;
                    touchExperimentalDraftGraph(order);
                    order.triggerRecomputeAllPrices();
                    order._markDirty();
                } else {
                    if (!["fixed", "percent"].includes(request.kind) || !/^[0-9]+(?:\.[0-9]{1,2})?$/.test(request.value || "") || Number(request.value) <= 0) {
                        throw new Error(_t("Enter a positive number using 0-9 and at most two decimal places."));
                    }
                    order.baseerAssignAnonymousB2cPartner?.();
                    order.uiState.baseerOfflineDiscount = {
                        version: 1, order_uuid: order.uuid,
                        action_uuid: prior?.kind === request.kind && prior?.value === request.value ? prior.action_uuid : crypto.randomUUID(),
                        kind: request.kind, value: request.value,
                        account_proofs: Object.keys(prior?.account_proofs || {}).length ? prior.account_proofs : { ...(this.config.baseer_offline_discount_account_proofs || {}) },
                        preview_line_uuids: prior?.preview_line_uuids || [],
                        removed_line_ids: [...new Set([...(prior?.removed_line_ids || []), ...pendingDeletedIds(order, "lines")])],
                        removed_payment_ids: [...new Set([...(prior?.removed_payment_ids || []), ...pendingDeletedIds(order, "payment_ids")])],
                    };
                    if (SHARED_DRAFT_FLOW_ENABLED) delete order.uiState.baseerSharedDraftRemoveRequested;
                    touchExperimentalDraftGraph(order);
                    refreshOfflineDiscount(this, order);
                    if (order.uiState.baseerOfflineDiscount.error) throw new Error(order.uiState.baseerOfflineDiscount.error);
                }
                this.addPendingOrder([order.id]);
                await this.data.synchronizeLocalDataInIndexedDB();
                return order;
            }
            return await submitDiscount(this, order, request);
        } catch (error) {
            // A definite Odoo rejection cannot have committed this transaction.
            // Read canonical state before dropping its durable recovery intent.
            if (error?.data?.name?.startsWith("odoo.exceptions.")) {
                try {
                    const result = await this.data.call("pos.order", "baseer_read_global_discount_state", [[order.id]]);
                    await this.baseerReconcileProtectedState(result, order.uuid);
                    localStorage.removeItem(this.baseerDiscountKey(order));
                } catch { /* Keep the payment block when the read also fails. */ }
            }
            this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: error?.data?.message || error?.message || pendingMessage() });
            return false;
        } finally {
            this.env.services.ui.unblock();
            this._baseerDiscountRunning = false;
        }
    },
    async applyDiscount(percent, order = this.getOrder()) {
        // Historical native discounts keep their own native refund behavior,
        // even after the shop enables this new command for subsequent sales.
        if (isDiscountFrozen(order) || needsDiscountRefund(order) || order?.uiState?.baseerOfflineDiscount) return;
        return super.applyDiscount(...arguments);
    },
    async syncAllOrders(options = {}) {
        if (SHARED_DRAFT_FLOW_ENABLED) {
            const pending = this.getPendingOrder();
            const orders = options.orders || [...pending.orderToCreate, ...pending.orderToUpdate];
            const managed = orders.filter(isManagedSharedDraft);
            const ordinary = orders.filter((order) => !isManagedSharedDraft(order));
            if (managed.length) {
                const results = (ordinary.length ? await super.syncAllOrders({ ...options, orders: ordinary }) : []) || [];
                for (const order of managed) {
                    try {
                        // A revision check marks the order before its RPC is
                        // complete. Wait for the latest check, then apply all
                        // existing guards without changing the payment graph.
                        let checking;
                        while ((checking = sharedRevisionPromises.get(order))) await checking;
                        const conflict = _t('The shared order changed on another device. Keep your local changes for review.');
                        // A failed lookup is not a proven conflict. Once a
                        // frozen paid ACK exists, reconciliation validates it
                        // instead of retrying payment or keeping our own warning.
                        if (order.uiState.baseerSharedDraftPaidAckPending && order.uiState.baseerSharedDraftRevisionWarningProvisional === true &&
                            order.uiState.baseerSharedDraftRefreshError === conflict) {
                            delete order.uiState.baseerSharedDraftRefreshError;
                            clearProvisionalWarning(order);
                            sharedRevisionWarningOwners.delete(order);
                        }
                        const hadPending = Boolean(order.uiState.baseerSharedDraftPending);
                        const retryFrozen = order.uiState.baseerSharedDraftRefreshError === conflict && hadPending;
                        if (sharedRefreshOrders.has(order) || order.uiState.baseerSharedDraftContaminated || order.uiState.baseerSharedDraftRemoteDeleted || order.uiState.baseerSharedDraftHydrationError || (order.uiState.baseerSharedDraftRefreshError && !retryFrozen)) throw new Error('Shared draft requires review');
                        if (!order.uiState.baseerSharedDraftPaidAckPending) await this.baseerRunSharedDraftExperiment(order);
                        if (hadPending && !order.uiState.baseerSharedDraftPending && order.uiState.baseerSharedDraftRefreshError === conflict) delete order.uiState.baseerSharedDraftRefreshError;
                        if (order.uiState.baseerSharedDraftPaidAckPending) await this.baseerReconcileSharedPaidExperiment(order);
                        if (!order.uiState.baseerSharedDraftNeedsSync && !order.uiState.baseerSharedDraftPending &&
                            !order.uiState.baseerSharedDraftPaidAckPending && Number.isSafeInteger(order.uiState.baseerSharedDraftRevision)) {
                            if (order.state === 'draft') this.removePendingOrder(order);
                            results.push(order);
                        }
                    } catch (error) {
                        if (options.throw) throw error;
                        if (!(error instanceof ConnectionLostError)) this.notification.add(_t('A shared discount order needs manager review. Keep its local data.'), { type: 'danger', sticky: true });
                    }
                }
                return results;
            }
        }
        if (options.throw) return super.syncAllOrders(...arguments);
        const pending = this.getPendingOrder();
        const orders = options.orders || [...pending.orderToCreate, ...pending.orderToUpdate];
        const pendingOffline = orders.some(isPendingOfflineDiscount);
        if (!pendingOffline) return super.syncAllOrders(...arguments);
        try {
            // Native's silent RPC failure path reloads the server draft. Propagate
            // internally instead so locally collected payment is never overwritten.
            return await super.syncAllOrders({ ...options, throw: true });
        } catch (error) {
            if (!(error instanceof ConnectionLostError)) {
                this.notification.add(_t("An offline discount order needs manager review. Do not collect payment again."), { type: "danger", sticky: true });
            }
            return [];
        }
    },
    async preSyncAllOrders(orders) {
        for (const order of orders) {
            if (order.uiState?.baseerOfflineDiscount && order.state === "draft") refreshOfflineDiscount(this, order);
        }
        const prepared = await super.preSyncAllOrders(...arguments);
        for (const order of prepared || []) {
            const intent = order.uiState?.baseerOfflineDiscount;
            if (!intent || order.state !== "paid" || intent.retry_payload) continue;
            for (const line of order.lines || []) line._markDirty();
            for (const payment of order.payment_ids || []) payment._markDirty();
            // Freeze the *entire* first paid RPC payload. Odoo's dirty flags and
            // relationship commands can change when the response is lost or
            // the browser reloads; the server validates the exact retry bytes.
            intent.retry_payload = JSON.stringify(order.serializeForORM({ keepCommands: true }));
            try {
                if (!this.data.indexedDB) throw new Error("IndexedDB unavailable");
                protectOfflineStorage(this.data.indexedDB, order);
                await persistNativeOfflinePaidOrder(this.data, order);
            } catch (error) {
                // Do not send a paid request that cannot be retried exactly.
                delete intent.retry_payload;
                this.dialog.add(AlertDialog, { title: _t("Offline order needs review"), body: _t("The payment could not be saved on this device. Do not collect it again. Keep this screen open and ask a manager for help.") });
                throw error;
            }
        }
        return prepared;
    },
    async postSyncAllOrders(orders) {
        await super.postSyncAllOrders(...arguments);
        for (const order of orders) {
            const intent = order.uiState?.baseerOfflineDiscount;
            if (intent && order.state === "draft" && intent.sent_deletions) {
                for (const [key, sent] of [["removed_line_ids", intent.sent_deletions.lines], ["removed_payment_ids", intent.sent_deletions.payment_ids]]) {
                    const acknowledged = new Set(sent || []);
                    intent[key] = (intent[key] || []).filter((id) => !acknowledged.has(id));
                }
                delete intent.sent_deletions;
            }
            if (intent && order.baseer_global_discount_locked && ["paid", "done", "invoiced"].includes(order.state)) {
                for (const line of [...order.lines]) if (intent.preview_line_uuids.includes(line.uuid)) line.delete();
                delete order.uiState.baseerOfflineDiscount;
                this.data.indexedDB?._baseerOfflineProtection?.delete(order.uuid);
            }
        }
    },
    async addLineToOrder(vals, order, ...args) {
        if (isDiscountFrozen(order)) {
            explainFrozen(this);
            return false;
        }
        noteSharedDraftEdit(order);
        return super.addLineToOrder(vals, order, ...args);
    },
    async selectPartner(order = this.getOrder()) {
        if (isDiscountFrozen(order)) { explainFrozen(this); return false; }
        return super.selectPartner(...arguments);
    },
    setPartnerToCurrentOrder() {
        if (isDiscountFrozen(this.getOrder())) { explainFrozen(this); return; }
        return super.setPartnerToCurrentOrder(...arguments);
    },
    async selectPreset(preset = false, order = this.getOrder()) {
        if (isDiscountFrozen(order)) { explainFrozen(this); return false; }
        return super.selectPreset(...arguments);
    },
});

patch(ControlButtons.prototype, {
    async clickBaseerGlobalDiscount() {
        const order = this.pos.getOrder();
        if (pendingDiscount(this.pos, order)) return this.pos.baseerSubmitDiscount(order, {});
        const request = await makeAwaitable(this.dialog, BaseerGlobalDiscountDialog, {
            locked: Boolean(order.baseer_global_discount_locked || order.uiState?.baseerOfflineDiscount), refund: Boolean(order.is_refund),
        });
        if (request) await this.pos.baseerSubmitDiscount(order, request);
    },
    async clickDiscount() {
        const order = this.pos.getOrder();
        if (this.pos.config.baseer_global_discount_enabled || isDiscountFrozen(order)) return this.clickBaseerGlobalDiscount();
        return super.clickDiscount(...arguments);
    },
    async clickFiscalPosition() {
        if (isDiscountFrozen(this.currentOrder)) { explainFrozen(this.pos); return; }
        return super.clickFiscalPosition(...arguments);
    },
    async clickPricelist() {
        if (isDiscountFrozen(this.currentOrder)) { explainFrozen(this.pos); return; }
        return super.clickPricelist(...arguments);
    },
});

patch(PosOrder.prototype, {
    update(values, options = {}) {
        if ((paidReconciliationOrders.has(this) || sharedRemoteDeleteOrders.has(this)) && ['lines', 'payment_ids', 'state', 'partner_id', 'fiscal_position_id', 'pricelist_id', 'amount_total', 'amount_tax', 'amount_paid'].some((field) => Object.hasOwn(values, field))) {
            throw new Error('The paid order is being reconciled');
        }
        if (['lines', 'payment_ids', 'partner_id', 'fiscal_position_id', 'pricelist_id', 'preset_id'].some((field) => Object.hasOwn(values, field))) noteSharedDraftEdit(this);
        return super.update(values, options);
    },
    addPaymentline() {
        noteSharedDraftEdit(this);
        return super.addPaymentline(...arguments);
    },
    removePaymentline() {
        noteSharedDraftEdit(this);
        return super.removePaymentline(...arguments);
    },
    serializeForIndexedDB() {
        const data = super.serializeForIndexedDB(...arguments);
        const tracker = this.models?._baseerDraftGenerationTracker;
        if (SHARED_DRAFT_FLOW_ENABLED && tracker && isManagedSharedDraft(this)) {
            const state = data.JSONuiState ? JSON.parse(data.JSONuiState) : {};
            state.baseerSharedDraftGeneration = tracker.get();
            data.JSONuiState = JSON.stringify(state);
        }
        return data;
    },
    serializeForORM() {
        const key = discountStorageKey(session.db || "", this.config_id.id, this.uuid);
        if (localStorage.getItem(key)) throw new Error(pendingMessage());
        const intent = this.uiState?.baseerOfflineDiscount;
        if (intent?.error) throw new Error(intent.error);
        const data = super.serializeForORM(...arguments);
        if (intent || SHARED_DRAFT_FLOW_ENABLED && this.models?._baseerDraftGenerationTracker && isManagedSharedDraft(this)) {
            if (this.state === "paid" && intent?.retry_payload) return JSON.parse(intent.retry_payload);
            const sent = { lines: [], payment_ids: [] };
            for (const [field, saved, mappedEvents] of [["lines", intent?.removed_line_ids, this.uiState.baseerSharedDraftLineDeletions], ["payment_ids", intent?.removed_payment_ids, this.uiState.baseerSharedDraftPaymentDeletions]]) {
                const existing = new Set((data[field] || []).filter((command) => [2, 3].includes(command[0])).map((command) => command[1]));
                const records = field === "lines" ? this.lines : this.payment_ids;
                const linked = new Set(records.map((record) => record.id));
                if (this.models?._baseerDraftGenerationTracker) {
                    const ids = field === 'lines' ? this.uiState.baseerSharedDraftLineIds : this.uiState.baseerSharedDraftPaymentIds;
                    for (const record of records) if (ids?.[record.uuid]) linked.add(ids[record.uuid]);
                }
                const mapped = this.models?._baseerDraftGenerationTracker ? (mappedEvents || []).map((item) => item.id) : [];
                if (mapped.some((id) => linked.has(id))) throw new Error(_t('A deleted draft item was restored and needs manager review.'));
                for (const id of new Set([...(saved || []), ...mapped])) {
                    if (!existing.has(id) && !linked.has(id)) (data[field] ||= []).push([2, id]);
                    if (!linked.has(id)) sent[field].push(id);
                }
            }
            if (intent && arguments[0]?.keepCommands) intent.sent_deletions = sent;
            if (intent) data.baseer_offline_discount_intent = wireOfflineDiscount(intent);
        }
        return data;
    },
    get canBeRemovedFromIndexedDB() {
        if (SHARED_DRAFT_FLOW_ENABLED && this.uiState?.baseerSharedDraftInvoicePending) return false;
        if (SHARED_DRAFT_FLOW_ENABLED && this.uiState?.baseerSharedDraftPaidAckPending) return false;
        if (this.state === 'paid' && isPendingOfflineDiscount(this)) return false;
        return super.canBeRemovedFromIndexedDB;
    },
    get isUnsyncedPaid() {
        if (SHARED_DRAFT_FLOW_ENABLED && this.uiState?.baseerSharedDraftPaidAckPending) return true;
        if (this.state === 'paid' && isPendingOfflineDiscount(this)) return true;
        return super.isUnsyncedPaid;
    },
    removeOrderline(line) {
        if (isDiscountFrozen(this)) return false;
        noteSharedDraftEdit(this);
        return super.removeOrderline(...arguments);
    },
    setPartner(partner) {
        if (isDiscountFrozen(this) && partner !== this.partner_id) return;
        if (partner !== this.partner_id) noteSharedDraftEdit(this);
        return super.setPartner(...arguments);
    },
    setPricelist(pricelist) {
        if (isDiscountFrozen(this) && pricelist !== this.pricelist_id) return;
        if (pricelist !== this.pricelist_id) noteSharedDraftEdit(this);
        return super.setPricelist(...arguments);
    },
    setPreset() {
        if (isDiscountFrozen(this)) return;
        noteSharedDraftEdit(this);
        return super.setPreset(...arguments);
    },
});

patch(PosOrderline.prototype, {
    delete() {
        const order = this.order_id;
        if (paidReconciliationOrders.has(order) || sharedRemoteDeleteOrders.has(order)) throw new Error('The order is being reconciled');
        const intent = order?.uiState?.baseerOfflineDiscount;
        const id = this.id;
        const tracker = order?.models?._baseerDraftGenerationTracker;
        const mapped = tracker && typeof id !== 'number' && !this.baseer_global_discount_line && !intent?.preview_line_uuids?.includes(this.uuid)
            ? order.uiState.baseerSharedDraftLineIds?.[this.uuid] : undefined;
        const track = intent && order.state === "draft" && typeof id === "number" && !this.baseer_global_discount_line && !intent.preview_line_uuids.includes(this.uuid);
        const result = super.delete(...arguments);
        if (intent && order.state === 'draft' && Number.isSafeInteger(mapped) && mapped > 0) {
            order.uiState.baseerSharedDraftLineDeletions ||= [];
            order.uiState.baseerSharedDraftLineDeletions.push({ id: mapped, token: crypto.randomUUID() });
            touchExperimentalDraftGraph(order);
            order._markDirty();
        }
        if (track) {
            intent.removed_line_ids = [...new Set([...(intent.removed_line_ids || []), id])];
            if (tracker) {
                order.uiState.baseerSharedDraftLineDeletions ||= [];
                order.uiState.baseerSharedDraftLineDeletions.push({ id, token: crypto.randomUUID() });
            }
            touchExperimentalDraftGraph(order);
            order._markDirty();
        }
        return result;
    },
    get isDiscountLine() {
        if (this.order_id?.uiState?.baseerOfflineDiscount?.preview_line_uuids?.includes(this.uuid)) return true;
        return super.isDiscountLine;
    },
    prepareBaseLineForTaxesComputationExtraValues() {
        const values = super.prepareBaseLineForTaxesComputationExtraValues(...arguments);
        if (this.order_id?.uiState?.baseerOfflineDiscount?.preview_line_uuids?.includes(this.uuid)) {
            // Preview tax IDs are already mapped by Odoo's source tax engine.
            values.tax_ids = this.tax_ids;
        }
        return values;
    },
    update(values, options = {}) {
        if ((paidReconciliationOrders.has(this.order_id) || sharedRemoteDeleteOrders.has(this.order_id)) && ['qty', 'price_unit', 'discount', 'tax_ids', 'product_id', 'order_id'].some((field) => Object.hasOwn(values, field))) {
            throw new Error('The paid order is being reconciled');
        }
        if (!this.baseer_global_discount_line && !this.order_id?.uiState?.baseerOfflineDiscount?.preview_line_uuids?.includes(this.uuid) &&
            ['qty', 'price_unit', 'discount', 'tax_ids', 'product_id'].some((field) => Object.hasOwn(values, field))) noteSharedDraftEdit(this.order_id);
        const source = this.refunded_orderline_id;
        if (source?.order_id?.baseer_global_discount_locked && source.combo_line_ids?.length
                && this.order_id?.is_refund && values.combo_line_ids) {
            // Native refund reconstruction includes every historical return
            // child. Link only this return's children before inverse relations
            // can move a previously posted/frozen line to another parent.
            values = { ...values, combo_line_ids: values.combo_line_ids.map((command) =>
                command[0] === "link" ? ["link", ...command.slice(1).filter((child) =>
                    child.order_id === this.order_id
                    && child.refunded_orderline_id?.combo_parent_id === source
                )] : command
            ) };
        }
        return super.update(values, options);
    },
    setQuantity(quantity) {
        if (isDiscountFrozen(this.order_id) && quantity !== this.qty) return false;
        if (quantity !== this.qty) noteSharedDraftEdit(this.order_id);
        return super.setQuantity(...arguments);
    },
    setUnitPrice(price) {
        if (isDiscountFrozen(this.order_id) && price !== this.price_unit) return;
        if (price !== this.price_unit) noteSharedDraftEdit(this.order_id);
        return super.setUnitPrice(...arguments);
    },
    setDiscount(discount) {
        if (isDiscountFrozen(this.order_id) && discount !== this.discount) return;
        if (discount !== this.discount) noteSharedDraftEdit(this.order_id);
        return super.setDiscount(...arguments);
    },
});

patch(PosPayment.prototype, {
    update(values, options = {}) {
        if (paidReconciliationOrders.has(this.pos_order_id) || sharedRemoteDeleteOrders.has(this.pos_order_id)) throw new Error('The order is being reconciled');
        noteSharedDraftEdit(this.pos_order_id);
        return super.update(values, options);
    },
    delete() {
        const order = this.pos_order_id;
        if (paidReconciliationOrders.has(order) || sharedRemoteDeleteOrders.has(order)) throw new Error('The order is being reconciled');
        const intent = order?.uiState?.baseerOfflineDiscount;
        const id = this.id;
        const tracker = order?.models?._baseerDraftGenerationTracker;
        const mapped = tracker && typeof id !== 'number' ? order.uiState.baseerSharedDraftPaymentIds?.[this.uuid] : undefined;
        const track = intent && order.state === "draft" && typeof id === "number";
        const result = super.delete(...arguments);
        if (intent && order.state === 'draft' && Number.isSafeInteger(mapped) && mapped > 0) {
            order.uiState.baseerSharedDraftPaymentDeletions ||= [];
            order.uiState.baseerSharedDraftPaymentDeletions.push({ id: mapped, token: crypto.randomUUID() });
            touchExperimentalDraftGraph(order);
            order._markDirty();
        }
        if (track) {
            intent.removed_payment_ids = [...new Set([...(intent.removed_payment_ids || []), id])];
            if (tracker) {
                order.uiState.baseerSharedDraftPaymentDeletions ||= [];
                order.uiState.baseerSharedDraftPaymentDeletions.push({ id, token: crypto.randomUUID() });
            }
            touchExperimentalDraftGraph(order);
            order._markDirty();
        }
        return result;
    },
});

patch(TicketScreen.prototype, {
    _onUpdateSelectedOrderline() {
        const line = this.getSelectedOrder()?.lines.find((item) => item.id === this.getSelectedOrderlineId());
        if (line?.baseer_global_discount_line) {
            this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: _t("Select the original item to refund. Its discount is included automatically.") });
            return;
        }
        return super._onUpdateSelectedOrderline(...arguments);
    },
    _getRefundableDetails() {
        return super._getRefundableDetails(...arguments).filter((detail) => !detail.line.baseer_global_discount_line);
    },
    async addAdditionalRefundInfo(original, destination) {
        await super.addAdditionalRefundInfo(...arguments);
        if (original.baseer_global_discount_locked) {
            const prepared = await this.pos.baseerSubmitDiscount(destination, { refund: true });
            if (!prepared) throw new Error(pendingMessage());
        }
    },
});

patch(OrderSummary.prototype, {
    async updateSelectedOrderline() {
        if (isDiscountFrozen(this.currentOrder)) { this.numberBuffer.reset(); explainFrozen(this.pos); return; }
        return super.updateSelectedOrderline(...arguments);
    },
    _setValue() {
        if (isDiscountFrozen(this.currentOrder)) { this.numberBuffer.reset(); explainFrozen(this.pos); return; }
        return super._setValue(...arguments);
    },
});

patch(PaymentScreen.prototype, {
    async validateOrder() {
        const order = this.currentOrder;
        if (SHARED_DRAFT_FLOW_ENABLED && sharedRefreshOrders.has(order)) {
            this.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: _t('The shared order could not be refreshed. Keep its local copy for review.') });
            return;
        }
        if (SHARED_DRAFT_FLOW_ENABLED && isManagedSharedDraft(order)) {
            try { if (!await this.pos.baseerSettleSharedDraftBeforePaymentExperiment(order)) throw new Error('The pending draft was not acknowledged'); }
            catch { this.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: order.uiState?.baseerSharedDraftRefreshError || pendingMessage() }); return; }
            try { if (!await this.pos.baseerCheckRestoredSharedDraftExperiment(order)) throw new Error('Remote deletion requires review'); }
            catch (error) { this.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: order.uiState?.baseerSharedDraftRefreshError || _t('The shared order could not be verified. Keep this copy and ask a manager to review it.') }); return; }
        }
        if (SHARED_DRAFT_FLOW_ENABLED && sharedRefreshOrders.has(order)) {
            this.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: _t('The shared order could not be refreshed. Keep its local copy for review.') }); return;
        }
        if (SHARED_DRAFT_FLOW_ENABLED && (order.uiState?.baseerSharedDraftCancelPending || order.uiState?.baseerSharedDraftCancelAcknowledged)) {
            this.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: _t('This draft cancellation needs manager review before payment.') });
            return;
        }
        if (order.uiState?.baseerSharedDraftContaminated || order.uiState?.baseerSharedDraftHydrationError || order.uiState?.baseerSharedDraftRefreshError) {
            this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: order.uiState.baseerSharedDraftHydrationError || order.uiState.baseerSharedDraftRefreshError || _t('The shared order could not be refreshed. Keep its local copy for review.') });
            return;
        }
        if (order.uiState?.baseerOfflineDiscount) {
            refreshOfflineDiscount(this.pos, order);
            if (order.uiState.baseerOfflineDiscount.error) {
                this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: order.uiState.baseerOfflineDiscount.error });
                return;
            }
        }
        if (this.pos._baseerDiscountRunning || pendingDiscount(this.pos, order)
            || (needsDiscountRefund(order) && !order.baseer_global_discount_locked)) {
            this.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: pendingMessage() });
            return;
        }
        return super.validateOrder(...arguments);
    },
});

patch(OrderPaymentValidation.prototype, {
    shouldDownloadInvoice() {
        if (SHARED_DRAFT_FLOW_ENABLED && (this.order.uiState?.baseerSharedDraftPaidAckPending || this.order.uiState?.baseerSharedDraftInvoicePending)) return false;
        return super.shouldDownloadInvoice(...arguments);
    },
    get canPrintReceipt() {
        if (SHARED_DRAFT_FLOW_ENABLED && (this.order.uiState?.baseerSharedDraftPaidAckPending || this.order.uiState?.baseerSharedDraftInvoicePending)) return false;
        return super.canPrintReceipt;
    },
    async validateOrder() {
        if (SHARED_DRAFT_FLOW_ENABLED && sharedRefreshOrders.has(this.order)) {
            this.pos.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: _t('The shared order could not be refreshed. Keep its local copy for review.') });
            return false;
        }
        if (SHARED_DRAFT_FLOW_ENABLED && isManagedSharedDraft(this.order)) {
            try { if (!await this.pos.baseerSettleSharedDraftBeforePaymentExperiment(this.order)) throw new Error('The pending draft was not acknowledged'); }
            catch { this.pos.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: this.order.uiState?.baseerSharedDraftRefreshError || pendingMessage() }); return false; }
            try { if (!await this.pos.baseerCheckRestoredSharedDraftExperiment(this.order)) throw new Error('Remote deletion requires review'); }
            catch (error) { this.pos.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: this.order.uiState?.baseerSharedDraftRefreshError || _t('The shared order could not be verified. Keep this copy and ask a manager to review it.') }); return false; }
        }
        if (SHARED_DRAFT_FLOW_ENABLED && sharedRefreshOrders.has(this.order)) {
            this.pos.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: _t('The shared order could not be refreshed. Keep its local copy for review.') }); return false;
        }
        if (SHARED_DRAFT_FLOW_ENABLED && (this.order.uiState?.baseerSharedDraftCancelPending || this.order.uiState?.baseerSharedDraftCancelAcknowledged)) {
            this.pos.dialog.add(AlertDialog, { title: _t('Invoice discount'), body: _t('This draft cancellation needs manager review before payment.') });
            return false;
        }
        if (this.order.uiState?.baseerSharedDraftContaminated || this.order.uiState?.baseerSharedDraftHydrationError || this.order.uiState?.baseerSharedDraftRefreshError) {
            this.pos.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: this.order.uiState.baseerSharedDraftHydrationError || this.order.uiState.baseerSharedDraftRefreshError || _t('The shared order could not be refreshed. Keep its local copy for review.') });
            return false;
        }
        if (this.order.uiState?.baseerOfflineDiscount) {
            refreshOfflineDiscount(this.pos, this.order);
            if (this.order.uiState.baseerOfflineDiscount.error) {
                this.pos.dialog.add(AlertDialog, { title: _t("Invoice discount"), body: this.order.uiState.baseerOfflineDiscount.error });
                return false;
            }
        }
        return super.validateOrder(...arguments);
    },
    async handleValidationError(error) {
        if (this.order.uiState?.baseerOfflineDiscount && (error instanceof ConnectionLostError || error instanceof RPCError)) {
            this.order.state = "paid";
            this.pos.addPendingOrder([this.order.id]);
            try {
                if (!this.pos.data.indexedDB) throw new Error("IndexedDB unavailable");
                protectOfflineStorage(this.pos.data.indexedDB, this.order);
                await persistNativeOfflinePaidOrder(this.pos.data, this.order);
            } catch (storageError) {
                this.pos.dialog.add(AlertDialog, { title: _t("Offline order needs review"), body: _t("The payment could not be saved on this device. Do not collect it again. Keep this screen open and ask a manager for help.") });
                throw storageError;
            }
            if (error instanceof RPCError) {
                this.pos.dialog.add(AlertDialog, { title: _t("Offline order needs review"), body: _t("Payment is recorded locally. Do not collect it again. Ask a manager to review the synchronization error.") });
                return error;
            }
            await this.afterOrderValidation();
            return error;
        }
        return super.handleValidationError(...arguments);
    },
    async shouldHideValidationBehindFeedbackScreen() {
        if (!this.order.uiState?.baseerOfflineDiscount || this.nextPage.page !== "FeedbackScreen") {
            return super.shouldHideValidationBehindFeedbackScreen(...arguments);
        }
        const nextPage = this.nextPage;
        this.pos.env.services.ui.block();
        try {
            const result = await this.finalizeValidation();
            if (result instanceof RPCError) return false;
        } finally { this.pos.env.services.ui.unblock(); }
        this.pos.navigate(nextPage.page, nextPage.params);
    },
});

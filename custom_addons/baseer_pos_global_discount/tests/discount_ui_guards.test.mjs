import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const memory = new Map();
globalThis.localStorage = {
    getItem: (key) => memory.get(key) ?? null,
    setItem: (key, val) => memory.set(key, val),
    removeItem: (key) => memory.delete(key),
};
const source = readFileSync(new URL("../static/src/app/global_discount.js", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "").replace("export class", "class")
    .replace('const SHARED_DRAFT_FLOW_ENABLED = true;', 'const SHARED_DRAFT_FLOW_ENABLED = false;');
const mocks = `
const extensions = new Map();
const patch = (target, extension) => { Object.setPrototypeOf(extension, target); extensions.set(target.constructor.name, extension); };
const _t = (value) => value; const session = { db: 'qa' };
const odoo = { pos_config_id: 2, pos_session_id: 27, last_data_change: '2026-11-24 12:00:00' };
const luxon = { DateTime: { fromSQL: (text) => Date.parse(text) } };
const discountStorageKey = (db, config, uuid) => [db, config, uuid].join(':');
const pendingDiscount = (pos, order) => localStorage.getItem(pos.baseerDiscountKey(order));
const needsDiscountRefund = (order) => order.needsRefund;
const cancelGraphUnchanged = (order, pending, tracker) => tracker.get() === pending.generation;
const cancelGraphFingerprint = () => 'test-graph';
const useState = (value) => value;
const useAutofocus = () => {};
class Component {} class Dialog {} class AlertDialog {} class ConfirmationDialog {};
const ask = async () => globalThis.baseerTestConfirm;
class ControlButtons { clickDiscount() { this.nativeDiscount = true; } clickFiscalPosition() { this.nativeCalled = true; } }
class PosStore { async reloadData() { this.nativeReload = true; } applyDiscount() { this.nativeCalled = true; } async beforeDeleteOrder() { this.nativeBeforeDelete = true; return true; } async deleteOrders() { this.nativeDeleted = true; return true; } async afterProcessServerData() { return this.nativeStartup(); } async syncAllOrders(options) { return this.nativeSync(options); } async preSyncAllOrders(orders) { return orders; } async postSyncAllOrders() {} }
class PosOrder { update(values) { this.nativeValues = values; } addPaymentline() { this.nativeCalled = true; } removePaymentline() { this.nativeCalled = true; } removeOrderline() { this.nativeCalled = true; } serializeForIndexedDB() { return { JSONuiState: JSON.stringify(this.uiState) }; } serializeForORM() {
    const commands = (items) => (items || []).filter((item) => item._dirty || typeof item.id !== 'number')
        .map((item) => [typeof item.id === 'number' ? 1 : 0, typeof item.id === 'number' ? item.id : 0, { uuid: item.uuid, value: item.value }]);
    return { uuid: this.uuid, lines: commands(this.lines), payment_ids: commands(this.payment_ids) };
} }
class PosOrderline {
    setQuantity() { this.nativeCalled = true; }
    update(values) { this.updated = values; return values; }
    delete() { this.nativeDeleted = true; return true; }
    prepareBaseLineForTaxesComputationExtraValues() { return { tax_ids: ["mapped-again"] }; }
}
class PosPayment { delete() { this.nativeDeleted = true; return true; } }
class OrderSummary { updateSelectedOrderline() { this.nativeCalled = true; } }
class OrderPaymentValidation { handleValidationError() { this.nativeCalled = true; } }
class ConnectionLostError extends Error {} class RPCError extends Error {}
let pingError; const rpc = async () => { if (pingError) throw pingError; };
class PosData { async checkAndDeleteMissingOrders(results) { if (this.failure) throw this.failure; this.forwarded = results; return results; } async loadInitialData() { return this.loadNative ? this.loadNative() : { native: true }; } async resetIndexedDB() { this.resetCalled = true; } async missingRecursive() { return { native: true }; } async getLocalDataFromIndexedDB() { return this.localResult; } }
class IndexedDB { delete(store, keys) { return { store, keys }; } }
class DevicesSynchronisation { async processDynamicRecords(records) { this.forwarded = records; return records; } processDeletedRecords(records) { this.forwarded = records; return records; } }
const refreshOfflineDiscount = () => {}; const wireOfflineDiscount = (intent) => intent;
const persistNativeOfflinePaidOrder = async (data) => data.synchronizeLocalDataInIndexedDB();
class TicketScreen {
    _getRefundableDetails() { return this.details; }
    _onUpdateSelectedOrderline() { this.nativeCalled = true; }
}
class PaymentScreen { validateOrder() { this.nativeCalled = true; } }
`;
const load = new Function(`${mocks}\n${source}\nreturn { extensions, BaseerGlobalDiscountDialog, ConnectionLostError, RPCError, setPingError: (value) => { pingError = value; } };`);
const { extensions, BaseerGlobalDiscountDialog, ConnectionLostError, RPCError, setPingError } = load();
let experimentalGeneration = 1;
const experimentalExtensions = new Function('attachDraftGenerationExperiment', 'hydrateSharedDraftExperiment', 'calculateOfflineDiscount', 'accountTaxHelpers', 'persistDraftGraphExperiment', 'stageNativeServerGraphExperiment',
    `${mocks}\n${source.replace('const SHARED_DRAFT_FLOW_ENABLED = false;', 'const SHARED_DRAFT_FLOW_ENABLED = true;')}\nreturn extensions;`)(
    () => ({ get: () => experimentalGeneration, touch: () => { experimentalGeneration++; } }),
    ({ order }) => { order.uiState.baseerOfflineDiscount = { preview_line_uuids: [] }; }, () => {}, {}, async ({ capture }) => capture(),
    ({ order, response, beforeLoad, verify }) => { beforeLoad(order); Object.assign(order, response['pos.order'][0]); verify(order); return { rollback() {} }; });
test('two discounted drafts do not schedule one another forever when preview lines are rebuilt', async () => {
    const tasks = [];
    const instrumentedMocks = mocks.replace('class PosStore {', 'class PosStore { async setup() {}')
        .replace('const refreshOfflineDiscount = () => {};', `const refreshOfflineDiscount = (pos, order) => {
            pos._baseerOfflineRebuilding ||= new Set(); pos._baseerOfflineRebuilding.add(order.uuid);
            pos.runs.push(order.uuid); pos.deleteListener(); pos._baseerOfflineRebuilding.delete(order.uuid);
        };`);
    const install = (code) => new Function('queueMicrotask', `${instrumentedMocks}\n${code}\nreturn extensions;`)((task) => tasks.push(task));
    const installed = install(source);
    const orders = ['one', 'two'].map((uuid) => ({ uuid, state: 'draft', uiState: { baseerOfflineDiscount: {} } }));
    const pos = { runs: [], config: { id: 2 }, models: {
        'pos.order': { getAll: () => orders, addEventListener() {} },
        'pos.order.line': { addEventListener(event, callback) { if (event === 'delete') pos.deleteListener = callback; } },
    } };
    await installed.get('PosStore').setup.call(pos);
    pos.deleteListener();
    for (let i = 0; tasks.length && i < 12; i++) tasks.shift()();
    assert.deepEqual(pos.runs, ['one', 'two']);
    assert.equal(tasks.length, 0);
    const old = install(source.replace('if (this._baseerOfflineRebuilding?.size) return;', ''));
    pos.runs = [];
    await old.get('PosStore').setup.call(pos);
    pos.deleteListener();
    for (let i = 0; tasks.length && i < 12; i++) tasks.shift()();
    assert.ok(tasks.length > 0, 'the previous listener continually schedules another draft');
});
test('native subtotal writes do not rebuild a frozen discount but cashier price edits do', async () => {
    const tasks = [];
    const instrumentedMocks = mocks.replace('class PosStore {', 'class PosStore { async setup() {}')
        .replace('const refreshOfflineDiscount = () => {};', 'const refreshOfflineDiscount = (pos) => { pos.runs++; };');
    const installed = new Function('queueMicrotask', `${instrumentedMocks}\n${source}\nreturn extensions;`)((task) => tasks.push(task));
    const order = { uuid: 'order', state: 'draft', uiState: { baseerOfflineDiscount: {} } };
    const pos = { runs: 0, config: { id: 2 }, models: {
        'pos.order': { getAll: () => [order], addEventListener() {} },
        'pos.order.line': { get: () => ({ order_id: order }), addEventListener(event, callback) { if (event === 'update') pos.onUpdate = callback; } },
    } };
    await installed.get('PosStore').setup.call(pos);
    pos.onUpdate({ id: 1, fields: ['price_subtotal', 'price_subtotal_incl'] });
    assert.equal(tasks.length, 0);
    pos.onUpdate({ id: 1, fields: ['qty'] });
    assert.equal(tasks.length, 1);
    tasks.shift()();
    assert.equal(pos.runs, 1);
});
test('server staging cancels stale preview work while later cashier edits still rebuild', async () => {
    const tasks = [];
    const instrumentedMocks = mocks.replace('class PosStore {', 'class PosStore { async setup() {}')
        .replace('const refreshOfflineDiscount = () => {};', 'const refreshOfflineDiscount = (pos) => { pos.runs++; };');
    const { extensions: installed, sharedStageOrders } = new Function('queueMicrotask', `${instrumentedMocks}\n${source}\nreturn { extensions, sharedStageOrders };`)((task) => tasks.push(task));
    const order = { uuid: 'order', state: 'draft', uiState: { baseerOfflineDiscount: {} } };
    const pos = { runs: 0, config: { id: 2 }, models: {
        'pos.order': { getAll: () => [order], addEventListener() {} },
        'pos.order.line': { get: () => ({ order_id: order }), addEventListener(event, callback) { pos[event] = callback; } },
    } };
    await installed.get('PosStore').setup.call(pos);
    pos.update({ id: 1, fields: ['qty'] });
    pos._baseerOfflineScheduled.delete(order.uuid); // The fresh stage supersedes old work.
    sharedStageOrders.add(order);
    pos.create({ ids: [1] });
    sharedStageOrders.delete(order);
    assert.equal(tasks.length, 1);
    pos.update({ id: 1, fields: ['price_unit'] });
    assert.equal(tasks.length, 2);
    tasks.shift()(); // The old ticket must not consume the later cashier edit.
    assert.equal(pos.runs, 0);
    tasks.shift()();
    assert.equal(pos.runs, 1);
});
test('opening an unchanged server draft does not queue a new revision', async () => {
    const remote = { uuid: 'remote', id: 42, state: 'draft', baseer_offline_draft_kind: 'fixed', uiState: {} };
    const local = { uuid: 'local', id: 43, state: 'draft', uiState: { baseerOfflineDiscount: {} } };
    const restored = { uuid: 'restored', id: 44, state: 'draft', uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: true } };
    let queued;
    const pos = { models: { 'pos.order': { getAll: () => [remote, local, restored] } }, addPendingOrder: (ids) => { queued = ids; },
        nativeStartup: async () => 'native' };
    assert.equal(await experimentalExtensions.get('PosStore').afterProcessServerData.call(pos), 'native');
    assert.deepEqual(queued, [43]);
    assert.ok(remote.uiState.baseerOfflineDiscount);
    let touches = 0;
    restored.models = { _baseerDraftGenerationTracker: { touch: () => { touches++; } } };
    experimentalExtensions.get('PosOrderline').setQuantity.call({ order_id: restored, qty: 1 }, 2);
    assert.equal(restored.uiState.baseerSharedDraftHydratedOnly, false);
    assert.equal(touches, 1);
    restored.uiState.baseerSharedDraftHydratedOnly = true;
    experimentalExtensions.get('PosOrder').update.call(restored, { partner_id: 7 });
    assert.equal(restored.uiState.baseerSharedDraftHydratedOnly, false);
    restored.uiState.baseerSharedDraftHydratedOnly = true;
    experimentalExtensions.get('PosOrder').addPaymentline.call(restored);
    assert.equal(restored.uiState.baseerSharedDraftHydratedOnly, false);
});
test('startup repairs a clean contaminated draft and blocks a locally edited one', async () => {
    const make = (uuid, clean) => ({ uuid, id: uuid === 'clean' ? 42 : 43, state: 'draft', lines: [{ uuid: 'food' },
        { uuid: 'preview' }, { id: 22, uuid: 'allowance', baseer_global_discount_line: true }], payment_ids: [],
        uiState: { baseerOfflineDiscount: { preview_line_uuids: ['preview'] }, baseerSharedDraftHydratedOnly: clean } });
    const clean = make('clean', true), dirty = make('dirty', false);
    const store = { models: { 'pos.order': { getAll: () => [clean, dirty] } }, data: { network: { offline: false } },
        async baseerRefreshCleanSharedDraftExperiment(order) { order.lines = order.lines.filter((line) => !line.baseer_global_discount_line); delete order.uiState.baseerSharedDraftContaminated; },
        addPendingOrder() {}, nativeStartup: async () => true };
    await experimentalExtensions.get('PosStore').afterProcessServerData.call(store);
    assert.deepEqual(clean.lines.map((line) => line.uuid), ['food', 'preview']);
    assert.equal(clean.uiState.baseerSharedDraftContaminated, undefined);
    assert.equal(dirty.uiState.baseerSharedDraftContaminated, true);
    assert.equal(dirty.lines.length, 3);
});
test('experimental native order serialization persists the latest edit generation for restart', () => {
    const order = { state: 'draft', uiState: { baseerOfflineDiscount: {}, baseerSharedDraftPending: { generation: 3 } },
        models: { _baseerDraftGenerationTracker: { get: () => 8 } } };
    const saved = experimentalExtensions.get('PosOrder').serializeForIndexedDB.call(order);
    const state = JSON.parse(saved.JSONuiState);
    assert.equal(state.baseerSharedDraftPending.generation, 3);
    assert.equal(state.baseerSharedDraftGeneration, 8);
    assert.equal(order.uiState.baseerSharedDraftGeneration, undefined);
});
test('device sync refreshes only clean hydrated shared drafts and never loads stale deltas over local copies', async () => {
    const clean = { id: 42, uuid: 'clean', state: 'draft', lines: [], payment_ids: [], uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: true } };
    const edited = { id: 43, uuid: 'edited', state: 'draft', lines: [], payment_ids: [], uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: false } };
    const refreshed = [];
    const device = { models: { 'pos.order': { getAll: () => [clean, edited] } },
        pos: { baseerRefreshCleanSharedDraftExperiment: async (order) => { refreshed.push(order.uuid); }, notification: { add() {} } } };
    const records = { 'pos.order': [{ id: 42, uuid: 'clean' }, { id: 43, uuid: 'edited' }, { id: 44, uuid: 'ordinary' }] };
    await experimentalExtensions.get('DevicesSynchronisation').processDynamicRecords.call(device, records);
    assert.deepEqual(refreshed, ['clean']);
    assert.deepEqual(device.forwarded['pos.order'].map((record) => record.id), [44]);
});
test('Orders loading refreshes a clean shared draft without mixing server allowances into its preview', async () => {
    const local = { id: 42, uuid: 'shared', state: 'draft', lines: [{ id: 11, uuid: 'food' }, { id: 'preview', uuid: 'preview' }], payment_ids: [],
        uiState: { baseerOfflineDiscount: { preview_line_uuids: ['preview'] }, baseerSharedDraftHydratedOnly: true, baseerSharedDraftRevision: 1 } };
    const response = { 'pos.order': [{ id: 42, uuid: 'shared', baseer_offline_draft_revision: 2 }],
        'pos.order.line': [{ id: 11, uuid: 'food', order_id: 42 }, { id: 22, uuid: 'server-allowance', order_id: 42, baseer_global_discount_line: true }], 'pos.payment': [] };
    let connected;
    const models = { 'pos.order': { getAll: () => [local] }, 'pos.config': { get: () => ({}) }, 'pos.session': { get: () => ({}) },
        connectNewData(data) { connected = data; return { 'pos.order': [] }; } };
    const service = { models, execute: async () => response, missingRecursive: async (value) => value, synchronizeServerDataInIndexedDB() {},
        deviceSync: { pos: { async baseerRefreshCleanSharedDraftExperiment(order) { order.lines = [{ id: 11, uuid: 'food' }, { id: 12, uuid: 'new-food' }, { id: 'new-preview', uuid: 'new-preview' }]; } } } };
    assert.deepEqual(await experimentalExtensions.get('PosData').loadServerOrders.call(service, []), [local]);
    assert.deepEqual(connected['pos.order'], []);
    assert.deepEqual(connected['pos.order.line'], []);
    assert.deepEqual(local.lines.map((line) => line.uuid), ['food', 'new-food', 'new-preview']);
    local.uiState.baseerSharedDraftHydratedOnly = false;
    local.lines.push({ uuid: 'local-edit' });
    await experimentalExtensions.get('PosData').loadServerOrders.call(service, []);
    assert.ok(local.lines.some((line) => line.uuid === 'local-edit'));
    assert.match(local.uiState.baseerSharedDraftRefreshError, /changed on another device/);
});
test('Orders loading rejects missing, older or wrong-UUID server identity without replacing local edits', async () => {
    for (const bad of [{ id: 42, uuid: 'shared' }, { id: 42, uuid: 'shared', baseer_offline_draft_revision: 1 },
        { id: 42, uuid: 'different', baseer_offline_draft_revision: 2 }]) {
        const local = { id: 42, uuid: 'shared', state: 'draft', lines: [{ id: 11, uuid: 'food', qty: 2 }], payment_ids: [],
            uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: false, baseerSharedDraftRevision: 2 } };
        let connected, refreshed = false;
        const models = { 'pos.order': { getAll: () => [local] }, 'pos.config': { get: () => ({}) }, 'pos.session': { get: () => ({}) },
            connectNewData(data) { connected = data; return { 'pos.order': [] }; } };
        const service = { models, execute: async () => ({ 'pos.order': [bad], 'pos.order.line': [{ id: 99, uuid: 'server', order_id: 42 }] }),
            missingRecursive: async (value) => value, synchronizeServerDataInIndexedDB() {},
            deviceSync: { pos: { async baseerRefreshCleanSharedDraftExperiment() { refreshed = true; } } } };
        await experimentalExtensions.get('PosData').loadServerOrders.call(service, []);
        assert.equal(refreshed, false);
        assert.deepEqual(connected['pos.order'], []);
        assert.deepEqual(connected['pos.order.line'], []);
        assert.equal(local.lines[0].qty, 2);
        assert.match(local.uiState.baseerSharedDraftRefreshError, /could not be refreshed/);
    }
});
test('device sync detects changed and deleted children through a UUID draft server ID map', async () => {
    const order = { id: 'order', uuid: 'order', state: 'draft', lines: [{ id: 'food', uuid: 'food' }], payment_ids: [{ id: 'cash', uuid: 'cash' }],
        uiState: { baseerOfflineDiscount: {}, baseerSharedDraftRevision: 1, baseerSharedDraftServerOrderId: 260,
            baseerSharedDraftLineIds: { food: 634 }, baseerSharedDraftPaymentIds: { cash: 70 } } };
    const checked = [];
    const device = { models: { 'pos.order': { getAll: () => [order] } }, pos: {
        baseerRefreshCleanSharedDraftExperiment: async () => {},
        baseerVerifyIncomingSharedRevisionExperiment: async (_order, id) => { checked.push(id); },
        baseerAcceptRemoteSharedDeletionExperiment: async () => {}, notification: { add() {} },
    } };
    await experimentalExtensions.get('DevicesSynchronisation').processDynamicRecords.call(device,
        { 'pos.order.line': [{ id: 634, uuid: 'food', order_id: 260 }] });
    assert.deepEqual(checked, [260]);
    assert.deepEqual(device.forwarded['pos.order.line'], []);
    experimentalExtensions.get('DevicesSynchronisation').processDeletedRecords.call(device, { 'pos.order.line': [634], 'pos.payment': [70] });
    assert.deepEqual(checked, [260, 260]);
    assert.deepEqual(device.forwarded['pos.order.line'], []);
    assert.deepEqual(device.forwarded['pos.payment'], []);
});
test('newer shared server revision blocks payment and preserves local edit', async () => {
    const order = { id: 'order', uuid: 'order', state: 'draft', uiState: { baseerOfflineDiscount: {}, baseerSharedDraftRevision: 1 }, lines: [{ qty: 2 }] };
    const store = { data: { orm: { call: async () => ({ 'pos.order': [{ id: 260, uuid: 'order', state: 'draft', baseer_offline_draft_revision: 2 }] }) } } };
    assert.equal(await experimentalExtensions.get('PosStore').baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 260), false);
    assert.match(order.uiState.baseerSharedDraftRefreshError, /changed on another device/);
    assert.equal(order.lines[0].qty, 2);
});
test('removed discount and confirmed card waits for matching revision without losing the payment', async () => {
    let release;
    const response = new Promise((resolve) => { release = resolve; });
    const order = { id: 42, uuid: 'removed-discount', state: 'paid', baseer_offline_draft_revision: 3,
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true },
        lines: [{ uuid: 'food', qty: 1 }], payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
    let sent = false;
    const store = { data: { orm: { call: async () => response } },
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} }, removePendingOrder() {},
        async baseerRunSharedDraftExperiment() { sent = true; } };
    const verifying = experimentalExtensions.get('PosStore').baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
    const syncing = experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [order], throw: true });
    await Promise.resolve();
    assert.equal(sent, false);
    assert.deepEqual(order.payment_ids, [{ uuid: 'bank', amount: 3, payment_status: 'done' }]);
    release({ 'pos.order': [{ id: 42, uuid: order.uuid, state: 'draft', baseer_offline_draft_revision: 3 }] });
    assert.equal(await verifying, true);
    assert.deepEqual(await syncing, [order]); assert.equal(sent, true);
    assert.equal(order.uiState.baseerSharedDraftRefreshError, undefined);
    assert.deepEqual(order.payment_ids, [{ uuid: 'bank', amount: 3, payment_status: 'done' }]);
});
test('lost revision-check response leaves review flag on removed-discount order with completed bank line', async () => {
    const order = { id: 42, uuid: 'card-offline', state: 'paid', baseer_offline_draft_revision: 3,
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true },
        lines: [{ uuid: 'food', qty: 1 }], payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
    const store = { data: { orm: { async call() { throw new ConnectionLostError(); } } },
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} } };
    await assert.rejects(() => experimentalExtensions.get('PosStore').baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42), ConnectionLostError);
    assert.match(order.uiState.baseerSharedDraftRefreshError, /changed on another device/);
    await assert.rejects(() => experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [order], throw: true }), /Shared draft requires review/);
    assert.deepEqual(order.payment_ids, [{ uuid: 'bank', amount: 3, payment_status: 'done' }]);
});
test('payment remains protected while in-flight revision check finds conflicts, deletion, or loses network', async () => {
    for (const outcome of ['revision', 'identity', 'deleted', 'network', 'paid']) {
        let release, reject;
        const response = new Promise((resolve, fail) => { release = resolve; reject = fail; });
        const order = { id: 42, uuid: `order-${outcome}`, state: 'paid', baseer_offline_draft_revision: 3,
            uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true },
            lines: [{ uuid: 'food', qty: 1 }], payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
        let sent = false;
        const store = { data: { orm: { call: async () => response } },
            getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
            async baseerAcceptRemoteSharedDeletionExperiment() { /* order remains intact for review */ },
            async baseerRunSharedDraftExperiment() { sent = true; } };
        const verifying = experimentalExtensions.get('PosStore').baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
        const syncing = experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [order], throw: true });
        const verifierOutcome = verifying.catch((error) => error);
        const syncOutcome = syncing.catch((error) => error);
        if (outcome === 'network') reject(new ConnectionLostError());
        else if (outcome === 'deleted') release({ 'pos.order': [] });
        else release({ 'pos.order': [{ id: 42, uuid: outcome === 'identity' ? 'other' : order.uuid,
            state: outcome === 'paid' ? 'paid' : 'draft', baseer_offline_draft_revision: outcome === 'revision' ? 4 : 3 }] });
        await verifierOutcome;
        const result = await syncOutcome;
        assert.ok(result instanceof Error, outcome);
        assert.equal(sent, false, outcome);
        assert.deepEqual(order.payment_ids, [{ uuid: 'bank', amount: 3, payment_status: 'done' }], outcome);
    }
});
test('payment waits for latest revision check when responses arrive in reverse order', async () => {
    const resolvers = [];
    const order = { id: 42, uuid: 'order', state: 'paid', baseer_offline_draft_revision: 3,
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true },
        lines: [{ uuid: 'food' }], payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
    let sent = false;
    const store = { data: { orm: { call: async () => new Promise((resolve) => resolvers.push(resolve)) } },
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
        async baseerRunSharedDraftExperiment() { sent = true; } };
    const verify = experimentalExtensions.get('PosStore').baseerVerifyIncomingSharedRevisionExperiment;
    const first = verify.call(store, order, 42), second = verify.call(store, order, 42);
    const syncing = experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [order], throw: true });
    resolvers[1]({ 'pos.order': [{ id: 42, uuid: 'order', state: 'draft', baseer_offline_draft_revision: 4 }] });
    assert.equal(await second, false);
    await assert.rejects(syncing, /Shared draft requires review/);
    resolvers[0]({ 'pos.order': [{ id: 42, uuid: 'order', state: 'draft', baseer_offline_draft_revision: 3 }] });
    assert.equal(await first, false);
    assert.equal(sent, false);
    assert.equal(order.payment_ids[0].amount, 3);
    assert.match(order.uiState.baseerSharedDraftRefreshError, /changed on another device/);
});
test('delayed paid server response does not discard a locally finalized bank payment', async () => {
    let release;
    const response = new Promise((resolve) => { release = resolve; });
    const order = { id: 42, uuid: 'late-paid', state: 'draft', baseer_offline_draft_revision: 3,
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true },
        lines: [{ uuid: 'food' }], payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
    let remoteDeleteCalls = 0, sent = false;
    const methods = experimentalExtensions.get('PosStore');
    const store = { data: { orm: { call: async () => response } }, models: {},
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
        async baseerAcceptRemoteSharedDeletionExperiment(value) {
            remoteDeleteCalls++;
            return methods.baseerAcceptRemoteSharedDeletionExperiment.call(this, value);
        }, async baseerRunSharedDraftExperiment() { sent = true; } };
    const checking = methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
    order.state = 'paid';
    const syncing = methods.syncAllOrders.call(store, { orders: [order], throw: true });
    release({ 'pos.order': [{ id: 42, uuid: order.uuid, state: 'paid', baseer_offline_draft_revision: 4 }] });
    assert.equal(await checking, false);
    await assert.rejects(syncing, /Shared draft requires review/);
    assert.equal(remoteDeleteCalls, 0);
    assert.equal(order.uiState.baseerSharedDraftRemoteDeleted, undefined);
    assert.equal(sent, false);
    assert.deepEqual(order.payment_ids, [{ uuid: 'bank', amount: 3, payment_status: 'done' }]);
});
test('overlapping draft checks release only their own provisional warning on paid ACK', async () => {
    for (const priorConflict of [false, true]) {
        const resolvers = [], conflict = 'The shared order changed on another device. Keep your local changes for review.';
        const order = { id: 42, uuid: 'two-checks', state: 'draft', uiState: { baseerSharedDraftRevision: 3,
            ...(priorConflict ? { baseerSharedDraftRefreshError: conflict } : {}) },
            payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
        let reconciled = 0, newCommands = 0;
        const methods = experimentalExtensions.get('PosStore');
        const store = { data: { orm: { call: () => new Promise((resolve) => resolvers.push(resolve)) } },
            getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
            async baseerRunSharedDraftExperiment() { newCommands++; },
            async baseerReconcileSharedPaidExperiment(value) { reconciled++; delete value.uiState.baseerSharedDraftPaidAckPending; } };
        const first = methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
        const second = methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
        order.state = 'paid'; order.uiState.baseerSharedDraftPaidAckPending = true;
        const syncing = methods.syncAllOrders.call(store, { orders: [order], throw: true });
        const observed = syncing.catch((error) => error);
        resolvers[0]({ 'pos.order': [] }); assert.equal(await first, false);
        resolvers[1]({ 'pos.order': [] }); assert.equal(await second, false);
        const result = await observed;
        if (priorConflict) { assert.match(result.message, /Shared draft requires review/); assert.equal(reconciled, 0); }
        else { assert.deepEqual(result, [order]); assert.equal(reconciled, 1); }
        assert.equal(newCommands, 0); assert.equal(order.payment_ids[0].amount, 3);
    }
});
test('an independent newer-server warning survives a pending check and paid ACK', async () => {
    let release;
    const response = new Promise((resolve) => { release = resolve; });
    const order = { id: 42, uuid: 'independent', state: 'draft', lines: [{ id: 11, uuid: 'food' }],
        payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }],
        uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: false, baseerSharedDraftRevision: 3 } };
    const methods = experimentalExtensions.get('PosStore');
    const pos = { data: { orm: { call: () => response } } };
    const checking = methods.baseerVerifyIncomingSharedRevisionExperiment.call(pos, order, 42);
    const updated = { 'pos.order': [{ id: 42, uuid: order.uuid, baseer_offline_draft_revision: 4 }], 'pos.order.line': [], 'pos.payment': [] };
    const models = { 'pos.order': { getAll: () => [order] }, 'pos.config': { get: () => ({}) },
        'pos.session': { get: () => ({}) }, connectNewData: () => ({ 'pos.order': [] }) };
    const service = { models, execute: async () => updated, missingRecursive: async (value) => value,
        synchronizeServerDataInIndexedDB() {}, deviceSync: { pos: { async baseerRefreshCleanSharedDraftExperiment() {} } } };
    await experimentalExtensions.get('PosData').loadServerOrders.call(service, []);
    order.state = 'paid'; order.uiState.baseerSharedDraftPaidAckPending = true;
    release({ 'pos.order': [] }); assert.equal(await checking, false);
    assert.match(order.uiState.baseerSharedDraftRefreshError, /changed on another device/);
    assert.equal(order.payment_ids[0].amount, 3);
});
test('paid ACK arriving during stale draft lookup is reconciled without a new payment command', async () => {
    for (const lookup of ['paid', 'empty', 'network']) for (const matches of [true, false]) {
        let release, reject;
        const response = new Promise((resolve, fail) => { release = resolve; reject = fail; });
        const payment = { uuid: 'bank', amount: 3, payment_status: 'done' };
        const order = { id: 42, uuid: 'late-ack', state: 'draft', baseer_offline_draft_revision: 3,
            uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true },
            lines: [{ uuid: 'food' }], payment_ids: [payment] };
        let newCommands = 0, reconciliations = 0;
        const methods = experimentalExtensions.get('PosStore');
        const store = { data: { orm: { call: async () => response } },
            getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
            async baseerRunSharedDraftExperiment() { newCommands++; },
            async baseerReconcileSharedPaidExperiment(value) {
                reconciliations++;
                assert.equal(value.uiState.baseerSharedDraftPaidCommand.command_uuid, 'frozen-paid');
                if (!matches) throw new Error('paid acknowledgement mismatch');
                delete value.uiState.baseerSharedDraftPaidAckPending;
            } };
        const checking = methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
        order.state = 'paid';
        order.uiState.baseerSharedDraftPaidAckPending = true;
        order.uiState.baseerSharedDraftPaidCommand = { command_uuid: 'frozen-paid' };
        const syncing = methods.syncAllOrders.call(store, { orders: [order], throw: true });
        const observed = syncing.catch((error) => error);
        if (lookup === 'network') reject(new ConnectionLostError());
        else release({ 'pos.order': lookup === 'empty' ? [] : [{ id: 42, uuid: order.uuid, state: 'paid', baseer_offline_draft_revision: 4 }] });
        assert.equal(await checking, false);
        const result = await observed;
        if (matches) assert.deepEqual(result, [order]);
        else { assert.match(result.message, /paid acknowledgement mismatch/); assert.equal(order.uiState.baseerSharedDraftPaidAckPending, true); }
        assert.equal(reconciliations, 1); assert.equal(newCommands, 0);
        assert.deepEqual(order.payment_ids, [payment]);
    }
});
test('stale lookup cannot clear review after local state or revision changed without a paid ACK', async () => {
    for (const changed of ['state', 'revision']) {
        let release;
        const response = new Promise((resolve) => { release = resolve; });
        const order = { id: 42, uuid: 'order', state: 'draft', uiState: { baseerSharedDraftRevision: 3 },
            payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
        const store = { data: { orm: { call: async () => response } } };
        const checking = experimentalExtensions.get('PosStore').baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
        if (changed === 'state') order.state = 'paid'; else order.uiState.baseerSharedDraftRevision = 4;
        release({ 'pos.order': [{ id: 42, uuid: order.uuid, state: changed === 'state' ? 'paid' : 'draft', baseer_offline_draft_revision: changed === 'revision' ? 4 : 3 }] });
        assert.equal(await checking, false);
        assert.match(order.uiState.baseerSharedDraftRefreshError, /changed on another device/);
        assert.equal(order.payment_ids[0].amount, 3);
    }
});
test('local paid transition without command continues only after matching server draft', async () => {
    for (const priorConflict of [false, true]) {
        let release;
        const response = new Promise((resolve) => { release = resolve; });
        const conflict = 'The shared order changed on another device. Keep your local changes for review.';
        const order = { id: 42, uuid: 'new-paid', state: 'draft', uiState: { baseerSharedDraftRevision: 3,
            ...(priorConflict ? { baseerSharedDraftRefreshError: conflict } : {}) },
            payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
        let sent = 0;
        const methods = experimentalExtensions.get('PosStore');
        const store = { data: { orm: { call: async () => response } }, getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }),
            notification: { add() {} }, async baseerRunSharedDraftExperiment() { sent++; } };
        const checking = methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
        order.state = 'paid';
        const syncing = methods.syncAllOrders.call(store, { orders: [order], throw: true });
        const observed = syncing.catch((error) => error);
        release({ 'pos.order': [{ id: 42, uuid: order.uuid, state: 'draft', baseer_offline_draft_revision: 3 }] });
        assert.equal(await checking, true);
        const result = await observed;
        if (priorConflict) { assert.match(result.message, /Shared draft requires review/); assert.equal(sent, 0); }
        else { assert.deepEqual(result, [order]); assert.equal(sent, 1); }
        assert.equal(order.payment_ids[0].amount, 3);
    }
});
test('paid ACK arriving after a failed lookup clears only that lookup warning', async () => {
    const order = { id: 42, uuid: 'after-network', state: 'draft', uiState: { baseerSharedDraftRevision: 3 },
        payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
    let reconciled = 0, sent = 0;
    const methods = experimentalExtensions.get('PosStore');
    const store = { data: { orm: { async call() { throw new ConnectionLostError(); } } },
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
        async baseerRunSharedDraftExperiment() { sent++; },
        async baseerReconcileSharedPaidExperiment(value) { reconciled++; delete value.uiState.baseerSharedDraftPaidAckPending; } };
    await assert.rejects(() => methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42), ConnectionLostError);
    order.state = 'paid'; order.uiState.baseerSharedDraftPaidAckPending = true;
    assert.deepEqual(await methods.syncAllOrders.call(store, { orders: [order], throw: true }), [order]);
    assert.equal(reconciled, 1); assert.equal(sent, 0); assert.equal(order.payment_ids[0].amount, 3);
});
test('paid server or empty lookup before a later paid ACK preserves provenance and the bank line', async () => {
    for (const outcome of ['paid', 'empty']) {
        let release;
        const response = new Promise((resolve) => { release = resolve; });
        const order = { id: 42, uuid: `late-${outcome}`, state: 'draft', uiState: { baseerSharedDraftRevision: 3 },
            payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
        let reconciled = 0, sent = 0;
        const methods = experimentalExtensions.get('PosStore');
        const store = { data: { orm: { call: () => response } },
            getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
            async baseerRunSharedDraftExperiment() { sent++; },
            async baseerReconcileSharedPaidExperiment(value) { reconciled++; delete value.uiState.baseerSharedDraftPaidAckPending; } };
        const checking = methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
        order.state = 'paid';
        release({ 'pos.order': outcome === 'empty' ? [] : [{ id: 42, uuid: order.uuid, state: 'paid', baseer_offline_draft_revision: 4 }] });
        assert.equal(await checking, false);
        await assert.rejects(() => methods.syncAllOrders.call(store, { orders: [order], throw: true }), /Shared draft requires review/);
        order.uiState.baseerSharedDraftPaidAckPending = true;
        assert.deepEqual(await methods.syncAllOrders.call(store, { orders: [order], throw: true }), [order]);
        assert.equal(reconciled, 1); assert.equal(sent, 0); assert.equal(order.payment_ids[0].amount, 3);
    }
});
test('paid order with a frozen lost-ACK command retries only that command after stale lookup', async () => {
    let release;
    const response = new Promise((resolve) => { release = resolve; });
    const pending = { command_uuid: 'original-paid', target_state: 'paid', payload_json: '{"frozen":true}' };
    const order = { id: 42, uuid: 'frozen', state: 'draft', uiState: { baseerSharedDraftRevision: 3 },
        payment_ids: [{ uuid: 'bank', amount: 3, payment_status: 'done' }] };
    let sent;
    const methods = experimentalExtensions.get('PosStore');
    const store = { data: { orm: { call: async () => response } },
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} },
        async baseerRunSharedDraftExperiment(value) { sent = structuredClone(value.uiState.baseerSharedDraftPending); delete value.uiState.baseerSharedDraftPending; } };
    const checking = methods.baseerVerifyIncomingSharedRevisionExperiment.call(store, order, 42);
    order.state = 'paid'; order.uiState.baseerSharedDraftPending = pending;
    const syncing = methods.syncAllOrders.call(store, { orders: [order], throw: true });
    release({ 'pos.order': [] }); assert.equal(await checking, false);
    assert.deepEqual(await syncing, [order]); assert.deepEqual(sent, pending);
    assert.deepEqual(order.payment_ids, [{ uuid: 'bank', amount: 3, payment_status: 'done' }]);
});
test('revision warning permits only a frozen pending retry and clears after acknowledgement', async () => {
    const warning = 'The shared order changed on another device. Keep your local changes for review.';
    const order = { id: 'order', uuid: 'order', state: 'draft', uiState: { baseerOfflineDiscount: {}, baseerSharedDraftRefreshError: warning,
        baseerSharedDraftPending: { command_uuid: 'same-command', payload_json: 'frozen' } } };
    let sent;
    const store = { getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), removePendingOrder() {}, notification: { add() {} },
        async baseerRunSharedDraftExperiment(value) { sent = { ...value.uiState.baseerSharedDraftPending }; delete value.uiState.baseerSharedDraftPending; value.uiState.baseerSharedDraftRevision = 2; } };
    assert.deepEqual(await experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [order] }), [order]);
    assert.deepEqual(sent, { command_uuid: 'same-command', payload_json: 'frozen' });
    assert.equal(order.uiState.baseerSharedDraftRefreshError, undefined);
});
test('remote deletion retains clean and edited local copies for review', async () => {
    const clean = { id: 42, uuid: 'clean-delete', state: 'draft', lines: [], payment_ids: [],
        uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: true },
        serializeForIndexedDB() { return { id: this.id, uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } };
    const edited = { id: 43, uuid: 'edited-delete', state: 'draft', lines: [], payment_ids: [],
        uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: false } };
    const pos = { models: {}, data: { indexedDB: {}, localDeleteCascade() { throw Error('must retain order'); } } };
    await experimentalExtensions.get('PosStore').baseerAcceptRemoteSharedDeletionExperiment.call(pos, clean);
    assert.equal(clean.uiState.baseerSharedDraftRemoteDeleted, true);
    assert.match(clean.uiState.baseerSharedDraftRefreshError, /another device/);
    const started = [];
    const device = { models: { 'pos.order': { getAll: () => [clean, edited] } }, pos: {
        baseerAcceptRemoteSharedDeletionExperiment: async (order) => started.push(order.uuid), notification: { add() {} },
    } };
    clean.uiState.baseerSharedDraftRefreshError = false;
    experimentalExtensions.get('DevicesSynchronisation').processDeletedRecords.call(device, { 'pos.order': [42, 43, 44] });
    assert.deepEqual(started, ['clean-delete', 'edited-delete']);
    assert.deepEqual(device.forwarded['pos.order'], [44]);
    const restored = { localResult: { 'pos.order': [clean] }, indexedDB: {}, localDeleteCascade() { throw Error('must retain after restart'); } };
    clean._markDirty = () => {}; clean.lines = []; clean.payment_ids = [];
    await experimentalExtensions.get('PosData').getLocalDataFromIndexedDB.call(restored);
    assert.equal(restored.localResult['pos.order'][0], clean);
});
test('restored shared draft checks server before sync and retains the basket on storage failure', async () => {
    const order = { id: 42, uuid: 'restored-review', state: 'draft', lines: [], payment_ids: [], _markDirty() {},
        uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: false },
        serializeForIndexedDB() { throw new Error('storage failed'); } };
    const restored = { localResult: { 'pos.order': [order] }, indexedDB: {}, localDeleteCascade() { throw Error('must retain'); } };
    await experimentalExtensions.get('PosData').getLocalDataFromIndexedDB.call(restored);
    const store = { models: {}, data: { indexedDB: {}, network: { offline: false }, orm: { async call() { return { 'pos.order': [] }; } } } };
    store.baseerAcceptRemoteSharedDeletionExperiment = (value) => experimentalExtensions.get('PosStore').baseerAcceptRemoteSharedDeletionExperiment.call(store, value);
    await assert.rejects(experimentalExtensions.get('PosStore').baseerCheckRestoredSharedDraftExperiment.call(store, order), /storage failed/);
    assert.equal(order.uiState.baseerSharedDraftRemoteDeleted, true);
    assert.match(order.uiState.baseerSharedDraftRefreshError, /local storage/);
    assert.equal(order.state, 'draft');
    assert.deepEqual(order.lines, []);
});
test('restored UUID draft checks the acknowledged numeric order on the server', async () => {
    const order = { id: 'uuid-draft', uuid: 'uuid-draft', state: 'draft', lines: [{ uuid: 'food', _markDirty() {} }], payment_ids: [], _markDirty() {},
        uiState: { baseerOfflineDiscount: { preview_line_uuids: [] }, baseerSharedDraftServerOrderId: 260 } };
    await experimentalExtensions.get('PosData').getLocalDataFromIndexedDB.call({ localResult: { 'pos.order': [order] }, indexedDB: {} });
    let domain;
    const store = { data: { network: { offline: false }, orm: { async call(_model, _method, args) { domain = args; return { 'pos.order': [{ id: 260, uuid: order.uuid, state: 'draft', baseer_offline_draft_revision: 1 }] }; } } } };
    order.uiState.baseerSharedDraftRevision = 1;
    assert.equal(await experimentalExtensions.get('PosStore').baseerCheckRestoredSharedDraftExperiment.call(store, order), true);
    assert.deepEqual(domain, [[['id', '=', 260]]]);
});
test('both payment paths block a restored pending command when server revision is newer', async () => {
    const pending = { command_uuid: 'stable-command', payload_json: 'unchanged' };
    const order = { id: 'local', uuid: 'local', state: 'draft', lines: [{ uuid: 'food', _markDirty() {} }], payment_ids: [], _markDirty() {},
        uiState: { baseerOfflineDiscount: { preview_line_uuids: [] }, baseerSharedDraftRevision: 1,
            baseerSharedDraftServerOrderId: 260, baseerSharedDraftPending: pending } };
    await experimentalExtensions.get('PosData').getLocalDataFromIndexedDB.call({ localResult: { 'pos.order': [order] }, indexedDB: {} });
    const notices = [];
    const store = { data: { network: { offline: false }, orm: { async call() { return { 'pos.order': [{ id: 260, uuid: 'local', state: 'draft', baseer_offline_draft_revision: 2 }] }; } } },
        dialog: { add: (...args) => notices.push(args) } };
    store.baseerSettleSharedDraftBeforePaymentExperiment = async () => true;
    store.baseerCheckRestoredSharedDraftExperiment = (value, opts) => experimentalExtensions.get('PosStore').baseerCheckRestoredSharedDraftExperiment.call(store, value, opts);
    const screen = { currentOrder: order, pos: store, dialog: store.dialog };
    await experimentalExtensions.get('PaymentScreen').validateOrder.call(screen);
    const validation = { order, pos: store };
    assert.equal(await experimentalExtensions.get('OrderPaymentValidation').validateOrder.call(validation), false);
    assert.equal(notices.length, 2);
    assert.equal(screen.nativeCalled, undefined);
    assert.equal(validation.nativeCalled, undefined);
    assert.equal(await store.baseerCheckRestoredSharedDraftExperiment(order, { allowFrozenRetry: true }), true);
    assert.equal(order.uiState.baseerSharedDraftPending, pending);
    assert.equal(pending.payload_json, 'unchanged');
});
test('first-create lost ACK must retry frozen command before either online payment path', async () => {
    const pending = { command_uuid: 'first-create', payload_json: '{"uuid":"local"}' };
    const order = { id: 'local', uuid: 'local', state: 'draft', uiState: { baseerOfflineDiscount: {}, baseerSharedDraftPending: pending } };
    const notices = [], sent = [];
    const store = { data: { network: { offline: false } }, dialog: { add: (...args) => notices.push(args) },
        async baseerRunSharedDraftExperiment(value) { sent.push(JSON.stringify(value.uiState.baseerSharedDraftPending)); throw new Error('newer remote revision'); },
        async baseerCheckRestoredSharedDraftExperiment() { throw new Error('must not reach validation'); } };
    store.baseerSettleSharedDraftBeforePaymentExperiment = (value) => experimentalExtensions.get('PosStore').baseerSettleSharedDraftBeforePaymentExperiment.call(store, value);
    const screen = { currentOrder: order, pos: store, dialog: store.dialog };
    await experimentalExtensions.get('PaymentScreen').validateOrder.call(screen);
    const validation = { order, pos: store };
    assert.equal(await experimentalExtensions.get('OrderPaymentValidation').validateOrder.call(validation), false);
    assert.deepEqual(sent, [JSON.stringify(pending), JSON.stringify(pending)]);
    assert.equal(notices.length, 2);
    assert.equal(screen.nativeCalled, undefined);
    assert.equal(validation.nativeCalled, undefined);
    assert.equal(order.uiState.baseerSharedDraftPending, pending);
    store.data.network.offline = true;
    assert.equal(await store.baseerSettleSharedDraftBeforePaymentExperiment(order), true);
    assert.equal(sent.length, 2);
    store.data.network.offline = false;
    store.baseerRunSharedDraftExperiment = async (value) => { assert.equal(value.uiState.baseerSharedDraftPending, pending); delete value.uiState.baseerSharedDraftPending; };
    assert.equal(await store.baseerSettleSharedDraftBeforePaymentExperiment(order), true);
});
test('managed sync returns only a fully acknowledged current order and preserves later edits', async () => {
    const make = (uuid) => ({ uuid, state: 'draft', uiState: { baseerOfflineDiscount: {} } });
    const acknowledged = make('ack'), edited = make('edited');
    const removed = [];
    const store = { getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), removePendingOrder: (order) => removed.push(order.uuid),
        notification: { add() {} }, async baseerRunSharedDraftExperiment(order) {
            order.uiState.baseerSharedDraftRevision = 1;
            order.uiState.baseerSharedDraftNeedsSync = order.uuid === 'edited';
        } };
    const result = await experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [acknowledged, edited] });
    assert.deepEqual(result, [acknowledged]);
    assert.deepEqual(removed, ['ack']);
});
test('saving a managed draft reports success only after acknowledgement and retains rejected edits', async () => {
    const order = { uuid: 'shared-save', state: 'draft', uiState: { baseerOfflineDiscount: {} } };
    const notices = [], switched = [];
    const pos = { models: {}, getOrder: () => order, notification: { add: (message) => notices.push(message) },
        getEmptyOrder: () => 'empty', setOrder: (value) => switched.push(value),
        async syncAllOrders() { throw new Error('server rejected'); } };
    await experimentalExtensions.get('PosStore').clickSaveOrder.call(pos);
    assert.deepEqual(switched, []);
    assert.match(notices[0], /could not be synchronized/);
    assert.ok(order.uiState.baseerOfflineDiscount);
    pos.syncAllOrders = async () => [order];
    await experimentalExtensions.get('PosStore').clickSaveOrder.call(pos);
    assert.deepEqual(switched, ['empty']);
    assert.equal(notices[1], 'Order saved for later');
});
test('restored discount without a product line is retained and marked unsafe for payment and sync', async () => {
    const order = { id: 41, uuid: 'incomplete', state: 'draft', lines: [{ uuid: 'preview', _markDirty() {} }], payment_ids: [], _markDirty() {},
        uiState: { baseerOfflineDiscount: { preview_line_uuids: ['preview'] } } };
    const data = { localResult: { 'pos.order': [order] }, indexedDB: {}, localDeleteCascade() { throw Error('must retain'); } };
    await experimentalExtensions.get('PosData').getLocalDataFromIndexedDB.call(data);
    assert.match(order.uiState.baseerSharedDraftHydrationError, /product line/);
    assert.equal(data.localResult['pos.order'][0], order);
    let sent = false;
    const store = { getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [] }), notification: { add() {} }, async baseerRunSharedDraftExperiment() { sent = true; } };
    assert.deepEqual(await experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [order] }), []);
    assert.equal(sent, false);
    const paid = { id: 42, uuid: 'paid-incomplete', state: 'paid', lines: [{ uuid: 'preview-paid', _markDirty() {} }],
        payment_ids: [{ uuid: 'paid-cash', amount: 105, _markDirty() {} }], _markDirty() {},
        uiState: { baseerOfflineDiscount: { preview_line_uuids: ['preview-paid'] } } };
    const paidData = { localResult: { 'pos.order': [paid] }, indexedDB: {}, localDeleteCascade() { throw Error('must retain'); } };
    await experimentalExtensions.get('PosData').getLocalDataFromIndexedDB.call(paidData);
    assert.match(paid.uiState.baseerSharedDraftHydrationError, /product line/);
    assert.deepEqual(await experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [paid] }), []);
    assert.equal(paid.payment_ids[0].amount, 105);
    assert.equal(paid.state, 'paid');
    assert.equal(sent, false);
    const missingPayment = { id: 43, uuid: 'paid-no-payment', state: 'paid', lines: [{ uuid: 'food', _markDirty() {} }],
        payment_ids: [], _markDirty() {}, uiState: { baseerOfflineDiscount: { preview_line_uuids: [] },
            baseerSharedDraftPending: { source_payment_uuids: ['cash'] } } };
    await experimentalExtensions.get('PosData').getLocalDataFromIndexedDB.call({ localResult: { 'pos.order': [missingPayment] }, indexedDB: {} });
    assert.match(missingPayment.uiState.baseerSharedDraftHydrationError, /payment line/);
    assert.deepEqual(await experimentalExtensions.get('PosStore').syncAllOrders.call(store, { orders: [missingPayment] }), []);
    assert.equal(sent, false);
});
test('online paid restore refuses a missing local payment before server data can mask it', async () => {
    const data = { 'pos.order': [{ uuid: 'paid', state: 'paid', JSONuiState: JSON.stringify({ baseerOfflineDiscount: {},
        baseerSharedDraftPending: { target_state: 'paid', source_line_uuids: ['food'], source_payment_uuids: ['cash'] } }) }],
        'pos.order.line': [{ uuid: 'food' }], 'pos.payment': [] };
    const service = { _baseerRestoringLocalData: true, network: { offline: false } };
    await assert.rejects(experimentalExtensions.get('PosData').missingRecursive.call(service, data), /local order is incomplete/);
    assert.equal(data['pos.order'][0].state, 'paid');
    assert.deepEqual(data['pos.payment'], []);
});
test('clean draft refresh refuses a response if the cashier edits while fetching', async () => {
    experimentalGeneration = 1;
    const order = { id: 42, uuid: 'clean', state: 'draft', lines: [{ id: 11, uuid: 'food' }], payment_ids: [],
        uiState: { baseerOfflineDiscount: {}, baseerSharedDraftHydratedOnly: true },
        serializeForIndexedDB() { return { id: this.id, uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } };
    let release, started;
    const gate = new Promise((resolve) => { release = resolve; });
    const begin = new Promise((resolve) => { started = resolve; });
    const data = { network: { offline: false }, indexedDB: {}, missingRecursive: async (value) => value,
        orm: { async call() { started(); await gate; return { 'pos.order': [{ id: 42, uuid: 'clean', state: 'draft', baseer_offline_draft_revision: 2, baseer_offline_draft_kind: false }] }; } } };
    const pos = { data, models: {}, config: {} };
    const method = experimentalExtensions.get('PosStore').baseerRefreshCleanSharedDraftExperiment;
    let waiting;
    pos.baseerAcceptRemoteSharedDeletionExperiment = async () => {};
    pos.baseerRefreshCleanSharedDraftExperiment = (value) => (waiting = method.call(pos, value));
    pos.notification = { add() {} };
    const device = { models: { 'pos.order': { getAll: () => [order] } }, pos };
    experimentalExtensions.get('DevicesSynchronisation').processDeletedRecords.call(device, { 'pos.order.line': [11] });
    await begin;
    const notices = [];
    const screen = { currentOrder: order, dialog: { add: (...args) => notices.push(args) } };
    await experimentalExtensions.get('PaymentScreen').validateOrder.call(screen);
    const validation = { order, pos: { dialog: { add: (...args) => notices.push(args) } } };
    assert.equal(await experimentalExtensions.get('OrderPaymentValidation').validateOrder.call(validation), false);
    assert.equal(notices.length, 2);
    assert.equal(screen.nativeCalled, undefined);
    assert.equal(validation.nativeCalled, undefined);
    experimentalGeneration++;
    order.uiState.baseerSharedDraftHydratedOnly = false;
    release();
    await assert.rejects(waiting, /changed while refreshing/);
    assert.ok(order.uiState.baseerSharedDraftRefreshError);
    assert.equal(order.baseer_offline_draft_revision, undefined);
    assert.ok(order.uiState.baseerOfflineDiscount);
});
test('exact shared draft refresh never stages stale revision or mismatched identity', async () => {
    let stages = 0, failFingerprint = false, rollbacks = 0;
    const installed = new Function('attachDraftGenerationExperiment', 'hydrateSharedDraftExperiment', 'calculateOfflineDiscount', 'accountTaxHelpers', 'persistDraftGraphExperiment', 'stageNativeServerGraphExperiment', 'cancelGraphFingerprint',
        `${mocks.replace("const cancelGraphFingerprint = () => 'test-graph';", "")}\n${source.replace('const SHARED_DRAFT_FLOW_ENABLED = false;', 'const SHARED_DRAFT_FLOW_ENABLED = true;')}\nreturn extensions;`)(
        () => ({ get: () => 4 }), () => {}, () => {}, {}, async ({ capture }) => capture(),
        ({ order, response }) => { stages++; const oldId = order.id; Object.assign(order, response['pos.order'][0]); order.lines = []; return { rollback() { rollbacks++; order.id = oldId; } }; },
        (order) => { if (failFingerprint) throw new Error('fingerprint unavailable'); return JSON.stringify({ header: { ...order.serializeForIndexedDB(), JSONuiState: order.uiState }, lines: [] }); });
    const method = installed.get('PosStore').baseerRefreshCleanSharedDraftExperiment;
    const expected = { serverId: 42, uuid: 'shared', revision: 3, sessionId: 27, configId: 2, companyId: 1,
        lines: [{ id: 10, uuid: 'source', productId: 9, qty: 1, priceUnit: 100, discount: 0, taxIds: [138] }] };
    const makeOrder = () => ({ id: 'local', uuid: 'shared', state: 'draft', lines: [], payment_ids: [],
        uiState: { baseerSharedDraftServerOrderId: 42, baseerSharedDraftRevision: 3, baseerSharedDraftHydratedOnly: true },
        serializeForIndexedDB() { return { id: this.id, uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } });
    const row = { id: 42, uuid: 'shared', state: 'draft', baseer_offline_draft_revision: 3,
        session_id: [27, 'session'], config_id: [2, 'pos'], company_id: [1, 'company'], lines: [10] };
    const line = { id: 10, uuid: 'source', order_id: 42, product_id: 9, qty: 1, price_unit: 100,
        discount: 0, tax_ids: [138], baseer_global_discount_line: false };
    for (const changed of [{ id: 43 }, { uuid: 'other' }, { state: 'cancel' }, { baseer_offline_draft_revision: 4 },
        { session_id: [28, 'session'] }, { config_id: [3, 'pos'] }, { company_id: [9, 'company'] }]) {
        const order = makeOrder();
        const data = { network: { offline: false }, indexedDB: {}, orm: { call: async () => ({ 'pos.order': [{ ...row, ...changed }], 'pos.order.line': [line] }) },
            missingRecursive: async (raw) => raw };
        assert.equal(await method.call({ data, models: {} }, order, { expected }), false);
        assert.equal(stages, 0); assert.equal(order.id, 'local');
    }
    for (const changeAt of ['expand', 'confirm']) {
        const order = makeOrder(); let calls = 0;
        const data = { network: { offline: false }, indexedDB: {}, orm: { call: async () => {
            calls++; return { 'pos.order': [{ ...row, ...(changeAt === 'confirm' && calls === 2 ? { baseer_offline_draft_revision: 4 } : {}) }], 'pos.order.line': [line] };
        } }, missingRecursive: async (raw) => changeAt === 'expand' ? { 'pos.order': [{ ...row, baseer_offline_draft_revision: 4 }], 'pos.order.line': [line] } : raw };
        assert.equal(await method.call({ data, models: {} }, order, { expected }), false);
        assert.equal(stages, 0); assert.equal(order.id, 'local');
    }
    for (const lines of [[], [line, line], [{ ...line, uuid: 'other' }], [{ ...line, order_id: 55 }],
        [{ ...line, product_id: 8 }], [{ ...line, qty: 2 }], [{ ...line, price_unit: 99 }],
        [{ ...line, discount: 1 }], [{ ...line, baseer_global_discount_line: true }],
        [{ ...line, tax_ids: [] }], [{ ...line, tax_ids: [139] }],
        [{ ...line, tax_ids: [138, 138] }], [{ ...line, tax_ids: undefined }]]) {
        const order = makeOrder();
        const data = { network: { offline: false }, indexedDB: {},
            orm: { call: async () => ({ 'pos.order': [row], 'pos.order.line': [line] }) },
            missingRecursive: async () => ({ 'pos.order': [row], 'pos.order.line': lines }) };
        assert.equal(await method.call({ data, models: {} }, order, { expected }), false);
        assert.equal(stages, 0); assert.equal(order.id, 'local');
    }
    {
        const order = makeOrder(), missingAllowance = { ...row, lines: [10, 11] };
        const data = { network: { offline: false }, indexedDB: {},
            orm: { call: async () => ({ 'pos.order': [missingAllowance], 'pos.order.line': [line] }) },
            missingRecursive: async (raw) => raw };
        assert.equal(await method.call({ data, models: {} }, order, { expected }), false);
        assert.equal(stages, 0); assert.equal(order.id, 'local');
    }
    {
        const order = makeOrder();
        const data = { network: { offline: false }, indexedDB: {}, orm: { call: async () => ({ 'pos.order': [row], 'pos.order.line': [line] }) }, missingRecursive: async (raw) => raw };
        failFingerprint = true;
        await assert.rejects(() => method.call({ data, models: {} }, order, { expected }), /fingerprint unavailable/);
        assert.equal(order.id, 'local'); assert.equal(rollbacks, 1);
        failFingerprint = false; stages = 0;
    }
    const order = makeOrder(); let calls = 0;
    const data = { network: { offline: false }, indexedDB: {}, orm: { call: async () => { calls++; return { 'pos.order': [row], 'pos.order.line': [line] }; } }, missingRecursive: async (raw) => raw };
    assert.equal(await method.call({ data, models: {} }, order, { expected }), true);
    assert.equal(stages, 1); assert.equal(calls, 2); assert.equal(order.id, 42);
});
test('refresh graph ignores only Odoo hasChange on the identified discount preview', () => {
    const make = () => ({ header: { JSONuiState: { baseerOfflineDiscount: { preview_line_uuids: ['preview'], value: '10' } } },
        lines: [{ uuid: 'food', qty: 1, JSONuiState: JSON.stringify({ hasChange: true }) },
            { uuid: 'preview', price_unit: -10, JSONuiState: JSON.stringify({ hasChange: true, other: 1 }) }], payments: [], attrs: [] });
    const modifiedMocks = mocks.replace("const cancelGraphFingerprint = () => 'test-graph';", '');
    const fingerprint = new Function('cancelGraphFingerprint', `${modifiedMocks}\n${source}\nreturn refreshGraphFingerprint;`)((graph) => JSON.stringify(graph));
    const original = make(), baseline = fingerprint(original), previewChange = make();
    previewChange.lines[1].JSONuiState = JSON.stringify({ hasChange: false, other: 1 });
    assert.equal(fingerprint(previewChange), baseline);
    const cashier = make(); cashier.lines[0].qty = 2;
    assert.notEqual(fingerprint(cashier), baseline);
    const kitchen = make(); kitchen.lines[0].JSONuiState = JSON.stringify({ hasChange: false });
    assert.notEqual(fingerprint(kitchen), baseline);
    const previewValue = make(); previewValue.lines[1].price_unit = -20;
    assert.notEqual(fingerprint(previewValue), baseline);
    const previewOther = make(); previewOther.lines[1].JSONuiState = JSON.stringify({ hasChange: true, other: 2 });
    assert.notEqual(fingerprint(previewOther), baseline);
    const missing = make(); missing.lines.pop();
    assert.throws(() => fingerprint(missing), /Incomplete discount preview/);
});
test('exact shared draft refresh preserves and blocks a cashier edit during IndexedDB save', async () => {
    let generation = 4, saves = 0, lastState;
    const order = { id: 'local', uuid: 'shared', state: 'draft', lines: [], payment_ids: [],
        uiState: { baseerSharedDraftServerOrderId: 42, baseerSharedDraftRevision: 3, baseerSharedDraftHydratedOnly: true,
            baseerOfflineDiscount: { value: '20' } },
        serializeForIndexedDB() { return { id: this.id, uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } };
    const row = { id: 42, uuid: 'shared', state: 'draft', baseer_offline_draft_revision: 3,
        session_id: 27, config_id: 2, company_id: 1, lines: [10] };
    const line = { id: 10, uuid: 'source', order_id: 42, product_id: 9, qty: 1, price_unit: 100,
        discount: 0, tax_ids: [138], baseer_global_discount_line: false };
    const expected = { serverId: 42, uuid: 'shared', revision: 3, sessionId: 27, configId: 2, companyId: 1,
        lines: [{ id: 10, uuid: 'source', productId: 9, qty: 1, priceUnit: 100, discount: 0, taxIds: [138] }] };
    const installed = new Function('attachDraftGenerationExperiment', 'hydrateSharedDraftExperiment', 'calculateOfflineDiscount', 'accountTaxHelpers', 'persistDraftGraphExperiment', 'stageNativeServerGraphExperiment', 'cancelGraphFingerprint',
        `${mocks.replace("const cancelGraphFingerprint = () => 'test-graph';", "")}\n${source.replace('const SHARED_DRAFT_FLOW_ENABLED = false;', 'const SHARED_DRAFT_FLOW_ENABLED = true;')}\nreturn extensions;`)(
        () => ({ get: () => generation }), () => {}, () => {}, {}, async ({ capture }) => {
            const snap = capture(); saves++; lastState = JSON.parse(snap.records['pos.order'][0].JSONuiState);
            if (saves === 1) { order.uiState.baseerOfflineDiscount.value = '10'; generation++; }
            return snap;
        }, ({ order, response }) => { Object.assign(order, response['pos.order'][0]); order.lines = []; return { rollback() { throw new Error('must not roll back newer edit'); } }; },
        (order) => JSON.stringify({ header: { ...order.serializeForIndexedDB(), JSONuiState: order.uiState }, lines: [] }));
    const data = { network: { offline: false }, indexedDB: {}, orm: { call: async () => ({ 'pos.order': [row], 'pos.order.line': [line] }) },
        missingRecursive: async (raw) => raw };
    await assert.rejects(() => installed.get('PosStore').baseerRefreshCleanSharedDraftExperiment.call({ data, models: {} }, order, { expected }), /changed while saving/);
    assert.equal(saves, 2);
    assert.equal(lastState.baseerOfflineDiscount.value, '10');
    assert.equal(lastState.baseerSharedDraftNeedsSync, true);
    assert.match(lastState.baseerSharedDraftRefreshError, /changed while saving/);
    assert.equal(order.uiState.baseerSharedDraftNeedsSync, true);
    assert.equal(order.uiState.baseerOfflineDiscount.value, '10');
});
test('exact shared draft refresh allows an unrelated order event during IndexedDB save', async () => {
    let generation = 4, saves = 0;
    const order = { id: 'local', uuid: 'shared', state: 'draft', lines: [], payment_ids: [],
        uiState: { baseerSharedDraftServerOrderId: 42, baseerSharedDraftRevision: 3, baseerSharedDraftHydratedOnly: true },
        serializeForIndexedDB() { return { id: this.id, uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } };
    const row = { id: 42, uuid: 'shared', state: 'draft', baseer_offline_draft_revision: 3,
        session_id: 27, config_id: 2, company_id: 1, lines: [10] };
    const line = { id: 10, uuid: 'source', order_id: 42, product_id: 9, qty: 1, price_unit: 100,
        discount: 0, tax_ids: [138], baseer_global_discount_line: false };
    const expected = { serverId: 42, uuid: 'shared', revision: 3, sessionId: 27, configId: 2, companyId: 1,
        lines: [{ id: 10, uuid: 'source', productId: 9, qty: 1, priceUnit: 100, discount: 0, taxIds: [138] }] };
    const installed = new Function('attachDraftGenerationExperiment', 'hydrateSharedDraftExperiment', 'calculateOfflineDiscount', 'accountTaxHelpers', 'persistDraftGraphExperiment', 'stageNativeServerGraphExperiment', 'cancelGraphFingerprint',
        `${mocks.replace("const cancelGraphFingerprint = () => 'test-graph';", "")}\n${source.replace('const SHARED_DRAFT_FLOW_ENABLED = false;', 'const SHARED_DRAFT_FLOW_ENABLED = true;')}\nreturn extensions;`)(
        () => ({ get: () => generation }), () => {}, () => {}, {}, async ({ capture }) => {
            const snap = capture(); if (++saves === 1) generation++; return snap;
        }, ({ order, response }) => { Object.assign(order, response['pos.order'][0]); order.lines = []; return { rollback() {} }; },
        (order) => JSON.stringify({ header: { ...order.serializeForIndexedDB(), JSONuiState: order.uiState }, lines: [] }));
    const data = { network: { offline: false }, indexedDB: {}, orm: { call: async () => ({ 'pos.order': [row], 'pos.order.line': [line] }) }, missingRecursive: async (raw) => raw };
    assert.equal(await installed.get('PosStore').baseerRefreshCleanSharedDraftExperiment.call({ data, models: {} }, order, { expected }), true);
    assert.equal(saves, 2);
    assert.equal(order.uiState.baseerSharedDraftNeedsSync, undefined);
});
test('experimental cancellation never removes the local order before protected ACK', async () => {
    const order = { uuid: 'draft', state: 'draft', uiState: { baseerOfflineDiscount: {} } };
    const calls = [];
    const pos = { models: { 'pos.order': { get: () => order } },
        _onBeforeDeleteOrder: async () => true,
        baseerCancelSharedDraftExperiment: async () => { throw new Error('stale revision'); },
        data: { indexedDB: {}, localDeleteCascade: () => calls.push('delete') },
        removePendingOrder: () => calls.push('dequeue'), notification: { add: () => calls.push('warning') } };
    assert.equal(await experimentalExtensions.get('PosStore').deleteOrders.call(pos, [order]), false);
    assert.deepEqual(calls, ['warning']);
    pos.baseerCancelSharedDraftExperiment = async () => { calls.push('ack'); };
    assert.equal(await experimentalExtensions.get('PosStore').deleteOrders.call(pos, [order]), true);
    assert.deepEqual(calls, ['warning', 'ack', 'delete', 'dequeue']);
});
test('managed kitchen cancellation persists its reason and reuses a legacy pending UUID after a lost response', async () => {
    const moduleSource = readFileSync(new URL('../static/src/app/draft_snapshot_experiment.js', import.meta.url), 'utf8');
    const flow = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`);
    let generation = 4, storageError = false;
    const snapshots = [], requests = [], events = [];
    const persist = async ({ order, pending, acknowledgement }) => {
        if (storageError) throw new Error('storage failed');
        if (!acknowledgement) order.uiState.baseerSharedDraftCancelPending = structuredClone(pending);
        else { delete order.uiState.baseerSharedDraftCancelPending; order.uiState.baseerSharedDraftCancelAcknowledged = true; }
        snapshots.push(structuredClone(order.uiState));
        return { generation, needsReview: false };
    };
    const installed = new Function('attachDraftGenerationExperiment', 'kitchenCancelIntent', 'persistDraftCancelExperiment', 'cancelDraftSnapshot', 'singleFlightDraftExperiment',
        `${mocks}\n${source.replace('const SHARED_DRAFT_FLOW_ENABLED = false;', 'const SHARED_DRAFT_FLOW_ENABLED = true;')}\nreturn extensions;`)(
        () => ({ get: () => generation }), flow.kitchenCancelIntent, persist, flow.cancelDraftSnapshot, flow.singleFlightDraftExperiment);
    const methods = installed.get('PosStore');
    const pending = { order_uuid: 'draft', revision: 3, command_uuid: 'old-cancel', generation: 4 };
    const order = { id: 42, uuid: 'draft', state: 'draft', baseer_offline_draft_revision: 3,
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftGeneration: 4,
            baseerSharedDraftCancelPending: pending, baseerKitchenCancellation: { reasonCode: 'wrong_order', reasonNote: '' } } };
    let fail = true;
    const pos = { models: { 'pos.order': { get: () => order } }, config: { current_session_id: 27 }, syncingOrders: new Set(),
        data: { network: { offline: false }, indexedDB: {}, orm: { call: async (_model, _method, args) => {
            requests.push(structuredClone(args)); assert.ok(snapshots.at(-1).baseerSharedDraftKitchenCancelIntent);
            if (fail) throw new Error('lost response');
            return { uuid: 'draft', state: 'cancel', revision: 4 };
        } }, localDeleteCascade: () => events.push('delete') },
        _onBeforeDeleteOrder: async () => true, removePendingOrder: () => events.push('dequeue'),
        notification: { add: () => events.push('warning') } };
    pos.baseerCancelSharedDraftExperiment = (record) => methods.baseerCancelSharedDraftExperiment.call(pos, record);
    order.uiState.baseerSharedDraftNeedsSync = true;
    assert.equal(await methods.deleteOrders.call(pos, [order]), false);
    assert.equal(requests.length, 0, 'do not cancel an order with unsynchronized local changes');
    delete order.uiState.baseerSharedDraftNeedsSync;
    storageError = true;
    assert.equal(await methods.deleteOrders.call(pos, [order]), false);
    assert.equal(requests.length, 0, 'do not send before the frozen intent is durable');
    storageError = false;
    assert.equal(await methods.deleteOrders.call(pos, [order]), false);
    assert.deepEqual(events, ['warning', 'warning', 'warning']);
    assert.deepEqual(requests[0], ['draft', 3, 'old-cancel', { session_id: 27, reason_code: 'wrong_order', reason_note: '' }]);
    order.uiState.baseerKitchenCancellation.reasonCode = 'staff_error';
    assert.equal(await methods.deleteOrders.call(pos, [order]), false);
    assert.equal(requests.length, 1, 'a different reason cannot replace an unknown action');
    order.uiState.baseerKitchenCancellation.reasonCode = 'wrong_order';
    fail = false;
    assert.equal(await methods.deleteOrders.call(pos, [order]), true);
    assert.deepEqual(requests[1], requests[0]);
    assert.deepEqual(events.slice(-2), ['delete', 'dequeue']);
});
test('changed local draft fences an old cancellation and synchronizes before opening cancellation', async () => {
    const events = [], snapshots = [];
    let outcome = 'fenced', failPersist = false, failSync = false;
    const pending = { order_uuid: 'draft', revision: 3, command_uuid: 'old', generation: 3 };
    const tracker = { get: () => 4 };
    const savePending = async ({ order }) => {
        if (failPersist) throw new Error('storage failed');
        snapshots.push(structuredClone(order.uiState)); events.push('save-local');
    };
    const saveFence = async ({ order, resolution }) => {
        assert.equal(resolution.outcome, 'fenced');
        delete order.uiState.baseerSharedDraftCancelPending;
        order.uiState.baseerSharedDraftRevision = resolution.revision;
        order.uiState.baseerSharedDraftGeneration = 4;
        order.uiState.baseerSharedDraftNeedsSync = true;
        order.uiState.baseerSharedDraftRecoverySync = true;
        events.push('save-fence');
    };
    const installed = new Function('attachDraftGenerationExperiment', 'persistDraftCancelExperiment', 'persistCancelFenceRecovery',
        `${mocks}\n${source.replace('const SHARED_DRAFT_FLOW_ENABLED = false;', 'const SHARED_DRAFT_FLOW_ENABLED = true;')}\nreturn extensions;`)(
        () => tracker, savePending, saveFence);
    const methods = installed.get('PosStore');
    const order = { id: 42, uuid: 'draft', state: 'draft', baseer_offline_draft_kind: 'fixed', amount_total: 3,
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftCancelPending: pending,
            baseerSharedDraftNeedsSync: true, baseerSharedDraftRemoveRequested: true } };
    const pos = { config: { current_session_id: 27 }, models: {}, syncingOrders: new Set(),
        data: { network: { offline: false }, indexedDB: {}, orm: { call: async (_model, method, args) => {
            events.push('resolve'); assert.equal(method, 'baseer_resolve_offline_draft_cancel');
            assert.deepEqual(args, ['draft', 3, 'old', 27]);
            return { outcome, uuid: 'draft', state: outcome === 'fenced' ? 'draft' : 'cancel', revision: 4 };
        } } }, notification: { add: () => events.push('warning') },
        baseerRunSharedDraftExperiment: async (record) => { events.push('sync'); if (failSync) throw new Error('lost sync response'); record.uiState.baseerSharedDraftNeedsSync = false; } };
    pos.baseerRecoverChangedCancellation = (record) => methods.baseerRecoverChangedCancellation.call(pos, record);
    pos.baseerFinishCancellationRecovery = (record) => methods.baseerFinishCancellationRecovery.call(pos, record);
    failPersist = true;
    assert.equal(await methods.beforeDeleteOrder.call(pos, order), false);
    assert.deepEqual(events, ['warning']);
    assert.equal(order.uiState.baseerSharedDraftCancelPending.command_uuid, 'old');
    failPersist = false; outcome = 'committed'; events.length = 0;
    assert.equal(await methods.beforeDeleteOrder.call(pos, order), false);
    assert.deepEqual(events, ['save-local', 'resolve', 'warning']);
    assert.equal(order.uiState.baseerSharedDraftCancelPending.command_uuid, 'old');
    assert.equal(order.amount_total, 3);
    outcome = 'fenced'; failSync = true; events.length = 0;
    assert.equal(await methods.beforeDeleteOrder.call(pos, order), false);
    assert.deepEqual(events, ['save-local', 'resolve', 'save-fence', 'sync', 'warning']);
    assert.equal(order.uiState.baseerSharedDraftRecoverySync, true);
    assert.equal(order.uiState.baseerSharedDraftCancelPending, undefined);
    failSync = false; events.length = 0;
    assert.equal(await methods.beforeDeleteOrder.call(pos, order), true);
    assert.deepEqual(events, ['sync'], 'retry the frozen synchronization without sending cancellation again');
    assert.equal(pos.nativeBeforeDelete, true);
    assert.equal(order.amount_total, 3);
    assert.equal(order.uiState.baseerSharedDraftRevision, 4);
    assert.equal(order.uiState.baseerSharedDraftCancelPending, undefined);
    assert.ok(snapshots.at(-1).baseerSharedDraftRemoveRequested);
});
test('local UUID draft verifies its server identity and asks the kitchen reason exactly once', async () => {
    const order = { id: 'local-uuid', uuid: 'draft-uuid', isSynced: false, state: 'draft',
        baseer_offline_draft_revision: 3, uiState: { baseerSharedDraftServerOrderId: 42 } };
    let questions = 0, serverUuid = order.uuid, allow = true;
    const pos = { models: {}, config: { baseer_direct_print_enabled: true, current_session_id: 27 },
        data: { network: { offline: false }, orm: { call: async () => ({ 'pos.order': [{ id: 42, uuid: serverUuid, state: 'draft' }] }) } },
        _baseerCancellationPreview: async (ids, session) => { assert.deepEqual(ids, [42]); assert.equal(session, 27); return { order_ids: [42] }; },
        _baseerAskCancellationReason: async () => { questions++; return allow && { reasonCode: 'wrong_order', reasonNote: '' }; },
        notification: { add() {} } };
    assert.equal(await experimentalExtensions.get('PosStore').beforeDeleteOrder.call(pos, order), true);
    assert.equal(questions, 1);
    assert.equal(order.uiState.baseerKitchenCancellation.reasonCode, 'wrong_order');
    delete order.uiState.baseerKitchenCancellation; serverUuid = 'other-order';
    assert.equal(await experimentalExtensions.get('PosStore').beforeDeleteOrder.call(pos, order), false);
    assert.equal(questions, 1);
    serverUuid = order.uuid; allow = false;
    assert.equal(await experimentalExtensions.get('PosStore').beforeDeleteOrder.call(pos, order), false);
    assert.equal(questions, 2);
    order.id = 42; order.isSynced = true; allow = true;
    assert.equal(await experimentalExtensions.get('PosStore').beforeDeleteOrder.call(pos, order), true);
    assert.equal(questions, 2, 'bridge owns the numeric synchronized case');
});
test('cancel first synchronizes removed discount and deleted card without accepting a remaining payment', async () => {
    const method = experimentalExtensions.get('PosStore').beforeDeleteOrder;
    const create = () => ({ id: 42, uuid: 'draft', state: 'draft', isSynced: true, payment_ids: [],
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftGeneration: experimentalGeneration,
            baseerSharedDraftRemoveRequested: true, baseerSharedDraftPaymentDeletions: [{ id: 88, token: 'deleted-card' }] } });
    let calls = 0;
    const pos = { models: {}, data: { network: { offline: false } }, config: { baseer_direct_print_enabled: true },
        notification: { add() {} }, async baseerRunSharedDraftExperiment(order) {
            calls++; assert.equal(order.uiState.baseerSharedDraftRemoveRequested, true);
            assert.deepEqual(order.uiState.baseerSharedDraftPaymentDeletions, [{ id: 88, token: 'deleted-card' }]);
            order.uiState.baseerSharedDraftPaymentDeletions = []; order.uiState.baseerSharedDraftNeedsSync = false;
            order.uiState.baseerSharedDraftGeneration = experimentalGeneration;
        } };
    const clean = create();
    assert.equal(await method.call(pos, clean), true); assert.equal(calls, 1); assert.equal(pos.nativeBeforeDelete, true);
    const withCard = create(); withCard.payment_ids = [{ uuid: 'card', amount: 3, payment_status: 'done' }];
    pos.nativeBeforeDelete = false;
    assert.equal(await method.call(pos, withCard), false); assert.equal(calls, 1); assert.equal(pos.nativeBeforeDelete, false);
    const lateCard = create();
    pos.baseerRunSharedDraftExperiment = async (order) => { order.payment_ids.push({ uuid: 'card', amount: 3 }); order.uiState.baseerSharedDraftGeneration = experimentalGeneration; };
    assert.equal(await method.call(pos, lateCard), false); assert.equal(lateCard.payment_ids[0].amount, 3);
    const disconnected = create(); pos.data.network.offline = true;
    assert.equal(await method.call(pos, disconnected), false);
});
test('a payment added while cancellation waits for draft sync prevents cancellation', async () => {
    let release, started;
    const inFlight = new Promise((resolve) => { release = resolve; });
    const entered = new Promise((resolve) => { started = resolve; });
    const order = { id: 42, uuid: 'draft', state: 'draft', isSynced: true, payment_ids: [],
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true } };
    const pos = { models: {}, data: { network: { offline: false } }, config: { baseer_direct_print_enabled: true },
        notification: { add() {} }, async baseerRunSharedDraftExperiment(value) {
            started(); await inFlight; value.uiState.baseerSharedDraftGeneration = experimentalGeneration;
        } };
    const cancelling = experimentalExtensions.get('PosStore').beforeDeleteOrder.call(pos, order);
    await entered;
    order.payment_ids.push({ uuid: 'bank', amount: 3, payment_status: 'done' });
    release();
    assert.equal(await cancelling, false);
    assert.equal(pos.nativeBeforeDelete, undefined);
    assert.deepEqual(order.payment_ids, [{ uuid: 'bank', amount: 3, payment_status: 'done' }]);
});
test('lost draft synchronization response keeps frozen command and prevents cancellation', async () => {
    const pending = { command_uuid: 'frozen-draft', target_state: 'draft', payload_json: '{"unchanged":true}' };
    const order = { id: 42, uuid: 'draft', state: 'draft', isSynced: true, payment_ids: [],
        uiState: { baseerSharedDraftRevision: 3, baseerSharedDraftRemoveRequested: true } };
    const pos = { models: {}, data: { network: { offline: false } }, config: { baseer_direct_print_enabled: true },
        notification: { add() {} }, async baseerRunSharedDraftExperiment(value) {
            value.uiState.baseerSharedDraftPending = structuredClone(pending);
            throw new ConnectionLostError();
        } };
    assert.equal(await experimentalExtensions.get('PosStore').beforeDeleteOrder.call(pos, order), false);
    assert.equal(pos.nativeBeforeDelete, undefined);
    assert.deepEqual(order.uiState.baseerSharedDraftPending, pending);
    assert.equal(order.uiState.baseerSharedDraftRevision, 3);
});
test('restored kitchen cancellation with lost ACK retries its frozen intent before server preview', async () => {
    const moduleSource = readFileSync(new URL('../static/src/app/draft_snapshot_experiment.js', import.meta.url), 'utf8');
    const flow = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`);
    const failureMocks = mocks.replace('async beforeDeleteOrder() { this.nativeBeforeDelete = true; return true; }',
        'async beforeDeleteOrder() { throw new Error("already cancelled on server"); }')
        .replace('const cancelGraphUnchanged = (order, pending, tracker) => tracker.get() === pending.generation;',
            'const cancelGraphUnchanged = actualGraphCheck;');
    const installed = new Function('attachDraftGenerationExperiment', 'kitchenCancelIntent', 'actualGraphCheck',
        `${failureMocks}\n${source.replace('const SHARED_DRAFT_FLOW_ENABLED = false;', 'const SHARED_DRAFT_FLOW_ENABLED = true;')}\nreturn extensions;`)(
        () => ({ get: () => 5 }), (saved) => saved, flow.cancelGraphUnchanged);
    const order = { id: 42, uuid: 'draft', isSynced: true, state: 'draft', baseer_offline_draft_revision: 3,
        lines: [], payment_ids: [], uiState: { baseerOfflineDiscount: { value: 1 } },
        serializeForIndexedDB() { return { uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } };
    const graph_fingerprint = flow.cancelGraphFingerprint(order);
    order.uiState.baseerSharedDraftCancelPending = { order_uuid: 'draft', revision: 3, command_uuid: 'same', generation: 4, graph_fingerprint };
    order.uiState.baseerSharedDraftKitchenCancelIntent = { session_id: 27, reason_code: 'wrong_order', reason_note: '' };
    const pos = { config: { baseer_direct_print_enabled: true, current_session_id: 27 }, models: {}, notification: { add() {} },
        baseerRecoverChangedCancellation: async () => { throw new Error('needs review'); } };
    order.uiState.selected_orderline_uuid = 'another-selection';
    order.uiState.baseerSharedDraftRemoteDeleted = true;
    order.uiState.baseerSharedDraftRefreshError = 'remote deleted';
    order.uiState.baseerSharedDraftNeedsSync = true;
    assert.equal(await installed.get('PosStore').beforeDeleteOrder.call(pos, order), true);
    assert.equal(order.uiState.baseerSharedDraftCancelPending.command_uuid, 'same');
    assert.equal(order.uiState.baseerSharedDraftKitchenCancelIntent.reason_code, 'wrong_order');
    order.uiState.baseerOfflineDiscount.value = 2;
    assert.equal(await installed.get('PosStore').beforeDeleteOrder.call(pos, order), false, 'own unsynchronized change stays protected');
    order.uiState.baseerOfflineDiscount.value = 1;
    delete order.uiState.baseerSharedDraftRemoteDeleted;
    assert.equal(await installed.get('PosStore').beforeDeleteOrder.call(pos, order), false, 'ordinary unsynchronized edits still need review');
    order.uiState.baseerSharedDraftRemoteDeleted = true;
    delete order.uiState.baseerSharedDraftCancelPending.graph_fingerprint;
    assert.equal(await installed.get('PosStore').beforeDeleteOrder.call(pos, order), false, 'legacy without graph proof stays protected');
});
test('experimental print marker verifies the acknowledged revision and current generation', async () => {
    const order = { uuid: 'draft', state: 'draft', uiState: { baseerOfflineDiscount: {} } };
    let generation = 4;
    const pos = { models: { _baseerDraftGenerationTracker: { get: () => generation } }, notification: { add() {} },
        async baseerRunSharedDraftExperiment() {
            order.uiState.baseerSharedDraftRevision = 7;
            order.uiState.baseerSharedDraftGeneration = generation;
            order.uiState.baseerSharedDraftNeedsSync = false;
        } };
    const methods = experimentalExtensions.get('PosStore');
    const marker = await methods.baseerPrepareSharedDraftPrintExperiment.call(pos, order);
    assert.deepEqual(marker, { uuid: 'draft', revision: 7, generation: 4 });
    assert.equal(methods.baseerIsSharedDraftPrintCurrentExperiment.call(pos, order, marker), true);
    generation++;
    assert.equal(methods.baseerIsSharedDraftPrintCurrentExperiment.call(pos, order, marker), false);
    order.uiState.baseerSharedDraftNeedsSync = true;
    assert.equal(await methods.baseerPrepareSharedDraftPrintExperiment.call({ ...pos, async baseerRunSharedDraftExperiment() {} }, order), false);
});
test('experimental paid ACK awaiting reconciliation cannot download or print a final invoice', async () => {
    const order = { state: 'paid', uiState: { baseerSharedDraftPaidAckPending: true } };
    const validation = { order };
    const payment = experimentalExtensions.get('OrderPaymentValidation');
    assert.equal(payment.shouldDownloadInvoice.call(validation), false);
    assert.equal(Object.getOwnPropertyDescriptor(payment, 'canPrintReceipt').get.call(validation), false);
    const notices = [];
    const pos = { getOrder: () => order, notification: { add: (message) => notices.push(message) } };
    assert.deepEqual(await experimentalExtensions.get('PosStore').printReceipt.call(pos, { order }), { successful: false });
    assert.match(notices[0], /awaiting server confirmation/);
});
test('a locked invoiced order with unreconciled paid ACK stays protected and queued after restart', () => {
    const order = { state: 'invoiced', baseer_global_discount_locked: true, uiState: { baseerSharedDraftPaidAckPending: true } };
    const model = experimentalExtensions.get('PosOrder');
    assert.equal(Object.getOwnPropertyDescriptor(model, 'canBeRemovedFromIndexedDB').get.call(order), false);
    assert.equal(Object.getOwnPropertyDescriptor(model, 'isUnsyncedPaid').get.call(order), true);
});
test('invoice verification clears the pending marker only for a matching posted move', async () => {
    const order = { id: 42, uuid: 'order', account_move: { id: 77 }, lines: [], payment_ids: [],
        uiState: { baseerSharedDraftInvoicePending: true }, serializeForIndexedDB() { return { uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } };
    const data = { indexedDB: {}, orm: { read: async () => { throw new Error('access denied'); } } };
    const pos = { data, models: {}, notification: { add() {} } };
    const method = experimentalExtensions.get('PosStore').baseerVerifySharedInvoiceExperiment;
    assert.equal(await method.call(pos, order), false);
    assert.equal(order.uiState.baseerSharedDraftInvoicePending, true);
    data.orm.read = async () => [{ id: 77, state: 'draft' }];
    assert.equal(await method.call(pos, order), false);
    assert.equal(order.uiState.baseerSharedDraftInvoicePending, true);
    data.orm.read = async () => [{ id: 77, state: 'posted' }];
    assert.equal(await method.call(pos, order), true);
    assert.equal(order.uiState.baseerSharedDraftInvoicePending, false);
});
test('offline startup uses only matching open cached session and config', async () => {
    const data = { indexedDB: { readAll: async () => ({ 'pos.order': [{ uiState: { baseerOfflineDiscount: {} } }] }) }, network: { offline: true }, getCachedServerDataFromIndexedDB: async () => ({
        'pos.config': [{ id: 2 }], 'pos.session': [{ id: 27, config_id: 2, state: 'opened' }],
    }) };
    const extension = extensions.get('PosData');
    assert.equal((await extension.loadInitialData.call(data))['pos.config'][0].id, 2);
    data.getCachedServerDataFromIndexedDB = async () => ({ 'pos.config': [{ id: 2 }], 'pos.session': [{ id: 27, state: 'closed' }] });
    await assert.rejects(() => extension.loadInitialData.call(data), /cannot be verified/);
    data.network.offline = false;
    assert.equal((await extension.loadInitialData.call(data)).native, true);
    data.getCachedServerDataFromIndexedDB = async () => ({ 'pos.config': [{ id: 2 }], 'pos.session': [{ id: 27, config_id: 2, state: 'opened' }] });
    setPingError(new ConnectionLostError());
    assert.equal((await extension.loadInitialData.call(data))['pos.session'][0].id, 27);
    assert.equal(data.network.offline, true);
    setPingError();
});
test('server connection loss preserves local orders; other failures still propagate', async () => {
    const extension = extensions.get('PosData');
    const paid = { state: 'paid', uiState: { baseerOfflineDiscount: {} } };
    const draft = { state: 'draft', id: 42 };
    const data = { network: { offline: false }, failure: new ConnectionLostError() };
    await extension.checkAndDeleteMissingOrders.call(data, { 'pos.order': [paid, draft] });
    assert.equal(data.network.offline, true);
    assert.equal(paid.state, 'paid');
    assert.equal(draft.id, 42);
    data.network.offline = false;
    data.failure = new RPCError();
    await assert.rejects(() => extension.checkAndDeleteMissingOrders.call(data, { 'pos.order': [draft] }), RPCError);
});

test('shared draft hydration error blocks both payment validation paths without changing the basket', async () => {
    const saved = { uiState: { baseerSharedDraftHydrationError: 'verify server draft' }, lines: [{ uuid: 'source' }, { uuid: 'server-allowance' }] };
    const alerts = [];
    const screen = { currentOrder: saved, dialog: { add: (_type, values) => alerts.push(values.body) } };
    await extensions.get('PaymentScreen').validateOrder.call(screen);
    const validation = { order: saved, pos: { dialog: { add: (_type, values) => alerts.push(values.body) } } };
    assert.equal(await extensions.get('OrderPaymentValidation').validateOrder.call(validation), false);
    assert.deepEqual(saved.lines.map((line) => line.uuid), ['source', 'server-allowance']);
    assert.deepEqual(alerts, ['verify server draft', 'verify server draft']);
    assert.equal(screen.nativeCalled, undefined);
});
test('server lost after ping marks offline; native RPC errors are not hidden', async () => {
    const extension = extensions.get('PosData');
    const cached = { 'pos.config': [{ id: 2 }], 'pos.session': [{ id: 27, config_id: 2, state: 'opened' }] };
    const originalOrm = { async call() { throw new ConnectionLostError(); } };
    const data = { indexedDB: { readAll: async () => ({ 'pos.order': [{ uiState: { baseerOfflineDiscount: {} } }] }) }, network: { offline: false }, orm: originalOrm, async loadNative() {
        try { await this.orm.call('pos.session', 'load_data', []); } catch (error) { this.nativeError = error; }
        return cached;
    } };
    assert.equal(await extension.loadInitialData.call(data), cached);
    assert.equal(data.network.offline, true);
    assert.ok(data.nativeError instanceof ConnectionLostError);
    assert.equal(data.orm, originalOrm);
    data.network.offline = false;
    originalOrm.call = async () => { throw new RPCError(); };
    assert.equal(await extension.loadInitialData.call(data), cached);
    assert.equal(data.network.offline, false);
    assert.ok(data.nativeError instanceof RPCError);
    assert.equal(data.orm, originalOrm);
});
const storageKey = "qa:2:order";
function order(pending = false) {
    memory.clear();
    if (pending) memory.set(storageKey, "pending-intent");
    return { config_id: { id: 2 }, uuid: "order", baseer_global_discount_locked: !pending };
}
test("quantity and removal are frozen during an unknown discount response", () => {
    const draft = order(true);
    const line = { order_id: draft, qty: 1 };
    assert.equal(extensions.get("PosOrderline").setQuantity.call(line, 2), false);
    assert.equal(line.nativeCalled, undefined);
    assert.equal(extensions.get("PosOrder").removeOrderline.call(draft, {}), false);
    assert.equal(draft.nativeCalled, undefined);
});

test("native repeated combo returns link only current return children", () => {
    const sale = { baseer_global_discount_locked: true };
    const source = { order_id: sale, combo_line_ids: [{}] };
    const current = { is_refund: true };
    const historical = { is_refund: true };
    const childSource = { combo_parent_id: source };
    const child = { order_id: current, refunded_orderline_id: childSource };
    const oldChild = { order_id: historical, refunded_orderline_id: childSource };
    const foreignChild = { order_id: current, refunded_orderline_id: { combo_parent_id: {} } };
    const parent = { order_id: current, refunded_orderline_id: source };
    extensions.get("PosOrderline").update.call(parent, {
        combo_line_ids: [["link", oldChild, child, foreignChild]], qty: -1,
    });
    assert.deepEqual(parent.updated.combo_line_ids, [["link", child]]);
    assert.equal(parent.updated.qty, -1);
    assert.equal(oldChild.order_id, historical);
    const native = { order_id: current, refunded_orderline_id: { ...source, order_id: {} } };
    const values = { combo_line_ids: [["link", child, oldChild]] };
    extensions.get("PosOrderline").update.call(native, values);
    assert.equal(native.updated, values, "unmanaged historical orders retain native behavior");
});
test("fiscal position action is blocked before native direct tax assignment", async () => {
    const calls = [];
    const control = { currentOrder: order(), pos: { dialog: { add: (...args) => calls.push(args) } } };
    await extensions.get("ControlButtons").clickFiscalPosition.call(control);
    assert.equal(control.nativeCalled, undefined);
    assert.equal(calls.length, 1);
});
test("owned discounts never trigger native automatic percentage reapplication", async () => {
    for (const scenario of ["locked", "refund"]) {
        const pos = { config: { baseer_global_discount_enabled: true } };
        const draft = { baseer_global_discount_locked: scenario === "locked", needsRefund: scenario === "refund" };
        await extensions.get("PosStore").applyDiscount.call(pos, 10, draft);
        assert.equal(pos.nativeCalled, undefined, scenario);
    }
    const normal = { config: {} };
    await extensions.get("PosStore").applyDiscount.call(normal, 10, {});
    assert.equal(normal.nativeCalled, true);
});
test("enabling the new feature preserves native historical discount refunds", async () => {
    const pos = { config: { baseer_global_discount_enabled: true } };
    const historicalRefund = { baseer_global_discount_locked: false, needsRefund: false };
    await extensions.get("PosStore").applyDiscount.call(pos, 10, historicalRefund);
    assert.equal(pos.nativeCalled, true);
});
test("native percentage reapplication waits for a managed command with an unknown result", async () => {
    const pending = order(true);
    const pos = { config: { baseer_global_discount_enabled: true } };
    await extensions.get("PosStore").applyDiscount.call(pos, 10, pending);
    assert.equal(pos.nativeCalled, undefined);
});
test("refund picker excludes standalone allowances and explains manual selection", () => {
    const allowance = { id: 2, baseer_global_discount_line: true };
    const regular = { id: 1 };
    const screen = {
        details: [{ line: regular }, { line: allowance }],
        getSelectedOrder: () => ({ lines: [regular, allowance] }), getSelectedOrderlineId: () => 2,
        dialog: { add: () => { screen.explained = true; } },
    };
    assert.deepEqual(extensions.get("TicketScreen")._getRefundableDetails.call(screen), [{ line: regular }]);
    extensions.get("TicketScreen")._onUpdateSelectedOrderline.call(screen);
    assert.equal(screen.nativeCalled, undefined);
    assert.equal(screen.explained, true);
});
test("payment waits for confirmation and original-discount refund preparation", async () => {
    for (const scenario of ["pending", "running", "unprepared-refund"]) {
        const draft = order(scenario === "pending");
        draft.baseer_global_discount_locked = false;
        draft.needsRefund = scenario === "unprepared-refund";
        const screen = {
            currentOrder: draft,
            pos: { _baseerDiscountRunning: scenario === "running", baseerDiscountKey: () => storageKey },
            dialog: { add: () => { screen.explained = true; } },
        };
        await extensions.get("PaymentScreen").validateOrder.call(screen);
        assert.equal(screen.nativeCalled, undefined, scenario);
        assert.equal(screen.explained, true, scenario);
    }
});
test("discount opens as a fixed amount and submits without a reason prompt", () => {
    const dialog = new BaseerGlobalDiscountDialog();
    dialog.setup();
    assert.equal(dialog.state.kind, "fixed");
    let payload;
    let closed = false;
    dialog.props = { getPayload: (value) => { payload = value; }, close: () => { closed = true; } };
    dialog.state.value = "20";
    dialog.confirm();
    assert.deepEqual(payload, { kind: "fixed", value: "20" });
    assert.equal(closed, true);
    const xml = readFileSync(new URL("../static/src/app/global_discount.xml", import.meta.url), "utf8");
    assert.equal(xml.includes("baseer-discount-reason"), false);
    assert.equal(xml.includes("baseer-global-discount"), false, "reuse the original native button instead of adding a second one");
    assert.ok(xml.includes("hasclass('js_discount')"));
});

test("paid offline order with numeric server id remains eligible for local persistence and restart queue", () => {
    const draft = { id: 42, state: "paid", baseer_global_discount_locked: false, uiState: { baseerOfflineDiscount: { version: 1 } } };
    const extension = extensions.get("PosOrder");
    assert.equal(Object.getOwnPropertyDescriptor(extension, "canBeRemovedFromIndexedDB").get.call(draft), false);
    assert.equal(Object.getOwnPropertyDescriptor(extension, "isUnsyncedPaid").get.call(draft), true);
});

test("failed offline synchronization preserves locally paid state and does not ask for payment again", async () => {
    for (const ErrorType of [ConnectionLostError, RPCError]) {
        const calls = [];
        const saved = { id: 42, state: "paid", uiState: { baseerOfflineDiscount: { version: 1 } } };
        saved.uuid = "order-1";
        const validation = { order: saved, pos: { addPendingOrder: (ids) => calls.push(["queue", ...ids]), data: { indexedDB: {}, synchronizeLocalDataInIndexedDB: async () => calls.push(["save"]) }, dialog: { add: () => calls.push(["manager"]) } }, afterOrderValidation: async () => calls.push(["offline"]) };
        await extensions.get("OrderPaymentValidation").handleValidationError.call(validation, new ErrorType());
        assert.equal(saved.state, "paid");
        assert.deepEqual(calls.slice(0, 2), [["queue", 42], ["save"]]);
        assert.equal(calls.at(-1)[0], ErrorType === RPCError ? "manager" : "offline");
    }
});

test("storage failure leaves paid order on screen and never reports completion", async () => {
    const calls = [];
    const saved = { id: 42, uuid: "order-1", state: "paid", uiState: { baseerOfflineDiscount: { version: 1 } } };
    const validation = { order: saved, pos: { addPendingOrder: () => calls.push("queue"),
        data: { indexedDB: {}, synchronizeLocalDataInIndexedDB: async () => { throw new Error("quota"); } },
        dialog: { add: () => calls.push("manager") } }, afterOrderValidation: async () => calls.push("receipt") };
    await assert.rejects(() => extensions.get("OrderPaymentValidation").handleValidationError.call(validation, new ConnectionLostError()), /quota/);
    assert.equal(saved.state, "paid");
    assert.deepEqual(calls, ["queue", "manager"]);
});

test("offline preview preserves already-mapped tax IDs instead of applying the fiscal position twice", () => {
    const line = { uuid: "preview", tax_ids: ["already-mapped"], order_id: { uiState: { baseerOfflineDiscount: { preview_line_uuids: ["preview"] } } } };
    assert.deepEqual(extensions.get("PosOrderline").prepareBaseLineForTaxesComputationExtraValues.call(line).tax_ids, ["already-mapped"]);
    line.uuid = "ordinary";
    assert.deepEqual(extensions.get("PosOrderline").prepareBaseLineForTaxesComputationExtraValues.call(line).tax_ids, ["mapped-again"]);
});

test("background RPC failure cannot trigger native server-draft reload over a locally paid order", async () => {
    const calls = [];
    const paid = { state: "paid", uiState: { baseerOfflineDiscount: {} }, baseer_global_discount_locked: false };
    const pos = { getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [paid] }), notification: { add: () => calls.push("manager") },
        nativeSync: async (options) => { calls.push(options.throw ? "throw" : "reload-risk"); throw new RPCError(); } };
    assert.deepEqual(await extensions.get("PosStore").syncAllOrders.call(pos, {}), []);
    assert.deepEqual(calls, ["manager"]);
    assert.equal(paid.state, "paid");
});

test("startup verification excludes numeric-id paid offline order while retaining ordinary native orders", async () => {
    const pending = { id: 42, uuid: "paid", state: "paid", uiState: { baseerOfflineDiscount: {} } };
    const ordinary = { id: 43, uuid: "draft", state: "draft", uiState: {} };
    const data = {};
    await extensions.get("PosData").checkAndDeleteMissingOrders.call(data, { "pos.order": [pending, ordinary] });
    assert.deepEqual(data.forwarded["pos.order"], [ordinary]);
    pending.baseer_global_discount_locked = true;
    await extensions.get("PosData").checkAndDeleteMissingOrders.call(data, { "pos.order": [pending, ordinary] });
    assert.deepEqual(data.forwarded["pos.order"], [pending, ordinary]);
});

test("device updates and deletions cannot overwrite locally paid order or children before server acknowledgement", async () => {
    const pending = { id: 42, uuid: "paid", state: "paid", uiState: { baseerOfflineDiscount: {} }, lines: [{ id: 10, custom_attribute_value_ids: [{ id: 30 }] }], payment_ids: [{ id: 20 }] };
    const sync = { models: { "pos.order": { getAll: () => [pending] } } };
    const incoming = { "pos.order": [{ id: 42, uuid: "paid", state: "draft" }, { id: 43, uuid: "ordinary" }],
        "pos.order.line": [{ id: 10, order_id: 42 }, { id: 11, order_id: [42, "server"] }, { id: 12, order_id: 43 }],
        "pos.payment": [{ id: 20, pos_order_id: 42 }, { id: 21, pos_order_id: 43 }],
        "product.attribute.custom.value": [{ id: 30, pos_order_id: 42 }, { id: 31, pos_order_id: 43 }] };
    const extension = extensions.get("DevicesSynchronisation");
    await extension.processDynamicRecords.call(sync, incoming);
    assert.deepEqual(sync.forwarded["pos.order"].map((record) => record.id), [43]);
    assert.deepEqual(sync.forwarded["pos.order.line"].map((record) => record.id), [12]);
    assert.deepEqual(sync.forwarded["pos.payment"].map((record) => record.id), [21]);
    assert.deepEqual(sync.forwarded["product.attribute.custom.value"].map((record) => record.id), [31]);
    extension.processDeletedRecords.call(sync, { "pos.order": [42, 43], "pos.order.line": [10, 12], "pos.payment": [20, 21] });
    assert.deepEqual(sync.forwarded, { "pos.order": [43], "pos.order.line": [12], "pos.payment": [21] });
    pending.baseer_global_discount_locked = true;
    await extension.processDynamicRecords.call(sync, incoming);
    assert.equal(sync.forwarded, incoming, "acknowledged orders follow native synchronization");
});

test("native cache reset cannot delete the database shared with other registers", async () => {
    const extension = extensions.get("PosData");
    const data = { indexedDB: { readAll: async () => ({ "pos.order": [{ uiState: { baseerOfflineDiscount: {} } }] }) } };
    await assert.rejects(() => extension.resetIndexedDB.call(data), /local point-of-sale data cannot be verified/);
    assert.equal(data.resetCalled, undefined);
});

test('POS startup loads the replacement session while preserving an old session draft', async () => {
    const extension = extensions.get('PosData');
    const draft = { id: 42, uuid: 'saved-draft', state: 'draft' };
    const previous = {
        'pos.config': [{ id: 2, _data_server_date: '2026-11-24 11:00:00' }],
        'pos.session': [{ id: 26, config_id: 2, state: 'closed' }],
    };
    const fresh = {
        'pos.config': [{ id: 2 }],
        'pos.session': [{ id: 27, config_id: 2, state: 'opened' }],
    };
    globalThis.window = { location: { href: 'https://test.invalid/pos/ui/2' } };
    try {
        let reads = 0;
        const data = {
            network: { offline: false },
            opts: { databaseTable: { 'pos.order': {} } },
            indexedDB: {
                readAll: async (tables) => tables.includes('pos.order') ? { 'pos.order': [{ uiState: { baseerOfflineDiscount: {} } }] } : previous,
                db: {
                    objectStoreNames: { contains: () => true },
                    transaction(models, mode) {
                        assert.deepEqual(models, ['pos.config', 'pos.session']);
                        assert.equal(mode, 'readwrite');
                        const tx = { objectStore: () => ({ clear() {}, put() {} }) };
                        queueMicrotask(() => tx.oncomplete());
                        return tx;
                    },
                },
            },
            getCachedServerDataFromIndexedDB: async () => previous,
            isLimitedLoading: () => true,
            loadNative: () => { assert.fail('native startup would clear the order store'); },
            orm: { call: async (model, method, args, { context }) => {
                reads++;
                assert.equal(model, 'pos.session');
                assert.equal(method, 'load_data');
                assert.equal(args[0], 27);
                assert.deepEqual(context, { pos_last_server_date: false, pos_limited_loading: true });
                return fresh;
            } },
        };
        assert.equal(await extension.loadInitialData.call(data), fresh);
        assert.equal(reads, 1);
        assert.equal(data.resetCalled, undefined);
        assert.deepEqual(draft, { id: 42, uuid: 'saved-draft', state: 'draft' });
        data.orm.call = async () => previous;
        await assert.rejects(() => extension.loadInitialData.call(data), /current point-of-sale session could not be verified/);
        data.orm.call = async () => { throw new ConnectionLostError(); };
        await assert.rejects(() => extension.loadInitialData.call(data), /local point-of-sale data cannot be verified/);
        assert.equal(data.network.offline, true);
    } finally {
        delete globalThis.window;
    }
});

test('manual refresh waits for the live payment before navigating to a non-destructive reload', async () => {
    const order = {
        id: 42, uuid: 'sale', state: 'paid', isUnsyncedPaid: true, uiState: { baseerSharedDraftPaidAckPending: true },
        serializeForIndexedDB: () => ({ uuid: 'sale', JSONuiState: '{"selected_paymentline_uuid":"payment","baseerSharedDraftPaidAckPending":true}' }),
    };
    const payment = { uuid: 'payment', amount: 3, pos_order_id: order.id };
    const pos = {
        data: {
            network: { offline: false },
            opts: { databaseTable: {
                'pos.order': { condition: () => true, key: 'uuid' },
                'pos.payment': { condition: () => true, key: 'uuid' },
            } },
            models: {
                'pos.order': { getAll: () => [order] },
                'pos.payment': { getAll: () => [{ pos_order_id: order, serializeForIndexedDB: () => ({ ...payment }) }] },
            },
            indexedDB: { readAll: async () => ({ 'pos.payment': [] }) },
        },
        models: { 'pos.order': { getAll: () => [order] } },
        device: { saveUnusedNumber() {} },
        notification: { add(message) { this.message = message; } },
        syncingOrders: new Set(),
    };
    const original = 'https://test.invalid/pos/ui/2';
    globalThis.window = { location: { href: original } };
    try {
        const refresh = extensions.get('PosStore').reloadData;
        await refresh.call(pos, true);
        assert.equal(window.location.href, original);
        assert.match(pos.notification.message, /wait for orders to finish saving/);
        const stored = { 'pos.order': [{ uuid: 'sale', JSONuiState: '{"baseerSharedDraftPaidAckPending":true}' }], 'pos.payment': [{ ...payment }] };
        pos.data.indexedDB.readAll = async () => {
            payment.amount = 4;
            return stored;
        };
        await refresh.call(pos, true);
        assert.equal(window.location.href, original);
        payment.amount = 3;
        pos.data.indexedDB.readAll = async () => stored;
        await refresh.call(pos, true);
        assert.equal(window.location.href, original + '?baseer_preserve_local_orders=1&limited_loading=0');
    } finally {
        delete globalThis.window;
    }
});

test("late native cleanup cannot delete paid offline keys but leaves unrelated cleanup unchanged", () => {
    const indexed = { _baseerOfflineProtection: new Map([["one", { "pos.order": new Set(["protected"]), "pos.payment": new Set(["pay"]) }]]) };
    const extension = extensions.get("IndexedDB");
    assert.deepEqual(extension.delete.call(indexed, "pos.order", ["protected", "ordinary"]), { store: "pos.order", keys: ["ordinary"] });
    assert.deepEqual(extension.delete.call(indexed, "pos.payment", ["pay", "other"]), { store: "pos.payment", keys: ["other"] });
    indexed._baseerOfflineProtection.clear();
    assert.deepEqual(extension.delete.call(indexed, "pos.order", ["protected"]), { store: "pos.order", keys: ["protected"] });
});

test("startup offline restores the full local paid graph and rejects missing line or product", async () => {
    const intent = { kind: "fixed" };
    const order = { id: 42, state: "paid", JSONuiState: JSON.stringify({ baseerOfflineDiscount: intent }), lines: ["line"], payment_ids: ["payment"] };
    const records = { "pos.order": [order], "pos.order.line": [{ id: "line", product_id: 10 }], "pos.payment": [{ id: "payment" }] };
    const data = { _baseerRestoringLocalData: true, network: { offline: true }, models: { "product.product": { getAll: () => [{ id: 10 }] } } };
    const extension = extensions.get("PosData");
    assert.deepEqual(await extension.missingRecursive.call(data, records), records);
    await assert.rejects(() => extension.missingRecursive.call(data, { ...records, "pos.order.line": [] }), /incomplete/);
    data.models["product.product"].getAll = () => [];
    await assert.rejects(() => extension.missingRecursive.call(data, records), /incomplete/);
    data._baseerRestoringLocalData = false;
    assert.deepEqual(await extension.missingRecursive.call(data, records), { native: true });
});

test('ordinary offline draft restoration follows native behavior', async () => {
    const records = { 'pos.order': [{ id: 42, state: 'draft', lines: ['line'], payment_ids: [] }],
        'pos.order.line': [{ id: 'line', product_id: 10 }], 'pos.payment': [] };
    const data = { _baseerRestoringLocalData: true, network: { offline: true }, models: { 'product.product': { getAll: () => [{ id: 10 }] } } };
    const extension = extensions.get('PosData');
    assert.deepEqual(await extension.missingRecursive.call(data, records), { native: true });
    assert.deepEqual(await extension.missingRecursive.call(data, { ...records, 'pos.order.line': [] }), { native: true });
});

test("restored paid numeric-id order is made dirty before native pending synchronization", async () => {
    const child = (uuid) => ({ uuid, _dirty: false, custom_attribute_value_ids: [], _markDirty() { this._dirty = true; } });
    const restored = { id: 42, uuid: "paid", state: "paid", _dirty: false,
        uiState: { baseerOfflineDiscount: {} }, lines: [child("line")],
        payment_ids: [child("payment")], _markDirty() { this._dirty = true; } };
    const data = { indexedDB: {}, localResult: { "pos.order": [restored] } };
    const result = await extensions.get("PosData").getLocalDataFromIndexedDB.call(data);
    assert.equal(result["pos.order"][0]._dirty, true);
    assert.equal(restored.lines[0]._dirty, true);
    assert.equal(restored.payment_ids[0]._dirty, true);
    assert.equal(data.indexedDB._baseerOfflineProtection.get("paid")["pos.payment"].has("payment"), true);
    // Native syncAllOrders includes queued records only if dirty or forced.
    assert.equal([restored].filter((order) => order._dirty).length, 1);
});

test('restored discounted draft queues before startup sync and sends changed lines plus stored deletions', async () => {
    const kept = { id: 11, uuid: 'kept', value: 100, _markDirty() { this._dirty = true; }, custom_attribute_value_ids: [] };
    const preview = { id: 'preview', uuid: 'preview', value: -10, _markDirty() { this._dirty = true; }, custom_attribute_value_ids: [] };
    const intent = { version: 1, preview_line_uuids: ['preview'], removed_line_ids: [12], removed_payment_ids: [] };
    const draft = { id: 42, uuid: 'draft', state: 'draft', config_id: { id: 2 }, uiState: { baseerOfflineDiscount: intent },
        lines: [kept, preview], payment_ids: [], _markDirty() { this._dirty = true; } };
    const extension = extensions.get('PosData');
    const restored = { indexedDB: {}, localResult: { 'pos.order': [draft] } };
    await extension.getLocalDataFromIndexedDB.call(restored);
    assert.equal(draft._dirty, true);
    assert.equal(kept._dirty, true);
    assert.equal(restored.indexedDB._baseerOfflineProtection.get('draft')['pos.order.line'].has('kept'), true);
    let payload;
    const pos = { models: { 'pos.order': { getAll: () => [draft] } }, addPendingOrder(ids) { this.pending = ids; },
        async nativeStartup() {
            assert.deepEqual(this.pending, [42]);
            payload = extensions.get('PosOrder').serializeForORM.call(draft, { keepCommands: true });
        } };
    await experimentalExtensions.get('PosStore').afterProcessServerData.call(pos);
    assert.ok(payload.lines.some((command) => command[0] === 1 && command[1] === 11));
    assert.ok(payload.lines.some((command) => command[0] === 2 && command[1] === 12));
    assert.deepEqual(intent.removed_line_ids, [12]);
    assert.deepEqual(intent.sent_deletions.lines, [12]);
});

test("synced child deletions survive in the local intent and become native ORM delete commands", () => {
    const intent = { preview_line_uuids: [], version: 1 };
    const order = { uuid: "order", id: 42, state: "draft", config_id: { id: 2 }, uiState: { baseerOfflineDiscount: intent }, lines: [], payment_ids: [], _markDirty() {} };
    const line = { id: 11, uuid: "line", order_id: order };
    const payment = { id: 21, pos_order_id: order };
    extensions.get("PosOrderline").delete.call(line);
    extensions.get("PosPayment").delete.call(payment);
    assert.deepEqual(intent.removed_line_ids, [11]);
    assert.deepEqual(intent.removed_payment_ids, [21]);
    const serialized = extensions.get("PosOrder").serializeForORM.call(order, { keepCommands: true });
    assert.deepEqual(serialized.lines, [[2, 11]]);
    assert.deepEqual(serialized.payment_ids, [[2, 21]]);
    assert.deepEqual(intent.sent_deletions, { lines: [11], payment_ids: [21] });
});

test('tracked draft deletions explicitly mark financial uiState mutations', () => {
    let touches = 0;
    const intent = { preview_line_uuids: [] };
    const order = { state: 'draft', uiState: { baseerOfflineDiscount: intent }, models: { _baseerDraftGenerationTracker: { touch: () => { touches++; } } }, _markDirty() {} };
    extensions.get('PosOrderline').delete.call({ id: 11, uuid: 'line', order_id: order });
    extensions.get('PosPayment').delete.call({ id: 21, pos_order_id: order });
    assert.equal(touches, 2);
    assert.deepEqual(intent.removed_line_ids, [11]);
    assert.deepEqual(intent.removed_payment_ids, [21]);
});

test('experimental mapped local-UUID line and payment deletions become server-ID commands', () => {
    let touches = 0;
    const intent = { preview_line_uuids: [] };
    const order = { id: 42, uuid: 'order', state: 'draft', config_id: { id: 2 }, lines: [], payment_ids: [],
        uiState: { baseerOfflineDiscount: intent, baseerSharedDraftLineIds: { line: 11 }, baseerSharedDraftPaymentIds: { pay: 21 } },
        models: { _baseerDraftGenerationTracker: { touch: () => { touches++; } } }, _markDirty() {} };
    extensions.get('PosOrderline').delete.call({ id: 'line', uuid: 'line', order_id: order });
    extensions.get('PosPayment').delete.call({ id: 'pay', uuid: 'pay', pos_order_id: order });
    const sent = extensions.get('PosOrder').serializeForORM.call(order, { keepCommands: true });
    assert.ok(sent.lines.some((command) => command[0] === 2 && command[1] === 11));
    assert.ok(sent.payment_ids.some((command) => command[0] === 2 && command[1] === 21));
    assert.equal(touches, 2);
    order.lines.push({ id: 'line', uuid: 'line' });
    assert.throws(() => extensions.get('PosOrder').serializeForORM.call(order, { keepCommands: true }), /needs manager review/);
});
test('experimental removal command keeps source deletion events after discount intent is removed', () => {
    const order = { id: 42, uuid: 'order', state: 'draft', config_id: { id: 2 }, lines: [], payment_ids: [],
        uiState: { baseerSharedDraftRevision: 2, baseerSharedDraftLineDeletions: [{ id: 11, token: 'one' }] },
        models: { _baseerDraftGenerationTracker: { get: () => 1 } } };
    const sent = experimentalExtensions.get('PosOrder').serializeForORM.call(order, { keepCommands: true });
    assert.ok(sent.lines.some((command) => command[0] === 2 && command[1] === 11));
    assert.equal(sent.baseer_offline_discount_intent, undefined);
});

test("draft acknowledgment clears only deletions included in that request", async () => {
    const intent = { removed_line_ids: [11, 12], removed_payment_ids: [21, 22],
        sent_deletions: { lines: [11], payment_ids: [21] }, preview_line_uuids: [] };
    const order = { state: "draft", uiState: { baseerOfflineDiscount: intent }, lines: [] };
    await extensions.get("PosStore").postSyncAllOrders.call({ data: { indexedDB: {} } }, [order]);
    assert.deepEqual(intent.removed_line_ids, [12]);
    assert.deepEqual(intent.removed_payment_ids, [22]);
    assert.equal(intent.sent_deletions, undefined);
});

test("paid retry reuses the complete persisted RPC payload unchanged after lost acknowledgement and reload", async () => {
    const child = (id, uuid, value) => ({ id, uuid, value, _dirty: false, _markDirty() { this._dirty = true; } });
    const intent = { version: 1, order_uuid: "order", action_uuid: "action", kind: "fixed", value: "10",
        expected_total: "90.00", expected_tax: "0.00", preview_line_uuids: ["preview"], removed_line_ids: [18] };
    const order = { uuid: "order", id: 42, state: "paid", config_id: { id: 2 }, uiState: { baseerOfflineDiscount: intent },
        lines: [child(11, "item", 100), child("preview", "preview", -10)], payment_ids: [child(21, "payment", 90)] };
    order.serializeForORM = (...args) => extensions.get("PosOrder").serializeForORM.call(order, ...args);
    let savedState;
    const pos = { data: { indexedDB: {}, synchronizeLocalDataInIndexedDB: async () => { savedState = JSON.parse(JSON.stringify(order.uiState)); } }, dialog: { add() {} } };
    await extensions.get("PosStore").preSyncAllOrders.call(pos, [order]);
    const first = order.serializeForORM({ keepCommands: true });
    assert.deepEqual(first.lines.map((line) => line[0]), [1, 0, 2]);
    assert.deepEqual(first.payment_ids.map((line) => line[0]), [1]);
    assert.ok(savedState.baseerOfflineDiscount.retry_payload);
    // A reload resets dirty state; a lost response may also change local IDs.
    order.uiState = savedState;
    order.lines[0].id = 111; order.lines[0]._dirty = false;
    order.payment_ids[0].id = 121; order.payment_ids[0]._dirty = false;
    await extensions.get("PosStore").preSyncAllOrders.call(pos, [order]);
    const retry = order.serializeForORM({ keepCommands: true });
    assert.equal(JSON.stringify(retry), JSON.stringify(first));
});

test("paid sync stops before RPC when immutable payload cannot be persisted", async () => {
    const order = { uuid: "order", id: 42, state: "paid", config_id: { id: 2 },
        uiState: { baseerOfflineDiscount: { preview_line_uuids: [] } }, lines: [], payment_ids: [] };
    order.serializeForORM = (...args) => extensions.get("PosOrder").serializeForORM.call(order, ...args);
    let alert = false;
    const pos = { data: { indexedDB: {}, synchronizeLocalDataInIndexedDB: async () => { throw new Error("quota"); } }, dialog: { add: () => { alert = true; } } };
    await assert.rejects(() => extensions.get("PosStore").preSyncAllOrders.call(pos, [order]), /quota/);
    assert.equal(order.uiState.baseerOfflineDiscount.retry_payload, undefined);
    assert.equal(alert, true);
});

function recoveryFixture(status, payments = []) {
    const methods = experimentalExtensions.get('PosStore');
    const order = { id: 42, uuid: 'sale', state: 'draft', lines: [], payment_ids: payments,
        uiState: { baseerSharedDraftRevision: 1, baseerSharedDraftRefreshError: 'review', baseerSharedDraftNeedsSync: true } };
    const calls = [];
    const pos = Object.assign({}, methods, { config: { id: 2, current_session_id: 27 }, models: {},
        pendingOrder: { create: new Set([42]), write: new Set([42]), delete: new Set([42]) },
        data: { network: { offline: false }, indexedDB: { _baseerOfflineProtection: new Map([['sale', { 'pos.order': new Set(['sale']) }]]),
            async delete(model, keys) { calls.push([model, keys]); } },
            orm: { async call(model, method) { calls.push(method); if (status instanceof Error) throw status; return method === 'baseer_shared_draft_remote_status' ? { sale: status } : true; } },
            localDeleteCascade() { calls.push('removed'); } },
        notification: { add(message) { calls.push(message); } }, getCashier: () => ({ _role: 'manager' }), dialog: {},
    });
    return { pos, order, calls };
}

test('remote cancellation and missing order remove an unpaid local graph', async () => {
    for (const exists of [true, false]) {
        const { pos, order, calls } = recoveryFixture({ exists, state: exists ? 'cancel' : false, payment_count: 0, amount_paid: 0 });
        assert.equal(await pos.baseerTryRemoteRemoval(order), true);
        assert.ok(calls.includes('removed'));
        assert.equal(pos.pendingOrder.write.size, 0);
        assert.equal(pos.data.indexedDB._baseerOfflineProtection.size, 0);
    }
});

test('missing never-synced managed draft is retained without calling removal', async () => {
    const { pos, order, calls } = recoveryFixture({ exists: false, payment_count: 0, amount_paid: 0 });
    order.id = 'local-id';
    order.uiState = { baseerOfflineDiscount: {}, baseerSharedDraftServerOrderId: 0, baseerSharedDraftRevision: 0 };
    let removalCalled = false;
    pos.baseerRemoveLocalCopy = async () => { removalCalled = true; };
    assert.equal(await pos.baseerTryRemoteRemoval(order), false);
    assert.equal(removalCalled, false);
    assert.ok(!calls.includes('removed'));
});

test('missing managed draft is removed for each kind of server evidence', async () => {
    for (const evidence of [
        { id: 42 },
        { uiState: { baseerSharedDraftServerOrderId: 42 } },
        { baseer_offline_draft_revision: 1 },
        { uiState: { baseerSharedDraftRevision: 1 } },
    ]) {
        const { pos, order, calls } = recoveryFixture({ exists: false, payment_count: 0, amount_paid: 0 });
        order.id = evidence.id ?? 'local-id';
        order.baseer_offline_draft_revision = evidence.baseer_offline_draft_revision;
        order.uiState = { baseerOfflineDiscount: {}, ...evidence.uiState };
        assert.equal(await pos.baseerTryRemoteRemoval(order), true);
        assert.ok(calls.includes('removed'));
    }
});

test('server cancellation removes a managed draft even without local server evidence', async () => {
    const { pos, order, calls } = recoveryFixture({ exists: true, state: 'cancel', payment_count: 0, amount_paid: 0 });
    order.id = 'local-id';
    order.uiState = { baseerOfflineDiscount: {} };
    assert.equal(await pos.baseerTryRemoteRemoval(order), true);
    assert.ok(calls.includes('removed'));
});

test('unknown status and existing paid draft retain the local copy', async () => {
    for (const status of [new Error('offline'), { exists: true, state: 'draft', payment_count: 1, amount_paid: 3 }]) {
        const { pos, order, calls } = recoveryFixture(status);
        assert.equal(await pos.baseerTryRemoteRemoval(order), false);
        pos.data.network.offline = true;
        assert.equal(await pos.baseerTryRemoteRemoval(order), false);
        assert.ok(!calls.includes('removed'));
    }
});

test('manager discard audits before removal and retains copy on failure', async () => {
    globalThis.baseerTestConfirm = true;
    const fixture = recoveryFixture({ exists: false, payment_count: 0, amount_paid: 0 }, [{ amount: 3, payment_method_id: { name: 'Bank' } }]);
    assert.equal(await fixture.pos.baseerDiscardLocalCopy(fixture.order), true);
    assert.ok(fixture.calls.indexOf('baseer_log_discarded_local_copy') < fixture.calls.indexOf('removed'));
    const failed = recoveryFixture(new Error('RPC failed'));
    assert.equal(await failed.pos.baseerDiscardLocalCopy(failed.order), false);
    assert.ok(!failed.calls.includes('removed'));
});

test('non-manager is directed to a manager', async () => {
    const { pos, order, calls } = recoveryFixture(new Error('RPC failed'));
    pos.getCashier = () => ({ _role: 'cashier' });
    assert.equal(await pos.beforeDeleteOrder(order), false);
    assert.ok(calls.some((item) => typeof item === 'string' && item.includes('Ask a manager')));
});

test('review notification is limited to one per POS session', async () => {
    const { pos, order, calls } = recoveryFixture(new Error('RPC failed'));
    pos.getPendingOrder = () => ({ orderToCreate: [], orderToUpdate: [] });
    await pos.syncAllOrders({ orders: [order] });
    await pos.syncAllOrders({ orders: [order] });
    assert.equal(calls.filter((item) => typeof item === 'string' && item.startsWith('A saved order needs review')).length, 1);
});

test('cancelled server with local payment remains available for manager review', async () => {
    const { pos, order, calls } = recoveryFixture({ exists: true, state: 'cancel', payment_count: 0, amount_paid: 0 },
        [{ amount: 3, payment_method_id: { name: 'Bank' } }]);
    assert.equal(await pos.baseerTryRemoteRemoval(order), false);
    assert.equal(order.uiState.baseerSharedDraftRemoteDeleted, true);
    assert.ok(!calls.includes('removed'));
});

test('local cascade can remove protected line and payment records', async () => {
    const { pos, order } = recoveryFixture({ exists: false, payment_count: 0, amount_paid: 0 });
    const line = { id: 'line', uuid: 'line', order_id: order };
    const payment = { id: 'payment', uuid: 'payment', pos_order_id: order };
    order.lines = [line]; order.payment_ids = [payment];
    pos.data.localDeleteCascade = () => {
        experimentalExtensions.get('PosOrderline').delete.call(line);
        experimentalExtensions.get('PosPayment').delete.call(payment);
    };
    await pos.baseerRemoveLocalCopy(order);
    assert.equal(line.nativeDeleted, true);
    assert.equal(payment.nativeDeleted, true);
});


test('new order discount button follows native path even with legacy configuration enabled', async () => {
    const order = { uuid: 'new', uiState: {}, lines: [], config_id: { id: 2 } };
    const button = { pos: { config: { baseer_global_discount_enabled: true }, getOrder: () => order,
        baseerDiscountKey: () => 'new-order-key' } };
    await extensions.get('ControlButtons').clickDiscount.call(button);
    assert.equal(button.nativeDiscount, true);
});

test('native server cancellation is forwarded while legacy draft deletion stays guarded', () => {
    const ordinary = { id: 43, uuid: 'ordinary', state: 'draft', uiState: {}, lines: [], payment_ids: [] };
    const legacy = { id: 42, uuid: 'legacy', state: 'draft', uiState: { baseerOfflineDiscount: {} }, lines: [], payment_ids: [] };
    const sync = { models: { 'pos.order': { getAll: () => [ordinary, legacy] } } };
    extensions.get('DevicesSynchronisation').processDeletedRecords.call(sync, { 'pos.order': [42, 43] });
    assert.deepEqual(sync.forwarded['pos.order'], [43]);
    sync.models['pos.order'].getAll = () => [ordinary];
    const native = { 'pos.order': [43] };
    extensions.get('DevicesSynchronisation').processDeletedRecords.call(sync, native);
    assert.equal(sync.forwarded, native);
});

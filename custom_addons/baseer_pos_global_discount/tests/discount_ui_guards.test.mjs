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
const odoo = { pos_config_id: 2, pos_session_id: 27 };
const discountStorageKey = (db, config, uuid) => [db, config, uuid].join(':');
const pendingDiscount = (pos, order) => localStorage.getItem(pos.baseerDiscountKey(order));
const needsDiscountRefund = (order) => order.needsRefund;
const useState = (value) => value;
const useAutofocus = () => {};
class Component {} class Dialog {} class AlertDialog {};
class ControlButtons { clickFiscalPosition() { this.nativeCalled = true; } }
class PosStore { applyDiscount() { this.nativeCalled = true; } async deleteOrders() { this.nativeDeleted = true; return true; } async afterProcessServerData() { return this.nativeStartup(); } async syncAllOrders(options) { return this.nativeSync(options); } async preSyncAllOrders(orders) { return orders; } async postSyncAllOrders() {} }
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
    const data = { network: { offline: true }, getCachedServerDataFromIndexedDB: async () => ({
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
    const data = { network: { offline: false }, orm: originalOrm, async loadNative() {
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
    assert.deepEqual(calls, ["throw", "manager"]);
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

function resetDatabase(records, fail = false) {
    return { transaction() {
        const tx = { objectStore() { return { getAll() {
            const req = {};
            queueMicrotask(() => {
                if (fail) { tx.error = new Error("read failed"); tx.onabort(); return; }
                req.result = records; req.onsuccess(); tx.oncomplete();
            });
            return req;
        } }; } };
        return tx;
    } };
}

test("native cache reset stops before deletion when a paid discount has not synchronized", async () => {
    const extension = extensions.get("PosData");
    const pending = { state: "paid", JSONuiState: JSON.stringify({ baseerOfflineDiscount: { kind: "fixed" } }) };
    const data = { indexedDB: { db: resetDatabase([pending]) } };
    await assert.rejects(() => extension.resetIndexedDB.call(data), /waiting to synchronize/);
    assert.equal(data.resetCalled, undefined);
    const acknowledged = { ...pending, baseer_global_discount_locked: true };
    const draft = { indexedDB: { db: resetDatabase([{ id: 42, state: 'draft' }]) } };
    await assert.rejects(() => extension.resetIndexedDB.call(draft), /locally saved draft/);
    assert.equal(draft.resetCalled, undefined);
    const native = { indexedDB: { db: resetDatabase([acknowledged]) } };
    await extension.resetIndexedDB.call(native);
    assert.equal(native.resetCalled, true);
    const empty = { indexedDB: { db: resetDatabase([]) } };
    await extension.resetIndexedDB.call(empty);
    assert.equal(empty.resetCalled, true);
    const failed = { indexedDB: { db: resetDatabase([], true) } };
    await assert.rejects(() => extension.resetIndexedDB.call(failed), /read failed/);
    assert.equal(failed.resetCalled, undefined);
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

test('offline startup restores draft graph even without a paid discount', async () => {
    const records = { 'pos.order': [{ id: 42, state: 'draft', lines: ['line'], payment_ids: [] }],
        'pos.order.line': [{ id: 'line', product_id: 10 }], 'pos.payment': [] };
    const data = { _baseerRestoringLocalData: true, network: { offline: true }, models: { 'product.product': { getAll: () => [{ id: 10 }] } } };
    const extension = extensions.get('PosData');
    assert.deepEqual(await extension.missingRecursive.call(data, records), records);
    await assert.rejects(() => extension.missingRecursive.call(data, { ...records, 'pos.order.line': [] }), /incomplete/);
    assert.deepEqual(await extension.missingRecursive.call(data, { 'pos.order': [] }), { 'pos.order': [] });
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
    await extensions.get('PosStore').afterProcessServerData.call(pos);
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

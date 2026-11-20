import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

function runtime(nativeCreate) {
    class RPCError extends Error {}
    class PosStore {
        async syncAllOrders(options) { this.nativeSyncs.push(options.orders); return options.orders; }
        handlePreparationHistory() { this.historyCalls = (this.historyCalls || 0) + 1; }
    }
    class SplitBillScreen {
        get currentOrder() { return this.pos.order; }
        getNumberOfProducts() { return 1; }
        get totOrderQty() { return 2; }
        async createSplittedOrder() {
            this.nativeCalls = (this.nativeCalls || 0) + 1;
            return nativeCreate ? nativeCreate.call(this) : 'native';
        }
        async paySplittedOrder() { await this.createSplittedOrder(); this.pos.payCalls = (this.pos.payCalls || 0) + 1; }
    }
    const sandbox = { PosStore, SplitBillScreen, RPCError, _t: (message) => message,
        patch(target, extension) {
            const previous = {};
            Object.defineProperties(previous, Object.getOwnPropertyDescriptors(target));
            Object.setPrototypeOf(extension, previous);
            Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
        } };
    vm.createContext(sandbox);
    const source = readFileSync(new URL('../static/src/app/native_split.js', import.meta.url), 'utf8');
    vm.runInContext(source.replace(/^import .*;\r?\n/gm, '').replace('export function ', 'function '), sandbox);
    const store = new PosStore();
    const orders = [
        { id: 1, uuid: 'source', isSynced: true, uiState: {}, serializeForORM: () => ({ uuid: 'source' }) },
        { id: 2, uuid: 'child', isSynced: true, uiState: {}, serializeForORM: () => ({ uuid: 'child' }) },
    ];
    Object.assign(store, { order: orders[0], nativeSyncs: [], config: { baseer_direct_print_enabled: true },
        syncingOrders: new Set(), notification: { add() {} },
        env: { services: { ui: { block() {}, unblock() {} } } },
        models: { 'pos.order': { getBy: (_, uuid) => orders.find((order) => order.uuid === uuid) } },
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: orders }),
        getSyncAllOrdersContext: (_orders, options) => options.context,
        preSyncAllOrders: async () => orders, postSyncAllOrders: async () => {},
        removePendingOrder() {}, setOrder() {}, navigate() {},
        data: { network: { offline: false }, async synchronizeLocalDataInIndexedDB() {},
            async call(_model, method) { assert.equal(method, 'baseer_prepare_bill_split'); return 'baseline'; } },
    });
    const screen = new SplitBillScreen(); screen.pos = store;
    return { store, orders, screen, RPCError };
}

for (const condition of ['baseerPreparationOutcomeUnknown', 'baseerPreparationAction', 'baseerRestaurantMergePending', 'baseerBillSplitPending']) {
    test(`split is stopped before native mutation when ${condition}`, async () => {
        const { store, screen } = runtime();
        store.order.uiState[condition] = true;
        assert.equal(await screen.createSplittedOrder(), false);
        assert.equal(screen.nativeCalls || 0, 0);
        assert.equal(store.nativeSyncs.length, 0);
    });
}
test('ordinary non-direct POS delegates to the native splitter', async () => {
    const { store, screen } = runtime(); store.config.baseer_direct_print_enabled = false;
    assert.equal(await screen.createSplittedOrder(), 'native');
    assert.equal(screen.nativeCalls, 1);
});
test('a blocked split cannot fall through to native payment of the whole original order', async () => {
    const { store, screen } = runtime(); store.order.uiState.baseerPreparationOutcomeUnknown = true;
    assert.equal(await screen.paySplittedOrder(), false);
    assert.equal(store.payCalls || 0, 0);
    assert.equal(screen.nativeCalls || 0, 0);
});
test('a definitive split rejection followed by successful restoration cannot open payment', async () => {
    const { store, screen, RPCError } = runtime(async function () {
        const marker = this.pos._baseerBillSplitCapture;
        marker.target_uuid = 'child'; marker.sent = true; marker.rejected = true;
        throw new RPCError('Stale baseline');
    });
    let restored = 0;
    store._baseerRejectBillSplit = async () => { restored++; delete store.order.uiState.baseerBillSplitPending; };
    assert.equal(await screen.paySplittedOrder(), false);
    assert.equal(restored, 1);
    assert.equal(store.payCalls || 0, 0);
    assert.equal(screen.nativeCalls, 1);
});
test('full selection is rejected before mutation, while native whole Payment is untouched', async () => {
    const { screen } = runtime(); screen.getNumberOfProducts = () => 2;
    assert.equal(await screen.createSplittedOrder(), false);
    assert.equal(screen.nativeCalls || 0, 0);
});
test('ordinary unrelated sync still uses the native path', async () => {
    const { store, orders } = runtime();
    await store.syncAllOrders({ orders: [orders[0]] });
    assert.equal(store.nativeSyncs.length, 1);
    assert.equal(store.nativeSyncs[0][0], orders[0]);
});

function pendingPair() {
    const state = runtime();
    const { store, orders } = state;
    const marker = { source_uuid: 'source', target_uuid: 'child', baseline: 'baseline',
        payloads: [{ uuid: 'source', qty: 1 }, { uuid: 'child', qty: 1 }],
        context: { baseer_native_split: { source_uuid: 'source', target_uuid: 'child', baseline: 'baseline' } } };
    orders.forEach((order) => { order.uiState.baseerBillSplitPending = marker; });
    const calls = [];
    store.data.call = async (...args) => { calls.push(args); return { 'pos.order': [{ id: 1 }, { id: 2 }] }; };
    store.data.missingRecursive = async (data) => data;
    store.models.loadConnectedData = () => ({ 'pos.order': orders });
    store._baseerPersistPreparationSnapshot = async (_data, _order, _stale, fields, current) => {
        assert.equal(fields[0], 'baseerBillSplitPending'); assert.equal(current(), true);
        assert.ok(orders.every((order) => order.uiState.baseerBillSplitPending));
    };
    return { ...state, marker, calls };
}
test('the pair is sent in one native RPC and unlocked only after durable persistence', async () => {
    const { store, orders, calls } = pendingPair();
    await store.syncAllOrders({ orders });
    assert.equal(calls.length, 1);
    assert.equal(calls[0][1], 'sync_from_ui');
    assert.equal(calls[0][2][0].length, 2);
    assert.ok(orders.every((order) => !order.uiState.baseerBillSplitPending));
    assert.equal(store.nativeSyncs.length, 0);
});
test('a lost response retains both locks and retries the exact frozen pair', async () => {
    const { store, orders, calls, marker } = pendingPair();
    const normalCall = store.data.call;
    store.data.call = async (...args) => { await normalCall(...args); throw new Error('Connection lost'); };
    await assert.rejects(store.syncAllOrders({ orders }), /Connection lost/);
    assert.ok(orders.every((order) => order.uiState.baseerBillSplitPending === marker));
    store.data.call = normalCall;
    await store.syncAllOrders({ orders });
    assert.equal(JSON.stringify(calls[0]), JSON.stringify(calls[1]));
    assert.equal(store.nativeSyncs.length, 0);
});
test('a definitive RPC rejection is marked for canonical rollback, not a new split', async () => {
    const { store, orders, marker, RPCError } = pendingPair();
    store.data.call = async () => { throw new RPCError('Stale baseline'); };
    await assert.rejects(store.syncAllOrders({ orders }), /Stale baseline/);
    assert.equal(marker.rejected, true);
    let restored = 0; store._baseerRejectBillSplit = async () => { restored++; };
    await store.syncAllOrders({ orders });
    assert.equal(restored, 1); assert.equal(store.nativeSyncs.length, 0);
});
test('autosync cannot leak either half while native splitting is still building its map', async () => {
    const { store, orders } = pendingPair();
    delete orders[0].uiState.baseerBillSplitPending.payloads;
    await store.syncAllOrders();
    assert.equal(store.nativeSyncs.length, 0);
});

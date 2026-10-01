import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function fixture({ status = { accepted: false }, canonical = null } = {}) {
    class PosStore {}
    PosStore.prototype.sendOrderInPreparation = async () => true;
    PosStore.prototype.syncAllOrders = async options => options.orders;
    const sandbox = {
        PosStore, OrderReceipt: class {}, SelectionPopup: class {}, TextInputPopup: class {},
        _t: (s) => s, ask: async () => true,
        patch(target, extension) {
            Object.setPrototypeOf(extension, { ...target });
            Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(readFileSync(new URL('../static/src/app/preparation_bridge.js', import.meta.url), 'utf8')
        .replace(/^import .*;\r?\n/gm, ''), sandbox);
    const store = new PosStore();
    const action = { action_uuid: 'attempt-1', lines: [] };
    const order = { uuid: 'order-1', id: 7, isSynced: true, qty: 9,
        uiState: { baseerPreparationAction: action, baseerPreparationOutcomeUnknown: true,
            baseerPreparationPreviousChange: { lines: {} } } };
    const calls = { status: 0, resolve: 0, refresh: 0, save: 0, notices: [] };
    store.notification = { add: (message) => calls.notices.push(message) };
    store._baseerPreparationStatus = async () => { calls.status++; return status; };
    store.data = { network: { offline: false },
        async silentCall(model, method, args) {
            calls.resolve++;
            assert.equal(model, 'pos.order');
            assert.equal(method, 'baseer_resolve_preparation_action');
            assert.equal(args[0][0], order.id);
            assert.equal(args[1], action);
            return { accepted: true, skipped: true };
        },
        async synchronizeLocalDataInIndexedDB() { calls.save++; },
    };
    store.deviceSync = { async readDataFromServer() { calls.refresh++; } };
    if (canonical) store.models = { 'pos.order': { getBy: () => canonical } };
    return { store, order, action, calls };
}

test('unaccepted attempt is retired automatically without resending or losing the order', async () => {
    const { store, order, calls } = fixture();
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(calls.resolve, 1);
    assert.equal(calls.refresh, 1);
    assert.equal(order.qty, 9);
    assert.equal(order.uiState.baseerPreparationAction, undefined);
    assert.match(calls.notices[0], /continue working/);
});

test('accepted print failure only warns and releases editing without another send', async () => {
    const { store, order, calls } = fixture({ status: { accepted: true, failed: true } });
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(calls.resolve, 0);
    assert.match(calls.notices[0], /printing failed.*continue working/);
});

test('concurrent controls share one resolution and one durable save', async () => {
    const { store, order, calls } = fixture();
    assert.deepEqual(await Promise.all([store.baseerResolvePreparationOutcome(order),
        store.baseerResolvePreparationOutcome(order)]), [true, true]);
    assert.equal(calls.status, 1);
    assert.equal(calls.resolve, 1);
    assert.equal(calls.save, 1);
});

test('server offline cannot falsely acknowledge or discard uncertain intent', async () => {
    const { store, order, calls } = fixture();
    store.data.network.offline = true;
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(calls.status + calls.resolve, 0);
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
});

for (const failure of ['status', 'resolve', 'refresh']) {
    test(`${failure} failure retains the intent and returns normally`, async () => {
        const { store, order } = fixture();
        const fail = async () => { throw new Error('Network unavailable'); };
        if (failure === 'status') store._baseerPreparationStatus = fail;
        if (failure === 'resolve') store.data.silentCall = fail;
        if (failure === 'refresh') store.deviceSync.readDataFromServer = fail;
        assert.equal(await store.baseerResolvePreparationOutcome(order), false);
        assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-1');
    });
}

test('IndexedDB failure retains recovery flags on canonical order without restoring old quantities', async () => {
    const canonical = { uuid: 'order-1', qty: 3, uiState: {} };
    const { store, order } = fixture({ canonical });
    store.data.synchronizeLocalDataInIndexedDB = async () => { throw new Error('disk full'); };
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(canonical.qty, 3);
    assert.equal(canonical.uiState.baseerPreparationAction.action_uuid, 'attempt-1');
    assert.equal(canonical.uiState.baseerPreparationOutcomeUnknown, true);
});

test('old status response cannot clear a newer attempt', async () => {
    const { store, order, calls } = fixture();
    let resolve;
    store._baseerPreparationStatus = () => new Promise((r) => { resolve = r; });
    const pending = store.baseerResolvePreparationOutcome(order);
    order.uiState.baseerPreparationAction = { action_uuid: 'attempt-2' };
    resolve({ accepted: true });
    assert.equal(await pending, false);
    assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-2');
    assert.equal(calls.refresh, 0);
});

test('a newer intent created during persistence is never deleted', async () => {
    const { store, order } = fixture();
    store.data.synchronizeLocalDataInIndexedDB = async () => {
        order.uiState.baseerPreparationAction = { action_uuid: 'attempt-2' };
        order.uiState.baseerPreparationOutcomeUnknown = true;
        throw new Error('disk full');
    };
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-2');
});

test('an unsynchronized order is not reported as skipped', async () => {
    const { store, order, calls } = fixture();
    order.isSynced = false;
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(calls.resolve, 0);
});

test('a fresh control during IndexedDB commit awaits the result and cannot bypass failed persistence', async () => {
    const { store, order, calls } = fixture();
    let started, failSave;
    const saving = new Promise(resolve => { started = resolve; });
    store.data.synchronizeLocalDataInIndexedDB = () => new Promise((_resolve, reject) => {
        failSave = reject;
        started();
    });
    const first = store.baseerResolvePreparationOutcome(order);
    await saving;
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, undefined);
    let returned = false;
    const next = store.baseerResolvePreparationOutcome(order).then(result => { returned = true; return result; });
    await Promise.resolve();
    assert.equal(returned, false);
    failSave(new Error('disk full'));
    assert.deepEqual(await Promise.all([first, next]), [false, false]);
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
    assert.equal(calls.resolve, 1);
});

test('an original retry marker cannot bypass recovery persistence through autosync', async () => {
    const { store, order } = fixture();
    store.getPendingOrder = () => ({ orderToCreate: [], orderToUpdate: [order] });
    order._baseerPreparationRetrySync = 'attempt-1';
    let started, finishSave;
    const saving = new Promise(resolve => { started = resolve; });
    store.data.synchronizeLocalDataInIndexedDB = () => new Promise(resolve => { finishSave = resolve; started(); });
    const recovery = store.baseerResolvePreparationOutcome(order);
    await saving;
    const synced = await store.syncAllOrders({ orders: [order] });
    assert.equal(synced.length, 0);
    await assert.rejects(store.syncAllOrders({ orders: [order], throw: true }), /pending kitchen/);
    finishSave();
    assert.equal(await recovery, true);
});

test('canonical order is refreshed before clearing the uncertainty flag', async () => {
    const canonical = { uuid: 'order-1', qty: 3, uiState: {} };
    const { store, order } = fixture({ canonical });
    store.deviceSync.readDataFromServer = async () => {
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
    };
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(canonical.qty, 3);
    assert.equal(canonical.uiState.baseerPreparationAction, undefined);
});

test('an old send response cannot clear a newer preparation intent', async () => {
    const { store, order } = fixture();
    store.config = { baseer_direct_print_enabled: true };
    store.syncAllOrders = async () => [order];
    order.uiState.baseerPreparationOutcomeUnknown = false;
    order.last_order_preparation_change = { lines: {} };
    let resolveStatus, started;
    const waiting = new Promise(resolve => { started = resolve; });
    store._baseerPreparationStatus = () => new Promise(resolve => { resolveStatus = resolve; started(); });
    const sent = store.sendOrderInPreparation(order);
    await waiting;
    order.uiState.baseerPreparationAction = { action_uuid: 'attempt-2' };
    order.uiState.baseerPreparationOutcomeUnknown = true;
    resolveStatus({ accepted: true });
    assert.equal(await sent, false);
    assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-2');
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
});

test('old Send button cleanup cannot discard a newer attempt', async () => {
    const { store, order } = fixture();
    store.config = { baseer_direct_print_enabled: true };
    store.getOrder = () => order;
    store.addPendingOrder = () => {};
    order.uiState.baseerPreparationOutcomeUnknown = false;
    const oldAction = order.uiState.baseerPreparationAction;
    oldAction.lines = [{}];
    store.sendOrderInPreparation = async () => {
        order.uiState.baseerPreparationAction = { action_uuid: 'attempt-2' };
        order.uiState.baseerPreparationPreviousChange = { newer: true };
        return true;
    };
    await store.baseerSendCurrentOrder();
    assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-2');
    assert.equal(order.uiState.baseerPreparationPreviousChange.newer, true);
});

test('old send status rejection cannot change the newer intent in the error path', async () => {
    const { store, order } = fixture();
    store.config = { baseer_direct_print_enabled: true };
    store.syncAllOrders = async () => { throw new Error('lost original response'); };
    order.uiState.baseerPreparationOutcomeUnknown = false;
    order.last_order_preparation_change = { newer: true };
    let rejectStatus, started;
    const waiting = new Promise(resolve => { started = resolve; });
    store._baseerPreparationStatus = () => new Promise((_resolve, reject) => { rejectStatus = reject; started(); });
    const sent = store.sendOrderInPreparation(order);
    await waiting;
    order.uiState.baseerPreparationAction = { action_uuid: 'attempt-2' };
    order.uiState.baseerPreparationOutcomeUnknown = false;
    rejectStatus(new Error('status connection lost'));
    assert.equal(await sent, false);
    assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-2');
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, false);
    assert.equal(order.last_order_preparation_change.newer, true);
});

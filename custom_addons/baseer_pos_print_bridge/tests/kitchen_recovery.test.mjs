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
        _t: (s) => s, ask: async () => true, SERIALIZED_UI_STATE_PROP: 'JSONuiState', setTimeout, clearTimeout,
        patch(target, extension) {
            Object.setPrototypeOf(extension, { ...target });
            Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(readFileSync(new URL('../static/src/app/preparation_bridge.js', import.meta.url), 'utf8')
        .replace(/^import .*;\r?\n/gm, ''), sandbox);
    const store = new PosStore();
    store.config = { id: 2, company_id: { id: 1 } };
    const action = { action_uuid: 'attempt-1', lines: [] };
    const order = { uuid: 'order-1', id: 7, isSynced: true, qty: 9, state: 'draft',
        company_id: { id: 1 }, config_id: { id: 2 },
        uiState: { baseerPreparationAction: action, baseerPreparationOutcomeUnknown: true,
            baseerPreparationPreviousChange: { lines: {} } } };
    const calls = { status: 0, resolve: 0, refresh: 0, save: 0, unlock: 0, notices: [], trace: [] };
    const snapshot = { 'pos.order': [{ id: 7, uuid: 'order-1', company_id: 1, config_id: 2,
        state: 'draft', lines: [11], payment_ids: [], amount_total: 3, amount_paid: 0,
        amount_return: 0, account_move: false, is_refund: false, last_order_preparation_change: { lines: {} } }],
        'pos.order.line': [{ id: 11, uuid: 'line-1', order_id: 7, qty: canonical?.qty ?? 3,
            pack_lot_ids: [], custom_attribute_value_ids: [] }],
        'pos.payment': [], 'pos.pack.operation.lot': [], 'product.attribute.custom.value': [] };
    const records = { 'pos.order': [order], 'pos.order.line': [], 'pos.payment': [],
        'pos.pack.operation.lot': [], 'product.attribute.custom.value': [] };
    const commands = [];
    function attach(model, values) {
        const record = { ...values, model: { name: model },
            serializeForIndexedDB() { return Object.fromEntries(Object.entries(this)
                .filter(([key, value]) => key !== 'model' && typeof value !== 'function')
                .map(([key, value]) => [key, value?.id || value])); },
            delete() { calls.trace.push(`delete:${this.id}`); commands.push({ parentId: this.order_id?.id || this.pos_order_id?.id || this.pos_order_line_id?.id });
                records[model].splice(records[model].indexOf(this), 1);
                order.lines = order.lines.filter(line => line !== this);
                order.payment_ids = order.payment_ids.filter(payment => payment !== this); },
            serializeForORM() { calls.trace.push(`drain:${this.id}`); for (let i = commands.length - 1; i >= 0; i--) if (commands[i].parentId === this.id) commands.splice(i, 1); },
        };
        records[model].push(record);
        return record;
    }
    order.serializeForORM = function () { calls.trace.push(`drain:${this.id}`); for (let i = commands.length - 1; i >= 0; i--) if (commands[i].parentId === this.id) commands.splice(i, 1); };
    order.serializeForIndexedDB = () => ({ id: order.id, uuid: order.uuid, state: order.state,
        JSONuiState: JSON.stringify(order.uiState) });
    order.lines = [attach('pos.order.line', { id: 11, uuid: 'line-1', order_id: order, qty: 9 })];
    order.payment_ids = [];
    store.models = Object.fromEntries(Object.keys(records).map(model => [model, {
        filter: predicate => records[model].filter(predicate),
        get: id => records[model].find(record => record.id === id),
        getBy: (key, value) => records[model].find(record => record[key] === value),
    }]));
    store.models.loadConnectedData = data => {
        calls.trace.push('load');
        for (const model of ['pos.order.line', 'pos.payment', 'pos.pack.operation.lot', 'product.attribute.custom.value']) {
            for (const raw of data[model]) {
                let record = records[model].find(record => record.uuid === raw.uuid || record.id === raw.id);
                if (!record) record = attach(model, raw);
                Object.assign(record, raw);
                for (const inverse of ['order_id', 'pos_order_id']) if (record[inverse] === order.id) record[inverse] = order;
                if (Number.isInteger(record.pos_order_line_id)) record.pos_order_line_id = records['pos.order.line'].find(line => line.id === record.pos_order_line_id);
            }
        }
        const raw = data['pos.order'][0];
        Object.assign(order, raw, { company_id: { id: raw.company_id }, config_id: { id: raw.config_id },
            lines: records['pos.order.line'].filter(line => raw.lines.includes(line.id)),
            payment_ids: records['pos.payment'].filter(payment => raw.payment_ids.includes(payment.id)),
            qty: data['pos.order.line'][0]?.qty ?? 0 });
    };
    store.removePendingOrder = () => { calls.trace.push('unpend'); };
    store.notification = { add: (message) => calls.notices.push(message) };
    store._baseerPreparationStatus = async () => { calls.status++; return status; };
    store.data = { network: { offline: false }, fields: {}, relations: {}, opts: { databaseTable: {
        'pos.order': { key: 'uuid' }, 'pos.order.line': { key: 'uuid' },
        'pos.payment': { key: 'uuid' }, 'product.attribute.custom.value': { key: 'id' },
    } },
        indexedDBMutex: { exec: callback => callback() },
        indexedDB: { activeTransactions: new Set(), cached: new Map(),
            getNewTransaction(stores) {
                const database = this;
                calls.save++;
                const handlers = {}, puts = [], deletes = [], requests = [];
                let finished = false;
                function request() {
                    const callbacks = [];
                    let succeeded = false;
                    const result = { addEventListener(name, callback) { assert.equal(name, 'success'); callbacks.push(callback); },
                        success() { if (succeeded) return; succeeded = true; for (const callback of callbacks) callback(); } };
                    requests.push(result);
                    return result;
                }
                const tx = {
                    addEventListener(name, callback) { (handlers[name] ||= []).push(callback); },
                    objectStore(model) {
                        assert(stores.includes(model));
                        return {
                            put(row) { puts.push([model, structuredClone(row)]); return request(); },
                            delete(key) { deletes.push([model, key]); return request(); },
                        };
                    },
                    abort() { if (finished) return; finished = true; for (const callback of handlers.abort || []) callback(); },
                    complete() {
                        if (finished) return;
                        for (const request of requests) request.success();
                        if (finished) return;
                        finished = true;
                        for (const [model, key] of deletes) { database.cached.delete(`${model}:${key}`); calls.trace.push(`idb-delete:${model}:${key}`); }
                        for (const [model, row] of puts) {
                            const key = store.data.opts.databaseTable[model]?.key || 'id';
                            database.cached.set(`${model}:${row[key]}`, row);
                        }
                        calls.unlock++; calls.trace.push('unlock');
                        for (const callback of handlers.complete || []) callback();
                    },
                    puts, deletes, requests,
                };
                this.activeTransactions.add(tx);
                queueMicrotask(() => {
                    database.onTransaction?.(tx);
                    if (!database.holdCommit) tx.complete();
                });
                return tx;
            },
        },
        async deleteRecordsInIndexedDB(model, keys) { calls.trace.push(`idb-delete:${model}:${keys[0]}`); },
        async call(model, method, args, kwargs, queue) {
            assert.equal(model, 'pos.order'); assert.equal(method, 'read_pos_data_uuid');
            assert.equal(args[0], order.uuid); assert.equal(queue, false);
            calls.refresh++; calls.trace.push('fetch'); return structuredClone(snapshot);
        },
        async missingRecursive(data) { calls.trace.push('hydrate'); return data; },
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
    store.deviceSync = { async readDataFromServer() { throw new Error('Incremental reads cannot resolve uncertainty'); } };
    return { store, order, action, calls, snapshot, records, commands, attach };
}

test('unaccepted attempt is retired automatically without resending or losing the order', async () => {
    const { store, order, calls } = fixture();
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(calls.resolve, 1);
    assert.equal(calls.refresh, 1);
    assert.equal(order.qty, 3);
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
        if (failure === 'refresh') store.data.call = fail;
        assert.equal(await store.baseerResolvePreparationOutcome(order), false);
        assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-1');
    });
}

test('IndexedDB failure retains recovery flags on canonical order without restoring old quantities', async () => {
    const canonical = { uuid: 'order-1', qty: 3, uiState: {} };
    const { store, order } = fixture({ canonical });
    store.data.indexedDB.onTransaction = transaction => transaction.abort();
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(order.qty, 3);
    assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-1');
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
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
    store.data.indexedDB.onTransaction = transaction => {
        order.uiState.baseerPreparationAction = { action_uuid: 'attempt-2' };
        order.uiState.baseerPreparationOutcomeUnknown = true;
        transaction.abort();
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
    store.data.indexedDB.holdCommit = true;
    store.data.indexedDB.onTransaction = transaction => {
        failSave = () => transaction.abort();
        started();
    };
    const first = store.baseerResolvePreparationOutcome(order);
    await saving;
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
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
    store.data.indexedDB.holdCommit = true;
    store.data.indexedDB.onTransaction = transaction => { finishSave = () => transaction.complete(); started(); };
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
    const read = store.data.call;
    store.data.call = async (...args) => {
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
        return read(...args);
    };
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(order.qty, 3);
    assert.equal(order.uiState.baseerPreparationAction, undefined);
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

for (const status of [{ accepted: false }, { accepted: true, skipped: true }]) {
    test(`skipped attempt (${status.accepted ? 'existing receipt' : 'new receipt'}) point-reads unchanged server quantities before payment`, async () => {
        const { store, order, snapshot, calls } = fixture({ status });
        order.lines[0].qty = 0;
        snapshot['pos.order.line'][0].qty = 1;
        assert.equal(await store.baseerResolvePreparationOutcome(order), true);
        assert.equal(order.lines[0].qty, 1);
        assert.equal(calls.refresh, 1);
        assert.equal(calls.unlock, 1);
        assert.equal(order.uiState.baseerPreparationAction, undefined);
    });
}

test('an accepted cancellation retains the authoritative reduced quantity', async () => {
    const { store, order, snapshot } = fixture({ status: { accepted: true, done: true } });
    order.lines[0].qty = 1;
    snapshot['pos.order.line'][0].qty = 0;
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(order.lines[0].qty, 0);
});

test('accepted cancellation of the last item loads native cancelled empty state', async () => {
    const { store, order, snapshot } = fixture({ status: { accepted: true, done: true } });
    Object.assign(snapshot['pos.order'][0], { state: 'cancel', lines: [], amount_total: 0,
        last_order_preparation_change: { lines: { old: { quantity: 0 } } } });
    snapshot['pos.order.line'] = [];
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(order.state, 'cancel');
    assert.equal(order.lines.length, 0);
});

for (const mutate of [
    data => { data['pos.order'][0].company_id = 999; },
    data => { data['pos.order'][0].config_id = 999; },
    data => { data['pos.order'][0].uuid = 'foreign-order'; },
    data => { data['pos.order'][0].id = 999; },
    data => { data['pos.order'][0].lines.push(99); },
    data => { data['pos.order.line'][0].order_id = 999; },
    data => { data['pos.order.line'].push({ ...data['pos.order.line'][0] }); },
    data => { data['pos.payment'] = [{ id: 91, uuid: 'foreign-payment', pos_order_id: 999 }]; data['pos.order'][0].payment_ids = [91]; },
    data => { delete data['pos.order.line']; },
    data => { data['pos.order'][0].state = 'paid'; },
    data => { data['pos.order'][0].state = 'done'; },
]) {
    test(`invalid/terminal snapshot remains blocked before local mutation: ${mutate}`, async () => {
        const { store, order, snapshot, calls } = fixture({ status: { accepted: true } });
        mutate(snapshot);
        assert.equal(await store.baseerResolvePreparationOutcome(order), false);
        assert.equal(order.lines[0].qty, 9);
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
        assert.equal(calls.save + calls.unlock, 0);
        assert(!calls.trace.includes('load'));
    });
}

test('incomplete declared financial fields remain blocked before merge', async () => {
    const { store, order, calls } = fixture();
    store.data.fields['pos.order'] = ['amount_total', 'amount_tax'];
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(order.lines[0].qty, 9);
    assert.equal(calls.unlock, 0);
});

for (const modify of [
    raw => { raw.amount_paid = 1; }, raw => { raw.amount_total = 1; },
    raw => { raw.account_move = 12; }, raw => { raw.is_refund = true; },
    raw => { raw.last_order_preparation_change = { lines: { old: { quantity: 1 } } }; },
]) {
    test(`terminal cancellation cannot erase financial obligations: ${modify}`, async () => {
        const { store, order, snapshot } = fixture({ status: { accepted: true } });
        Object.assign(snapshot['pos.order'][0], { state: 'cancel', lines: [], amount_total: 0 });
        snapshot['pos.order.line'] = [];
        modify(snapshot['pos.order'][0]);
        assert.equal(await store.baseerResolvePreparationOutcome(order), false);
        assert.equal(order.state, 'draft');
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
    });
}

test('stale/unsynced children are removed and their deletion commands drain before reload without touching another order', async () => {
    const { store, order, records, attach, commands, calls } = fixture();
    const staleLine = attach('pos.order.line', { id: 12, uuid: 'stale', order_id: order, qty: 10 });
    const unsynced = attach('pos.order.line', { id: 'new', uuid: 'new', order_id: order, qty: 20 });
    const stalePayment = attach('pos.payment', { id: 'new-payment', uuid: 'new-payment', pos_order_id: order, amount: 50 });
    order.lines.push(staleLine, unsynced); order.payment_ids.push(stalePayment);
    commands.push({ parentId: 7, id: 77 }, { parentId: 99, id: 88 });
    const load = store.models.loadConnectedData;
    store.models.loadConnectedData = data => {
        assert.equal(commands.filter(command => command.parentId === 7).length, 0);
        assert.equal(records['pos.order.line'].some(line => line.id === 'new'), false);
        load(data);
    };
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.deepEqual(commands, [{ parentId: 99, id: 88 }]);
    assert.deepEqual(order.lines.map(line => line.id), [11]);
    assert.equal(order.payment_ids.length, 0);
    assert(calls.trace.indexOf('delete:12') < calls.trace.indexOf('drain:7'));
    assert(calls.trace.indexOf('drain:7') < calls.trace.indexOf('load'));
    assert(calls.trace.indexOf('idb-delete:pos.order.line:new') < calls.trace.indexOf('unlock'));
});

test('canonical existing payments reload amounts and native backrefs', async () => {
    const { store, order, snapshot } = fixture();
    snapshot['pos.order'][0].payment_ids = [91];
    snapshot['pos.payment'].push({ id: 91, uuid: 'server-payment', amount: 3, pos_order_id: 7 });
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(order.payment_ids[0].amount, 3);
    assert.equal(order.payment_ids[0].pos_order_id, order);
});

for (const stage of ['fetch', 'hydrate', 'load', 'transaction-open', 'transaction-abort']) {
    test(`failure at ${stage} retains the recovery lock`, async () => {
        const { store, order, attach } = fixture();
        const fail = async () => { throw new Error(`failed ${stage}`); };
        if (stage === 'fetch') store.data.call = fail;
        if (stage === 'hydrate') store.data.missingRecursive = fail;
        if (stage === 'load') store.models.loadConnectedData = () => { throw new Error('merge failed'); };
        if (stage === 'transaction-open') store.data.indexedDB.getNewTransaction = () => false;
        if (stage === 'transaction-abort') store.data.indexedDB.onTransaction = transaction => transaction.abort();
        assert.equal(await store.baseerResolvePreparationOutcome(order), false);
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
        assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-1');
        if (['transaction-open', 'transaction-abort'].includes(stage)) assert.equal(order.lines[0].qty, 3);
    });
}

test('failed full fetch remains blocked and reconnect performs a new canonical point read', async () => {
    const { store, order, calls } = fixture();
    const read = store.data.call;
    store.data.call = async () => { throw new Error('connection lost'); };
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(order.lines[0].qty, 9);
    store.data.call = read;
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert.equal(order.lines[0].qty, 3);
    assert.equal(calls.refresh, 1);
});

for (const stage of ['fetch', 'hydrate']) {
    test(`a same-UUID model replacement during ${stage} cannot unlock either order`, async () => {
        const { store, order, records, calls } = fixture();
        const replace = () => { records['pos.order'][0] = { ...order, uiState: { ...order.uiState } }; };
        if (stage === 'fetch') {
            const read = store.data.call;
            store.data.call = async (...args) => { const data = await read(...args); replace(); return data; };
        } else {
            store.data.missingRecursive = async data => { replace(); return data; };
        }
        assert.equal(await store.baseerResolvePreparationOutcome(order), false);
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
        assert.equal(records['pos.order'][0].uiState.baseerPreparationOutcomeUnknown, true);
        assert.equal(calls.unlock, 0);
    });
}

test('going offline after the point read retains the unresolved intent', async () => {
    const { store, order, calls } = fixture();
    const read = store.data.call;
    store.data.call = async (...args) => { const data = await read(...args); store.data.network.offline = true; return data; };
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(order.lines[0].qty, 9);
    assert.equal(calls.unlock, 0);
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
});

test('missingRecursive cannot silently accept an unresolved product read', async () => {
    const { store, order, snapshot, calls } = fixture();
    snapshot['pos.order.line'][0].product_id = 55;
    store.models['product.product'] = { get: () => undefined };
    store.data.relations['pos.order.line'] = { product_id: { name: 'product_id', relation: 'product.product', type: 'many2one' } };
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    assert.equal(order.lines[0].qty, 9);
    assert.equal(calls.unlock, 0);
});

test('request success followed by transaction abort cannot unlock memory or commit a partial graph', async () => {
    const { store, order, calls } = fixture();
    let started, failUnlock;
    const unlocking = new Promise(resolve => { started = resolve; });
    store.data.indexedDB.holdCommit = true;
    store.data.indexedDB.onTransaction = transaction => {
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
        const [, row] = transaction.puts.find(([model]) => model === 'pos.order');
        assert.equal(JSON.parse(row.JSONuiState).baseerPreparationAction, undefined);
        assert.equal(transaction.puts.find(([model]) => model === 'pos.order.line')[1].qty, 3);
        // Native requests may have all reported success here; only the
        // transaction completion event is permitted to unlock the order.
        failUnlock = () => transaction.abort();
        started();
    };
    const first = store.baseerResolvePreparationOutcome(order);
    await unlocking;
    const next = store.baseerResolvePreparationOutcome(order);
    failUnlock(new Error('atomic IDB transaction aborted'));
    assert.deepEqual(await Promise.all([first, next]), [false, false]);
    assert.equal(order.lines[0].qty, 3);
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
    assert.equal(calls.save, 1);
    assert.equal(calls.unlock, 0);
    assert.equal(store.data.indexedDB.cached.size, 0);
});

test('stale IndexedDB deletion failure can be retried without dropping its tombstone', async () => {
    const { store, order, attach, calls } = fixture();
    order.lines.push(attach('pos.order.line', { id: 'new', uuid: 'new', order_id: order }));
    let fail = true;
    store.data.indexedDB.onTransaction = transaction => { if (fail) transaction.abort(); };
    assert.equal(await store.baseerResolvePreparationOutcome(order), false);
    fail = false;
    assert.equal(await store.baseerResolvePreparationOutcome(order), true);
    assert(calls.trace.includes('idb-delete:pos.order.line:new'));
    assert.equal(calls.unlock, 1);
});

test('a send retry with an uncertain intent resolves canonically before any normal sync', async () => {
    const { store, order, calls } = fixture({ status: { accepted: true, skipped: true } });
    store.config.baseer_direct_print_enabled = true;
    store.syncAllOrders = async () => { throw new Error('Uncertain intent must not be flushed'); };
    assert.equal(await store.sendOrderInPreparation(order), true);
    assert.equal(order.lines[0].qty, 3);
    assert.equal(calls.refresh, 1);
    assert.equal(order.uiState.baseerPreparationAction, undefined);
});

for (const lostResponse of [false, true]) {
    test(`accepted skipped ${lostResponse ? 'lost response' : 'normal response'} routes through canonical recovery`, async () => {
        const { store, order, calls } = fixture({ status: { accepted: true, skipped: true } });
        store.config.baseer_direct_print_enabled = true;
        order.uiState.baseerPreparationOutcomeUnknown = false;
        order.last_order_preparation_change = { lines: {} };
        store.syncAllOrders = async () => { if (lostResponse) throw new Error('Lost sync reply'); return [order]; };
        const result = await store.sendOrderInPreparation(order);
        assert.equal(result.recovered, true);
        assert.equal(order.lines[0].qty, 3);
        assert.equal(calls.refresh, 1);
        assert.equal(order.uiState.baseerPreparationAction, undefined);
    });
}

test('accepted receipt plus failed canonical recovery cannot restore a cached baseline or use definitive-error unlock', async () => {
    const { store, order, snapshot } = fixture({ status: { accepted: true } });
    store.config.baseer_direct_print_enabled = true;
    order.uiState.baseerPreparationOutcomeUnknown = false;
    order.last_order_preparation_change = { current: true };
    snapshot['pos.order'][0].company_id = 999;
    const original = { data: { name: 'odoo.exceptions.ValidationError' } };
    store.syncAllOrders = async () => { throw original; };
    await assert.rejects(store.sendOrderInPreparation(order), error => error === original);
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
    assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-1');
    assert.equal(order.last_order_preparation_change.current, true);
});

for (const timing of ['first-put', 'last-put', 'delete']) {
    test(`a newer intent before ${timing} request success aborts the graph transaction and retains the disk lock`, async () => {
        const { store, order, attach, calls } = fixture();
        const database = store.data.indexedDB;
        const durableBefore = structuredClone(order.serializeForIndexedDB());
        database.cached.set('pos.order:order-1', durableBefore);
        if (timing === 'delete') {
            order.lines.push(attach('pos.order.line', { id: 'new', uuid: 'new', order_id: order }));
        }
        database.onTransaction = transaction => {
            if (timing === 'last-put') {
                for (const request of transaction.requests.slice(0, -1)) request.success();
            }
            if (timing === 'delete') assert(transaction.deletes.length > 0);
            order.uiState.baseerPreparationAction = { action_uuid: 'attempt-2' };
            order.uiState.baseerPreparationOutcomeUnknown = true;
        };
        assert.equal(await store.baseerResolvePreparationOutcome(order), false);
        assert.equal(order.uiState.baseerPreparationAction.action_uuid, 'attempt-2');
        assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
        assert.deepEqual(database.cached.get('pos.order:order-1'), durableBefore);
        assert.equal(JSON.parse(database.cached.get('pos.order:order-1').JSONuiState).baseerPreparationOutcomeUnknown, true);
        assert.equal(calls.unlock, 0);
        assert.equal(database.activeTransactions.size, 0);
    });
}

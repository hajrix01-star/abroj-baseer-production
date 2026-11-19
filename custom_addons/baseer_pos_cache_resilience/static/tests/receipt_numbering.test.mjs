import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const source = read('../src/receipt_number_reservation.js');
function storage(values = {}) {
    const store = { ...values };
    Object.defineProperties(store, {
        getItem: { value(key) { return this[key] ?? null; } },
        setItem: { value(key, value) { this[key] = String(value); } },
        removeItem: { value(key) { delete this[key]; } },
        clear: { value() { for (const key of Object.keys(this)) delete this[key]; } },
    });
    return store;
}
function runtime(patched = true) {
    const context = vm.createContext({
        localStorage: storage(), odoo: { access_token: 'qa-config', pos_config_id: 27 },
        luxon: { DateTime: { now: () => ({ year: 2026 }) } },
        patch(target, extension) {
            Object.setPrototypeOf(extension, Object.create(null, Object.getOwnPropertyDescriptors(target)));
            Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
        },
    });
    vm.runInContext(read('./fixtures/device_sequence_20260817.js').replace('export default class', 'class') +
        '\nglobalThis.DeviceIdentifierSequence = DeviceIdentifierSequence;', context);
    vm.runInContext('const {DateTime} = luxon;\n' + read('./fixtures/store_numbering_20260817.js') +
        '\nglobalThis.PosStore = PosStore;', context);
    if (patched) vm.runInContext(source.replace(/^import .*;\r?\n/gm, ''), context);
    context.localStorage.setItem('qa-config-unique_device_identifier', JSON.stringify({
        device_identifier: '4', next_number: 9, unsynced_number_stack: [8],
    }));
    const device = new context.DeviceIdentifierSequence({ orm: {} });
    const orders = [];
    const store = new context.PosStore();
    Object.assign(store, { device, config: { id: 27 }, models: { 'pos.order': { getAll: () => orders } } });
    return { context, store, device, orders };
}

test('baseline reproduces a duplicate reference held by a restored draft', () => {
    const { store, orders } = runtime(false);
    orders.push({ pos_reference: '264-27-000008', isSynced: false });
    const next = {};
    store.setNextOrderRefs(next);
    assert.equal(next.pos_reference, orders[0].pos_reference);
});

for (const synced of [false, true]) {
    test(`official fix reserves a loaded ${synced ? 'synced' : 'unsynced'} order number`, () => {
        const { store, orders, device } = runtime();
        orders.push({ pos_reference: '264-27-000008', isSynced: synced });
        const next = {};
        store.setNextOrderRefs(next);
        assert.equal(next.pos_reference, '264-27-000009');
        assert.equal(next.tracking_number, '4009');
        assert.deepEqual(Array.from(device.unsyncedNumberStack), []);
        assert.equal(orders[0].pos_reference, '264-27-000008');
    });
}

test('successful sync reserves the number after the order leaves the local store', () => {
    const { store, device } = runtime();
    store.postSyncAllOrders([{ pos_reference: '264-27-000008' }]);
    assert.deepEqual(Array.from(device.unsyncedNumberStack), []);
    const next = {};
    store.setNextOrderRefs(next);
    assert.equal(next.pos_reference, '264-27-000009');
});

test('device and config namespaces remain isolated', () => {
    const { store, orders } = runtime();
    orders.push({ pos_reference: '2649-27-000008' }, { pos_reference: '264-279-000008' });
    const next = {};
    store.setNextOrderRefs(next);
    assert.equal(next.pos_reference, '264-27-000008');
});

test('official behavior still reuses a genuinely released number', () => {
    const { store } = runtime();
    const next = {};
    store.setNextOrderRefs(next);
    assert.equal(next.pos_reference, '264-27-000008');
});

test('empty reuse stack follows native monotonic allocation without network', () => {
    const { store, device } = runtime();
    device.save({ unsynced_number_stack: [] });
    for (let i = 9; i < 15; i++) {
        const next = {};
        store.setNextOrderRefs(next);
        assert.equal(next.pos_reference, `264-27-${String(i).padStart(6, '0')}`);
    }
});

test('upstream-native reservation method is not overwritten on a future upgrade', () => {
    const { context } = runtime(false);
    const original = function () {};
    context.DeviceIdentifierSequence.prototype.removeUsedNumbers = original;
    vm.runInContext(source.replace(/^import .*;\r?\n/gm, ''), context);
    assert.equal(context.DeviceIdentifierSequence.prototype.removeUsedNumbers, original);
});

test('critical recovery preserves UUID and both config counters without restoring stale values', async () => {
    const counter = JSON.stringify({ device_identifier: 4, next_number: 99, unsynced_number_stack: [] });
    const localStorage = storage({ device_uuid: 'qa-device',
        'a-unique_device_identifier': counter, 'b-unique_device_identifier': 'other-counter', garbage: 'remove' });
    let reloads = 0;
    const context = vm.createContext({ localStorage, sessionStorage: storage({ tmp: 'x' }),
        navigator: {}, window: {}, location: { reload() { reloads++; } }, setTimeout });
    vm.runInContext(read('../src/receipt_storage.js').replace('export function', 'function'), context);
    vm.runInContext(read('../src/reset_local_data.js').replace(/^import .*;\r?\n/gm, '').replace('export async function', 'async function'), context);
    await vm.runInContext('resetLocalData()', context);
    assert.equal(localStorage.device_uuid, 'qa-device');
    assert.equal(localStorage['a-unique_device_identifier'], counter);
    assert.equal(localStorage['b-unique_device_identifier'], 'other-counter');
    assert.equal(localStorage.getItem('garbage'), null);
    assert.equal(context.sessionStorage.getItem('tmp'), null);
    assert.equal(reloads, 1);
});

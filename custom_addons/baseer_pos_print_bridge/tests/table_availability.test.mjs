import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

class PosStore {}
PosStore.prototype.shouldCreatePendingOrder = () => true;
PosStore.prototype.unsetTable = async function () { this.nativeCalled = true; };
const runtime = {PosStore, _t: (s) => s, patch(target, extension) {
    Object.setPrototypeOf(extension, {...target});
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
}};
vm.createContext(runtime);
vm.runInContext(readFileSync(new URL('../static/src/app/table_availability.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace('export function ', 'function '), runtime);
const store = new PosStore();
store.config = {module_pos_restaurant: true};
store.syncingOrders = new Set();
store.removePendingOrder = () => {};
store.setOrder = (order) => { store.current = order; };
store.getOrder = () => store.current;
store.data = {localDeleteCascade: () => { store.deleted = true; },
    call: async () => ({released: false, data: {}}), missingRecursive: async (data) => data};
store.models = {loadConnectedData: () => {}};
store.notification = {add: () => { store.warned = true; }};
const empty = () => ({uuid: 'empty', table_id: {id: 1}, lines: [], payment_ids: [], uiState: {}});
store.current = empty();
assert.equal(store.shouldCreatePendingOrder(store.current), false);
assert.equal(store.tableHasOrders({getOrders: () => [store.current]}), false);
await store.unsetTable();
assert.equal(store.deleted, true);
assert.equal(store.current, null);
for (const qty of [0, -1, 1]) {
    store.current = {...empty(), lines: [{qty, price_unit: 0}]};
    assert.equal(store.shouldCreatePendingOrder(store.current), true);
    assert.equal(store.tableHasOrders({getOrders: () => [store.current]}), true);
}
store.current = {...empty(), isSynced: true, id: 10};
store.deleted = false;
await store.unsetTable();
assert.equal(store.deleted, false, 'server rejection must preserve concurrent work');
store.current = {...empty(), payment_ids: [{amount: 0}]};
assert.equal(store.tableHasOrders({getOrders: () => [store.current]}), true);
store.current = empty();
store.baseerHasPendingProtectedAction = () => true;
assert.equal(store.shouldCreatePendingOrder(store.current), true);
assert.equal(store.tableHasOrders({getOrders: () => [store.current]}), true);
console.log('PASS empty-table visit, zero/free/refund goods, payments, concurrent server rejection, pending protection');

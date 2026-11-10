// Focused dependency-free tests for bridge intent and failure handling.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import { webcrypto } from 'node:crypto';

function runtime(file, native = {}) {
    class PosStore {}
    class Orderline {}
    Object.assign(PosStore.prototype, native);
    Object.defineProperties(Orderline.prototype, Object.getOwnPropertyDescriptors(native.orderline || {}));
    const sandbox = {
        PosStore, PosOrder: class {}, PosOrderline: class {}, Orderline, OrderSummary: class {},
        SelectionPopup: class {}, TextInputPopup: class {}, ConfirmationDialog: class {},
        AlertDialog: class {}, NumberPopup: class {}, OrderReceipt: class {}, crypto: webcrypto,
        makeAwaitable: native.makeAwaitable || (async () => null),
        ask: native.ask || (async () => true),
        SERIALIZED_UI_STATE_PROP: 'JSONuiState', setTimeout, clearTimeout,
        window: native.window || { location: {} },
        _t: (message, value) => message.replace('%s', value ?? '%s'),
        patch(target, extension) {
            Object.setPrototypeOf(extension, Object.create(null, Object.getOwnPropertyDescriptors(target)));
            Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
        },
    };
    vm.createContext(sandbox);
    const source = readFileSync(new URL(`../static/src/app/${file}`, import.meta.url), 'utf8')
        .replace(/^import .*;\r?\n/gm, '').replace(/export function /g, 'function ');
    vm.runInContext(source, sandbox);
    return sandbox;
}

const lineRuntime = runtime('line_actions.js');
const displayRuntime = runtime('line_actions.js', { orderline: {
    get lineScreenValues() {
        const { uuid, order_id } = this.line;
        return order_id.unitPrices.baseLineByLineUuids[uuid].tax_details;
    },
} });
const displayLine = new displayRuntime.Orderline();
const validTaxDetails = { total_included: 1.15 };
const priceData = { baseLineByLineUuids: { salad: { tax_details: validTaxDetails } } };
displayLine.props = { mode: 'display' };
displayLine.line = { uuid: 'salad', order_id: { unitPrices: priceData, prices: priceData } };
assert.equal(displayLine.lineScreenValues, validTaxDetails);
// The server can remove the price entries before OWL unmounts the old row.
delete priceData.baseLineByLineUuids.salad;
assert.equal(displayLine.lineScreenValues, null);
displayLine.line.order_id = null;
assert.equal(displayLine.lineScreenValues, null);
priceData.baseLineByLineUuids.salad = { tax_details: validTaxDetails };
displayLine.line.order_id = { unitPrices: priceData, prices: priceData };
displayLine.props.mode = 'receipt';
assert.equal(displayLine.lineScreenValues, validTaxDetails);

const line = { uuid: 'replacement', baseer_substitution_silent_quantity: 1, qty: 1,
    getQuantity() { return this.qty; } };
const order = { getOrderlines: () => [line], last_order_preparation_change: { lines: {
    replacement: { uuid: line.uuid, quantity: 1 },
} } };
assert.equal(lineRuntime.buildBaseerPreparationAction(order).lines.length, 0);
line.qty = 3;
let action = lineRuntime.buildBaseerPreparationAction(order).lines[0];
assert.equal(action.expected_quantity, 0);
assert.equal(action.new_quantity, 2);
order.last_order_preparation_change.lines.replacement.quantity = 3;
assert.equal(lineRuntime.getBaseerSentQuantity(order, line), 2);
assert.equal(lineRuntime.buildBaseerPreparationAction(order).lines.length, 0);
order.last_order_preparation_change = { lines: {} };
assert.equal(lineRuntime.getBaseerSentQuantity(order, line), 0);

const paymentSteps = [];
let confirmSend = false;
const paymentBridge = runtime('preparation_bridge.js', {
    ask: async (_dialog, options) => {
        assert.equal(options.confirmLabel, 'Send to kitchen and continue to payment');
        assert.equal(options.cancelLabel, 'Back to order');
        paymentSteps.push('prompt');
        return confirmSend;
    },
    async pay() { paymentSteps.push('pay'); },
    async validateOrderFast() { paymentSteps.push('fast pay'); },
});
paymentBridge.buildBaseerPreparationAction = lineRuntime.buildBaseerPreparationAction;
const paymentStore = new paymentBridge.PosStore();
const food = { id: 9, pos_categ_ids: [{ id: 2 }] };
const foodLine = { uuid: 'food-line', product_id: food, getQuantity: () => 1 };
const retail = { id: 10, pos_categ_ids: [{ id: 3 }] };
let retailQuantity = 1;
const retailLine = { uuid: 'retail-line', product_id: retail, getQuantity: () => retailQuantity };
let cartLines = [foodLine, retailLine];
const paymentOrder = { uuid: 'order-for-payment', uiState: {}, getOrderlines: () => cartLines,
    last_order_preparation_change: { lines: {} } };
paymentStore.config = { id: 7, baseer_direct_print_enabled: true };
paymentStore.getOrder = () => paymentOrder;
let hasKitchenRoute = true;
paymentStore.data = { call: async (model, method, [configId, orderUuid, products], _kwargs, queue) => {
    assert.equal(model, 'pos.config');
    assert.equal(method, 'baseer_kitchen_payment_lines');
    assert.equal(configId, paymentStore.config.id);
    assert.equal(orderUuid, paymentOrder.uuid);
    assert.equal(queue, false);
    return Object.keys(products).filter((key) => hasKitchenRoute && products[key] === food.id);
} };
paymentStore.notification = { add: () => paymentSteps.push('send error') };
paymentStore.baseerSendCurrentOrder = async (actionType) => {
    assert.equal(actionType, 'send_before_payment');
    paymentSteps.push('send');
    for (const line of cartLines) {
        paymentOrder.last_order_preparation_change.lines[line.uuid] = {
            uuid: line.uuid, product_id: line.product_id.id, quantity: line.getQuantity(),
        };
    }
    return true;
};
assert.equal(await paymentStore.pay(), false);
assert.deepEqual(paymentSteps.splice(0), ['prompt']);
confirmSend = true;
await paymentStore.pay();
assert.deepEqual(paymentSteps.splice(0), ['prompt', 'send', 'pay']);
await paymentStore.pay();
assert.deepEqual(paymentSteps.splice(0), ['pay']);
retailQuantity++;
await paymentStore.pay();
assert.deepEqual(paymentSteps.splice(0), ['pay']);
cartLines = [foodLine];
await paymentStore.pay();
assert.deepEqual(paymentSteps.splice(0), ['pay']);
paymentOrder.last_order_preparation_change.lines = {};
paymentStore.baseerSendCurrentOrder = async () => { throw new Error('offline'); };
assert.equal(await paymentStore.validateOrderFast(), false);
assert.deepEqual(paymentSteps.splice(0), ['prompt', 'send error']);
hasKitchenRoute = false;
await paymentStore.validateOrderFast();
assert.deepEqual(paymentSteps.splice(0), ['fast pay']);
let finishRouting;
paymentStore.data.call = () => new Promise((resolve) => { finishRouting = resolve; });
cartLines = [retailLine];
const paymentWithCartEdit = paymentStore.pay();
cartLines.push(foodLine);
finishRouting([]);
assert.equal(await paymentWithCartEdit, false);
assert.deepEqual(paymentSteps, ['send error']);

// Exercise the real payment -> shared send -> acknowledgement chain, including
// a mixed cart whose non-kitchen change survives the native preparation update.
function paymentFixture() {
    const calls = { routing: 0, sent: 0, pay: 0, blocked: 0, notices: [] };
    const food = { uuid: 'food', product_id: { id: 1 }, qty: 1, getQuantity() { return this.qty; } };
    const retail = { uuid: 'retail', product_id: { id: 2 }, qty: 1, getQuantity() { return this.qty; } };
    const order = { id: 7, uuid: 'payment', isSynced: true, uiState: {},
        getOrderlines: () => [food, retail], last_order_preparation_change: { lines: {} } };
    const hooks = { confirm: async () => true, beforeSync: async () => {}, accepted: true };
    const bridge = runtime('preparation_bridge.js', {
        ask: async () => await hooks.confirm(),
        async pay() { calls.pay++; },
        async validateOrderFast() { calls.pay++; },
        async sendOrderInPreparation(current) {
            calls.sent++;
            current.last_order_preparation_change.lines.food = {
                uuid: 'food', product_id: 1, quantity: food.qty,
            };
            return false; // Direct printer bypass: server acknowledgement is authoritative.
        },
    });
    bridge.buildBaseerPreparationAction = lineRuntime.buildBaseerPreparationAction;
    const store = new bridge.PosStore();
    store.config = { id: 1, baseer_direct_print_enabled: true };
    store.getOrder = () => order;
    store.env = { services: { ui: { block() { calls.blocked++; }, unblock() { calls.blocked--; } } } };
    store.notification = { add(message) { calls.notices.push(message); return () => {}; } };
    store.data = { network: { offline: false },
        call: async () => { calls.routing++; return ['food']; },
        synchronizeLocalDataInIndexedDB: async () => {},
    };
    store.syncAllOrders = async () => { await hooks.beforeSync(); order.isSynced = true; return [order]; };
    store._baseerPreparationStatus = async () => ({ accepted: hooks.accepted });
    store._baseerNotifyPreparationStatus = () => {};
    store.addPendingOrder = () => {};
    return { store, order, food, retail, calls, hooks };
}

test('payment sends a mixed cart with one routing lookup and durable acknowledgement', async () => {
    const { store, calls } = paymentFixture();
    await store.pay();
    assert.equal(calls.routing, 1);
    assert.equal(calls.sent, 1);
    assert.equal(calls.pay, 1);
    assert.equal(calls.blocked, 0);
});

test('already sent cart opens payment without routing or a new kitchen send', async () => {
    const { store, order, calls } = paymentFixture();
    for (const line of order.getOrderlines()) order.last_order_preparation_change.lines[line.uuid] = {
        uuid: line.uuid, product_id: line.product_id.id, quantity: line.qty,
    };
    await store.pay();
    assert.equal(calls.routing, 0);
    assert.equal(calls.sent, 0);
    assert.equal(calls.pay, 1);
});

test('Back leaves the order unsent and payment closed', async () => {
    const { store, calls, hooks } = paymentFixture();
    hooks.confirm = async () => false;
    await store.pay();
    assert.equal(calls.sent, 0);
    assert.equal(calls.pay, 0);
});

test('editing the cart during confirmation requires review without sending', async () => {
    const { store, food, calls, hooks } = paymentFixture();
    hooks.confirm = async () => { food.qty++; return true; };
    await store.pay();
    assert.equal(calls.sent, 0);
    assert.equal(calls.pay, 0);
    assert.ok(calls.notices.includes('The order changed. Review it and press Payment again.'));
});

test('editing a new order during draft sync cannot reuse the previous approval', async () => {
    const { store, order, food, calls, hooks } = paymentFixture();
    order.isSynced = false;
    hooks.beforeSync = async () => { food.qty++; };
    await store.pay();
    assert.equal(calls.routing, 1);
    assert.equal(calls.sent, 0);
    assert.equal(calls.pay, 0);
    assert.equal(calls.blocked, 0);
});

test('cart edit during dispatch prevents payment without another routing request', async () => {
    const { store, retail, calls, hooks } = paymentFixture();
    hooks.beforeSync = async () => { retail.qty++; };
    await store.pay();
    assert.equal(calls.routing, 1);
    assert.equal(calls.sent, 1);
    assert.equal(calls.pay, 0);
});

test('manual Send and repeated Payment cannot overlap a payment kitchen send', { timeout: 1000 }, async () => {
    const { store, calls, hooks } = paymentFixture();
    let ready, finish;
    const started = new Promise(resolve => { ready = resolve; });
    hooks.beforeSync = () => new Promise(resolve => { finish = resolve; ready(); });
    const paying = store.pay();
    await started;
    assert.equal(await store.pay(), false);
    assert.equal(await store.baseerSendCurrentOrder(), false);
    finish();
    await paying;
    assert.equal(calls.routing, 1);
    assert.equal(calls.sent, 1);
    assert.equal(calls.pay, 1);
    assert.equal(calls.blocked, 0);
});

test('a missing acknowledgement keeps payment closed and releases the UI lock', async () => {
    const { store, order, calls, hooks } = paymentFixture();
    hooks.accepted = false;
    await store.pay();
    assert.equal(calls.pay, 0);
    assert.equal(order.uiState.baseerPreparationOutcomeUnknown, true);
    assert.equal(calls.blocked, 0);
});

test('native guest dialog stays interactive before dispatch locks the UI', async () => {
    const { store, calls } = paymentFixture();
    store.ensureGuestCustomerCount = async () => { assert.equal(calls.blocked, 0); };
    await store.pay();
    assert.equal(calls.sent, 1);
    assert.equal(calls.pay, 1);
    assert.equal(calls.blocked, 0);
});

const bridge = runtime('preparation_bridge.js', { async sendOrderInPreparation() { return false; } });
bridge.buildBaseerPreparationAction = lineRuntime.buildBaseerPreparationAction;
const store = new bridge.PosStore();
store.config = { baseer_direct_print_enabled: true, baseer_native_receipt_enabled: true,
    baseer_preparation_bindings: [{ category_id: false }] };
store.getOrder = () => null;
assert.equal(store.baseerCategoryCount.length, 0);
assert.equal(await store.sendOrderInPreparation(null), false);
const notices = [];
store.notification = { add: (message) => notices.push(message) };
const nativeCompany = { id: 2, vat: false, country_id: { id: 1, code: 'SA' } };
let companyRefreshes = 0;
store.data = { read: async (model, ids) => {
    assert.equal(model, 'res.company');
    assert.equal(ids[0], 2);
    companyRefreshes++;
    nativeCompany.vat = 'fresh-test-vat';
    return [nativeCompany];
} };
let renderedFresh = false;
store.printer = { renderer: { toCanvas: async (_component, { order: receiptOrder }) => {
    assert.equal(receiptOrder.company.vat, 'fresh-test-vat');
    renderedFresh = true;
    throw { data: { message: 'Company VAT missing' } };
} } };
const printed = await store.printReceipt({ order: { isSynced: true, id: 1, state: 'paid',
    company_id: nativeCompany, company: nativeCompany } });
assert.equal(printed.successful, false);
assert.equal(companyRefreshes, 1);
assert.equal(renderedFresh, true);
assert.ok(notices[0].includes('Company VAT missing'));
assert.ok(!notices[0].includes('connection'));
store.syncAllOrders = async () => false; // Native may return false instead of throwing.
store.data = { synchronizeLocalDataInIndexedDB: async () => true };
store._baseerPreparationStatus = async () => ({ accepted: false });
const draft = { isSynced: true, uiState: { baseerPreparationAction: { action_uuid: 'pending' } },
    last_order_preparation_change: { lines: {} } };
await assert.rejects(store.sendOrderInPreparation(draft), /not been acknowledged/);
assert.equal(draft.uiState.baseerPreparationOutcomeUnknown, true);
assert.equal(draft.uiState.baseerPreparationAction.action_uuid, 'pending');
store.getOrder = () => draft;
assert.equal(await store._baseerSendKitchenBeforePayment(), false);
function installRecoveryContract(record) {
    Object.assign(record, { id: 7, uuid: record.uuid || 'retry-draft', isSynced: true,
        company_id: { id: 2 }, config_id: { id: 3 }, state: 'draft', lines: [], payment_ids: [] });
    Object.assign(store.config, { id: 3, company_id: { id: 2 } });
    record.serializeForORM = () => {};
    record.serializeForIndexedDB = () => ({ id: record.id, uuid: record.uuid,
        JSONuiState: JSON.stringify(record.uiState) });
    store.removePendingOrder = () => {};
    const snapshot = { 'pos.order': [{ id: record.id, uuid: record.uuid, company_id: 2, config_id: 3,
        state: 'draft', lines: [], payment_ids: [] }],
        'pos.order.line': [], 'pos.payment': [], 'pos.pack.operation.lot': [], 'product.attribute.custom.value': [] };
    store.models = Object.fromEntries(Object.keys(snapshot).map(model => [model, {
        get: () => model === 'pos.order' ? record : undefined,
        getBy: () => model === 'pos.order' ? record : undefined,
        filter: predicate => model === 'pos.order' && predicate(record) ? [record] : [],
    }]));
    store.models.loadConnectedData = data => {
        Object.assign(record, data['pos.order'][0], { company_id: { id: 2 }, config_id: { id: 3 } });
    };
    let reads = 0;
    store.data = { network: { offline: false }, fields: {}, relations: {}, opts: { databaseTable: {} },
        synchronizeLocalDataInIndexedDB: async () => true,
        call: async (model, method, args, kwargs, queue) => {
            assert.equal(model, 'pos.order'); assert.equal(method, 'read_pos_data_uuid');
            assert.equal(args[0], record.uuid); assert.equal(queue, false); reads++;
            return snapshot;
        },
        missingRecursive: async data => data,
        indexedDBMutex: { exec: callback => callback() },
        indexedDB: { activeTransactions: new Set(), getNewTransaction() {
            const handlers = {};
            const requests = [];
            const request = () => { const value = { addEventListener(name, callback) { requests.push(callback); } }; return value; };
            const transaction = { addEventListener(name, callback) { handlers[name] = callback; },
                objectStore: () => ({ put: request, delete: request }), abort() { handlers.abort(); } };
            this.activeTransactions.add(transaction);
            queueMicrotask(() => { for (const callback of requests) callback(); handlers.complete(); });
            return transaction;
        } },
    };
    store.deviceSync = { readDataFromServer: async () => { throw new Error('Incremental recovery is forbidden'); } };
    return () => reads;
}
const draftReads = installRecoveryContract(draft);
store._baseerPreparationStatus = async () => ({ accepted: true });
assert.equal(await store.sendOrderInPreparation(draft), true);
assert.equal(draft.uiState.baseerPreparationOutcomeUnknown, undefined);
assert.equal(draftReads(), 1);
const acknowledgedDraft = { isSynced: true,
    uiState: { baseerPreparationAction: { action_uuid: 'confirmed-direct-action' } },
    last_order_preparation_change: { lines: {} } };
assert.equal(await store.sendOrderInPreparation(acknowledgedDraft), true);
store.config.baseer_direct_print_enabled = false;
assert.equal(await store.sendOrderInPreparation(acknowledgedDraft), false);
store.config.baseer_direct_print_enabled = true;
const recoverable = {
    uuid: 'reconcile-confirmed-cancellation',
    uiState: {
        baseerPreparationOutcomeUnknown: true,
        baseerPreparationAction: { action_uuid: 'confirmed-cancellation' },
    },
};
const recoveredRefreshes = installRecoveryContract(recoverable);
store._baseerPreparationStatus = async () => ({ accepted: true, done: true });
assert.equal(await store.baseerResolvePreparationOutcome(recoverable), true);
assert.equal(recoveredRefreshes(), 1);
assert.equal(recoverable.uiState.baseerPreparationOutcomeUnknown, undefined);
assert.equal(recoverable.uiState.baseerPreparationAction, undefined);
store.syncAllOrders = async () => { throw { data: { name: 'odoo.exceptions.ValidationError', message: 'Rejected' } }; };
store._baseerPreparationStatus = async () => ({ accepted: false });
draft.uiState.baseerPreparationAction = { action_uuid: 'rejected-new-action' };
await assert.rejects(store.sendOrderInPreparation(draft));
assert.equal(draft.uiState.baseerPreparationOutcomeUnknown, undefined);
const unfinalized = await store.printReceipt({ order: { isSynced: true, id: 2, state: 'draft' } });
assert.equal(unfinalized.successful, false);
assert.ok(notices.at(-1).includes('not finalized'));
const kitchenStore = new lineRuntime.PosStore();
kitchenStore.config = { baseer_direct_print_enabled: true };
let retired = 0;
let retained = 0;
kitchenStore.data = { network: { offline: false },
    localDeleteCascade: () => retired++, synchronizeLocalDataInIndexedDB: async () => true };
kitchenStore.env = { services: { ui: { block() {}, unblock() {} } } };
kitchenStore.sendOrderInPreparation = async () => true;
kitchenStore.addPendingOrder = () => retained++;
kitchenStore.removePendingOrder = () => {};
kitchenStore.showDefault = () => {};
kitchenStore.notification = { add() {} };
kitchenStore.dialog = { add() {} };
const otherLineRemoval = { id: 18, parentId: 9 };
const otherOrderRemoval = { id: 19, parentId: 10 };
const removalCommands = {
    unlink: new Map([['lines', [otherLineRemoval, otherOrderRemoval]]]),
    delete: new Map([['lines', [{ id: 17, parentId: 9 }]]]),
};
const paymentDraft = { id: 9, state: 'draft', uiState: {},
    models: { commands: { 'pos.order': removalCommands } },
    last_order_preparation_change: { lines: {} }, getOrderlines: () => [],
    removeOrderline(line) {
        // Native removeOrderline queues a command even when the server has
        // already removed the line during the kitchen action.
        removalCommands.unlink.get('lines').push({ id: line.id, parentId: this.id });
    } };
const cancellingLine = { id: 17, uuid: 'cancel-me', order_id: paymentDraft, getQuantity: () => 1,
    setQuantity: () => true };
assert.equal(await kitchenStore._baseerCommitSentLineQuantity(cancellingLine, 0), true);
assert.deepEqual(removalCommands.unlink.get('lines'), [otherLineRemoval, otherOrderRemoval]);
assert.equal(removalCommands.delete.has('lines'), false);
assert.equal(retired, 0); // Empty draft may still contain a deposit; server decides.
assert.equal(retained, 1);
paymentDraft.state = 'cancel';
assert.equal(await kitchenStore._baseerCommitSentLineQuantity(cancellingLine, 0), true);
assert.equal(retired, 1);
kitchenStore.config.baseer_direct_print_enabled = false;
paymentDraft.state = 'draft';
assert.equal(await kitchenStore._baseerCommitSentLineQuantity(cancellingLine, 0), true);
assert.deepEqual(removalCommands.unlink.get('lines'), [
    otherLineRemoval, otherOrderRemoval, { id: 17, parentId: 9 },
]);
let resolveCancellationChoice;
const serializedRuntime = runtime('line_actions.js', {
    makeAwaitable: async () => await new Promise((resolve) => { resolveCancellationChoice = resolve; }),
});
const serializedStore = new serializedRuntime.PosStore();
const serializedNotices = [];
serializedStore.notification = { add: (message) => serializedNotices.push(message) };
serializedStore.baseerIsSentLine = () => true;
const serializedOrder = { uiState: {} };
const serializedLine = { order_id: serializedOrder };
const firstCancellation = serializedStore.baseerCancelSentLine(serializedLine);
await Promise.resolve(); // The current-line recovery check precedes acquiring the item guard.
assert.equal(serializedOrder.uiState.baseerKitchenLineActionPending, true);
assert.equal(await serializedStore.baseerCancelSentLine(serializedLine), false);
assert.equal(serializedNotices.length, 1);
resolveCancellationChoice(null);
assert.equal(await firstCancellation, false);
assert.equal(serializedOrder.uiState.baseerKitchenLineActionPending, undefined);
const backendLocation = { href: "" };
const posExitRuntime = runtime("pos_exit.js", { window: { location: backendLocation } });
new posExitRuntime.PosStore().redirectToBackend();
assert.equal(backendLocation.href, "/odoo/action-point_of_sale.action_pos_config_kanban");
const mergeRuntime = runtime('preparation_bridge.js', {
    async _mergeOrders() { this.nativeMergeCalled = true; },
    async _mergeLines(_source, destination) { return destination; },
    async mergeOrders() { this.nativeWholeMergeCalled = true; },
    async deleteOrders(orders) { this.nativeDeleteOrders = orders; return true; },
});
const mergeStore = new mergeRuntime.PosStore();
mergeStore.config = {baseer_direct_print_enabled: true, current_session_id: 4};
let mergeUiBlocks = 0;
mergeStore.env = {services: {ui: {block() { mergeUiBlocks++; }, unblock() { mergeUiBlocks--; }}}};
const mergedSource = {id: 41, uuid: 'source', isSynced: true, state: 'draft', uiState: {}, isDirty: () => false};
const mergedDestination = {id: 42, uuid: 'destination', isSynced: true, state: 'draft', uiState: {}, isDirty: () => false,
    serializeForORM: () => ({id: 42, uuid: 'destination'})};
const mergeCalls = [];
let committed = false;
mergeStore.data = {network: {offline: false}, synchronizeLocalDataInIndexedDB: async () => true,
    silentCall: async (model, method, args) => {
        mergeCalls.push([model, method, args]);
        return {requires_transfer: true, preparation_line_uuids: ['source-line'], baseline: 'baseline'};
    },
    call: async (model, method, args, kwargs) => {
        mergeCalls.push([model, method, args, kwargs]);
        if (method === 'sync_from_ui') { committed = true; return {'pos.order': [{id: 42, uuid: 'destination'}]}; }
        if (method === 'read') return [{id: 41, uuid: 'source', state: committed ? 'cancel' : 'draft',
            baseer_merged_into_order_id: committed ? [42, 'destination'] : false}];
        throw new Error(`unexpected ${method}`);
    }};
mergeStore.models = {'pos.order': {getBy: (_field, uuid) => uuid === 'source' ? mergedSource : mergedDestination}};
let queuedOrders = [mergedSource, mergedDestination];
mergeStore.getPendingOrder = () => ({orderToCreate: [], orderToUpdate: queuedOrders});
mergeStore.syncAllOrders = async ({orders, force, throw: throwOnError}) => {
    assert.equal(force, true);
    assert.equal(throwOnError, true);
    assert.deepEqual(Array.from(orders, order => order.id), [41, 42]);
    mergeCalls.push(['flush']);
    await Promise.resolve();
    assert.equal(mergeUiBlocks, 1);
    for (const order of [mergedSource, mergedDestination]) {
        assert.throws(() => mergeRuntime.PosOrderline.prototype.setQuantity.call({order_id: order}, 9),
            /being saved for the merge/);
    }
    queuedOrders = [];
    return orders;
};
mergeStore.preSyncAllOrders = async orders => orders;
mergeStore.getSyncAllOrdersContext = (_orders, options) => options.context;
mergeStore._baseerRestoreCanonicalOrder = async () => true;
mergeStore._baseerPersistRestaurantMergeMarkers = async () => true;
mergeStore.removeOrder = order => { mergeStore.removed = order; };
mergeStore.removePendingOrder = () => {};
mergedDestination.uiState.unmerge = {'target-line': {formerUuid: 'source-line'}};
assert.equal(await mergeStore.mergeOrders(mergedSource, mergedDestination), mergedDestination);
assert.equal(mergeCalls[0][0], 'flush');
assert.equal(mergeCalls[1][1], 'baseer_begin_restaurant_merge');
assert.equal(mergeUiBlocks, 0);
assert.equal(mergeStore.nativeMergeCalled, true);
assert.equal(mergeStore.removed, mergedSource);
assert.equal(mergedDestination.uiState.baseerRestaurantMergePending, undefined);
const mergeSync = mergeCalls.find(call => call[1] === 'sync_from_ui');
assert.equal(mergeSync[3].context.baseer_restaurant_merge.source_id, 41);
assert.equal(JSON.stringify(mergeSync[3].context.baseer_restaurant_merge.line_uuid_map), JSON.stringify({'source-line': 'target-line'}));
// Never replace a preexisting unsaved edit with a canonical server snapshot.
mergedSource.isDirty = () => true;
mergedSource.localEdit = 'preserve me';
mergeStore.syncAllOrders = async () => [];
const mergeCallsBeforeFailedSave = mergeCalls.length;
await assert.rejects(mergeStore.mergeOrders(mergedSource, mergedDestination), /Save both orders/);
assert.equal(mergedSource.localEdit, 'preserve me');
assert.equal(mergeCalls.length, mergeCallsBeforeFailedSave);
assert.equal(mergeUiBlocks, 0);
assert.equal(mergedSource._baseerSavingForMerge, undefined);
mergedSource.isDirty = () => false;
mergeStore._baseerAtomicMergeLines = new Set(['sent']);
assert.equal(await mergeStore._mergeLines({uuid: 'sent'}, {id: 4}), null);
assert.equal((await mergeStore._mergeLines({uuid: 'other'}, {id: 4})).id, 4);
delete mergeStore._baseerAtomicMergeLines;
// An uncertain send retains both markers and retries the exact original payload.
const uncertainSource = {id: 51, uuid: 'uncertain-source', uiState: {}};
const uncertainDestination = {id: 52, uuid: 'uncertain-destination', uiState: {}};
const uncertainMarker = {source_id: 51, destination_id: 52, source_uuid: 'uncertain-source',
    destination_uuid: 'uncertain-destination', baseline: 'b', payload: {uuid: 'uncertain-destination', lines: [[0, 0, {qty: 2}]]},
    context: {baseer_restaurant_merge: {source_id: 51, destination_id: 52, baseline: 'b'}}};
uncertainSource.uiState.baseerRestaurantMergePending = uncertainMarker;
uncertainDestination.uiState.baseerRestaurantMergePending = uncertainMarker;
let replay = false;
const attempts = [];
mergeStore.models['pos.order'].getBy = (_field, uuid) => uuid === uncertainSource.uuid ? uncertainSource : uncertainDestination;
mergeStore.data.call = async (_model, method, args) => {
    if (method === 'sync_from_ui') {
        attempts.push(JSON.stringify(args));
        if (!replay) throw new Error('connection lost');
        return {'pos.order': [{id: 52, uuid: 'uncertain-destination'}]};
    }
    return [{id: 51, uuid: 'uncertain-source', state: 'cancel', baseer_merged_into_order_id: [52, 'destination']}];
};
assert.equal(await mergeStore._baseerRecoverRestaurantMerge(uncertainSource, uncertainDestination, uncertainMarker, true), false);
assert.equal(uncertainSource.uiState.baseerRestaurantMergePending, uncertainMarker);
assert.equal(uncertainDestination.uiState.baseerRestaurantMergePending, uncertainMarker);
replay = true;
assert.equal(await mergeStore._baseerRecoverRestaurantMerge(uncertainSource, uncertainDestination, uncertainMarker), true);
assert.equal(attempts[0], attempts[1]);
assert.equal(uncertainDestination.uiState.baseerRestaurantMergePending, undefined);
// A definite server rollback restores both drafts and must not delete source.
const rejectedSource = {id: 61, uuid: 'rejected-source', uiState: {}};
const rejectedDestination = {id: 62, uuid: 'rejected-destination', uiState: {}};
const rejectedMarker = {source_id: 61, destination_id: 62, source_uuid: 'rejected-source',
    destination_uuid: 'rejected-destination', baseline: 'b2', payload: {uuid: 'rejected-destination'}, context: {}};
rejectedSource.uiState.baseerRestaurantMergePending = rejectedMarker;
rejectedDestination.uiState.baseerRestaurantMergePending = rejectedMarker;
mergeStore.models['pos.order'].getBy = (_field, uuid) => uuid === rejectedSource.uuid ? rejectedSource : rejectedDestination;
const restored = [];
mergeStore._baseerRestoreCanonicalOrder = async order => { restored.push(order.id); return true; };
mergeStore.removed = undefined;
mergeStore.data.call = async (_model, method) => {
    if (method === 'sync_from_ui') throw {data: {name: 'odoo.exceptions.ValidationError'}};
    return [{id: 61, uuid: 'rejected-source', state: 'draft', baseer_merged_into_order_id: false}];
};
assert.equal(await mergeStore._baseerRecoverRestaurantMerge(rejectedSource, rejectedDestination, rejectedMarker), false);
assert.deepEqual(restored, [61, 62]);
assert.equal(mergeStore.removed, undefined);
assert.equal(rejectedSource.uiState.baseerRestaurantMergePending, undefined);
assert.equal(rejectedDestination.uiState.baseerRestaurantMergePending, undefined);
// A successful IDB request is not a commit: a later abort must reject and
// leave both in-memory markers intact.
const storageStore = new mergeRuntime.PosStore();
const storageOrders = [1, 2].map(id => ({id, uiState: {baseerRestaurantMergePending: {baseline: 'b'},
    baseerPreparationOutcomeUnknown: true}, serializeForIndexedDB() {
        return {id, JSONuiState: JSON.stringify(this.uiState)};
    }}));
const handlers = {};
const transaction = {error: new Error('abort after request success'),
    addEventListener(name, callback) { handlers[name] = callback; },
    objectStore() { return {put() {}, delete() {}}; }, abort() { handlers.abort(); }};
storageStore.data = {indexedDBMutex: {exec: callback => callback()}, opts: {databaseTable: {'pos.order': {key: 'id'}}},
    indexedDB: {activeTransactions: new Set([transaction]), getNewTransaction() {
        queueMicrotask(() => handlers.abort()); return transaction;
    }}};
await assert.rejects(storageStore._baseerPersistRestaurantMergeMarkers(storageOrders, {clear: true}), /abort/);
assert.ok(storageOrders.every(order => order.uiState.baseerRestaurantMergePending));
// Reload can omit the cancelled source; the durable source receipt is then
// the only authority allowing the surviving destination to be unblocked.
const reloadDestination = {id: 72, uuid: 'reload-destination', uiState: {}};
const reloadMarker = {source_id: 71, destination_id: 72, source_uuid: 'reload-source',
    destination_uuid: 'reload-destination', source_order_key: 71,
    source_stale_keys: [['pos.order.line', 901]], baseline: 'reload-b'};
reloadDestination.uiState.baseerRestaurantMergePending = reloadMarker;
reloadDestination.uiState.baseerPreparationOutcomeUnknown = true;
mergeStore.models['pos.order'].getBy = (_field, uuid) => uuid === reloadDestination.uuid ? reloadDestination : undefined;
let clearedSourceKey = false;
mergeStore.data.call = async (_model, method) => {
    assert.equal(method, 'read');
    return [{id: 71, uuid: 'reload-source', state: 'cancel', baseer_merged_into_order_id: [72, 'destination']}];
};
mergeStore._baseerRestoreCanonicalOrder = async () => ({'pos.order': [{id: 72}], 'pos.order.line': []});
mergeStore._baseerPersistRestaurantMergeMarkers = async (_orders, options) => {
    clearedSourceKey = options.removeSource && options.marker.source_order_key === 71
        && options.staleKeys.some(([model, key]) => model === 'pos.order.line' && key === 901);
};
assert.equal(await mergeStore.baseerResolvePreparationOutcome(reloadDestination), true);
assert.equal(clearedSourceKey, true);
assert.equal(reloadDestination.uiState.baseerRestaurantMergePending, undefined);
const selectionPopupSources = ["preparation_bridge.js", "line_actions.js"]
    .map((file) => readFileSync(new URL(`../static/src/app/${file}`, import.meta.url), "utf8"));
const selectionPopupBodies = selectionPopupSources.flatMap((source) => source.match(/SelectionPopup,\s*\{[\s\S]*?\n\s*\}\);/g) || []);
assert.ok(selectionPopupBodies.length > 0);
assert.ok(selectionPopupBodies.every((props) => !/\bbody\s*:/.test(props)), "SelectionPopup accepts only its supported props");
console.log('PASS bridge frontend: silent quantities, null order, precise receipt error, authoritative kitchen ack, valid selection popup props');

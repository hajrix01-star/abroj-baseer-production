// Focused dependency-free tests for bridge intent and failure handling.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

function runtime(file, native = {}) {
    class PosStore {}
    Object.assign(PosStore.prototype, native);
    const sandbox = {
        PosStore, PosOrder: class {}, Orderline: class {}, OrderSummary: class {},
        SelectionPopup: class {}, TextInputPopup: class {}, ConfirmationDialog: class {},
        AlertDialog: class {}, NumberPopup: class {}, OrderReceipt: class {}, crypto: webcrypto,
        makeAwaitable: native.makeAwaitable || (async () => null),
        ask: native.ask || (async () => true),
        window: native.window || { location: {} },
        _t: (message, value) => message.replace('%s', value ?? '%s'),
        patch(target, extension) {
            Object.setPrototypeOf(extension, { ...target });
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

const bridge = runtime('preparation_bridge.js', { async sendOrderInPreparation() { return true; } });
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
assert.equal(await store._baseerConfirmPaymentWithoutKitchen(), false);
store._baseerPreparationStatus = async () => ({ accepted: true });
assert.equal(await store.sendOrderInPreparation(draft), true);
assert.equal(draft.uiState.baseerPreparationOutcomeUnknown, undefined);
let recoveredRefreshes = 0;
const recoverable = {
    uuid: 'reconcile-confirmed-cancellation',
    uiState: {
        baseerPreparationOutcomeUnknown: true,
        baseerPreparationAction: { action_uuid: 'confirmed-cancellation' },
    },
};
store.data = { network: { offline: false }, synchronizeLocalDataInIndexedDB: async () => true };
store.deviceSync = { readDataFromServer: async () => recoveredRefreshes++ };
store._baseerPreparationStatus = async () => ({ accepted: true, done: true });
assert.equal(await store.baseerResolvePreparationOutcome(recoverable), true);
assert.equal(recoveredRefreshes, 1);
assert.equal(recoverable.uiState.baseerPreparationOutcomeUnknown, undefined);
assert.equal(recoverable.uiState.baseerPreparationAction, undefined);
store.syncAllOrders = async () => { throw { data: { name: 'odoo.exceptions.ValidationError', message: 'Rejected' } }; };
store._baseerPreparationStatus = async () => ({ accepted: false });
await assert.rejects(store.sendOrderInPreparation(draft));
assert.equal(draft.uiState.baseerPreparationOutcomeUnknown, undefined);
const unfinalized = await store.printReceipt({ order: { isSynced: true, id: 2, state: 'draft' } });
assert.equal(unfinalized.successful, false);
assert.ok(notices.at(-1).includes('not finalized'));
const kitchenStore = new lineRuntime.PosStore();
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
const paymentDraft = { id: 9, state: 'draft', uiState: {},
    last_order_preparation_change: { lines: {} }, getOrderlines: () => [], removeOrderline() {} };
const cancellingLine = { uuid: 'cancel-me', order_id: paymentDraft, getQuantity: () => 1,
    setQuantity: () => true };
assert.equal(await kitchenStore._baseerCommitSentLineQuantity(cancellingLine, 0), true);
assert.equal(retired, 0); // Empty draft may still contain a deposit; server decides.
assert.equal(retained, 1);
paymentDraft.state = 'cancel';
assert.equal(await kitchenStore._baseerCommitSentLineQuantity(cancellingLine, 0), true);
assert.equal(retired, 1);
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
const selectionPopupSources = ["preparation_bridge.js", "line_actions.js"]
    .map((file) => readFileSync(new URL(`../static/src/app/${file}`, import.meta.url), "utf8"));
const selectionPopupBodies = selectionPopupSources.flatMap((source) => source.match(/SelectionPopup,\s*\{[\s\S]*?\n\s*\}\);/g) || []);
assert.ok(selectionPopupBodies.length > 0);
assert.ok(selectionPopupBodies.every((props) => !/\bbody\s*:/.test(props)), "SelectionPopup accepts only its supported props");
console.log('PASS bridge frontend: silent quantities, null order, precise receipt error, authoritative kitchen ack, valid selection popup props');

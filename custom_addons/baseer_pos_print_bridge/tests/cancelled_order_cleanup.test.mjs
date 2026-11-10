import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import { nativeOrderCancellation, nativeWholeOrderDeletion } from './native_cancel_contract.mjs';

const source = readFileSync(new URL('../static/src/app/line_actions.js', import.meta.url), 'utf8');
const start = source.indexOf('    async _baseerCommitSentLineQuantity(');
const end = source.indexOf('    async baseerCancelSentLine(', start);
const context = vm.createContext({
    clonePreparationState: (order) => JSON.parse(JSON.stringify(order.last_order_preparation_change)),
    getBaseerSentQuantity: () => 1,
    getBaseerSilentQuantity: () => 0,
    buildBaseerPreparationAction: (_order, _kind, lines) => ({ action_uuid: 'this-action', lines }),
    _t: (message) => message,
    AlertDialog: class {},
});
const helperStart = source.indexOf('export function captureBaseerCancellationRoute(');
const helperEnd = source.indexOf('function preparationLine(', helperStart);
vm.runInContext(source.slice(helperStart, helperEnd).replace(/export function /g, 'function '), context);
const commit = vm.runInContext(`({${source.slice(start, end)}})`, context)._baseerCommitSentLineQuantity;

function fixture({ restaurant = false, render = true, terminal = true, switchRoute = false,
    failSave = false, failCleanup = false, rejectSend = false, unknown = false, ack = true } = {}) {
    const calls = { send: 0, retire: 0, deletedLines: 0, save: 0, unblock: 0, navigation: [], notices: [] };
    const order = Object.create(nativeOrderCancellation);
    Object.assign(order, { id: 2684, uuid: 'cancelled-order', state: 'draft',
        uiState: { lineToRefund: {} }, lines: [], payment_ids: [],
        last_order_preparation_change: { lines: { line: { quantity: 1 } } },
        models: { commands: { 'pos.order': { unlink: new Map(), delete: new Map() } } },
        getLastOrderline() { return this.lines.at(-1); }, selectOrderline() {},
    });
    const line = { id: 9, uuid: 'line', order_id: order, qty: 1,
        getQuantity() { return this.qty; }, setQuantity(value) { this.qty = value; return true; },
        getAllLinesInCombo() { return [this]; },
        delete() { calls.deletedLines++; order.lines = order.lines.filter((item) => item !== this); },
    };
    order.lines = [line];
    const fallback = { uuid: 'native-fallback', state: 'draft', lines: [{ qty: 1, price: 11.50 }],
        payment_ids: [{ uuid: 'fallback-payment', amount: 11.50 }] };
    const fallbackBefore = JSON.stringify(fallback);
    let selected = order;
    let saved = false;
    const store = {
        config: { baseer_direct_print_enabled: true, module_pos_restaurant: restaurant },
        router: { state: { current: 'ProductScreen', params: { orderUuid: order.uuid } } },
        getOrder: () => selected,
        setOrder: (value) => { selected = value; },
        _baseerCurrentKitchenLine: async (value) => value,
        removePendingOrder() {}, addPendingOrder() {},
        notification: { add: (message) => calls.notices.push(message) }, dialog: { add() {} },
        env: { services: { ui: { block() {}, unblock() { calls.unblock++; } } } },
        navigate(page, params = {}) {
            assert.equal(saved, true, 'navigate only after durable cleanup');
            calls.navigation.push([page, params.orderUuid]);
            this.router.state = { current: page, params };
        },
        showDefault() { selected = fallback; this.navigate('ProductScreen', { orderUuid: fallback.uuid }); },
        async sendOrderInPreparation() {
            calls.send++;
            if (rejectSend) throw Object.assign(new Error('send failed'), { baseerPreparationOutcomeUnknown: unknown });
            if (!ack) return false;
            if (terminal) {
                order.state = 'cancel'; order.lines = [];
                order.last_order_preparation_change = { lines: { line: { quantity: 0 } } };
                // Native loading can retain this removed line's order backref.
                // ProductScreen then selects another draft without navigating.
                if (render) selected = fallback;
            }
            if (switchRoute) {
                selected = { uuid: 'other-order', state: 'draft' };
                this.router.state = { current: 'ProductScreen', params: { orderUuid: selected.uuid } };
            }
            return true;
        },
        data: {
            network: { offline: false },
            localDeleteCascade(record) {
                assert.equal(record.state, 'cancel');
                if (failCleanup) throw new Error('local cleanup failed');
                calls.retire++;
            },
            async synchronizeLocalDataInIndexedDB() {
                calls.save++;
                if (failSave) throw new Error('storage failed');
                saved = true;
            },
        },
    };
    return { store, order, line, calls, selected: () => selected,
        verifyUnchangedDraft: () => assert.equal(JSON.stringify(fallback), fallbackBefore),
        run: () => commit.call(store, line, 0, { reasonCode: 'customer_cancelled' }) };
}

test('QA native contract rejects removal from a cancelled order', () => {
    const f = fixture(); f.order.state = 'cancel';
    assert.throws(() => f.order.removeOrderline(f.line), /Finalized Order cannot be modified/);
});
for (const restaurant of [false, true]) {
    for (const render of [false, true]) {
        test(`actual sent-line cancellation preserves acknowledgement: restaurant=${restaurant}, render=${render}`, async () => {
            const f = fixture({ restaurant, render });
            assert.equal(await f.run(), true);
            assert.equal(f.calls.send, 1); assert.equal(f.calls.retire, 1);
            assert.equal(f.calls.deletedLines, 0); assert.equal(f.calls.save, 1);
            assert.equal(f.line.qty, 0); assert.equal(f.order.state, 'cancel');
            assert.deepEqual(f.calls.notices, []);
            assert.deepEqual(f.calls.navigation, restaurant ? [['FloorScreen', undefined]] : [['ProductScreen', 'native-fallback']]);
            if (restaurant) assert.equal(f.selected(), null);
            f.verifyUnchangedDraft();
        });
    }
    test(`another routed order stays selected: restaurant=${restaurant}`, async () => {
        const f = fixture({ restaurant, switchRoute: true });
        assert.equal(await f.run(), true);
        assert.deepEqual(f.calls.navigation, []);
        assert.equal(f.selected().uuid, 'other-order');
        f.verifyUnchangedDraft();
    });
}
test('surviving draft keeps native line cleanup without retirement', async () => {
    const f = fixture({ terminal: false });
    assert.equal(await f.run(), true);
    assert.equal(f.calls.deletedLines, 1); assert.equal(f.calls.retire, 0);
    assert.deepEqual(f.calls.navigation, []);
});
test('TicketScreen is not redirected', async () => {
    const f = fixture({ restaurant: true }); f.store.router.state.current = 'TicketScreen';
    assert.equal(await f.run(), true); assert.deepEqual(f.calls.navigation, []);
});
test('storage failure keeps canonical cancellation and never navigates', async () => {
    const f = fixture({ failSave: true });
    await assert.rejects(f.run(), /storage failed/);
    assert.equal(f.order.state, 'cancel'); assert.equal(f.line.qty, 0);
    assert.equal(f.order.last_order_preparation_change.lines.line.quantity, 0);
    assert.deepEqual(f.calls.navigation, []); assert.equal(f.calls.unblock, 1);
});
test('local cleanup failure cannot restore a cancelled item or claim it was kept', async () => {
    const f = fixture({ failCleanup: true });
    assert.equal(await f.run(), false);
    assert.equal(f.line.qty, 0); assert.equal(f.order.last_order_preparation_change.lines.line.quantity, 0);
    assert.deepEqual(f.calls.notices, ['Kitchen cancellation was recorded.']);
    assert.deepEqual(f.calls.navigation, []);
});
test('unacknowledged send never retires or navigates', async () => {
    const f = fixture({ ack: false });
    assert.equal(await f.run(), false); assert.equal(f.calls.retire, 0);
    assert.deepEqual(f.calls.navigation, []);
});
test('rejected draft send retains existing rollback behavior', async () => {
    const f = fixture({ rejectSend: true });
    assert.equal(await f.run(), false); assert.equal(f.line.qty, 1);
    assert.equal(f.calls.retire, 0); assert.deepEqual(f.calls.navigation, []);
});
test('uncertain send retains its quantity and does not retire or navigate', async () => {
    const f = fixture({ rejectSend: true, unknown: true });
    assert.equal(await f.run(), false); assert.equal(f.line.qty, 0);
    assert.equal(f.calls.retire, 0); assert.deepEqual(f.calls.navigation, []);
});

const preparation = readFileSync(new URL('../static/src/app/preparation_bridge.js', import.meta.url), 'utf8');
const deletionStart = preparation.indexOf('    async onDeleteOrder(order)');
const deletionEnd = preparation.indexOf('    async beforeDeleteOrder(', deletionStart);
const deletionPatch = vm.runInContext(`({${preparation.slice(deletionStart, deletionEnd)}})`, context);
Object.setPrototypeOf(deletionPatch, nativeWholeOrderDeletion);

function wholeFixture({ allowed = true, nativeSuccess = true, restaurant = false,
    direct = true, switchRoute = false, failSave = false } = {}) {
    const order = { uuid: 'whole-cancelled', lines: [], uiState: {} };
    const next = { uuid: 'last-open-draft', state: 'draft', lines: [{ qty: 1, price: 11.50 }],
        payment_ids: [{ uuid: 'untouched-payment', amount: 11.50 }] };
    const before = JSON.stringify(next);
    let selected = order, exists = true, durable = false;
    const calls = { delete: 0, save: 0, navigation: [] };
    const store = {
        config: { module_pos_restaurant: restaurant, baseer_direct_print_enabled: direct },
        router: { state: { current: 'ProductScreen', params: { orderUuid: order.uuid } } },
        getOrder: () => selected,
        setOrder: (value) => { selected = value; },
        getOpenOrders: () => [next],
        beforeDeleteOrder: async () => allowed,
        afterOrderDeletion: nativeWholeOrderDeletion.afterOrderDeletion,
        async deleteOrders(orders) {
            assert.equal(orders[0], order); calls.delete++;
            if (!nativeSuccess) return false;
            exists = false; selected = undefined;
            // Native restaurant.removeOrder already redirects to Floor.
            if (restaurant) this.router.state = { current: 'FloorScreen', params: {} };
            if (switchRoute) this.router.state = { current: 'ProductScreen', params: { orderUuid: 'another-route' } };
            return true;
        },
        models: { 'pos.order': { getBy: () => exists ? order : undefined } },
        data: { async synchronizeLocalDataInIndexedDB() {
            calls.save++; if (failSave) throw new Error('storage failed'); durable = true;
        } },
        navigate(page, params) {
            assert.equal(durable, true); calls.navigation.push([page, params.orderUuid]);
            this.router.state = { current: page, params };
        },
    };
    return { store, order, calls, selected: () => selected,
        verifyUnchanged: () => assert.equal(JSON.stringify(next), before),
        run: () => deletionPatch.onDeleteOrder.call(store, order) };
}

test('QA native whole-order caller changes selection without changing its route', async () => {
    const f = wholeFixture();
    assert.equal(await nativeWholeOrderDeletion.onDeleteOrder.call(f.store, f.order), true);
    assert.equal(f.selected().uuid, 'last-open-draft');
    assert.equal(f.store.router.state.params.orderUuid, 'whole-cancelled');
});
test('whole-order normal cancellation routes after native afterOrderDeletion', async () => {
    const f = wholeFixture();
    assert.equal(await f.run(), true);
    assert.equal(f.calls.delete, 1); assert.equal(f.calls.save, 1);
    assert.deepEqual(f.calls.navigation, [['ProductScreen', 'last-open-draft']]);
    assert.equal(f.store.router.state.params.orderUuid, f.selected().uuid);
    f.verifyUnchanged();
});
for (const options of [{ allowed: false }, { nativeSuccess: false }, { switchRoute: true }]) {
    test(`whole-order wrapper does not redirect without ownership/success: ${JSON.stringify(options)}`, async () => {
        const f = wholeFixture(options); await f.run();
        assert.deepEqual(f.calls.navigation, []); f.verifyUnchanged();
    });
}
test('whole-order TicketScreen retains the native screen', async () => {
    const f = wholeFixture(); f.store.router.state.current = 'TicketScreen';
    await f.run(); assert.deepEqual(f.calls.navigation, []);
});
test('whole-order restaurant follows its existing native floor redirect', async () => {
    const f = wholeFixture({ restaurant: true });
    await f.run(); assert.equal(f.store.router.state.current, 'FloorScreen');
    assert.equal(f.calls.delete, 1); assert.equal(f.calls.save, 0);
    assert.deepEqual(f.calls.navigation, []); f.verifyUnchanged();
});
test('whole-order non-direct printing remains native', async () => {
    const f = wholeFixture({ direct: false });
    await f.run(); assert.equal(f.calls.save, 0); assert.deepEqual(f.calls.navigation, []);
});
test('whole-order failed durable save never navigates', async () => {
    const f = wholeFixture({ failSave: true });
    await assert.rejects(f.run(), /storage failed/); assert.deepEqual(f.calls.navigation, []);
    f.verifyUnchanged();
});

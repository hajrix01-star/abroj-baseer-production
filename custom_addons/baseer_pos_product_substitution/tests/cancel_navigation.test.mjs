import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

// Execute the real reconciliation method, including its asynchronous boundary.
const source = readFileSync(new URL('../static/src/app/substitution.js', import.meta.url), 'utf8');
const start = source.indexOf('    async baseerReconcileProtectedState(');
const end = source.indexOf('    async baseerExecuteProtectedIntent(', start);
const reconcile = vm.runInNewContext(`({${source.slice(start, end)}})`).baseerReconcileProtectedState;

function fixture({ restaurant = false, render = true, cancelled = true, background = false,
    switchRoute = false, storageFails = false } = {}) {
    const order = { id: 1, uuid: 'cancelled-order', state: 'draft', uiState: {}, lines: [], payment_ids: [] };
    const fallback = { uuid: 'native-fallback', state: 'draft', lines: [{ qty: 1, price: 11.50 }],
        payment_ids: [], isFilledDirectSale: restaurant };
    const other = { uuid: 'user-selected-order', state: 'draft' };
    const originalFallback = JSON.stringify(fallback);
    let selected = background ? other : order;
    let durable = false;
    const navigation = [];
    const store = {
        config: { module_pos_restaurant: restaurant },
        router: { state: { current: 'ProductScreen', params: { orderUuid: selected.uuid } } },
        getOrder: () => selected,
        setOrder: (value) => { selected = value; },
        removePendingOrder() {},
        navigate(page, params = {}) {
            assert.equal(durable, true, 'navigation must follow durable canonical storage');
            navigation.push([page, params.orderUuid]);
            this.router.state = { current: page, params };
        },
        showDefault() { this.navigate('ProductScreen', { orderUuid: fallback.uuid }); },
        models: {
            'pos.order': { getBy: () => order, serializeForORM() {} },
            loadConnectedData() { order.state = cancelled ? 'cancel' : 'draft'; return { 'pos.order': [order] }; },
        },
        data: {
            missingRecursive: async (value) => value,
            async synchronizeLocalDataInIndexedDB() {
                // Odoo ProductScreen.onWillRender selects addNewOrder() when
                // canonical loading changes the displayed order to cancelled.
                // Restaurant may reuse an existing unsynced direct-sale draft.
                if (render && selected === order && order.state !== 'draft') selected = fallback;
                if (switchRoute) {
                    selected = other;
                    store.router.state = { current: 'ProductScreen', params: { orderUuid: other.uuid } };
                }
                if (storageFails) throw new Error('storage failed');
                durable = true;
            },
        },
    };
    return {
        store, order, fallback, navigation,
        selected: () => selected,
        verifyUntouched: () => assert.equal(JSON.stringify(fallback), originalFallback),
        run: () => reconcile.call(store, { data: {
            'pos.order': [{ uuid: order.uuid }], 'pos.order.line': [], 'pos.payment': [],
        } }, order.uuid),
    };
}

for (const restaurant of [false, true]) {
    for (const render of [false, true]) {
        test(`cancelled current order navigates after storage: restaurant=${restaurant}, render=${render}`, async () => {
            const f = fixture({ restaurant, render });
            await f.run();
            assert.deepEqual(f.navigation, restaurant ? [['FloorScreen', undefined]] : [['ProductScreen', 'native-fallback']]);
            if (restaurant) assert.equal(f.selected(), null);
            f.verifyUntouched();
        });
    }
    test(`another routed order retains selection: restaurant=${restaurant}`, async () => {
        const f = fixture({ restaurant, switchRoute: true });
        await f.run();
        assert.deepEqual(f.navigation, []);
        assert.equal(f.selected().uuid, 'user-selected-order');
        f.verifyUntouched();
    });
    test(`background cancellation never redirects: restaurant=${restaurant}`, async () => {
        const f = fixture({ restaurant, background: true });
        await f.run();
        assert.deepEqual(f.navigation, []);
        assert.equal(f.selected().uuid, 'user-selected-order');
    });
}

test('a surviving draft does not navigate', async () => {
    const f = fixture({ cancelled: false });
    await f.run();
    assert.deepEqual(f.navigation, []);
});

test('TicketScreen cancellation retains its native screen', async () => {
    const f = fixture({ restaurant: true });
    f.store.router.state.current = 'TicketScreen';
    await f.run();
    assert.deepEqual(f.navigation, []);
});

test('navigation to another screen without an order UUID is preserved', async () => {
    const f = fixture({ restaurant: true });
    const save = f.store.data.synchronizeLocalDataInIndexedDB;
    f.store.data.synchronizeLocalDataInIndexedDB = async () => {
        await save();
        f.store.router.state = { current: 'FloorScreen', params: {} };
    };
    await f.run();
    assert.deepEqual(f.navigation, []);
});

test('failed durable storage never navigates', async () => {
    const f = fixture({ storageFails: true });
    await assert.rejects(f.run(), /storage failed/);
    assert.deepEqual(f.navigation, []);
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

function fixture() {
    class PosOrder {
        getName() { return this.table_id ? 'T 7' : this.tracking_number; }
    }
    class ReceiptHeader { get order() { return this.props.order; } }
    class OrderTabs {}
    class TicketScreen {
        _getSearchFields() { return { REFERENCE: { repr: (order) => order.getName() } }; }
        _computeSyncedOrdersDomain() {
            return [['company_id', '=', 7], ['tracking_number', 'ilike', '%' + this.state.search.searchTerm + '%']];
        }
    }
    class PosStore {
        async addLineToOrder(vals, order) { order.lines.push(vals); return vals; }
        addPendingOrder(ids) { this.pending = ids; }
        async syncAllOrders({ orders: [order] }) {
            this.syncs++;
            Object.assign(order, { baseer_ticket_number: 1, baseer_ticket_label: '27-1', isSynced: true });
        }
        async printReceipt() { return 'native receipt'; }
        async sendOrderInPreparation() { return 'native kitchen'; }
        getOrderData(order) { return { tracking_number: order.tracking_number, pos_reference: 'original' }; }
    }
    const source = readFileSync(new URL('../static/src/app/session_ticket.js', import.meta.url), 'utf8');
    vm.runInNewContext(source.replace(/^import .*;\r?\n/gm, ''), {
        PosOrder, OrderTabs, ReceiptHeader, TicketScreen, PosStore, _t: (text) => text,
        patch(target, extension) {
            const previous = Object.create(Object.getPrototypeOf(target), Object.getOwnPropertyDescriptors(target));
            Object.setPrototypeOf(extension, previous);
            Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
        },
    });
    const order = Object.assign(new PosOrder(), {
        id: 'order', tracking_number: '8001', state: 'draft', uiState: {}, lines: [],
        session_id: { id: 27, baseer_ticket_enabled: true },
        generateQrcode() { return 'signed existing QR'; },
    });
    const header = Object.assign(new ReceiptHeader(), { props: { order } });
    const store = Object.assign(new PosStore(), {
        syncs: 0, data: { network: { offline: false } }, config: { printerCategories: new Set([1]) }, notification: { add() {} },
    });
    const screen = Object.assign(new TicketScreen(), { state: { search: { fieldName: 'REFERENCE', searchTerm: '27-1' } } });
    return { order, header, store, screen, tabs: new OrderTabs() };
}

test('cashier tabs use numeric order without moving named or historical slots', () => {
    const { tabs } = fixture();
    const tab = (name, number, table) => ({ getName: () => name, baseer_ticket_number: number, table_id: table });
    tabs.props = { orders: [tab('2', 2), tab('10', 10), tab('15', 0), tab('1', 1), tab('T 7', 3, {})] };
    assert.deepEqual(tabs.sortedTicketTabs.map((order) => order.getName()), ['1', '2', '15', '10', 'T 7']);
});

test('same ticket on early/paid receipts and kitchen, short tab and native tax QR', async () => {
    const { order, header, store } = fixture();
    assert.equal(order.getName(), 'Awaiting number');
    assert.equal(header.order.tracking_number, '');
    await store.addLineToOrder({ qty: 1 }, order);
    await store.addLineToOrder({ qty: 2 }, order);
    assert.equal(store.syncs, 1);
    assert.equal(order.getName(), '1');
    assert.equal(store.getOrderData(order).tracking_number, '27-1');
    assert.equal(store.getOrderData(order).pos_reference, 'original');
    for (const state of ['draft', 'paid']) {
        order.state = state;
        assert.equal(await store.printReceipt({ order }), 'native receipt');
        assert.equal(header.order.tracking_number, '27-1');
        assert.equal(header.order.generateQrcode(), 'signed existing QR');
        assert.equal(order.tracking_number, '8001');
    }
    order.table_id = { id: 7 };
    assert.equal(order.getName(), 'T 7');
    order.table_id = null;
    order.isRefund = true;
    assert.equal(order.getName(), '1 (Refund)');
});

test('offline unsaved order keeps pending state; reconnect before printing allocates once', async () => {
    const { order, store } = fixture();
    store.data.network.offline = true;
    await store.addLineToOrder({ qty: 1 }, order);
    assert.equal(store.syncs, 0);
    assert.equal(store.pending[0], 'order');
    assert.equal((await store.printReceipt({ order })).successful, false);
    assert.equal(await store.sendOrderInPreparation(order, { byPassPrint: true }), 'native kitchen');
    store.config.printerCategories.clear();
    assert.equal(await store.sendOrderInPreparation(order), 'native kitchen');
    store.config.printerCategories.add(1);
    assert.equal(await store.sendOrderInPreparation(order), false);
    store.data.network.offline = false;
    assert.equal(await store.sendOrderInPreparation(order), 'native kitchen');
    assert.equal(await store.printReceipt({ order }), 'native receipt');
    assert.equal(store.syncs, 1);
});

test('pre-existing and moved legacy orders retain original numbers; direct sale waits for native booking', async () => {
    const { order, store, header } = fixture();
    order.isSynced = true;
    assert.equal(order.getName(), '8001');
    assert.equal(header.order, order);
    order.isSynced = false;
    order.session_id.baseer_ticket_enabled = false;
    await store.addLineToOrder({ qty: 1 }, order);
    assert.equal(store.syncs, 0);
    assert.equal(order.getName(), '8001');
    const direct = fixture();
    direct.order.isDirectSale = true;
    await direct.store.addLineToOrder({ qty: 1 }, direct.order);
    assert.equal(direct.store.syncs, 0);
    assert.equal(await direct.store.printReceipt({ order: direct.order }), 'native receipt');
    assert.equal(direct.store.syncs, 1);
});

test('searching printed or short number augments the tracking leaf within the original company restriction', () => {
    const { screen } = fixture();
    function domain(term) {
        screen.state.search.searchTerm = term;
        return JSON.parse(JSON.stringify(screen._computeSyncedOrdersDomain()));
    }
    assert.deepEqual(domain('27-1'), [['company_id', '=', 7], '|', ['tracking_number', 'ilike', '%27-1%'],
        '&', ['baseer_ticket_session_id', '=', 27], ['baseer_ticket_number', '=', 1]]);
    assert.deepEqual(domain('1'), [['company_id', '=', 7], '|', ['tracking_number', 'ilike', '%1%'],
        ['baseer_ticket_number', '=', 1]]);
    assert.equal(domain('9999999999').length, 2);
    assert.equal(domain('271-27-000001').length, 2);
});

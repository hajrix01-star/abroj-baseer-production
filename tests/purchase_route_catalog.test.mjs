import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = readFileSync(new URL('../custom_addons/baseer_procurement_requests/static/src/procurement_catalog.js', import.meta.url), 'utf8');
// Execute the actual component methods without fabricating Owl/browser acceptance.
const routeBody = source.match(/setPurchaseRoute\(route\) \{([\s\S]*?)\n    \}/)[1];
const saveBody = source.match(/get canSave\(\) \{([\s\S]*?)\n    \}/)[1];
const setRoute = new Function('route', routeBody);
const canSave = new Function(saveBody);
const draftBody = source.match(/async saveDraft\(openWhatsApp = false\) \{([\s\S]*?)\n    \}/)[1];
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const saveDraft = new AsyncFunction('openWhatsApp', 'newClientToken', '_t', draftBody);
const component = () => ({ state: {
    existingRequest: false, purchaseRoute: 'representative', representativePartnerId: 42,
    warehouseId: 1, cart: [{}], saving: false, quotePending: false, quoteError: false,
    quote: { lines: [{}] },
}, unpricedReceivedLines: [] });

test('cash/bank clear representative and can save; returning to representative requires choice', () => {
    for (const route of ['cash', 'bank_transfer']) {
        const c = component();
        setRoute.call(c, route);
        assert.equal(c.state.purchaseRoute, route);
        assert.equal(c.state.representativePartnerId, false);
        assert.equal(canSave.call(c), true);
        setRoute.call(c, 'representative');
        assert.equal(canSave.call(c), false);
        c.state.representativePartnerId = 42;
        assert.equal(canSave.call(c), true);
    }
});
test('existing requests and unknown routes cannot change the route', () => {
    const c = component();
    setRoute.call(c, 'invalid');
    assert.equal(c.state.purchaseRoute, 'representative');
    c.state.existingRequest = { id: 1 };
    setRoute.call(c, 'cash');
    assert.equal(c.state.purchaseRoute, 'representative');
    assert.equal(c.state.representativePartnerId, 42);
});
test('route choices retain quote/warehouse save guards', () => {
    const c = component();
    setRoute.call(c, 'cash');
    c.state.quotePending = true;
    assert.equal(canSave.call(c), false);
    c.state.quotePending = false;
    c.state.warehouseId = false;
    assert.equal(canSave.call(c), false);
});

function submission(route) {
    const c = component();
    setRoute.call(c, route);
    c.state.clientToken = 'original-token';
    c.state.cart = [{ option_id: 5, quantity: '2.00' }];
    const calls = [], actions = [], notices = [];
    Object.defineProperty(c, 'canSave', { get: () => canSave.call(c) });
    c.orm = { call: async (model, method, args) => {
        calls.push({ model, method, args });
        return method === 'action_open_whatsapp' ? { type: 'ir.actions.act_url', url: 'wa.me/test' } : 91;
    } };
    c.action = { doAction: async (action) => actions.push(action) };
    c.notification = { add: (...args) => notices.push(args) };
    return { c, calls, actions, notices };
}

test('cash/bank primary action submits route then sends without WhatsApp', async () => {
    for (const route of ['cash', 'bank_transfer']) {
        const { c, calls, actions, notices } = submission(route);
        await saveDraft.call(c, true, () => 'next-token', (text) => text);
        assert.deepEqual(calls.map((call) => call.method), ['create_from_catalog', 'action_mark_sent']);
        assert.deepEqual(calls[0].args, [[{ option_id: 5, quantity: '2.00' }], 1, false, false, 'original-token', false, route]);
        assert.deepEqual(calls[1].args, [[91]]);
        assert.equal(actions.length, 1);
        assert.equal(actions[0].res_id, 91);
        assert.deepEqual(actions[0].views, [[false, 'form']]);
        assert.equal(c.state.clientToken, 'next-token');
        assert.equal(c.state.saving, false);
        assert.deepEqual(notices, []);
    }
});

test('representative primary action preserves WhatsApp and representative RPC arguments', async () => {
    const { c, calls, actions, notices } = submission('representative');
    await saveDraft.call(c, true, () => 'next-token', (text) => text);
    assert.deepEqual(calls.map((call) => call.method), ['create_from_catalog', 'action_open_whatsapp']);
    assert.equal(calls[0].args[5], 42);
    assert.equal(calls[0].args[6], 'representative');
    assert.deepEqual(calls[1].args, [[91]]);
    assert.equal(actions[0].type, 'ir.actions.act_url');
    assert.equal(actions[1].res_id, 91);
    assert.deepEqual(notices, []);
});

test('save-only never sends; pending quote prevents all submission RPCs', async () => {
    for (const route of ['cash', 'bank_transfer', 'representative']) {
        const { c, calls } = submission(route);
        c.state.quotePending = true;
        await saveDraft.call(c, true, () => 'next-token', (text) => text);
        assert.deepEqual(calls, []);
        c.state.quotePending = false;
        await saveDraft.call(c, false, () => 'next-token', (text) => text);
        assert.deepEqual(calls.map((call) => call.method), ['create_from_catalog']);
        assert.equal(calls[0].args[6], route);
    }
});

function cartComponent(existing = false) {
    const c = { state: { existingRequest: existing, cart: [] }, quotes: 0,
        scheduleQuote() { this.quotes++; } };
    for (const [name, args] of Object.entries({
        remove: ['line'], markNotReceived: ['line'], restoreReceived: ['line'],
        setQuantity: ['line', 'value'], commitQuantity: ['line'],
        isNotReceived: ['line'], stepQuantity: ['line', 'step'],
    })) {
        const body = source.match(new RegExp(`    ${name}\\([^\\n]*\\) \\{([\\s\\S]*?)\\n    \\}`));
        if (body) c[name] = new Function(...args, body[1]);
    }
    return c;
}

test('receipt minus at zero never restores a missing item or its price', () => {
    const c = cartComponent(true);
    const line = { quantity: '0', actual_price: '0', requested_quantity: '4', last_price: '10' };
    c.state.cart = [line];
    c.stepQuantity(line, -1);
    c.stepQuantity(line, -1);
    assert.equal(Number(line.quantity), 0);
    assert.equal(Number(line.actual_price), 0);
    assert.equal(c.quotes, 0);
});

test('new-cart committed zero and minus from one both remove only the intended item', () => {
    for (const manual of [false, true]) {
        const c = cartComponent();
        const line = { quantity: '1' }, other = { quantity: '2' };
        c.state.cart = [line, other];
        if (manual) { c.setQuantity(line, '0'); c.commitQuantity(line); }
        else c.stepQuantity(line, -1);
        assert.deepEqual(c.state.cart, [other]);
    }
});

test('typing a fractional new quantity retains the row until input is committed', () => {
    const c = cartComponent();
    const line = { quantity: '1' };
    c.state.cart = [line];
    for (const value of ['', '0', '0.5']) c.setQuantity(line, value);
    c.commitQuantity(line);
    assert.equal(c.state.cart[0], line);
    assert.equal(Number(line.quantity), 0.5);
    c.stepQuantity(line, 1);
    assert.equal(Number(line.quantity), 1.5);
    c.stepQuantity(line, -1);
    assert.equal(Number(line.quantity), 0.5);
});

test('receipt zero, remove and repeated minus preserve the edited snapshot for explicit restore', () => {
    for (const action of ['manual', 'remove', 'minus']) {
        const c = cartComponent(true);
        const line = { quantity: '0.5', actual_price: '13.25', requested_quantity: '4', last_price: '10' };
        c.state.cart = [line];
        if (action === 'manual') { c.setQuantity(line, '0'); c.commitQuantity(line); }
        else if (action === 'remove') c.remove(line);
        else c.stepQuantity(line, -1);
        assert.equal(Number(line.quantity), 0);
        assert.equal(Number(line.actual_price), 0);
        c.stepQuantity(line, -1);
        c.remove(line); // explicit restore control
        assert.equal(Number(line.quantity), 0.5);
        assert.equal(Number(line.actual_price), 13.25);
        assert.equal(c.state.cart.length, 1);
    }
});

test('receipt plus from zero restores price while increasing to one', () => {
    const c = cartComponent(true);
    const line = { quantity: '3', actual_price: '12', requested_quantity: '4', last_price: '10' };
    c.remove(line);
    c.stepQuantity(line, 1);
    assert.equal(Number(line.quantity), 1);
    assert.equal(Number(line.actual_price), 12);
});

test('receipt typing through a blank field restores the last edited price', () => {
    const c = cartComponent(true);
    const line = { quantity: '3', actual_price: '12', requested_quantity: '4', last_price: '10' };
    c.remove(line);
    c.setQuantity(line, '');
    c.setQuantity(line, '2');
    c.commitQuantity(line);
    assert.equal(Number(line.quantity), 2);
    assert.equal(Number(line.actual_price), 12);
});

test('blank and negative receipt quantities are invalid input, not a not-received state', () => {
    const c = cartComponent(true);
    for (const quantity of ['', '-1', 'invalid']) assert.equal(c.isNotReceived({ quantity }), false);
    assert.equal(c.isNotReceived({ quantity: '0' }), true);
});

test('old quote responses cannot repopulate an emptied cart or unlock a newer edit', async () => {
    for (const empty of [false, true]) {
        const c = cartComponent();
        c.quoteSequence = 0;
        c.emptyQuote = () => ({ lines: [], total_text: '0.00' });
        c.state.quote = { lines: [{ option_id: 1 }], total_text: '10.00' };
        c.state.cart = [{ option_id: 1, quantity: '1' }];
        let resolve;
        c.orm = { call: () => new Promise((done) => { resolve = done; }) };
        const schedule = source.match(/    scheduleQuote\(\) \{([\s\S]*?)\n    \}/)[1];
        const refresh = source.match(/    async refreshQuote\(\) \{([\s\S]*?)\n    \}/)[1];
        c.scheduleQuote = new Function(schedule);
        c.refreshQuote = new AsyncFunction(refresh);
        const pending = c.refreshQuote();
        if (empty) c.remove(c.state.cart[0]);
        else c.setQuantity(c.state.cart[0], '2');
        clearTimeout(c.quoteTimer);
        resolve({ lines: [{ option_id: 1 }], total_text: 'STALE' });
        await pending;
        assert.notEqual(c.state.quote.total_text, 'STALE');
        assert.equal(c.state.quotePending, !empty);
        if (empty) assert.deepEqual(c.state.quote.lines, []);
    }
});

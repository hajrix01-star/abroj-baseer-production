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

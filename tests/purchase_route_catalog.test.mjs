import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = readFileSync(process.env.PROCUREMENT_SOURCE_FILE || new URL('../custom_addons/baseer_procurement_requests/static/src/procurement_catalog.js', import.meta.url), 'utf8');
const template = readFileSync(process.env.PROCUREMENT_TEMPLATE_FILE || new URL('../custom_addons/baseer_procurement_requests/static/src/procurement_catalog.xml', import.meta.url), 'utf8');
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
        return method === 'action_open_whatsapp' ? { type: 'ir.actions.client', tag: 'baseer_procurement_requests.whatsapp_share', params: { request_id: 91, url: 'https://wa.me/?text=test', text: 'test' } } : 91;
    } };
    c.action = { doAction: async (action) => actions.push(action) };
    c.notification = { add: (...args) => notices.push(args) };
    c.emptyQuote = () => ({ lines: [], total_text: '0.00' });
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
    assert.equal(actions[0].type, 'ir.actions.client');
    assert.equal(actions[0].tag, 'baseer_procurement_requests.whatsapp_share');
    assert.equal(actions[0].params.open_saved_request, true);
    assert.equal(actions.length, 1);
    assert.deepEqual(c.state.cart, []);
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
    c.notices = [];
    c.notification = { add: (...args) => c.notices.push(args) };
    for (const [name, args] of Object.entries({
        remove: ['line'], markNotReceived: ['line'], restoreReceived: ['line'],
        setQuantity: ['line', 'value'], commitQuantity: ['line'],
        isNotReceived: ['line'], stepQuantity: ['line', 'step'],
        add: ['option'], quoteLine: ['line'], receiptLines: [],
        editorLines: [], editorFingerprint: [], restoreEditorLine: ['line'], setPlannedPrice: ['line', 'value'],
        closeProductOptions: [], selectProductOption: ['option'],
    })) {
        const body = source.match(new RegExp(`    ${name}\\([^\\n]*\\) \\{([\\s\\S]*?)\\n    \\}`));
        if (body) {
            const method = new Function(...args, '_t', body[1]);
            c[name] = (...values) => method.call(c, ...values, (text) => text);
        }
    }
    return c;
}

function editorComponent() {
    const c = cartComponent();
    c.state.editRequest = { id: 71, snapshot: 'snapshot-a', purchase_route: 'cash' };
    c.state.removedLines = [];
    c.state.purchaseRoute = 'cash';
    c.state.representativePartnerId = false;
    c.state.warehouseId = 1;
    c.state.quote = { lines: [{}] };
    c.unpricedReceivedLines = [];
    Object.defineProperty(c, 'canSave', { get: () => canSave.call(c) });
    Object.defineProperty(c, 'editorDirty', { get: () => c.editorFingerprint() !== c.state.editorBaseline });
    return c;
}

test('order editor increases requested quantity freely while receipt caps remain unchanged', () => {
    const c = editorComponent();
    const line = { line_id: 2, option_id: 4, product_id: 7, quantity: '5', requested_quantity: '5', maximum_quantity: '5', unit_price: '20' };
    c.state.cart = [line];
    c.stepQuantity(line, 1);
    assert.equal(line.quantity, '6');
    assert.equal(c.notices.length, 0);
    assert.deepEqual(c.editorLines(), [{ line_id: 2, option_id: 4, quantity: '6', unit_price: '20' }]);
});

test('quantity buttons preserve two-decimal inputs without binary rounding digits', () => {
    const c = editorComponent();
    const line = { quantity: '0.14' };
    c.stepQuantity(line, 1);
    assert.equal(line.quantity, '1.14');
    c.stepQuantity(line, -1);
    assert.equal(line.quantity, '0.14');
});

test('editor zero and delete preserve quantity and price for explicit restoration', () => {
    for (const manual of [false, true]) {
        const c = editorComponent();
        const line = { line_id: 2, option_id: 4, product_id: 7, quantity: '1', unit_price: '18.75' };
        c.state.cart = [line];
        if (manual) { c.setQuantity(line, '0'); c.commitQuantity(line); }
        else c.stepQuantity(line, -1);
        assert.equal(c.state.cart.length, 0);
        assert.equal(c.state.removedLines.length, 1);
        c.restoreEditorLine(c.state.removedLines[0]);
        assert.equal(c.state.cart[0].quantity, '1');
        assert.equal(c.state.cart[0].unit_price, '18.75');
        assert.equal(c.state.removedLines.length, 0);
    }
});

test('packaging and material replacement preserve original line identity and use selected price', () => {
    const c = editorComponent();
    const original = { line_id: 2, option_id: 4, product_id: 7, quantity: '6.50', unit_price: '18.75' };
    c.state.cart = [original];
    c.state.replacementLine = original;
    c.add({ id: 8, product_id: 7, product_name: 'Rice', option_name: 'Carton', packaging_note: '12 packs', last_price: '35.25', currency_symbol: 'SR' });
    assert.equal(c.state.cart.length, 1);
    assert.deepEqual(c.editorLines(), [{ line_id: 2, option_id: 8, quantity: '6.50', unit_price: '35.25' }]);
    assert.equal(c.state.replacementLine, false);
    c.add({ id: 9, product_id: 7, last_price: '10' });
    assert.equal(c.state.cart.length, 1);
    assert.equal(c.notices.length, 1);
});

test('a removed replacement target cannot replace an unrelated final cart row', async () => {
    const c = editorComponent();
    const target = { line_id: 2, option_id: 4, product_id: 7, quantity: '1', unit_price: '18.75' };
    const other = { line_id: 3, option_id: 5, product_id: 8, quantity: '2', unit_price: '10' };
    c.state.cart = [target, other];
    let finish;
    c.orm = { call: () => new Promise((resolve) => { finish = resolve; }) };
    const body = source.match(/    async changePackaging\(line\) \{([\s\S]*?)\n    \}/)[1];
    const loading = new AsyncFunction('line', '_t', body).call(c, target, (text) => text);
    c.remove(target);
    finish([{ id: 8, product_id: 7, last_price: '35' }]);
    await loading;
    assert.equal(c.state.selectedProduct, undefined);
    assert.equal(Boolean(c.state.replacementLine), false);
    c.state.replacementLine = target; // a stale option click must also be harmless
    c.add({ id: 8, product_id: 7, last_price: '35' });
    assert.deepEqual(c.state.cart, [other]);
});

test('size selection overlay is outside panes that can be hidden on mobile', () => {
    const stack = [];
    let overlays = 0;
    for (const match of template.matchAll(/<(\/?)([\w:.-]+)\b((?:"[^"]*"|'[^']*'|[^'">])*)>/g)) {
        const [, closing, tag, attributes] = match;
        if (closing) { assert.equal(stack.pop().tag, tag); continue; }
        if (/class="o_prc_option_overlay"/.test(attributes)) {
            overlays++;
            assert.equal(stack.some((ancestor) => /o_prc_(product|cart)_pane/.test(ancestor.attributes)), false);
            assert.equal(stack.at(-1).tag, 'main');
        }
        if (!/\/\s*$/.test(attributes)) stack.push({ tag, attributes });
    }
    assert.equal(overlays, 1);
});

test('packaging selection, unchanged choice and cancellation keep the mobile cart visible', async () => {
    for (const choice of ['different', 'same', 'cancel']) {
        const c = editorComponent();
        const target = { line_id: 2, option_id: 4, product_id: 7, quantity: '1', unit_price: '18.75' };
        c.state.cart = [target];
        c.state.mobilePane = 'cart';
        c.orm = { call: async () => [{ id: 8, product_id: 7, last_price: '35' }] };
        const body = source.match(/    async changePackaging\(line\) \{([\s\S]*?)\n    \}/)[1];
        await new AsyncFunction('line', '_t', body).call(c, target, (text) => text);
        assert.equal(c.state.mobilePane, 'cart');
        assert.equal(c.state.selectedProduct.options.length, 1);
        if (choice === 'cancel') c.closeProductOptions();
        else c.selectProductOption({ id: choice === 'same' ? 4 : 8, product_id: 7, last_price: '35' });
        assert.equal(c.state.mobilePane, 'cart');
        assert.equal(c.state.selectedProduct, false);
        assert.equal(c.state.replacementLine, false);
        assert.equal(c.state.cart[0].option_id, choice === 'different' ? 8 : 4);
    }
});

test('editor save changes calls only planned-save RPC and applies the returned snapshot', async () => {
    const c = editorComponent();
    c.state.cart = [{ line_id: 2, option_id: 4, product_id: 7, quantity: '6', unit_price: '18.75' }];
    c.state.editorBaseline = 'before';
    const calls = [];
    const response = { id: 71, snapshot: 'snapshot-b' };
    c.orm = { call: async (...args) => { calls.push(args); return response; } };
    c.applyEditor = (value) => { c.applied = value; };
    c.loadRecentRequests = async () => {};
    const body = source.match(/    async saveEditor\(\) \{([\s\S]*?)\n    \}/)[1];
    await new AsyncFunction('_t', body).call(c, (text) => text);
    assert.deepEqual(calls, [['baseer.procurement.request', 'save_catalog_edit', [71,
        [{ line_id: 2, option_id: 4, quantity: '6', unit_price: '18.75' }], 'cash', false, 'snapshot-a']]]);
    assert.equal(c.applied, response);
    assert.equal(c.state.saving, false);
});

test('dirty editor navigation waits for explicit discard and supports keeping edits', async () => {
    const c = editorComponent();
    c.state.cart = [{ option_id: 4, quantity: '6', unit_price: '18.75' }];
    c.state.editorBaseline = 'before';
    let dialog;
    c.dialog = { add: (_component, props) => { dialog = props; } };
    const body = source.match(/    async allowEditorLeave\(\) \{([\s\S]*?)\n    \}/)[1];
    const leave = new AsyncFunction('_t', 'ConfirmationDialog', body);
    const kept = leave.call(c, (text) => text, {});
    dialog.cancel();
    assert.equal(await kept, false);
    const discarded = leave.call(c, (text) => text, {});
    dialog.confirm();
    assert.equal(await discarded, true);
    c.state.saving = true;
    assert.equal(await leave.call(c, (text) => text, {}), false);
});

test('editor quote sends planned price and snapshot and never invokes receipt or creation', async () => {
    const c = editorComponent();
    c.state.cart = [{ option_id: 4, quantity: '6', unit_price: '18.75' }];
    c.quoteSequence = 0;
    const calls = [];
    c.orm = { call: async (...args) => { calls.push(args); return { lines: [{ option_id: 4 }], total_text: '112.50' }; } };
    const body = source.match(/    async refreshQuote\(\) \{([\s\S]*?)\n    \}/)[1];
    await new AsyncFunction('_t', body).call(c, (text) => text);
    assert.deepEqual(calls, [['baseer.procurement.request', 'quote_catalog_edit', [71,
        [{ option_id: 4, quantity: '6', unit_price: '18.75' }], 'cash', false, 'snapshot-a']]]);
    assert.equal(c.state.quote.total_text, '112.50');
    assert.equal(c.state.quotePending, false);
});

test('cancellation sends reason and snapshot without saving staged order changes', async () => {
    const c = editorComponent();
    c.state.cancelReason = 'Duplicate order';
    c.state.quotePending = true;
    c.state.quoteError = 'Stale quote error';
    const calls = [];
    c.orm = { call: async (...args) => { calls.push(args); return { id: 71, state: 'cancel' }; } };
    c.emptyQuote = () => ({ lines: [], total_text: '0.00' });
    c.loadRecentRequests = async () => {};
    const body = source.match(/    async cancelEditor\(\) \{([\s\S]*?)\n    \}/)[1];
    await new AsyncFunction('_t', body).call(c, (text) => text);
    assert.deepEqual(calls, [['baseer.procurement.request', 'cancel_catalog_edit', [71, 'snapshot-a', 'Duplicate order']]]);
    assert.equal(c.state.workspaceTab, 'recent');
    assert.equal(c.state.editRequest, false);
    assert.equal(c.state.quotePending, false);
    assert.equal(c.state.quoteError, false);
});

test('receipt minus at zero never restores a missing item or its price', () => {
    const c = cartComponent(true);
    const line = { line_id: 1, quantity: '0', actual_price: '0', requested_quantity: '4', last_price: '10' };
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
        const line = { line_id: 1, quantity: '0.5', actual_price: '13.25', requested_quantity: '4', last_price: '10' };
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
    const line = { line_id: 1, quantity: '3', actual_price: '12', requested_quantity: '4', last_price: '10' };
    c.remove(line);
    c.stepQuantity(line, 1);
    assert.equal(Number(line.quantity), 1);
    assert.equal(Number(line.actual_price), 12);
});

test('receipt typing through a blank field restores the last edited price', () => {
    const c = cartComponent(true);
    const line = { line_id: 1, quantity: '3', actual_price: '12', requested_quantity: '4', last_price: '10' };
    c.remove(line);
    c.setQuantity(line, '');
    c.setQuantity(line, '2');
    c.commitQuantity(line);
    assert.equal(Number(line.quantity), 2);
    assert.equal(Number(line.actual_price), 12);
});

test('blank and negative receipt quantities are invalid input, not a not-received state', () => {
    const c = cartComponent(true);
    for (const quantity of ['', '-1', 'invalid']) assert.equal(c.isNotReceived({ line_id: 1, quantity }), false);
    assert.equal(c.isNotReceived({ line_id: 1, quantity: '0' }), true);
});

const receiptOption = { id: 7, product_id: 9, product_name: 'Added material', option_name: 'kg', last_price: '10.25', currency_symbol: 'SR' };
test('receipt addition starts at catalogue price and has only option identity in the payload', () => {
    const c = cartComponent({ id: 3, state: 'sent', can_add_materials: true });
    c.add(receiptOption);
    assert.equal(c.state.cart[0].actual_price, '10.25');
    assert.equal(c.state.cart[0].currency_symbol, 'SR');
    assert.deepEqual(c.receiptLines(), [{ option_id: 7, actual_qty: '1', actual_price: '10.25' }]);
});

test('unpriced receipt addition is explicit zero price rather than an undefined field', () => {
    const c = cartComponent({ id: 3, can_add_materials: true });
    c.add({ ...receiptOption, last_price: '0.00' });
    assert.equal(c.state.cart[0].actual_price, '0.00');
});

test('temporary receipt rows delete on trash or committed zero and never remove originals', () => {
    for (const operation of ['trash', 'zero', 'minus']) {
        const c = cartComponent({ id: 3, can_add_materials: true });
        const original = { line_id: 4, option_id: 2, quantity: '1', actual_price: '5' };
        c.state.cart.push(original);
        c.add(receiptOption);
        const added = c.state.cart[1];
        if (operation === 'trash') c.remove(added);
        else if (operation === 'minus') c.stepQuantity(added, -1);
        else { c.setQuantity(added, '0'); c.commitQuantity(added); }
        assert.deepEqual(c.state.cart, [original]);
    }
});

test('multiple new receipt rows match their own quote identities', () => {
    const c = cartComponent({ id: 3 });
    c.state.quote = { lines: [{ line_id: 4, option_id: 2, line_total_text: '5.00' },
        { line_id: false, option_id: 7, line_total_text: '10.25' },
        { line_id: false, option_id: 8, line_total_text: '20.00' }] };
    assert.equal(c.quoteLine({ option_id: 7 }).line_total_text, '10.25');
    assert.equal(c.quoteLine({ option_id: 8 }).line_total_text, '20.00');
    assert.equal(c.quoteLine({ line_id: 4, option_id: 2 }).line_total_text, '5.00');
});

test('handover and BWork flags prevent unsupportable temporary additions', () => {
    for (const state of ['sent', 'received']) {
        const c = cartComponent({ id: 3, state, can_add_materials: false });
        c.add(receiptOption);
        assert.deepEqual(c.state.cart, []);
        assert.equal(c.notices.length, 1);
    }
});

test('clicking an existing original honours its cap and restores the last price at zero', () => {
    const c = cartComponent({ id: 3, can_add_materials: true });
    const original = { line_id: 4, option_id: 7, quantity: '1', actual_price: '20', maximum_quantity: '1', requested_quantity: '1', last_price: '10' };
    c.state.cart = [original];
    c.add(receiptOption);
    assert.equal(original.quantity, '1');
    assert.equal(c.notices.length, 1);
    c.remove(original);
    c.add(receiptOption);
    assert.equal(original.quantity, '1');
    assert.equal(original.actual_price, '20');
});

test('confirmation sends both original and new identities without snapshots or view metadata', async () => {
    const c = cartComponent({ id: 3, can_add_materials: true, name: 'test' });
    c.state.cart = [{ line_id: 4, option_id: 2, quantity: '1', actual_price: '5', receivedSnapshot: { quantity: '2' } }];
    c.add(receiptOption);
    c.canSave = true;
    c.emptyQuote = () => ({ lines: [] });
    c.loadRecentRequests = async () => {};
    const calls = [];
    c.orm = { call: async (...args) => calls.push(args) };
    await saveDraft.call(c, false, () => 'unused', (text) => text);
    assert.deepEqual(calls, [['baseer.procurement.request', 'confirm_actual_from_catalog', [3, [
        { line_id: 4, actual_qty: '1', actual_price: '5' },
        { option_id: 7, actual_qty: '1', actual_price: '10.25' },
    ]]]]);
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

function whatsappEditor() {
    const c = editorComponent();
    c.state.purchaseRoute = 'representative';
    c.state.cart = [{ line_id: 2, option_id: 4, quantity: '1.00', unit_price: '9.25' }];
    c.state.editorBaseline = c.editorFingerprint();
    c.state.shareLoading = false;
    c.calls = []; c.dialogs = [];
    c.orm = { call: async (...args) => { c.calls.push(args); return { request_id: 71, text: 'saved message', url: 'https://wa.me/?text=saved' }; } };
    c.dialog = { add: (_component, props) => c.dialogs.push(props) };
    const body = source.match(/    async openEditorWhatsApp\(\) \{([\s\S]*?)\n    \}/)?.[1];
    assert.ok(body, 'draft editor exposes a WhatsApp preparation action');
    const open = new AsyncFunction('_t', 'ProcurementWhatsAppDialog', body);
    c.openWhatsApp = () => open.call(c, (text) => text, {});
    return c;
}

test('draft WhatsApp opens a read-only saved preview without save, send, receipt or opening audit', async () => {
    const c = whatsappEditor();
    await c.openWhatsApp();
    assert.deepEqual(c.calls, [['baseer.procurement.request', 'prepare_catalog_whatsapp', [71, 'snapshot-a']]]);
    assert.equal(c.dialogs[0].payload.text, 'saved message');
    assert.equal(c.state.shareLoading, false);
    for (const guard of ['dirty', 'cash', 'saving', 'pending']) {
        const guarded = whatsappEditor();
        if (guard === 'dirty') guarded.state.cart[0].unit_price = '10';
        if (guard === 'cash') guarded.state.purchaseRoute = 'cash';
        if (guard === 'saving') guarded.state.saving = true;
        if (guard === 'pending') guarded.state.shareLoading = true;
        await guarded.openWhatsApp();
        assert.deepEqual(guarded.calls, []);
    }
});

test('draft WhatsApp ignores a late response after local edits or a different request', async () => {
    for (const changed of ['price', 'request']) {
        const c = whatsappEditor(); let done;
        c.orm = { call: () => new Promise((resolve) => { done = resolve; }) };
        const pending = c.openWhatsApp();
        if (changed === 'price') c.state.cart[0].unit_price = '12';
        else c.state.editRequest = { id: 72, snapshot: 'other' };
        done({ request_id: 71, text: 'stale' });
        await pending;
        assert.equal(c.dialogs.length, 0);
        assert.equal(c.state.shareLoading, false);
    }
});

test('draft WhatsApp failure keeps the order and enables retry without creating anything', async () => {
    const c = whatsappEditor();
    const before = c.editorFingerprint();
    c.orm = { call: async () => { throw { data: { arguments: ['Reload the order'] } }; } };
    await c.openWhatsApp();
    assert.equal(c.state.shareLoading, false);
    assert.equal(c.editorFingerprint(), before);
    assert.equal(c.dialogs.length, 0);
    assert.equal(c.notices[0][0], 'Reload the order');
});

test('WhatsApp direct link keeps the browser gesture and offers a readable copy fallback', () => {
    const dialog = template.slice(template.indexOf('<t t-name="baseer_procurement_requests.WhatsAppShareDialog">'));
    assert.match(dialog, /<a[^>]+t-att-href="props.payload.url"[^>]+target="_blank"[^>]+rel="noopener noreferrer"/);
    assert.doesNotMatch(dialog.match(/<a[^>]+>/)?.[0] || '', /\.prevent/);
    assert.match(dialog, /<textarea[^>]+readonly="readonly"[^>]+t-esc="props.payload.text"/);
    assert.match(dialog, /Copy message/);
    assert.doesNotMatch(source, /window\.open\(/);
});

test('WhatsApp copy uses the saved message and reports a manual fallback when clipboard is unavailable', async () => {
    const body = source.match(/    async copyMessage\(\) \{([\s\S]*?)\n    \}/)?.[1];
    assert.ok(body);
    const copy = new AsyncFunction('navigator', '_t', body);
    const c = { props: { payload: { text: 'طلب مشتريات\n9.25 SR' } }, state: {} };
    let copied;
    await copy.call(c, { clipboard: { writeText: async (text) => { copied = text; } } }, (text) => text);
    assert.equal(copied, c.props.payload.text);
    assert.equal(c.state.copyStatus, 'Message copied.');
    await copy.call(c, {}, (text) => text);
    assert.equal(c.state.copyStatus, 'Select the message below and copy it manually.');
});

test('WhatsApp opening audit is separate from preparation and cannot block the native link', async () => {
    const body = source.match(/    async recordOpened\(\) \{([\s\S]*?)\n    \}/)?.[1];
    assert.ok(body);
    const audit = new AsyncFunction('_t', body);
    const calls = [], notices = [];
    const c = { props: { payload: { request_id: 71 } }, env: { services: { orm: { call: async (...args) => { calls.push(args); throw Error('offline'); } } } }, notification: { add: (...args) => notices.push(args) } };
    await audit.call(c, (text) => text);
    assert.deepEqual(calls, [['baseer.procurement.request', 'action_mark_whatsapp_opened', [[71]]]]);
    assert.equal(notices.length, 1);
});

test('saved-new-request handoff allows its own navigation while protecting saving editors', async () => {
    const body = source.match(/    async allowEditorLeave\(\) \{([\s\S]*?)\n    \}/)[1];
    const leave = new AsyncFunction('_t', 'ConfirmationDialog', body);
    const c = { state: { saving: true, editRequest: false }, allowSavedRequestNavigation: false };
    assert.equal(await leave.call(c), false);
    c.allowSavedRequestNavigation = true;
    assert.equal(await leave.call(c), true);
    c.state.editRequest = { id: 71 };
    assert.equal(await leave.call(c), false);
});

test('WhatsApp share action opens the saved form before adding its dialog and keeps native callers in place', async () => {
    const body = source.match(/add\("baseer_procurement_requests.whatsapp_share", async \(env, action\) => \{([\s\S]*?)\n\}\);/)[1];
    const run = new AsyncFunction('env', 'action', 'ProcurementWhatsAppDialog', body);
    for (const newRequest of [false, true]) {
        const events = [], dialogs = [];
        const env = { services: {
            action: { doAction: async (action) => { events.push('form'); assert.equal(action.res_id, 91); dialogs.length = 0; } },
            dialog: { add: (_component, props) => { events.push('dialog'); dialogs.push(props); } },
        } };
        await run(env, { params: { request_id: 91, text: 'saved', open_saved_request: newRequest } }, {});
        assert.deepEqual(events, newRequest ? ['form', 'dialog'] : ['dialog']);
        assert.equal(dialogs.length, 1);
    }
});

test('sharing failure after creation retains the saved request and cannot create a duplicate', async () => {
    const { c, calls, actions, notices } = submission('representative');
    c.orm.call = async (model, method, args) => {
        calls.push({ model, method, args });
        if (method === 'action_open_whatsapp') throw Error('network failure');
        return 91;
    };
    await saveDraft.call(c, true, () => 'new-token', (text) => text);
    assert.deepEqual(calls.map((call) => call.method), ['create_from_catalog', 'action_open_whatsapp']);
    assert.deepEqual(c.state.cart, []);
    assert.equal(c.state.clientToken, 'new-token');
    assert.equal(actions[0].res_id, 91);
    assert.equal(notices.length, 1);
    assert.equal(c.allowSavedRequestNavigation, false);
    assert.equal(c.state.saving, false);
});

test('successful WhatsApp audit refreshes the clean editor version after the metadata write', async () => {
    const body = source.match(/    async recordOpened\(\) \{([\s\S]*?)\n    \}/)[1];
    const audit = new AsyncFunction('_t', body);
    const events = [];
    const c = { props: { payload: { request_id: 71 }, onOpened: async () => events.push('refresh') },
        env: { services: { orm: { call: async () => events.push('audit') } } } };
    await audit.call(c, (text) => text);
    assert.deepEqual(events, ['audit', 'refresh']);
});

test('WhatsApp metadata refresh never overwrites a locally changed order', async () => {
    const body = source.match(/    async refreshSharedEditor\(requestId\) \{([\s\S]*?)\n    \}/)[1];
    const refresh = new AsyncFunction('requestId', '_t', body);
    for (const dirtyWhen of ['before', 'during', 'clean']) {
        const c = whatsappEditor(); let finish;
        c.applyEditor = (value) => { c.applied = value; };
        c.orm = { call: () => new Promise((resolve) => { finish = resolve; }) };
        if (dirtyWhen === 'before') c.state.cart[0].unit_price = '12';
        const pending = refresh.call(c, 71, (text) => text);
        if (dirtyWhen === 'during') c.state.cart[0].unit_price = '12';
        if (finish) finish({ id: 71, snapshot: 'after-audit' });
        await pending;
        assert.equal(Boolean(c.applied), dirtyWhen === 'clean');
    }
});

test('WhatsApp metadata refresh respects unmount, another request, in-flight save and packaging selection', async () => {
    const body = source.match(/    async refreshSharedEditor\(requestId\) \{([\s\S]*?)\n    \}/)[1];
    const refresh = new AsyncFunction('requestId', '_t', body);
    for (const stage of ['before', 'during']) {
        for (const condition of ['unmount', 'request', 'saving', 'packaging', 'loading', 'replacement']) {
            const c = whatsappEditor(); let finish;
            c.catalogAlive = true;
            c.applyEditor = () => { c.applied = true; };
            c.orm = { call: () => new Promise((resolve) => { finish = resolve; }) };
            const change = () => {
                if (condition === 'unmount') c.catalogAlive = false;
                if (condition === 'request') c.state.editRequest = { id: 72 };
                if (condition === 'saving') c.state.saving = true;
                if (condition === 'packaging') c.state.selectedProduct = { id: 7 };
                if (condition === 'loading') c.state.editorLoading = true;
                if (condition === 'replacement') c.state.replacementLine = { id: 4 };
            };
            if (stage === 'before') change();
            const pending = refresh.call(c, 71, (text) => text);
            if (stage === 'during') change();
            if (finish) finish({ id: 71, snapshot: 'after-audit' });
            await pending;
            assert.equal(Boolean(c.applied), false, `${stage}/${condition}`);
        }
    }
});

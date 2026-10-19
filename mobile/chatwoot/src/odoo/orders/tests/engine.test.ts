// @ts-nocheck -- executable in Node without coupling product types to node:test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { OrdersEngine } from '../core/OrdersEngine.ts';
import { bytes, validateConfirmInput, validateCreateInput } from '../core/validators.ts';

const summary = (company = 1, orderId = 100) => ({ id: orderId, name: 'PR100', company_id: company, company_name: 'Company', requester_id: 7, requester_name: 'Owner', state: 'sent', purchase_route: 'cash', purchase_route_name: 'Cash', representative_id: null, representative_name: '', requested_total: '12.30', currency_symbol: 'SAR', submitted_at: '2026-10-19T00:00:00Z', room_id: null });
const receiptSummary = (company = 1) => ({ id: 100, name: 'PR100', company_id: company, warehouse_name: 'Main', requester_name: 'Owner', state: 'sent', requested_total: '12.30', currency_symbol: 'SAR', submitted_at: null });
const createInput = (quantity = '1.00') => ({ company_id: 1, warehouse_id: 3, purchase_route: 'cash', representative_partner_id: null, lines: [{ option_id: 9, quantity }] });
const confirmInput = () => ({ company_id: 1, lines: [{ line_id: 77, actual_qty: '1', actual_price: '12.30' }, { line_id: 78, actual_qty: '0', actual_price: '0' }] });
const options = (extras = {}) => ({ api_version: 2, workflow_version: 1, receipt_list_version: 1, access: 'operator', can_view: true, can_create: true, can_receive: true, companies: [{ id: 1, name: 'First' }, { id: 2, name: 'Second' }], ...extras });
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
async function setup() {
  const data = new Map(); const calls = []; let writes = 0; let counter = 0;
  let identity = { origin: 'https://example.test', db: 'db', uid: 7, epoch: 1, verified: true, companyIds: [1, 2], permissions: { order_view: true, order_create: true, order_receive: true, chat_send: true } };
  let storageFail = () => false; let handler;
  let unauthorized = 0; let forbidden = 0;
  const storage = { getItem: async key => data.get(key) ?? null, setItem: async (key, value) => { writes += 1; if (storageFail(writes)) throw new Error('disk full'); data.set(key, value); } };
  const deps = { storage, identityScope: () => identity, now: () => 1234, uuid: () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`, onUnauthorized: () => { unauthorized += 1; }, onForbidden: () => { forbidden += 1; }, transport: { request: async request => {
    calls.push(request); if (handler) return handler(request);
    if (request.path.endsWith('/options')) return options();
    if (request.path.endsWith('/catalog')) return { api_version: 2, items: [], next_after_id: null };
    if (request.path.endsWith('/share')) return { api_version: 2, order_id: 100, room_id: 8, message_id: 99, shared: true, replayed: false };
    if (request.path.endsWith('/confirm')) return { api_version: 2, client_uuid: request.payload.client_uuid, replayed: false, receipt: { order_id: 100, name: 'PR100', state: 'purchased', company_id: request.payload.company_id, actual_total: '12.30', currency_symbol: 'SAR', picking_id: null, confirmed_at: null, confirmed_by_id: 7 } };
    if (request.path.endsWith('/receipts')) return { api_version: 2, orders: [receiptSummary(request.query.company_id)], next_before_id: null };
    if (request.method === 'POST') return { api_version: 2, client_uuid: request.payload.client_uuid, replayed: false, order: summary(request.payload.company_id) };
    return { api_version: 2, orders: [summary(2), summary(1, 99)], next_before_id: null };
  } } };
  const engine = new OrdersEngine(deps);
  await engine.options(); calls.length = 0;
  return { engine, deps, data, calls, get writes() { return writes; }, get identity() { return identity; }, set identity(value) { identity = value; }, handler: value => { handler = value; }, storageFail: value => { storageFail = value; }, callbacks: () => ({ unauthorized, forbidden }) };
}
const code = expected => error => error.code === expected;

test('unified list uses scope=all, global cursor and authorized row companies', async () => {
  const t = await setup(); const page = await t.engine.list();
  assert.equal(page.orders[0].company_id, 2); assert.deepEqual(t.calls[0].query, { scope: 'all' });
  await t.engine.list(101); assert.deepEqual(t.calls[1].query, { scope: 'all', before_id: 101 });
  t.handler(() => ({ api_version: 2, orders: [summary(5)], next_before_id: null }));
  await assert.rejects(t.engine.list(), code('invalid_response'));
});
test('detail targets row company and scope=all, never a selected header company', async () => {
  const t = await setup(); t.handler(() => ({ api_version: 2, order: { ...summary(2), warehouse_id: 6 }, lines: [] }));
  await t.engine.detail(2, 100); assert.deepEqual(t.calls[0].query, { company_id: 2, scope: 'all' });
  await assert.rejects(t.engine.detail(1, 100), code('invalid_response'));
});

test('global receipts require explicit server capability and validate one authorized global page', async () => {
  const t = await setup();
  t.handler(request => ({ api_version: 2, orders: [receiptSummary(2), { ...receiptSummary(1), id: 99 }], next_before_id: 99 }));
  const page = await t.engine.receipts(undefined, 101);
  assert.deepEqual(t.calls[0].query, { scope: 'all', before_id: 101 });
  assert.deepEqual(page.orders.map(row => row.company_id), [2, 1]);
  for (const response of [
    { orders: [receiptSummary(3)], next_before_id: null },
    { orders: [receiptSummary()], next_before_id: 101 },
    { orders: [receiptSummary()], next_before_id: 99 },
    { orders: [{ ...receiptSummary(), state: 'purchased' }], next_before_id: null },
  ]) {
    t.handler(() => ({ api_version: 2, ...response }));
    await assert.rejects(t.engine.receipts(undefined, 101), error => ['invalid_response', 'invalid_payload'].includes(error.code));
  }
  t.handler(() => ({ api_version: 2, orders: [receiptSummary(2)], next_before_id: null }));
  await assert.rejects(t.engine.receipts(1), code('invalid_response'));
  for (const version of [undefined, 0, 2]) {
    t.handler(() => options({ receipt_list_version: version })); await t.engine.options();
    const before = t.calls.length;
    await assert.rejects(t.engine.receipts(), code('server_update_required'));
    assert.equal(t.calls.length, before, 'unsupported global scope never sends HTTP or returns false empty');
    t.handler(() => ({ api_version: 2, orders: [receiptSummary()], next_before_id: null }));
    await t.engine.receipts(1);
    assert.deepEqual(t.calls.at(-1).query, { company_id: 1 }, 'legacy single-company queue remains compatible');
  }
});

test('global receipt completion cannot cross permission, actor, company or capability revalidation', async () => {
  for (const change of [i => ({ ...i, uid: 8 }), i => ({ ...i, verified: false }), i => ({ ...i, companyIds: [1] }), i => ({ ...i, permissions: { ...i.permissions, order_receive: false } })]) {
    const t = await setup(), wait = deferred(); t.handler(() => wait.promise);
    const pending = t.engine.receipts(); t.identity = change(t.identity);
    wait.resolve({ api_version: 2, orders: [receiptSummary(2)], next_before_id: null });
    await assert.rejects(pending, error => ['stale', 'forbidden'].includes(error.code));
  }
  const t = await setup(), wait = deferred(); t.handler(() => wait.promise);
  const pending = t.engine.receipts();
  t.handler(() => options({ receipt_list_version: 0 })); await t.engine.options();
  wait.resolve({ api_version: 2, orders: [], next_before_id: null });
  await assert.rejects(pending, code('server_update_required'));
  t.identity.permissions.order_receive = false;
  const before = t.calls.length; await assert.rejects(t.engine.receipts(), code('forbidden'));
  assert.equal(t.calls.length, before);
});
test('viewer and receiver permissions are independent from create and chat_send', async () => {
  const t = await setup(); t.identity.permissions.order_create = false; t.identity.permissions.chat_send = false;
  await t.engine.options(); await t.engine.receipts(1); assert.equal(t.calls.length, 2);
  await assert.rejects(t.engine.options(1), code('forbidden'));
  await assert.rejects(t.engine.catalog(1), code('forbidden'));
  await assert.rejects(t.engine.create(createInput()), code('forbidden'));
  await t.engine.confirm(100, confirmInput(), [77, 78]);
  await assert.rejects(t.engine.share(1, 100), code('forbidden'));
});
test('unverified identities, company revocation and malformed IDs make zero calls', async () => {
  const t = await setup(); t.identity.verified = false;
  await assert.rejects(t.engine.list(), code('unauthorized'));
  t.identity.verified = true; t.identity.companyIds = [2];
  await assert.rejects(t.engine.receipts(1), code('forbidden'));
  await assert.rejects(t.engine.list(2147483648), code('invalid_payload'));
  await assert.rejects(t.engine.list(0), code('invalid_payload'));
  assert.equal(t.calls.length, 0);
});
test('old account, epoch, company or rights responses cannot reach the UI', async () => {
  for (const change of [i => ({ ...i, uid: 8 }), i => ({ ...i, epoch: 'reset2' }), i => ({ ...i, companyIds: [1] }), i => ({ ...i, permissions: { ...i.permissions, order_view: false } })]) {
    const t = await setup(); const wait = deferred(); t.handler(() => wait.promise);
    const result = t.engine.list(); t.identity = change(t.identity);
    wait.resolve({ api_version: 2, orders: [], next_before_id: null });
    await assert.rejects(result, error => ['stale', 'forbidden'].includes(error.code));
  }
});
test('a late authentication failure never invokes callbacks for a newer account', async () => {
  const t = await setup(); const wait = deferred(); t.handler(() => wait.promise);
  const result = t.engine.list(); t.identity = { ...t.identity, epoch: 2, uid: 8 };
  wait.reject({ status: 401 }); await assert.rejects(result, code('stale'));
  assert.deepEqual(t.callbacks(), { unauthorized: 0, forbidden: 0 });
});
test('403 blocks further calls until explicit fresh options verification; rights never elevate', async () => {
  const t = await setup(); t.handler(() => { throw { status: 403 }; });
  await assert.rejects(t.engine.list()); await assert.rejects(t.engine.list(), code('forbidden'));
  assert.equal(t.calls.length, 1); assert.equal(t.callbacks().forbidden, 1);
  t.handler(() => options({ can_receive: false })); await t.engine.options();
  await assert.rejects(t.engine.receipts(1), code('forbidden'));
  t.handler(() => ({ api_version: 2, orders: [], next_before_id: null })); await t.engine.list();
});
test('strict decimal/cart/receipt boundaries match the server and require every receipt line', async () => {
  for (const raw of [1, '1e2', '01', '-1', '1.001', '1000000', '0.00', '١', ' 1']) assert.throws(() => validateCreateInput(createInput(raw)));
  validateCreateInput(createInput('999999.99'));
  assert.throws(() => validateCreateInput({ ...createInput(), lines: [createInput().lines[0], createInput().lines[0]] }));
  assert.throws(() => validateCreateInput({ ...createInput(), lines: Array.from({ length: 101 }, (_, i) => ({ option_id: i + 1, quantity: '1' })) }));
  const maximum = { ...createInput(), lines: Array.from({ length: 100 }, (_, i) => ({ option_id: i + 1, quantity: '1' })) }; validateCreateInput(maximum);
  validateConfirmInput(confirmInput(), [77, 78]);
  assert.throws(() => validateConfirmInput(confirmInput(), [77]));
  assert.throws(() => validateConfirmInput({ company_id: 1, lines: [{ line_id: 77, actual_qty: '0', actual_price: '1' }] }, [77]));
  assert.throws(() => validateConfirmInput({ company_id: 1, lines: [{ line_id: 77, actual_qty: '1', actual_price: '0' }] }, [77]));
  assert.throws(() => validateConfirmInput({ company_id: 1, lines: [{ line_id: 77, actual_qty: '0', actual_price: '0' }] }, [77]));
  validateConfirmInput({ company_id: 1, lines: [{ line_id: 77, actual_qty: '999999.99', actual_price: '999999999.99' }] }, [77]);
});
test('quote echoes server amounts, binds exact cart revision and invalidates after cart edit', async () => {
  const t = await setup(); const wait = deferred(); t.handler(() => wait.promise);
  const input = { company_id: 1, warehouse_id: 3, cart_revision: 4, lines: [{ option_id: 9, quantity: '1' }] };
  const response = { api_version: 2, company_id: 1, cart_revision: 4, lines: [{ option_id: 9, quantity: '1.00', unit_price: '12.30', line_total: '12.30' }], estimated_total: '12.30', currency_code: 'SAR', currency_symbol: 'SAR', quoted_at: '2026-10-19T00:00:00Z' };
  const result = t.engine.quote(input); t.engine.invalidateQuote(); wait.resolve(response);
  await assert.rejects(result, code('stale'));
  t.handler(() => response); assert.equal((await t.engine.quote(input)).estimated_total, '12.30');
  t.handler(() => ({ ...response, cart_revision: 3 })); await assert.rejects(t.engine.quote(input), code('invalid_response'));
  t.handler(() => ({ ...response, lines: [{ ...response.lines[0], quantity: '2.00' }] })); await assert.rejects(t.engine.quote(input), code('invalid_response'));
});
test('newer reads abort older reads and old responses stay stale', async () => {
  const t = await setup(); const wait = deferred(); let first = true;
  t.handler(() => { if (first) { first = false; return wait.promise; } return { api_version: 2, orders: [], next_before_id: null }; });
  const old = t.engine.list(); await t.engine.list(); assert.equal(t.calls[0].signal.aborted, true);
  wait.resolve({ api_version: 2, orders: [], next_before_id: null }); await assert.rejects(old, code('stale'));
});
test('catalog and share use exactly one explicit POST, no invented UUID and no replay', async () => {
  const t = await setup(); await t.engine.catalog(1, { q: 'مواد', categoryId: 4, afterId: 2 }); await t.engine.share(1, 100);
  assert.equal(t.calls.length, 2); assert.deepEqual(t.calls[0].payload, { api_version: 2 });
  assert.deepEqual(t.calls[1].payload, { api_version: 2, company_id: 1 }); assert.equal(t.writes, 0);
  t.handler(() => { throw new Error('lost'); }); await assert.rejects(t.engine.share(1, 100));
  await assert.rejects(t.engine.catalog(1)); assert.equal(t.calls.length, 4); assert.equal((await t.engine.pending()).length, 0);
});
test('catalog/product cursor and list cursor are validated at boundaries', async () => {
  const t = await setup(); t.handler(() => ({ api_version: 2, items: [], next_after_id: 9 }));
  await assert.rejects(t.engine.catalog(1), code('invalid_response'));
  t.handler(() => ({ api_version: 2, orders: [summary(1, 100)], next_before_id: 99 }));
  await assert.rejects(t.engine.list(), code('invalid_response'));
  t.handler(() => ({ api_version: 2, orders: [summary(1, 100)], next_before_id: null }));
  await assert.rejects(t.engine.list(100), code('invalid_response'));
});
test('intent storage ACK precedes POST and success ACK is durable before success returns', async () => {
  const t = await setup(); t.handler(request => {
    assert.equal(t.writes, 1); const journal = JSON.parse([...t.data.values()][0]);
    assert.equal(journal.attempts[0].uuid, request.payload.client_uuid); assert.equal(journal.attempts[0].status, 'unknown');
    return { api_version: 2, client_uuid: request.payload.client_uuid, replayed: false, order: summary() };
  });
  const result = await t.engine.create(createInput()); assert.equal(result.order.requested_total, '12.30');
  const stored = JSON.parse([...t.data.values()][0]); assert.equal(stored.attempts[0].status, 'ack');
  assert.deepEqual(stored.attempts[0].result, result); assert.equal(t.writes, 2); assert.deepEqual(await t.engine.pending(), []);
});
test('failure to persist intent or storage readback ACK prevents any POST', async () => {
  const t = await setup(); t.storageFail(() => true);
  await assert.rejects(t.engine.create(createInput()), code('storage')); assert.equal(t.calls.length, 0);
  const other = await setup(); other.deps.storage.setItem = async () => {};
  await assert.rejects(other.engine.create(createInput()), code('storage')); assert.equal(other.calls.length, 0);
});
test('lost reply retries original payload/UUID only and blocks accidental duplicate creation', async () => {
  const t = await setup(); t.handler(() => { throw new Error('reply lost after commit'); });
  await assert.rejects(t.engine.create(createInput()), code('unknown'));
  const pending = await t.engine.pending(); const original = t.calls[0].payload;
  await assert.rejects(t.engine.create(createInput()), error => error.code === 'unknown' && error.attemptId === pending[0].uuid);
  assert.equal(t.calls.length, 1);
  t.handler(request => ({ api_version: 2, order: summary(), client_uuid: request.payload.client_uuid, replayed: true }));
  const result = await t.engine.retry(pending[0].uuid); assert.equal(result.replayed, true);
  assert.deepEqual(t.calls[1].payload, original); assert.equal((await t.engine.pending()).length, 0);
});
test('ACK write failure retains unknown original intent and retry restores durable success', async () => {
  const t = await setup(); t.storageFail(n => n === 2);
  await assert.rejects(t.engine.create(createInput()), code('unknown'));
  const pending = await t.engine.pending(); assert.equal(pending.length, 1);
  assert.equal(JSON.parse([...t.data.values()][0]).attempts[0].status, 'unknown');
  await t.engine.retry(pending[0].uuid); assert.deepEqual(t.calls[0].payload, t.calls[1].payload);
});
test('journal survives logout but is inaccessible to another origin, DB, user, company or rights', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); }); await assert.rejects(t.engine.create(createInput()));
  const saved = JSON.stringify([...t.data]); const original = structuredClone(t.identity);
  t.identity = null; await assert.rejects(t.engine.pending(), code('unauthorized'));
  for (const change of [{ uid: 8 }, { db: 'other' }, { origin: 'https://other.test' }]) {
    t.identity = { ...original, ...change }; assert.deepEqual(await t.engine.pending(), []);
  }
  t.identity = { ...original, companyIds: [2] }; assert.deepEqual(await t.engine.pending(), []);
  t.identity = { ...original, permissions: { ...original.permissions, order_create: false } }; assert.deepEqual(await t.engine.pending(), []);
  t.identity = { ...original, epoch: 90, verified: false }; await assert.rejects(t.engine.pending(), code('unauthorized'));
  t.identity = { ...original, epoch: 91 }; assert.equal((await t.engine.pending()).length, 1);
  assert.equal(JSON.stringify([...t.data]), saved); assert.equal(t.calls.length, 1);
});
test('a stale successful POST cannot emit UI success and still retains original UUID', async () => {
  const t = await setup(); const wait = deferred(); t.handler(request => { t.identity = { ...t.identity, epoch: 2 }; return wait.promise; });
  const result = t.engine.create(createInput());
  // Wait until durable intent storage and POST have begun.
  while (!t.calls.length) await new Promise(resolve => setImmediate(resolve));
  wait.resolve({ api_version: 2, order: summary(), client_uuid: t.calls[0].payload.client_uuid, replayed: false });
  await assert.rejects(result, code('unknown')); assert.equal((await t.engine.pending()).length, 1);
});
test('pending journal blocks the 21st intent without evicting any of the first 20', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); });
  for (let n = 1; n <= 20; n += 1) await assert.rejects(t.engine.create(createInput(String(n))), code('unknown'));
  const stored = JSON.stringify([...t.data]); await assert.rejects(t.engine.create(createInput('21')), code('storage_full'));
  assert.equal(t.calls.length, 20); assert.equal((await t.engine.pending()).length, 20); assert.equal(JSON.stringify([...t.data]), stored);
});
test('oversized or malformed durable storage blocks new writes without deleting evidence', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); }); await assert.rejects(t.engine.create(createInput()));
  const key = [...t.data.keys()][0]; const raw = t.data.get(key); const oversized = `${raw}${' '.repeat(1048576)}`;
  t.data.set(key, oversized); assert.ok(bytes(oversized) > 1048576);
  await assert.rejects(t.engine.create(createInput('2')), code('storage_corrupt')); assert.equal(t.data.get(key), oversized); assert.equal(t.calls.length, 1);
});
test('confirm replays all original actual lines and keeps share a separate operation', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); });
  await assert.rejects(t.engine.confirm(100, confirmInput(), [77, 78]), code('unknown'));
  const token = (await t.engine.pending())[0].uuid;
  t.handler(request => ({ api_version: 2, client_uuid: request.payload.client_uuid, replayed: true, receipt: { order_id: 100, name: 'PR100', state: 'purchased', company_id: 1, actual_total: '12.30', currency_symbol: 'SAR', picking_id: 22, confirmed_at: null, confirmed_by_id: 7 } }));
  const result = await t.engine.retry(token); assert.equal(result.receipt.actual_total, '12.30'); assert.deepEqual(t.calls[0].payload, t.calls[1].payload);
  assert.equal(t.calls.filter(call => call.path.endsWith('/share')).length, 0);
  t.handler(() => { throw new Error('lost share'); }); await assert.rejects(t.engine.share(1, 100)); assert.equal((await t.engine.pending()).length, 0);
});
test('invalid success ACK UUID/company cannot resolve an attempt', async () => {
  const t = await setup(); t.handler(request => ({ api_version: 2, order: summary(2), client_uuid: request.payload.client_uuid, replayed: false }));
  await assert.rejects(t.engine.create(createInput()), code('unknown')); assert.equal((await t.engine.pending()).length, 1);
});
test('equivalent reordered inputs cannot bypass an existing unknown UUID', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); });
  const first = { company_id: 1, warehouse_id: 3, representative_partner_id: null, lines: [{ option_id: 9, quantity: '1' }, { option_id: 8, quantity: '2' }] };
  await assert.rejects(t.engine.create(first), code('unknown'));
  await assert.rejects(t.engine.create({ lines: [{ option_id: 8, quantity: '2.00' }, { option_id: 9, quantity: '1.0' }], representative_partner_id: null, warehouse_id: 3, company_id: 1, purchase_route: 'representative' }), code('unknown'));
  assert.equal(t.calls.length, 1); assert.equal((await t.engine.pending()).length, 1);
});
test('restoration lists durable attempts without automatic POST and concurrent retry sends once', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); }); await assert.rejects(t.engine.create(createInput()));
  const restored = new OrdersEngine(t.deps); const pending = await restored.pending(); assert.equal(t.calls.length, 1);
  const wait = deferred(); t.handler(() => wait.promise); const retry = restored.retry(pending[0].uuid);
  while (t.calls.length < 2) await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(restored.retry(pending[0].uuid), code('unknown')); assert.equal(t.calls.length, 2);
  wait.resolve({ api_version: 2, order: summary(), client_uuid: pending[0].uuid, replayed: true }); await retry;
  assert.deepEqual(await restored.pending(), []);
});
test('public read continuations recheck their original actor after transport already checked it', async () => {
  const cases = [
    ['options', t => t.engine.options(), () => options()],
    ['catalog', t => t.engine.catalog(1), () => ({ api_version: 2, items: [], next_after_id: null })],
    ['list', t => t.engine.list(), () => ({ api_version: 2, orders: [summary()], next_before_id: null })],
    ['detail', t => t.engine.detail(1, 100), () => ({ api_version: 2, order: { ...summary(), name: 'OLD_DB_PRIVATE', warehouse_id: 3 }, lines: [] })],
    ['receipts', t => t.engine.receipts(1), () => ({ api_version: 2, orders: [receiptSummary()], next_before_id: null })],
    ['receiptDetail', t => t.engine.receiptDetail(1, 100), () => ({ api_version: 2, order: receiptSummary(), lines: [{ line_id: 77, product_name: 'Old DB product', option_name: 'Box', uom_name: 'Box', requested_qty: '1.00', manager_received_qty: '0.00' }] })],
    ['quote', t => t.engine.quote({ company_id: 1, warehouse_id: 3, cart_revision: 1, lines: [{ option_id: 9, quantity: '1' }] }), () => ({ api_version: 2, company_id: 1, cart_revision: 1, lines: [{ option_id: 9, quantity: '1.00', unit_price: '12.30', line_total: '12.30' }], estimated_total: '12.30', currency_code: 'SAR', currency_symbol: 'SAR', quoted_at: '2026-10-19T00:00:00Z' })],
  ];
  for (const [name, operation, response] of cases) {
    const t = await setup(); t.handler(async () => response());
    const result = operation(t);
    // First request guard passes; switch actor before the outer public method resumes.
    queueMicrotask(() => queueMicrotask(() => { t.identity = { ...t.identity, db: 'new-db', uid: 8, epoch: 2 }; }));
    await assert.rejects(result, code('stale'), name);
  }
  const share = await setup(); share.handler(async () => ({ api_version: 2, order_id: 100, room_id: 8, message_id: 99, shared: true, replayed: false }));
  const result = share.engine.share(1, 100);
  queueMicrotask(() => { share.identity = { ...share.identity, db: 'new-db', uid: 8, epoch: 2 }; });
  await assert.rejects(result, code('stale'), 'share');
});
test('stale options cannot clear a newer actor server verification or permissions', async () => {
  const t = await setup(); const older = structuredClone(t.identity); const newer = { ...older, db: 'new-db', uid: 8, epoch: 2 };
  t.identity = newer; t.handler(async () => options({ can_receive: false })); await t.engine.options();
  t.identity = older; t.handler(async () => options()); const stale = t.engine.options();
  queueMicrotask(() => queueMicrotask(() => { t.identity = newer; }));
  await assert.rejects(stale, code('stale'));
  const callCount = t.calls.length;
  await assert.rejects(t.engine.receipts(1), code('forbidden')); assert.equal(t.calls.length, callCount);
});

test('workflow verification fences new writes and scoped reads on legacy or unsupported servers', async () => {
  for (const workflow_version of [undefined, 0, 2]) {
    const t = await setup(); t.handler(() => options({ workflow_version })); await t.engine.options(); t.calls.length = 0;
    await assert.rejects(t.engine.create(createInput()), code('server_update_required'));
    await assert.rejects(t.engine.list(undefined, 1), code('server_update_required'));
    await assert.rejects(t.engine.rooms(1), code('server_update_required'));
    await assert.rejects(t.engine.shareOrder(1, 100, 8), code('server_update_required'));
    assert.equal(t.calls.length, 0); assert.equal(t.writes, 0); assert.equal(t.data.size, 0);
  }
  const t = await setup(); const fresh = new OrdersEngine(t.deps);
  await assert.rejects(fresh.create(createInput()), code('server_update_required'));
  assert.equal(t.calls.length, 0);
});

test('a legacy unknown attempt still retries exact original bytes without a workflow flag or room injection', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); });
  await assert.rejects(t.engine.create(createInput()), code('unknown'));
  const original = JSON.stringify(t.calls[0].payload); const token = (await t.engine.pending())[0].uuid;
  t.handler(() => options({ workflow_version: undefined })); await t.engine.options();
  t.handler(request => ({ api_version: 2, order: summary(), client_uuid: request.payload.client_uuid, replayed: true }));
  assert.equal((await t.engine.retry(token)).replayed, true);
  assert.equal(JSON.stringify(t.calls.at(-1).payload), original);
  assert.equal('room_id' in t.calls.at(-1).payload, false);
});

test('company-scoped orders use server filtering and reject other-company rows and invalid cursors', async () => {
  const t = await setup(); t.handler(() => ({ api_version: 2, orders: [summary(2)], next_before_id: 100 }));
  await t.engine.list(101, 2); assert.deepEqual(t.calls[0].query, { scope: 'all', before_id: 101, company_id: 2 });
  await assert.rejects(t.engine.list(undefined, 1), code('invalid_response'));
  await assert.rejects(t.engine.list(100, 2), code('invalid_response'));
});

test('an in-flight company page cannot pass after workflow support is withdrawn', async () => {
  const t = await setup(); const wait = deferred();
  t.handler(request => request.path.endsWith('/options') ? options({ workflow_version: 2 }) : wait.promise);
  const page = t.engine.list(undefined, 1); await t.engine.options();
  wait.resolve({ api_version: 2, orders: [summary()], next_before_id: null });
  await assert.rejects(page, code('server_update_required'));
});

const roomsPage = (extras = {}) => ({ api_version: 2, company_id: 1, rooms: [{ id: 8, name: 'Purchases' }], next_after_id: null, preferred_room: null, ...extras });
test('room discovery validates pagination, preferred binding, response size and company isolation', async () => {
  const t = await setup(); t.handler(() => roomsPage({ rooms: Array.from({ length: 50 }, (_, n) => ({ id: n + 1, name: `Room ${n}` })), next_after_id: 50, preferred_room: { id: 90, name: 'Default outside page' } }));
  const page = await t.engine.rooms(1, { q: 'Purchases', preferredRoomId: 90 });
  assert.equal(page.rooms.length, 50); assert.equal(page.preferred_room.id, 90);
  assert.deepEqual(t.calls[0].query, { company_id: 1, q: 'Purchases', preferred_room_id: 90 });
  t.handler(() => roomsPage({ rooms: [{ id: 51, name: 'Page two' }] })); await t.engine.rooms(1, { afterId: 50 });
  for (const extras of [
    { company_id: 2 }, { rooms: [{ id: 8, name: 'A' }, { id: 8, name: 'B' }] },
    { preferred_room: { id: 9, name: 'Wrong' } }, { next_after_id: 7 },
    { rooms: Array.from({ length: 51 }, (_, n) => ({ id: n + 1, name: 'Room' })) },
    { padding: 'x'.repeat(65536) },
  ]) { t.handler(() => roomsPage(extras)); await assert.rejects(t.engine.rooms(1), error => ['invalid_response', 'invalid_payload'].includes(error.code)); }
  const count = t.calls.length;
  for (const query of [{ q: 'ع'.repeat(129) }, { afterId: 0 }, { preferredRoomId: 2147483648 }]) await assert.rejects(t.engine.rooms(1, query), code('invalid_payload'));
  assert.equal(t.calls.length, count);
  t.identity.permissions.chat_send = false; await assert.rejects(t.engine.rooms(1), code('forbidden'));
});

test('conversation default stores IDs only, isolates actor/company, and revalidates eligibility before saving', async () => {
  const t = await setup(); t.handler(request => roomsPage({ company_id: request.query.company_id, preferred_room: { id: request.query.preferred_room_id, name: 'Private room name' } }));
  await t.engine.saveRoom(1, 8); assert.equal(await t.engine.savedRoom(1), 8); assert.equal(await t.engine.savedRoom(2), null);
  const original = structuredClone(t.identity); const stored = JSON.stringify([...t.data]);
  assert.equal(stored.includes('Private room name'), false); assert.equal(stored.includes('journal'), false);
  for (const patch of [{ uid: 9 }, { db: 'other' }, { origin: 'https://other.test' }]) {
    t.identity = { ...original, ...patch }; t.handler(() => options()); await t.engine.options();
    assert.equal(await t.engine.savedRoom(1), null);
  }
  t.identity = original; t.handler(() => options()); await t.engine.options();
  t.handler(() => roomsPage()); await assert.rejects(t.engine.saveRoom(1, 9), code('room_unavailable'));
  assert.equal(JSON.stringify([...t.data]), stored);
  await t.engine.saveRoom(1, null); assert.equal(await t.engine.savedRoom(1), null);
  assert.equal((await t.engine.pending()).length, 0);
});

test('corrupt preference and storage failure never damage the durable write journal', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); }); await assert.rejects(t.engine.create(createInput()));
  const journal = [...t.data.entries()][0];
  await t.engine.saveRoom(1, null); const prefKey = [...t.data.keys()].find(key => key.includes('.room.'));
  t.data.set(prefKey, '{broken'); await assert.rejects(t.engine.savedRoom(1), code('preference_corrupt'));
  assert.equal(t.data.get(prefKey), '{broken'); assert.equal(t.data.get(journal[0]), journal[1]);
  t.storageFail(() => true); await assert.rejects(t.engine.saveRoom(1, null), code('storage'));
  assert.equal((await t.engine.pending()).length, 1);
});

test('post-create share is one explicit bounded operation, guards double taps, validates ACK and never creates an order', async () => {
  const t = await setup(); const wait = deferred(); t.handler(() => wait.promise);
  const result = t.engine.shareOrder(1, 100, 8);
  await assert.rejects(t.engine.shareOrder(1, 100, 9), code('busy'));
  assert.equal(t.calls.length, 1); assert.deepEqual(t.calls[0].payload, { api_version: 2, company_id: 1, room_id: 8 });
  assert.equal(t.calls[0].path, '/bchat/api/v2/orders/100/share'); assert.equal(t.writes, 0);
  wait.resolve({ api_version: 2, order_id: 100, room_id: 8, message_id: 99, shared: true, replayed: false }); await result;
  for (const patch of [{ order_id: 101 }, { room_id: 9 }]) {
    t.handler(() => ({ api_version: 2, order_id: 100, room_id: 8, message_id: 99, shared: true, replayed: false, ...patch }));
    await assert.rejects(t.engine.shareOrder(1, 100, 8), code('invalid_response'));
  }
  t.handler(() => { throw new Error('reply lost'); }); await assert.rejects(t.engine.shareOrder(1, 100, 8));
  assert.equal(t.calls.length, 4); assert.equal((await t.engine.pending()).length, 0);
});

test('new room/default/share continuations cannot leak to another actor or mutate another actor preference', async () => {
  for (const operation of [t => t.engine.rooms(1), t => t.engine.shareOrder(1, 100, 8), t => t.engine.saveRoom(1, 8)]) {
    const t = await setup(); const wait = deferred(); t.handler(() => wait.promise);
    const result = operation(t); t.identity = { ...t.identity, uid: 8, epoch: 2 };
    wait.resolve(roomsPage({ preferred_room: { id: 8, name: 'Old private room' } }));
    await assert.rejects(result, code('stale')); assert.equal(t.writes, 0);
  }
  const t = await setup(); const result = t.engine.savedRoom(1); t.identity = { ...t.identity, epoch: 2 };
  await assert.rejects(result, code('stale'));
});

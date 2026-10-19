// @ts-nocheck -- native transport facade remains executable without a device.
import test from 'node:test';
import assert from 'node:assert/strict';
import { ordersNativeRequest } from './transport.ts';
const base = '/bchat/api/v2/orders';
const code = expected => error => error.code === expected;

test('transport allowlist maps all actual order read endpoints and preserves abort signal', () => {
  const signal = new AbortController().signal;
  for (const [path, query] of [[`${base}/options`, {}], [`${base}/options`, { company_id: 1 }], [base, { scope: 'all', before_id: 80 }], [base, { scope: 'all', company_id: 2 }], [`${base}/rooms`, { company_id: 2, after_id: 50, preferred_room_id: 90 }], [`${base}/91`, { company_id: 2, scope: 'all' }], [`${base}/receipts`, { company_id: 2, before_id: 100 }], [`${base}/receipts/91`, { company_id: 2 }]]) {
    const output = ordersNativeRequest({ method: 'GET', path, query, signal }, '');
    const suffix = Object.entries(query).map(([key, value]) => `${key}=${value}`).join('&');
    assert.equal(output.path, `${path}${suffix ? `?${suffix}` : ''}`); assert.equal(output.method, 'GET');
    assert.equal(output.signal, signal); assert.equal(output.form, undefined); assert.equal(output.json, undefined);
  }
});
test('transport maps explicit POSTs to only csrf_token plus exact serialized payload', () => {
  const csrf = 'csrf-actual';
  for (const path of [base, `${base}/quote`, `${base}/91/share`, `${base}/receipts/91/confirm`, `${base}/receipts/91/share`, `${base}/catalog`]) {
    const payload = { api_version: 2, company_id: 2, lines: [{ option_id: 9, quantity: '1.00' }] };
    const output = ordersNativeRequest({ method: 'POST', path, ...(path.endsWith('/catalog') ? { query: { company_id: 2 } } : {}), payload }, csrf);
    assert.deepEqual(output.form, { csrf_token: csrf, payload: JSON.stringify(payload) }); assert.equal(output.json, undefined);
    assert.equal(output.method, 'POST'); assert.deepEqual(payload.lines, [{ option_id: 9, quantity: '1.00' }]);
  }
});
test('transport query encoding prevents search text from creating a second query field', () => {
  const query = { company_id: 1, q: 'قهوة &company_id=2? #', category_id: 3, after_id: 12 };
  const output = ordersNativeRequest({ method: 'POST', path: `${base}/catalog`, query, payload: { api_version: 2 } }, 'csrf');
  const parsed = new URL(output.path, 'https://example.test'); assert.equal(parsed.searchParams.get('q'), query.q);
  assert.deepEqual(parsed.searchParams.getAll('company_id'), ['1']); assert.equal(parsed.hash, '');
});
test('transport rejects foreign paths, unsupported methods, embedded query, suffixes and oversized path IDs', () => {
  for (const path of ['/web/dataset/call_kw', 'https://other.test/bchat/api/v2/orders', `${base}/../rooms`, `${base}/options?company_id=2`, `${base}/options#fragment`, `${base}/1/`, `${base}/receipts/1/delete`, `${base}/0`, `${base}/01`, `${base}/2147483648`, `${base}/receipts/2147483648`, null, {}, 1]) assert.throws(() => ordersNativeRequest({ method: 'GET', path }, 'csrf'), code('invalid_path'));
  for (const method of ['PUT', 'DELETE', 'PATCH', 'get', 'post']) assert.throws(() => ordersNativeRequest({ method, path: base }, 'csrf'), code('invalid_path'));
  assert.throws(() => ordersNativeRequest({ method: 'GET', path: `${base}/quote` }, 'csrf'), code('invalid_path'));
  assert.throws(() => ordersNativeRequest({ method: 'POST', path: `${base}/options`, payload: { api_version: 2 } }, 'csrf'), code('invalid_path'));
  assert.throws(() => ordersNativeRequest({ method: 'POST', path: `${base}/receipts/2147483648/confirm`, payload: { api_version: 2 } }, 'csrf'), code('invalid_path'));
});
test('transport enforces required company/scopes and rejects unknown or conflicting query fields', () => {
  for (const [method, path] of [['GET', base], ['GET', `${base}/91`], ['GET', `${base}/receipts`], ['GET', `${base}/receipts/91`], ['POST', `${base}/catalog`]]) assert.throws(() => ordersNativeRequest({ method, path, payload: method === 'POST' ? { api_version: 2 } : undefined }, 'csrf'), code('invalid_payload'));
  for (const query of [{ scope: 'all', company_id: 0 }, { scope: 'mine' }, { scope: 'all', limit: 500 }, { scope: ['all'] }, { scope: 'all', before_id: [1, 2] }]) assert.throws(() => ordersNativeRequest({ method: 'GET', path: base, query }, ''), code('invalid_payload'));
  assert.throws(() => ordersNativeRequest({ method: 'POST', path: base, query: { company_id: 1 }, payload: { api_version: 2 } }, 'csrf'), code('invalid_payload'));
  assert.throws(() => ordersNativeRequest({ method: 'GET', path: `${base}/options`, query: [] }, ''), code('invalid_payload'));
});

test('receipt list scope is explicitly all or a legacy company, while details always require company', () => {
  for (const query of [{ scope: 'all' }, { scope: 'all', before_id: 100 }, { company_id: 2 }, { scope: 'all', company_id: 2 }]) {
    assert.ok(ordersNativeRequest({ method: 'GET', path: `${base}/receipts`, query }, '').path.includes('/receipts?'));
  }
  for (const query of [{}, { before_id: 100 }, { scope: 'mine' }, { scope: 'all', company_id: 0 }, { scope: 'all', before_id: [1] }]) {
    assert.throws(() => ordersNativeRequest({ method: 'GET', path: `${base}/receipts`, query }, ''), code('invalid_payload'));
  }
  assert.throws(() => ordersNativeRequest({ method: 'GET', path: `${base}/receipts/91`, query: { scope: 'all' } }, ''), code('invalid_payload'));
});
test('query IDs accept only the server positive int32 syntax and catalog search has a UTF8 byte bound', () => {
  for (const company_id of [0, -1, 1.5, 2147483648, true, null, '01', '1.0', '1e2', '+1', '١']) assert.throws(() => ordersNativeRequest({ method: 'GET', path: `${base}/options`, query: { company_id } }, ''), code('invalid_payload'));
  for (const company_id of [1, 2147483647, '1', '2147483647']) assert.ok(ordersNativeRequest({ method: 'GET', path: `${base}/options`, query: { company_id } }, '').path.includes(`company_id=${company_id}`));
  const request = q => ({ method: 'POST', path: `${base}/catalog`, query: { company_id: 1, q }, payload: { api_version: 2 } });
  ordersNativeRequest(request('أ'.repeat(128)), 'csrf'); ordersNativeRequest(request('a'.repeat(256)), 'csrf');
  for (const q of ['أ'.repeat(129), 'a'.repeat(257), 1, null, ['x']]) assert.throws(() => ordersNativeRequest(request(q), 'csrf'), code('invalid_payload'));
});
test('GET rejects payload, POST rejects missing or malformed csrf and invalid API payload', () => {
  assert.throws(() => ordersNativeRequest({ method: 'GET', path: `${base}/options`, payload: {} }, ''), code('invalid_payload'));
  for (const csrf of ['', '  ', null, 1, {}, 'x'.repeat(1025)]) assert.throws(() => ordersNativeRequest({ method: 'POST', path: base, payload: { api_version: 2 } }, csrf), code('unauthorized'));
  for (const payload of [undefined, null, [], '2', {}, { api_version: 1 }, { api_version: '2' }, { api_version: 2, value: 1n }]) assert.throws(() => ordersNativeRequest({ method: 'POST', path: base, payload }, 'csrf'), code('invalid_payload'));
  const cyclic = { api_version: 2 }; cyclic.self = cyclic;
  assert.throws(() => ordersNativeRequest({ method: 'POST', path: base, payload: cyclic }, 'csrf'), code('invalid_payload'));
});
test('POST enforces actual encoded form limit of 64KiB', () => {
  const request = text => ({ method: 'POST', path: base, payload: { api_version: 2, text } });
  const prefix = 'csrf_token=csrf&payload=';
  const baseline = prefix.length + encodeURIComponent(JSON.stringify(request('').payload)).length;
  const atBoundary = request('a'.repeat(65536 - baseline)); assert.ok(ordersNativeRequest(atBoundary, 'csrf').form);
  assert.throws(() => ordersNativeRequest(request('a'.repeat(65537 - baseline)), 'csrf'), code('payload_too_large'));
  assert.throws(() => ordersNativeRequest(request('أ'.repeat(12000)), 'csrf'), code('payload_too_large'));
});

test('room discovery query and new share paths remain narrowly allowlisted', () => {
  for (const query of [{}, { company_id: 1, room_id: 8 }, { company_id: 1, after_id: 0 }, { company_id: 1, preferred_room_id: 2147483648 }, { company_id: 1, q: 'ع'.repeat(129) }]) {
    assert.throws(() => ordersNativeRequest({ method: 'GET', path: `${base}/rooms`, query }, ''), code('invalid_payload'));
  }
  const output = ordersNativeRequest({ method: 'GET', path: `${base}/rooms`, query: { company_id: 1, q: 'A &company_id=2' } }, '');
  assert.deepEqual(new URL(output.path, 'https://example.test').searchParams.getAll('company_id'), ['1']);
  for (const path of [`${base}/0/share`, `${base}/01/share`, `${base}/2147483648/share`]) assert.throws(() => ordersNativeRequest({ method: 'POST', path, payload: { api_version: 2 } }, 'csrf'), code('invalid_path'));
});

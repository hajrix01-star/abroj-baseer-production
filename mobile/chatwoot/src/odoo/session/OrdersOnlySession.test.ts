// @ts-nocheck -- executable pure contract tests, independent of the native runtime.
import test from 'node:test';
import assert from 'node:assert/strict';
import { ordersOnlyBootstrap, OrdersOnlySession } from './OrdersOnlySession.ts';

const bootstrap = (extra = {}) => ({ api_version: 2, user_id: 7, database: 'db', company_ids: [1, 2], csrf_token: 'csrf', permissions: { chat_view: false, chat_send: false, order_view: true, order_create: false, order_receive: true, upload_limit: 12 }, ...extra });
const mismatch = error => error.code === 'identity_mismatch';
const stale = error => error.code === 'stale_session';

test('orders-only validator accepts explicit independent grants and clones only its supported identity', () => {
  const raw = bootstrap({ arbitrary: 'not copied', password: 'not copied' });
  const value = ordersOnlyBootstrap(raw, 7, 'db');
  assert.deepEqual(value, { api_version: 2, user_id: 7, database: 'db', company_ids: [1, 2], csrf_token: 'csrf', permissions: raw.permissions });
  raw.permissions.order_receive = false; raw.company_ids.push(3);
  assert.equal(value.permissions.order_receive, true); assert.deepEqual(value.company_ids, [1, 2]);
});
test('normal chat and absent order grants do not become orders-only sessions', () => {
  for (const raw of [null, [], {}, bootstrap({ permissions: null }), bootstrap({ permissions: [] }), bootstrap({ permissions: { chat_view: true, order_view: true } }), bootstrap({ permissions: { chat_view: false, order_view: false } }), bootstrap({ permissions: { order_view: true } }), bootstrap({ permissions: { chat_view: 0, order_view: true } })]) assert.equal(ordersOnlyBootstrap(raw, 7, 'db'), null);
});
test('orders-only identity rejects malformed uid, API version and database boundaries', () => {
  for (const user_id of [0, -1, 1.5, '7', null, 8, 2147483648]) assert.throws(() => ordersOnlyBootstrap(bootstrap({ user_id }), 7, 'db'), mismatch);
  for (const expected of [0, -1, 1.5, '7', 2147483648]) assert.throws(() => ordersOnlyBootstrap(bootstrap({ user_id: expected }), expected, 'db'), mismatch);
  for (const api_version of [1, '2', true, null]) assert.throws(() => ordersOnlyBootstrap(bootstrap({ api_version }), 7, 'db'), mismatch);
  assert.throws(() => ordersOnlyBootstrap(bootstrap({ database: 'other' }), 7, 'db'), mismatch);
  for (const database of ['', ' ', 'd'.repeat(201), null, 9]) assert.throws(() => ordersOnlyBootstrap(bootstrap({ database }), 7, database), mismatch);
  assert.equal(ordersOnlyBootstrap(bootstrap({ user_id: 2147483647, database: 'd'.repeat(200) }), 2147483647, 'd'.repeat(200)).user_id, 2147483647);
});
test('orders-only companies are bounded positive unique int32 authority', () => {
  for (const company_ids of [null, {}, [], [1, 1], [0], [-1], [1.1], ['1'], [true], [2147483648], Array.from({ length: 1001 }, (_, i) => i + 1)]) assert.throws(() => ordersOnlyBootstrap(bootstrap({ company_ids }), 7, 'db'), mismatch);
  assert.deepEqual(ordersOnlyBootstrap(bootstrap({ company_ids: [2147483647] }), 7, 'db').company_ids, [2147483647]);
});
test('orders-only csrf and permissions require exact safe shapes', () => {
  for (const csrf_token of ['', '  ', null, 7, {}, 'x'.repeat(1025)]) assert.throws(() => ordersOnlyBootstrap(bootstrap({ csrf_token }), 7, 'db'), mismatch);
  assert.equal(ordersOnlyBootstrap(bootstrap({ csrf_token: 'x'.repeat(1024) }), 7, 'db').csrf_token.length, 1024);
  for (const key of ['order_create', 'order_receive', 'chat_send']) {
    for (const bad of [undefined, null, 0, 1, 'true', {}, []]) {
      const raw = bootstrap(); raw.permissions[key] = bad; assert.throws(() => ordersOnlyBootstrap(raw, 7, 'db'), mismatch);
    }
  }
  for (const unknown of ['yes', {}, [], -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    const raw = bootstrap(); raw.permissions.extension = unknown; assert.throws(() => ordersOnlyBootstrap(raw, 7, 'db'), mismatch);
  }
});
test('optional display profile cannot add company authority or retain mutable source values', () => {
  const raw = bootstrap({ profile: { name: 'Owner', companies: [{ id: 1, name: 'One', name_ar: 'أ'.repeat(600), name_en: 'One' }, { id: 3, name: 'Unauthorized' }, { id: 2, name: 9 }, { id: -1, name: 'Bad' }] } });
  const identity = ordersOnlyBootstrap(raw, 7, 'db'); assert.equal(identity.profile.companies.length, 1);
  assert.equal(identity.profile.companies[0].id, 1); assert.equal(identity.profile.companies[0].name_ar.length, 512);
  raw.profile.companies[0].name = 'Changed'; assert.equal(identity.profile.companies[0].name, 'One');
  assert.equal(ordersOnlyBootstrap(bootstrap({ profile: { name: 'x'.repeat(513), companies: [] } }), 7, 'db').profile, undefined);
});
test('generation store publishes isolated snapshots and notifies subscribers once per change', () => {
  const session = new OrdersOnlySession(); let changes = 0; const unsubscribe = session.subscribe(() => changes++);
  assert.deepEqual(session.snapshot(), { identity: null, generation: -1, verified: false, revision: 0 });
  const identity = ordersOnlyBootstrap(bootstrap(), 7, 'db'); session.publish(identity, 2, 2);
  identity.company_ids.push(4); identity.permissions.order_view = false;
  const snapshot = session.snapshot(); assert.equal(snapshot.verified, true); assert.equal(snapshot.generation, 2); assert.equal(snapshot.revision, 1);
  assert.deepEqual(snapshot.identity.company_ids, [1, 2]); snapshot.identity.company_ids.push(5);
  assert.deepEqual(session.snapshot().identity.company_ids, [1, 2]); assert.equal(changes, 1);
  session.lock(); assert.equal(session.snapshot().verified, false); assert.equal(session.snapshot().revision, 2);
  session.lock(); assert.equal(changes, 2); unsubscribe(); session.clear(2); assert.equal(changes, 2);
});
test('stale publish and stale clear cannot replace or remove a newer orders-only identity', () => {
  const session = new OrdersOnlySession(); const identity = ordersOnlyBootstrap(bootstrap(), 7, 'db'); session.publish(identity, 5, 5);
  const original = session.snapshot();
  assert.throws(() => session.publish({ ...identity, user_id: 8 }, 4, 5), stale); assert.deepEqual(session.snapshot(), original);
  assert.equal(session.clear(4), false); assert.deepEqual(session.snapshot(), original);
  assert.throws(() => session.publish({ ...identity, permissions: { ...identity.permissions, chat_view: true } }, 5, 5), stale);
  assert.throws(() => session.publish({ ...identity, permissions: { ...identity.permissions, order_view: false } }, 5, 5), stale);
  session.lock(); assert.equal(session.snapshot().identity.user_id, 7); assert.equal(session.snapshot().verified, false);
  session.publish(identity, 5, 5); assert.equal(session.snapshot().verified, true);
  assert.equal(session.clear(5), true); assert.equal(session.snapshot().identity, null); assert.equal(session.snapshot().verified, false);
});

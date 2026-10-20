import { test } from 'node:test';
import assert from 'node:assert/strict';
import { leadershipNativeRequest } from './transport.ts';
const root = '/bwork/api/v2/leadership';
test('GET facade emits only C1 paths and exact filters without form/body/auth data', () => {
  assert.deepEqual(leadershipNativeRequest({ method: 'GET', path: `${root}/options` }), { method: 'GET', path: `${root}/options`, signal: undefined });
  const result = leadershipNativeRequest({ method: 'GET', path: root, query: { month: '2026-10', period: 'date', date: '2026-10-19', company_id: 2 } });
  assert.equal(result.path, `${root}?month=2026-10&period=date&date=2026-10-19&company_id=2`); assert.equal('form' in result, false);
});
test('GET facade refuses arbitrary paths, methods, unknown keys, bodies and invalid date scope', () => {
  for (const input of [{ method: 'POST', path: root }, { method: 'GET', path: '/bwork/api/v2/users' }, { method: 'GET', path: `${root}?month=2026-10` }, { method: 'GET', path: `${root}/options`, query: { company_id: 1 } }, { method: 'GET', path: root, payload: {} }, { method: 'GET', path: root, query: { month: '2026-10', period: 'month', token: 'unsafe' } }, { method: 'GET', path: root, query: { month: '2026-10', period: 'date', date: '2026-09-30' } }, { method: 'GET', path: root, query: { month: '2026-02', period: 'date', date: '2026-02-30' } }, { method: 'GET', path: root, query: { month: '2026-10', period: 'month', company_id: 0 } }]) assert.throws(() => leadershipNativeRequest(input as any));
});
test('shared calendar range is1900..9998; prior calendar1899 remains a response-only boundary', () => {
  for (const month of ['1900-01', '9998-12']) assert.doesNotThrow(() => leadershipNativeRequest({ method: 'GET', path: root, query: { month, period: 'month' } }));
  for (const month of ['1899-12', '9999-01']) assert.throws(() => leadershipNativeRequest({ method: 'GET', path: root, query: { month, period: 'month' } }));
});

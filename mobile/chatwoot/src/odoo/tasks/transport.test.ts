// @ts-nocheck
import test from 'node:test';
import assert from 'node:assert/strict';
import { tasksNativeRequest } from './transport.ts';
import { createBody } from './tests/fixtures.ts';
const ROOT = '/bchat/api/v2/work-tasks';
const payload = () => ({ api_version: 2, work_tasks_version: 1, ...createBody(), client_uuid: '00000000-0000-4000-8000-000000000001' });
test('strict native facade emits one encoded modern GET and carries AbortSignal', () => {
  const signal = new AbortController().signal;
  const r = tasksNativeRequest({ method: 'GET', path: `${ROOT}/assignees`, query: { company_id: 2, q: 'a & ب', after_id: 7 }, signal }, '');
  assert.equal(r.path, `${ROOT}/assignees?company_id=2&q=a%20%26%20%D8%A8&after_id=7`); assert.equal(r.signal, signal);
  assert.deepEqual(tasksNativeRequest({ method: 'GET', path: ROOT, query: { view: 'mine', state: 'open' } }, ''), { method: 'GET', path: `${ROOT}?view=mine&state=open`, signal: undefined });
});
test('strict native facade rejects legacy/arbitrary paths, queries, IDs and GET payloads', () => {
  for (const request of [
    { method: 'GET', path: '/bchat/api/v2/tasks' }, { method: 'GET', path: `${ROOT}?company_id=1` }, { method: 'GET', path: `${ROOT}/1#x` },
    { method: 'GET', path: `${ROOT}/2147483648`, query: { company_id: 1 } }, { method: 'GET', path: `${ROOT}/0`, query: { company_id: 1 } },
    { method: 'GET', path: `${ROOT}/1` }, { method: 'GET', path: `${ROOT}/options`, query: { company_id: 1 } },
    { method: 'GET', path: ROOT, query: { scope: 'all' } }, { method: 'GET', path: ROOT, query: { company_id: 0 } },
    { method: 'GET', path: ROOT, query: { before_id: '01' } }, { method: 'GET', path: ROOT, query: { state: 'new' } },
    { method: 'GET', path: ROOT, query: { view: 'everyone' } }, { method: 'GET', path: ROOT, payload: {} },
    { method: 'GET', path: `${ROOT}/assignees`, query: { company_id: 1, q: 'ا'.repeat(129) } },
    { method: 'POST', path: `${ROOT}/1` }, { method: 'POST', path: ROOT, query: { company_id: 1 }, payload: payload() },
  ]) assert.throws(() => tasksNativeRequest(request, 'csrf'));
});
test('native POST has exact versioned CSRF form, no arbitrary or legacy fields', () => {
  const body = payload(); const r = tasksNativeRequest({ method: 'POST', path: ROOT, payload: body }, 'csrf');
  assert.deepEqual(r.form, { csrf_token: 'csrf', payload: JSON.stringify(body) }); assert.equal(r.path, ROOT);
  for (const bad of [{ ...body, api_version: 1 }, { ...body, work_tasks_version: 2 }, { ...body, room_id: 2 }, { ...body, other: true }, { ...body, client_uuid: 'bad' }, { ...body, title: 'x'.repeat(161) }]) assert.throws(() => tasksNativeRequest({ method: 'POST', path: ROOT, payload: bad }, 'csrf'));
  for (const csrf of ['', ' ', 'x'.repeat(1025)]) assert.throws(() => tasksNativeRequest({ method: 'POST', path: ROOT, payload: body }, csrf));
});
test('transition wire fields require canonical explicit revision/company/action and bounded reason', () => {
  const body = { api_version: 2, work_tasks_version: 1, company_id: 2, client_uuid: payload().client_uuid, expected_revision: 4, action: 'done', assignee_id: null, reason: 'Fixed' };
  const r = tasksNativeRequest({ method: 'POST', path: `${ROOT}/100/transition`, payload: body }, 'csrf'); assert.equal(JSON.parse(r.form.payload).expected_revision, 4);
  for (const bad of [{ ...body, expected_revision: 0 }, { ...body, assignee_id: 7 }, { ...body, action: 'delete' }, { ...body, reason: 'ا'.repeat(257) }]) assert.throws(() => tasksNativeRequest({ method: 'POST', path: `${ROOT}/100/transition`, payload: bad }, 'csrf'));
});

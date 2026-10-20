// @ts-nocheck -- executable Node contract tests independent of native UI.
import test from 'node:test';
import assert from 'node:assert/strict';
import { TasksEngine } from '../core/TasksEngine.ts';
import { TasksError } from '../core/types.ts';
import { createInput, utc } from '../core/validators.ts';
import { accountKey } from '../core/journal.ts';
import { setup, taskRow, createBody, optionsDTO, detailDTO, writeDTO, deferred, code, NOW } from './fixtures.ts';

test('all-company lists use one global query, separate filter and global cursor', async () => {
  const t = await setup(); const page = await t.engine.list();
  assert.deepEqual(page.tasks.map(t => t.company_id), [2, 1]); assert.equal(t.calls.length, 1);
  assert.deepEqual(t.calls[0].query, { view: 'mine', state: 'open' });
  await t.engine.list({ view: 'created', companyId: 2, beforeId: 101 });
  assert.deepEqual(t.calls[1].query, { view: 'created', state: 'open', company_id: 2, before_id: 101 });
  await assert.rejects(t.engine.list({ companyId: 3 }), code('forbidden'));
  assert.equal(t.calls.length, 2);
});
test('single company default is canonical and a write never uses all-company scope', async () => {
  const t = await setup({ initialize: false }); t.identity.companyIds = [1];
  t.handler(() => optionsDTO({ companies: [{ id: 1, name: 'One' }], default_company_id: 1 }));
  assert.equal((await t.engine.options()).default_company_id, 1);
  await assert.rejects(t.engine.create(createBody({ company_id: 0 })), code('invalid_payload'));
  assert.equal(t.calls.length, 1);
});
test('every read/write needs verified modern options; no legacy fallback', async () => {
  for (const value of [optionsDTO({ work_tasks_version: undefined }), optionsDTO({ work_tasks_version: 2 }), optionsDTO({ capabilities: {} })]) {
    const t = await setup({ initialize: false }); t.handler(() => value);
    await assert.rejects(t.engine.options(), code('server_update_required'));
    const before = t.calls.length; await assert.rejects(t.engine.list(), code('server_update_required')); assert.equal(t.calls.length, before);
  }
  for (const status of [404, 503]) { const t = await setup({ initialize: false }); t.handler(() => { throw { status }; }); await assert.rejects(t.engine.options(), code('server_update_required')); }
});
test('options cannot expand bootstrap companies or fake one-company default', async () => {
  const t = await setup();
  for (const value of [optionsDTO({ companies: [{ id: 3, name: 'Foreign' }] }), optionsDTO({ companies: [{ id: 1, name: 'One' }], default_company_id: null }), optionsDTO({ companies: [{ id: 1, name: 'One' }, { id: 1, name: 'Duplicate' }] })]) {
    t.handler(() => value); await assert.rejects(t.engine.options(), code('invalid_response'));
  }
});
test('task-only permissions work; no-view/view-only cannot mutate or enumerate assignees', async () => {
  const t = await setup(); t.identity.permissions = { task_view: true, task_manage: false };
  t.handler(() => optionsDTO({ can_manage: false })); await t.engine.options();
  t.handler(req => ({ api_version: 2, work_tasks_version: 1, server_now: NOW, view: 'mine', company_id: null, tasks: [taskRow({ allowed_actions: [] })], next_before_id: null }));
  assert.equal((await t.engine.list()).tasks.length, 1);
  const before = t.calls.length; await assert.rejects(t.engine.create(createBody()), code('forbidden')); await assert.rejects(t.engine.assignees(1), code('forbidden'));
  assert.equal(t.calls.length, before); t.identity.permissions.task_view = false; await assert.rejects(t.engine.list(), code('forbidden'));
});
test('all DTO fields, visibility perspective, state, cursor, bytes and order are validated', async () => {
  const t = await setup(); const good = { api_version: 2, work_tasks_version: 1, server_now: NOW, view: 'mine', company_id: null, tasks: [taskRow()], next_before_id: null };
  for (const patch of [
    { tasks: [taskRow({ company_id: 3 })] }, { tasks: [taskRow({ assignee_id: 8, allowed_actions: ['cancel'] })] },
    { tasks: [taskRow({ state: 'done', allowed_actions: [] })] }, { tasks: [taskRow(), taskRow()] }, { tasks: [taskRow({ id: 101 })] },
    { tasks: [taskRow({ description: 'x'.repeat(4097) })] }, { tasks: [taskRow({ created_at: '2026-02-30T00:00:00Z' })] },
    { tasks: [taskRow({ last_actor_id: undefined })] }, { tasks: [taskRow({ allowed_actions: ['delete'] })] },
    { tasks: [taskRow({ creator_id: 9, assignee_id: 7, allowed_actions: ['cancel'] })] }, { next_before_id: 99 }, { next_before_id: 100, tasks: [] },
    { tasks: Array.from({ length: 31 }, (_, i) => taskRow({ id: 100 - i })) }, { unexpected: 'x'.repeat(131072) },
  ]) { t.handler(() => ({ ...good, ...patch })); await assert.rejects(t.engine.list({ beforeId: 101 }), code('invalid_response')); }
  t.handler(() => ({ ...good, tasks: [taskRow({ creator_id: 8, allowed_actions: ['start', 'done'] })], view: 'created' }));
  await assert.rejects(t.engine.list({ view: 'created' }), code('invalid_response'));
});
test('detail binds the row company, not a previous selected company', async () => {
  const t = await setup(); t.handler(() => detailDTO(taskRow({ company_id: 2 })));
  await t.engine.detail(100, 2); assert.deepEqual(t.calls[0].query, { company_id: 2 });
  await assert.rejects(t.engine.detail(100, 1), code('invalid_response'));
  t.handler(() => detailDTO(taskRow({ creator_id: 8, assignee_id: 9, allowed_actions: [] })));
  await assert.rejects(t.engine.detail(100, 1), code('invalid_response'));
});
test('assignees are company scoped, ascending paged and bounded', async () => {
  const t = await setup(); await t.engine.assignees(2, { q: 'أحمد', afterId: 5 });
  assert.deepEqual(t.calls[0].query, { company_id: 2, q: 'أحمد', after_id: 5 });
  const base = { api_version: 2, work_tasks_version: 1, company_id: 2, assignees: [{ id: 7, name: 'One' }], next_after_id: null };
  for (const patch of [{ company_id: 1 }, { assignees: [{ id: 5, name: 'Old' }] }, { next_after_id: 8 }, { assignees: Array.from({ length: 51 }, (_, i) => ({ id: i + 6, name: 'Many' })) }]) {
    t.handler(() => ({ ...base, ...patch })); await assert.rejects(t.engine.assignees(2, { afterId: 5 }), code('invalid_response'));
  }
  await assert.rejects(t.engine.assignees(2, { q: 'ا'.repeat(129) }), code('invalid_payload'));
});
test('reads abort and reject late cancelled/filter/epoch results without write replay', async () => {
  const t = await setup(); const d = deferred(); t.handler(() => d.promise); const first = t.engine.list();
  assert.ok(t.calls[0].signal); t.engine.cancelReads(); assert.equal(t.calls[0].signal.aborted, true);
  d.resolve({ api_version: 2, work_tasks_version: 1, server_now: NOW, view: 'mine', company_id: null, tasks: [], next_before_id: null });
  await assert.rejects(first, code('stale'));
  const e = deferred(); t.handler(() => e.promise); const pending = t.engine.detail(100, 1); t.identity.epoch = 2; e.resolve(detailDTO()); await assert.rejects(pending, code('stale'));
  assert.equal(t.calls.filter(c => c.method === 'POST').length, 0);
});
test('newest read wins even when transport ignores abort', async () => {
  const t = await setup(); const d = deferred(); t.handler(() => d.promise); const first = t.engine.detail(100, 1);
  t.handler(() => detailDTO()); await t.engine.detail(100, 1); d.resolve(detailDTO()); await assert.rejects(first, code('stale'));
});
test('dates/reminders reject invalid Gregorian, offset, excessive input and room creation', () => {
  for (const input of [createBody({ title: ' ' }), createBody({ title: 'a\nline' }), createBody({ description: 'a\u0000line' }), createBody({ description: '\ud800' }), createBody({ title: 'ا'.repeat(81) }), createBody({ room_id: 3 }), createBody({ reminder_at: NOW }), createBody({ due_at: NOW, reminder_at: '2026-10-20T00:00:00Z' }), { ...createBody(), extra: true }]) assert.throws(() => createInput(input));
  for (const value of ['2026-02-30T00:00:00Z', '2026-10-19T12:00:00+00:00', '2026-10-19T12:00:00.000Z']) assert.throws(() => utc(value));
  createInput(createBody({ due_at: NOW, reminder_at: '2026-10-18T00:00:00Z' }));
});
test('create persists intent before HTTP and settles only validated durable ACK', async () => {
  const t = await setup(); t.handler(req => { assert.equal(t.writes, 1); const saved = JSON.parse([...t.data.values()][0]); assert.equal(saved.attempts[0].state, 'unknown'); return writeDTO(req); });
  const result = await t.engine.create(createBody()); assert.equal(result.operation_revision, 1); assert.equal(t.calls.length, 1);
  assert.deepEqual(await t.engine.pending(), []); assert.equal(t.writes, 2);
});
test('create canonicalizes required title once before durable intent and HTTP', async () => {
  const t = await setup(); await t.engine.create(createBody({ title: '  Repair AC  ' }));
  assert.equal(t.calls[0].payload.title, 'Repair AC'); assert.deepEqual(await t.engine.pending(), []);
});
test('storage prepare failure or corruption never sends POST or resets the journal', async () => {
  const t = await setup(); t.failWrite(() => true); await assert.rejects(t.engine.create(createBody()), code('storage_unavailable')); assert.equal(t.calls.length, 0);
  t.failWrite(() => false); const key = `bwork.tasks.journal.v1:${encodeURIComponent(accountKey(t.identity))}`; t.data.set(key, '{broken');
  await assert.rejects(t.engine.create(createBody()), code('storage_corrupt')); await assert.rejects(t.engine.pending(), code('storage_corrupt')); assert.equal(t.data.get(key), '{broken'); assert.equal(t.calls.length, 0);
});
test('lost ACK survives restart; manual retry preserves exact payload and UUID', async () => {
  const t = await setup(); t.handler(() => { throw new Error('timeout'); });
  await assert.rejects(t.engine.create(createBody()), e => e.attemptId && e.code === 'network_error');
  const original = structuredClone(t.calls[0]); const pending = await t.engine.pending(); assert.equal(pending.length, 1);
  const second = new TasksEngine(t.deps); t.handler(req => req.path.endsWith('/options') ? optionsDTO() : writeDTO(req, { replayed: true }));
  await second.options(); assert.equal(t.calls.filter(c => c.method === 'POST').length, 1, 'no startup automatic replay');
  const result = await second.retry(pending[0].uuid); assert.equal(result.replayed, true); assert.deepEqual(t.calls.at(-1).payload, original.payload); assert.deepEqual(await second.pending(), []);
});
test('unknown equivalent create dedupes even reordered keys; unknown transition blocks that task only', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); });
  await assert.rejects(t.engine.create(createBody())); const uuid = (await t.engine.pending())[0].uuid;
  const reordered = Object.fromEntries(Object.entries(createBody()).reverse());
  await assert.rejects(t.engine.create(reordered), e => e.code === 'pending_attempt' && e.attemptId === uuid);
  await assert.rejects(t.engine.transition(taskRow(), { action: 'done' }));
  const before = t.calls.length; await assert.rejects(t.engine.transition(taskRow(), { action: 'start' }), code('pending_attempt')); assert.equal(t.calls.length, before);
  await assert.rejects(t.engine.transition(taskRow({ id: 99 }), { action: 'done' })); assert.equal(t.calls.length, before + 1);
});
test('ACK-store failure retains original immutable unknown intent for same-UUID retry', async () => {
  const t = await setup(); t.failWrite(n => n === 2);
  await assert.rejects(t.engine.create(createBody()), e => e.code === 'storage_unavailable' && !!e.attemptId);
  const pending = await t.engine.pending(); assert.equal(pending.length, 1); const payload = t.calls[0].payload;
  t.failWrite(() => false); await t.engine.retry(pending[0].uuid); assert.deepEqual(t.calls.at(-1).payload, payload); assert.deepEqual(await t.engine.pending(), []);
});
test('401/403/409 after uncertainty never clear or auto retry intent', async () => {
  for (const status of [401, 403, 409]) {
    const t = await setup(); t.handler(() => { throw { status, code: status === 409 ? 'revision_conflict' : undefined }; });
    await assert.rejects(t.engine.create(createBody())); assert.equal((await t.engine.pending()).length, 1); assert.equal(t.calls.length, 1);
    assert.equal(t.callbacks().unauthorized, status === 401 ? 1 : 0); assert.equal(t.callbacks().forbidden, status === 403 ? 1 : 0);
  }
});
test('response UUID/revision/intent mismatch does not ACK an uncertain operation', async () => {
  for (const patch of [{ client_uuid: '00000000-0000-4000-8000-000000000099' }, { operation_revision: 3 }, { task: taskRow({ title: 'Wrong intent' }) }, { task: taskRow({ company_id: 2 }) }]) {
    const t = await setup(); t.handler(req => writeDTO(req, patch)); await assert.rejects(t.engine.create(createBody()), code('invalid_response')); assert.equal((await t.engine.pending()).length, 1);
  }
});
test('transition binds revision/company/action and accepts canonical completion metadata', async () => {
  const t = await setup(); const result = await t.engine.transition(taskRow({ company_id: 2, revision: 4 }), { action: 'done', note: 'Repaired' });
  assert.deepEqual(t.calls[0].payload, { api_version: 2, work_tasks_version: 1, company_id: 2, client_uuid: result.client_uuid, expected_revision: 4, action: 'done', assignee_id: null, reason: 'Repaired' });
  assert.equal(result.task.done_by_id, 7); assert.equal(result.task.done_at, NOW); assert.equal(result.task.completion_note, 'Repaired'); assert.equal(result.operation_revision, 5);
});
test('forged allowed actions never grant another actor role, terminal writes or changed authority', async () => {
  const t = await setup();
  for (const [row, input] of [[taskRow({ creator_id: 8, allowed_actions: ['cancel'] }), { action: 'cancel' }], [taskRow({ assignee_id: 8, allowed_actions: ['done'] }), { action: 'done' }], [taskRow({ state: 'done', allowed_actions: [] }), { action: 'done' }]]) await assert.rejects(t.engine.transition(row, input));
  assert.equal(t.calls.length, 0); t.identity.permissions.task_manage = false; await assert.rejects(t.engine.transition(taskRow(), { action: 'done' }), code('forbidden'));
});
test('old actor late ACK settles original journal only and never notifies or returns to new actor', async () => {
  const t = await setup(); const d = deferred(); let emits = 0; t.engine.subscribe(() => { emits++; }); t.handler(() => d.promise);
  const write = t.engine.create(createBody()); await new Promise(resolve => setTimeout(resolve, 0)); const request = t.calls[0]; assert.equal(emits, 1);
  const old = structuredClone(t.identity); t.identity = { ...old, uid: 8, epoch: 2 }; d.resolve(writeDTO(request));
  await assert.rejects(write, code('stale')); assert.equal(emits, 1); assert.deepEqual(await t.engine.pending(), []);
  t.identity = old; assert.deepEqual(await t.engine.pending(), []);
});
test('same actor new verification epoch cancels render yet may durably settle original ACK', async () => {
  const t = await setup(); const d = deferred(); t.handler(() => d.promise); const write = t.engine.create(createBody());
  await new Promise(resolve => setTimeout(resolve, 0)); const request = t.calls[0]; t.identity = { ...t.identity, epoch: 2 }; d.resolve(writeDTO(request));
  await assert.rejects(write, code('stale')); assert.deepEqual(await t.engine.pending(), []);
  t.identity.verified = false; await assert.rejects(t.engine.pending(), code('unauthorized'));
});
test('journal is partitioned by actor/origin/database and does not expire unknown intents', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); }); await assert.rejects(t.engine.create(createBody())); const first = structuredClone(t.identity);
  for (const patch of [{ uid: 8 }, { origin: 'https://other.test' }, { db: 'other' }]) { t.identity = { ...first, ...patch }; assert.deepEqual(await t.engine.pending(), []); }
  t.identity = first; t.deps.now = () => 9999999999999; assert.equal((await new TasksEngine(t.deps).pending()).length, 1);
});
test('at most twenty unknown intents; no implicit eviction, while unrelated retries remain possible', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); });
  for (let n = 0; n < 20; n++) await assert.rejects(t.engine.create(createBody({ title: `Task ${n}` })));
  assert.equal((await t.engine.pending()).length, 20); const before = t.calls.length;
  await assert.rejects(t.engine.create(createBody({ title: 'Twenty first' })), code('pending_capacity')); assert.equal(t.calls.length, before); assert.equal((await t.engine.pending()).length, 20);
});
test('corrupted stored payload/revision cannot be replayed and acknowledged rows may not be invented', async () => {
  const t = await setup(); t.handler(() => { throw new Error('lost'); }); await assert.rejects(t.engine.transition(taskRow(), { action: 'done' }));
  const [key, raw] = [...t.data.entries()][0]; const record = JSON.parse(raw); record.attempts[0].payload.expected_revision = 0; t.data.set(key, JSON.stringify(record));
  const before = t.calls.length; await assert.rejects(t.engine.retry(record.attempts[0].uuid), code('storage_corrupt')); assert.equal(t.calls.length, before);
});

// @ts-nocheck -- Node-only bounded contract fixtures.
import { TasksEngine } from '../core/TasksEngine.ts';
export const NOW = '2026-10-19T12:00:00Z';
export const taskRow = (extras = {}) => ({
  id: 100, company_id: 1, company_name: 'Company', room_id: null, title: 'Repair AC', description: '', state: 'new',
  creator_id: 7, creator_name: 'Manager', assignee_id: 7, assignee_name: 'Engineer', due_at: null, created_at: NOW, updated_at: NOW,
  revision: 1, last_actor_id: 7, last_changed_at: NOW, last_note: '', started_at: null, done_at: null, cancelled_at: null,
  completion_note: '', done_by_id: null, done_by_name: '', reminder_at: null, reminder_emitted_at: null, reminder_due: false,
  origin_api: 'work_tasks_v1', allowed_actions: ['start', 'done', 'cancel', 'reassign'], ...extras,
});
export const optionsDTO = (extras = {}) => ({ api_version: 2, work_tasks_version: 1, server_now: NOW, companies: [{ id: 1, name: 'One' }, { id: 2, name: 'Two' }], default_company_id: null, can_view: true, can_manage: true, capabilities: { direct_done: true, reminders: true }, ...extras });
export const createBody = (extras = {}) => ({ company_id: 1, room_id: null, title: 'Repair AC', description: '', assignee_id: 7, due_at: null, reminder_at: null, ...extras });
export const detailDTO = (row = taskRow()) => ({ api_version: 2, work_tasks_version: 1, server_now: NOW, task: row });
export const writeDTO = (request, extras = {}) => {
  const p = request.payload; const transition = request.path.endsWith('/transition');
  const state = !transition ? 'new' : p.action === 'done' ? 'done' : p.action === 'cancel' ? 'cancelled' : p.action === 'start' ? 'in_progress' : 'new';
  return { ...detailDTO(taskRow({ company_id: p.company_id, title: p.title ?? 'Repair AC', description: p.description ?? '', due_at: p.due_at ?? null, reminder_at: p.reminder_at ?? null,
    assignee_id: p.assignee_id ?? 7, revision: transition ? p.expected_revision + 1 : 1, state,
    allowed_actions: state === 'done' || state === 'cancelled' ? [] : state === 'in_progress' ? ['done', 'cancel', 'reassign'] : ['start', 'done', 'cancel', 'reassign'],
    ...(state === 'done' ? { done_at: NOW, done_by_id: 7, done_by_name: 'Engineer', completion_note: p.reason ?? '' } : {}),
  })), client_uuid: p.client_uuid, replayed: false, operation_revision: transition ? p.expected_revision + 1 : 1, ...extras };
};
export const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
export const code = expected => error => error.code === expected;
export async function setup(options = {}) {
  const data = options.data ?? new Map(); const calls = []; let writes = 0; let counter = 0; let failWrite = () => false; let failRead = () => false; let handler;
  let identity = { origin: 'https://example.test', db: 'db', uid: 7, epoch: 1, verified: true, companyIds: [1, 2], permissions: { task_view: true, task_manage: true } };
  let unauthorized = 0; let forbidden = 0;
  const storage = { getItem: async key => { if (failRead()) throw new Error('read failure'); return data.get(key) ?? null; }, setItem: async (key, value) => { writes++; if (failWrite(writes)) throw new Error('disk full'); data.set(key, value); } };
  const deps = { storage, identityScope: () => identity, now: () => 1234, uuid: () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`, onUnauthorized: () => { unauthorized++; }, onForbidden: () => { forbidden++; }, transport: { request: async request => {
    calls.push(request); if (handler) return handler(request);
    if (request.path.endsWith('/options')) return optionsDTO();
    if (request.method === 'POST') return writeDTO(request);
    if (request.path.endsWith('/assignees')) return { api_version: 2, work_tasks_version: 1, company_id: request.query.company_id, assignees: [{ id: 7, name: 'Engineer' }], next_after_id: null };
    if (request.path.endsWith('/100')) return detailDTO();
    return { api_version: 2, work_tasks_version: 1, server_now: NOW, view: request.query.view, company_id: request.query.company_id ?? null, tasks: [taskRow({ company_id: request.query.company_id ?? 2 }), taskRow({ id: 99, company_id: request.query.company_id ?? 1 })], next_before_id: null };
  } } };
  const engine = new TasksEngine(deps); if (options.initialize !== false) await engine.options(); calls.length = 0;
  return { engine, deps, data, calls, get writes() { return writes; }, get identity() { return identity; }, set identity(v) { identity = v; }, handler: fn => { handler = fn; }, failWrite: fn => { failWrite = fn; }, failRead: fn => { failRead = fn; }, callbacks: () => ({ unauthorized, forbidden }) };
}

import { TasksError } from './types.ts';
import type { TaskAction, TaskIdentity, WorkTask, WorkTaskCreateInput, WorkTasksOptions, WorkTaskAssigneesPage, WorkTasksPage, WorkTaskDetail, WorkTaskWriteResult } from './types.ts';

export const bytes = (text: string): number => new TextEncoder().encode(text).length;
export const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));
export function invalid(): never { throw new TasksError('invalid_response'); }
export function id(value: unknown): number { if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0 || value > 2147483647) throw new TasksError('invalid_payload'); return value; }
export function text(value: unknown, maximum: number, nonempty = false): string {
  if (typeof value !== 'string' || bytes(value) > maximum || (nonempty && !value.trim())
    || /\p{C}/u.test(nonempty ? value : value.replace(/[\n\t]/g, ''))) throw new TasksError('invalid_payload'); return value;
}
export function utc(value: unknown, nullable = true): string | null {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)) throw new TasksError('invalid_payload');
  const parsed = new Date(value); if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().replace('.000Z', 'Z') !== value) throw new TasksError('invalid_payload'); return value;
}
export function uuid(value: unknown): string { if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)) throw new TasksError('invalid_payload'); return value; }
export function exact(value: unknown, keys: string[]): asserts value is Record<string, any> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== keys.length || keys.some(k => !Object.prototype.hasOwnProperty.call(value, k))) throw new TasksError('invalid_payload');
}
export function createInput(input: WorkTaskCreateInput): void {
  exact(input, ['company_id', 'room_id', 'title', 'description', 'assignee_id', 'due_at', 'reminder_at']);
  id(input.company_id); id(input.assignee_id); if (input.room_id !== null) throw new TasksError('invalid_payload');
  text(input.title, 160, true); text(input.description, 4096); utc(input.due_at); utc(input.reminder_at);
  if (input.reminder_at && (!input.due_at || input.reminder_at > input.due_at)) throw new TasksError('invalid_payload');
}
export function payloadInput(kind: 'create' | 'transition', input: Record<string, any>): void {
  if (kind === 'create') {
    exact(input, ['api_version', 'work_tasks_version', 'company_id', 'room_id', 'client_uuid', 'title', 'description', 'assignee_id', 'due_at', 'reminder_at']);
    const { api_version: _api, work_tasks_version: _version, client_uuid: _uuid, ...body } = input; createInput(body as WorkTaskCreateInput);
  } else {
    exact(input, ['api_version', 'work_tasks_version', 'company_id', 'client_uuid', 'expected_revision', 'action', 'assignee_id', 'reason']);
    id(input.company_id); id(input.expected_revision);
    if (!['start', 'done', 'cancel', 'reassign'].includes(input.action)) throw new TasksError('invalid_payload');
    if (input.action === 'reassign') id(input.assignee_id); else if (input.assignee_id !== null) throw new TasksError('invalid_payload');
    if (input.reason !== null) text(input.reason, 512);
  }
  if (input.api_version !== 2 || input.work_tasks_version !== 1) throw new TasksError('invalid_payload'); uuid(input.client_uuid);
}
function envelope(value: unknown, maximum: number): any {
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value) || bytes(JSON.stringify(value)) > maximum) invalid();
    if ((value as any).api_version !== 2 || (value as any).work_tasks_version !== 1) throw new TasksError('server_update_required');
    return value;
  } catch (error) { if (error instanceof TasksError) throw error; return invalid(); }
}
function response<T>(validate: () => T): T { try { return copy(validate()); } catch (error) { if (error instanceof TasksError && error.code === 'server_update_required') throw error; return invalid(); } }
function selection(value: any): void { id(value?.id); text(value.name, 256, true); }
function nullableId(value: unknown): void { if (value !== null) id(value); }
export function task(value: any, identity: TaskIdentity): WorkTask {
  if (!value || typeof value !== 'object' || Array.isArray(value) || bytes(JSON.stringify(value)) > 12288) invalid();
  for (const key of ['id', 'company_id', 'creator_id', 'assignee_id', 'revision']) id(value[key]);
  for (const key of ['room_id', 'last_actor_id', 'done_by_id']) nullableId(value[key]);
  for (const key of ['company_name', 'creator_name', 'assignee_name', 'done_by_name']) text(value[key], 256);
  text(value.title, 160, true); text(value.description, 4096); text(value.last_note, 512); text(value.completion_note, 512);
  utc(value.created_at, false); utc(value.updated_at, false);
  for (const key of ['due_at', 'last_changed_at', 'started_at', 'done_at', 'cancelled_at', 'reminder_at', 'reminder_emitted_at']) utc(value[key]);
  if (!identity.companyIds.includes(value.company_id) || !['new', 'in_progress', 'done', 'cancelled'].includes(value.state)
    || !['tasks_v2', 'work_tasks_v1'].includes(value.origin_api) || typeof value.reminder_due !== 'boolean') invalid();
  if (value.room_id === null && value.creator_id !== identity.uid && value.assignee_id !== identity.uid) invalid();
  if (value.reminder_at && (!value.due_at || value.reminder_at > value.due_at)) invalid();
  if ((value.done_by_id === null && value.done_by_name !== '') || (value.state !== 'done' && (value.done_by_id !== null || value.done_at !== null || value.completion_note !== ''))) invalid();
  if (!Array.isArray(value.allowed_actions) || value.allowed_actions.length > 4 || new Set(value.allowed_actions).size !== value.allowed_actions.length) invalid();
  const open = ['new', 'in_progress'].includes(value.state);
  for (const action of value.allowed_actions as TaskAction[]) {
    if (!identity.permissions.task_manage || !open || !['start', 'done', 'cancel', 'reassign'].includes(action)) invalid();
    if (['start', 'done'].includes(action) && (value.assignee_id !== identity.uid || (action === 'start' && value.state !== 'new'))) invalid();
    if (['cancel', 'reassign'].includes(action) && value.creator_id !== identity.uid) invalid();
  }
  return value as WorkTask;
}
export function optionsResponse(value: unknown, identity: TaskIdentity): WorkTasksOptions { return response(() => {
  const v = envelope(value, 524288); utc(v.server_now, false);
  if (!Array.isArray(v.companies) || v.companies.length > 1000 || typeof v.can_view !== 'boolean' || typeof v.can_manage !== 'boolean' || (v.can_manage && !v.can_view)) invalid();
  if (v.capabilities?.direct_done !== true || v.capabilities?.reminders !== true) throw new TasksError('server_update_required');
  const ids = new Set<number>(); for (const company of v.companies) { selection(company); if (ids.has(company.id) || !identity.companyIds.includes(company.id)) invalid(); ids.add(company.id); }
  nullableId(v.default_company_id);
  if ((v.companies.length === 1 && v.default_company_id !== v.companies[0].id) || (v.default_company_id !== null && !ids.has(v.default_company_id))) invalid();
  return v;
}); }
export function assigneesResponse(value: unknown, companyId: number, afterId = 0): WorkTaskAssigneesPage { return response(() => {
  const v = envelope(value, 65536); if (v.company_id !== companyId || !Array.isArray(v.assignees) || v.assignees.length > 50) invalid();
  let previous = afterId; for (const candidate of v.assignees) { selection(candidate); if (candidate.id <= previous) invalid(); previous = candidate.id; }
  nullableId(v.next_after_id); if (v.next_after_id !== null && (!v.assignees.length || v.next_after_id !== previous)) invalid(); return v;
}); }
export function pageResponse(value: unknown, identity: TaskIdentity, view: string, state: string, companyId?: number, beforeId?: number): WorkTasksPage { return response(() => {
  const v = envelope(value, 131072); utc(v.server_now, false);
  if (v.view !== view || v.company_id !== (companyId ?? null) || !Array.isArray(v.tasks) || v.tasks.length > 30) invalid();
  let previous = beforeId ?? 2147483648;
  for (const item of v.tasks) {
    task(item, identity); if (item.id >= previous || (companyId !== undefined && item.company_id !== companyId)
      || (view === 'mine' ? item.assignee_id !== identity.uid : item.creator_id !== identity.uid)
      || (state === 'open' ? !['new', 'in_progress'].includes(item.state) : item.state !== state)) invalid(); previous = item.id;
  }
  nullableId(v.next_before_id); if (v.next_before_id !== null && (!v.tasks.length || v.next_before_id !== previous)) invalid(); return v;
}); }
export function detailResponse(value: unknown, identity: TaskIdentity, taskId?: number, companyId?: number): WorkTaskDetail { return response(() => {
  const v = envelope(value, 131072); utc(v.server_now, false); task(v.task, identity);
  if ((taskId !== undefined && v.task.id !== taskId) || (companyId !== undefined && v.task.company_id !== companyId)) invalid(); return v;
}); }
export function writeResponse(value: unknown, identity: TaskIdentity, kind: 'create' | 'transition', payload: Record<string, any>, taskId?: number): WorkTaskWriteResult { return response(() => {
  const v = detailResponse(value, identity, taskId, payload.company_id);
  const out = value as WorkTaskWriteResult;
  if (out.client_uuid !== payload.client_uuid || typeof out.replayed !== 'boolean' || out.operation_revision !== (kind === 'create' ? 1 : payload.expected_revision + 1) || v.task.revision < out.operation_revision) invalid();
  if (kind === 'create' && (v.task.creator_id !== identity.uid || v.task.origin_api !== 'work_tasks_v1' || v.task.room_id !== null || v.task.title !== payload.title || v.task.description !== payload.description || v.task.due_at !== payload.due_at || v.task.reminder_at !== payload.reminder_at || (v.task.revision === 1 && v.task.assignee_id !== payload.assignee_id))) invalid();
  if (kind === 'transition' && v.task.revision === out.operation_revision) {
    const expectedState = payload.action === 'done' ? 'done' : payload.action === 'cancel' ? 'cancelled' : payload.action === 'start' ? 'in_progress' : null;
    if ((expectedState && v.task.state !== expectedState) || v.task.last_actor_id !== identity.uid || (payload.action === 'reassign' && v.task.assignee_id !== payload.assignee_id)
      || (payload.action === 'done' && (v.task.done_by_id !== identity.uid || v.task.completion_note !== (payload.reason ?? '')))) invalid();
  }
  return out;
}); }

import { TasksError } from './types.ts';
import type { TaskIdentity, TasksEngineDependencies, TasksRequest, TasksAssigneesQuery, TasksListQuery, WorkTask, WorkTaskCreateInput, TaskTransitionInput, PendingTaskAttempt, WorkTasksOptions } from './types.ts';
import { accountKey, TasksJournal } from './journal.ts';
import type { TaskAttempt } from './journal.ts';
import { assigneesResponse, copy, createInput, detailResponse, id, optionsResponse, pageResponse, task, text, uuid, writeResponse } from './validators.ts';

const ROOT = '/bwork/api/v2/work-tasks';
type Right = 'task_view' | 'task_manage';
function stamp(value: TaskIdentity): string { return JSON.stringify([accountKey(value), value.epoch, [...value.companyIds].sort((a, b) => a - b), value.permissions]); }
/** Connected-only bounded reads; durable explicit writes; never polling or automatic replay. */
export class TasksEngine {
  private deps: TasksEngineDependencies;
  private journal: TasksJournal;
  private optionsScope = new Map<string, WorkTasksOptions>();
  private revoked = new Set<string>();
  private reads = new Map<string, { sequence: number; controller: AbortController }>();
  private sequence = 0;
  private inflightWrites = new Set<string>();
  private listeners = new Set<() => void>();
  constructor(deps: TasksEngineDependencies) { this.deps = deps; this.journal = new TasksJournal(deps.storage); }
  subscribe(listener: () => void): () => void { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; }
  private emit(start: TaskIdentity): void {
    if (!this.current(start)) return;
    for (const listener of this.listeners) { try { listener(); } catch { /* A UI subscriber cannot break durable settlement. */ } }
  }
  cancelReads(): void { for (const read of this.reads.values()) read.controller.abort(); this.reads.clear(); this.sequence += 1; }
  private current(start: TaskIdentity): boolean { const now = this.deps.identityScope(); return !!now?.verified && stamp(now) === stamp(start); }
  private identity(right: Right, companyId?: number, options = true): TaskIdentity {
    const value = this.deps.identityScope();
    if (!value?.verified || typeof value.origin !== 'string' || !value.origin || typeof value.db !== 'string' || !value.db) throw new TasksError('unauthorized');
    id(value.uid);
    if (!Array.isArray(value.companyIds) || value.companyIds.length > 1000 || new Set(value.companyIds).size !== value.companyIds.length) throw new TasksError('forbidden');
    value.companyIds.forEach(id);
    if (!value.permissions.task_view || !value.permissions[right]) throw new TasksError('forbidden');
    if (companyId !== undefined && !value.companyIds.includes(id(companyId))) throw new TasksError('forbidden');
    if (options) {
      if (this.revoked.has(stamp(value))) throw new TasksError('forbidden');
      const verified = this.optionsScope.get(stamp(value));
      if (!verified) throw new TasksError('server_update_required');
      if (!verified.can_view || (right === 'task_manage' && !verified.can_manage)
        || (companyId !== undefined && !verified.companies.some(c => c.id === companyId))) throw new TasksError('forbidden');
    }
    return copy(value);
  }
  private guard(start: TaskIdentity, right: Right, companyId?: number, options = true): void {
    if (!this.current(start)) throw new TasksError('stale'); this.identity(right, companyId, options);
  }
  private error(error: unknown, start: TaskIdentity, companyId?: number): Error {
    if (!this.current(start)) return new TasksError('stale');
    const value = error as any; const status = value?.status;
    let code = value?.code;
    if (status === 404 || status === 503) code = 'server_update_required';
    if (status === 401 || code === 'unauthorized' || code === 'session') { this.optionsScope.delete(stamp(start)); this.deps.onUnauthorized?.(); code = 'unauthorized'; }
    if (status === 403 || code === 'forbidden') { this.revoked.add(stamp(start)); this.deps.onForbidden?.(companyId); code = 'forbidden'; }
    return new TasksError(typeof code === 'string' ? code : 'network_error', typeof code === 'string' ? code : 'network_error', undefined, status);
  }
  private async transport(start: TaskIdentity, request: TasksRequest, companyId?: number): Promise<unknown> {
    try {
      const value = await this.deps.transport.request(request);
      if (value && typeof value === 'object' && 'error' in value) {
        const code = (value as any).error?.code;
        throw new TasksError(typeof code === 'string' ? code : 'server_error');
      }
      return value;
    } catch (error) { throw this.error(error, start, companyId); }
  }
  private async read<T>(key: string, start: TaskIdentity, companyId: number | undefined, request: TasksRequest, validate: (value: unknown) => T, options = true): Promise<T> {
    this.guard(start, 'task_view', companyId, options);
    this.reads.get(key)?.controller.abort();
    const active = { sequence: ++this.sequence, controller: new AbortController() }; this.reads.set(key, active);
    try {
      const value = await this.transport(start, { ...request, signal: active.controller.signal }, companyId);
      if (active.controller.signal.aborted || this.reads.get(key) !== active) throw new TasksError('stale');
      this.guard(start, 'task_view', companyId, options); const result = validate(value);
      this.guard(start, 'task_view', companyId, options); return result;
    } catch (error) { if (active.controller.signal.aborted || this.reads.get(key) !== active || !this.current(start)) throw new TasksError('stale'); throw error; }
    finally { if (this.reads.get(key) === active) this.reads.delete(key); }
  }
  async options(): Promise<WorkTasksOptions> {
    const start = this.identity('task_view', undefined, false); this.optionsScope.delete(stamp(start));
    const result = await this.read('options', start, undefined, { method: 'GET', path: `${ROOT}/options` }, v => optionsResponse(v, start), false);
    this.guard(start, 'task_view', undefined, false);
    if (!result.can_view || (result.can_manage && !start.permissions.task_manage)) throw new TasksError('forbidden');
    this.optionsScope.clear(); this.optionsScope.set(stamp(start), copy(result)); this.revoked.delete(stamp(start)); return result;
  }
  async assignees(companyId: number, query: TasksAssigneesQuery = {}) {
    const start = this.identity('task_manage', companyId); const args: Record<string, string | number> = { company_id: id(companyId) };
    if (query.q !== undefined) args.q = text(query.q, 256); if (query.afterId !== undefined) args.after_id = id(query.afterId);
    return this.read('assignees', start, companyId, { method: 'GET', path: `${ROOT}/assignees`, query: args }, v => assigneesResponse(v, companyId, query.afterId));
  }
  async list(query: TasksListQuery = {}) {
    const { view = 'mine', state = 'open', companyId, beforeId } = query;
    if (!['mine', 'created'].includes(view) || !['open', 'done', 'cancelled'].includes(state)) throw new TasksError('invalid_payload');
    const start = this.identity('task_view', companyId); const args: Record<string, string | number> = { view, state };
    if (companyId !== undefined) args.company_id = id(companyId); if (beforeId !== undefined) args.before_id = id(beforeId);
    return this.read('list', start, companyId, { method: 'GET', path: ROOT, query: args }, v => {
      const result = pageResponse(v, start, view, state, companyId, beforeId);
      const allowed = this.optionsScope.get(stamp(start))!.companies.map(c => c.id);
      if (result.tasks.some(t => !allowed.includes(t.company_id))) throw new TasksError('invalid_response'); return result;
    });
  }
  async detail(taskId: number, companyId: number) {
    const start = this.identity('task_view', companyId);
    return this.read('detail', start, companyId, { method: 'GET', path: `${ROOT}/${id(taskId)}`, query: { company_id: id(companyId) } }, v => detailResponse(v, start, taskId, companyId));
  }
  async pending(): Promise<PendingTaskAttempt[]> {
    const start = this.identity('task_view', undefined, false); const entries = await this.journal.pending(accountKey(start)); this.guard(start, 'task_view', undefined, false);
    return entries.filter(a => start.companyIds.includes(a.companyId)).map(({ payload: _payload, state: _state, ...publicEntry }) => publicEntry);
  }
  private async execute(start: TaskIdentity, attempt: TaskAttempt) {
    if (this.inflightWrites.has(attempt.uuid)) throw new TasksError('write_in_progress');
    this.inflightWrites.add(attempt.uuid);
    try {
      this.guard(start, 'task_manage', attempt.companyId);
      const value = await this.transport(start, { method: 'POST', path: attempt.kind === 'create' ? ROOT : `${ROOT}/${attempt.taskId}/transition`, payload: copy(attempt.payload) }, attempt.companyId);
      // A late response may settle only its original actor's durable journal, never a new UI identity.
      const result = writeResponse(value, start, attempt.kind, attempt.payload, attempt.taskId);
      await this.journal.acknowledge(accountKey(start), attempt.uuid);
      this.guard(start, 'task_manage', attempt.companyId); this.emit(start); return result;
    } catch (error) {
      if (!this.current(start)) throw new TasksError('stale');
      const code = (error as any)?.code;
      if (code === 'stale') throw error;
      throw new TasksError(typeof code === 'string' ? code : 'outcome_unknown', typeof code === 'string' ? code : 'outcome_unknown', attempt.uuid, (error as any)?.status);
    } finally { this.inflightWrites.delete(attempt.uuid); }
  }
  async create(input: WorkTaskCreateInput) {
    const body = copy(input); createInput(body); body.title = body.title.trim(); const start = this.identity('task_manage', body.company_id);
    const attempt: TaskAttempt = { uuid: uuid(this.deps.uuid()), kind: 'create', companyId: body.company_id, createdAt: this.deps.now(), state: 'unknown', payload: { api_version: 2, work_tasks_version: 1, ...body, client_uuid: '' } };
    attempt.payload.client_uuid = attempt.uuid;
    await this.journal.add(accountKey(start), attempt); this.emit(start); return this.execute(start, attempt);
  }
  async transition(row: WorkTask, input: TaskTransitionInput) {
    const current = copy(row); const start = this.identity('task_manage', current.company_id); task(current, start);
    if (!input || !['start', 'done', 'cancel', 'reassign'].includes(input.action) || !['new', 'in_progress'].includes(current.state)) throw new TasksError('invalid_payload');
    if (!current.allowed_actions.includes(input.action)) throw new TasksError('forbidden');
    // Recheck roles independently of untrusted or stale allowed_actions supplied by a caller.
    if (['start', 'done'].includes(input.action) && (current.assignee_id !== start.uid || (input.action === 'start' && current.state !== 'new'))) throw new TasksError('forbidden');
    if (['cancel', 'reassign'].includes(input.action) && current.creator_id !== start.uid) throw new TasksError('forbidden');
    if (input.action === 'reassign') id(input.assigneeId); else if (input.assigneeId !== undefined) throw new TasksError('invalid_payload');
    if (input.note !== undefined) text(input.note, 512);
    if (current.revision >= 2147483647) throw new TasksError('invalid_payload');
    const attempt: TaskAttempt = { uuid: uuid(this.deps.uuid()), kind: 'transition', companyId: current.company_id, taskId: current.id, createdAt: this.deps.now(), state: 'unknown', payload: {
      api_version: 2, work_tasks_version: 1, company_id: current.company_id, client_uuid: '', expected_revision: current.revision,
      action: input.action, assignee_id: input.action === 'reassign' ? input.assigneeId! : null, reason: input.note ?? null,
    } };
    attempt.payload.client_uuid = attempt.uuid;
    await this.journal.add(accountKey(start), attempt); this.emit(start); return this.execute(start, attempt);
  }
  async retry(attemptId: string) {
    uuid(attemptId); const start = this.identity('task_manage'); const entries = await this.journal.pending(accountKey(start));
    this.guard(start, 'task_manage'); const attempt = entries.find(a => a.uuid === attemptId);
    if (!attempt) throw new TasksError('unknown_attempt'); this.guard(start, 'task_manage', attempt.companyId);
    return this.execute(start, attempt);
  }
}

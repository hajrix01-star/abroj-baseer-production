/** Modern work-tasks facade. No implicit chat or order authority. */
export type TaskAction = 'start' | 'done' | 'cancel' | 'reassign';
export type TaskState = 'new' | 'in_progress' | 'done' | 'cancelled';
export type TasksView = 'mine' | 'created';
export type TasksStateFilter = 'open' | 'done' | 'cancelled';
export interface TaskSelection { id: number; name: string }
export interface TaskIdentity {
  origin: string; db: string; uid: number; companyIds: readonly number[];
  epoch: string | number; verified: boolean;
  permissions: { task_view: boolean; task_manage: boolean };
}
export interface WorkTask {
  id: number; company_id: number; company_name: string; room_id: number | null;
  title: string; description: string; state: TaskState;
  creator_id: number; creator_name: string; assignee_id: number; assignee_name: string;
  due_at: string | null; created_at: string; updated_at: string; revision: number;
  last_actor_id: number | null; last_changed_at: string | null; last_note: string;
  started_at: string | null; done_at: string | null; cancelled_at: string | null;
  completion_note: string; done_by_id: number | null; done_by_name: string;
  reminder_at: string | null; reminder_emitted_at: string | null; reminder_due: boolean;
  origin_api: 'tasks_v2' | 'work_tasks_v1'; allowed_actions: TaskAction[];
}
export interface WorkTasksOptions {
  api_version: 2; work_tasks_version: 1; server_now: string; companies: TaskSelection[];
  default_company_id: number | null; can_view: boolean; can_manage: boolean;
  capabilities: { direct_done: true; reminders: true };
}
export interface WorkTaskAssigneesPage {
  api_version: 2; work_tasks_version: 1; company_id: number;
  assignees: TaskSelection[]; next_after_id: number | null;
}
export interface TasksAssigneesQuery { q?: string; afterId?: number }
export interface TasksListQuery { view?: TasksView; state?: TasksStateFilter; companyId?: number; beforeId?: number }
export interface WorkTasksPage {
  api_version: 2; work_tasks_version: 1; server_now: string; view: TasksView;
  company_id: number | null; tasks: WorkTask[]; next_before_id: number | null;
}
export interface WorkTaskDetail { api_version: 2; work_tasks_version: 1; server_now: string; task: WorkTask }
export interface WorkTaskCreateInput {
  company_id: number; room_id: null; title: string; description: string;
  assignee_id: number; due_at: string | null; reminder_at: string | null;
}
export interface TaskTransitionInput { action: TaskAction; assigneeId?: number; note?: string }
export interface WorkTaskWriteResult extends WorkTaskDetail { client_uuid: string; replayed: boolean; operation_revision: number }
export interface PendingTaskAttempt { uuid: string; kind: 'create' | 'transition'; companyId: number; taskId?: number; createdAt: number }
export interface TasksRequest { method: 'GET' | 'POST'; path: string; query?: Record<string, string | number>; payload?: Record<string, unknown>; signal?: AbortSignal }
export interface TasksTransport { request(request: TasksRequest): Promise<unknown> }
export interface TasksStorage { getItem(key: string): Promise<string | null>; setItem(key: string, value: string): Promise<void> }
export interface TasksEngineDependencies {
  transport: TasksTransport; storage: TasksStorage; identityScope: () => TaskIdentity | null;
  now: () => number; uuid: () => string; onUnauthorized?: () => void; onForbidden?: (companyId?: number) => void;
}
export class TasksError extends Error {
  code: string; attemptId?: string; status?: number;
  constructor(code: string, message = code, attemptId?: string, status?: number) {
    super(message); this.name = 'TasksError'; this.code = code; this.attemptId = attemptId; this.status = status;
  }
}

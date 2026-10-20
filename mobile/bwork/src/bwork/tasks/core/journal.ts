import { TasksError } from './types.ts';
import type { PendingTaskAttempt, TaskIdentity, TasksStorage } from './types.ts';
import { bytes, copy, exact, id, payloadInput, uuid } from './validators.ts';

export const accountKey = (identity: TaskIdentity): string => JSON.stringify([identity.origin, identity.db, identity.uid]);
export interface TaskAttempt extends PendingTaskAttempt {
  payload: Record<string, any>; state: 'unknown' | 'acknowledged';
}
interface RecordFile { version: 1; account: string; attempts: TaskAttempt[] }
const queues = new WeakMap<TasksStorage, Map<string, Promise<unknown>>>();
/** Private actor partition, serialized durable round trips. Unknown intents are never evicted. */
export class TasksJournal {
  private storage: TasksStorage;
  constructor(storage: TasksStorage) { this.storage = storage; }
  private key(account: string): string { return `bwork.tasks.journal.v1:${encodeURIComponent(account)}`; }
  private async exclusive<T>(account: string, work: () => Promise<T>): Promise<T> {
    let map = queues.get(this.storage); if (!map) { map = new Map(); queues.set(this.storage, map); }
    const prior = map.get(account) ?? Promise.resolve();
    const current = prior.catch(() => undefined).then(work); map.set(account, current);
    try { return await current; } finally { if (map.get(account) === current) map.delete(account); }
  }
  private async read(account: string): Promise<RecordFile> {
    let raw: string | null;
    try { raw = await this.storage.getItem(this.key(account)); } catch { throw new TasksError('storage_unavailable'); }
    if (raw === null) return { version: 1, account, attempts: [] };
    try {
      if (typeof raw !== 'string' || bytes(raw) > 1048576) throw new Error();
      const value = JSON.parse(raw); exact(value, ['version', 'account', 'attempts']);
      if (value.version !== 1 || value.account !== account || !Array.isArray(value.attempts) || value.attempts.length > 40) throw new Error();
      const ids = new Set<string>();
      for (const entry of value.attempts) {
        exact(entry, entry.kind === 'create' ? ['uuid', 'kind', 'companyId', 'createdAt', 'payload', 'state'] : ['uuid', 'kind', 'companyId', 'taskId', 'createdAt', 'payload', 'state']);
        uuid(entry.uuid); id(entry.companyId); if (entry.kind !== 'create' && entry.kind !== 'transition') throw new Error();
        if (entry.kind === 'transition') id(entry.taskId);
        if (!Number.isSafeInteger(entry.createdAt) || entry.createdAt < 0 || !['unknown', 'acknowledged'].includes(entry.state) || ids.has(entry.uuid)) throw new Error();
        ids.add(entry.uuid); payloadInput(entry.kind, entry.payload);
        if (entry.payload.client_uuid !== entry.uuid || entry.payload.company_id !== entry.companyId) throw new Error();
      }
      if (value.attempts.filter((a: TaskAttempt) => a.state === 'unknown').length > 20) throw new Error();
      return value as unknown as RecordFile;
    } catch { throw new TasksError('storage_corrupt'); }
  }
  private async persist(account: string, value: RecordFile): Promise<void> {
    const encoded = JSON.stringify(value); if (bytes(encoded) > 1048576) throw new TasksError('pending_capacity');
    try { await this.storage.setItem(this.key(account), encoded); if (await this.storage.getItem(this.key(account)) !== encoded) throw new Error(); }
    catch { throw new TasksError('storage_unavailable'); }
  }
  pending(account: string): Promise<TaskAttempt[]> { return this.exclusive(account, async () => copy((await this.read(account)).attempts.filter(a => a.state === 'unknown'))); }
  async add(account: string, attempt: TaskAttempt): Promise<void> {
    return this.exclusive(account, async () => {
      const value = await this.read(account); const pending = value.attempts.filter(a => a.state === 'unknown');
      if (value.attempts.some(a => a.uuid === attempt.uuid)) throw new TasksError('duplicate_uuid');
      if (pending.length >= 20) throw new TasksError('pending_capacity');
      const duplicate = pending.find(a => attempt.kind === 'transition' ? a.kind === 'transition' && a.taskId === attempt.taskId : a.kind === 'create' && this.intent(a.payload) === this.intent(attempt.payload));
      if (duplicate) throw new TasksError('pending_attempt', 'pending_attempt', duplicate.uuid);
      // Only previously durably acknowledged entries may be compacted.
      value.attempts = [...pending, ...value.attempts.filter(a => a.state === 'acknowledged').slice(-19), copy(attempt)];
      await this.persist(account, value);
    });
  }
  private intent(payload: Record<string, any>): string { return JSON.stringify(Object.keys(payload).filter(k => k !== 'client_uuid').sort().map(k => [k, payload[k]])); }
  async acknowledge(account: string, attemptId: string): Promise<void> {
    return this.exclusive(account, async () => {
      const before = await this.read(account); const value = copy(before); const attempt = value.attempts.find(a => a.uuid === attemptId);
      if (!attempt) throw new TasksError('storage_corrupt'); if (attempt.state === 'acknowledged') return;
      attempt.state = 'acknowledged';
      try { await this.persist(account, value); }
      catch (error) {
        // A failed ACK round trip must not intentionally forget the original immutable intent.
        try { await this.persist(account, before); } catch { /* Storage is failed; never clear or invent settlement. */ }
        throw error;
      }
    });
  }
}

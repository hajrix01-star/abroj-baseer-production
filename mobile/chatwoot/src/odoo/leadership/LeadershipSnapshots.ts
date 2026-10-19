import type { Storage } from '../core/ChatEngine.ts';
import { LeadershipError } from './types.ts';
import type { LeadershipOptions, LeadershipQuery, LeadershipReport } from './types.ts';
import { date, id, optionsResponse, query as checkedQuery, reportResponse } from './validation.ts';

export interface SnapshotAuthority {
  origin: string; db: string; uid: number; companyIds: number[]; canView: boolean;
  revision: number; epoch: string | number; leaseRemainingMs: number;
}
interface Control { version: 1; blocked: boolean; highWater: number }
interface Entry {
  key: string; query: LeadershipQuery; businessDate: string | null;
  savedAt: number; expiresAt: number; report: LeadershipReport;
}
interface Envelope { version: 1; fingerprint: string; options: LeadershipOptions; entries: Entry[] }
interface Operation { authority: SnapshotAuthority; actor: string; fingerprint: string; stamp: string; generation: number; leaseEnd: number; highWater: number }
const TTL = 24 * 60 * 60 * 1000, LIMIT = 1048576, PREFIX = 'bwork.leadership.snapshots.v1:';
const unavailable = (): never => { throw new LeadershipError('snapshot_unavailable'); };
const size = (value: string): number => unescape(encodeURIComponent(value)).length;
const finiteTime = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const actorKey = (a: SnapshotAuthority) => PREFIX + encodeURIComponent(JSON.stringify([a.origin, a.db, a.uid]));
const fingerprint = (a: SnapshotAuthority) => JSON.stringify([a.origin, a.db, a.uid, a.companyIds, a.canView, a.revision]);
const stamp = (a: SnapshotAuthority) => JSON.stringify([fingerprint(a), a.epoch]);
const nativeIdentity = (a: SnapshotAuthority) => ({ ...a, verified: true });
function authority(value: SnapshotAuthority): SnapshotAuthority {
  if (!value || typeof value.origin !== 'string' || value.origin.length > 2048 || typeof value.db !== 'string' || !value.db || value.db.length > 256 ||
      typeof value.canView !== 'boolean' || !Number.isSafeInteger(value.revision) || value.revision < 0 ||
      !['string', 'number'].includes(typeof value.epoch) || typeof value.epoch === 'number' && !Number.isFinite(value.epoch) ||
      typeof value.leaseRemainingMs !== 'number' || !Number.isFinite(value.leaseRemainingMs) || value.leaseRemainingMs < 0) return unavailable();
  const origin = new URL(value.origin);
  if (origin.protocol !== 'https:' || origin.origin !== value.origin || origin.username || origin.password) return unavailable();
  id(value.uid);
  if (!Array.isArray(value.companyIds) || value.companyIds.length > 1000 || new Set(value.companyIds).size !== value.companyIds.length) return unavailable();
  value.companyIds.forEach(id);
  return { ...value, companyIds: [...value.companyIds].sort((a, b) => a - b) };
}
function businessDate(input: LeadershipQuery, time: number): string | null {
  if (!['today', 'yesterday'].includes(input.period)) return null;
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Riyadh', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(time));
  const part = (type: string) => parts.find(p => p.type === type)?.value;
  const today = date([part('year'), part('month'), part('day')].join('-'));
  if (input.period === 'today') return today;
  const yesterday = new Date(today + 'T12:00:00Z'); yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  return yesterday.toISOString().slice(0, 10);
}
const entryKey = (q: LeadershipQuery, day: string | null) => JSON.stringify([q.companyId ?? null, q.month, q.period, q.date ?? null, day]);
function scope(q: LeadershipQuery, options: LeadershipOptions): void {
  if (q.companyId === undefined ? options.companies.length > options.max_companies : !options.companies.some(c => c.id === q.companyId)) return unavailable();
}

/**
 * Historical financial displays only. Call save ONLY with a newly verified online
 * options/report pair. No credential storage, HTTP authority or request-error fallback.
 * AsyncStorage is app-private, not application-encrypted. Total persistent I/O failure
 * cannot promise crash-durable revocation; in-process access is still blocked immediately.
 */
export class LeadershipSnapshots {
  private storage: Storage; private current: () => SnapshotAuthority | null; private now: () => number;
  private queue: Promise<void> = Promise.resolve();
  private generations = new Map<string, number>(); private blocked = new Set<string>();
  private writers = new Map<string, string | number>(); private expires = 0;
  private epochs = new Map<string, Array<string | number>>();
  constructor(deps: { storage: Storage; current: () => SnapshotAuthority | null; now?: () => number }) {
    this.storage = deps.storage; this.current = deps.current; this.now = deps.now ?? Date.now;
  }
  get displayExpiresAt(): number { return this.expires; }
  private clock(): number { const value = this.now(); if (!finiteTime(value) || !Number.isFinite(new Date(value).getTime())) return unavailable(); return value; }
  private serial<T>(run: () => Promise<T>): Promise<T> {
    const result = this.queue.then(run).catch(error => { if (error instanceof LeadershipError && error.code === 'stale') throw error; return unavailable(); });
    this.queue = result.then(() => undefined, () => undefined); return result;
  }
  private begin(input: SnapshotAuthority): Operation {
    const a = authority(input), actor = actorKey(a), time = this.clock();
    if (!a.canView || !a.companyIds.length || a.leaseRemainingMs <= 0) return unavailable();
    const op = { authority: a, actor, fingerprint: fingerprint(a), stamp: stamp(a), generation: this.generations.get(actor) ?? 0,
      leaseEnd: time + Math.min(a.leaseRemainingMs, TTL), highWater: time };
    this.guard(op, true);
    const epochs = this.epochs.get(actor) ?? [];
    if (!epochs.includes(a.epoch)) { epochs.push(a.epoch); this.epochs.set(actor, epochs.slice(-16)); }
    return op;
  }
  private guard(op: Operation, allowBlocked = false): void {
    let current: SnapshotAuthority;
    try { current = authority(this.current()!); } catch { throw new LeadershipError('stale'); }
    if (!current.canView || current.leaseRemainingMs <= 0 || stamp(current) !== op.stamp ||
        (this.generations.get(op.actor) ?? 0) !== op.generation) throw new LeadershipError('stale');
    const time = this.clock();
    if (time < op.highWater || time >= op.leaseEnd || !allowBlocked && this.blocked.has(op.actor)) return unavailable();
  }
  private async control(op: Operation): Promise<{ value: Control | null; damaged: boolean }> {
    const raw = await this.storage.getItem(op.actor + '/control'); this.guard(op, true);
    if (raw === null) return { value: null, damaged: false };
    try {
      if (size(raw) > 1024) throw new Error();
      const v = JSON.parse(raw);
      if (!v || v.version !== 1 || typeof v.blocked !== 'boolean' || !finiteTime(v.highWater)) throw new Error();
      op.highWater = Math.max(op.highWater, v.highWater); this.guard(op, true);
      return { value: { version: 1, blocked: v.blocked, highWater: v.highWater }, damaged: false };
    } catch (error) { if (error instanceof LeadershipError) throw error; return { value: null, damaged: true }; }
  }
  private decode(raw: string, op: Operation): Envelope {
    if (raw.length > LIMIT || size(raw) > LIMIT) return unavailable();
    const v = JSON.parse(raw);
    if (!v || v.version !== 1 || v.fingerprint !== op.fingerprint || !Array.isArray(v.entries) || !v.entries.length || v.entries.length > 8) return unavailable();
    const options = optionsResponse(v.options, nativeIdentity(op.authority));
    if (!options.can_view) return unavailable();
    const entries: Entry[] = v.entries.map((e: any) => {
      const selected = checkedQuery(e.query); scope(selected, options);
      const report = reportResponse(e.report, selected, options);
      const day = businessDate(selected, Date.parse(report.as_of));
      if (e.businessDate !== day || e.key !== entryKey(selected, day) || !finiteTime(e.savedAt) || !finiteTime(e.expiresAt) ||
          e.expiresAt <= e.savedAt || e.expiresAt > e.savedAt + TTL || e.savedAt > this.clock()) return unavailable();
      return { key: e.key, query: selected, businessDate: day, savedAt: e.savedAt, expiresAt: e.expiresAt, report };
    });
    if (new Set(entries.map(e => e.key)).size !== entries.length) return unavailable();
    return { version: 1, fingerprint: op.fingerprint, options, entries };
  }
  private async load(op: Operation): Promise<Envelope> {
    this.guard(op);
    const control = await this.control(op);
    if (!control.value || control.damaged || control.value.blocked) return unavailable();
    const raw = await this.storage.getItem(op.actor + '/envelope'); this.guard(op);
    if (!raw) return unavailable();
    return this.decode(raw, op);
  }
  private async highWater(op: Operation): Promise<void> {
    this.guard(op); const now = this.clock(); op.highWater = now;
    await this.storage.setItem(op.actor + '/control', JSON.stringify({ version: 1, blocked: false, highWater: now }));
    this.guard(op);
  }
  async save(input: SnapshotAuthority, suppliedOptions: LeadershipOptions, suppliedQuery: LeadershipQuery, suppliedReport: LeadershipReport): Promise<void> {
    let op: Operation, options: LeadershipOptions, selected: LeadershipQuery, report: LeadershipReport, started: number;
    try {
      op = this.begin(input); started = this.clock(); selected = checkedQuery(suppliedQuery);
      options = optionsResponse(suppliedOptions, nativeIdentity(op.authority)); if (!options.can_view) return unavailable();
      scope(selected, options);
      report = reportResponse(suppliedReport, selected, options);
      if (businessDate(selected, started) !== businessDate(selected, Date.parse(report.as_of))) return unavailable();
    } catch (error) { if (error instanceof LeadershipError && error.code === 'stale') throw error; return unavailable(); }
    return this.serial(async () => {
      this.guard(op, true);
      const control = await this.control(op);
      const raw = await this.storage.getItem(op.actor + '/envelope'); this.guard(op, true);
      let previous: Envelope | null = null, reset = control.damaged || !control.value || control.value.blocked || this.blocked.has(op.actor);
      if (raw && !reset) { try { previous = this.decode(raw, op); } catch { reset = true; } }
      if (reset) {
        // Never unlock a blocked incarnation while any old envelope can survive.
        await this.storage.removeItem(op.actor + '/envelope'); this.guard(op, true);
      }
      const time = this.clock(), savedAt = started, expiresAt = Math.min(started + TTL, op.leaseEnd);
      this.guard(op, true);
      if (time >= expiresAt) return unavailable();
      const day = businessDate(selected, time);
      if (day !== businessDate(selected, Date.parse(report.as_of))) return unavailable();
      const key = entryKey(selected, day), entry = { key, query: selected, businessDate: day, savedAt, expiresAt, report };
      const envelope: Envelope = { version: 1, fingerprint: op.fingerprint, options,
        entries: [...(previous?.entries ?? []).filter(e => e.key !== key && e.expiresAt > time), entry].slice(-8) };
      let encoded = JSON.stringify(envelope);
      while (size(encoded) > LIMIT && envelope.entries.length > 1) { envelope.entries.shift(); encoded = JSON.stringify(envelope); }
      if (size(encoded) > LIMIT) return unavailable();
      this.guard(op, true);
      await this.storage.setItem(op.actor + '/envelope', encoded); this.guard(op, true);
      op.highWater = this.clock();
      await this.storage.setItem(op.actor + '/control', JSON.stringify({ version: 1, blocked: false, highWater: op.highWater })); this.guard(op, true);
      this.blocked.delete(op.actor); this.writers.set(op.actor, op.authority.epoch);
    });
  }
  async options(input: SnapshotAuthority): Promise<LeadershipOptions> {
    let op: Operation; try { op = this.begin(input); } catch (error) { if (error instanceof LeadershipError && error.code === 'stale') throw error; return unavailable(); }
    return this.serial(async () => {
      const envelope = await this.load(op);
      if (!envelope.entries.some(e => e.expiresAt > this.clock())) return unavailable();
      await this.highWater(op);
      if (!envelope.entries.some(e => e.expiresAt > this.clock())) return unavailable();
      return envelope.options;
    });
  }
  async read(input: SnapshotAuthority, suppliedQuery: LeadershipQuery): Promise<LeadershipReport> {
    this.expires = 0;
    let op: Operation, selected: LeadershipQuery;
    try { op = this.begin(input); selected = checkedQuery(suppliedQuery); } catch (error) { if (error instanceof LeadershipError && error.code === 'stale') throw error; return unavailable(); }
    return this.serial(async () => {
      const envelope = await this.load(op), day = businessDate(selected, this.clock());
      const entry = envelope.entries.find(e => e.key === entryKey(selected, day));
      if (!entry || entry.expiresAt <= this.clock()) return unavailable();
      await this.highWater(op);
      if (entry.expiresAt <= this.clock() || day !== businessDate(selected, this.clock())) return unavailable();
      this.expires = Math.min(entry.expiresAt, op.leaseEnd); return entry.report;
    }).catch(error => { this.expires = 0; throw error; });
  }
  async revoke(input: SnapshotAuthority): Promise<void> {
    let a: SnapshotAuthority; try { a = authority(input); } catch { return unavailable(); }
    const actor = actorKey(a), writer = this.writers.get(actor);
    // A current/new logout is valid even before that epoch saves anything. Skip
    // only positively old cleanup, never merely an epoch unlike the last writer.
    let current: SnapshotAuthority | null = null;
    try { const value = this.current(); if (value) current = authority(value); } catch { /* cleanup needs only its captured actor */ }
    const sameActor = current && actorKey(current) === actor, currentCleanup = sameActor && current!.epoch === a.epoch;
    const epochs = this.epochs.get(actor) ?? [], oldIndex = epochs.indexOf(a.epoch), writerIndex = writer === undefined ? -1 : epochs.indexOf(writer);
    if (!currentCleanup && writer !== undefined && writer !== a.epoch && oldIndex >= 0 && oldIndex < writerIndex) return;
    this.expires = 0; this.blocked.add(actor); this.generations.set(actor, (this.generations.get(actor) ?? 0) + 1);
    return this.serial(async () => {
      let raw: string | null = null;
      // A read failure must not prevent a still-working durable denial write.
      try { raw = await this.storage.getItem(actor + '/control'); } catch { /* attempt the blocked marker regardless */ }
      const time = this.now(); let highWater = finiteTime(time) ? time : 0;
      try { const v = raw && JSON.parse(raw); if (v && finiteTime(v.highWater)) highWater = Math.max(highWater, v.highWater); } catch { /* preserve denial even for malformed old metadata */ }
      await this.storage.setItem(actor + '/control', JSON.stringify({ version: 1, blocked: true, highWater }));
      await this.storage.removeItem(actor + '/envelope');
    });
  }
}

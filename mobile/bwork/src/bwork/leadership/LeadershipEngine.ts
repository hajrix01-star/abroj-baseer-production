import { accessDenied, LeadershipError } from './types.ts';
import type { LeadershipDependencies, LeadershipIdentity, LeadershipOptions, LeadershipQuery, LeadershipRequest } from './types.ts';
import { id, optionsResponse, query, reportResponse, ROOT } from './validation.ts';
import type { SnapshotAuthority } from './LeadershipSnapshots.ts';

const stamp = (v: LeadershipIdentity) => JSON.stringify([v.origin, v.db, v.uid, v.epoch, [...v.companyIds].sort((a, b) => a - b), v.canView, v.revision]);
const authorityStamp = (v: SnapshotAuthority | LeadershipIdentity) => JSON.stringify([v.origin, v.db, v.uid, [...v.companyIds].sort((a, b) => a - b), v.canView, v.revision]);
/** HTTP remains verified-online-only. Remembered display authority reads local snapshots only. */
export class LeadershipEngine {
  private deps: LeadershipDependencies;
  private scope = ''; private approved: LeadershipOptions | null = null; private revoked = false;
  private reads = new Map<string, AbortController>();
  private generation = 0; private cachedUntil = 0;
  private readWasCached = false; private cachedAuthority = '';
  constructor(deps: LeadershipDependencies) { this.deps = deps; }
  cancelReads(): void { this.generation++; this.reads.forEach(c => c.abort()); this.reads.clear(); }
  clear(): void { this.cancelReads(); this.scope = ''; this.approved = null; this.revoked = false; this.cachedUntil = 0; this.readWasCached = false; this.cachedAuthority = ''; }
  /** Internal presentation lease, not a user-visible update timestamp. */
  get displayLeaseRemainingMs(): number {
    if (!this.readWasCached) return Infinity;
    const authority = this.deps.displayScope?.(), now = (this.deps.now ?? Date.now)();
    return authority && authorityStamp(authority) === this.cachedAuthority && now <= this.cachedUntil
      ? Math.max(0, Math.min(authority.leaseRemainingMs, this.cachedUntil - now)) : 0;
  }
  get displayIsCached(): boolean { return this.readWasCached; }
  private displayIdentity(): SnapshotAuthority {
    const value = this.deps.displayScope?.();
    if (!value?.canView || !(value.leaseRemainingMs > 0) || !this.deps.snapshots) throw new LeadershipError('snapshot_unavailable');
    return value;
  }
  private async revoke(start: LeadershipIdentity, display = this.deps.displayScope?.()): Promise<void> {
    this.cancelReads(); this.approved = null; this.revoked = true; this.cachedUntil = 0;
    // A denial belongs to the original actor even if logout has already cleared display scope.
    const actor = display && authorityStamp(display) === authorityStamp(start) ? display : { ...start, revision: start.revision ?? 0, leaseRemainingMs: 0 };
    await this.deps.snapshots?.revoke(actor).catch(() => undefined);
  }
  private identity(): LeadershipIdentity {
    const v = this.deps.identityScope();
    if (!v?.verified || typeof v.origin !== 'string' || !v.origin || typeof v.db !== 'string' || !v.db || !['number', 'string'].includes(typeof v.epoch)) { this.clear(); throw new LeadershipError('unauthorized'); }
    try { id(v.uid); if (!Array.isArray(v.companyIds) || v.companyIds.length > 1000 || new Set(v.companyIds).size !== v.companyIds.length) throw new Error(); v.companyIds.forEach(id); }
    catch { this.clear(); throw new LeadershipError('forbidden'); }
    if (!v.canView) { this.clear(); throw new LeadershipError('forbidden'); }
    const key = stamp(v); if (this.scope !== key) {
      // A same-authority reconnect verifies options without blanking leased pixels.
      // This never retains a deadline across a company/grant/revision change.
      const retained = this.readWasCached && this.cachedAuthority === authorityStamp(v), until = this.cachedUntil;
      this.clear(); this.scope = key;
      if (retained) { this.readWasCached = true; this.cachedUntil = until; this.cachedAuthority = authorityStamp(v); }
    }
    return { ...v, companyIds: [...v.companyIds] };
  }
  private current(start: LeadershipIdentity): boolean { const now = this.deps.identityScope(); return !!now?.verified && now.canView && stamp(now) === stamp(start); }
  private async fetch<T>(kind: string, start: LeadershipIdentity, request: LeadershipRequest, validate: (value: unknown) => T): Promise<T> {
    const display = this.deps.displayScope?.();
    this.reads.get(kind)?.abort(); const controller = new AbortController(); this.reads.set(kind, controller);
    try {
      const value = await this.deps.transport.request({ ...request, signal: controller.signal });
      if (controller.signal.aborted || this.reads.get(kind) !== controller || !this.current(start)) throw new LeadershipError('stale');
      if (value && typeof value === 'object' && 'error' in value) throw new LeadershipError(String((value as any).error?.code ?? 'server_error'));
      return validate(value);
    } catch (error) {
      if (!this.current(start)) { this.clear(); throw new LeadershipError('stale'); }
      if (controller.signal.aborted || this.reads.get(kind) !== controller) throw new LeadershipError('stale');
      const status = Number((error as any)?.status), code = String((error as any)?.code ?? 'network_error');
      if (accessDenied(error)) { await this.revoke(start, display); if (status === 401 || code === 'unauthorized' || code === 'session') this.deps.onUnauthorized?.(); else this.deps.onForbidden?.(); throw new LeadershipError(status === 401 || code === 'unauthorized' || code === 'session' ? 'unauthorized' : 'forbidden', status); }
      if ([404, 503].includes(status)) throw new LeadershipError('server_update_required', status);
      throw new LeadershipError(['invalid_response', 'response_too_large', 'server_update_required', 'stale'].includes(code) ? code : 'network_error', status);
    } finally { if (this.reads.get(kind) === controller) this.reads.delete(kind); }
  }
  async options(): Promise<LeadershipOptions> {
    const emptyOptions = (): LeadershipOptions => ({ api_version: 2, leadership_version: 2, can_view: true, companies: [], max_companies: 10 });
    if (this.deps.offline?.()) {
      const authority = this.displayIdentity(), ticket = this.generation;
      if (!authority.companyIds.length) { this.approved = emptyOptions(); return this.approved; }
      const result = await this.deps.snapshots!.options(authority);
      const current = this.displayIdentity();
      if (ticket !== this.generation || !this.deps.offline() || authority.epoch !== current.epoch || authorityStamp(authority) !== authorityStamp(current)) throw new LeadershipError('stale');
      this.approved = result; return result;
    }
    const start = this.identity();
    if (!start.companyIds.length) { this.approved = emptyOptions(); return this.approved; }
    const result = await this.fetch('options', start, { method: 'GET', path: `${ROOT}/options` }, value => optionsResponse(value, start));
    if (!result.can_view) { await this.revoke(start); throw new LeadershipError('forbidden', 403); }
    this.approved = result; this.revoked = false; return result;
  }
  async read(input: LeadershipQuery) {
    if (this.deps.offline?.()) {
      const authority = this.displayIdentity(), ticket = this.generation;
      if (!authority.companyIds.length) throw new LeadershipError('snapshot_unavailable');
      this.cachedUntil = 0;
      const result = await this.deps.snapshots!.read(authority, query(input));
      const current = this.displayIdentity();
      if (ticket !== this.generation || !this.deps.offline() || authority.epoch !== current.epoch || authorityStamp(authority) !== authorityStamp(current)) throw new LeadershipError('stale');
      this.cachedUntil = this.deps.snapshots!.displayExpiresAt; this.readWasCached = true; this.cachedAuthority = authorityStamp(authority); return result;
    }
    const start = this.identity(), selected = query(input), options = this.approved;
    if (!start.companyIds.length) throw new LeadershipError('snapshot_unavailable');
    if (this.revoked) throw new LeadershipError('forbidden');
    if (!options) throw new LeadershipError('server_update_required');
    if (selected.companyId === undefined && options.companies.length > options.max_companies) throw new LeadershipError('company_limit');
    if (selected.companyId !== undefined && !options.companies.some(c => c.id === selected.companyId)) throw new LeadershipError('forbidden');
    const result = await this.fetch('report', start, { method: 'GET', path: ROOT, query: { month: selected.month, period: selected.period, ...(selected.date ? { date: selected.date } : {}), ...(selected.companyId ? { company_id: selected.companyId } : {}) } }, value => reportResponse(value, selected, options));
    const authority = this.deps.displayScope?.(), ticket = this.generation;
    if (authority && authorityStamp(authority) === authorityStamp(start)) {
      // Local quota/I/O failure must not hide an authorized current server response.
      await this.deps.snapshots?.save(authority, options, selected, result).catch(() => undefined);
    }
    if (ticket !== this.generation || !this.current(start) || this.deps.offline?.()) throw new LeadershipError('stale');
    this.readWasCached = false;
    return result;
  }
}

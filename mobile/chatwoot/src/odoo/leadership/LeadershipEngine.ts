import { accessDenied, LeadershipError } from './types.ts';
import type { LeadershipDependencies, LeadershipIdentity, LeadershipOptions, LeadershipQuery, LeadershipRequest } from './types.ts';
import { id, optionsResponse, query, reportResponse, ROOT } from './validation.ts';

const stamp = (v: LeadershipIdentity) => JSON.stringify([v.origin, v.db, v.uid, v.epoch, [...v.companyIds].sort((a, b) => a - b), v.canView]);
/** Financial data is connected-only, never persisted or cached by this engine. */
export class LeadershipEngine {
  private deps: LeadershipDependencies;
  private scope = ''; private approved: LeadershipOptions | null = null; private revoked = false;
  private reads = new Map<string, AbortController>();
  constructor(deps: LeadershipDependencies) { this.deps = deps; }
  cancelReads(): void { this.reads.forEach(c => c.abort()); this.reads.clear(); }
  clear(): void { this.cancelReads(); this.scope = ''; this.approved = null; this.revoked = false; }
  private identity(): LeadershipIdentity {
    const v = this.deps.identityScope();
    if (!v?.verified || typeof v.origin !== 'string' || !v.origin || typeof v.db !== 'string' || !v.db || !['number', 'string'].includes(typeof v.epoch)) { this.clear(); throw new LeadershipError('unauthorized'); }
    try { id(v.uid); if (!Array.isArray(v.companyIds) || v.companyIds.length > 1000 || new Set(v.companyIds).size !== v.companyIds.length) throw new Error(); v.companyIds.forEach(id); }
    catch { this.clear(); throw new LeadershipError('forbidden'); }
    if (!v.canView) { this.clear(); throw new LeadershipError('forbidden'); }
    const key = stamp(v); if (this.scope !== key) { this.clear(); this.scope = key; }
    return { ...v, companyIds: [...v.companyIds] };
  }
  private current(start: LeadershipIdentity): boolean { const now = this.deps.identityScope(); return !!now?.verified && now.canView && stamp(now) === stamp(start); }
  private async fetch<T>(kind: string, start: LeadershipIdentity, request: LeadershipRequest, validate: (value: unknown) => T): Promise<T> {
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
      if (accessDenied(error)) { this.cancelReads(); this.approved = null; this.revoked = true; if (status === 401 || code === 'unauthorized' || code === 'session') this.deps.onUnauthorized?.(); else this.deps.onForbidden?.(); throw new LeadershipError(status === 401 || code === 'unauthorized' || code === 'session' ? 'unauthorized' : 'forbidden', status); }
      if ([404, 503].includes(status)) throw new LeadershipError('server_update_required', status);
      throw new LeadershipError(['invalid_response', 'response_too_large', 'server_update_required', 'stale'].includes(code) ? code : 'network_error', status);
    } finally { if (this.reads.get(kind) === controller) this.reads.delete(kind); }
  }
  async options(): Promise<LeadershipOptions> {
    const start = this.identity();
    const result = await this.fetch('options', start, { method: 'GET', path: `${ROOT}/options` }, value => optionsResponse(value, start));
    if (!result.can_view) { this.cancelReads(); this.approved = null; this.revoked = true; throw new LeadershipError('forbidden', 403); }
    this.approved = result; this.revoked = false; return result;
  }
  async read(input: LeadershipQuery) {
    const start = this.identity(), selected = query(input), options = this.approved;
    if (this.revoked) throw new LeadershipError('forbidden');
    if (!options) throw new LeadershipError('server_update_required');
    if (selected.companyId === undefined && options.companies.length > options.max_companies) throw new LeadershipError('company_limit');
    if (selected.companyId !== undefined && !options.companies.some(c => c.id === selected.companyId)) throw new LeadershipError('forbidden');
    return this.fetch('report', start, { method: 'GET', path: ROOT, query: { month: selected.month, period: selected.period, ...(selected.date ? { date: selected.date } : {}), ...(selected.companyId ? { company_id: selected.companyId } : {}) } }, value => reportResponse(value, selected, options));
  }
}

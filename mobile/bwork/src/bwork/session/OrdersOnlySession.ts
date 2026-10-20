import { ChatError, type Bootstrap } from '../core/ChatEngine.ts';

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const positive = (value: unknown): value is number => Number.isInteger(value) && Number(value) > 0 && Number(value) <= 2147483647;
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/** An extension of the application login, never a relaxation of the chat bootstrap. */
export function ordersOnlyBootstrap(raw: unknown, expectedUid: number, database: string): Bootstrap | null {
  if (!record(raw) || !record(raw.permissions)) return null;
  const permissions = raw.permissions;
  if (permissions.chat_view === true) return null;
  if (permissions.chat_view !== false || (permissions.order_view !== true && permissions.task_view !== true && permissions.dashboard_view !== true)) return null;
  if (raw.api_version !== 2 || !positive(expectedUid) || raw.user_id !== expectedUid || raw.database !== database
      || typeof database !== 'string' || !database.trim() || database.length > 200
      || !Array.isArray(raw.company_ids) || !raw.company_ids.length || raw.company_ids.length > 1000
      || !raw.company_ids.every(positive) || new Set(raw.company_ids).size !== raw.company_ids.length
      || typeof raw.csrf_token !== 'string' || !raw.csrf_token.trim() || raw.csrf_token.length > 1024
      || typeof permissions.chat_send !== 'boolean'
      || (permissions.order_view === true && ['order_create', 'order_receive'].some(key => typeof permissions[key] !== 'boolean'))
      || (permissions.task_view === true && typeof permissions.task_manage !== 'boolean')
      || Object.values(permissions).some(v => typeof v !== 'boolean' && !(Number.isSafeInteger(v) && Number(v) >= 0))) {
    throw new ChatError('identity_mismatch', 403);
  }
  const value: Bootstrap = {
    api_version: 2, database, user_id: expectedUid, company_ids: [...raw.company_ids], csrf_token: raw.csrf_token,
    permissions: clone(raw.permissions) as Bootstrap['permissions'],
  };
  // Profile is optional at the server. It cannot provide company authority.
  const profile = raw.profile;
  if (record(profile) && typeof profile.name === 'string' && profile.name.length <= 512 && Array.isArray(profile.companies)) {
    const companies = profile.companies.filter((row: unknown) => record(row) && positive(row.id)
      && value.company_ids.includes(row.id) && typeof row.name === 'string' && row.name.length <= 512)
      .map((row: any) => ({ id: row.id, name: row.name,
        ...(typeof row.name_ar === 'string' ? { name_ar: row.name_ar.slice(0, 512) } : {}),
        ...(typeof row.name_en === 'string' ? { name_en: row.name_en.slice(0, 512) } : {}),
      }));
    value.profile = { name: profile.name, companies };
  }
  return value;
}

export interface OrdersOnlySnapshot { identity: Bootstrap | null; generation: number; verified: boolean; revision: number }

/** Memory-only application scope. A locked identity cannot render data or authorize a request. */
export class OrdersOnlySession {
  private state: OrdersOnlySnapshot = { identity: null, generation: -1, verified: false, revision: 0 };
  private listeners = new Set<() => void>();
  snapshot = (): OrdersOnlySnapshot => clone(this.state);
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private changed() { this.state.revision++; for (const listener of this.listeners) listener(); }
  lock() { if (this.state.identity && this.state.verified) { this.state.verified = false; this.changed(); } }
  clear(expectedGeneration: number) {
    if (this.state.identity && this.state.generation !== expectedGeneration) return false;
    this.state = { identity: null, generation: -1, verified: false, revision: this.state.revision };
    this.changed(); return true;
  }
  publish(identity: Bootstrap, acceptedGeneration: number, currentGeneration: number) {
    if (acceptedGeneration !== currentGeneration || identity.permissions.chat_view !== false
        || (identity.permissions.order_view !== true && identity.permissions.task_view !== true && identity.permissions.dashboard_view !== true)) throw new ChatError('stale_session');
    this.state = { identity: clone(identity), generation: acceptedGeneration, verified: true, revision: this.state.revision };
    this.changed();
  }
}

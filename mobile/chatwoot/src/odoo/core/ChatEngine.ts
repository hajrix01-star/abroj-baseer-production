/** Odoo-owned chat domain. No native dependencies, credentials or telemetry. */
import type { LoginStage, NetworkFailure } from './loginDiagnostics';
export interface Storage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
  getAllKeys(): Promise<readonly string[]>;
}
export interface Request {
  method: 'GET' | 'POST'; path: string; json?: unknown;
  form?: Record<string, string>; signal?: AbortSignal;
}
export interface Transport { request(request: Request): Promise<unknown>; cancelAll?(): void }
export interface Policy { api_version: 2; company_id: number; direct_enabled: boolean; can_manage: boolean }
export interface Bootstrap {
  api_version: 2; database: string; user_id: number; company_ids: number[];
  current_company_id?: number; csrf_token?: string;
  permissions: Record<string, boolean | number>; mobile_policy?: Policy[];
  profile?: { name: string; companies: { id: number; name: string; name_ar?: string; name_en?: string }[] };
}
export interface Room {
  id: number; company_id: number; membership_id: number; name: string;
  is_group: boolean; is_group_admin?: boolean; mobile_direct?: boolean;
  last_message_id?: number; last_message_preview?: string; unread_count?: number;
  invoice_policy?: string; invoice_policy_version?: number;
}
export interface Message {
  id: number; author_user_id: number; author_name: string; text: string; created_at: string;
  delivery_state?: string; media?: Record<string, unknown>; reply?: Record<string, unknown>;
}
export interface History { api_version: 2; messages: Message[]; next_before_id: number | null }
export interface Pending {
  client_uuid: string; room_id: number; company_id: number; membership_id: number;
  text: string; reply_to_message_id?: number; created_at: number;
  state: 'queued' | 'sending' | 'unknown' | 'failed'; attempts: number; next_attempt_at: number;
  error?: string;
  attachment?: Attachment;
}
export interface Attachment {
  uri: string; name: string; mime: string; size: number; sha256: string;
  kind: 'image' | 'file' | 'audio'; upload_uuid: string; media_id?: number; policy_version?: number;
}
export interface ReceiptAck {
  api_version: 2; message_id: number; delivered_at: string; read_at: string | null;
  unread_count: number; last_message_id: number; replayed: boolean;
}
export interface Options {
  transport: Transport; storage: Storage; origin: string; database: string; uuid?: () => string; now?: () => number;
  upload?: (room: Room, attachment: Attachment, csrfToken: string, signal: AbortSignal) => Promise<{ media_id: number; policy_version?: number }>;
  removeAttachment?: (attachment: Attachment) => Promise<void>;
}
export class ChatError extends Error {
  readonly code: string;
  readonly status: number;
  loginStage?: LoginStage;
  networkFailure?: NetworkFailure;
  sessionTrace?: string;
  constructor(code: string, status = 0) { super(code); this.name = 'ChatError'; this.code = code; this.status = status; }
}
const TTL = 24 * 60 * 60 * 1000;
/** Conservative AsyncStorage/heap quotas. Eviction never touches durable outbox/ACKs. */
export const HISTORY_LIMITS = Object.freeze({ roomMessages: 500, roomBytes: 512 * 1024, accountBytes: 2 * 1024 * 1024, accountMessages: 2000 });
const id = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const object = (v: unknown): Record<string, any> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new ChatError('invalid_response');
  return v as Record<string, any>;
};
const denied = (e: unknown) => e instanceof ChatError && (e.status === 401 || e.status === 403 || ['forbidden', 'identity_mismatch', 'membership_changed', 'session_expired'].includes(e.code));
const codeOf = (e: unknown) => e instanceof ChatError ? e.code : 'connection_failed';

export class ChatEngine {
  private readonly transport: Transport;
  private readonly storage: Storage;
  private readonly database: string;
  private readonly root: string;
  private readonly uuid: () => string;
  private readonly now: () => number;
  private readonly upload?: Options['upload'];
  private readonly removeAttachment?: Options['removeAttachment'];
  private epoch = 0;
  private abort = new AbortController();
  private work: Promise<unknown> = Promise.resolve();
  private lifecycle: Promise<unknown> = Promise.resolve();
  private pumping: Promise<void> | null = null;
  private refreshing: Promise<Bootstrap> | null = null;
  private account: Bootstrap | null = null;
  private roomRows: Room[] = [];
  private histories = new Map<string, History>();
  private queue = new Map<string, Pending>();
  private remembered = false;
  private verifiedAt = 0;
  private changeCursor = 0;
  private disconnected = true;
  private failures = 0;
  private state = 'signed_out';
  private accessLocked = false;
  private receiptWork: Promise<unknown> = Promise.resolve();
  private receiptPumps = new Map<string, Promise<ReceiptAck | null>>();
  private receiptAcks = new Map<string, { delivered?: ReceiptAck; read?: ReceiptAck; unavailable?: boolean }>();

  constructor(options: Options) {
    const origin = new URL(options.origin);
    if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new ChatError('https_origin_required');
    if (!options.database.trim()) throw new ChatError('database_required');
    this.transport = options.transport; this.storage = options.storage; this.database = options.database;
    this.root = `odoo-chat/v1/${encodeURIComponent(origin.origin)}/${encodeURIComponent(options.database)}/`;
    this.uuid = options.uuid ?? (() => globalThis.crypto.randomUUID()); this.now = options.now ?? Date.now;
    this.upload = options.upload; this.removeAttachment = options.removeAttachment;
  }
  get identity(): Bootstrap | null { return this.account && !this.accessLocked ? copy(this.account) : null; }
  get offline(): boolean { return this.disconnected; }
  get status(): string { return this.state; }
  get backoffMs(): number { return this.failures ? [5000, 10000, 20000, 30000][Math.min(this.failures - 1, 3)]! : 2000; }
  markDisconnected(): void { this.disconnected = true; if (this.account) this.state = 'offline'; }
  private fence(e: number) { if (e !== this.epoch) throw new ChatError('stale_session'); }
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const result = this.work.then(fn, fn); this.work = result.catch(() => undefined); return result;
  }
  private lifecycleRun<T>(fn: () => Promise<T>): Promise<T> {
    const result = this.lifecycle.then(fn, fn); this.lifecycle = result.catch(() => undefined); return result;
  }
  private reset(): number {
    this.epoch++; this.abort.abort(); this.transport.cancelAll?.(); this.abort = new AbortController();
    this.account = null; this.roomRows = []; this.histories.clear(); this.queue.clear();
    this.remembered = false; this.verifiedAt = 0; this.changeCursor = 0; this.disconnected = true;
    this.refreshing = null; this.pumping = null; this.state = 'signed_out';
    this.accessLocked = false;
    this.receiptWork = Promise.resolve(); this.receiptPumps.clear(); this.receiptAcks.clear();
    return this.epoch;
  }
  private prefix(uid = this.account?.user_id): string {
    if (!id(uid)) throw new ChatError('login_required');
    return `${this.root}u/${uid}/`;
  }
  private scope(room: Room): string { return `${this.prefix()}c/${room.company_id}/r/${room.id}/m/${room.membership_id}/`; }
  private async removeStoredAttachments(entries: [string, string][]) {
    const attachments = new Map<string, Attachment>();
    for (const [key, value] of entries) if (key.includes('/outbox/') || key.includes('/ack/')) {
      try { const saved = JSON.parse(value); if (saved.attachment?.uri) attachments.set(saved.attachment.uri, saved.attachment); } catch { /* Invalid local entries contain no trusted stage reference. */ }
    }
    for (const attachment of attachments.values()) {
      try { await this.removeAttachment?.(copy(attachment)); } catch { /* Revoked bytes remain inaccessible; native startup cleanup retries. */ }
    }
  }
  private async purge(prefix: string, removeFiles = true) {
    const keys = await this.storage.getAllKeys();
    const removed: [string, string][] = [];
    for (const key of keys) if (key.startsWith(prefix)) {
      if (removeFiles && (key.includes('/outbox/') || key.includes('/ack/'))) {
        const value = await this.storage.getItem(key); if (value !== null) removed.push([key, value]);
      }
      await this.storage.removeItem(key);
    }
    if (removeFiles) await this.removeStoredAttachments(removed);
  }
  private async request(path: string, e: number, body?: unknown, json = false, rawForm?: Record<string, string>): Promise<any> {
    this.fence(e);
    const form = rawForm ?? (body === undefined || json ? undefined : { csrf_token: this.account?.csrf_token ?? '', payload: JSON.stringify(body) });
    let result: unknown;
    try { result = await this.transport.request({ method: body === undefined && !rawForm ? 'GET' : 'POST', path, ...(json ? { json: body } : { form }), signal: this.abort.signal }); }
    catch (error) {
      this.fence(e);
      if (error instanceof ChatError) throw error;
      const raw = error as { code?: string; status?: number };
      if (raw?.status) throw new ChatError(raw.code ?? 'request_failed', raw.status);
      throw new ChatError('connection_failed');
    }
    this.fence(e);
    const value = object(result);
    if (value.error?.data?.name === 'odoo.http.SessionExpiredException') throw new ChatError('session_expired', 401);
    if (value.error) throw new ChatError(value.error.code ?? 'request_failed', Number(value.error.status ?? 0));
    return value;
  }
  private async closeSession(e: number, requestId: number) {
    try { await this.request('/web/session/destroy', e, { jsonrpc: '2.0', method: 'call', params: {}, id: requestId }, true); }
    catch (error) {
      // Only the exact no-session result proves there is no previous session.
      if (!(error instanceof ChatError && error.code === 'session_expired' && error.status === 401)) throw error;
    }
  }
  private bootstrap(raw: unknown, uid: number): Bootstrap {
    const b = object(raw);
    if (b.api_version !== 2 || b.user_id !== uid || b.database !== this.database || !id(uid) || !Array.isArray(b.company_ids) || !b.company_ids.every(id) || !b.company_ids.length || typeof b.csrf_token !== 'string' || !b.csrf_token || !b.permissions || b.permissions.chat_view !== true) throw new ChatError('identity_mismatch', 403);
    return b as Bootstrap;
  }
  private async persistIdentity(e: number) {
    this.fence(e);
    if (!this.account) return;
    if (this.remembered) {
      const { csrf_token: _csrf, ...safe } = this.account;
      await this.storage.setItem(`${this.root}identity`, JSON.stringify({ bootstrap: safe, verifiedAt: this.verifiedAt }));
    }
    this.fence(e);
    // The bounded membership map is recovery metadata for durable operations;
    // without a remembered identity it cannot enable offline display.
    await this.storage.setItem(`${this.prefix()}rooms`, JSON.stringify(this.roomRows));
  }
  private async invalidate(e: number) {
    this.fence(e); const root = this.root;
    this.reset();
    await this.serial(() => this.purge(root));
  }
  private async loadStoredAccount(e: number) {
    this.fence(e);
    const rooms = JSON.parse(await this.storage.getItem(`${this.prefix()}rooms`) ?? '[]'); this.fence(e);
    // Cached company access can be older than today's bootstrap. Load only
    // structurally valid scopes, then reconcile every scope with /rooms.
    if (!Array.isArray(rooms) || rooms.length > 100) throw new ChatError('invalid_rooms');
    this.roomRows = rooms.filter(r => id(r.id) && id(r.company_id) && id(r.membership_id) && typeof r.name === 'string');
    let order: string[] = [];
    try { const value = JSON.parse(await this.storage.getItem(`${this.prefix()}history-lru`) ?? '[]'); if (Array.isArray(value)) order = value.filter(key => typeof key === 'string').slice(-100); } catch { /* Order is a hint, never an identity source. */ }
    const cacheRooms = [...this.roomRows].sort((a, b) => order.indexOf(this.scope(a)) - order.indexOf(this.scope(b)));
    for (const room of cacheRooms) {
      const key = this.scope(room);
      try {
        const history = await this.storage.getItem(`${key}history`); this.fence(e);
        if (history) await this.cacheHistory(room, this.validHistory(JSON.parse(history)), e);
      } catch {
        // CursorWindow can reject a legacy oversized value before JSON parsing.
        // Cache failure must never turn into deletion of unACKed operations.
        this.fence(e); this.histories.delete(key);
        try { await this.storage.removeItem(`${key}history`); }
        catch { throw new ChatError('history_storage_unavailable'); }
      }
    }
    const keys = await this.storage.getAllKeys(); this.fence(e);
    const retainedHistory = new Set([...this.histories.keys()].map(scope => `${scope}history`));
    for (const key of keys) if (key.startsWith(this.prefix()) && key.endsWith('/history') && !retainedHistory.has(key)) {
      try { await this.storage.removeItem(key); } catch { throw new ChatError('history_storage_unavailable'); }
    }
    for (const key of keys.filter(k => k.startsWith(this.prefix()) && k.includes('/outbox/')).sort()) {
      const value = await this.storage.getItem(key); this.fence(e);
      if (!value) continue;
      const p = JSON.parse(value) as Pending;
      const room = this.roomRows.find(r => r.id === p.room_id && r.company_id === p.company_id && r.membership_id === p.membership_id);
      if (!room || !uuidPattern.test(p.client_uuid) || typeof p.text !== 'string' || key !== `${this.scope(room)}outbox/${p.client_uuid}` || this.queue.size >= 100) { await this.storage.removeItem(key); await this.removeStoredAttachments([[key, value]]); continue; }
      if (p.attachment) this.validateAttachment(p.attachment);
      if (p.state === 'sending') { p.state = 'unknown'; await this.storage.setItem(key, JSON.stringify(p)); }
      this.queue.set(p.client_uuid, p);
    }
    for (const key of keys.filter(k => k.startsWith(this.prefix()) && k.includes('/ack/'))) {
      const value = await this.storage.getItem(key); this.fence(e);
      if (!value) continue;
      const ack = object(JSON.parse(value));
      if (id(ack.message_id) && uuidPattern.test(ack.client_uuid)) {
        const outboxKey = key.replace('/ack/', '/outbox/');
        await this.storage.removeItem(outboxKey); this.queue.delete(ack.client_uuid);
        await this.removeStoredAttachments([[key, value]]); await this.storage.removeItem(key);
      }
    }
  }
  async login(login: string, password: string, remember: boolean): Promise<Bootstrap> {
    const e = this.reset(); this.state = 'connecting'; this.accessLocked = true;
    return this.lifecycleRun(async () => {
      this.fence(e);
      // Keep unACKed operations durable through network/password/MFA failures.
      // A durable lock prevents offline restore until the same uid/db is proven.
      const prior = await this.serial(async () => {
        this.fence(e); let uid: number | undefined; let verifiedAt = 0;
        try {
          const raw = await this.storage.getItem(`${this.root}identity`);
          const saved = raw ? object(JSON.parse(raw)) : null;
          if (id(saved?.bootstrap?.user_id)) { uid = saved!.bootstrap.user_id; verifiedAt = Number(saved!.verifiedAt) || 0; }
          if (!uid) { const owner = await this.storage.getItem(`${this.root}owner`); const value = owner ? JSON.parse(owner) : null; if (id(value?.user_id)) uid = value.user_id; }
        } catch { /* Corrupt recovery cannot supply an authenticated identity. */ }
        this.fence(e); await this.storage.setItem(`${this.root}authentication-required`, 'true');
        return { uid, verifiedAt };
      }); this.fence(e);
      let bootstrapRequested = false;
      let loginStage: LoginStage = 'session_close';
      try {
        // The native cookie jar is shared by this origin. A failed close blocks switching.
        await this.closeSession(e, 1);
        loginStage = 'authenticate';
        const auth = await this.request('/web/session/authenticate', e, { jsonrpc: '2.0', method: 'call', params: { db: this.database, login, password }, id: 2 }, true);
        const result = object(auth.result);
        if (!id(result.uid)) throw new ChatError(result.uid === null ? 'mfa_required' : 'login_failed');
        if (result.db && result.db !== this.database) throw new ChatError('identity_mismatch', 403);
        loginStage = 'storage';
        await this.serial(async () => {
          this.fence(e);
          if (prior.uid !== result.uid) { await this.purge(this.root); await this.storage.setItem(`${this.root}authentication-required`, 'true'); }
          await this.storage.setItem(`${this.root}owner`, JSON.stringify({ user_id: result.uid })); this.fence(e);
        });
        bootstrapRequested = true;
        loginStage = 'bootstrap';
        const bootstrap = this.bootstrap(await this.request('/bchat/api/v2/bootstrap', e), result.uid);
        this.account = bootstrap; this.remembered = remember; this.verifiedAt = prior.uid === result.uid ? prior.verifiedAt : 0;
        if (prior.uid === result.uid) await this.serial(() => this.loadStoredAccount(e));
        await this.applyBootstrap(bootstrap, e);
        loginStage = 'rooms';
        await this.loadRooms(e);
        this.verifiedAt = this.now();
        loginStage = 'storage';
        await this.serial(async () => {
          this.fence(e); await this.persistIdentity(e);
          if (!remember) await this.storage.removeItem(`${this.root}identity`);
          await this.storage.removeItem(`${this.root}authentication-required`); this.fence(e);
        });
        this.accessLocked = false; this.disconnected = false; this.state = 'ready'; this.failures = 0;
        return copy(bootstrap);
      } catch (error) {
        if (error instanceof ChatError) error.loginStage = loginStage;
        if (e === this.epoch) {
          try { await this.closeSession(e, 3); } catch { /* The next login must close successfully. */ }
          if (error instanceof ChatError && error.code === 'identity_mismatch' || bootstrapRequested && denied(error)) await this.invalidate(e);
          else {
            // Preserve current scoped recovery, including any authoritative
            // revocations already applied by bootstrap. Never restore an old snapshot.
            this.account = null; this.roomRows = []; this.histories.clear(); this.queue.clear(); this.remembered = false;
            this.verifiedAt = 0; this.disconnected = true; this.accessLocked = true; this.state = 'authentication_required';
          }
        }
        throw error;
      }
    });
  }
  async restoreOffline(): Promise<boolean> {
    const e = this.reset();
    return this.serial(async () => {
      if (await this.storage.getItem(`${this.root}authentication-required`)) { this.fence(e); this.accessLocked = true; this.state = 'authentication_required'; return false; }
      const raw = await this.storage.getItem(`${this.root}identity`); this.fence(e);
      if (!raw) return false;
      try {
        const saved = object(JSON.parse(raw)); const b = object(saved.bootstrap);
        if (b.database !== this.database || b.api_version !== 2 || !id(b.user_id) || !Array.isArray(b.company_ids) || !b.company_ids.every(id) || b.permissions?.chat_view !== true || !Number.isFinite(saved.verifiedAt) || this.now() < saved.verifiedAt) throw new ChatError('invalid_offline_identity');
        if (this.now() - saved.verifiedAt > TTL) {
          // Expired reads require login, but cache age must not destroy unsent work.
          for (const key of await this.storage.getAllKeys()) if (key.startsWith(this.root) && key.endsWith('/history')) await this.storage.removeItem(key);
          this.state = 'offline_expired'; return false;
        }
        this.account = b as Bootstrap; this.verifiedAt = saved.verifiedAt; this.remembered = true;
        await this.loadStoredAccount(e); this.roomRows = this.validRooms(this.roomRows);
        this.state = 'offline'; return true;
      } catch (error) {
        this.fence(e); this.account = null; this.roomRows = []; this.histories.clear(); this.queue.clear();
        if (error instanceof ChatError && error.code === 'history_storage_unavailable') {
          this.accessLocked = true; this.state = 'authentication_required';
          await this.storage.setItem(`${this.root}authentication-required`, 'true'); return false;
        }
        await this.purge(this.root); this.state = 'signed_out'; return false;
      }
    });
  }
  async logout(): Promise<void> {
    const e = this.reset();
    await this.serial(() => this.purge(this.root));
    return this.lifecycleRun(async () => {
      this.fence(e);
      try { await this.closeSession(e, 4); }
      catch (error) { this.fence(e); this.state = 'logout_pending'; throw error; }
    });
  }
  private validRooms(raw: unknown): Room[] {
    if (!Array.isArray(raw) || raw.length > 100) throw new ChatError('invalid_rooms');
    const seen = new Set<number>();
    return raw.map(value => {
      const r = object(value);
      if (!id(r.id) || !id(r.company_id) || !id(r.membership_id) || typeof r.name !== 'string' || !this.account?.company_ids.includes(r.company_id) || seen.has(r.id)) throw new ChatError('invalid_rooms');
      seen.add(r.id); return r as Room;
    });
  }
  private async applyBootstrap(bootstrap: Bootstrap, e: number): Promise<void> {
    this.fence(e); this.account = bootstrap;
    const revokedScopes = new Set<string>(); const removedPending = new Map<string, Pending>();
    const stripMedia = new Set<string>();
    const reconcileMemory = () => {
      this.fence(e);
      for (const old of this.roomRows) if (!bootstrap.company_ids.includes(old.company_id)) {
        const key = this.scope(old); revokedScopes.add(key); this.histories.delete(key);
      }
      this.roomRows = this.roomRows.filter(room => bootstrap.company_ids.includes(room.company_id));
      for (const [uuid, pending] of this.queue) {
        const room = this.roomRows.find(row => row.id === pending.room_id && row.membership_id === pending.membership_id && row.company_id === pending.company_id);
        const directDisabled = room?.mobile_direct && !bootstrap.mobile_policy?.find(policy => policy.company_id === room.company_id)?.direct_enabled;
        if (!bootstrap.company_ids.includes(pending.company_id) || bootstrap.permissions.chat_send !== true || pending.attachment && bootstrap.permissions.media !== true || directDisabled) {
          removedPending.set(uuid, pending); this.queue.delete(uuid);
        }
      }
      if (bootstrap.permissions.media !== true) for (const [key, history] of this.histories) {
        const messages = history.messages.map(message => { const { media: _media, ...textOnly } = message; return textOnly; });
        this.histories.set(key, { ...history, messages }); stripMedia.add(key);
      }
    };
    // Restrict visible memory before waiting behind any pending disk operation.
    reconcileMemory();
    await this.serial(async () => {
      // An enqueue already holding the disk mutex may have completed meanwhile.
      reconcileMemory();
      for (const scope of revokedScopes) await this.purge(scope);
      const companyPrefixes = new Set<string>();
      for (const key of await this.storage.getAllKeys()) if (key.startsWith(this.prefix())) {
        const match = /^c\/(\d+)\//.exec(key.slice(this.prefix().length));
        if (match && !bootstrap.company_ids.includes(Number(match[1]))) companyPrefixes.add(`${this.prefix()}c/${match[1]}/`);
      }
      for (const prefix of companyPrefixes) await this.purge(prefix);
      for (const [uuid, pending] of removedPending) {
        const key = `${this.prefix()}c/${pending.company_id}/r/${pending.room_id}/m/${pending.membership_id}/outbox/${uuid}`;
        await this.storage.removeItem(key); await this.removeStoredAttachments([[key, JSON.stringify(pending)]]);
      }
      if (this.remembered) for (const key of stripMedia) {
        const history = this.histories.get(key); if (history) await this.storage.setItem(`${key}history`, JSON.stringify(history));
      }
      this.fence(e); await this.persistIdentity(e);
    });
  }
  private async loadRooms(e: number) {
    const result = await this.request('/bchat/api/v2/rooms', e);
    const rooms = this.validRooms(result.rooms);
    await this.serial(async () => {
      this.fence(e);
      for (const old of this.roomRows) {
        if (!rooms.some(r => r.id === old.id && r.company_id === old.company_id && r.membership_id === old.membership_id)) await this.dropRoom(old, e);
      }
      this.fence(e); this.roomRows = rooms;
      for (const [uuid, p] of this.queue) {
        const room = rooms.find(r => r.id === p.room_id);
        const directDisabled = room?.mobile_direct && !this.account?.mobile_policy?.find(policy => policy.company_id === room.company_id)?.direct_enabled;
        const mediaRevoked = p.attachment && this.account?.permissions.media !== true;
        if (this.account?.permissions.chat_send !== true || directDisabled || mediaRevoked) {
          if (room) await this.storage.removeItem(`${this.scope(room)}outbox/${uuid}`);
          this.queue.delete(uuid);
          if (p.attachment) await this.removeStoredAttachments([[`${this.prefix()}outbox/${uuid}`, JSON.stringify(p)]]);
        }
      }
      await this.persistIdentity(e);
    });
  }
  private async dropRoom(room: Room, e: number) {
    this.fence(e); const scope = this.scope(room);
    this.histories.delete(scope); this.roomRows = this.roomRows.filter(r => !(r.id === room.id && r.company_id === room.company_id && r.membership_id === room.membership_id));
    for (const [key, p] of this.queue) if (p.room_id === room.id && p.company_id === room.company_id && p.membership_id === room.membership_id) this.queue.delete(key);
    for (const key of this.receiptAcks.keys()) if (key.startsWith(scope)) this.receiptAcks.delete(key);
    await this.purge(scope); this.fence(e);
  }
  async refresh(): Promise<Bootstrap> {
    if (this.refreshing) return this.refreshing;
    const e = this.epoch;
    // An expired offline lease blocks display, not online identity verification.
    if (!this.account || this.accessLocked) throw new ChatError('login_required');
    const uid = this.account.user_id;
    const run = (async () => {
      try {
        const bootstrap = this.bootstrap(await this.request('/bchat/api/v2/bootstrap', e), uid);
        await this.applyBootstrap(bootstrap, e);
        await this.loadRooms(e);
        const changes = await this.request(`/bchat/api/v2/changes?after=${this.changeCursor}&limit=100&permissions_version=1`, e);
        if (changes.api_version !== 2 || !Array.isArray(changes.changes) || !Number.isSafeInteger(changes.next_after)) throw new ChatError('invalid_changes');
        const changedRooms = new Set<number>();
        for (const change of changes.changes) {
          if (change.kind === 'revoked') {
            const room = this.roomRows.find(r => r.id === change.room_id);
            if (room) await this.serial(() => this.dropRoom(room, e));
          } else if (['message', 'receipt', 'room'].includes(change.kind)) changedRooms.add(change.room_id);
        }
        if (changes.reset_required) for (const room of this.roomRows) changedRooms.add(room.id);
        for (const roomId of changedRooms) {
          const room = this.roomRows.find(r => r.id === roomId);
          if (room && this.histories.has(this.scope(room))) await this.readHistory(room, undefined, e);
        }
        this.changeCursor = changes.reset_required ? changes.watermark : changes.next_after;
        this.fence(e); this.verifiedAt = this.now(); await this.serial(() => this.persistIdentity(e));
        this.disconnected = false; this.state = 'ready'; this.failures = 0;
        return copy(bootstrap);
      } catch (error) {
        if (e === this.epoch && denied(error)) await this.invalidate(e);
        else if (e === this.epoch) { this.disconnected = true; this.state = 'offline'; this.failures++; }
        throw error;
      }
    })();
    this.refreshing = run;
    try { return await run; } finally { if (this.refreshing === run) this.refreshing = null; }
  }
  private requireIdentity(): Bootstrap {
    if (!this.account || this.accessLocked) throw new ChatError('login_required');
    if (this.disconnected && (this.now() < this.verifiedAt || this.now() - this.verifiedAt > TTL)) {
      this.roomRows = []; this.histories.clear(); this.state = 'offline_expired'; throw new ChatError('offline_expired');
    }
    return this.account;
  }
  private room(value: Room | number): Room {
    this.requireIdentity(); const room = this.roomRows.find(r => r.id === (typeof value === 'number' ? value : value.id));
    if (!room || !this.account?.company_ids.includes(room.company_id) || (typeof value !== 'number' && (room.membership_id !== value.membership_id || room.company_id !== value.company_id))) throw new ChatError('room_unavailable', 403);
    return room;
  }
  rooms(): Room[] { const account = this.requireIdentity(); return copy(this.roomRows.filter(room => account.company_ids.includes(room.company_id))); }
  private validHistory(raw: unknown): History {
    const h = object(raw);
    if (h.api_version !== 2 || !Array.isArray(h.messages) || h.messages.some((m: any) => !id(m.id) || !id(m.author_user_id) || typeof m.text !== 'string') || (h.next_before_id !== null && !id(h.next_before_id))) throw new ChatError('invalid_history');
    return { api_version: 2, messages: h.messages.slice(-HISTORY_LIMITS.roomMessages), next_before_id: h.next_before_id };
  }
  private fitHistory(history: History): { history: History; json: string; bytes: number } {
    const encoder = new TextEncoder();
    const base: History = { api_version: 2, messages: [], next_before_id: history.next_before_id };
    let bytes = encoder.encode(JSON.stringify(base)).length;
    const newest: Message[] = [];
    for (let index = history.messages.length - 1; index >= 0 && newest.length < HISTORY_LIMITS.roomMessages; index--) {
      const message = history.messages[index]!;
      const additional = encoder.encode(JSON.stringify(message)).length + (newest.length ? 1 : 0);
      if (bytes + additional > HISTORY_LIMITS.roomBytes) {
        if (!newest.length) throw new ChatError('history_message_too_large');
        break;
      }
      bytes += additional; newest.push(message);
    }
    base.messages = newest.reverse(); const json = JSON.stringify(base);
    return { history: base, json, bytes: encoder.encode(json).length };
  }
  private historyUsage(): { bytes: number; messages: number } {
    let bytes = 0; let messages = 0;
    for (const history of this.histories.values()) { bytes += new TextEncoder().encode(JSON.stringify(history)).length; messages += history.messages.length; }
    return { bytes, messages };
  }
  /** Called under the storage mutex, both on restore and network history writes. */
  private async cacheHistory(room: Room, history: History, e: number): Promise<void> {
    this.fence(e); const key = this.scope(room); const fitted = this.fitHistory(history);
    this.histories.delete(key); this.histories.set(key, fitted.history);
    const evicted: string[] = [];
    let usage = this.historyUsage();
    while (usage.bytes > HISTORY_LIMITS.accountBytes || usage.messages > HISTORY_LIMITS.accountMessages) {
      const oldest = this.histories.keys().next().value!;
      this.histories.delete(oldest); evicted.push(oldest); usage = this.historyUsage();
    }
    // Reclaim old history first, keeping even transient disk usage bounded.
    for (const scope of evicted) { this.fence(e); await this.storage.removeItem(`${scope}history`); }
    this.fence(e);
    if (this.remembered) await this.storage.setItem(`${key}history`, fitted.json);
    else await this.storage.removeItem(`${key}history`);
    this.fence(e); await this.storage.setItem(`${this.prefix()}history-lru`, JSON.stringify([...this.histories.keys()]));
  }
  async history(value: Room | number, beforeId?: number): Promise<History> {
    const room = this.room(value); const e = this.epoch;
    if (this.disconnected) return this.serial(async () => {
      this.fence(e); this.room(room); const key = this.scope(room); const saved = this.histories.get(key);
      if (saved) { this.histories.delete(key); this.histories.set(key, saved); await this.storage.setItem(`${this.prefix()}history-lru`, JSON.stringify([...this.histories.keys()])); this.fence(e); }
      return copy(saved ?? { api_version: 2, messages: [], next_before_id: null });
    });
    return this.readHistory(room, beforeId, e);
  }
  private async readHistory(room: Room, beforeId: number | undefined, e: number): Promise<History> {
    if (beforeId !== undefined && !id(beforeId)) throw new ChatError('invalid_before_id');
    try {
      const page = this.validHistory(await this.request(`/bchat/api/v2/rooms/${room.id}/messages${beforeId ? `?before_id=${beforeId}` : ''}`, e));
      await this.serial(async () => {
        this.fence(e); this.room(room);
        const key = this.scope(room); const old = this.histories.get(key);
        const messages = new Map<number, Message>();
        for (const m of old?.messages ?? []) messages.set(m.id, m);
        for (const m of page.messages) messages.set(m.id, m);
        const merged: History = { api_version: 2, messages: [...messages.values()].sort((a, b) => a.id - b.id).slice(-HISTORY_LIMITS.roomMessages), next_before_id: beforeId || !old ? page.next_before_id : old.next_before_id };
        await this.cacheHistory(room, merged, e);
      });
      return copy(this.histories.get(this.scope(room))!);
    } catch (error) {
      if (e === this.epoch && error instanceof ChatError && error.status === 401) await this.invalidate(e);
      else if (e === this.epoch && denied(error)) await this.serial(async () => { await this.dropRoom(room, e); await this.persistIdentity(e); });
      else if (e === this.epoch && (!(error instanceof ChatError) || !error.status)) { this.disconnected = true; this.failures++; }
      throw error;
    }
  }
  pending(value?: Room | number): Pending[] {
    const account = this.requireIdentity(); const room = value === undefined ? null : this.room(value);
    return copy([...this.queue.values()].filter(p => account.company_ids.includes(p.company_id)
      && this.roomRows.some(member => member.id === p.room_id && member.company_id === p.company_id && member.membership_id === p.membership_id)
      && (!p.attachment || account.permissions.media === true) && (!room || p.room_id === room.id)).sort((a, b) => a.created_at - b.created_at));
  }
  async acknowledge(value: Room | number, messageId: number, kind: 'read' | 'delivered'): Promise<ReceiptAck | null> {
    const room = this.room(value); const account = this.requireIdentity(); const e = this.epoch;
    if (!id(messageId) || !['read', 'delivered'].includes(kind)) throw new ChatError('invalid_receipt');
    const checkMessage = () => {
      this.fence(e); this.room(room);
      const message = this.histories.get(this.scope(room))?.messages.find(row => row.id === messageId);
      if (!message) throw new ChatError('message_unavailable', 403);
      return message.author_user_id !== this.account?.user_id;
    };
    if (!checkMessage() || this.disconnected) return null;
    const key = `${this.scope(room)}receipt/${messageId}`; const pumpKey = `${key}/${kind}`;
    const cached = () => {
      const saved = this.receiptAcks.get(key);
      if (saved?.unavailable) return null;
      return saved?.read ?? (kind === 'delivered' ? saved?.delivered : undefined);
    };
    const previous = cached(); if (previous !== undefined) return previous ? copy(previous) : null;
    const running = this.receiptPumps.get(pumpKey); if (running) return running;
    if (this.receiptPumps.size >= 100) throw new ChatError('receipt_busy');
    const run = this.receiptWork.then(async () => {
      if (!checkMessage() || this.disconnected) return null;
      const previous = cached(); if (previous !== undefined) return previous ? copy(previous) : null;
      if (!this.account?.csrf_token || this.account.user_id !== account.user_id) throw new ChatError('stale_session');
      try {
        const result = await this.request(`/bchat/api/v2/rooms/${room.id}/messages/${messageId}/receipts`, e, undefined, false, { csrf_token: this.account.csrf_token, kind });
        checkMessage();
        if (result.api_version !== 2 || result.message_id !== messageId || typeof result.delivered_at !== 'string' || !result.delivered_at
          || result.read_at !== null && typeof result.read_at !== 'string' || kind === 'read' && !result.read_at
          || !Number.isSafeInteger(result.unread_count) || result.unread_count < 0 || !id(result.last_message_id) || result.last_message_id < messageId
          || typeof result.replayed !== 'boolean') throw new ChatError('invalid_receipt_ack');
        const ack = result as ReceiptAck; const saved = this.receiptAcks.get(key) ?? {};
        saved.delivered = copy(ack); if (ack.read_at) saved.read = copy(ack); this.receiptAcks.set(key, saved);
        if (this.receiptAcks.size > 1000) this.receiptAcks.delete(this.receiptAcks.keys().next().value!);
        await this.serial(async () => {
          this.fence(e); const current = this.room(room);
          if ((current.last_message_id ?? 0) <= ack.last_message_id) { current.last_message_id = ack.last_message_id; current.unread_count = ack.unread_count; }
          await this.persistIdentity(e);
        });
        return copy(ack);
      } catch (error) {
        this.fence(e);
        if (error instanceof ChatError && error.status === 409 && error.code === 'receipt_unavailable') {
          this.receiptAcks.set(key, { unavailable: true });
          if (this.receiptAcks.size > 1000) this.receiptAcks.delete(this.receiptAcks.keys().next().value!);
          return null;
        }
        if (error instanceof ChatError && error.status === 401) await this.invalidate(e);
        else if (denied(error)) await this.serial(async () => { await this.dropRoom(room, e); await this.persistIdentity(e); });
        throw error;
      }
    });
    this.receiptWork = run.catch(() => undefined); this.receiptPumps.set(pumpKey, run);
    try { return await run; } finally { if (this.receiptPumps.get(pumpKey) === run) this.receiptPumps.delete(pumpKey); }
  }
  private validateAttachment(value: Attachment): Attachment {
    const a = object(value);
    const fileMimes: Record<string, string> = {
      'application/pdf': '.pdf', 'text/plain': '.txt',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    };
    const lowerName = typeof a.name === 'string' ? a.name.toLowerCase() : '';
    const validType = a.kind === 'image' && ['image/jpeg', 'image/png', 'image/webp'].includes(a.mime)
      || a.kind === 'audio' && a.mime === 'audio/mp4' && lowerName.endsWith('.m4a')
      || a.kind === 'file' && typeof a.mime === 'string' && fileMimes[a.mime] && lowerName.endsWith(fileMimes[a.mime]);
    if (typeof a.uri !== 'string' || !a.uri.startsWith('file://') || /[\u0000-\u001f]/.test(a.uri)
      || typeof a.name !== 'string' || !a.name.trim() || /[\\/\p{C}]/u.test(a.name) || new TextEncoder().encode(a.name).length > 160
      || !validType || !Number.isSafeInteger(a.size) || a.size <= 0 || a.size > (a.kind === 'image' ? 5 : 10) * 1024 * 1024
      || typeof a.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(a.sha256) || !uuidPattern.test(a.upload_uuid)
      || a.media_id !== undefined && !id(a.media_id) || a.policy_version !== undefined && !id(a.policy_version)) throw new ChatError('invalid_attachment');
    return { uri: a.uri, name: a.name, mime: a.mime, size: a.size, sha256: a.sha256, kind: a.kind, upload_uuid: a.upload_uuid,
      ...(a.media_id !== undefined ? { media_id: a.media_id } : {}), ...(a.policy_version !== undefined ? { policy_version: a.policy_version } : {}) } as Attachment;
  }
  async enqueue(value: Room | number, text: string, replyTo?: number): Promise<Pending> {
    return this.enqueueItem(value, text, replyTo);
  }
  async enqueueAttachment(value: Room | number, attachment: Attachment, text = '', replyTo?: number): Promise<Pending> {
    const validated = this.validateAttachment(attachment);
    return this.enqueueItem(value, text, replyTo, validated);
  }
  private async enqueueItem(value: Room | number, text: string, replyTo?: number, attachment?: Attachment): Promise<Pending> {
    const room = this.room(value); const e = this.epoch;
    if (this.account?.permissions.chat_send !== true) throw new ChatError('send_denied', 403);
    if (attachment && this.account.permissions.media !== true) throw new ChatError('media_denied', 403);
    if (attachment && !attachment.media_id && !this.upload) throw new ChatError('media_upload_unavailable');
    if (room.mobile_direct && !this.account.mobile_policy?.find(p => p.company_id === room.company_id)?.direct_enabled) throw new ChatError('direct_disabled', 403);
    if (typeof text !== 'string' || !attachment && !text.trim() || new TextEncoder().encode(text).length > 16384 || (replyTo !== undefined && !id(replyTo))) throw new ChatError('invalid_text');
    return this.serial(async () => {
      this.fence(e); this.room(room);
      if (this.queue.size >= 100) throw new ChatError('outbox_full');
      const operationCount = (await this.storage.getAllKeys()).filter(k => k.startsWith(this.prefix()) && k.includes('/operations/')).length;
      this.fence(e); if (this.queue.size + operationCount >= 100) throw new ChatError('outbox_full');
      if (attachment) {
        if ([...this.queue.values()].some(p => p.attachment?.upload_uuid === attachment.upload_uuid || p.attachment?.uri === attachment.uri)) throw new ChatError('attachment_already_queued');
        const bytes = [...this.queue.values()].reduce((total, p) => total + (p.attachment?.size ?? 0), 0);
        if (bytes + attachment.size > 50 * 1024 * 1024) throw new ChatError('attachment_quota');
      }
      const uuid = this.uuid(); if (!uuidPattern.test(uuid) || this.queue.has(uuid)) throw new ChatError('invalid_uuid');
      const pending: Pending = { client_uuid: uuid, room_id: room.id, company_id: room.company_id, membership_id: room.membership_id, text, ...(replyTo ? { reply_to_message_id: replyTo } : {}), ...(attachment ? { attachment } : {}), created_at: this.now(), state: 'queued', attempts: 0, next_attempt_at: 0 };
      await this.storage.setItem(`${this.scope(room)}outbox/${uuid}`, JSON.stringify(pending));
      this.fence(e); this.queue.set(uuid, pending); return copy(pending);
    });
  }
  async flush(): Promise<void> {
    if (this.pumping) return this.pumping;
    const e = this.epoch;
    const run = (async () => {
      // Never replay under a remembered identity until server identity and memberships agree.
      await this.refresh(); this.fence(e);
      for (const pending of [...this.queue.values()]) {
        this.fence(e);
        if (pending.state === 'failed' || pending.next_attempt_at > this.now()) continue;
        const room = this.room(pending.room_id);
        if (pending.membership_id !== room.membership_id || pending.company_id !== room.company_id) continue;
        const key = `${this.scope(room)}outbox/${pending.client_uuid}`;
        await this.serial(async () => { this.fence(e); pending.state = 'sending'; pending.attempts++; await this.storage.setItem(key, JSON.stringify(pending)); });
        try {
          if (pending.attachment && !pending.attachment.media_id) {
            if (!this.upload || !this.account?.csrf_token || this.account.permissions.media !== true) throw new ChatError('media_denied', 403);
            const uploaded = await this.upload(copy(room), copy(pending.attachment), this.account.csrf_token, this.abort.signal);
            this.fence(e); this.room(room);
            if (!id(uploaded.media_id) || uploaded.policy_version !== undefined && !id(uploaded.policy_version)) throw new ChatError('invalid_upload_ack');
            await this.serial(async () => {
              this.fence(e); this.room(room);
              pending.attachment = { ...pending.attachment!, media_id: uploaded.media_id,
                ...(uploaded.policy_version ?? room.invoice_policy_version ? { policy_version: uploaded.policy_version ?? room.invoice_policy_version } : {}) };
              // The media result must survive restart before the message POST.
              await this.storage.setItem(key, JSON.stringify(pending)); this.fence(e);
            });
          }
          const payload = { api_version: 2, membership_id: pending.membership_id, client_uuid: pending.client_uuid, text: pending.text,
            ...(pending.reply_to_message_id ? { reply_to_message_id: pending.reply_to_message_id } : {}),
            ...(pending.attachment ? { media_id: pending.attachment.media_id, document_type: 'other', ...(pending.attachment.policy_version ? { policy_version: pending.attachment.policy_version } : {}) } : {}) };
          const ack = await this.request(`/bchat/api/v2/rooms/${room.id}/messages`, e, payload);
          if (ack.api_version !== 2 || ack.room_id !== room.id || ack.membership_id !== pending.membership_id || ack.client_uuid !== pending.client_uuid || ack.state !== 'sent' || !id(ack.message_id)
            || pending.attachment && ack.media_id !== pending.attachment.media_id) throw new ChatError('invalid_ack');
          await this.serial(async () => {
            this.fence(e); this.room(room);
            // ACK durability precedes removing the operation. A crash before removal safely replays UUID.
            const ackKey = `${this.scope(room)}ack/${pending.client_uuid}`;
            const durableAck = JSON.stringify({ message_id: ack.message_id, client_uuid: pending.client_uuid, ...(pending.attachment ? { attachment: pending.attachment } : {}) });
            await this.storage.setItem(ackKey, durableAck);
            await this.storage.removeItem(key); this.fence(e); this.queue.delete(pending.client_uuid);
            await this.removeStoredAttachments([[ackKey, durableAck]]);
            await this.storage.removeItem(ackKey);
          });
          // The operation has a durable ACK. A subsequent history read failure
          // must never recreate its already-removed outbox item.
          try { await this.readHistory(room, undefined, e); }
          catch (error) { this.fence(e); if (denied(error)) throw error; }
        } catch (error) {
          this.fence(e);
          if (denied(error)) { await this.serial(async () => { await this.dropRoom(room, e); await this.persistIdentity(e); }); throw error; }
          await this.serial(async () => {
            this.fence(e); pending.state = error instanceof ChatError && error.status === 429 ? 'queued'
              : error instanceof ChatError && error.status >= 400 && error.status < 500 && error.status !== 408 ? 'failed' : 'unknown';
            pending.error = codeOf(error); pending.next_attempt_at = this.now() + [5000, 10000, 20000, 30000][Math.min(pending.attempts - 1, 3)]!;
            await this.storage.setItem(key, JSON.stringify(pending));
          });
          this.disconnected = true; this.failures++; throw error;
        }
      }
    })();
    this.pumping = run;
    try { await run; } finally { if (this.pumping === run) this.pumping = null; }
  }
  private async write(path: string, payload: Record<string, unknown>): Promise<any> {
    const e = this.epoch; await this.refresh(); this.fence(e);
    return this.request(path, e, { api_version: 2, ...payload });
  }
  async createGroup(companyId: number, name: string, memberUserIds: number[]) {
    const e = this.epoch; await this.refresh(); this.fence(e);
    if (!id(companyId) || !this.account?.company_ids.includes(companyId) || this.account.permissions.group_create !== true) throw new ChatError('group_create_denied', 403);
    if (typeof name !== 'string' || !name.trim() || !Array.isArray(memberUserIds) || !memberUserIds.length || memberUserIds.length > 49 || !memberUserIds.every(id)) throw new ChatError('invalid_group');
    const payload = { company_id: companyId, name: name.trim(), member_user_ids: [...memberUserIds].sort((a, b) => a - b) };
    const key = `${this.prefix()}c/${companyId}/operations/group/${encodeURIComponent(JSON.stringify(payload))}`;
    const uuid = await this.serial(async () => {
      this.fence(e); const previous = await this.storage.getItem(key); this.fence(e);
      if (previous) {
        const saved = object(JSON.parse(previous));
        if (!uuidPattern.test(saved.client_uuid)) throw new ChatError('invalid_uuid');
        return saved.client_uuid as string;
      }
      const pendingKeys = (await this.storage.getAllKeys()).filter(k => k.startsWith(this.prefix()) && (k.includes('/outbox/') || k.includes('/operations/')));
      if (pendingKeys.length >= 100) throw new ChatError('outbox_full');
      const generated = this.uuid(); if (!uuidPattern.test(generated)) throw new ChatError('invalid_uuid');
      await this.storage.setItem(key, JSON.stringify({ client_uuid: generated })); this.fence(e); return generated;
    });
    const result = await this.request('/bchat/api/v2/rooms', e, { api_version: 2, ...payload, client_uuid: uuid });
    if (result.api_version !== 2 || !id(result.room_id) || !id(result.membership_id)) throw new ChatError('invalid_group_ack');
    await this.serial(async () => { this.fence(e); await this.storage.removeItem(key); });
    await this.refresh(); this.fence(e); return result as { api_version: 2; room_id: number; membership_id: number; replayed: boolean };
  }
  async candidates(companyId: number, q = ''): Promise<{ api_version: 2; users: { user_id: number; name: string }[] }> {
    this.requireIdentity(); if (!id(companyId) || !this.account?.company_ids.includes(companyId)) throw new ChatError('company_denied', 403);
    const route = this.account.mobile_policy ? 'mobile/candidates' : 'member-candidates';
    return this.request(`/bchat/api/v2/${route}?company_id=${companyId}&q=${encodeURIComponent(q)}`, this.epoch);
  }
  async directOpen(companyId: number, userId: number) {
    const e = this.epoch;
    const result = await this.write('/bchat/api/v2/mobile/direct', { company_id: companyId, user_id: userId, client_uuid: this.uuid() });
    await this.refresh(); this.fence(e); return result as { api_version: 2; room_id: number; membership_id: number; replayed: boolean };
  }
  async policy(companyId: number): Promise<Policy> {
    this.requireIdentity(); return this.request(`/bchat/api/v2/mobile/policy?company_id=${companyId}`, this.epoch);
  }
  async setPolicy(companyId: number, enabled: boolean): Promise<Policy> {
    const e = this.epoch;
    const result = await this.write('/bchat/api/v2/mobile/policy', { company_id: companyId, direct_enabled: enabled });
    await this.refresh(); this.fence(e); return result as Policy;
  }
  async groupInfo(value: Room | number): Promise<{ api_version: 2; room: Room & { description: string }; members: { user_id: number; name: string; is_admin: boolean }[]; can_manage: boolean }> {
    const room = this.room(value); return this.request(`/bchat/api/v2/rooms/${room.id}/group`, this.epoch);
  }
  async groupChange(value: Room | number, change: { action: string; name?: string; description?: string; user_id?: number }) {
    const e = this.epoch;
    const room = this.room(value); const result = await this.write(`/bchat/api/v2/rooms/${room.id}/group`, change);
    await this.refresh(); this.fence(e); return result;
  }
}

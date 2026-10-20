/** Odoo-owned chat domain. No native dependencies, credentials or telemetry. */
import type { LoginStage, NetworkFailure } from './loginDiagnostics';
import type { ArchiveEdge, ArchiveQuery, ArchiveSlice, HistoryArchive, HistoryScope } from './HistoryArchive.ts';
import { ARCHIVE_LIMITS, ArchiveError } from './HistoryArchive.ts';
import { MemoryHistoryArchive } from './MemoryHistoryArchive.ts';
import { decodeGallery, galleryQuery, GALLERY_LIMITS, type MediaGalleryPage, type MediaGalleryQuery } from './MediaGallery.ts';
import {contentRevision,decodeContentState,CONTENT_LIMITS,type ContentCache} from './ContentRetention.ts';
import { compatibility } from '../compatibility.ts';
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
  capabilities?: {retention_version?:number;retention_ready?:boolean;[key:string]:unknown};
  profile?: { name: string; companies: { id: number; name: string; name_ar?: string; name_en?: string }[] };
}
export interface Room {
  id: number; company_id: number; membership_id: number; name: string;
  is_group: boolean; is_group_admin?: boolean; mobile_direct?: boolean;
  last_message_id?: number; last_message_preview?: string; unread_count?: number;
  invoice_policy?: string; invoice_policy_version?: number;
  avatar_version?: number;
  content_revision?:number;
}
export interface GroupInfo {
  api_version: 2;
  room: { id: number; company_id: number; name: string; description: string; avatar_version: number; is_group: boolean };
  members: { user_id: number; name: string; is_admin: boolean }[];
  can_manage: boolean;
}
export interface GroupAvatarInput { uri: string; name: string; mime: string }
export interface GroupAvatarAck { api_version: 2; room_id: number; avatar_version: number }
export interface Message {
  id: number; author_user_id: number; author_name: string; text: string; created_at: string;
  delivery_state?: string; read_at?: string | null; media?: Record<string, unknown>; reply?: Record<string, unknown>;
  content_removed?: boolean; media_removed?: boolean;
}
export interface History { api_version: 2; messages: Message[]; next_before_id: number | null;
  archive?: { older: ArchiveEdge; newer: ArchiveEdge; partial: boolean; browsing: boolean; latestId: number | null; unverified?: boolean } }
/** Only successful canonical post-ACK reads from this exact flush incarnation.
 * Null requires the caller's ordinary history path; this never fetches or renews authority. */
export interface FlushResult { historyFor(value: Room | number): History | null }
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
  uploadGroupAvatar?: (room: Room, input: GroupAvatarInput, csrfToken: string, signal: AbortSignal) => Promise<GroupAvatarAck>;
  archive?: HistoryArchive;
  contentCache?:ContentCache;
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
/** Match the existing server's UTF-8 group-description contract, including empty-to-clear. */
export function groupDescription(value: unknown): string {
  if (typeof value !== 'string') throw new ChatError('description_invalid');
  const normalized = value.replace(/\r\n/g, '\n').trim();
  if (/\p{C}/u.test(normalized.replace(/\n/g, '')) || new TextEncoder().encode(normalized).length > 1024) throw new ChatError('description_invalid');
  return normalized;
}

export class ChatEngine {
  private readonly transport: Transport;
  private readonly storage: Storage;
  private readonly database: string;
  private readonly root: string;
  private readonly uuid: () => string;
  private readonly now: () => number;
  private readonly upload?: Options['upload'];
  private readonly removeAttachment?: Options['removeAttachment'];
  private readonly avatarUpload?: Options['uploadGroupAvatar'];
  private readonly archive: HistoryArchive;
  private readonly contentCache?:ContentCache;
  private contentStates=new Map<string,{revision:number;ready:boolean;mediaReady:boolean}>();
  private contentListeners=new Set<()=>void>();
  private contentVersion=0;
  get contentEpoch():number{return this.contentVersion;}
  subscribeContent(listener:()=>void):()=>void{this.contentListeners.add(listener);return()=>{this.contentListeners.delete(listener);};}
  private contentNotify(){this.contentVersion++;for(const listener of this.contentListeners)try{listener();}catch{/* Observers cannot authorize content. */}}
  private archiveCleanup = new Set<string>();
  private archiveOwner: string | null = null;
  private browsing = new Set<string>();
  private historyPumps = new Map<string, Promise<History>>();
  private windowVersions = new Map<string, number>();
  private hiddenIds = new Map<string, Set<number>>();
  private galleryAssociations = new Map<string, Map<number, Message>>();
  private galleryPages = new Map<string, MediaGalleryPage>();
  private epoch = 0;
  private abort = new AbortController();
  private work: Promise<unknown> = Promise.resolve();
  private lifecycle: Promise<unknown> = Promise.resolve();
  private pumping: Promise<FlushResult> | null = null;
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
    this.root = `${compatibility.storage.chatRoot}${encodeURIComponent(origin.origin)}/${encodeURIComponent(options.database)}/`;
    this.uuid = options.uuid ?? (() => globalThis.crypto.randomUUID()); this.now = options.now ?? Date.now;
    this.upload = options.upload; this.removeAttachment = options.removeAttachment;
    this.avatarUpload = options.uploadGroupAvatar;
    this.archive = options.archive ?? new MemoryHistoryArchive();
    this.contentCache=options.contentCache;
  }
  get identity(): Bootstrap | null { return this.account && !this.accessLocked ? copy(this.account) : null; }
  get accountScope(): string | null { return this.account && !this.accessLocked ? `${this.prefix()}/epoch:${this.epoch}` : null; }
  get offline(): boolean { return this.disconnected; }
  /** Remaining display lease only; reading this never verifies or renews it. */
  get leaseRemainingMs(): number {
    if (!this.account || this.accessLocked) return 0;
    const now = this.now();
    return Number.isFinite(now) && now >= this.verifiedAt ? Math.max(0, TTL - (now - this.verifiedAt)) : 0;
  }
  /** Remembered display permission only; never verifies or renews HTTP authority. */
  get rememberedLeaseRemainingMs(): number { return this.remembered ? this.leaseRemainingMs : 0; }
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
    this.browsing.clear(); this.historyPumps.clear(); this.windowVersions.clear();
    this.hiddenIds.clear();
    this.galleryAssociations.clear(); this.galleryPages.clear();
    this.contentStates.clear();this.contentNotify();
    this.accessLocked = false;
    this.receiptWork = Promise.resolve(); this.receiptPumps.clear(); this.receiptAcks.clear();
    return this.epoch;
  }
  private prefix(uid = this.account?.user_id): string {
    if (!id(uid)) throw new ChatError('login_required');
    return `${this.root}u/${uid}/`;
  }
  private scope(room: Room): string { return `${this.prefix()}c/${room.company_id}/r/${room.id}/m/${room.membership_id}/`; }
  private archiveScope(room: Room): HistoryScope { return { account: this.prefix(), companyId: room.company_id, roomId: room.id, membershipId: room.membership_id }; }
  private archiveGuard(e: number, room?: Room, internal = false): () => void {
    const account = this.prefix();
    return () => {
      this.fence(e);
      if (!this.account || this.prefix() !== account || this.account.permissions.chat_view !== true) throw new ChatError('stale_session');
      if (!internal) this.requireIdentity();
      if (room && (!this.account.company_ids.includes(room.company_id) || !this.roomRows.some(row => row.id === room.id && row.company_id === room.company_id && row.membership_id === room.membership_id))) throw new ChatError('membership_changed', 403);
      if(room&&this.retentionEnabled()){
        const current=this.roomRows.find(row=>row.id===room.id)!;
        if(current.content_revision!==room.content_revision)throw new ChatError('content_changed',409);
        if((this.contentStates.get(this.scope(room))?.revision??0)>Number(room.content_revision))throw new ChatError('content_changed',409);
        if(!internal)this.requireContent(room);
      }
    };
  }
  private retentionEnabled():boolean{return this.account?.capabilities?.retention_version===1;}
  contentReady(value:Room|number):boolean{
    const room=this.room(value),state=this.contentStates.get(this.scope(room));return !this.retentionEnabled()||state?.ready===true&&state.revision===room.content_revision&&(this.account?.permissions.media!==true||state.mediaReady===true);
  }
  private requireContent(room:Room):void{if(!this.contentReady(room))throw new ChatError('content_sync_required',409);}
  private blockContent(room:Room,revision:number):void{
    const key=this.scope(room);revision=Math.max(revision,this.contentStates.get(key)?.revision??0);this.contentStates.set(key,{revision,ready:false,mediaReady:false});this.histories.delete(key);this.browsing.delete(key);
    this.windowVersions.set(key,(this.windowVersions.get(key)??0)+1);this.clearGalleryScope(key);this.contentNotify();
  }
  private async loadContentMarkers(e:number):Promise<void>{
    if(!this.retentionEnabled())return;
    for(const room of this.roomRows){let raw:string|null=null;
      try{raw=await this.storage.getItem(`${this.scope(room)}content-state`);}catch{/* An unreadable content marker is not corrupt identity or permission to purge the outbox. */}this.fence(e);
      let saved:any;try{saved=raw?JSON.parse(raw):null;}catch{/* Unknown marker blocks content. */}
      if(contentRevision(room.content_revision)&&saved?.revision===room.content_revision&&saved?.ready===true)this.contentStates.set(this.scope(room),{revision:room.content_revision,ready:true,mediaReady:saved.mediaReady===true});
      else this.blockContent(room,Math.max(contentRevision(room.content_revision)?room.content_revision:0,contentRevision(saved?.revision)?saved.revision:0));
    }
  }
  private async observeContentRevision(room:Room,revision:number):Promise<void>{
    const e=this.epoch,scope=this.scope(room),key=`${scope}content-state`;
    this.blockContent(room,Math.max(revision,this.contentStates.get(scope)?.revision??0));
    // The durable incomplete marker must land before this observation rejects.
    // Queue with all other marker writers; never let an older completion reopen it.
    await this.serial(async()=>{
      const guard=()=>{this.fence(e);if(!this.roomRows.some(row=>row.id===room.id&&row.company_id===room.company_id&&row.membership_id===room.membership_id)||this.scope(room)!==scope)throw new ChatError('stale_session');};
      guard();const current=this.contentStates.get(scope);
      if(current?.ready&&current.revision>=revision)return;
      const observed=Math.max(revision,current?.revision??0);
      try{await this.storage.setItem(key,JSON.stringify({revision:observed,ready:false}));guard();}
      catch(error){
        guard();
        // If writing fails, removing the old ready marker still fails closed on restart.
        // Total storage I/O failure cannot promise crash durability; reject, never display.
        await this.storage.removeItem(key);guard();throw error;
      }
    });
  }
  private async assertContentResponse(raw:any,room:Room):Promise<void>{
    if(!this.retentionEnabled())return;
    if(!contentRevision(raw?.content_revision)||raw.content_revision!==room.content_revision){
      if(contentRevision(raw?.content_revision)&&Number(raw.content_revision)>Number(room.content_revision))await this.observeContentRevision(room,raw.content_revision);
      throw new ChatError('content_changed',409);
    }
    this.requireContent(room);
  }
  async checkContentRevision(value:Room|number,revision:unknown):Promise<void>{await this.assertContentResponse({content_revision:revision},this.room(value));}
  private async reconcileContent(e:number):Promise<void>{
    if(!this.retentionEnabled())return;
    for(const room of this.roomRows){
      const revision=room.content_revision!,mediaReady=this.account!.permissions.media===true,saved=this.contentStates.get(this.scope(room));
      if(saved&&saved.revision>revision)throw new ChatError('content_revision_rollback',409);
      if(saved?.ready&&saved.revision===revision&&saved.mediaReady===mediaReady)continue;
      this.blockContent(room,revision);const guard=this.archiveGuard(e,room,true),key=`${this.scope(room)}content-state`,scope=this.archiveScope(room);
      await this.serial(async()=>{guard();await this.storage.setItem(key,JSON.stringify({revision,ready:false}));guard();});
      if(!this.archive.clearRoom)throw new ChatError('content_storage_unavailable');
      await this.serial(async()=>{guard();await this.archive.clearRoom!(scope,guard);guard();await this.storage.removeItem(`${this.scope(room)}history`);guard();});
      // Media revocation does not revoke text/outbox authority. Quarantine bytes
      // without asking a media-only endpoint; regrant must reconcile this same revision.
      const ids=(mediaReady?await this.contentCache?.quarantine(scope,room,revision,guard)??[]:[]).sort((a,b)=>a-b);guard();
      if(ids.length>CONTENT_LIMITS.cacheIds||ids.some((v,i)=>!id(v)||i>0&&v===ids[i-1]))throw new ChatError('invalid_content_state');
      for(let start=0;start<ids.length;start+=CONTENT_LIMITS.ids){
        const batch=ids.slice(start,start+CONTENT_LIMITS.ids),seen=new Set<number>();let cursor:string|undefined;
        do{
          guard();const raw=await this.request(`/bwork/api/v2/rooms/${room.id}/content-state`,e,{api_version:2,membership_id:room.membership_id,content_revision:revision,media_ids:batch,...(cursor?{cursor}:{})});guard();
          let page;try{page=decodeContentState(raw,room,revision,batch,cursor);}catch{throw new ChatError('invalid_content_state');}
          for(const item of page.items){if(seen.has(item.media_id))throw new ChatError('invalid_content_state');seen.add(item.media_id);}
          await this.contentCache?.apply(scope,room,revision,page.items,guard);guard();cursor=page.next_cursor??undefined;
        }while(cursor);
        if(seen.size!==batch.length)throw new ChatError('invalid_content_state');
      }
      await this.contentCache?.complete(scope,room,revision,guard);guard();
      await this.serial(async()=>{guard();await this.storage.setItem(key,JSON.stringify({revision,ready:true,mediaReady}));guard();this.contentStates.set(this.scope(room),{revision,ready:true,mediaReady});this.contentNotify();});
    }
  }
  /** Epoch-only cleanup authority remains usable after account reset. Called under serial. */
  private async drainArchiveCleanup(e: number): Promise<void> {
    for (const account of [...this.archiveCleanup]) {
      this.fence(e); await this.archive.purgeAccount(account, () => this.fence(e)); this.fence(e);
      this.archiveCleanup.delete(account);
    }
  }
  private async reconcileArchive(e: number): Promise<void> {
    const guard = this.archiveGuard(e, undefined, true);
    await this.archive.reconcile(this.prefix(), this.roomRows.map(room => this.archiveScope(room)), this.account!.permissions.media === true, guard); guard();
  }
  private async migrateLegacyHistory(e: number): Promise<void> {
    for (const room of this.roomRows) {
      if(this.retentionEnabled()&&this.contentStates.get(this.scope(room))?.ready!==true)continue;
      const key = `${this.scope(room)}history`, guard = this.archiveGuard(e, room, this.accessLocked);
      let raw: string | null;
      try { raw = await this.storage.getItem(key); guard(); }
      catch { guard(); await this.storage.removeItem(key); continue; }
      if (!raw) continue;
      let history: History;
      try {
        if (new TextEncoder().encode(raw).length > HISTORY_LIMITS.roomBytes) throw new ChatError('invalid_history');
        history = this.validHistory(JSON.parse(raw));
      } catch { guard(); await this.storage.removeItem(key); continue; }
      // Import ACK is the only authority to remove this replaceable legacy source.
      try { await this.archive.importLegacy(this.archiveScope(room), history, guard); guard(); }
      catch { guard(); throw new ChatError('history_storage_unavailable'); }
      await this.storage.removeItem(key); guard();
    }
  }
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
    for (const key of this.hiddenIds.keys()) if (key.startsWith(prefix)) this.hiddenIds.delete(key);
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
      if (path==='/bwork/api/v2/bootstrap' && [404,405].includes(Number((error as {status?:number})?.status))) throw new ChatError('server_incompatible',Number((error as {status?:number}).status));
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
    if(b.capabilities?.retention_version!==undefined&&(b.capabilities.retention_version!==1||typeof b.capabilities.retention_ready!=='boolean'))throw new ChatError('invalid_content_state',409);
    return b as Bootstrap;
  }
  /** Application login may select another authorized module. Default chat behavior is unchanged. */
  protected nonChatBootstrap(_raw: unknown, _expectedUid: number): Bootstrap | null { return null; }
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
    if (this.archiveOwner) this.archiveCleanup.add(this.archiveOwner);
    const cleanup = this.reset();
    await this.serial(async () => { this.fence(cleanup); await this.drainArchiveCleanup(cleanup); await this.purge(root); });
  }
  private async loadStoredAccount(e: number) {
    this.fence(e);
    const rooms = JSON.parse(await this.storage.getItem(`${this.prefix()}rooms`) ?? '[]'); this.fence(e);
    // Cached company access can be older than today's bootstrap. Load only
    // structurally valid scopes, then reconcile every scope with /rooms.
    if (!Array.isArray(rooms) || rooms.length > 100) throw new ChatError('invalid_rooms');
    this.roomRows = rooms.filter(r => id(r.id) && id(r.company_id) && id(r.membership_id) && typeof r.name === 'string');
    const keys = await this.storage.getAllKeys(); this.fence(e);
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
      await this.serial(() => this.drainArchiveCleanup(e)); this.fence(e);
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
        bootstrapRequested = true;
        loginStage = 'bootstrap';
        const rawBootstrap = await this.request('/bwork/api/v2/bootstrap', e);
        const alternate = this.nonChatBootstrap(rawBootstrap, result.uid);
        if (alternate) {
          // The authoritative bootstrap has withdrawn chat access. Keep its
          // native session for the application module, never a chat identity.
          await this.invalidate(e);
          return copy(alternate);
        }
        const bootstrap = this.bootstrap(rawBootstrap, result.uid);
        // Authenticate is not proof that this server supports the BWork protocol.
        // Defer destructive account replacement until canonical bootstrap validates.
        loginStage = 'storage';
        await this.serial(async () => {
          this.fence(e);
          if (prior.uid !== result.uid) {
            if (prior.uid) this.archiveCleanup.add(this.prefix(prior.uid));
            this.archiveCleanup.add(this.prefix(result.uid)); await this.drainArchiveCleanup(e);
            await this.purge(this.root); await this.storage.setItem(`${this.root}authentication-required`, 'true');
          }
          this.archiveOwner = this.prefix(result.uid);
          await this.storage.setItem(`${this.root}owner`, JSON.stringify({ user_id: result.uid })); this.fence(e);
        });
        this.account = bootstrap; this.remembered = remember; this.verifiedAt = prior.uid === result.uid ? prior.verifiedAt : 0;
        if (prior.uid === result.uid) {await this.serial(() => this.loadStoredAccount(e));await this.loadContentMarkers(e);}
        await this.applyBootstrap(bootstrap, e);
        loginStage = 'rooms';
        await this.loadRooms(e);
        this.verifiedAt = this.now();
        loginStage = 'storage';
        await this.serial(async () => {
          await this.migrateLegacyHistory(e);
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
        this.archiveOwner = this.prefix(); await this.drainArchiveCleanup(e);
        await this.loadStoredAccount(e); this.roomRows = this.validRooms(this.roomRows);await this.loadContentMarkers(e);
        try { await this.reconcileArchive(e); await this.migrateLegacyHistory(e); }
        catch (error) {
          this.fence(e);
          if (error instanceof ChatError && denied(error)) throw error;
          throw new ChatError('history_storage_unavailable');
        }
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
    if (this.archiveOwner) this.archiveCleanup.add(this.archiveOwner);
    const e = this.reset();
    await this.serial(async () => { this.fence(e); await this.drainArchiveCleanup(e); await this.purge(this.root); });
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
      if (r.avatar_version !== undefined && (!Number.isSafeInteger(r.avatar_version) || r.avatar_version < 0)) throw new ChatError('invalid_rooms');
      if(this.retentionEnabled()&&!contentRevision(r.content_revision))throw new ChatError('invalid_content_state');
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
        this.clearGalleryScope(key);
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
      if (bootstrap.permissions.media !== true || bootstrap.permissions.chat_view !== true) {
        this.galleryAssociations.clear(); this.galleryPages.clear();
      }
    };
    // Restrict visible memory before waiting behind any pending disk operation.
    reconcileMemory();
    await this.serial(async () => {
      // An enqueue already holding the disk mutex may have completed meanwhile.
      reconcileMemory();
      for (const scope of revokedScopes) await this.purge(scope);
      await this.reconcileArchive(e);
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
      this.fence(e); await this.persistIdentity(e);
    });
  }
  private async loadRooms(e: number) {
    const result = await this.request('/bwork/api/v2/rooms', e);
    const rooms = this.validRooms(result.rooms);
    if(this.retentionEnabled())for(const room of rooms){
      const saved=this.contentStates.get(this.scope(room));
      if(saved&&saved.revision>room.content_revision!)throw new ChatError('content_revision_rollback',409);
      if(!saved?.ready||saved.revision!==room.content_revision)this.blockContent(room,room.content_revision!);
    }
    await this.serial(async () => {
      this.fence(e);
      for (const old of this.roomRows) {
        if (!rooms.some(r => r.id === old.id && r.company_id === old.company_id && r.membership_id === old.membership_id)) await this.dropRoom(old, e);
      }
      this.fence(e); this.roomRows = rooms;
      await this.reconcileArchive(e);
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
    await this.reconcileContent(e);
  }
  private async dropRoom(room: Room, e: number) {
    this.fence(e); const scope = this.scope(room);
    this.histories.delete(scope); this.roomRows = this.roomRows.filter(r => !(r.id === room.id && r.company_id === room.company_id && r.membership_id === room.membership_id));
    this.clearGalleryScope(scope);
    this.browsing.delete(scope); await this.reconcileArchive(e);
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
        const bootstrap = this.bootstrap(await this.request('/bwork/api/v2/bootstrap', e), uid);
        await this.applyBootstrap(bootstrap, e);
        await this.loadRooms(e);
        const changes = await this.request(`/bwork/api/v2/changes?after=${this.changeCursor}&limit=100&permissions_version=1`, e);
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
    const base: History = { api_version: 2, messages: [], next_before_id: history.next_before_id, ...(history.archive ? { archive: copy(history.archive) } : {}) };
    let bytes = encoder.encode(JSON.stringify(base)).length;
    const newest: Message[] = [];
    for (let index = history.messages.length - 1; index >= 0 && newest.length < ARCHIVE_LIMITS.windowMessages; index--) {
      const message = history.messages[index]!;
      const additional = encoder.encode(JSON.stringify(message)).length + (newest.length ? 1 : 0);
      if (bytes + additional > HISTORY_LIMITS.roomBytes) {
        if (!newest.length) throw new ChatError('history_message_too_large');
        break;
      }
      bytes += additional; newest.push(message);
    }
    base.messages = newest.reverse();
    if (base.archive && newest.length < history.messages.length && base.messages.length) {
      base.next_before_id = base.messages[0]!.id; base.archive.older = { kind: 'cached', cursor: base.next_before_id };
    }
    const json = JSON.stringify(base);
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
    // Archive retention is independent from this small JS view/LRU. Never evict durable sends.
    this.fence(e);
  }
  /** Current authorized snapshot only; never fetches, renews a lease or exposes mutable cache. */
  rememberedHistory(value: Room | number): History | null {
    const account = this.requireIdentity();
    if (account.permissions.chat_view !== true || account.permissions.media !== true) throw new ChatError('forbidden', 403);
    const room = this.room(value);
    this.requireContent(room);
    const history = this.histories.get(this.scope(room));
    return history ? copy(history) : null;
  }
  /** Canonical association, not authority granted by a caller-provided file descriptor. */
  async mediaAssociation(value: Room | number, mediaId: number): Promise<Message | null> {
    const room = this.room(value), e = this.epoch;this.requireContent(room);
    if (!id(mediaId)) throw new ChatError('invalid_media');
    const scopeGuard = this.archiveGuard(e, room);
    const guard = () => { scopeGuard(); if (this.account?.permissions.media !== true) throw new ChatError('forbidden', 403); };
    guard();
    await this.hiddenMessages(room); guard();
    const visible = (message: Message | null | undefined): Message | null => {
      guard();
      return message && !(message.author_user_id === this.account?.user_id && this.hiddenIds.get(this.scope(room))?.has(message.id)) ? copy(message) : null;
    };
    const hot = this.histories.get(this.scope(room))?.messages.find(message => message.media?.id === mediaId);
    if (hot) return visible(hot);
    const sparse = this.galleryAssociations.get(this.scope(room))?.get(mediaId);
    if (sparse) return visible(sparse);
    return this.serial(async () => { guard(); const message = await this.archive.findMedia(this.archiveScope(room), mediaId, guard); return visible(message); });
  }
  /** Persist only an internally resolved canonical association, never caller metadata. */
  async retainMediaAssociation(value: Room | number, mediaId: number, keep: boolean): Promise<void> {
    const room = this.room(value), e = this.epoch, scopeGuard = this.archiveGuard(e, room);
    const guard = () => { scopeGuard(); if (this.account?.permissions.media !== true) throw new ChatError('forbidden', 403); };
    guard();
    if (!id(mediaId) || typeof keep !== 'boolean') throw new ChatError('invalid_media');
    const retain = this.archive.retainMediaAssociation;
    if (!retain) throw new ChatError('media_storage_unavailable');
    const message = keep ? await this.mediaAssociation(room, mediaId) : null; guard();
    if (keep && !message) throw new ChatError('media_unavailable');
    await this.serial(async () => { guard(); await retain.call(this.archive, this.archiveScope(room), message, mediaId, guard); guard(); });
  }
  private clearGalleryScope(scope: string): void {
    this.galleryAssociations.delete(scope);
    for (const key of this.galleryPages.keys()) if (key.startsWith(scope)) this.galleryPages.delete(key);
  }
  /** Bounded sparse canonical associations, never committed as history pages or receipts. */
  async mediaGallery(value: Room | number, requested: MediaGalleryQuery = {}): Promise<MediaGalleryPage> {
    const room = this.room(value), e = this.epoch, guard = this.archiveGuard(e, room), scope = this.scope(room);
    const mediaGuard = () => { guard(); if (this.account?.permissions.media !== true) throw new ChatError('forbidden', 403); };
    mediaGuard();
    let query: ReturnType<typeof galleryQuery>;
    try { query = galleryQuery(requested); } catch { throw new ChatError('invalid_gallery'); }
    const key = `${scope}gallery/${JSON.stringify(query)}`;
    const hideOwned = async (page: MediaGalleryPage): Promise<MediaGalleryPage> => {
      const hidden = new Set(await this.hiddenMessages(room)); mediaGuard();
      return { ...copy(page), items: page.items.filter(item => !(item.author_user_id === this.account?.user_id && hidden.has(item.id))).map(copy) };
    };
    if (this.disconnected) {
      const saved = this.galleryPages.get(key);
      if (!saved) throw new ChatError('gallery_offline');
      return hideOwned({ ...saved, cached: true });
    }
    try {
      const params = new URLSearchParams({ kind: query.kind, order: query.order, limit: String(query.limit) });
      if (query.cursor) params.set('cursor', query.cursor);
      const raw = await this.request(`/bwork/api/v2/rooms/${room.id}/media?${params}`, e); mediaGuard();
      await this.assertContentResponse(raw,room);
      let page: MediaGalleryPage;
      try { page = decodeGallery(raw, room, query); } catch { throw new ChatError('invalid_gallery'); }
      const visible = await hideOwned(page); mediaGuard();
      const associations = this.galleryAssociations.get(scope) ?? new Map<number, Message>();
      for (const message of visible.items) {
        const id = Number(message.media!.id); associations.delete(id); associations.set(id, copy(message));
      }
      this.galleryAssociations.delete(scope); this.galleryAssociations.set(scope, associations);
      let size = [...this.galleryAssociations.values()].reduce((count, rows) => count + rows.size, 0);
      for (const [oldScope, rows] of this.galleryAssociations) {
        while (size > GALLERY_LIMITS.associations && rows.size) { rows.delete(rows.keys().next().value!); size--; }
        if (!rows.size) this.galleryAssociations.delete(oldScope);
      }
      this.galleryPages.delete(key); this.galleryPages.set(key, copy(page));
      while (this.galleryPages.size > 6) this.galleryPages.delete(this.galleryPages.keys().next().value!);
      return visible;
    } catch (error) {
      if (e === this.epoch && denied(error)) {
        this.clearGalleryScope(scope);
        if (error instanceof ChatError && error.status === 401) await this.invalidate(e);
        else await this.serial(() => this.dropRoom(room, e));
      }
      throw error;
    }
  }
  async history(value: Room | number, beforeId?: number): Promise<History> {
    const room = this.room(value); const e = this.epoch;
    this.requireContent(room);
    if (beforeId !== undefined) return this.navigateHistory(room, 'before', beforeId);
    if (this.disconnected) return this.serial(async () => {
      const guard = this.archiveGuard(e, room); guard();
      const old = this.histories.get(this.scope(room)); if (old && this.browsing.has(this.scope(room))) return copy(old);
      const slice = await this.archive.read(this.archiveScope(room), { direction: 'latest', limit: ARCHIVE_LIMITS.windowMessages, maxBytes: ARCHIVE_LIMITS.windowBytes }, guard); guard();
      const page = this.sliceHistory(slice, false); await this.cacheHistory(room, page, e); return copy(page);
    });
    return this.readHistory(room, beforeId, e);
  }
  /** Only explicit latest resets browsing; routine sync/history never snaps back. */
  async latest(value: Room | number): Promise<History> {
    const room = this.room(value), scope = this.scope(room);
    this.windowVersions.set(scope, (this.windowVersions.get(scope) ?? 0) + 1); this.browsing.delete(scope);
    return this.history(room);
  }
  /** One exact, authorized message; no receipt POST or alteration of the reader's window. */
  async messageInfo(value: Room | number, messageId: number): Promise<Message> {
    const room = this.room(value), e = this.epoch, guard = this.archiveGuard(e, room);
    if (!id(messageId) || messageId >= Number.MAX_SAFE_INTEGER) throw new ChatError('invalid_message');
    try {
      let message: Message | undefined;
      if (!this.disconnected) {
        const result = await this.request(`/bwork/api/v2/rooms/${room.id}/messages/${messageId}`, e); guard();
        await this.assertContentResponse(result,room);
        if (result.api_version !== 2) throw new ChatError('invalid_response');
        message = this.validHistory({ api_version: 2, messages: [object(result.message)], next_before_id: null }).messages[0];
      } else {
        message = this.histories.get(this.scope(room))?.messages.find(row => row.id === messageId);
        if (!message) {
          const slice = await this.serial(() => this.archive.read(this.archiveScope(room), { direction: 'before', anchorId: messageId + 1, limit: 1, maxBytes: ARCHIVE_LIMITS.windowBytes }, guard));
          message = slice.messages.find(row => row.id === messageId);
        }
      }
      guard();
      if (!message) throw new ChatError('message_unavailable', 404);
      if (message.id !== messageId || typeof message.author_name !== 'string' || typeof message.created_at !== 'string'
        || message.read_at !== undefined && message.read_at !== null && typeof message.read_at !== 'string') throw new ChatError('invalid_response');
      const result = copy(message);
      if (this.account?.permissions.media !== true) delete result.media;
      return result;
    } catch (error) {
      if (e === this.epoch && error instanceof ChatError && error.status === 401) await this.invalidate(e);
      if (error instanceof ChatError && error.status === 403) throw new ChatError('message_unavailable', 403);
      throw error;
    }
  }
  /** Resolve an original without walking all pages or mistaking its nearest neighbor for it. */
  async jumpToMessage(value: Room | number, messageId: number): Promise<History> {
    const room = this.room(value), e = this.epoch, guard = this.archiveGuard(e, room), key = this.scope(room);
    if (!id(messageId) || messageId >= Number.MAX_SAFE_INTEGER) throw new ChatError('invalid_message');
    const version = (this.windowVersions.get(key) ?? 0) + 1; this.windowVersions.set(key, version);
    try {
    let slice = await this.serial(() => this.archive.read(this.archiveScope(room), { direction: 'before', anchorId: messageId + 1, limit: ARCHIVE_LIMITS.pageMessages, maxBytes: ARCHIVE_LIMITS.windowBytes }, guard));
    guard();
    if (!this.disconnected) {
      // Revalidate visibility/joins online even if a provisional old cache contains the target.
      await this.fetchHistoryPage(room, messageId + 1, e); guard();
      slice = await this.serial(() => this.archive.read(this.archiveScope(room), { direction: 'before', anchorId: messageId + 1, limit: ARCHIVE_LIMITS.pageMessages, maxBytes: ARCHIVE_LIMITS.windowBytes }, guard));
    }
    if (!slice.messages.some(row => row.id === messageId)) throw new ChatError('message_unavailable', 404);
    return await this.serial(async () => {
      guard(); if (this.windowVersions.get(key) !== version) throw new ChatError('stale_session');
      this.browsing.add(key); const page = this.sliceHistory(slice, true);
      await this.cacheHistory(room, page, e); guard(); return copy(page);
    });
    } catch (error) {
      if (error instanceof ChatError && ['message_unavailable', 'stale_session'].includes(error.code)) throw error;
      return this.historyFailure(room, e, error);
    }
  }
  /** Device presentation metadata only. Server content and queued sends are never mutated. */
  private async loadHidden(room: Room, guard: () => void): Promise<Set<number>> {
    const key = this.scope(room); guard();
    const old = this.hiddenIds.get(key);
    const raw = old ? null : await this.storage.getItem(`${key}hidden-message-ids`); guard();
    if (raw !== null && raw.length > 90001) throw new ChatError('local_state_invalid');
    let ids: unknown;
    try { ids = raw === null ? [] : JSON.parse(raw); } catch { throw new ChatError('local_state_invalid'); }
    if (!Array.isArray(ids) || ids.length > 5000 || ids.some(value => !id(value)) || new Set(ids).size !== ids.length) throw new ChatError('local_state_invalid');
    const loaded = old ?? new Set<number>(ids);
    // Earlier releases allowed hiding received messages. Only prune authorship
    // proven by this bounded canonical window; never scan the archive per ID.
    const foreign = new Set((this.histories.get(key)?.messages ?? [])
      .filter(message => message.author_user_id !== this.account?.user_id).map(message => message.id));
    const owned = new Set([...loaded].filter(messageId => !foreign.has(messageId)));
    if (owned.size !== loaded.size) { await this.storage.setItem(`${key}hidden-message-ids`, JSON.stringify([...owned])); guard(); }
    this.hiddenIds.set(key, owned); return owned;
  }
  async hiddenMessages(value: Room | number): Promise<number[]> {
    const room = this.room(value), guard = this.archiveGuard(this.epoch, room);
    return this.serial(async () => { const ids = await this.loadHidden(room, guard); guard(); return [...ids]; });
  }
  cachedHiddenMessages(value: Room | number): number[] | null {
    const room = this.room(value), ids = this.hiddenIds.get(this.scope(room));
    return ids ? [...ids] : null;
  }
  async setMessageHidden(value: Room | number, messageId: number, hidden: boolean): Promise<number[]> {
    const room = this.room(value), e = this.epoch, guard = this.archiveGuard(e, room);
    if (!id(messageId) || typeof hidden !== 'boolean') throw new ChatError('invalid_message');
    return this.serial(async () => {
      guard();
      if (hidden) {
        const message = this.histories.get(this.scope(room))?.messages.find(row => row.id === messageId);
        if (!message) throw new ChatError('message_unavailable', 404);
        if (message.author_user_id !== this.account?.user_id) throw new ChatError('forbidden', 403);
      }
      const previous = await this.loadHidden(room, guard), next = new Set(previous); guard();
      if (hidden) {
        if (!next.has(messageId) && next.size >= 5000) throw new ChatError('local_hide_quota');
        next.add(messageId);
      } else next.delete(messageId);
      await this.storage.setItem(`${this.scope(room)}hidden-message-ids`, JSON.stringify([...next])); guard();
      this.hiddenIds.set(this.scope(room), next); return [...next];
    });
  }
  async newer(value: Room | number): Promise<History> {
    const room = this.room(value), last = this.histories.get(this.scope(room))?.messages.at(-1)?.id;
    return last ? this.navigateHistory(room, 'after', last) : this.latest(room);
  }
  private sliceHistory(slice: ArchiveSlice, browsing: boolean): History {
    return { api_version: 2, messages: copy(slice.messages), next_before_id: slice.older.kind === 'end' ? null : slice.messages[0]?.id ?? slice.older.cursor,
      archive: { older: copy(slice.older), newer: copy(slice.newer), partial: slice.partial, browsing, latestId: slice.latestId, unverified: slice.unverified } };
  }
  private mergeWindow(old: History | undefined, slice: ArchiveSlice, direction: 'before' | 'after'): History {
    // Legacy rows can contain internal holes. Never carry provisional islands into a proven cursor.
    if (old?.archive?.unverified && !slice.unverified && slice.messages.length) old = undefined;
    const rows = new Map<number, Message>(); for (const row of old?.messages ?? []) rows.set(row.id, row); for (const row of slice.messages) rows.set(row.id, row);
    const ordered = [...rows.values()].sort((a, b) => a.id - b.id), candidates = direction === 'before' ? ordered : [...ordered].reverse();
    const selected: Message[] = []; let used = 2;
    for (const message of candidates) {
      const size = new TextEncoder().encode(JSON.stringify(message)).length + (selected.length ? 1 : 0);
      if (selected.length >= ARCHIVE_LIMITS.windowMessages || used + size > ARCHIVE_LIMITS.windowBytes - 2048) break;
      used += size; selected.push(message);
    }
    if (direction === 'after') selected.reverse();
    const older = direction === 'before' ? slice.older : old?.archive?.older ?? slice.older;
    const newer = direction === 'after' ? slice.newer : old?.archive?.newer ?? slice.newer;
    const trimOlder = selected[0]?.id !== ordered[0]?.id, trimNewer = selected.at(-1)?.id !== ordered.at(-1)?.id;
    const metadata = { older: trimOlder ? { kind: 'cached' as const, cursor: selected[0]!.id } : older,
      newer: trimNewer ? { kind: 'cached' as const, cursor: selected.at(-1)!.id } : newer,
      partial: slice.partial || old?.archive?.partial === true, browsing: true, latestId: slice.latestId,
      unverified: slice.unverified || old?.archive?.unverified === true };
    return { api_version: 2, messages: copy(selected), next_before_id: metadata.older.kind === 'end' ? null : selected[0]?.id ?? metadata.older.cursor, archive: metadata };
  }
  private async navigateHistory(room: Room, direction: 'before' | 'after', anchorId: number): Promise<History> {
    if (!id(anchorId)) throw new ChatError('invalid_before_id');
    const scope = this.scope(room), pump = `${scope}${direction}/${anchorId}`, running = this.historyPumps.get(pump); if (running) return running;
    const e = this.epoch, version = (this.windowVersions.get(scope) ?? 0) + 1;
    this.windowVersions.set(scope, version); this.browsing.add(scope);
    const run = (async () => {
      const guard = this.archiveGuard(e, room);
      const oldWindow = this.histories.get(scope);
      const provisionalLast = oldWindow?.archive?.unverified ? oldWindow.messages.at(-1)?.id : undefined;
      const revalidate = direction === 'before' && !this.disconnected && provisionalLast !== undefined;
      // The provisional first row may be below an internal hole: validate from the visible upper edge.
      const verifiedAnchor = revalidate && provisionalLast! < Number.MAX_SAFE_INTEGER ? provisionalLast! + 1 : undefined;
      const query: ArchiveQuery = { direction: revalidate && verifiedAnchor === undefined ? 'latest' : direction,
        anchorId: revalidate ? verifiedAnchor : anchorId, limit: ARCHIVE_LIMITS.pageMessages, maxBytes: ARCHIVE_LIMITS.pageBytes };
      let slice = await this.serial(async () => { guard(); const result = await this.archive.read(this.archiveScope(room), query, guard); guard(); return result; });
      if (direction === 'before' && !this.disconnected && (revalidate || slice.unverified || !slice.messages.length && slice.older.kind !== 'end')) {
        await this.fetchHistoryPage(room, revalidate ? verifiedAnchor : anchorId, e);
        slice = await this.serial(async () => { guard(); const result = await this.archive.read(this.archiveScope(room), query, guard); guard(); return result; });
      }
      return this.serial(async () => {
        guard(); const old = this.histories.get(scope);
        if (version !== this.windowVersions.get(scope)) return copy(old ?? this.sliceHistory(slice, this.browsing.has(scope)));
        const window = this.mergeWindow(revalidate ? undefined : old, slice, direction); await this.cacheHistory(room, window, e); guard(); return copy(window);
      });
    })();
    this.historyPumps.set(pump, run);
    try { return await run; }
    catch (error) { return this.historyFailure(room, e, error); }
    finally { if (this.historyPumps.get(pump) === run) this.historyPumps.delete(pump); }
  }
  private async fetchHistoryPage(room: Room, beforeId: number | undefined, e: number): Promise<History> {
    this.requireContent(room);
    const raw=await this.request(`/bwork/api/v2/rooms/${room.id}/messages${beforeId ? `?before_id=${beforeId}` : ''}`, e);
    await this.assertContentResponse(raw,room);const page = this.validHistory(raw);
    const guard = this.archiveGuard(e, room, true);
    await this.serial(async () => { guard(); await this.archive.commitPage(this.archiveScope(room), { beforeId: beforeId ?? null, history: page }, guard); guard(); });
    return page;
  }
  private async readHistory(room: Room, beforeId: number | undefined, e: number, committed?: (history: History) => void): Promise<History> {
    if (beforeId !== undefined && !id(beforeId)) throw new ChatError('invalid_before_id');
    try {
      const page = await this.fetchHistoryPage(room, beforeId, e);
      await this.serial(async () => {
        const guard = this.archiveGuard(e, room, true); guard();
        const key = this.scope(room), old = this.histories.get(key);
        if (!page.messages.length && page.next_before_id === null) this.browsing.delete(key);
        if (old && this.browsing.has(key)) {
          const changed = new Map(page.messages.map(message => [message.id, message]));
          const last = old.messages.at(-1)?.id ?? 0, latestId = page.messages.at(-1)?.id ?? null;
          const updated = { ...old, messages: old.messages.map(message => changed.get(message.id) ?? message) };
          if (updated.archive && latestId !== null) updated.archive = { ...updated.archive, latestId,
            newer: latestId > last ? { kind: 'gap', cursor: last || null } : updated.archive.newer };
          await this.cacheHistory(room, updated, e);
        } else {
          const slice = await this.archive.read(this.archiveScope(room), { direction: 'latest', limit: ARCHIVE_LIMITS.windowMessages, maxBytes: ARCHIVE_LIMITS.windowBytes }, guard); guard();
          await this.cacheHistory(room, this.sliceHistory(slice, false), e);
        }
        // Capture the real internal object while the storage mutex is held.
        // A later replacement can invalidate its consumer without trusting a caller page.
        committed?.(this.histories.get(key)!);
      });
      return copy(this.histories.get(this.scope(room))!);
    } catch (error) { return this.historyFailure(room, e, error); }
  }
  private async historyFailure(room: Room, e: number, error: unknown): Promise<never> {
    if (e === this.epoch && error instanceof ChatError && error.status === 401) await this.invalidate(e);
    else if (e === this.epoch && denied(error)) await this.serial(async () => { await this.dropRoom(room, e); await this.persistIdentity(e); });
    else if (e === this.epoch && !(error instanceof ArchiveError) && (!(error instanceof ChatError) || !error.status)) { this.disconnected = true; this.failures++; }
    throw error;
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
        const result = await this.request(`/bwork/api/v2/rooms/${room.id}/messages/${messageId}/receipts`, e, undefined, false, { csrf_token: this.account.csrf_token, kind });
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
  async flush(): Promise<FlushResult> {
    if (this.pumping) return this.pumping;
    const e = this.epoch;
    const pages = new Map<number, { room: Room; accountScope: string | null; version: number; history: History }>();
    const prunePages = () => {
      for (const [id, page] of pages) if (this.histories.get(this.scope(page.room)) !== page.history) pages.delete(id);
    };
    const result: FlushResult = { historyFor: value => {
      this.fence(e);
      const account = this.requireIdentity();
      if (account.permissions.chat_view !== true) throw new ChatError('forbidden', 403);
      if (this.leaseRemainingMs <= 0) throw new ChatError('offline_expired');
      const current = this.room(value), page = pages.get(current.id);
      if (!page) return null;
      this.room(page.room); // A numeric selector must not cross a membership period either.
      if (page.accountScope !== this.accountScope) throw new ChatError('stale_session');
      const key = this.scope(current);
      if ((this.windowVersions.get(key) ?? 0) !== page.version || this.histories.get(key) !== page.history) return null;
      return copy(page.history);
    } };
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
          const ack = await this.request(`/bwork/api/v2/rooms/${room.id}/messages`, e, payload);
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
          pages.delete(room.id);
          try {
            const key = this.scope(room), version = this.windowVersions.get(key) ?? 0;
            let committed: History | undefined;
            await this.readHistory(room, undefined, e, history => {
              if ((this.windowVersions.get(key) ?? 0) === version) committed = history;
            });
            prunePages();
            if (committed && this.histories.get(key) === committed && (this.windowVersions.get(key) ?? 0) === version)
              pages.set(room.id, { room: copy(room), accountScope: this.accountScope, version, history: committed });
          }
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
      prunePages();
      return result;
    })();
    this.pumping = run;
    try { return await run; } finally { if (this.pumping === run) this.pumping = null; }
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
    const result = await this.request('/bwork/api/v2/rooms', e, { api_version: 2, ...payload, client_uuid: uuid });
    if (result.api_version !== 2 || !id(result.room_id) || !id(result.membership_id)) throw new ChatError('invalid_group_ack');
    await this.serial(async () => { this.fence(e); await this.storage.removeItem(key); });
    await this.refresh(); this.fence(e); return result as { api_version: 2; room_id: number; membership_id: number; replayed: boolean };
  }
  async candidates(companyId: number, q = ''): Promise<{ api_version: 2; users: { user_id: number; name: string }[] }> {
    this.requireIdentity(); if (!id(companyId) || !this.account?.company_ids.includes(companyId)) throw new ChatError('company_denied', 403);
    const route = this.account.mobile_policy ? 'mobile/candidates' : 'member-candidates';
    return this.request(`/bwork/api/v2/${route}?company_id=${companyId}&q=${encodeURIComponent(q)}`, this.epoch);
  }
  async directOpen(companyId: number, userId: number) {
    const e = this.epoch;
    const result = await this.write('/bwork/api/v2/mobile/direct', { company_id: companyId, user_id: userId, client_uuid: this.uuid() });
    await this.refresh(); this.fence(e); return result as { api_version: 2; room_id: number; membership_id: number; replayed: boolean };
  }
  async policy(companyId: number): Promise<Policy> {
    this.requireIdentity(); return this.request(`/bwork/api/v2/mobile/policy?company_id=${companyId}`, this.epoch);
  }
  async setPolicy(companyId: number, enabled: boolean): Promise<Policy> {
    const e = this.epoch;
    const result = await this.write('/bwork/api/v2/mobile/policy', { company_id: companyId, direct_enabled: enabled });
    await this.refresh(); this.fence(e); return result as Policy;
  }
  async groupInfo(value: Room | number): Promise<GroupInfo> {
    const e = this.epoch; const room = this.room(value);
    const result = object(await this.request(`/bwork/api/v2/rooms/${room.id}/group`, e));
    this.room(room); this.fence(e);
    const detail = object(result.room);
    if (result.api_version !== 2 || detail.id !== room.id || detail.company_id !== room.company_id
        || typeof detail.name !== 'string' || !detail.name.trim() || new TextEncoder().encode(detail.name).length > 256
        || typeof detail.is_group !== 'boolean' || detail.is_group !== room.is_group
        || !Number.isSafeInteger(detail.avatar_version) || detail.avatar_version < 0
        || typeof detail.description !== 'string' || groupDescription(detail.description) !== detail.description
        || typeof result.can_manage !== 'boolean' || (!detail.is_group && result.can_manage)
        || !Array.isArray(result.members) || result.members.length > 50
        || result.members.some((member: any) => !id(member?.user_id) || typeof member.name !== 'string'
          || new TextEncoder().encode(member.name).length > 1024 || typeof member.is_admin !== 'boolean')
        || new Set(result.members.map((member: any) => member.user_id)).size !== result.members.length
        || !result.members.some((member: any) => member.user_id === this.account?.user_id)) throw new ChatError('invalid_group');
    this.roomRows = this.roomRows.map(row => row.id === room.id ? { ...row, avatar_version: detail.avatar_version } : row);
    return copy(result as GroupInfo);
  }
  async groupChange(value: Room | number, change: { action: string; name?: string; description?: string; user_id?: number }) {
    const e = this.epoch;
    const room = this.room(value);
    if (change.action === 'set_description') change = { action: 'set_description', description: groupDescription(change.description) };
    const result = await this.write(`/bwork/api/v2/rooms/${room.id}/group`, change);
    if (result?.api_version !== 2 || result.room_id !== room.id || result.action !== change.action) throw new ChatError('invalid_group');
    await this.refresh(); this.fence(e); return result;
  }
  /** Online administrative mutation, not a durable message upload and never automatically retried. */
  async setGroupAvatar(value: Room | number, input: GroupAvatarInput): Promise<GroupInfo> {
    const e = this.epoch;
    if (this.offline) throw new ChatError('connection_failed');
    await this.refresh(); this.fence(e);
    const room = this.room(value); const before = await this.groupInfo(room);
    if (!before.room.is_group || !before.can_manage) throw new ChatError('group_manage_denied', 403);
    if (!this.avatarUpload) throw new ChatError('avatar_invalid');
    try {
      const ack = await this.avatarUpload(room, input, this.account!.csrf_token!, this.abort.signal);
      this.fence(e); this.room(room);
      if (ack?.api_version !== 2 || ack.room_id !== room.id || !Number.isSafeInteger(ack.avatar_version)
          || ack.avatar_version <= before.room.avatar_version) throw new ChatError('invalid_group');
      await this.refresh(); this.fence(e);
      const after = await this.groupInfo(room);
      if (after.room.avatar_version !== ack.avatar_version) throw new ChatError('invalid_group');
      return after;
    } catch (error) {
      this.fence(e);
      if (error instanceof ChatError && ([400, 401, 403, 413, 415].includes(error.status)
          || ['avatar_invalid', 'stale_session'].includes(error.code))) throw error;
      // A later version is not proof that our POST committed: another admin may have written it.
      try { await this.refresh(); this.fence(e); await this.groupInfo(room); } catch { this.fence(e); }
      throw new ChatError('avatar_uncertain');
    }
  }
}

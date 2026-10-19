/** Android trial native boundary. No credential extraction, telemetry or public media URLs. */
import { AppState, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import * as FS from 'expo-file-system/legacy';
import BlobUtil from 'react-native-blob-util';
import type { FetchBlobResponse, StatefulPromise } from 'react-native-blob-util';
import { ChatEngine, ChatError } from './core/ChatEngine';
import type { Attachment, Bootstrap, GroupAvatarAck, GroupAvatarInput, History, Pending, Request, Room } from './core/ChatEngine';
import { actorPattern, mediaFilePattern, nativeSessionOptions, retainNativeFile, scopePattern, trustedMedia, validThumbnail } from './core/nativeBoundary';
import { nativeSessionTrace, networkFailure } from './core/loginDiagnostics';
import { historyArchive, mediaCacheCatalog } from './storage/nativeArchive';
import { OrdersOnlySession, ordersOnlyBootstrap } from './session/OrdersOnlySession';
import { OrdersEngine } from './orders/core/OrdersEngine';
import { OrdersError, type OrdersIdentity } from './orders/core/types';
import { ordersNativeRequest } from './orders/transport';
import { TasksEngine } from './tasks/core/TasksEngine';
import { TasksError, type TaskIdentity } from './tasks/core/types';
import { tasksNativeRequest } from './tasks/transport';
import { LeadershipEngine } from './leadership/core/LeadershipEngine';
import { LeadershipError, type LeadershipIdentity } from './leadership/core/types';
import { leadershipNativeRequest } from './leadership/transport';
import { LeadershipSnapshots } from './leadership/LeadershipSnapshots';
import type { SnapshotAuthority } from './leadership/LeadershipSnapshots';
import { NotificationsEngine, notificationScope, type NotificationAuthority } from './notifications/NotificationsEngine';
import { nativePush } from './notifications/native';

export const config = Object.freeze({
  origin: (process.env.EXPO_PUBLIC_ODOO_ORIGIN ?? '').trim(),
  database: (process.env.EXPO_PUBLIC_ODOO_DATABASE ?? '').trim(),
});
const MAX_FILE = 10 * 1024 * 1024;
const MAX_STAGED = 50 * 1024 * 1024;
const MAX_CACHE = 128 * 1024 * 1024;
const MAX_CACHE_FILES = 5000;
const MAX_THUMBNAIL = 128 * 1024;
const mediaRoot = `${FS.documentDirectory ?? ''}odoo-chat-media/`;
const tasks = new Set<StatefulPromise<FetchBlobResponse>>();
const ordersOnlySession = new OrdersOnlySession();
let ordersEngine: OrdersEngine | undefined;
let workTasksEngine: TasksEngine | undefined;
let leadershipEngine: LeadershipEngine | undefined;
let leadershipSnapshots: LeadershipSnapshots | undefined;
let notificationsEngine: NotificationsEngine | undefined;
// Chat's disconnected state also covers invalid/server responses; those must
// never authorize a historical financial fallback.
let leadershipOfflineScope: string | null = null;
let ordersConnectivity = true;
let ordersAccessEpoch = 0;
let ordersRefresh: { generation: number; accessEpoch: number; operation: Promise<Bootstrap> } | null = null;
export const subscribeOrdersOnlySession = ordersOnlySession.subscribe;
export const ordersOnlySnapshot = ordersOnlySession.snapshot;
export function setOrdersConnectivity(connected: boolean): void {
  if (!connected && ordersConnectivity) ordersAccessEpoch++;
  ordersConnectivity = connected;
  if (!connected) ordersOnlySession.lock();
  if (!connected) workTasksEngine?.cancelReads();
  if (!connected) leadershipEngine?.cancelReads();
}
const reservations = new Map<string, { epoch: number; at: number }>();
let generation = 0;
let engine: NativeChatEngine | undefined;
let mediaWork: Promise<unknown> = Promise.resolve();
// Network waits must never own the file mutation queue. One automatic preview
// and one deliberate original may transfer at once; taps do not queue behind
// thumbnails. Cache writes, quota, eviction and staging remain serialized.
const mediaTransfers: Record<MediaVariant, Promise<unknown>> = { preview: Promise.resolve(), original: Promise.resolve() };
const mediaDownloads = new Map<string, { operation: Promise<LocalMediaLease>; readers: number }>();
const mediaDownloadReservations = new Map<object, { actor: string; bytes: number }>();
type CacheEntry = { uri: string; bytes: number; sha256: string | null; usedAt: number };
type ActorFiles = { cache: Map<string, CacheEntry>; stages: Map<string, number>; cacheBytes: number; stageBytes: number };
const actorFiles = new Map<string, ActorFiles>();
const mediaPins = new Map<string, Set<object>>();
let discoveredActors = false;
export type MediaVariant = 'preview' | 'original';
export interface LocalMediaLease { uri: string; release(): void }
const extensions: Record<string, string> = {
  'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
  'audio/mp4': '.m4a', 'application/pdf': '.pdf', 'text/plain': '.txt',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
};
export interface GroupAvatarImage { uri: string; version: number; key: string }
type AvatarEntry = GroupAvatarImage & { room: Room; actor: string; epoch: number; bytes: number };
const avatars = new Map<string, AvatarEntry>();
const avatarReads = new Map<string, Promise<GroupAvatarImage>>();
let avatarEpoch = 0;
const avatarListeners = new Set<() => void>();
const AVATAR_CACHE_BYTES = 4 * 1024 * 1024; // Actual ASCII data-URI bytes, not a native heap claim.
const avatarNotify = () => { for (const listener of avatarListeners) { try { listener(); } catch { /* Presentation observers cannot change transport results. */ } } };
export function subscribeGroupAvatars(listener: () => void): () => void { avatarListeners.add(listener); return () => { avatarListeners.delete(listener); }; }
export function hasGroupAvatar(key: string): boolean { return avatars.has(key); }
export function clearGroupAvatars(): void { avatarEpoch++; avatarReads.clear(); if (avatars.size) { avatars.clear(); avatarNotify(); } }
type MemberAvatar = { uri: string; at: number };
const memberAvatars = new Map<string, MemberAvatar>();
const memberAvatarReads = new Map<string, Promise<string>>();
let memberAvatarEpoch = 0;
export function clearMemberAvatars(): void { memberAvatarEpoch++; memberAvatars.clear(); memberAvatarReads.clear(); }
/** Existing protected room-member endpoint; never a guessed/public employee URL. */
export async function readMemberAvatar(room: Room, userId: number): Promise<string> {
  if (AppState.currentState !== 'active' || !Number.isSafeInteger(userId) || userId <= 0) throw new ChatError('avatar_missing', 404);
  if (getEngine().identity?.permissions.chat_view !== true) throw new ChatError('forbidden', 403);
  const snapshot = scope(room), epoch = memberAvatarEpoch;
  const key = `${snapshot.key}/${snapshot.epoch}/${room.company_id}/${room.id}/${room.membership_id}/${userId}`;
  const valid = () => { fence(room, snapshot); if (getEngine().identity?.permissions.chat_view !== true || epoch !== memberAvatarEpoch || AppState.currentState !== 'active') throw new ChatError('stale_session'); };
  valid();
  const cached = memberAvatars.get(key);
  if (cached && Date.now() - cached.at < 60000) { memberAvatars.delete(key); memberAvatars.set(key, cached); return cached.uri; }
  memberAvatars.delete(key);
  if (getEngine().offline) throw new ChatError('avatar_missing', 404);
  const running = memberAvatarReads.get(key); if (running) return running;
  if (memberAvatarReads.size >= 8) throw new ChatError('avatar_missing', 404);
  const pending = (async () => {
    const response = await sessionNative(`/bchat/api/v2/rooms/${room.id}/members/${userId}/avatar`, 'GET', { Accept: 'image/png' }, undefined, undefined, undefined, 256 * 1024);
    valid(); const headers = headersOf(response);
    if ((headers['content-type'] ?? '').split(';')[0].trim() !== 'image/png') throw new ChatError('invalid_response');
    const encoded = await response.base64();
    if (typeof encoded !== 'string' || encoded.length > 349528 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw new ChatError('invalid_response');
    const raw = BlobUtil.base64.decode(encoded);
    const size = (offset: number) => raw.charCodeAt(offset) * 0x1000000 + (raw.charCodeAt(offset + 1) << 16) + (raw.charCodeAt(offset + 2) << 8) + raw.charCodeAt(offset + 3);
    if (raw.length < 24 || raw.length > 256 * 1024 || raw.slice(0, 8) !== '\x89PNG\r\n\x1a\n' || raw.slice(12, 16) !== 'IHDR'
      || size(8) !== 13 || size(16) < 1 || size(16) > 128 || size(20) < 1 || size(20) > 128
      || headers['content-length'] !== undefined && Number(headers['content-length']) !== raw.length) throw new ChatError('invalid_response');
    valid(); const uri = `data:image/png;base64,${encoded}`;
    memberAvatars.set(key, { uri, at: Date.now() });
    while (memberAvatars.size > 128 || [...memberAvatars.values()].reduce((sum, item) => sum + item.uri.length, 0) > 4 * 1024 * 1024) memberAvatars.delete(memberAvatars.keys().next().value!);
    return uri;
  })();
  memberAvatarReads.set(key, pending);
  try { return await pending; } finally { if (memberAvatarReads.get(key) === pending) memberAvatarReads.delete(key); }
}
function pruneGroupAvatars(all = false): void {
  let removed = false;
  for (const [key, item] of avatars) {
    try {
      if (all || !engine || engine.identity?.permissions.chat_view !== true) throw new Error();
      const live = scope(item.room);
      const current = engine.rooms().find(room => room.id === item.room.id)!;
      if (item.epoch !== generation || live.key !== item.actor || current.avatar_version !== item.version) throw new Error();
    } catch { avatars.delete(key); removed = true; }
  }
  if (removed) avatarNotify();
}
function avatarScope(current: ChatEngine, room: Room) {
  if (current !== getEngine() || current.identity?.permissions.chat_view !== true) throw new ChatError('stale_session');
  const snapshot = scope(room);
  if (!room.is_group) throw new ChatError('not_a_group');
  return snapshot;
}
/** Private, memory-only group images; message-media ACLs and disk caching do not apply. */
export async function readGroupAvatar(current: ChatEngine, room: Room): Promise<GroupAvatarImage> {
  const snapshot = avatarScope(current, room);
  const version = current.rooms().find(row => row.id === room.id)?.avatar_version ?? room.avatar_version ?? 0;
  const key = `${snapshot.key}/${snapshot.epoch}/${avatarEpoch}/${room.company_id}/${room.id}/${room.membership_id}/${version}`;
  const existing = avatarReads.get(key); if (existing) return existing;
  const pending = loadGroupAvatar(current, room); avatarReads.set(key, pending);
  try { return await pending; } finally { if (avatarReads.get(key) === pending) avatarReads.delete(key); }
}
async function loadGroupAvatar(current: ChatEngine, room: Room): Promise<GroupAvatarImage> {
  pruneGroupAvatars();
  const snapshot = avatarScope(current, room);
  const readEpoch = avatarEpoch;
  let version = current.rooms().find(row => row.id === room.id)?.avatar_version ?? room.avatar_version ?? 0;
  for (let attempt = 0; attempt < 2; attempt++) {
    if (!Number.isSafeInteger(version) || version <= 0) throw new ChatError('avatar_missing', 404);
    const key = `${snapshot.key}/${room.company_id}/${room.id}/${room.membership_id}/${version}`;
    const cached = avatars.get(key);
    if (cached) { avatars.delete(key); avatars.set(key, cached); return { uri: cached.uri, version, key }; }
    if (current.offline) throw new ChatError('avatar_missing', 404);
    try {
      const response = await sessionNative(`/bchat/api/v2/rooms/${room.id}/avatar?version=${version}`, 'GET', { Accept: 'image/png' }, undefined, undefined, undefined, 256 * 1024);
      fence(room, snapshot); avatarScope(current, room);
      if (readEpoch !== avatarEpoch) throw new ChatError('stale_session');
      const headers = headersOf(response);
      if (!/^(0|[1-9]\d*)$/.test(headers['x-bchat-avatar-version'] ?? '')) throw new ChatError('invalid_response');
      if (Number(headers['x-bchat-avatar-version']) !== version) {
        if (attempt) throw new ChatError('invalid_response');
        const detail = await current.groupInfo(room); fence(room, snapshot);
        version = detail.room.avatar_version; pruneGroupAvatars(); continue;
      }
      if ((headers['content-type'] ?? '').split(';')[0].trim() !== 'image/png') throw new ChatError('invalid_response');
      const encoded = await response.base64();
      if (typeof encoded !== 'string' || encoded.length > 349528 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw new ChatError('invalid_response');
      const raw = BlobUtil.base64.decode(encoded);
      const size = (offset: number) => ((raw.charCodeAt(offset) * 0x1000000) + (raw.charCodeAt(offset + 1) << 16) + (raw.charCodeAt(offset + 2) << 8) + raw.charCodeAt(offset + 3));
      if (raw.length < 24 || raw.length > 256 * 1024 || raw.slice(0, 8) !== '\x89PNG\r\n\x1a\n' || raw.slice(12, 16) !== 'IHDR'
          || size(8) !== 13 || size(16) <= 0 || size(16) > 256 || size(20) <= 0 || size(20) > 256
          || headers['content-length'] !== undefined && Number(headers['content-length']) !== raw.length) throw new ChatError('invalid_response');
      fence(room, snapshot); avatarScope(current, room);
      if (readEpoch !== avatarEpoch || current.rooms().find(row => row.id === room.id)?.avatar_version !== version) throw new ChatError('stale_session');
      const uri = `data:image/png;base64,${encoded}`;
      avatars.set(key, { uri, version, key, room: { ...room }, actor: snapshot.key, epoch: generation, bytes: uri.length });
      while ([...avatars.values()].reduce((sum, item) => sum + item.bytes, 0) > AVATAR_CACHE_BYTES) avatars.delete(avatars.keys().next().value!);
      avatarNotify(); return { uri, version, key };
    } catch (error) { avatars.delete(key); avatarNotify(); throw error; }
  }
  throw new ChatError('invalid_response');
}
async function uploadGroupAvatar(room: Room, input: GroupAvatarInput, csrfToken: string, signal: AbortSignal): Promise<GroupAvatarAck> {
  const snapshot = avatarScope(getEngine(), room);
  if (!/^(file|content):\/\//.test(input.uri) || !['image/jpeg', 'image/png', 'image/webp'].includes(input.mime)) throw new ChatError('avatar_invalid');
  const root = FS.cacheDirectory ?? FS.documentDirectory;
  if (!root) throw new ChatError('avatar_invalid');
  const temporary = `${root}odoo-group-avatar-${Crypto.randomUUID()}${extensions[input.mime]}`;
  try {
    await FS.copyAsync({ from: input.uri, to: temporary }); fence(room, snapshot);
    const info = await FS.getInfoAsync(temporary);
    if (!info.exists || info.isDirectory || info.size <= 0 || info.size > 2 * 1024 * 1024) throw new ChatError('avatar_invalid', 413);
    if (signal.aborted) throw new ChatError('stale_session');
    fence(room, snapshot); avatarScope(getEngine(), room);
    const response = await sessionNative(`/bchat/api/v2/rooms/${room.id}/avatar`, 'POST', { Accept: 'application/json', 'Content-Type': 'multipart/form-data' }, [
      { name: 'csrf_token', data: csrfToken },
      { name: 'file', filename: `group${extensions[input.mime]}`, type: input.mime, data: BlobUtil.wrap(decodeURI(temporary.replace(/^file:\/\//, ''))) },
    ], signal);
    fence(room, snapshot);
    if (!(headersOf(response)['content-type'] ?? '').includes('application/json')) throw new ChatError('invalid_response');
    let ack: GroupAvatarAck; try { ack = response.json(); } catch { throw new ChatError('invalid_response'); }
    clearGroupAvatars(); return ack;
  } finally { await FS.deleteAsync(temporary, { idempotent: true }).catch(() => undefined); }
}
function fixedURL(path: string): string {
  const origin = new URL(config.origin);
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash || !config.database) throw new ChatError('configuration_required');
  if (!path.startsWith('/bchat/api/v2/') && !path.startsWith('/web/session/')) throw new ChatError('invalid_path');
  const url = new URL(path, origin);
  if (url.origin !== origin.origin) throw new ChatError('invalid_path');
  return url.href;
}
function cancelNative(): void {
  leadershipOfflineScope = null;
  generation++;
  leadershipEngine?.clear();
  ordersOnlySession.lock();
  clearGroupAvatars();
  clearMemberAvatars();
  mediaPins.clear();
  for (const task of tasks) task.cancel(() => undefined);
  tasks.clear();
}
function headersOf(response: FetchBlobResponse): Record<string, string> {
  if (!response.info()?.headers || typeof response.info().headers !== 'object') throw new ChatError('native_response_missing');
  return Object.fromEntries(Object.entries(response.info().headers as Record<string, unknown>).map(([key, value]) => [key.toLowerCase(), String(value)]));
}
async function sessionNative(path: string, method: 'GET' | 'POST', headers: Record<string, string>, body?: unknown, signal?: AbortSignal, output?: string, byteLimit = 2 * 1024 * 1024): Promise<FetchBlobResponse> {
  // whatwg-fetch ignores redirect:'error' on this RN version. This native
  // client's no-follow option is enforced in Android OkHttp. BlobUtil obtains
  // OkHttpClientProvider's native cookie jar; no Cookie value enters JS.
  if (Platform.OS !== 'android') throw new ChatError('android_trial_required');
  if (signal?.aborted) throw new ChatError('stale_session');
  const epoch = generation;
  // Odoo 19 treats X-Odoo-Database without a database-bound session as stateless
  // (session.can_save=false). Authenticate selects its DB through JSON params.db;
  // it must be allowed to persist that session before the scoped bootstrap.
  const statefulAuthenticate = method === 'POST' && path === '/web/session/authenticate';
  const task = BlobUtil.config({ ...nativeSessionOptions, ...(output ? { path: decodeURI(output.replace(/^file:\/\//, '')), overwrite: true } : {}) })
    .fetch(method, fixedURL(path), { ...headers, ...(statefulAuthenticate ? {} : { 'X-Odoo-Database': config.database }) }, body);
  let tooLarge = false;
  let sessionTrace: string | undefined;
  const abort = () => { task.cancel(() => undefined); };
  signal?.addEventListener('abort', abort); tasks.add(task);
  task.progress({ interval: 100 }, received => { if (received > byteLimit) { tooLarge = true; abort(); } });
  try {
    const response = await task;
    if (generation !== epoch || signal?.aborted) throw new ChatError('stale_session');
    if (tooLarge) throw new ChatError('file_too_large');
    // The native interceptor replaces this private header with bounded bits.
    // Snapshot it before redirect rejection and engine cleanup destroy the session.
    if (method === 'GET' && path === '/bchat/api/v2/bootstrap')
      sessionTrace = nativeSessionTrace(headersOf(response)['x-baseer-native-session']);
    const status = response.info()?.status;
    if (!Number.isInteger(status) || status < 100 || status > 599) throw new ChatError('native_response_missing');
    // BlobUtil's Android interceptor records the INITIAL URL as entry zero.
    const visited = response.info().redirects ?? [];
    if (status >= 300 && status < 400 || visited.length > 1 || visited.some(url => new URL(url).href !== fixedURL(path))) throw new ChatError('redirect_denied', status);
    if (status < 200 || status >= 300) {
      let code = status === 401 ? 'unauthenticated' : status === 403 ? 'forbidden' : 'request_failed';
      if (!output) { try {
        const value = response.json();
        if (value?.error?.data?.name === 'odoo.http.SessionExpiredException') code = 'session_expired';
        else if (typeof value?.error?.code === 'string' && value.error.code !== 'session_expired') code = value.error.code;
      } catch { /* Raw responses never enter UI/logs. */ } }
      throw new ChatError(code, status);
    }
    return response;
  } catch (error) {
    if (generation !== epoch || signal?.aborted) throw new ChatError('stale_session');
    if (tooLarge) throw new ChatError('file_too_large');
    if (error instanceof ChatError) {
      if (sessionTrace) error.sessionTrace = sessionTrace;
      throw error;
    }
    const failure = new ChatError('connection_failed');
    failure.networkFailure = networkFailure(error);
    throw failure;
  } finally { tasks.delete(task); signal?.removeEventListener('abort', abort); }
}
async function request(req: Request): Promise<unknown> {
  const headers: Record<string, string> = { Accept: 'application/json' }; let body: string | undefined;
  if (req.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(req.json); }
  if (req.form) { headers['Content-Type'] = 'application/x-www-form-urlencoded'; body = Object.entries(req.form).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&'); }
  const response = await sessionNative(req.path, req.method, headers, body, req.signal);
  if (!(headersOf(response)['content-type'] ?? '').includes('application/json')) throw new ChatError('invalid_response');
  let value: any;
  try { value = response.json(); } catch { throw new ChatError('invalid_response'); }
  if (value?.error?.data?.name === 'odoo.http.SessionExpiredException') throw new ChatError('session_expired', 401);
  if (value?.error?.data?.name === 'odoo.exceptions.AccessDenied') throw new ChatError('authentication_failed', 401);
  return value;
}
function serialMedia<T>(fn: () => Promise<T>): Promise<T> {
  const result = mediaWork.then(fn, fn); mediaWork = result.catch(() => undefined); return result;
}
function scope(room: Room): { uid: number; epoch: number; key: string } {
  const current = getEngine(); const uid = current.identity?.user_id;
  if (!uid || !current.rooms().some(r => r.id === room.id && r.company_id === room.company_id && r.membership_id === room.membership_id)) throw new ChatError('membership_changed', 403);
  return { uid, epoch: generation, key: `${new URL(config.origin).origin}|${config.database}|${uid}` };
}
function fence(room: Room, expected: ReturnType<typeof scope>): void {
  const actual = scope(room);
  if (actual.epoch !== expected.epoch || actual.uid !== expected.uid) throw new ChatError('stale_session');
}
function mediaFence(room: Room, expected: ReturnType<typeof scope>): void {
  fence(room, expected);
  if (getEngine().identity?.permissions.media !== true) throw new ChatError('forbidden', 403);
}
async function actorDirectory(key: string): Promise<string> {
  if (!FS.documentDirectory) throw new ChatError('native_storage_required');
  return `${mediaRoot}${await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, key)}/`;
}
function owned(uri: string): boolean {
  if (!FS.documentDirectory || !uri.startsWith(mediaRoot)) return false;
  const parts = uri.slice(mediaRoot.length).split('/');
  return parts.length === 3 && actorPattern.test(parts[0]) && scopePattern.test(parts[1]) && mediaFilePattern.test(parts[2]);
}
/** SQL catalog keys are digests, never native filesystem directory strings. */
function catalogActor(actorDirectory: string): string {
  const digest = actorDirectory.startsWith(mediaRoot) ? actorDirectory.slice(mediaRoot.length, -1) : '';
  if (!actorDirectory.endsWith('/') || !actorPattern.test(digest)) throw new ChatError('invalid_attachment');
  return digest;
}
async function removeOwned(uri: string): Promise<void> {
  if (!owned(uri)) throw new ChatError('invalid_attachment');
  await FS.deleteAsync(uri, { idempotent: true });
  const actor = uri.slice(0, uri.indexOf('/', mediaRoot.length) + 1);
  const state = actorFiles.get(actor);
  if (state) {
    const cached = state.cache.get(uri);
    if (cached) { state.cacheBytes -= cached.bytes; state.cache.delete(uri); }
    const staged = state.stages.get(uri);
    if (staged !== undefined) { state.stageBytes -= staged; state.stages.delete(uri); }
  }
  mediaPins.delete(uri);
  if (uri.split('/').at(-1)!.startsWith('media-') && !uri.endsWith('.part')) await mediaCacheCatalog.remove(catalogActor(actor), uri);
}
/** Reconcile legacy/cache files once per actor, never recursively on each image. */
async function loadActorFiles(actor: string, epoch = generation): Promise<ActorFiles> {
  const existing = actorFiles.get(actor); if (existing) return existing;
  const state: ActorFiles = { cache: new Map(), stages: new Map(), cacheBytes: 0, stageBytes: 0 };
  const saved = new Map<string, CacheEntry>();
  for (const item of await mediaCacheCatalog.list(catalogActor(actor))) {
    if (owned(item.uri) && item.uri.startsWith(actor) && !item.uri.split('/').at(-1)!.startsWith('stage-')
        && Number.isSafeInteger(item.bytes) && item.bytes > 0 && item.bytes <= MAX_FILE
        && /^[a-f0-9]{64}$/.test(item.sha256) && Number.isFinite(item.usedAt) && item.usedAt >= 0)
      saved.set(item.uri, item);
    else await mediaCacheCatalog.remove(catalogActor(actor), item.uri);
    if (epoch !== generation) throw new ChatError('stale_session');
  }
  const info = await FS.getInfoAsync(actor);
  if (info.exists && info.isDirectory) for (const directory of await FS.readDirectoryAsync(actor)) {
    if (!scopePattern.test(directory)) continue;
    const path = `${actor}${directory}/`, directoryInfo = await FS.getInfoAsync(path);
    if (!directoryInfo.exists || !directoryInfo.isDirectory) continue;
    for (const filename of await FS.readDirectoryAsync(path)) {
      if (!mediaFilePattern.test(filename)) continue;
      if (epoch !== generation) throw new ChatError('stale_session');
      const uri = `${path}${filename}`, stat = await FS.getInfoAsync(uri);
      if (!stat.exists || stat.isDirectory) continue;
      if (filename.startsWith('stage-')) { state.stages.set(uri, stat.size); state.stageBytes += stat.size; }
      else if (filename.endsWith('.part') || stat.size <= 0 || stat.size > MAX_FILE) {
        if (epoch !== generation) throw new ChatError('stale_session');
        await removeOwned(uri); saved.delete(uri);
      } else {
        const prior = saved.get(uri);
        state.cache.set(uri, { uri, bytes: stat.size, sha256: prior?.bytes === stat.size ? prior.sha256 : null,
          usedAt: prior?.usedAt ?? 0 });
        state.cacheBytes += stat.size; saved.delete(uri);
      }
    }
  }
  for (const uri of saved.keys()) { if (epoch !== generation) throw new ChatError('stale_session'); await mediaCacheCatalog.remove(catalogActor(actor), uri); }
  if (epoch !== generation) throw new ChatError('stale_session');
  state.cache = new Map([...state.cache.values()].sort((a, b) => a.usedAt - b.usedAt || a.uri.localeCompare(b.uri)).map(entry => [entry.uri, entry]));
  actorFiles.set(actor, state); return state;
}
async function capacity(actor: string, additional: number, stage = false, additionalFiles = additional > 0 ? 1 : 0): Promise<void> {
  const epoch = generation, state = await loadActorFiles(actor, epoch);
  if (stage) { if (state.stageBytes + additional > MAX_STAGED || state.stages.size >= 200 && additional > 0) throw new ChatError('media_quota'); return; }
  const victims = state.cache.values();
  while (state.cacheBytes + additional > MAX_CACHE || state.cache.size + additionalFiles > MAX_CACHE_FILES) {
    let victim: CacheEntry | undefined;
    for (const item of victims) if (!mediaPins.get(item.uri)?.size) { victim = item; break; }
    if (!victim) throw new ChatError('media_quota');
    if (epoch !== generation) throw new ChatError('stale_session');
    await removeOwned(victim.uri);
  }
}
async function hashFile(uri: string): Promise<string> { return BlobUtil.fs.hash(decodeURI(uri.replace(/^file:\/\//, '')), 'sha256'); }
async function verifyAttachment(room: Room, attachment: Attachment): Promise<void> {
  const snapshot = scope(room); const actor = await actorDirectory(snapshot.key);
  if (!owned(attachment.uri) || !attachment.uri.startsWith(`${actor}c${room.company_id}-r${room.id}-m${room.membership_id}/stage-`)) throw new ChatError('invalid_attachment');
  const info = await FS.getInfoAsync(attachment.uri);
  if (!info.exists || info.isDirectory || info.size !== attachment.size || await hashFile(attachment.uri) !== attachment.sha256) throw new ChatError('attachment_changed');
  fence(room, snapshot);
}
/** Own queued bytes are not acknowledged media. Resolve only an actual current
 * outbox stage; never accept a caller URI, create a cache/pin or fetch history. */
export async function localPendingImage(room: Room, clientUuid: string): Promise<string> {
  const snapshot = scope(room);
  const read = () => {
    mediaFence(room, snapshot);
    const current = getEngine();
    if (AppState.currentState !== 'active' || current.identity?.permissions.chat_view !== true
        || current.identity?.permissions.chat_send !== true) throw new ChatError('forbidden', 403);
    const pending = current.pending(room).find(item => item.client_uuid === clientUuid);
    const attachment = pending?.attachment;
    if (!pending || !['queued', 'sending'].includes(pending.state) || pending.room_id !== room.id
        || pending.company_id !== room.company_id || pending.membership_id !== room.membership_id
        || !attachment || attachment.kind !== 'image' || !['image/jpeg', 'image/png', 'image/webp'].includes(attachment.mime)
        || !owned(attachment.uri)) throw new ChatError('invalid_attachment');
    return attachment;
  };
  const attachment = read();
  // Upload ACK may add media_id/policy_version while this same owned stage is
  // still sending. Those server fields neither change its bytes nor grant a
  // message association; only the local stage identity participates here.
  const fingerprint = (value: Attachment) => JSON.stringify([value.uri, value.upload_uuid, value.kind, value.mime,
    value.size, value.sha256, value.name]);
  const expected = fingerprint(attachment);
  const guard = () => { if (fingerprint(read()) !== expected) throw new ChatError('stale_session'); };
  const actor = await actorDirectory(snapshot.key); guard();
  if (!attachment.uri.startsWith(`${actor}c${room.company_id}-r${room.id}-m${room.membership_id}/stage-`))
    throw new ChatError('invalid_attachment');
  const stat = await FS.getInfoAsync(attachment.uri); guard();
  if (!stat.exists || stat.isDirectory || stat.size !== attachment.size) throw new ChatError('attachment_changed');
  const sha256 = await hashFile(attachment.uri); guard();
  if (sha256 !== attachment.sha256) throw new ChatError('attachment_changed');
  return attachment.uri;
}
async function upload(room: Room, attachment: Attachment, csrfToken: string, signal: AbortSignal): Promise<{ media_id: number; policy_version?: number }> {
  const snapshot = scope(room); await verifyAttachment(room, attachment);
  const complete = async (mediaId: number) => {
    // Replaceable bytes, never a message association or permission. The outbox
    // still owns its stage; a failed cache optimization must not replay upload.
    await cacheUploadedImage(room, attachment, mediaId, snapshot).catch(() => undefined);
    fence(room, snapshot); return { media_id: mediaId };
  };
  const base = `/bchat/api/v2/rooms/${room.id}/uploads`;
  const reconciled = await request({ method: 'GET', path: `${base}/${attachment.upload_uuid}/reconcile`, signal }) as Record<string, unknown>;
  fence(room, snapshot);
  if (reconciled.api_version !== 2 || reconciled.membership_id !== room.membership_id || reconciled.room_id !== room.id || reconciled.upload_uuid !== attachment.upload_uuid) throw new ChatError('invalid_response');
  if (Number.isSafeInteger(reconciled.media_id) && Number(reconciled.media_id) > 0 && ['staged', 'attached'].includes(String(reconciled.state))) return complete(Number(reconciled.media_id));
  if (reconciled.state !== 'missing') throw new ChatError('upload_pending');
  const metadata = { api_version: 2, membership_id: room.membership_id, upload_uuid: attachment.upload_uuid, kind: attachment.kind, mime: attachment.mime, size: attachment.size, sha256: attachment.sha256, name: attachment.name };
  const body = [{ name: 'csrf_token', data: csrfToken }, { name: 'metadata', data: JSON.stringify(metadata) },
    { name: 'file', filename: attachment.name, type: attachment.mime, data: BlobUtil.wrap(decodeURI(attachment.uri.replace(/^file:\/\//, ''))) }];
  const response = await sessionNative(base, 'POST', { Accept: 'application/json', 'Content-Type': 'multipart/form-data' }, body, signal);
  let result: any; try { result = response.json(); } catch { throw new ChatError('invalid_response'); }
  fence(room, snapshot);
  if (result.api_version !== 2 || result.upload_uuid !== attachment.upload_uuid || !Number.isSafeInteger(result.media_id) || result.media_id <= 0 || !['staged', 'attached'].includes(result.state)) throw new ChatError('invalid_response');
  return complete(result.media_id);
}
/** Cache the sender's verified image without moving/retaining its outbox stage.
 * localMediaLease still requires canonical history, current membership and SHA
 * before any display; an upload ACK alone cannot make these bytes readable. */
async function cacheUploadedImage(room: Room, attachment: Attachment, mediaId: number, snapshot: ReturnType<typeof scope>): Promise<void> {
  if (attachment.kind !== 'image' || !['image/jpeg', 'image/png', 'image/webp'].includes(attachment.mime)) return;
  return serialMedia(async () => {
    mediaFence(room, snapshot);
    if (getEngine().identity?.permissions.chat_send !== true) throw new ChatError('forbidden', 403);
    await verifyAttachment(room, attachment); mediaFence(room, snapshot);
    const actor = await actorDirectory(snapshot.key);
    const directory = `${actor}c${room.company_id}-r${room.id}-m${room.membership_id}/`;
    const uri = `${directory}media-${mediaId}${extensions[attachment.mime]}`;
    // Never replace a leased/existing URI or compete with a canonical download.
    if ((await FS.getInfoAsync(uri)).exists || mediaPins.get(uri)?.size
        || [...mediaDownloads.keys()].some(key => key.startsWith(`${snapshot.epoch}/${uri}/`))) return;
    const partial = `${directory}media-${mediaId}-${Crypto.randomUUID()}.part`;
    let moved = false;
    try {
      const held = [...mediaDownloadReservations.values()].filter(item => item.actor === actor);
      await capacity(actor, attachment.size + held.reduce((sum, item) => sum + item.bytes, 0), false, held.length + 1);
      mediaFence(room, snapshot);
      await FS.copyAsync({ from: attachment.uri, to: partial });
      const copied = await FS.getInfoAsync(partial);
      if (!copied.exists || copied.isDirectory || copied.size !== attachment.size || await hashFile(partial) !== attachment.sha256)
        throw new ChatError('attachment_changed');
      mediaFence(room, snapshot);
      if (getEngine().identity?.permissions.chat_send !== true) throw new ChatError('forbidden', 403);
      await FS.moveAsync({ from: partial, to: uri }); moved = true; mediaFence(room, snapshot);
      const state = await loadActorFiles(actor, snapshot.epoch), prior = state.cache.get(uri);
      const entry = { uri, bytes: attachment.size, sha256: attachment.sha256, usedAt: Date.now() };
      state.cacheBytes += entry.bytes - (prior?.bytes ?? 0); state.cache.set(uri, entry);
      await mediaCacheCatalog.put(catalogActor(actor), entry); mediaFence(room, snapshot);
    } catch (error) {
      // Still under the mutation lock: stale cleanup cannot race a new actor's
      // cache commit. The original stage is never a cleanup target here.
      await removeOwned(partial).catch(() => undefined);
      if (moved) await removeOwned(uri).catch(() => undefined);
      throw error;
    }
  });
}
/** Remove only regex-validated app-owned files, never an arbitrary directory. */
async function pruneMedia(mode: 'snapshot' | 'cacheOnly' | 'logout', expectedGeneration = generation): Promise<void> {
  if (expectedGeneration !== generation) throw new ChatError('stale_session');
  pruneGroupAvatars(mode !== 'snapshot');
  return serialMedia(async () => {
    if (!FS.documentDirectory) return;
    const epoch = expectedGeneration;
    if (epoch !== generation) throw new ChatError('stale_session');
    const current = engine; const identity = current?.identity;
    let rooms: Room[] = []; let pending: Pending[] = []; let valid = false;
    try { if (identity) { rooms = current!.rooms(); pending = current!.pending(); valid = true; } } catch { /* Offline lease denies cached content, but unsent files survive. */ }
    const actor = identity ? await actorDirectory(`${new URL(config.origin).origin}|${config.database}|${identity.user_id}`) : null;
    const actorName = actor?.slice(mediaRoot.length).replace(/\/$/, '');
    const permitted = new Set(rooms.map(r => `c${r.company_id}-r${r.id}-m${r.membership_id}`));
    const staged = new Set(pending.flatMap(p => p.attachment ? [p.attachment.uri] : []));
    if (!discoveredActors) {
      const rootInfo = await FS.getInfoAsync(mediaRoot);
      if (rootInfo.exists && rootInfo.isDirectory) for (const entry of await FS.readDirectoryAsync(mediaRoot)) {
        if (actorPattern.test(entry)) await loadActorFiles(`${mediaRoot}${entry}/`, epoch);
      }
      if (epoch !== generation) throw new ChatError('stale_session');
      discoveredActors = true;
    }
    if (actor) await loadActorFiles(actor, epoch);
    for (const [actorPath, state] of actorFiles) {
      const actorEntry = actorPath.slice(mediaRoot.length).replace(/\/$/, '');
      for (const uri of [...state.cache.keys(), ...state.stages.keys()]) {
        if (epoch !== generation) throw new ChatError('stale_session');
        const relative = uri.slice(actorPath.length), [scopeEntry, filename] = relative.split('/');
        const matchingScope = valid && actorEntry === actorName && permitted.has(scopeEntry!);
        const reservation = reservations.get(uri);
        const reserved = reservation && reservation.epoch === epoch && Date.now() - reservation.at < 5 * 60 * 1000 && matchingScope;
        const keep = retainNativeFile({ filename: filename!, mode, validIdentity: valid, matchingScope, mediaRight: identity?.permissions.media === true,
          sendRight: identity?.permissions.chat_send === true, pending: staged.has(uri), reserved: !!reserved });
        if (!keep) { await removeOwned(uri); reservations.delete(uri); }
      }
      if (actorPath === actor && mode === 'snapshot') await capacity(actor, 0);
    }
  });
}
function deniedCleanupEpoch(error: unknown, expected: number): number {
  // invalidate() advances exactly once. A newer login/logout advances again;
  // a stale response must never sweep the newer account's cached files.
  const denied = error instanceof ChatError && error.code !== 'stale_session'
    && (error.status === 401 || error.status === 403 || error.code === 'identity_mismatch');
  return denied && generation === expected + 1 && engine?.status === 'signed_out' && !engine.identity ? generation : expected;
}
/** Cleanup may identify a remembered actor while backgrounded or expired.
 * This is never passed to HTTP and is not sufficient for displaying data. */
function leadershipSnapshotAuthority(): SnapshotAuthority | null {
  const chat = getEngine(), identity = chat.identity, epoch = chat.accountScope;
  if (!identity || !epoch) return null;
  const revision = identity.permissions.revision;
  return { origin: config.origin, db: config.database, uid: identity.user_id, epoch,
    companyIds: [...identity.company_ids], canView: identity.permissions.dashboard_view === true,
    revision: typeof revision === 'number' && Number.isSafeInteger(revision) && revision >= 0 ? revision : 0,
    leaseRemainingMs: chat.rememberedLeaseRemainingMs };
}
function leadershipDisplayScope(): SnapshotAuthority | null {
  if (AppState.currentState !== 'active') return null;
  const authority = leadershipSnapshotAuthority();
  return authority && authority.leaseRemainingMs > 0 ? authority : null;
}
function getLeadershipSnapshots(): LeadershipSnapshots {
  if (!leadershipSnapshots) leadershipSnapshots = new LeadershipSnapshots({
    storage: AsyncStorage, current: leadershipDisplayScope, now: Date.now,
  });
  return leadershipSnapshots;
}
function snapshotAuthorityStamp(authority: SnapshotAuthority | null): string {
  // Epoch/deadline renewal is not a company or permission change.
  return authority ? JSON.stringify([authority.origin, authority.db, authority.uid,
    [...authority.companyIds].sort((a, b) => a - b), authority.canView, authority.revision]) : '';
}
async function revokeLeadershipSnapshots(authority: SnapshotAuthority | null): Promise<void> {
  leadershipEngine?.clear();
  if (authority) await getLeadershipSnapshots().revoke(authority);
}
async function reconcileLeadershipSnapshots(before: SnapshotAuthority | null, expected: number): Promise<void> {
  if (generation !== expected || snapshotAuthorityStamp(before) === snapshotAuthorityStamp(leadershipSnapshotAuthority())) return;
  await revokeLeadershipSnapshots(before);
}
class NativeChatEngine extends ChatEngine {
  protected override nonChatBootstrap(raw: unknown, expectedUid: number): Bootstrap | null {
    return ordersOnlyBootstrap(raw, expectedUid, config.database);
  }
  override async login(login: string, password: string, remember: boolean): Promise<Bootstrap> {
    // clearNow executes before authentication can replace this native account.
    void getNotificationsEngine().invalidate().catch(() => undefined);
    const before = leadershipSnapshotAuthority();
    const operation = super.login(login, password, remember); const epoch = generation;
    const accessEpoch = ordersAccessEpoch;
    try {
      const result = await operation;
      const acceptedGeneration = result.permissions.chat_view === false ? epoch + 1 : epoch;
      const acceptedScope = this.accountScope;
      const after = leadershipSnapshotAuthority();
      if (generation !== acceptedGeneration || result.permissions.chat_view === true && (!after || after.uid !== result.user_id)) throw new ChatError('stale_session');
      // A cold login has no prior in-memory actor. Its own new incarnation may
      // revoke older disk snapshots before the login result reaches the UI.
      await revokeLeadershipSnapshots(before ?? after).catch(() => undefined);
      if (generation !== acceptedGeneration || this.accountScope !== acceptedScope) throw new ChatError('stale_session');
      if (result.permissions.chat_view === false && (result.permissions.order_view === true || result.permissions.task_view === true)) {
        const accepted = epoch + 1; // Exactly this login's authoritative chat invalidation.
        if (generation !== accepted || this.identity || this.status !== 'signed_out') throw new ChatError('stale_session');
        await pruneMedia('logout', accepted);
        if (generation !== accepted || ordersAccessEpoch !== accessEpoch || !ordersConnectivity || AppState.currentState !== 'active') throw new ChatError('stale_session');
        ordersOnlySession.publish(result, accepted, generation);
      } else {
        await pruneMedia('snapshot', epoch);
        if (generation !== epoch) throw new ChatError('stale_session');
        ordersOnlySession.clear(ordersOnlySnapshot().generation);
      }
      return result;
    }
    catch (error) {
      const cleanupEpoch = deniedCleanupEpoch(error, epoch);
      if (cleanupEpoch !== epoch) await revokeLeadershipSnapshots(before).catch(() => undefined);
      await pruneMedia('cacheOnly', cleanupEpoch).catch(() => undefined); throw error;
    }
  }
  override async restoreOffline(): Promise<boolean> {
    const operation = super.restoreOffline(); const epoch = generation;
    const restored = await operation;
    if (generation === epoch) leadershipOfflineScope = restored ? this.accountScope : null;
    await pruneMedia('snapshot', epoch); return restored;
  }
  override async refresh(): Promise<Bootstrap> {
    const before = leadershipSnapshotAuthority();
    const pushBefore = pushAuthority(this.identity, this.accountScope);
    const epoch = generation;
    leadershipOfflineScope = null;
    try {
      const result = await super.refresh();
      const pushAfter = pushAuthority(result, this.accountScope);
      if (generation === epoch && pushBefore && (!pushAfter || notificationScope(pushBefore) !== notificationScope(pushAfter)))
        void getNotificationsEngine().invalidate().catch(() => undefined);
      await reconcileLeadershipSnapshots(before, epoch).catch(() => undefined);
      await pruneMedia('snapshot', epoch); return result;
    }
    catch (error) {
      const cleanupEpoch = deniedCleanupEpoch(error, epoch);
      if (cleanupEpoch !== epoch) void getNotificationsEngine().invalidate().catch(() => undefined);
      if (generation === epoch && error instanceof ChatError && error.code === 'connection_failed' && !error.status)
        leadershipOfflineScope = this.accountScope;
      if (cleanupEpoch !== epoch) await revokeLeadershipSnapshots(before).catch(() => undefined);
      else await reconcileLeadershipSnapshots(before, epoch).catch(() => undefined);
      await pruneMedia(cleanupEpoch === epoch ? 'snapshot' : 'cacheOnly', cleanupEpoch).catch(() => undefined); throw error;
    }
  }
  override async logout(): Promise<void> {
    void getNotificationsEngine().invalidate().catch(() => undefined);
    const financialActor = leadershipSnapshotAuthority();
    // Start the actor's serialized revoke before reset hides its identity.
    // Store failure blocks financial reads in-process; it must not change chat logout.
    const financialCleanup = revokeLeadershipSnapshots(financialActor).catch(() => undefined);
    const prior = ordersOnlySnapshot();
    const operation = super.logout(); const epoch = generation;
    try { await operation; } finally {
      await financialCleanup;
      if (generation === epoch) {
        reservations.clear(); await pruneMedia('logout', epoch);
        ordersOnlySession.clear(prior.generation);
      }
    }
  }
  override async enqueueAttachment(room: Room | number, attachment: Attachment, text = '', replyTo?: number): Promise<Pending> {
    try { const item = await super.enqueueAttachment(room, attachment, text, replyTo); reservations.delete(attachment.uri); return item; }
    catch (error) {
      reservations.delete(attachment.uri);
      let pendingOwner = true;
      try { pendingOwner = this.pending().some(item => item.attachment?.uri === attachment.uri); } catch { /* Unreadable ownership is not permission to delete. */ }
      if (!pendingOwner && !await stagedJournalOwns(attachment.uri)) await removeOwned(attachment.uri).catch(() => undefined);
      throw error;
    }
  }
}
export function getEngine(): NativeChatEngine {
  if (!engine) {
    fixedURL('/bchat/api/v2/bootstrap');
    engine = new NativeChatEngine({ origin: config.origin, database: config.database, storage: AsyncStorage, archive: historyArchive, uuid: Crypto.randomUUID,
      transport: { request, cancelAll: cancelNative }, upload, removeAttachment: a => removeOwned(a.uri), uploadGroupAvatar,
    });
  }
  return engine;
}

function pushAuthority(identity: Bootstrap | null, epoch: string | number | null): NotificationAuthority | null {
  if (!identity || epoch===null || !(identity.permissions.chat_view === true || identity.permissions.task_view === true)) return null;
  return {origin:config.origin,db:identity.database,uid:identity.user_id,epoch,companyIds:[...identity.company_ids],
    revision:typeof identity.permissions.revision === 'number' ? identity.permissions.revision : 0,
    chat:identity.permissions.chat_view === true,task:identity.permissions.task_view === true,csrf:identity.csrf_token ?? ''};
}
export function getNotificationsEngine(): NotificationsEngine {
  if (!notificationsEngine) notificationsEngine = new NotificationsEngine({native:nativePush,current:()=> {
    const value=applicationOrdersIdentity();return value ? pushAuthority(value.identity,value.epoch) : null;
  },request:async input=> {
    const before=applicationOrdersIdentity(), expected=identityStamp(before);
    if (!before || !(before.identity.permissions.chat_view || before.identity.permissions.task_view)) throw new ChatError('forbidden',403);
    try {
      const result=await request(input);
      if (identityStamp(applicationOrdersIdentity())!==expected) throw new ChatError('stale_session');
      return result;
    } catch(error) {
      if (!input.path.endsWith('/unregister') && identityStamp(applicationOrdersIdentity())===expected && error instanceof ChatError && [401,403].includes(error.status))
        void notificationsEngine?.invalidate().catch(()=>undefined);
      throw error;
    }
  }});
  return notificationsEngine;
}

/** Fresh application scope for orders; a chat-revoked user never becomes a chat identity. */
function applicationOrdersIdentity(): { identity: Bootstrap; epoch: string | number } | null {
  const alternate = ordersOnlySnapshot();
  if (alternate.identity) {
    return alternate.verified && alternate.generation === generation && ordersConnectivity && AppState.currentState === 'active'
      ? { identity: alternate.identity, epoch: `${alternate.generation}/orders` } : null;
  }
  const chat = getEngine();
  const identity = chat.identity;
  return identity && !chat.offline && AppState.currentState === 'active' && chat.accountScope
    && ordersConnectivity ? { identity, epoch: `${chat.accountScope}/orders` } : null;
}
function identityStamp(value: ReturnType<typeof applicationOrdersIdentity>): string {
  // Renewal fences stale HTTP completions, not the user's same-authority cart
  // or verified options. Locked/background scopes still return no authority.
  return value ? JSON.stringify([value.identity.database, value.identity.user_id, value.epoch,
    value.identity.company_ids, value.identity.permissions, ordersAccessEpoch,
    ordersOnlySnapshot().identity ? ordersOnlySnapshot().revision : null]) : '';
}
export function getOrdersEngine(): OrdersEngine {
  if (!ordersEngine) ordersEngine = new OrdersEngine({
    storage: AsyncStorage, now: Date.now, uuid: Crypto.randomUUID,
    identityScope: (): OrdersIdentity | null => {
      const current = applicationOrdersIdentity();
      if (!current) return null;
      const b = current.identity;
      return { origin: config.origin, db: config.database, uid: b.user_id, epoch: current.epoch,
        companyIds: b.company_ids, verified: true, permissions: {
          order_view: b.permissions.order_view === true, order_create: b.permissions.order_create === true,
          order_receive: b.permissions.order_receive === true, chat_send: b.permissions.chat_send === true,
        } };
    },
    transport: { request: async input => {
      const expected = applicationOrdersIdentity();
      if (!expected || expected.identity.permissions.order_view !== true) throw new OrdersError('unauthorized');
      const stamp = identityStamp(expected);
      try {
        const value = await request(ordersNativeRequest(input, expected.identity.csrf_token ?? ''));
        if (identityStamp(applicationOrdersIdentity()) !== stamp) throw new OrdersError('stale');
        return value;
      } catch (error) {
        if (identityStamp(applicationOrdersIdentity()) !== stamp) throw new OrdersError('stale');
        if (error instanceof ChatError && error.status === 401) {
          // The comparison precedes logout; an old response cannot destroy a newer session.
          await getEngine().logout();
        }
        if (error instanceof OrdersError) throw error;
        throw new OrdersError(error instanceof ChatError ? error.code : 'connection_failed', undefined, undefined,
          error instanceof ChatError ? error.status : undefined);
      }
    } },
  });
  return ordersEngine;
}
/** Tasks authority is independent of chat/orders; POST ACKs settle only their original private journal. */
export function getTasksEngine(): TasksEngine {
  if (!workTasksEngine) workTasksEngine = new TasksEngine({
    storage: AsyncStorage, now: Date.now, uuid: Crypto.randomUUID,
    identityScope: (): TaskIdentity | null => {
      const current = applicationOrdersIdentity();
      if (!current) return null;
      const b = current.identity;
      return { origin: config.origin, db: config.database, uid: b.user_id, epoch: current.epoch,
        companyIds: b.company_ids, verified: true, permissions: {
          task_view: b.permissions.task_view === true, task_manage: b.permissions.task_manage === true,
        } };
    },
    transport: { request: async input => {
      const expected = applicationOrdersIdentity();
      if (!expected || expected.identity.permissions.task_view !== true) throw new TasksError('unauthorized');
      const stamp = identityStamp(expected);
      try {
        const value = await request(tasksNativeRequest(input, expected.identity.csrf_token ?? ''));
        // The engine independently validates POST identity/intent before durable ACK,
        // then rejects presentation if the actor or authority changed in flight.
        if (input.method === 'GET' && identityStamp(applicationOrdersIdentity()) !== stamp) throw new TasksError('stale');
        return value;
      } catch (error) {
        if (identityStamp(applicationOrdersIdentity()) !== stamp) throw new TasksError('stale');
        if (error instanceof ChatError && error.status === 401) await getEngine().logout();
        if (error instanceof TasksError) throw error;
        throw new TasksError(error instanceof ChatError ? error.code : 'connection_failed', undefined, undefined,
          error instanceof ChatError ? error.status : undefined);
      }
    } },
  });
  return workTasksEngine;
}
/** Financial reports are read-only and live only in their verified actor scope. */
export function getLeadershipEngine(): LeadershipEngine {
  if (!leadershipEngine) leadershipEngine = new LeadershipEngine({
    snapshots: getLeadershipSnapshots(),
    offline: () => !ordersConnectivity || getEngine().offline && leadershipOfflineScope !== null && leadershipOfflineScope === getEngine().accountScope,
    displayScope: leadershipDisplayScope,
    now: Date.now,
    identityScope: (): LeadershipIdentity | null => {
      const current = applicationOrdersIdentity();
      if (!current) return null;
      const b = current.identity;
      return { origin: config.origin, db: config.database, uid: b.user_id, epoch: current.epoch,
        companyIds: b.company_ids, verified: true, canView: b.permissions.dashboard_view === true,
        ...(typeof b.permissions.revision === 'number' ? { revision: b.permissions.revision } : {}) };
    },
    transport: { request: async input => {
      const expected = applicationOrdersIdentity();
      if (!expected || expected.identity.permissions.dashboard_view !== true) throw new LeadershipError('unauthorized');
      const stamp = identityStamp(expected);
      try {
        const value = await request(leadershipNativeRequest(input));
        if (identityStamp(applicationOrdersIdentity()) !== stamp) throw new LeadershipError('stale');
        return value;
      } catch (error) {
        if (identityStamp(applicationOrdersIdentity()) !== stamp) throw new LeadershipError('stale');
        if (error instanceof ChatError && error.status === 401) await getEngine().logout();
        if (error instanceof LeadershipError) throw error;
        throw new LeadershipError(error instanceof ChatError ? error.code : 'connection_failed',
          error instanceof ChatError ? error.status : undefined);
      }
    } },
  });
  return leadershipEngine;
}
export async function refreshOrdersOnlySession(): Promise<Bootstrap> {
  const prior = ordersOnlySnapshot();
  if (!prior.identity || prior.generation !== generation || !ordersConnectivity || AppState.currentState !== 'active') throw new ChatError('stale_session');
  const accessEpoch = ordersAccessEpoch;
  if (ordersRefresh?.generation === prior.generation && ordersRefresh.accessEpoch === accessEpoch) return ordersRefresh.operation;
  ordersOnlySession.lock();
  const expected = prior.generation;
  const operation = (async () => {
    try {
      const raw = await request({ method: 'GET', path: '/bchat/api/v2/bootstrap' });
      if (generation !== expected || ordersAccessEpoch !== accessEpoch || ordersOnlySnapshot().generation !== expected || !ordersConnectivity || AppState.currentState !== 'active') throw new ChatError('stale_session');
      const identity = ordersOnlyBootstrap(raw, prior.identity!.user_id, config.database);
      if (!identity) throw new ChatError('forbidden', 403);
      const pushBefore=pushAuthority(prior.identity,prior.generation),pushAfter=pushAuthority(identity,expected);
      if(pushBefore&&(!pushAfter||notificationScope(pushBefore)!==notificationScope(pushAfter)))
        void getNotificationsEngine().invalidate().catch(()=>undefined); // clearNow precedes publication; no background/foreign-session cleanup.
      ordersOnlySession.publish(identity, expected, generation);
      return identity;
    } catch (error) {
      if (generation === expected && ordersAccessEpoch === accessEpoch && ordersOnlySnapshot().generation === expected
          && error instanceof ChatError && [401, 403].includes(error.status)) await getEngine().logout();
      throw error;
    }
  })();
  ordersRefresh = { generation: expected, accessEpoch, operation };
  try { return await operation; } finally { if (ordersRefresh?.operation === operation) ordersRefresh = null; }
}
export function stageFile(room: Room, input: { uri: string; name: string; mime: string; kind?: 'image' | 'file' | 'audio' }): Promise<Attachment> {
  return serialMedia(async () => {
    const snapshot = scope(room);
    if (!getEngine().identity?.permissions.media || !getEngine().identity?.permissions.chat_send) throw new ChatError('forbidden', 403);
    if (!/^(file|content):\/\//.test(input.uri) || !extensions[input.mime]) throw new ChatError('invalid_attachment');
    const kind = input.kind ?? (input.mime.startsWith('image/') ? 'image' : input.mime === 'audio/mp4' ? 'audio' : 'file');
    let name = input.name.replace(/[\\/\p{C}]/gu, '_').slice(0, 80) || 'attachment';
    if (!name.toLowerCase().endsWith(extensions[input.mime])) name += extensions[input.mime];
    if (new TextEncoder().encode(name).length > 160) name = `attachment${extensions[input.mime]}`;
    const actor = await actorDirectory(snapshot.key); const directory = `${actor}c${room.company_id}-r${room.id}-m${room.membership_id}/`;
    await FS.makeDirectoryAsync(directory, { intermediates: true });
    const state = await loadActorFiles(actor);
    const upload_uuid = Crypto.randomUUID(); const uri = `${directory}stage-${upload_uuid}${extensions[input.mime]}`;
    try {
      const original = await FS.getInfoAsync(input.uri);
      if (original.exists && !original.isDirectory) { if (original.size > (kind === 'image' ? MAX_FILE / 2 : MAX_FILE)) throw new ChatError('file_too_large'); await capacity(actor, original.size, true); }
      await FS.copyAsync({ from: input.uri, to: uri }); const info = await FS.getInfoAsync(uri);
      if (!info.exists || info.isDirectory || info.size <= 0 || info.size > (kind === 'image' ? MAX_FILE / 2 : MAX_FILE)) throw new ChatError('file_too_large');
      await capacity(actor, info.size, true);
      state.stages.set(uri, info.size); state.stageBytes += info.size;
      const sha256 = await hashFile(uri); mediaFence(room, snapshot);
      if (getEngine().identity?.permissions.chat_send !== true) throw new ChatError('forbidden', 403);
      reservations.set(uri, { epoch: snapshot.epoch, at: Date.now() });
      return { uri, name, mime: input.mime, kind, size: info.size, sha256, upload_uuid };
    } catch (error) { await removeOwned(uri).catch(() => undefined); throw error; }
  });
}
async function stagedJournalOwns(uri: string): Promise<boolean> {
  try {
    for (const key of await AsyncStorage.getAllKeys()) if (key.includes('/outbox/') || key.includes('/ack/')) {
      const raw = await AsyncStorage.getItem(key);
      if (raw && JSON.parse(raw).attachment?.uri === uri) return true;
    }
    return false;
  } catch { return true; } // Unknown durable outcome must preserve its bytes.
}
/** Dispose only an unclaimed picker reservation. An unreadable/uncertain outbox
 * is never evidence that a staged file is disposable. */
export function discardStagedAttachment(attachment: Attachment): Promise<void> {
  return serialMedia(async () => {
    const uri = attachment.uri, reservation = reservations.get(uri);
    if (!reservation || !owned(uri) || !uri.split('/').at(-1)?.startsWith('stage-')) return;
    let pending: Pending[];
    try { pending = getEngine().pending(); } catch { return; }
    if (pending.some(item => item.attachment?.uri === uri)) return;
    // Pending state may be awaiting an in-flight durable enqueue; preserve any
    // journal reference, and fail closed if its storage cannot be inspected.
    if (await stagedJournalOwns(uri)) return;
    try { if (getEngine().pending().some(item => item.attachment?.uri === uri)) return; } catch { return; }
    if (reservations.get(uri) !== reservation) return;
    reservations.delete(uri); await removeOwned(uri);
  });
}
function pinLocal(uri: string): LocalMediaLease {
  const token = {}, owners = mediaPins.get(uri) ?? new Set<object>(); owners.add(token); mediaPins.set(uri, owners);
  return { uri, release() { const current = mediaPins.get(uri); if (current !== owners) return; current.delete(token); if (!current.size) mediaPins.delete(uri); } };
}
/** Compatibility resolver; presentation owners use a lease to prevent LRU races. */
export async function localMedia(room: Room, descriptor: Record<string, unknown>, variant: MediaVariant = 'original'): Promise<string> {
  const lease = await localMediaLease(room, descriptor, variant); lease.release(); return lease.uri;
}
export async function localMediaLease(room: Room, descriptor: Record<string, unknown>, variant: MediaVariant = 'original', cachedOnly = false): Promise<LocalMediaLease> {
  const before = scope(room);
  if (!Number.isSafeInteger(descriptor.id) || Number(descriptor.id) <= 0) throw new ChatError('invalid_attachment');
  const associated = await getEngine().mediaAssociation(room, Number(descriptor.id));
  let history: History | null = associated ? { api_version: 2, messages: [associated], next_before_id: null } : null;
  // Unknown IDs retain the bounded authoritative fallback; known archived media
  // never forces an HTTP history request or a full archive scan.
  if (!history) history = await getEngine().history(room);
  const media = trustedMedia(history, descriptor); mediaFence(room, before);
  const prepared = await serialMedia(async () => {
    mediaFence(room, before); const snapshot = scope(room); const extension = extensions[media.mime];
    if (!extension || getEngine().identity?.permissions.media !== true) throw new ChatError('forbidden', 403);
    const actor = await actorDirectory(snapshot.key); const directory = `${actor}c${room.company_id}-r${room.id}-m${room.membership_id}/`;
    const state = await loadActorFiles(actor, snapshot.epoch);
    const preview = variant === 'preview' && media.kind === 'image' && media.thumbnail_available === true;
    const uri = `${directory}media-${media.id}${preview ? '-preview.jpg' : extension}`;
    const cachedLease = async (path: string, expected: { bytes: number; sha256: string | null } | undefined) => {
      const cached = await FS.getInfoAsync(path);
      if (!cached.exists || cached.isDirectory) return null;
      if (expected?.sha256 && cached.size === expected.bytes && await hashFile(path) === expected.sha256) {
        mediaFence(room, snapshot);
        const usedAt = Date.now(), entry = { uri: path, bytes: cached.size, sha256: expected.sha256, usedAt };
        if (!state.cache.has(path)) state.cacheBytes += cached.size;
        state.cache.delete(path); state.cache.set(path, entry);
        await mediaCacheCatalog.put(catalogActor(actor), entry); mediaFence(room, snapshot); return pinLocal(path);
      }
      await removeOwned(path); return null;
    };
    const existing = await cachedLease(uri, preview ? state.cache.get(uri) : { bytes: media.size, sha256: media.sha256 });
    if (existing) return { local: existing };
    // A modern thumbnail may have been evicted while its verified full image
    // remains. Reuse only local bytes: scrolling never downloads an original.
    if (preview) {
      const original = await cachedLease(`${directory}media-${media.id}${extension}`, { bytes: media.size, sha256: media.sha256 });
      if (original) return { local: original };
    }
    // Legacy images may reuse a downloaded original, but a scroll never starts
    // a large original download simply because a thumbnail is unavailable.
    if (variant === 'preview' && !preview) throw new ChatError('media_not_cached');
    if (cachedOnly || getEngine().offline) throw new ChatError('media_not_cached');
    return { snapshot, actor, directory, preview, uri, limit: preview ? MAX_THUMBNAIL : media.size };
  });
  if (prepared.local) return prepared.local;
  const { snapshot, actor, directory, preview, uri, limit } = prepared;
  const downloadKey = `${snapshot.epoch}/${uri}/${media.sha256}`;
  let shared = mediaDownloads.get(downloadKey);
  if (!shared) {
    const transfer = async (): Promise<LocalMediaLease> => {
      const reservation = {};
      const partial = `${directory}media-${media.id}-${Crypto.randomUUID()}.part`; let moved = false;
      try {
        await serialMedia(async () => {
          mediaFence(room, snapshot);
          const held = [...mediaDownloadReservations.values()].filter(item => item.actor === actor);
          await capacity(actor, limit + held.reduce((sum, item) => sum + item.bytes, 0), false, held.length + 1);
          mediaFence(room, snapshot);
          await FS.makeDirectoryAsync(directory, { intermediates: true });
          mediaDownloadReservations.set(reservation, { actor, bytes: limit });
        });
        mediaFence(room, snapshot);
        const mime = preview ? 'image/jpeg' : media.mime;
        const response = await sessionNative(`/bchat/api/v2/media/${media.id}/${preview ? 'thumbnail' : 'content'}`, 'GET', { Accept: mime, 'Accept-Encoding': 'identity' }, undefined, undefined, partial, limit);
        mediaFence(room, snapshot); const headers = headersOf(response);
        if ((headers['content-type'] ?? '').split(';')[0].trim() !== mime) throw new ChatError('invalid_response');
        const info = await FS.getInfoAsync(partial);
        if (!info.exists || info.isDirectory || info.size <= 0 || info.size > limit
            || headers['content-length'] !== undefined && (!/^[1-9]\d*$/.test(headers['content-length']) || Number(headers['content-length']) !== info.size)) throw new ChatError('invalid_response');
        const digest = await hashFile(partial);
        if (!preview && (info.size !== media.size || digest !== media.sha256)) throw new ChatError('attachment_changed');
        if (preview) {
          const encoded = await FS.readAsStringAsync(partial, { encoding: FS.EncodingType.Base64 });
          if (!validThumbnail(BlobUtil.base64.decode(encoded))) throw new ChatError('invalid_response');
        }
        return await serialMedia(async () => {
          try {
            mediaFence(room, snapshot);
            const state = await loadActorFiles(actor, snapshot.epoch);
            const held = [...mediaDownloadReservations.entries()].filter(([key, item]) => key !== reservation && item.actor === actor);
            await capacity(actor, info.size + held.reduce((sum, [, item]) => sum + item.bytes, 0), false, held.length + 1);
            mediaFence(room, snapshot);
            await FS.moveAsync({ from: partial, to: uri }); moved = true; mediaFence(room, snapshot);
            const entry = { uri, bytes: info.size, sha256: digest, usedAt: Date.now() };
            const prior = state.cache.get(uri); state.cacheBytes += info.size - (prior?.bytes ?? 0); state.cache.set(uri, entry);
            await mediaCacheCatalog.put(catalogActor(actor), entry); mediaFence(room, snapshot); return pinLocal(uri);
          } catch (error) {
            // Do not release the mutation lock between a failed commit and its
            // cleanup: a new generation may already be waiting to use this path.
            if (moved) await removeOwned(uri).catch(() => undefined);
            throw error;
          }
        });
      } catch (error) {
        await serialMedia(() => removeOwned(partial).catch(() => undefined));
        throw error;
      } finally {
        mediaDownloadReservations.delete(reservation);
      }
    };
    const lane = preview ? 'preview' : 'original';
    const operation = mediaTransfers[lane].then(transfer, transfer);
    mediaTransfers[lane] = operation.catch(() => undefined);
    shared = { operation, readers: 0 }; mediaDownloads.set(downloadKey, shared);
  }
  shared.readers++;
  try {
    const local = await shared.operation;
    mediaFence(room, snapshot); return pinLocal(local.uri);
  } finally {
    if (--shared.readers === 0) {
      if (mediaDownloads.get(downloadKey) === shared) mediaDownloads.delete(downloadKey);
      // The shared pin bridges completion to each caller's independent lease.
      void shared.operation.then(local => local.release(), () => undefined);
    }
  }
}

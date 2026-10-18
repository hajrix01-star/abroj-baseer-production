/** Android trial native boundary. No credential extraction, telemetry or public media URLs. */
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import * as FS from 'expo-file-system/legacy';
import BlobUtil from 'react-native-blob-util';
import type { FetchBlobResponse, StatefulPromise } from 'react-native-blob-util';
import { ChatEngine, ChatError } from './core/ChatEngine';
import type { Attachment, Bootstrap, GroupAvatarAck, GroupAvatarInput, Pending, Request, Room } from './core/ChatEngine';
import { actorPattern, mediaFilePattern, nativeSessionOptions, retainNativeFile, scopePattern, trustedMedia } from './core/nativeBoundary';
import { nativeSessionTrace, networkFailure } from './core/loginDiagnostics';

export const config = Object.freeze({
  origin: (process.env.EXPO_PUBLIC_ODOO_ORIGIN ?? '').trim(),
  database: (process.env.EXPO_PUBLIC_ODOO_DATABASE ?? '').trim(),
});
const MAX_FILE = 10 * 1024 * 1024;
const MAX_ACCOUNT = 50 * 1024 * 1024;
const mediaRoot = `${FS.documentDirectory ?? ''}odoo-chat-media/`;
const tasks = new Set<StatefulPromise<FetchBlobResponse>>();
const reservations = new Map<string, { epoch: number; at: number }>();
let generation = 0;
let engine: NativeChatEngine | undefined;
let mediaWork: Promise<unknown> = Promise.resolve();
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
  generation++;
  clearGroupAvatars();
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
async function actorDirectory(key: string): Promise<string> {
  if (!FS.documentDirectory) throw new ChatError('native_storage_required');
  return `${mediaRoot}${await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, key)}/`;
}
function owned(uri: string): boolean {
  if (!FS.documentDirectory || !uri.startsWith(mediaRoot)) return false;
  const parts = uri.slice(mediaRoot.length).split('/');
  return parts.length === 3 && actorPattern.test(parts[0]) && scopePattern.test(parts[1]) && mediaFilePattern.test(parts[2]);
}
async function removeOwned(uri: string): Promise<void> {
  if (!owned(uri)) throw new ChatError('invalid_attachment');
  await FS.deleteAsync(uri, { idempotent: true });
}
async function bytesIn(path: string, budget = { files: 0 }): Promise<number> {
  const info = await FS.getInfoAsync(path);
  if (!info.exists) return 0;
  if (!info.isDirectory) { if (++budget.files > 1000) throw new ChatError('media_quota'); return info.size; }
  let bytes = 0;
  for (const entry of await FS.readDirectoryAsync(path)) { bytes += await bytesIn(`${path.replace(/\/$/, '')}/${entry}`, budget); if (bytes > MAX_ACCOUNT) throw new ChatError('media_quota'); }
  return bytes;
}
async function capacity(actor: string, additional: number): Promise<void> {
  if (await bytesIn(actor) + additional > MAX_ACCOUNT) throw new ChatError('media_quota');
}
async function hashFile(uri: string): Promise<string> { return BlobUtil.fs.hash(decodeURI(uri.replace(/^file:\/\//, '')), 'sha256'); }
async function verifyAttachment(room: Room, attachment: Attachment): Promise<void> {
  const snapshot = scope(room); const actor = await actorDirectory(snapshot.key);
  if (!owned(attachment.uri) || !attachment.uri.startsWith(`${actor}c${room.company_id}-r${room.id}-m${room.membership_id}/stage-`)) throw new ChatError('invalid_attachment');
  const info = await FS.getInfoAsync(attachment.uri);
  if (!info.exists || info.isDirectory || info.size !== attachment.size || await hashFile(attachment.uri) !== attachment.sha256) throw new ChatError('attachment_changed');
  fence(room, snapshot);
}
async function upload(room: Room, attachment: Attachment, csrfToken: string, signal: AbortSignal): Promise<{ media_id: number; policy_version?: number }> {
  const snapshot = scope(room); await verifyAttachment(room, attachment);
  const base = `/bchat/api/v2/rooms/${room.id}/uploads`;
  const reconciled = await request({ method: 'GET', path: `${base}/${attachment.upload_uuid}/reconcile`, signal }) as Record<string, unknown>;
  fence(room, snapshot);
  if (reconciled.api_version !== 2 || reconciled.membership_id !== room.membership_id || reconciled.room_id !== room.id || reconciled.upload_uuid !== attachment.upload_uuid) throw new ChatError('invalid_response');
  if (Number.isSafeInteger(reconciled.media_id) && Number(reconciled.media_id) > 0 && ['staged', 'attached'].includes(String(reconciled.state))) return { media_id: Number(reconciled.media_id) };
  if (reconciled.state !== 'missing') throw new ChatError('upload_pending');
  const metadata = { api_version: 2, membership_id: room.membership_id, upload_uuid: attachment.upload_uuid, kind: attachment.kind, mime: attachment.mime, size: attachment.size, sha256: attachment.sha256, name: attachment.name };
  const body = [{ name: 'csrf_token', data: csrfToken }, { name: 'metadata', data: JSON.stringify(metadata) },
    { name: 'file', filename: attachment.name, type: attachment.mime, data: BlobUtil.wrap(decodeURI(attachment.uri.replace(/^file:\/\//, ''))) }];
  const response = await sessionNative(base, 'POST', { Accept: 'application/json', 'Content-Type': 'multipart/form-data' }, body, signal);
  let result: any; try { result = response.json(); } catch { throw new ChatError('invalid_response'); }
  fence(room, snapshot);
  if (result.api_version !== 2 || result.upload_uuid !== attachment.upload_uuid || !Number.isSafeInteger(result.media_id) || result.media_id <= 0 || !['staged', 'attached'].includes(result.state)) throw new ChatError('invalid_response');
  return { media_id: result.media_id };
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
    const rootInfo = await FS.getInfoAsync(mediaRoot); if (!rootInfo.exists || !rootInfo.isDirectory) return;
    for (const actorEntry of await FS.readDirectoryAsync(mediaRoot)) {
      if (!actorPattern.test(actorEntry)) continue;
      const actorPath = `${mediaRoot}${actorEntry}/`; const actorInfo = await FS.getInfoAsync(actorPath);
      if (!actorInfo.exists || !actorInfo.isDirectory) continue;
      for (const scopeEntry of await FS.readDirectoryAsync(actorPath)) {
        if (!scopePattern.test(scopeEntry)) continue;
        const directory = `${actorPath}${scopeEntry}/`; const directoryInfo = await FS.getInfoAsync(directory);
        if (!directoryInfo.exists || !directoryInfo.isDirectory) continue;
        for (const filename of await FS.readDirectoryAsync(directory)) {
          if (!mediaFilePattern.test(filename)) continue;
          if (epoch !== generation) throw new ChatError('stale_session');
          const uri = `${directory}${filename}`; const fileInfo = await FS.getInfoAsync(uri);
          if (!fileInfo.exists || fileInfo.isDirectory) continue;
          const matchingScope = valid && actorEntry === actorName && permitted.has(scopeEntry);
          const reservation = reservations.get(uri);
          const reserved = reservation && reservation.epoch === epoch && Date.now() - reservation.at < 5 * 60 * 1000 && matchingScope;
          const keep = retainNativeFile({ filename, mode, validIdentity: valid, matchingScope, mediaRight: identity?.permissions.media === true,
            sendRight: identity?.permissions.chat_send === true, pending: staged.has(uri), reserved: !!reserved });
          if (!keep) { if (epoch !== generation) throw new ChatError('stale_session'); await removeOwned(uri); reservations.delete(uri); }
        }
      }
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
class NativeChatEngine extends ChatEngine {
  override async login(login: string, password: string, remember: boolean): Promise<Bootstrap> {
    const operation = super.login(login, password, remember); const epoch = generation;
    try { const result = await operation; await pruneMedia('snapshot', epoch); return result; }
    catch (error) { await pruneMedia('cacheOnly', deniedCleanupEpoch(error, epoch)).catch(() => undefined); throw error; }
  }
  override async restoreOffline(): Promise<boolean> { const operation = super.restoreOffline(); const epoch = generation; const restored = await operation; await pruneMedia('snapshot', epoch); return restored; }
  override async refresh(): Promise<Bootstrap> {
    const epoch = generation;
    try { const result = await super.refresh(); await pruneMedia('snapshot', epoch); return result; }
    catch (error) {
      const cleanupEpoch = deniedCleanupEpoch(error, epoch);
      await pruneMedia(cleanupEpoch === epoch ? 'snapshot' : 'cacheOnly', cleanupEpoch).catch(() => undefined); throw error;
    }
  }
  override async logout(): Promise<void> {
    const operation = super.logout(); const epoch = generation;
    try { await operation; } finally { if (generation === epoch) { reservations.clear(); await pruneMedia('logout', epoch); } }
  }
  override async enqueueAttachment(room: Room | number, attachment: Attachment, text = '', replyTo?: number): Promise<Pending> {
    try { const item = await super.enqueueAttachment(room, attachment, text, replyTo); reservations.delete(attachment.uri); return item; }
    catch (error) {
      reservations.delete(attachment.uri);
      let pendingOwner = false;
      try { pendingOwner = this.pending().some(item => item.attachment?.uri === attachment.uri); } catch { /* No readable session remains. */ }
      if (!pendingOwner) await removeOwned(attachment.uri).catch(() => undefined);
      throw error;
    }
  }
}
export function getEngine(): NativeChatEngine {
  if (!engine) {
    fixedURL('/bchat/api/v2/bootstrap');
    engine = new NativeChatEngine({ origin: config.origin, database: config.database, storage: AsyncStorage, uuid: Crypto.randomUUID,
      transport: { request, cancelAll: cancelNative }, upload, removeAttachment: a => removeOwned(a.uri), uploadGroupAvatar,
    });
  }
  return engine;
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
    const upload_uuid = Crypto.randomUUID(); const uri = `${directory}stage-${upload_uuid}${extensions[input.mime]}`;
    try {
      const original = await FS.getInfoAsync(input.uri);
      if (original.exists && !original.isDirectory) { if (original.size > (kind === 'image' ? MAX_FILE / 2 : MAX_FILE)) throw new ChatError('file_too_large'); await capacity(actor, original.size); }
      await FS.copyAsync({ from: input.uri, to: uri }); const info = await FS.getInfoAsync(uri);
      if (!info.exists || info.isDirectory || info.size <= 0 || info.size > (kind === 'image' ? MAX_FILE / 2 : MAX_FILE)) throw new ChatError('file_too_large');
      await capacity(actor, 0); const sha256 = await hashFile(uri); fence(room, snapshot);
      reservations.set(uri, { epoch: snapshot.epoch, at: Date.now() });
      return { uri, name, mime: input.mime, kind, size: info.size, sha256, upload_uuid };
    } catch (error) { await removeOwned(uri).catch(() => undefined); throw error; }
  });
}
export async function localMedia(room: Room, descriptor: Record<string, unknown>): Promise<string> {
  // Prove room association before touching cache paths. Offline history contains
  // only this account/company/room/membership's remembered messages.
  const before = scope(room);
  let history = getEngine().rememberedHistory(room);
  // Already-validated room metadata avoids one history HTTP request per visible
  // image. A missing association still takes the original authoritative path.
  if (!history?.messages.some(message => message.media?.id === descriptor.id)) history = await getEngine().history(room);
  const media = trustedMedia(history, descriptor); fence(room, before);
  return serialMedia(async () => {
    fence(room, before); const snapshot = scope(room); const extension = extensions[media.mime];
    if (!extension || getEngine().identity?.permissions.media !== true) throw new ChatError('forbidden', 403);
    const actor = await actorDirectory(snapshot.key); const directory = `${actor}c${room.company_id}-r${room.id}-m${room.membership_id}/`;
    const uri = `${directory}media-${media.id}${extension}`; const cached = await FS.getInfoAsync(uri);
    if (cached.exists && !cached.isDirectory) {
      if (cached.size === media.size && await hashFile(uri) === media.sha256) { fence(room, snapshot); return uri; }
      await removeOwned(uri);
    }
    if (getEngine().offline) throw new ChatError('media_not_cached');
    await capacity(actor, media.size); await FS.makeDirectoryAsync(directory, { intermediates: true });
    const partial = `${directory}media-${media.id}-${Crypto.randomUUID()}.part`;
    try {
      const response = await sessionNative(`/bchat/api/v2/media/${media.id}/content`, 'GET', { Accept: media.mime, 'Accept-Encoding': 'identity' }, undefined, undefined, partial, media.size);
      fence(room, snapshot); const headers = headersOf(response);
      if ((headers['content-type'] ?? '').split(';')[0].trim() !== media.mime || headers['content-length'] !== undefined && Number(headers['content-length']) !== media.size) throw new ChatError('invalid_response');
      const info = await FS.getInfoAsync(partial);
      if (!info.exists || info.isDirectory || info.size !== media.size || await hashFile(partial) !== media.sha256) throw new ChatError('attachment_changed');
      fence(room, snapshot); await FS.moveAsync({ from: partial, to: uri }); fence(room, snapshot); return uri;
    } catch (error) { await removeOwned(partial).catch(() => undefined); throw error; }
  });
}

/** Executes the real runtime with native-module seams, not a device/cookie proof. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire, registerHooks } from 'node:module';
import { createHash, randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { SqliteArchiveStore } from '../storage/SqliteHistoryArchive.ts';
import type { ArchiveDatabase } from '../storage/SqliteHistoryArchive.ts';

const files = new Map<string, Buffer>(); const directories = new Set<string>(['file:///app/']);
let directoryReads = 0;
let beforeStat: ((uri: string) => Promise<void>) | undefined;
let failOwnedDelete = false;
const normalize = (uri: string) => uri.startsWith('file://') ? uri : `file://${uri}`;
function makeDirectory(uri: string) {
  const parts = uri.replace(/^file:\/\//, '').split('/').filter(Boolean); let path = 'file:///';
  for (const part of parts) { path += `${part}/`; directories.add(path); }
}
const fs = {
  documentDirectory: 'file:///app/', cacheDirectory: 'file:///cache/',
  async getInfoAsync(uri: string) {
    if (beforeStat) await beforeStat(uri);
    const value = files.get(normalize(uri)); if (value) return { exists: true, isDirectory: false, size: value.length };
    return { exists: directories.has(uri.endsWith('/') ? uri : `${uri}/`), isDirectory: true, size: 0 };
  },
  async makeDirectoryAsync(uri: string) { makeDirectory(uri); },
  async readDirectoryAsync(uri: string) {
    directoryReads++;
    const prefix = uri.endsWith('/') ? uri : `${uri}/`; const entries = new Set<string>();
    for (const key of [...directories, ...files.keys()]) if (key.startsWith(prefix) && key !== prefix) entries.add(key.slice(prefix.length).split('/')[0]!);
    return [...entries];
  },
  async deleteAsync(uri: string) { if (failOwnedDelete && uri.includes('/odoo-chat-media/')) throw new Error('synthetic cleanup failure'); files.delete(normalize(uri)); },
  async copyAsync({ from, to }: { from: string; to: string }) { const bytes = files.get(normalize(from)); if (!bytes) throw new Error('missing file'); files.set(normalize(to), Buffer.from(bytes)); },
  async moveAsync({ from, to }: { from: string; to: string }) { const bytes = files.get(normalize(from)); if (!bytes) throw new Error('missing file'); files.set(normalize(to), bytes); files.delete(normalize(from)); },
  EncodingType: { Base64: 'base64' },
  async readAsStringAsync(uri: string) { const bytes = files.get(normalize(uri)); if (!bytes) throw new Error('missing file'); return bytes.toString('base64'); },
};
const sqlite = new DatabaseSync(':memory:');
const database: ArchiveDatabase = {
  async execAsync(sql) { sqlite.exec(sql); },
  async runAsync(sql, ...values) { return sqlite.prepare(sql).run(...values); },
  async getFirstAsync<T>(sql: string, ...values: (string | number | null)[]) { return sqlite.prepare(sql).get(...values) as T ?? null; },
  async getAllAsync<T>(sql: string, ...values: (string | number | null)[]) { return sqlite.prepare(sql).all(...values) as T[]; },
};
const sqlArchive = new SqliteArchiveStore(async () => database);
const strictCatalogActor = (actor: string) => assert.match(actor, /^[a-f0-9]{64}$/, 'real SQLite catalog accepts an actor digest, never a file directory');
const catalog = {
  async list(actor: string) { strictCatalogActor(actor); return sqlArchive.mediaCacheCatalog.list(actor); },
  async put(actor: string, entry: { uri: string; bytes: number; sha256: string; usedAt: number }) { strictCatalogActor(actor); return sqlArchive.mediaCacheCatalog.put(actor, entry); },
  async remove(actor: string, uri: string) { strictCatalogActor(actor); return sqlArchive.mediaCacheCatalog.remove(actor, uri); },
  async touch(actor: string, uri: string, at: number) { strictCatalogActor(actor); return sqlArchive.mediaCacheCatalog.touch(actor, uri, at); },
};
const storage = new Map<string, string>();
const asyncStorage = {
  async getItem(k: string) { return storage.get(k) ?? null; }, async setItem(k: string, v: string) { storage.set(k, v); },
  async removeItem(k: string) { storage.delete(k); }, async getAllKeys() { return [...storage.keys()]; },
};
const payload = Buffer.from('%PDF-1.7 test data %%EOF'); const sha256 = createHash('sha256').update(payload).digest('hex');
const media = { id: 70, kind: 'file', mime: 'application/pdf', name: 'private.pdf', size: payload.length, sha256 };
const thumbnail = Buffer.from([255,216,255,192,0,11,8,0,1,0,1,1,1,17,0,255,218,0,8,1,1,0,0,63,0,1,255,217]);
const imageBytes = Buffer.from('synthetic original image bytes');
const imageMedia = { id: 170, kind: 'image', mime: 'image/jpeg', name: 'synthetic.jpg', size: imageBytes.length,
  sha256: createHash('sha256').update(imageBytes).digest('hex'), thumbnail_available: true };
const extraMedia = new Map<number, { metadata: typeof media | typeof imageMedia; bytes: Buffer }>();
let thumbnailBytes = thumbnail, thumbnailMime = 'image/jpeg';
const roomA = { id: 11, company_id: 1, membership_id: 21, name: 'A', is_group: true, avatar_version: 1 };
const roomB = { id: 12, company_id: 1, membership_id: 22, name: 'B', is_group: true, avatar_version: 1 };
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBz8AAAAASUVORK5CYII=', 'base64');
let avatarBytes = png, avatarMime = 'image/png', avatarHeader: string | undefined;
let avatarCanManage = true, avatarLostAck = false, avatarReads = 0, avatarUploads = 0, groupReads = 0;
const appState = { currentState: 'active' };
let rooms = [roomA, roomB]; let mediaRight = true; let offline = false; let redirect = false; let unauthorized = false; let revoked = false;
let beforeNative: ((path: string) => Promise<void>) | undefined;
let missingMetadata = false;
let nativeFailure: Error | undefined;
let bootstrapDiagnostic: string | undefined;
let emulateOdooStatelessHeader = false;
let statefulSessionIssued = false;
let bootstrapOverride: unknown;
let ordersStatus = 200;
const calls: { method: string; path: string; options: Record<string, unknown> }[] = [];
function nativeFetch(options: Record<string, unknown>, method: string, url: string, requestHeaders: Record<string, string>, requestBody?: unknown) {
  const path = new URL(url).pathname; calls.push({ method, path, options });
  assert.equal(options.followRedirect, false); assert.equal(options.trusty, false);
  if (path !== '/web/session/authenticate') assert.equal(requestHeaders['X-Odoo-Database'], 'trial');
  else {
    assert.equal(requestHeaders['X-Odoo-Database'], undefined);
    assert.equal(JSON.parse(String(requestBody)).params.db, 'trial');
  }
  const task: any = Promise.resolve().then(async () => {
    if (beforeNative) await beforeNative(path);
    if (nativeFailure) throw nativeFailure;
    if (offline) throw new Error('network unavailable');
    let status = 200; let body: unknown; const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (emulateOdooStatelessHeader && path === '/web/session/authenticate')
      statefulSessionIssued = requestHeaders['X-Odoo-Database'] === undefined;
    if (emulateOdooStatelessHeader && path === '/bchat/api/v2/bootstrap' && !statefulSessionIssued) {
      status = 303; headers['X-Baseer-Native-Session'] = 'I0A0S0M0L1';
    }
    else if (bootstrapDiagnostic !== undefined && path === '/bchat/api/v2/bootstrap') {
      status = 303; headers['X-Baseer-Native-Session'] = bootstrapDiagnostic;
    }
    else if (redirect) status = 302;
    else if (unauthorized) { status = 401; body = { error: { code: 'session_expired' } }; }
    else if (revoked && path.startsWith('/bchat/')) { status = 403; body = { error: { code: 'forbidden' } }; }
    // Actual QA fixture shape without a cookie, with fixed X-Odoo-Database.
    else if (path === '/web/session/destroy') body = { jsonrpc: '2.0', error: { code: 100, message: 'Odoo Session Expired', data: { name: 'odoo.http.SessionExpiredException', message: 'Odoo Session Expired' } } };
    else if (path === '/web/session/authenticate') body = { result: { uid: 7, db: 'trial' } };
    else if (path.endsWith('/bootstrap')) body = bootstrapOverride ?? { api_version: 2, database: 'trial', user_id: 7, company_ids: [1], csrf_token: 'notpersisted', permissions: { chat_view: true, chat_send: true, media: mediaRight } };
    else if (path === '/bchat/api/v2/orders/options') { status = ordersStatus; body = status === 200
      ? { api_version: 2, access: 'viewer', can_view: true, can_create: false, can_receive: false, companies: [{ id: 1, name: 'Synthetic company' }] }
      : { error: { code: 'session_expired' } }; }
    else if (path === '/bchat/api/v2/rooms') body = { api_version: 2, rooms };
    else if (/\/rooms\/\d+\/group$/.test(path)) {
      groupReads++; const room = rooms.find(row => row.id === Number(path.split('/').at(-2)))!;
      body = { api_version: 2, room: { id: room.id, company_id: room.company_id, name: room.name, description: 'Synthetic group', avatar_version: room.avatar_version, is_group: true }, members: [{ user_id: 7, name: 'Synthetic member', is_admin: avatarCanManage }], can_manage: avatarCanManage };
    }
    else if (/\/rooms\/\d+\/avatar$/.test(path)) {
      const room = rooms.find(row => row.id === Number(path.split('/').at(-2)))!;
      if (method === 'POST') {
        avatarUploads++;
        assert.deepEqual((requestBody as any[]).map(field => field.name), ['csrf_token', 'file']);
        assert.equal((requestBody as any[])[0].data, 'notpersisted');
        assert.equal((requestBody as any[])[1].type, 'image/png');
        assert.match((requestBody as any[])[1].data, /^native-file:\/cache\/odoo-group-avatar-/);
        room.avatar_version++;
        if (avatarLostAck) throw new Error('synthetic response lost');
        body = { api_version: 2, room_id: room.id, avatar_version: room.avatar_version };
      } else {
        avatarReads++; headers['Content-Type'] = avatarMime; headers['Content-Length'] = String(avatarBytes.length);
        headers['X-BChat-Avatar-Version'] = avatarHeader ?? String(room.avatar_version);
      }
    }
    else if (/\/rooms\/\d+\/members\/\d+\/avatar$/.test(path)) {
      headers['Content-Type'] = avatarMime; headers['Content-Length'] = String(avatarBytes.length);
    }
    else if (path.endsWith('/changes')) body = { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
    else if (path.endsWith('/11/messages')) body = { api_version: 2, messages: [
      { id: 1, author_user_id: 7, author_name: 'A', text: '', created_at: '', media },
      ...[...extraMedia.values()].map((item, index) => ({ id: index + 2, author_user_id: 7, author_name: 'A', text: '', created_at: '', media: item.metadata })),
    ], next_before_id: null };
    else if (path.endsWith('/12/messages')) body = { api_version: 2, messages: [], next_before_id: null };
    else if (path.endsWith('/media/70/content')) { headers['Content-Type'] = media.mime; headers['Content-Length'] = String(payload.length); if (options.path) files.set(normalize(String(options.path)), Buffer.from(payload)); }
    else if (/\/media\/\d+\/thumbnail$/.test(path)) {
      headers['Content-Type'] = thumbnailMime; headers['Content-Length'] = String(thumbnailBytes.length);
      if (options.path) files.set(normalize(String(options.path)), Buffer.from(thumbnailBytes));
    }
    else if (/\/media\/\d+\/content$/.test(path)) {
      const item = extraMedia.get(Number(path.split('/').at(-2)))!;
      headers['Content-Type'] = item.metadata.mime; headers['Content-Length'] = String(item.bytes.length);
      if (options.path) files.set(normalize(String(options.path)), Buffer.from(item.bytes));
    }
    else throw new Error(`Unexpected test route ${path}`);
    const image = Buffer.from(avatarBytes);
    return { info: () => missingMetadata ? { rnfbEncode: 'utf8' } : ({ status, headers, redirects: [url] }), json: () => body === undefined ? undefined : JSON.parse(JSON.stringify(body)), base64: () => image.toString('base64') };
  });
  task.cancel = () => task; task.progress = () => task;
  return task;
}
const mocks: Record<string, unknown> = {
  './storage/nativeArchive': { mediaCacheCatalog: catalog, historyArchive: sqlArchive },
  'react-native': { Platform: { OS: 'android' }, AppState: appState },
  '@react-native-async-storage/async-storage': asyncStorage,
  'expo-crypto': { CryptoDigestAlgorithm: { SHA256: 'SHA256' }, randomUUID, digestStringAsync: async (_algorithm: unknown, value: string) => createHash('sha256').update(value).digest('hex') },
  'expo-file-system/legacy': fs,
  'react-native-blob-util': { config: (options: Record<string, unknown>) => ({ fetch: (method: string, url: string, headers: Record<string, string>, body?: unknown) => nativeFetch(options, method, url, headers, body) }),
    base64: createRequire(import.meta.url)('base-64'),
    wrap: (path: string) => `native-file:${path}`, fs: { hash: async (path: string) => createHash('sha256').update(files.get(normalize(path))!).digest('hex') } },
};
(globalThis as any).__odooNativeTestMocks = mocks;
const hooks = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier in mocks) return { url: `odoo-native-test:${specifier}`, shortCircuit: true };
    if (/^\.\.?\//.test(specifier) && !/\.[a-z]+$/.test(specifier)) return nextResolve(`${specifier}.ts`, context);
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.startsWith('odoo-native-test:')) {
      const key = url.slice('odoo-native-test:'.length); const value = mocks[key];
      const source = ['react-native-blob-util', '@react-native-async-storage/async-storage'].includes(key)
        ? `export default globalThis.__odooNativeTestMocks[${JSON.stringify(key)}];`
        : Object.keys(value as object).map(name => `export const ${name}=globalThis.__odooNativeTestMocks[${JSON.stringify(key)}][${JSON.stringify(name)}];`).join('\n');
      return { format: 'module', source, shortCircuit: true };
    }
    return nextLoad(url, context);
  },
});
process.env.EXPO_PUBLIC_ODOO_ORIGIN = 'https://odoo.example'; process.env.EXPO_PUBLIC_ODOO_DATABASE = 'trial';
const { getEngine, getOrdersEngine, ordersOnlySnapshot, refreshOrdersOnlySession, setOrdersConnectivity, localMedia, localMediaLease, stageFile, readGroupAvatar, hasGroupAvatar, clearGroupAvatars, subscribeGroupAvatars, readMemberAvatar, clearMemberAvatars } = await import('../runtime.ts');
const engine = getEngine();

test('real native adapter maps no-cookie session fixture then rejects cross-room media and validates offline bytes', async () => {
  await engine.login('alice', 'private', true); await engine.history(roomA);
  const before = calls.filter(c => c.path.endsWith('/media/70/content')).length;
  await assert.rejects(localMedia(roomB, media), { code: 'media_room_mismatch' });
  assert.equal(calls.filter(c => c.path.endsWith('/media/70/content')).length, before);
  const uri = await localMedia(roomA, { ...media, mime: 'image/png', sha256: 'b'.repeat(64) });
  assert.match(uri, /c1-r11-m21\/media-70\.pdf$/); assert.deepEqual(files.get(uri), payload);
  const warmRequests = calls.length;
  assert.equal(await localMedia(roomA, media), uri);
  assert.equal(calls.length, warmRequests, 'warm scoped media rechecks local bytes without another messages/content request');
  await assert.rejects(localMedia(roomA, { id: 71 }), { code: 'media_room_mismatch' });
  assert.equal(calls.length, warmRequests + 1, 'unknown media association falls back to authoritative history');
  assert.equal(calls.at(-1)!.path, '/bchat/api/v2/rooms/11/messages');
  engine.markDisconnected(); offline = true;
  assert.equal(await localMedia(roomA, media), uri);
  files.set(uri, Buffer.from('x'.repeat(payload.length)));
  await assert.rejects(localMedia(roomA, media), { code: 'media_not_cached' }); assert.equal(files.has(uri), false);
  offline = false; await engine.refresh();
});
test('real runtime prunes revoked cache but preserves durable stages across same-user login', async () => {
  const uri = await localMedia(roomA, media);
  files.set('file:///external/report.pdf', payload);
  const staged = await stageFile(roomA, { uri: 'file:///external/report.pdf', name: 'report.pdf', mime: 'application/pdf' });
  await engine.enqueueAttachment(roomA, staged);
  await assert.rejects(engine.enqueueAttachment(roomA, staged), { code: 'attachment_already_queued' });
  assert.equal(files.has(staged.uri), true, 'a rejected duplicate must not delete an existing queued file');
  await engine.login('alice', 'private', true); assert.equal(files.has(staged.uri), true);
  mediaRight = false; await engine.refresh();
  assert.equal(files.has(uri), false); assert.equal(files.has(staged.uri), false); assert.equal(engine.pending().length, 0);
  const revokedRequests = calls.length;
  await assert.rejects(localMedia(roomA, media), { code: 'forbidden' });
  assert.equal(calls.length, revokedRequests, 'authorization failure is never swallowed into a network fallback');
  mediaRight = true; await engine.refresh();
  const restored = await localMedia(roomA, media); assert.equal(files.has(restored), true);
  rooms = [roomB]; await engine.refresh(); assert.equal(files.has(restored), false);
  rooms = [roomA, roomB]; await engine.refresh();
});
test('authoritative account revocation purges native cached media after core invalidates generation', async () => {
  const uri = await localMedia(roomA, media); assert.equal(files.has(uri), true);
  revoked = true; await assert.rejects(engine.refresh(), { code: 'forbidden', status: 403 });
  assert.equal(engine.identity, null); assert.equal(engine.status, 'signed_out'); assert.equal(files.has(uri), false);
  revoked = false; await engine.login('alice', 'private', true);
});
test('stale refresh from an old generation cannot purge the new session native cache', async () => {
  let release!: () => void; let started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }); const waiting = new Promise<void>(resolve => { started = resolve; });
  beforeNative = async path => { if (path.endsWith('/bootstrap')) { beforeNative = undefined; started(); await wait; } };
  const refresh = engine.refresh(); const outcome = assert.rejects(refresh, { code: 'stale_session' });
  await waiting; await engine.login('alice', 'private', true);
  const uri = await localMedia(roomA, media); release(); await outcome;
  assert.equal(engine.identity?.user_id, 7); assert.equal(files.has(uri), true);
});
test('real runtime preserves locked stages after transient login failure and verified same-user recovery', async () => {
  const staged = await stageFile(roomA, { uri: 'file:///external/report.pdf', name: 'report.pdf', mime: 'application/pdf' });
  await engine.enqueueAttachment(roomA, staged); offline = true;
  await assert.rejects(engine.login('alice', 'private', true), { code: 'connection_failed' });
  assert.equal(files.has(staged.uri), true); assert.equal(engine.identity, null);
  assert.equal(await engine.restoreOffline(), false); assert.equal(files.has(staged.uri), true);
  offline = false; await engine.login('alice', 'private', true);
  assert.equal(engine.pending().length, 1); assert.equal(files.has(staged.uri), true);
  await engine.logout(); assert.equal(files.has(staged.uri), false);
});
test('missing native response metadata fails closed with a safe stage code before authenticate', async () => {
  missingMetadata = true;
  const before = calls.filter(c => c.path.endsWith('/authenticate')).length;
  try {
    await assert.rejects(engine.login('alice', 'private', true), { code: 'native_response_missing', loginStage: 'session_close' });
    assert.equal(calls.filter(c => c.path.endsWith('/authenticate')).length, before);
    assert.equal(engine.identity, null);
  } finally { missingMetadata = false; }
});

test('native DNS failure retains original retry code and adds only a sanitized hint', async () => {
  nativeFailure = new Error('Unable to resolve host private.example with password=sentinel');
  try {
    await assert.rejects(engine.login('alice', 'private', true), { code: 'connection_failed', networkFailure: 'DNS', loginStage: 'session_close' });
    assert.equal(engine.identity, null);
  } finally { nativeFailure = undefined; }
});

test('bootstrap redirect snapshots native bits before cleanup and ignores non-bit header values', async () => {
  for (const value of ['I1A1S1M1L1', 'session_id=private-sentinel']) {
    bootstrapDiagnostic = value;
    const before = calls.length;
    try {
      await assert.rejects(engine.login('alice', 'private', true), (error: any) => {
        assert.equal(error.code, 'redirect_denied');
        assert.equal(error.status, 303);
        assert.equal(error.loginStage, 'bootstrap');
        assert.equal(error.sessionTrace, value === 'I1A1S1M1L1' ? value : undefined);
        assert.equal(JSON.stringify(error).includes('private-sentinel'), false);
        return true;
      });
      assert.deepEqual(calls.slice(before).map(call => call.path), [
        '/web/session/destroy', '/web/session/authenticate', '/bchat/api/v2/bootstrap', '/web/session/destroy',
      ]);
      assert.equal(engine.identity, null);
    } finally { bootstrapDiagnostic = undefined; }
  }
});

test('Odoo stateful authentication omits stateless database header and reaches scoped bootstrap', async () => {
  emulateOdooStatelessHeader = true; statefulSessionIssued = false;
  const before = calls.length;
  try {
    await engine.login('alice', 'private', true);
    assert.equal(statefulSessionIssued, true);
    assert.equal(engine.identity?.database, 'trial');
    assert.equal(engine.identity?.user_id, 7);
    assert.deepEqual(calls.slice(before).map(call => call.path), [
      '/web/session/destroy', '/web/session/authenticate', '/bchat/api/v2/bootstrap', '/bchat/api/v2/rooms',
    ]);
  } finally { emulateOdooStatelessHeader = false; }
});

test('group avatar reader uses actual binary base64 decoder, membership scope, shared in-flight request and media-independent rights', async () => {
  await engine.login('alice', 'private', true); clearGroupAvatars();
  mediaRight = false; avatarCanManage = false; await engine.refresh();
  const before = avatarReads;
  const [a, b] = await Promise.all([readGroupAvatar(engine, roomA), readGroupAvatar(engine, roomA)]);
  assert.deepEqual(a, b); assert.equal(avatarReads, before + 1); assert.equal(hasGroupAvatar(a.key), true);
  assert.equal(a.uri, `data:image/png;base64,${png.toString('base64')}`);
  assert.equal(await readGroupAvatar(engine, roomA).then(image => image.key), a.key);
  assert.equal(avatarReads, before + 1);
  engine.markDisconnected(); offline = true;
  assert.equal((await readGroupAvatar(engine, roomA)).key, a.key, 'private warm image remains bounded by offline identity');
  await assert.rejects(readGroupAvatar(engine, { ...roomA, membership_id: 999 }));
  offline = false; mediaRight = true; avatarCanManage = true; await engine.refresh();
});

test('avatar version mismatch refreshes exact metadata and retries at most once, invalid headers and PNG are never cached', async () => {
  clearGroupAvatars(); const old = { ...roomA }; roomA.avatar_version++;
  const before = avatarReads, metadata = groupReads;
  const image = await readGroupAvatar(engine, old);
  assert.equal(image.version, roomA.avatar_version); assert.equal(avatarReads, before + 2); assert.equal(groupReads, metadata + 1);
  for (const invalid of ['mime', 'version', 'dimensions', 'size']) {
    clearGroupAvatars(); avatarBytes = Buffer.from(png);
    if (invalid === 'mime') avatarMime = 'text/html';
    if (invalid === 'version') avatarHeader = '01';
    if (invalid === 'dimensions') avatarBytes.writeUInt32BE(257, 16);
    if (invalid === 'size') avatarBytes = Buffer.concat([png, Buffer.alloc(256 * 1024)]);
    await assert.rejects(readGroupAvatar(engine, roomA), { code: 'invalid_response' });
    avatarMime = 'image/png'; avatarHeader = undefined; avatarBytes = png;
  }
  clearGroupAvatars(); avatarHeader = String(roomA.avatar_version + 1);
  const bounded = avatarReads;
  await assert.rejects(readGroupAvatar(engine, roomA), { code: 'invalid_response' });
  assert.equal(avatarReads, bounded + 2); avatarHeader = undefined;
});

test('late avatar reads cannot restore a masked cache, and membership revocation clears permitted old data', async () => {
  clearGroupAvatars(); let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }); const waiting = new Promise<void>(resolve => { started = resolve; });
  beforeNative = async path => { if (path.endsWith('/avatar')) { beforeNative = undefined; started(); await wait; } };
  const pending = readGroupAvatar(engine, roomA); const outcome = assert.rejects(pending, { code: 'stale_session' });
  await waiting; clearGroupAvatars(); release(); await outcome;
  const image = await readGroupAvatar(engine, roomA); assert.equal(hasGroupAvatar(image.key), true);
  rooms = [roomB]; await engine.refresh(); assert.equal(hasGroupAvatar(image.key), false);
  rooms = [roomA, roomB]; await engine.refresh();
});

test('actual data-URI LRU stays under 4MiB without evicting durable outbox or allowing stale generation cleanup', async () => {
  clearGroupAvatars(); avatarBytes = Buffer.concat([png, Buffer.alloc(256 * 1024 - png.length)]);
  const original = rooms; rooms = Array.from({ length: 15 }, (_, i) => ({ ...roomA, id: 100 + i, membership_id: 200 + i }));
  await engine.refresh(); const images = [];
  await engine.enqueue(rooms[0]!, 'Synthetic unACKed text survives avatar eviction');
  const outbox = engine.pending();
  for (const room of rooms) images.push(await readGroupAvatar(engine, room));
  const retained = images.filter(image => hasGroupAvatar(image.key));
  assert.ok(retained.length < images.length); assert.ok(retained.reduce((sum, item) => sum + item.uri.length, 0) <= 4 * 1024 * 1024);
  assert.equal(hasGroupAvatar(images[0]!.key), false); assert.equal(hasGroupAvatar(images.at(-1)!.key), true);
  assert.deepEqual(engine.pending(), outbox, 'avatar-only LRU never evicts unACKed messages');
  rooms = original; avatarBytes = png; await engine.refresh();
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }); const waiting = new Promise<void>(resolve => { started = resolve; });
  beforeNative = async path => { if (path.endsWith('/bootstrap')) { beforeNative = undefined; started(); await wait; } };
  const refresh = engine.refresh(); const stale = assert.rejects(refresh, { code: 'stale_session' }); await waiting;
  await engine.login('alice', 'private', true); const current = await readGroupAvatar(engine, roomA);
  release(); await stale; assert.equal(hasGroupAvatar(current.key), true, 'old generation cannot clear new avatar cache');
});

test('avatar multipart is exact, staged input is isolated, bounds are local, lost ACK never retries POST', async () => {
  files.set('file:///external/avatar.png', png); const uploads = avatarUploads;
  const before = await engine.setGroupAvatar(roomA, { uri: 'file:///external/avatar.png', name: 'private-source.png', mime: 'image/png' });
  assert.equal(before.room.avatar_version, roomA.avatar_version); assert.equal(avatarUploads, uploads + 1);
  assert.equal([...files.keys()].some(key => key.includes('odoo-group-avatar-')), false);
  assert.equal(files.has('file:///external/avatar.png'), true);
  const pending = engine.pending().length;
  files.set('file:///external/oversize.png', Buffer.alloc(2 * 1024 * 1024 + 1));
  await assert.rejects(engine.setGroupAvatar(roomA, { uri: 'file:///external/oversize.png', name: 'big.png', mime: 'image/png' }), { code: 'avatar_invalid' });
  assert.equal(avatarUploads, uploads + 1); assert.equal(engine.pending().length, pending);
  avatarCanManage = false;
  await assert.rejects(engine.setGroupAvatar(roomA, { uri: 'file:///external/avatar.png', name: 'private.png', mime: 'image/png' }), { code: 'group_manage_denied' });
  assert.equal(avatarUploads, uploads + 1); avatarCanManage = true;
  avatarLostAck = true;
  try { await assert.rejects(engine.setGroupAvatar(roomA, { uri: 'file:///external/avatar.png', name: 'private.png', mime: 'image/png' }), { code: 'avatar_uncertain' }); }
  finally { avatarLostAck = false; }
  assert.equal(avatarUploads, uploads + 2, 'uncertain mutation is attempted exactly once');
  assert.equal([...files.keys()].some(key => key.includes('odoo-group-avatar-')), false);
  const image = await readGroupAvatar(engine, roomA); let notifications = 0;
  const unsubscribe = subscribeGroupAvatars(() => { notifications++; });
  await engine.logout(); assert.equal(hasGroupAvatar(image.key), false); assert.ok(notifications > 0); unsubscribe();
});

test('avatar metadata await cannot carry a revoked membership into POST and always removes its temporary copy', async () => {
  await engine.login('alice', 'private', true);
  files.set('file:///external/fenced-avatar.png', png);
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }); const waiting = new Promise<void>(resolve => { started = resolve; });
  beforeStat = async uri => { if (uri.includes('/odoo-group-avatar-')) { beforeStat = undefined; started(); await wait; } };
  const before = avatarUploads;
  const upload = engine.setGroupAvatar(roomA, { uri: 'file:///external/fenced-avatar.png', name: 'group.png', mime: 'image/png' });
  const rejected = assert.rejects(upload, { code: 'membership_changed' });
  try {
    await waiting; rooms = [roomB]; await engine.refresh(); release(); await rejected;
    assert.equal(avatarUploads, before, 'no avatar POST after membership revoked during stat');
    assert.equal([...files.keys()].some(key => key.includes('/odoo-group-avatar-')), false);
    assert.equal(files.has('file:///external/fenced-avatar.png'), true);
  } finally { beforeStat = undefined; release(); rooms = [roomA, roomB]; await engine.refresh(); }
});

test('real previews fetch only protected thumbnails; explicit original stays separate and warm lookup avoids directory scans', async () => {
  await engine.login('alice', 'private', true);
  extraMedia.set(imageMedia.id, { metadata: imageMedia, bytes: imageBytes }); await engine.history(roomA);
  const before = calls.length, scans = directoryReads;
  const a = await localMediaLease(roomA, { id: imageMedia.id, thumbnail_available: false }, 'preview');
  assert.match(a.uri, /media-170-preview\.jpg$/); assert.deepEqual(files.get(a.uri), thumbnail);
  assert.deepEqual(calls.slice(before).map(c => c.path), ['/bchat/api/v2/media/170/thumbnail']);
  const b = await localMediaLease(roomA, { id: imageMedia.id }, 'preview');
  assert.equal(b.uri, a.uri); assert.equal(calls.length, before + 1); assert.equal(directoryReads, scans);
  const full = await localMediaLease(roomA, { id: imageMedia.id }, 'original');
  assert.match(full.uri, /media-170\.jpg$/); assert.deepEqual(files.get(full.uri), imageBytes);
  assert.notEqual(full.uri, a.uri); assert.equal(directoryReads, scans);
  a.release(); a.release(); b.release(); full.release();
  await engine.refresh(); assert.equal(directoryReads, scans, 'polling no longer recursively scans native cache');
  extraMedia.clear(); await engine.history(roomA);
});

test('modern preview uses a verified cached original when its thumbnail is absent, offline and without original HTTP', async () => {
  await engine.logout(); await engine.login('alice', 'private', true);
  extraMedia.set(imageMedia.id, { metadata: imageMedia, bytes: imageBytes }); await engine.history(roomA);
  const original = await localMediaLease(roomA, { id: 170 }, 'original'); original.release();
  const before = calls.length; engine.markDisconnected(); offline = true;
  try {
    const preview = await localMediaLease(roomA, { id: 170 }, 'preview');
    assert.equal(preview.uri, original.uri); assert.equal(calls.length, before); preview.release();
    files.set(original.uri, Buffer.alloc(imageBytes.length, 1));
    await assert.rejects(localMediaLease(roomA, { id: 170 }, 'preview'), { code: 'media_not_cached' });
    assert.equal(files.has(original.uri), false); assert.equal(calls.length, before);
  } finally { offline = false; await engine.refresh(); extraMedia.clear(); await engine.history(roomA); }
});

test('cached-only audio/file lookup cannot download bytes and keeps the normal authorization fences', async () => {
  await engine.logout(); await engine.login('alice', 'private', true); await engine.history(roomA);
  const before = calls.length;
  await assert.rejects(localMediaLease(roomA, media, 'original', true), { code: 'media_not_cached' });
  assert.equal(calls.length, before);
  const original = await localMediaLease(roomA, media); original.release();
  const cached = await localMediaLease(roomA, media, 'original', true); cached.release();
  assert.equal(cached.uri, original.uri);
  await assert.rejects(localMediaLease(roomB, media, 'original', true), { code: 'media_room_mismatch' });
});

test('member avatars use the protected scoped endpoint, deduplicate, validate PNG and reject background/late membership results', async () => {
  await engine.login('alice', 'private', true); clearMemberAvatars();
  avatarBytes = png; avatarMime = 'image/png';
  const before = calls.length;
  const [first, second] = await Promise.all([readMemberAvatar(roomA, 7), readMemberAvatar(roomA, 7)]);
  assert.equal(first, second); assert.match(first, /^data:image\/png;base64,/);
  assert.deepEqual(calls.slice(before).map(c => c.path), ['/bchat/api/v2/rooms/11/members/7/avatar']);
  assert.equal(await readMemberAvatar(roomA, 7), first); assert.equal(calls.length, before + 1);
  appState.currentState = 'background';
  await assert.rejects(readMemberAvatar(roomA, 7), { code: 'avatar_missing' }); appState.currentState = 'active';
  clearMemberAvatars(); avatarMime = 'text/html'; await assert.rejects(readMemberAvatar(roomA, 7), { code: 'invalid_response' }); avatarMime = 'image/png';
  let release!: () => void, start!: () => void;
  const waiting = new Promise<void>(resolve => { start = resolve; }); const hold = new Promise<void>(resolve => { release = resolve; });
  beforeNative = async path => { if (path.includes('/members/')) { beforeNative = undefined; start(); await hold; } };
  const result = readMemberAvatar(roomA, 7); const rejected = assert.rejects(result, { code: 'membership_changed' });
  await waiting; rooms = [roomB]; await engine.refresh(); release(); await rejected;
  rooms = [roomA, roomB]; await engine.refresh(); clearMemberAvatars();
});

test('thumbnail failure never downloads original; legacy previews require an already verified original', async () => {
  await engine.logout(); await engine.login('alice', 'private', true);
  extraMedia.set(imageMedia.id, { metadata: imageMedia, bytes: imageBytes }); await engine.history(roomA);
  for (const invalid of ['mime', 'dimensions', 'length']) {
    thumbnailBytes = Buffer.from(thumbnail);
    if (invalid === 'mime') thumbnailMime = 'text/html';
    if (invalid === 'dimensions') { thumbnailBytes[7] = 1; thumbnailBytes[8] = 1; }
    if (invalid === 'length') thumbnailBytes = Buffer.alloc(128 * 1024 + 1);
    const before = calls.length;
    await assert.rejects(localMediaLease(roomA, { id: imageMedia.id }, 'preview'), { code: 'invalid_response' });
    assert.deepEqual(calls.slice(before).map(c => c.path), ['/bchat/api/v2/media/170/thumbnail']);
    assert.equal([...files.keys()].some(uri => uri.endsWith('.part')), false);
    thumbnailBytes = thumbnail; thumbnailMime = 'image/jpeg';
  }
  extraMedia.set(imageMedia.id, { metadata: { ...imageMedia, thumbnail_available: false }, bytes: imageBytes }); await engine.history(roomA);
  const before = calls.length;
  await assert.rejects(localMediaLease(roomA, { id: imageMedia.id, thumbnail_available: true }, 'preview'), { code: 'media_not_cached' });
  assert.equal(calls.length, before, 'caller cannot turn missing thumbnail into an automatic original download');
  const original = await localMediaLease(roomA, { id: imageMedia.id }); original.release();
  const preview = await localMediaLease(roomA, { id: imageMedia.id }, 'preview');
  assert.equal(preview.uri, original.uri); preview.release(); extraMedia.clear(); await engine.history(roomA);
});

test('128MiB LRU evicts only replaceable cache, preserving live leases and protected stages; all-pinned fails safely', async () => {
  await engine.logout(); await engine.login('alice', 'private', true);
  const bytes = Buffer.alloc(10 * 1024 * 1024, 80), digest = createHash('sha256').update(bytes).digest('hex');
  for (let n = 0; n < 15; n++) extraMedia.set(300 + n, { metadata: { ...media, id: 300 + n, size: bytes.length, sha256: digest }, bytes });
  await engine.history(roomA);
  files.set('file:///external/protected.pdf', payload);
  const staged = await stageFile(roomA, { uri: 'file:///external/protected.pdf', name: 'protected.pdf', mime: media.mime });
  await engine.enqueueAttachment(roomA, staged);
  const held = await localMediaLease(roomA, { id: 300 });
  const evicted = await localMedia(roomA, { id: 301 });
  for (let n = 2; n < 13; n++) await localMedia(roomA, { id: 300 + n });
  assert.equal(files.has(held.uri), true); assert.equal(files.has(evicted), false); assert.equal(files.has(staged.uri), true);
  const pins = [held];
  for (let n = 2; n < 13; n++) pins.push(await localMediaLease(roomA, { id: 300 + n }));
  const before = calls.length;
  await assert.rejects(localMediaLease(roomA, { id: 313 }), { code: 'media_quota' });
  assert.equal(calls.length, before); assert.equal([...files.keys()].some(uri => uri.endsWith('.part')), false);
  for (const lease of pins) lease.release();
  const next = await localMediaLease(roomA, { id: 313 }); next.release();
  assert.equal(files.has(staged.uri), true); assert.ok(Number((sqlite.prepare('SELECT SUM(bytes) AS bytes FROM media_cache').get() as any).bytes) <= 128 * 1024 * 1024);
  extraMedia.clear(); await engine.logout(); await engine.login('alice', 'private', true);
});

test('concurrent thumbnail leases share one network body; offline corruption is removed rather than trusted', async () => {
  extraMedia.set(imageMedia.id, { metadata: imageMedia, bytes: imageBytes }); await engine.history(roomA);
  const before = calls.length;
  const [first, second] = await Promise.all([localMediaLease(roomA, { id: 170 }, 'preview'), localMediaLease(roomA, { id: 170 }, 'preview')]);
  assert.equal(first.uri, second.uri); assert.equal(calls.length, before + 1);
  first.release(); second.release(); files.set(first.uri, Buffer.alloc(thumbnail.length, 1));
  engine.markDisconnected(); offline = true;
  try {
    await assert.rejects(localMediaLease(roomA, { id: 170 }, 'preview'), { code: 'media_not_cached' });
    assert.equal(files.has(first.uri), false);
  } finally { offline = false; await engine.refresh(); }
  extraMedia.clear(); await engine.history(roomA);
});

test('membership revoked during thumbnail response cannot commit or expose a late cached image', async () => {
  await engine.logout(); await engine.login('alice', 'private', true);
  extraMedia.set(imageMedia.id, { metadata: imageMedia, bytes: imageBytes }); await engine.history(roomA);
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }), waiting = new Promise<void>(resolve => { started = resolve; });
  beforeNative = async path => { if (path.endsWith('/thumbnail')) { beforeNative = undefined; started(); await wait; } };
  const preview = localMediaLease(roomA, { id: 170 }, 'preview'); const rejected = assert.rejects(preview, { code: 'membership_changed' });
  await waiting; rooms = [roomB]; const refreshing = engine.refresh();
  for (let n = 0; n < 100 && engine.rooms().some(row => row.id === roomA.id); n++) await Promise.resolve();
  assert.equal(engine.rooms().some(row => row.id === roomA.id), false);
  release(); await rejected; await refreshing;
  assert.equal([...files.keys()].some(uri => uri.includes('media-170')), false);
  rooms = [roomA, roomB]; extraMedia.clear(); await engine.refresh();
});

test('SQLite catalog seam recovers a verified preview after a fresh runtime module without re-downloading', async () => {
  await engine.login('alice', 'private', true);
  extraMedia.set(imageMedia.id, { metadata: imageMedia, bytes: imageBytes }); await engine.history(roomA);
  const original = await localMediaLease(roomA, { id: 170 }, 'preview'); original.release();
  // A fresh module models process-local maps/pins disappearing; only files and
  // persisted catalog/identity remain. Actual SQLite persistence has its own harness.
  const restarted = await import(new URL('../runtime.ts?media-restart', import.meta.url).href);
  const fresh = restarted.getEngine(); await fresh.login('alice', 'private', true); await fresh.history(roomA);
  const before = calls.length;
  const recovered = await restarted.localMediaLease(roomA, { id: 170 }, 'preview');
  assert.equal(recovered.uri, original.uri); assert.equal(calls.length, before); recovered.release();
  await fresh.logout(); extraMedia.clear(); await engine.login('alice', 'private', true);
});

test('file-count LRU reconciles more than the old 1000-file ceiling and evicts deterministically at 5000', async () => {
  await engine.logout();
  const actorHash = createHash('sha256').update('https://odoo.example|trial|7').digest('hex');
  const actor = `file:///app/odoo-chat-media/${actorHash}/`, directory = `${actor}c1-r11-m21/`;
  makeDirectory(directory);
  const one = Buffer.from('x'), digest = createHash('sha256').update(one).digest('hex');
  for (let n = 0; n < 5001; n++) {
    const uri = `${directory}media-${10000 + n}.pdf`; files.set(uri, one);
    // A legacy/orphan file can exist outside the catalog after interruption;
    // the strict SQL catalog itself correctly refuses a 5001st indexed row.
    if (n > 0) await catalog.put(actorHash, { uri, bytes: 1, sha256: digest, usedAt: n });
  }
  const restarted = await import(new URL('../runtime.ts?file-count-restart', import.meta.url).href);
  const fresh = restarted.getEngine(); await fresh.login('alice', 'private', true);
  assert.equal(files.has(`${directory}media-10000.pdf`), false);
  assert.equal(files.has(`${directory}media-10001.pdf`), true);
  assert.equal((await catalog.list(actorHash)).length, 5000);
  await fresh.history(roomA); await restarted.localMedia(roomA, media);
  assert.equal(files.has(`${directory}media-10001.pdf`), false);
  assert.equal(files.has(`${directory}media-15000.pdf`), true);
  await fresh.logout(); await engine.login('alice', 'private', true);
});

const ordersBootstrap = (changes: Record<string, unknown> = {}) => ({ api_version: 2, database: 'trial', user_id: 7,
  company_ids: [1], csrf_token: 'notpersisted', permissions: { chat_view: false, chat_send: false,
    order_view: true, order_create: false, order_receive: false }, ...changes });

test('native orders-only login purges chat, never fetches rooms or restores chat, and requires fresh foreground authority', async () => {
  await engine.login('alice', 'private', true); await engine.history(roomA);
  const cached = await localMedia(roomA, media);
  storage.set('bwork/orders/v1/synthetic-unknown', 'preserve durable order intent');
  bootstrapOverride = ordersBootstrap(); const before = calls.length;
  try {
    const identity = await engine.login('orders-only', 'private', true);
    assert.equal(identity.permissions.chat_view, false); assert.equal(engine.identity, null);
    assert.equal(engine.status, 'signed_out'); assert.equal(ordersOnlySnapshot().verified, true);
    assert.equal(files.has(cached), false);
    assert.equal(calls.slice(before).some(c => c.path.includes('/rooms')), false);
    assert.ok(![...storage.values()].some(v => v.includes('csrf_token')));
    assert.equal(storage.get('bwork/orders/v1/synthetic-unknown'), 'preserve durable order intent');
    const options = await getOrdersEngine().options(); assert.equal(options.companies[0]!.id, 1);
    setOrdersConnectivity(false); assert.equal(ordersOnlySnapshot().verified, false);
    await assert.rejects(getOrdersEngine().options(), { code: 'unauthorized' });
    setOrdersConnectivity(true); await assert.rejects(getOrdersEngine().options(), { code: 'unauthorized' });
    await refreshOrdersOnlySession(); assert.equal(ordersOnlySnapshot().verified, true);
    appState.currentState = 'background'; await assert.rejects(getOrdersEngine().options(), { code: 'unauthorized' });
    appState.currentState = 'active';
    bootstrapOverride = ordersBootstrap({ company_ids: [2] }); await refreshOrdersOnlySession();
    assert.deepEqual(ordersOnlySnapshot().identity!.company_ids, [2]);
    bootstrapOverride = ordersBootstrap({ permissions: { chat_view: false, order_view: false } });
    await assert.rejects(refreshOrdersOnlySession(), { code: 'forbidden' });
    assert.equal(ordersOnlySnapshot().identity, null); assert.equal(engine.identity, null);
  } finally { bootstrapOverride = undefined; appState.currentState = 'active'; setOrdersConnectivity(true); await engine.logout(); }
});

test('native orders-only rejects forged uid and cleanup failure before publishing application authority', async () => {
  bootstrapOverride = ordersBootstrap({ user_id: 8 });
  await assert.rejects(engine.login('orders-only', 'private', true), { code: 'identity_mismatch' });
  assert.equal(ordersOnlySnapshot().identity, null);
  bootstrapOverride = undefined; await engine.login('alice', 'private', true); await engine.history(roomA);
  await localMedia(roomA, media); bootstrapOverride = ordersBootstrap(); failOwnedDelete = true;
  try {
    await assert.rejects(engine.login('orders-only', 'private', true), /cleanup failure/);
    assert.equal(ordersOnlySnapshot().identity, null); assert.equal(engine.identity, null);
  } finally { failOwnedDelete = false; bootstrapOverride = undefined; await engine.logout(); }
});

test('native stale orders-only login cannot publish after a newer login and stale orders 401 cannot log it out', async () => {
  bootstrapOverride = ordersBootstrap();
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }); const seen = new Promise<void>(resolve => { started = resolve; });
  beforeNative = async path => { if (path.endsWith('/bootstrap')) { beforeNative = undefined; started(); await wait; } };
  const old = engine.login('old', 'private', true); const rejected = assert.rejects(old, { code: 'stale_session' });
  await seen; bootstrapOverride = undefined;
  const newer = engine.login('new', 'private', true); release(); await rejected; await newer;
  assert.equal(engine.identity!.user_id, 7); assert.equal(ordersOnlySnapshot().identity, null);
  bootstrapOverride = ordersBootstrap(); await engine.login('orders-only', 'private', true);
  let releaseOrder!: () => void, orderStarted!: () => void;
  const orderWait = new Promise<void>(resolve => { releaseOrder = resolve; }); const orderSeen = new Promise<void>(resolve => { orderStarted = resolve; });
  beforeNative = async path => { if (path.endsWith('/orders/options')) { beforeNative = undefined; orderStarted(); await orderWait; } };
  ordersStatus = 401;
  const oldOrder = getOrdersEngine().options(); const denied = assert.rejects(oldOrder, { code: 'stale' });
  await orderSeen; bootstrapOverride = undefined;
  await engine.login('new', 'private', true); releaseOrder(); await denied;
  assert.equal(engine.identity!.user_id, 7); assert.equal(engine.status, 'ready');
  assert.equal(ordersOnlySnapshot().identity, null); ordersStatus = 200;
});

test('orders access epoch rejects pre-disconnect reads and old foreground verification without locking a newer verification', async () => {
  bootstrapOverride = ordersBootstrap(); await engine.login('orders-only', 'private', true);
  let release!: () => void, started!: () => void;
  let wait = new Promise<void>(resolve => { release = resolve; }); let seen = new Promise<void>(resolve => { started = resolve; });
  beforeNative = async path => { if (path.endsWith('/orders/options')) { beforeNative = undefined; started(); await wait; } };
  const read = getOrdersEngine().options(); const rejected = assert.rejects(read, { code: 'stale' });
  await seen; setOrdersConnectivity(false); setOrdersConnectivity(true); await refreshOrdersOnlySession();
  release(); await rejected; assert.equal(ordersOnlySnapshot().verified, true);
  wait = new Promise<void>(resolve => { release = resolve; }); seen = new Promise<void>(resolve => { started = resolve; });
  beforeNative = async path => { if (path.endsWith('/bootstrap')) { beforeNative = undefined; started(); await wait; } };
  const prior = refreshOrdersOnlySession(); const stale = assert.rejects(prior, { code: 'stale_session' });
  await seen; setOrdersConnectivity(false); setOrdersConnectivity(true); await refreshOrdersOnlySession();
  const currentRevision = ordersOnlySnapshot().revision;
  release(); await stale;
  assert.equal(ordersOnlySnapshot().revision, currentRevision); assert.equal(ordersOnlySnapshot().verified, true);
  bootstrapOverride = undefined; await engine.logout();
});

test('same-authority orders renewal retains verified option restrictions while fencing manual-refresh HTTP completions', async () => {
  bootstrapOverride = ordersBootstrap({ permissions: { chat_view: false, chat_send: false, order_view: true, order_create: true, order_receive: false } });
  try {
    await engine.login('orders-only', 'private', true);
    const orders = getOrdersEngine(); await orders.options(); // Server options deny create despite the broad bootstrap grant.
    await assert.rejects(orders.catalog(1), { code: 'forbidden' });
    setOrdersConnectivity(false); setOrdersConnectivity(true); await refreshOrdersOnlySession();
    const before = calls.length;
    await assert.rejects(orders.catalog(1), { code: 'forbidden' });
    assert.equal(calls.length, before, 'same-authority renewal must not discard verified option restrictions');
    let release!: () => void, started!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
    const seen = new Promise<void>(resolve => { started = resolve; });
    beforeNative = async path => { if (path.endsWith('/orders/options')) { beforeNative = undefined; started(); await wait; } };
    const read = orders.options(); const rejected = assert.rejects(read, { code: 'stale' });
    await seen; await refreshOrdersOnlySession(); release(); await rejected;
    assert.equal(ordersOnlySnapshot().verified, true);
  } finally { bootstrapOverride = undefined; beforeNative = undefined; setOrdersConnectivity(true); await engine.logout(); }
});

test('native current orders 401 closes only its own scope and ordinary chat login still fetches rooms', async () => {
  bootstrapOverride = ordersBootstrap(); await engine.login('orders-only', 'private', true);
  ordersStatus = 401;
  try { await assert.rejects(getOrdersEngine().options()); assert.equal(ordersOnlySnapshot().identity, null); assert.equal(engine.identity, null); }
  finally { ordersStatus = 200; bootstrapOverride = undefined; }
  const before = calls.length; await engine.login('alice', 'private', true);
  assert.equal(engine.identity!.permissions.chat_view, true);
  assert.ok(calls.slice(before).some(c => c.path === '/bchat/api/v2/rooms'));
});

test('real runtime logout removes cached files and refuses HTTP redirects before authenticate', async () => {
  await engine.login('alice', 'private', true);
  const uri = await localMedia(roomA, media); await engine.logout(); assert.equal(files.has(uri), false);
  redirect = true; const before = calls.filter(c => c.path.endsWith('/authenticate')).length;
  await assert.rejects(engine.login('alice', 'private', true), { code: 'redirect_denied' });
  assert.equal(calls.filter(c => c.path.endsWith('/authenticate')).length, before);
  redirect = false;
  unauthorized = true;
  await assert.rejects(engine.login('alice', 'private', true), { code: 'unauthenticated', status: 401 });
  assert.equal(calls.filter(c => c.path.endsWith('/authenticate')).length, before);
  unauthorized = false;
  hooks.deregister();
});

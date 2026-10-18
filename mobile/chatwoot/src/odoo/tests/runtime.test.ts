/** Executes the real runtime with native-module seams, not a device/cookie proof. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { createHash, randomUUID } from 'node:crypto';

const files = new Map<string, Buffer>(); const directories = new Set<string>(['file:///app/']);
const normalize = (uri: string) => uri.startsWith('file://') ? uri : `file://${uri}`;
function makeDirectory(uri: string) {
  const parts = uri.replace(/^file:\/\//, '').split('/').filter(Boolean); let path = 'file:///';
  for (const part of parts) { path += `${part}/`; directories.add(path); }
}
const fs = {
  documentDirectory: 'file:///app/',
  async getInfoAsync(uri: string) {
    const value = files.get(normalize(uri)); if (value) return { exists: true, isDirectory: false, size: value.length };
    return { exists: directories.has(uri.endsWith('/') ? uri : `${uri}/`), isDirectory: true, size: 0 };
  },
  async makeDirectoryAsync(uri: string) { makeDirectory(uri); },
  async readDirectoryAsync(uri: string) {
    const prefix = uri.endsWith('/') ? uri : `${uri}/`; const entries = new Set<string>();
    for (const key of [...directories, ...files.keys()]) if (key.startsWith(prefix) && key !== prefix) entries.add(key.slice(prefix.length).split('/')[0]!);
    return [...entries];
  },
  async deleteAsync(uri: string) { files.delete(normalize(uri)); },
  async copyAsync({ from, to }: { from: string; to: string }) { const bytes = files.get(normalize(from)); if (!bytes) throw new Error('missing file'); files.set(normalize(to), Buffer.from(bytes)); },
  async moveAsync({ from, to }: { from: string; to: string }) { const bytes = files.get(normalize(from)); if (!bytes) throw new Error('missing file'); files.set(normalize(to), bytes); files.delete(normalize(from)); },
};
const storage = new Map<string, string>();
const asyncStorage = {
  async getItem(k: string) { return storage.get(k) ?? null; }, async setItem(k: string, v: string) { storage.set(k, v); },
  async removeItem(k: string) { storage.delete(k); }, async getAllKeys() { return [...storage.keys()]; },
};
const payload = Buffer.from('%PDF-1.7 test data %%EOF'); const sha256 = createHash('sha256').update(payload).digest('hex');
const media = { id: 70, kind: 'file', mime: 'application/pdf', name: 'private.pdf', size: payload.length, sha256 };
const roomA = { id: 11, company_id: 1, membership_id: 21, name: 'A', is_group: true };
const roomB = { id: 12, company_id: 1, membership_id: 22, name: 'B', is_group: true };
let rooms = [roomA, roomB]; let mediaRight = true; let offline = false; let redirect = false; let unauthorized = false; let revoked = false;
let beforeNative: ((path: string) => Promise<void>) | undefined;
let missingMetadata = false;
let nativeFailure: Error | undefined;
let bootstrapDiagnostic: string | undefined;
let emulateOdooStatelessHeader = false;
let statefulSessionIssued = false;
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
    else if (path.endsWith('/bootstrap')) body = { api_version: 2, database: 'trial', user_id: 7, company_ids: [1], csrf_token: 'notpersisted', permissions: { chat_view: true, chat_send: true, media: mediaRight } };
    else if (path === '/bchat/api/v2/rooms') body = { api_version: 2, rooms };
    else if (path.endsWith('/changes')) body = { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
    else if (path.endsWith('/11/messages')) body = { api_version: 2, messages: [{ id: 1, author_user_id: 7, author_name: 'A', text: '', created_at: '', media }], next_before_id: null };
    else if (path.endsWith('/12/messages')) body = { api_version: 2, messages: [], next_before_id: null };
    else if (path.endsWith('/media/70/content')) { headers['Content-Type'] = media.mime; headers['Content-Length'] = String(payload.length); if (options.path) files.set(normalize(String(options.path)), Buffer.from(payload)); }
    else throw new Error(`Unexpected test route ${path}`);
    return { info: () => missingMetadata ? { rnfbEncode: 'utf8' } : ({ status, headers, redirects: [url] }), json: () => body };
  });
  task.cancel = () => task; task.progress = () => task;
  return task;
}
const mocks: Record<string, unknown> = {
  'react-native': { Platform: { OS: 'android' } },
  '@react-native-async-storage/async-storage': asyncStorage,
  'expo-crypto': { CryptoDigestAlgorithm: { SHA256: 'SHA256' }, randomUUID, digestStringAsync: async (_algorithm: unknown, value: string) => createHash('sha256').update(value).digest('hex') },
  'expo-file-system/legacy': fs,
  'react-native-blob-util': { config: (options: Record<string, unknown>) => ({ fetch: (method: string, url: string, headers: Record<string, string>, body?: unknown) => nativeFetch(options, method, url, headers, body) }),
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
const { getEngine, localMedia, stageFile } = await import('../runtime.ts');
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

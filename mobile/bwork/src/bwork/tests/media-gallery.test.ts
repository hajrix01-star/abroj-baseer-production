import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ChatEngine, ChatError, type Message, type Request, type Room } from '../core/ChatEngine.ts';
import { decodeGallery, galleryQuery, GALLERY_LIMITS } from '../core/MediaGallery.ts';
import { MemoryHistoryArchive } from '../core/MemoryHistoryArchive.ts';

const room: Room = { id: 4, company_id: 1, membership_id: 12, name: 'Synthetic media', is_group: true };
const item = (id: number, owner = 7, size = 3): Message => ({ id, author_user_id: owner, author_name: 'Synthetic', text: '', created_at: '2026-10-20 10:00:00',
  media: { id: id + 100, kind: 'file', mime: 'text/plain', size, name: `synthetic-${id}.txt`, sha256: 'a'.repeat(64), thumbnail_available: false, size_label: `${size} B` } });
const page = (items = [item(8), item(5, 9)]) => ({ api_version: 2, gallery_version: 1, ...{ room_id: room.id, company_id: room.company_id, membership_id: room.membership_id }, kind: 'all', order: 'newest', items, next_cursor: null as string | null });
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));
function fixture(archive = new MemoryHistoryArchive(), storage = new Map<string, string>()) {
  const calls: Request[] = []; let now = 100000000, allowed = true, mediaAllowed = true, gallery = page(), history = [item(20), item(30, 9)];
  let wait: (() => Promise<void>) | undefined;
  const engine = new ChatEngine({ archive, origin: 'https://synthetic.invalid', database: 'db', now: () => now,
    uuid: () => '12345678-1234-4234-8234-123456789abc', storage: { getItem: async key => storage.get(key) ?? null, setItem: async (key, value) => { storage.set(key, value); }, removeItem: async key => { storage.delete(key); }, getAllKeys: async () => [...storage.keys()] },
    transport: { request: async request => {
      calls.push(request);
      if (request.path === '/web/session/authenticate') return { result: { uid: 7, db: 'db' } };
      if (request.path === '/web/session/destroy') return { result: null };
      if (request.path.endsWith('/bootstrap')) return { api_version: 2, user_id: 7, database: 'db', company_ids: [1], csrf_token: 'synthetic', permissions: { chat_view: true, chat_send: true, media: mediaAllowed } };
      if (request.path === '/bwork/api/v2/rooms') return { api_version: 2, rooms: allowed ? [room] : [] };
      if (request.path.includes('/changes?')) return { api_version: 2, changes: [], next_after: 0, latest_change_id: 0 };
      if (request.path.includes('/media?')) { if (wait) await wait(); return copy(gallery); }
      if (request.path.includes('/messages')) return { api_version: 2, messages: copy(history), next_before_id: null };
      throw new Error('Unexpected synthetic route');
    } } });
  return { engine, archive, storage, calls, history(value: Message[]) { history = value; }, page(value: ReturnType<typeof page>) { gallery = value; }, wait(value: typeof wait) { wait = value; }, revoke() { allowed = false; }, revokeMedia() { mediaAllowed = false; }, advance(ms: number) { now += ms; } };
}
const login = (engine: ChatEngine) => engine.login('synthetic', 'not-real', true);
const archiveAccount = (engine: ChatEngine) => engine.accountScope!.replace(/\/epoch:\d+$/, '');

test('gallery decoder rejects mixed authority, duplicate IDs, invalid cursor, wrong order and oversized pages', () => {
  assert.deepEqual(galleryQuery(), { kind: 'all', order: 'newest', limit: 30 });
  assert.equal(decodeGallery(page(), room).items.length, 2);
  for (const bad of [ { ...page(), room_id: 5 }, { ...page(), membership_id: 13 }, { ...page(), company_id: 2 },
    page([item(8), item(8)]), page([item(5), item(8)]), { ...page(), next_cursor: 'a/b' },
    { ...page([]), next_cursor: 'abcd' }, { ...page(), ignored: 'x'.repeat(GALLERY_LIMITS.bytes) },
    page([{ ...item(8), media: { ...item(8).media, size_label: '3<script>' } }]) ]) assert.throws(() => decodeGallery(bad, room));
  assert.throws(() => decodeGallery({ ...page(), next_cursor: 'abcd' }, room, { cursor: 'abcd' }));
  for (const bad of [{ limit: 61 }, { cursor: 'x'.repeat(257) }, { kind: 'video' }, { unknown: true }]) assert.throws(() => galleryQuery(bad as never));
  const largest = { ...page([item(8, 7, 10), item(5, 9, 10)]), order: 'largest' };
  assert.equal(decodeGallery(largest, room, { order: 'largest' }).items.length, 2);
  assert.throws(() => decodeGallery({ ...largest, items: [...largest.items].reverse() }, room, { order: 'largest' }));
});

test('gallery sparse associations never alter history coverage or acknowledge read receipts', async () => {
  const app = fixture(); await login(app.engine); await app.engine.latest(room);
  const before = app.engine.rememberedHistory(room), start = app.calls.length;
  const result = await app.engine.mediaGallery(room);
  assert.equal(result.items[0].id, 8);
  assert.deepEqual(app.engine.rememberedHistory(room), before);
  assert.deepEqual(app.calls.slice(start).map(request => request.method), ['GET']);
  assert.equal((await app.engine.mediaAssociation(room, 108))?.id, 8);
  assert.equal(app.calls.length, start + 1); // no latest-history request to resolve sparse media
  result.items[0].text = 'mutated';
  assert.equal((await app.engine.mediaAssociation(room, 108))?.text, '');
});

test('gallery cached pages are explicitly partial and expire with existing offline authority', async () => {
  const app = fixture(); await login(app.engine); await app.engine.mediaGallery(room);
  app.engine.markDisconnected(); const start = app.calls.length;
  assert.equal((await app.engine.mediaGallery(room)).cached, true);
  await assert.rejects(app.engine.mediaGallery(room, { kind: 'image' }), { code: 'gallery_offline' });
  assert.equal(app.calls.length, start);
  app.advance(24 * 60 * 60 * 1000 + 1);
  await assert.rejects(app.engine.mediaGallery(room), { code: 'offline_expired' });
});

test('hidden own media stays hidden across hot, sparse and retained/archive association paths', async () => {
  const app = fixture(); await login(app.engine); await app.engine.latest(room);
  await app.engine.setMessageHidden(room, 20, true);
  assert.equal(await app.engine.mediaAssociation(room, 120), null);
  await assert.rejects(app.engine.setMessageHidden(room, 30, true), { status: 403 });
  app.page(page([item(20), item(8), item(5, 9)]));
  assert.deepEqual((await app.engine.mediaGallery(room)).items.map(row => row.id), [8, 5]);
  await app.engine.retainMediaAssociation(room, 108, true);
  // Load old canonical message into hot history only to apply existing owner-hide command.
  await app.archive.commitPage({ account: archiveAccount(app.engine), companyId: 1, roomId: 4, membershipId: 12 }, { beforeId: null, history: { api_version: 2, messages: [item(8)], next_before_id: null } }, () => {});
  // Persist hidden marker through existing account-scoped store, simulating prior authorized hide.
  const hiddenKey = [...app.storage.keys()].find(key => key.endsWith('/hidden-message-ids'))!;
  app.storage.set(hiddenKey, JSON.stringify([20, 8]));
  const restarted = fixture(app.archive, app.storage); await login(restarted.engine);
  assert.equal(await restarted.engine.mediaAssociation(room, 108), null);
  assert.equal((await restarted.engine.mediaAssociation(room, 130))?.author_user_id ?? 9, 9);
});

test('retained canonical media survives engine restart without creating history coverage and unpin removes only retention', async () => {
  const app = fixture(); await login(app.engine); await app.engine.mediaGallery(room);
  const scope = { account: archiveAccount(app.engine), companyId: 1, roomId: 4, membershipId: 12 };
  await app.engine.retainMediaAssociation(room, 108, true);
  assert.deepEqual((await app.archive.read(scope, { direction: 'latest', limit: 30, maxBytes: 128 * 1024 }, () => {})).messages, []);
  const restarted = fixture(app.archive, app.storage); await login(restarted.engine);
  const start = restarted.calls.length;
  assert.equal((await restarted.engine.mediaAssociation(room, 108))?.id, 8);
  assert.equal(restarted.calls.length, start);
  await restarted.engine.retainMediaAssociation(room, 108, false);
  assert.equal(await restarted.engine.mediaAssociation(room, 108), null);
  await assert.rejects(restarted.engine.retainMediaAssociation(room, 9999, true), { code: 'media_unavailable' });
});

test('gallery revocation purges sparse and retained associations without granting administration visibility', async () => {
  for (const revoke of ['revoke', 'revokeMedia'] as const) {
    const app = fixture(); await login(app.engine); await app.engine.mediaGallery(room); await app.engine.retainMediaAssociation(room, 108, true);
    app[revoke](); await app.engine.refresh();
    await assert.rejects(app.engine.mediaAssociation(room, 108));
    await assert.rejects(app.engine.mediaGallery({ ...room, company_id: 2 }));
  }
});

test('gallery ignores late previous-account responses after logout and never records their associations', async () => {
  const app = fixture(); await login(app.engine);
  let release!: () => void, entered!: () => void;
  const seen = new Promise<void>(done => { entered = done; }), blocked = new Promise<void>(done => { release = done; });
  app.wait(async () => { entered(); await blocked; });
  const pending = app.engine.mediaGallery(room); await seen;
  await app.engine.logout(); release(); await assert.rejects(pending);
  assert.equal(app.engine.identity, null);
});

test('keep fails explicitly when canonical persistence is unavailable or fails', async () => {
  const archive = new MemoryHistoryArchive(); archive.retainMediaAssociation = async () => { throw new Error('synthetic disk failure'); };
  const app = fixture(archive); await login(app.engine); await app.engine.mediaGallery(room);
  await assert.rejects(app.engine.retainMediaAssociation(room, 108, true), /synthetic disk failure/);
  assert.equal(await app.archive.findMedia({ account: archiveAccount(app.engine), companyId: 1, roomId: 4, membershipId: 12 }, 108, () => {}), null);
});

test('fresh gallery refusal purges the exact membership and retained metadata without exposing cached fallback', async () => {
  const app = fixture(); await login(app.engine); await app.engine.mediaGallery(room); await app.engine.retainMediaAssociation(room, 108, true);
  app.wait(async () => { throw new ChatError('membership_changed', 403); });
  await assert.rejects(app.engine.mediaGallery(room), { status: 403 });
  assert.deepEqual(app.engine.rooms(), []);
  const scope = { account: archiveAccount(app.engine), companyId: 1, roomId: 4, membershipId: 12 };
  assert.equal(await app.archive.findMedia(scope, 108, () => {}), null);
  app.engine.markDisconnected(); await assert.rejects(app.engine.mediaGallery(room), { code: 'room_unavailable' });
});

test('queued owner hide is rechecked after an archive association lookup rather than using an old hidden snapshot', async () => {
  const app = fixture(); await login(app.engine); await app.engine.mediaGallery(room); await app.engine.retainMediaAssociation(room, 108, true);
  const restarted = fixture(app.archive, app.storage); await login(restarted.engine);
  // A text-only hot copy can legitimately coexist with a retained canonical media association.
  const { media: _media, ...text } = item(8); restarted.history([text]); await restarted.engine.latest(room);
  const original = restarted.engine.hiddenMessages.bind(restarted.engine); let hide: Promise<number[]> | undefined;
  restarted.engine.hiddenMessages = async value => {
    const snapshot = await original(value);
    hide = restarted.engine.setMessageHidden(room, 8, true); // queued before archive lookup
    return snapshot;
  };
  assert.equal(await restarted.engine.mediaAssociation(room, 108), null);
  await hide; assert.deepEqual(restarted.engine.cachedHiddenMessages(room), [8]);
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ChatEngine, ChatError, HISTORY_LIMITS } from '../core/ChatEngine.ts';
import type { Request, Storage, Room, Options, Attachment } from '../core/ChatEngine.ts';
import { MemoryHistoryArchive } from '../core/MemoryHistoryArchive.ts';
import { ARCHIVE_LIMITS } from '../core/HistoryArchive.ts';

class MemoryStorage implements Storage {
  data = new Map<string, string>();
  // Shared archive fixture models the separate durable DB across engine instances.
  archive = new MemoryHistoryArchive();
  async getItem(key: string) { return this.data.get(key) ?? null; }
  async setItem(key: string, value: string) { this.data.set(key, value); }
  async removeItem(key: string) { this.data.delete(key); }
  async getAllKeys() { return [...this.data.keys()]; }
}
const room: Room = { id: 11, company_id: 1, membership_id: 21, name: 'Private', is_group: true };
const UUID = 'e458127f-777e-414f-ad44-256b06df8910';
class Server {
  uid: number | null = 7; companyIds = [1]; rooms: Room[] = [room];
  offline = false; lostResponse = false; revoked = false; csrf = 'ephemeral';
  sendRight = true; mediaRight = true; viewRight = true; closed = 0; authenticateUid: number | null = 7;
  groupLostResponse = false; groupIds = new Map<string, number>();
  receiptUnavailable = false; receiptWrongAck = false;
  calls: Request[] = []; messages: any[] = []; dedup = new Map<string, number>();
  before?: (r: Request) => Promise<void>;
  async request(r: Request): Promise<unknown> {
    this.calls.push(r); if (this.before) await this.before(r);
    if (this.offline) throw new ChatError('connection_failed');
    if (r.path === '/web/session/destroy') { this.closed++; return { jsonrpc: '2.0', result: null }; }
    if (r.path === '/web/session/authenticate') return { jsonrpc: '2.0', result: { uid: this.authenticateUid, db: 'trial' } };
    if (this.revoked) throw new ChatError('forbidden', 403);
    if (r.path === '/bchat/api/v2/bootstrap') return { api_version: 2, user_id: this.uid, database: 'trial', company_ids: this.companyIds, csrf_token: this.csrf, permissions: { chat_view: this.viewRight, chat_send: this.sendRight, media: this.mediaRight, group_create: true, revision: 1 } };
    if (r.path === '/bchat/api/v2/rooms' && r.method === 'GET') return { api_version: 2, rooms: this.rooms };
    if (r.path === '/bchat/api/v2/rooms' && r.method === 'POST') {
      const p = JSON.parse(r.form!.payload!);
      const replayed = this.groupIds.has(p.client_uuid);
      if (!replayed) this.groupIds.set(p.client_uuid, this.groupIds.size + 100);
      if (this.groupLostResponse) { this.groupLostResponse = false; throw new ChatError('connection_failed'); }
      return { api_version: 2, room_id: this.groupIds.get(p.client_uuid), membership_id: 200, replayed };
    }
    if (r.path.startsWith('/bchat/api/v2/changes')) return { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
    const receiptRoute = /^\/bchat\/api\/v2\/rooms\/11\/messages\/(\d+)\/receipts$/.exec(r.path);
    if (receiptRoute && r.method === 'POST') {
      assert.deepEqual(Object.keys(r.form!).sort(), ['csrf_token', 'kind']); assert.equal(r.form!.csrf_token, this.csrf);
      if (this.receiptUnavailable) throw new ChatError('receipt_unavailable', 409);
      const messageId = Number(receiptRoute[1]);
      return { api_version: 2, message_id: this.receiptWrongAck ? messageId + 1 : messageId, delivered_at: '2026-10-18 12:00:01',
        read_at: r.form!.kind === 'read' ? '2026-10-18 12:00:02' : null, unread_count: r.form!.kind === 'read' ? 0 : 1,
        last_message_id: Math.max(...this.messages.map(message => message.id)), replayed: false };
    }
    if (r.path === '/bchat/api/v2/rooms/11/messages' && r.method === 'POST') {
      const p = JSON.parse(r.form!.payload!);
      assert.equal(r.form!.csrf_token, this.csrf);
      if (!this.dedup.has(p.client_uuid)) {
        const messageId = this.messages.length + 1;
        this.dedup.set(p.client_uuid, messageId);
        this.messages.push({ id: messageId, text: p.text, author_user_id: 7, author_name: 'Alice', created_at: '2026-10-18 12:00:00' });
      }
      if (this.lostResponse) { this.lostResponse = false; throw new ChatError('connection_failed'); }
      return { api_version: 2, room_id: 11, membership_id: 21, client_uuid: p.client_uuid, message_id: this.dedup.get(p.client_uuid), state: 'sent', ...(p.media_id ? { media_id: p.media_id } : {}) };
    }
    if (r.path.startsWith('/bchat/api/v2/rooms/11/messages')) return { api_version: 2, messages: this.messages, next_before_id: null };
    throw new ChatError('unexpected_test_request');
  }
}
function setup(storage = new MemoryStorage(), server = new Server(), extra: Partial<Options> = {}) {
  let time = 1_000_000; let seq = 0;
  const engine = new ChatEngine({ storage, archive: storage.archive, transport: server, origin: 'https://odoo.example', database: 'trial', now: () => time, uuid: () => seq++ ? UUID.replace('e458127f', 'a458127f') : UUID, ...extra });
  return { engine, storage, server, tick: (ms: number) => { time += ms; } };
}
const login = async (engine: ChatEngine) => engine.login('alice', 'NeverPersistThis', true);

test('plain ChatEngine keeps chat_view mandatory even when a genuine bootstrap grants orders-only rights', async () => {
  class OrdersServer extends Server {
    override async request(request: Request): Promise<unknown> {
      if (request.path === '/bchat/api/v2/bootstrap') {
        this.calls.push(request);
        return { api_version: 2, database: 'trial', user_id: 7, company_ids: [1], csrf_token: 'ephemeral',
          permissions: { chat_view: false, chat_send: false, order_view: true, order_create: true, order_receive: true } };
      }
      return super.request(request);
    }
  }
  const server = new OrdersServer(); const { engine, storage } = setup(new MemoryStorage(), server);
  await assert.rejects(login(engine), { code: 'identity_mismatch' });
  assert.equal(engine.identity, null); assert.equal(await engine.restoreOffline(), false);
  assert.equal(server.calls.some(request => request.path.includes('/rooms')), false);
  assert.ok(![...storage.data.values()].some(value => value.includes('csrf_token')));
});

test('remembered history is a defensive no-network snapshot fenced by identity, rights, company, membership and offline lease', async () => {
  const { engine, server, tick } = setup();
  assert.throws(() => engine.rememberedHistory(room), { code: 'login_required' });
  await login(engine);
  const emptyCalls = server.calls.length;
  assert.equal(engine.rememberedHistory(room), null); assert.equal(server.calls.length, emptyCalls);
  server.messages = [{ id: 1, author_user_id: 7, author_name: 'Alice', text: '', created_at: '',
    media: { id: 70, kind: 'image', mime: 'image/png', name: 'private.png', size: 10, sha256: 'a'.repeat(64) } }];
  await engine.history(room); const before = server.calls.length;
  const first = engine.rememberedHistory(room)!; first.messages[0]!.media!.sha256 = 'b'.repeat(64); first.messages.length = 0;
  assert.equal(engine.rememberedHistory(room)!.messages[0]!.media!.sha256, 'a'.repeat(64));
  assert.throws(() => engine.rememberedHistory({ ...room, company_id: 2 }), { code: 'room_unavailable' });
  assert.throws(() => engine.rememberedHistory({ ...room, membership_id: 22 }), { code: 'room_unavailable' });
  assert.equal(server.calls.length, before);
  server.mediaRight = false; await engine.refresh();
  assert.throws(() => engine.rememberedHistory(room), { code: 'forbidden' });
  server.mediaRight = true; server.viewRight = false;
  await assert.rejects(engine.refresh(), { code: 'identity_mismatch' });
  assert.throws(() => engine.rememberedHistory(room), { code: 'login_required' });
  server.viewRight = true; await login(engine); await engine.history(room);
  engine.markDisconnected(); tick(24 * 60 * 60 * 1000 + 1);
  assert.throws(() => engine.rememberedHistory(room), { code: 'offline_expired' });
  assert.throws(() => engine.rememberedHistory(room), { code: 'offline_expired' });
});

test('login support stage preserves the original error code at each remote step', async () => {
  const stages = [
    ['/web/session/destroy', 'session_close'], ['/web/session/authenticate', 'authenticate'],
    ['/bchat/api/v2/bootstrap', 'bootstrap'], ['/bchat/api/v2/rooms', 'rooms'],
  ];
  for (const [path, loginStage] of stages) {
    const { engine, server } = setup();
    server.before = async request => { if (request.path === path) throw new ChatError('connection_failed'); };
    await assert.rejects(login(engine), { code: 'connection_failed', loginStage });
    assert.equal(engine.identity, null);
  }
});

test('individual login verifies uid/database and never stores password or CSRF', async () => {
  const { engine, storage, server } = setup();
  await login(engine); assert.equal(engine.identity?.user_id, 7); assert.equal(server.closed, 1);
  const stored = [...storage.data.values()].join();
  assert.ok(!stored.includes('NeverPersistThis')); assert.ok(!stored.includes(server.csrf));
  assert.ok(!stored.includes('csrf_token'));
});
test('MFA pending uid=null fails closed with no cached identity', async () => {
  const { engine, storage, server } = setup(); server.authenticateUid = null;
  await assert.rejects(login(engine), { code: 'mfa_required' });
  assert.equal(engine.identity, null); assert.ok([...storage.data.keys()].every(key => key.endsWith('/authentication-required')));
  assert.ok(!server.calls.some(r => r.path.includes('/bootstrap')));
});
test('bootstrap identity mismatch purges local state and closes session', async () => {
  const { engine, server, storage } = setup(); server.uid = 8;
  await assert.rejects(login(engine), { code: 'identity_mismatch' });
  assert.equal(engine.identity, null); assert.equal(storage.data.size, 0); assert.equal(server.closed, 2);
});
test('durable UUID recovers lost response and process restart without duplicate', async () => {
  const { engine, server, storage, tick } = setup(); await login(engine);
  await engine.enqueue(room, 'offline text'); server.lostResponse = true;
  await assert.rejects(engine.flush(), { code: 'connection_failed' });
  assert.equal(engine.pending()[0]!.state, 'unknown'); assert.equal(server.messages.length, 1);
  tick(6000);
  const restarted = setup(storage, server); restarted.tick(6000);
  assert.equal(await restarted.engine.restoreOffline(), true);
  assert.equal(restarted.engine.pending()[0]!.client_uuid, UUID);
  await restarted.engine.flush();
  assert.equal(server.messages.length, 1); assert.equal(restarted.engine.pending().length, 0);
});
test('sending durable item after crash becomes unknown with same UUID', async () => {
  const { engine, storage, server } = setup(); await login(engine); await engine.enqueue(room, 'saved');
  const key = [...storage.data.keys()].find(k => k.includes('/outbox/'))!;
  const saved = JSON.parse(storage.data.get(key)!); saved.state = 'sending'; storage.data.set(key, JSON.stringify(saved));
  const next = setup(storage, server); await next.engine.restoreOffline();
  assert.equal(next.engine.pending()[0]!.state, 'unknown'); assert.equal(next.engine.pending()[0]!.client_uuid, UUID);
});
test('offline reads survive restart and use scoped membership cache', async () => {
  const { engine, storage, server } = setup(); await login(engine);
  await engine.enqueue(room, 'visible'); await engine.flush(); await engine.history(room);
  server.offline = true; const next = setup(storage, server); assert.equal(await next.engine.restoreOffline(), true);
  assert.equal((await next.engine.history(room)).messages[0]!.text, 'visible');
  assert.equal([...storage.data.keys()].some(k => k.endsWith('/history')), false, 'history lives in archive, not AsyncStorage');
});
test('revoked membership deletes room cache/outbox before replay', async () => {
  const { engine, storage, server } = setup(); await login(engine); await engine.history(room); await engine.enqueue(room, 'do not send');
  server.rooms = []; await engine.flush();
  assert.deepEqual(engine.rooms(), []); assert.equal(engine.pending().length, 0); assert.equal(server.messages.length, 0);
  assert.ok(![...storage.data.keys()].some(k => k.includes('/r/11/')));
});
test('new membership period removes old content and queued UUID', async () => {
  const { engine, storage, server } = setup(); await login(engine); await engine.enqueue(room, 'old');
  server.rooms = [{ ...room, membership_id: 22 }]; await engine.refresh();
  assert.equal(engine.pending().length, 0); assert.ok(![...storage.data.keys()].some(k => k.includes('/m/21/')));
});
test('chat send right revoked removes outbox before any send', async () => {
  const { engine, server } = setup(); await login(engine); await engine.enqueue(room, 'not authorized');
  server.sendRight = false; await engine.flush();
  assert.equal(engine.pending().length, 0); assert.equal(server.messages.length, 0);
});
test('account revoked purges caches and does not transmit pending data', async () => {
  const { engine, storage, server } = setup(); await login(engine); await engine.enqueue(room, 'private');
  server.revoked = true; await assert.rejects(engine.flush(), { code: 'forbidden' });
  assert.equal(engine.identity, null); assert.equal(storage.data.size, 0); assert.equal(server.messages.length, 0);
});
test('late response after logout cannot repopulate identity or durable cache', async () => {
  const { engine, server, storage } = setup(); await login(engine);
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  server.before = async r => { if (r.path.includes('/messages')) await wait; };
  const request = engine.history(room);
  const outcome = assert.rejects(request, { code: 'stale_session' });
  await engine.logout(); release(); await outcome;
  assert.equal(engine.identity, null); assert.equal(storage.data.size, 0);
});
test('native cookie close failure blocks a new authentication attempt', async () => {
  const { engine, server } = setup(); server.offline = true;
  await assert.rejects(login(engine), { code: 'connection_failed' });
  assert.ok(!server.calls.some(r => r.path.endsWith('/authenticate')));
});
test('origin validation rejects plaintext and credential URLs', () => {
  for (const origin of ['http://odoo.example', 'https://user:secret@odoo.example', 'https://odoo.example/path']) {
    assert.throws(() => new ChatEngine({ origin, database: 'trial', storage: new MemoryStorage(), transport: new Server() }), { code: 'https_origin_required' });
  }
});
test('room IDs cannot bypass membership/company validation', async () => {
  const { engine } = setup(); await login(engine);
  await assert.rejects(engine.enqueue({ ...room, company_id: 2 }, 'wrong company'), { code: 'room_unavailable' });
  await assert.rejects(engine.history(999), { code: 'room_unavailable' });
});
test('offline lease expires reads but retains outbox for verified same-user login', async () => {
  const { engine, storage, server } = setup(); await login(engine); await engine.enqueue(room, 'unsent for tomorrow');
  const next = setup(storage, server); next.tick(24 * 60 * 60 * 1000 + 1);
  assert.equal(await next.engine.restoreOffline(), false); assert.equal(next.engine.status, 'offline_expired');
  assert.ok([...storage.data.keys()].some(k => k.includes('/outbox/')));
  await login(next.engine); assert.equal(next.engine.pending()[0]!.client_uuid, UUID);
  await next.engine.flush(); assert.equal(server.messages.length, 1);
});
test('switch account purges previous queues and never replays another uid', async () => {
  const { engine, server, storage } = setup(); await login(engine); await engine.enqueue(room, 'Alice private');
  server.uid = 8; server.authenticateUid = 8;
  await engine.login('bob', 'different', true); assert.equal(engine.identity?.user_id, 8);
  assert.equal(engine.pending().length, 0); assert.ok(![...storage.data.keys()].some(k => k.includes('/u/7/')));
  await engine.flush(); assert.equal(server.messages.length, 0);
});
test('ACK history read failure never recreates a confirmed outbox operation', async () => {
  const { engine, server } = setup(); await login(engine); await engine.enqueue(room, 'ack is sufficient');
  const request = server.request.bind(server);
  server.request = async r => {
    if (r.method === 'GET' && r.path.includes('/messages')) throw new ChatError('connection_failed');
    return request(r);
  };
  await engine.flush(); assert.equal(engine.pending().length, 0); assert.equal(server.messages.length, 1);
});
test('delayed bootstrap cannot switch identity back after a newer login', async () => {
  const { engine, server } = setup(); await login(engine);
  let release!: () => void; const wait = new Promise<void>(resolve => { release = resolve; });
  let delayed = false;
  server.before = async r => { if (!delayed && r.path.endsWith('/bootstrap')) { delayed = true; await wait; } };
  const refreshing = engine.refresh(); const outcome = assert.rejects(refreshing, { code: 'stale_session' });
  server.uid = 8; server.authenticateUid = 8;
  await engine.login('bob', 'different', true); release(); await outcome;
  assert.equal(engine.identity?.user_id, 8);
});
test('a pending storage write cannot survive a simultaneous logout', async () => {
  const { engine, storage } = setup(); await login(engine);
  let release!: () => void; let started!: () => void;
  const writing = new Promise<void>(resolve => { started = resolve; });
  const blocked = new Promise<void>(resolve => { release = resolve; });
  const setItem = storage.setItem.bind(storage);
  storage.setItem = async (key, value) => { if (key.includes('/outbox/')) { started(); await blocked; } await setItem(key, value); };
  const enqueue = engine.enqueue(room, 'late local write');
  const outcome = assert.rejects(enqueue, { code: 'stale_session' });
  await writing; const logout = engine.logout(); release(); await logout; await outcome;
  assert.equal(storage.data.size, 0); assert.equal(engine.identity, null);
});
test('failed durable write prevents a network send and in-memory queued success', async () => {
  const { engine, storage, server } = setup(); await login(engine);
  const setItem = storage.setItem.bind(storage);
  storage.setItem = async (key, value) => { if (key.includes('/outbox/')) throw new Error('disk full'); await setItem(key, value); };
  await assert.rejects(engine.enqueue(room, 'do not transmit'));
  assert.equal(engine.pending().length, 0); assert.equal(server.messages.length, 0);
});
test('outbox is bounded at 100 durable operations', async () => {
  const storage = new MemoryStorage(); const server = new Server(); let sequence = 0;
  const engine = new ChatEngine({ storage, transport: server, origin: 'https://odoo.example', database: 'trial', uuid: () => `${(++sequence).toString(16).padStart(8, '0')}-777e-414f-ad44-256b06df8910` });
  await login(engine);
  for (let i = 0; i < 100; i++) await engine.enqueue(room, `pending ${i}`);
  await assert.rejects(engine.enqueue(room, 'overflow'), { code: 'outbox_full' });
  assert.equal(engine.pending().length, 100);
});
test('group creation retry after response loss keeps its durable UUID across restart', async () => {
  const { engine, storage, server } = setup(); await login(engine); server.groupLostResponse = true;
  await assert.rejects(engine.createGroup(1, 'Sales', [8, 9]), { code: 'connection_failed' });
  const next = setup(storage, server); await next.engine.restoreOffline();
  const result = await next.engine.createGroup(1, 'Sales', [9, 8]);
  assert.equal(result.replayed, true); assert.equal(server.groupIds.size, 1);
  assert.ok(![...storage.data.keys()].some(k => k.includes('/operations/')));
});
const file = (extra: Partial<Attachment> = {}): Attachment => ({ uri: 'file:///app/odoo-stage/report.pdf', name: 'report.pdf', mime: 'application/pdf', size: 1000, sha256: 'a'.repeat(64), kind: 'file', upload_uuid: UUID.replace('e458127f', 'b458127f'), ...extra });
test('attachment is durable before upload; message replay reuses persisted media result', async () => {
  const storage = new MemoryStorage(); const server = new Server(); let uploads = 0; const removed: string[] = [];
  const upload: Options['upload'] = async (_room, attachment, csrf) => {
    uploads++; assert.equal(csrf, server.csrf); assert.equal(attachment.upload_uuid, file().upload_uuid);
    assert.ok([...storage.data.values()].some(value => value.includes(attachment.upload_uuid)));
    return { media_id: 70, policy_version: 3 };
  };
  const removeAttachment: Options['removeAttachment'] = async attachment => { removed.push(attachment.uri); };
  const first = setup(storage, server, { upload, removeAttachment }); await login(first.engine);
  await first.engine.enqueueAttachment(room, file(), '', 4); server.lostResponse = true;
  await assert.rejects(first.engine.flush(), { code: 'connection_failed' });
  assert.equal(uploads, 1); assert.equal(removed.length, 0); assert.equal(first.engine.pending()[0]!.attachment!.media_id, 70);
  const next = setup(storage, server, { upload, removeAttachment }); next.tick(6000); await next.engine.restoreOffline();
  await next.engine.flush(); assert.equal(uploads, 1); assert.equal(server.messages.length, 1); assert.equal(removed.length, 1);
  const payload = JSON.parse(server.calls.find(r => r.method === 'POST' && r.path.endsWith('/messages'))!.form!.payload!);
  assert.equal(payload.media_id, 70); assert.equal(payload.document_type, 'other'); assert.equal(payload.policy_version, 3); assert.equal(payload.reply_to_message_id, 4);
});
test('uncertain upload survives restart and reconciles the same upload UUID', async () => {
  const storage = new MemoryStorage(); const server = new Server(); let uploadCalls = 0; const remote = new Map<string, number>();
  const upload: Options['upload'] = async (_room, a) => {
    uploadCalls++; remote.set(a.upload_uuid, 80);
    if (uploadCalls === 1) throw new ChatError('connection_failed');
    return { media_id: remote.get(a.upload_uuid)! };
  };
  const first = setup(storage, server, { upload }); await login(first.engine); await first.engine.enqueueAttachment(room, file());
  await assert.rejects(first.engine.flush(), { code: 'connection_failed' });
  const next = setup(storage, server, { upload }); next.tick(6000); await next.engine.restoreOffline(); await next.engine.flush();
  assert.equal(remote.size, 1); assert.equal(uploadCalls, 2); assert.equal(server.messages.length, 1);
});
test('media permission revocation drops staged bytes before upload/message replay', async () => {
  const removed: string[] = []; let uploaded = false;
  const { engine, server } = setup(undefined, undefined, { upload: async () => { uploaded = true; return { media_id: 1 }; }, removeAttachment: async a => { removed.push(a.uri); } });
  await login(engine); await engine.enqueueAttachment(room, file()); server.mediaRight = false; await engine.flush();
  assert.equal(uploaded, false); assert.equal(server.messages.length, 0); assert.equal(engine.pending().length, 0); assert.equal(removed.length, 1);
});
test('logout deletes staged attachments, same-user login recovery preserves them', async () => {
  const removed: string[] = []; const { engine } = setup(undefined, undefined, { upload: async () => ({ media_id: 1 }), removeAttachment: async a => { removed.push(a.uri); } });
  await login(engine); await engine.enqueueAttachment(room, file()); await login(engine);
  assert.equal(removed.length, 0); assert.equal(engine.pending().length, 1);
  await engine.logout(); assert.equal(removed.length, 1);
});
test('failed ACK persistence keeps staged file and durable media_id for retry', async () => {
  let removed = false; const { engine, storage } = setup(undefined, undefined, { upload: async () => ({ media_id: 91 }), removeAttachment: async () => { removed = true; } });
  await login(engine); await engine.enqueueAttachment(room, file());
  const setItem = storage.setItem.bind(storage);
  storage.setItem = async (key, value) => { if (key.includes('/ack/')) throw new Error('disk full'); await setItem(key, value); };
  await assert.rejects(engine.flush()); assert.equal(removed, false); assert.equal(engine.pending()[0]!.attachment!.media_id, 91);
  assert.ok([...storage.data.values()].some(value => value.includes('"media_id":91')));
});
test('invalid attachment metadata and MIME limits reject before queue or send', async () => {
  const { engine, server } = setup(undefined, undefined, { upload: async () => ({ media_id: 1 }) }); await login(engine);
  for (const invalid of [file({ size: 10 * 1024 * 1024 + 1 }), file({ sha256: 'bad' }), file({ uri: 'content://temporary' }), file({ mime: 'application/zip' }), file({ name: '../report.pdf' }), file({ upload_uuid: 'bad' }), file({ kind: 'image', mime: 'image/png', size: 5 * 1024 * 1024 + 1 })]) {
    await assert.rejects(engine.enqueueAttachment(room, invalid), { code: 'invalid_attachment' });
  }
  assert.equal(engine.pending().length, 0); assert.equal(server.messages.length, 0);
});
test('staged attachment aggregate cap is 50 MiB without network sends', async () => {
  const storage = new MemoryStorage(); const server = new Server(); let sequence = 0;
  const { engine } = setup(storage, server, { upload: async () => ({ media_id: 1 }), uuid: () => `${(++sequence).toString(16).padStart(8, '0')}-777e-414f-ad44-256b06df8910` }); await login(engine);
  for (let i = 1; i <= 5; i++) await engine.enqueueAttachment(room, file({ uri: `file:///app/stage/${i}.pdf`, size: 10 * 1024 * 1024, upload_uuid: `${i.toString(16).padStart(8, '0')}-777e-414f-ad44-256b06df8910` }));
  await assert.rejects(engine.enqueueAttachment(room, file({ uri: 'file:///app/stage/overflow.pdf' })), { code: 'attachment_quota' });
  assert.equal(engine.pending().length, 5); assert.equal(server.messages.length, 0);
});
test('late upload result after logout cannot send or recreate attachment state', async () => {
  let release!: () => void; let started!: () => void; let removed = false;
  const waiting = new Promise<void>(resolve => { release = resolve; }); const uploading = new Promise<void>(resolve => { started = resolve; });
  const { engine, storage, server } = setup(undefined, undefined, { upload: async () => { started(); await waiting; return { media_id: 101 }; }, removeAttachment: async () => { removed = true; } });
  await login(engine); await engine.enqueueAttachment(room, file());
  const sending = engine.flush(); const outcome = assert.rejects(sending, { code: 'stale_session' });
  await uploading; await engine.logout(); release(); await outcome;
  assert.equal(removed, true); assert.equal(storage.data.size, 0); assert.equal(server.messages.length, 0);
});
test('durable ACK after interrupted cleanup recovers stage without retransmitting', async () => {
  const storage = new MemoryStorage(); const server = new Server(); let removed = 0;
  const options = { upload: async () => ({ media_id: 110 }), removeAttachment: async () => { removed++; } };
  const first = setup(storage, server, options); await login(first.engine); await first.engine.enqueueAttachment(room, file());
  const removeItem = storage.removeItem.bind(storage); let failed = false;
  storage.removeItem = async key => { if (!failed && key.includes('/outbox/')) { failed = true; throw new Error('process stops at removal'); } await removeItem(key); };
  await assert.rejects(first.engine.flush()); assert.equal(removed, 0); assert.equal(server.messages.length, 1);
  const next = setup(storage, server, options); await next.engine.restoreOffline();
  assert.equal(next.engine.pending().length, 0); assert.equal(removed, 1);
  await next.engine.flush(); assert.equal(server.messages.length, 1);
});
test('R1 company revocation is applied even when subsequent rooms request fails', async () => {
  const { engine, server, storage } = setup(); await login(engine); await engine.history(room); await engine.enqueue(room, 'revoked scope');
  server.companyIds = [2]; server.before = async r => { if (r.path === '/bchat/api/v2/rooms') throw new ChatError('connection_failed'); };
  await assert.rejects(engine.refresh(), { code: 'connection_failed' });
  assert.deepEqual(engine.rooms(), []); assert.equal(engine.pending().length, 0);
  await assert.rejects(engine.history(room), { code: 'room_unavailable' });
  assert.ok(![...storage.data.keys()].some(k => k.includes('/c/1/')));
});
test('R1 incomplete scope refresh cannot renew the offline lease', async () => {
  const { engine, server, tick } = setup(); await login(engine); await engine.history(room);
  tick(24 * 60 * 60 * 1000 - 1);
  server.before = async r => { if (r.path === '/bchat/api/v2/rooms') throw new ChatError('connection_failed'); };
  await assert.rejects(engine.refresh(), { code: 'connection_failed' }); tick(2);
  assert.throws(() => engine.rooms(), { code: 'offline_expired' });
});
test('R1 media revocation removes pending stages even if following rooms request is unavailable', async () => {
  let removed = 0; const { engine, server } = setup(undefined, undefined, { upload: async () => ({ media_id: 1 }), removeAttachment: async () => { removed++; } });
  await login(engine); await engine.enqueueAttachment(room, file()); server.mediaRight = false;
  server.before = async r => { if (r.path === '/bchat/api/v2/rooms') throw new ChatError('connection_failed'); };
  await assert.rejects(engine.refresh(), { code: 'connection_failed' });
  assert.equal(engine.pending().length, 0); assert.equal(removed, 1); assert.equal(server.messages.length, 0);
});
test('R2 transient login failure locks but preserves durable same-user pending attachments', async () => {
  const storage = new MemoryStorage(); const server = new Server(); let removed = 0;
  const options = { upload: async () => ({ media_id: 120 }), removeAttachment: async () => { removed++; } };
  const first = setup(storage, server, options); await login(first.engine); await first.engine.enqueueAttachment(room, file());
  server.offline = true; await assert.rejects(login(first.engine), { code: 'connection_failed' });
  assert.equal(first.engine.identity, null); assert.ok([...storage.data.keys()].some(k => k.includes('/outbox/'))); assert.equal(removed, 0);
  const next = setup(storage, server, options); assert.equal(await next.engine.restoreOffline(), false);
  server.offline = false; await login(next.engine); assert.equal(next.engine.pending()[0]!.client_uuid, UUID);
  await next.engine.flush(); assert.equal(server.messages.length, 1); assert.equal(removed, 1);
});
test('R2 MFA and wrong-password retries preserve locked outbox without offline restoration', async () => {
  for (const failure of ['mfa', 'password']) {
    const { engine, storage, server } = setup(); await login(engine); await engine.enqueue(room, 'keep my unsent text');
    if (failure === 'mfa') server.authenticateUid = null;
    else server.before = async r => { if (r.path.endsWith('/authenticate')) throw new ChatError('authentication_failed', 401); };
    await assert.rejects(login(engine), { code: failure === 'mfa' ? 'mfa_required' : 'authentication_failed' });
    assert.ok([...storage.data.keys()].some(k => k.includes('/outbox/')));
    const next = setup(storage, server); assert.equal(await next.engine.restoreOffline(), false); assert.equal(next.engine.identity, null);
    server.authenticateUid = 7; server.before = undefined; await login(next.engine);
    assert.equal(next.engine.pending()[0]!.client_uuid, UUID);
  }
});
test('R2 locked recovery is purged on explicit logout or another verified user', async () => {
  for (const action of ['logout', 'switch']) {
    let removed = 0; const { engine, storage, server } = setup(undefined, undefined, { upload: async () => ({ media_id: 1 }), removeAttachment: async () => { removed++; } });
    await login(engine); await engine.enqueueAttachment(room, file()); server.offline = true;
    await assert.rejects(login(engine)); server.offline = false;
    if (action === 'logout') await engine.logout();
    else { server.uid = 8; server.authenticateUid = 8; await engine.login('bob', 'private', true); assert.equal(engine.pending().length, 0); }
    assert.ok(![...storage.data.keys()].some(key => key.includes('/u/7/'))); assert.equal(removed, 1);
  }
});
test('R2 unremembered account preserves durable operations but never enables offline identity', async () => {
  const { engine, storage, server } = setup(); await engine.login('alice', 'private', false); await engine.enqueue(room, 'unremembered but durable');
  const next = setup(storage, server); assert.equal(await next.engine.restoreOffline(), false); assert.equal(next.engine.identity, null);
  await next.engine.login('alice', 'private', false); assert.equal(next.engine.pending()[0]!.client_uuid, UUID);
  await next.engine.flush(); assert.equal(server.messages.length, 1);
});
test('R4 exact expired-session destroy permits first login and logout without a cookie', async () => {
  const { engine, server } = setup();
  server.before = async r => { if (r.path.endsWith('/destroy')) throw new ChatError('session_expired', 401); };
  await login(engine); assert.equal(engine.identity?.user_id, 7); await engine.logout(); assert.equal(engine.identity, null);
});
test('R4 other 401/403 destroy failures never bypass session-close preflight', async () => {
  for (const failure of [new ChatError('authentication_failed', 401), new ChatError('forbidden', 403), new ChatError('session_expired', 403)]) {
    const { engine, server } = setup(); server.before = async r => { if (r.path.endsWith('/destroy')) throw failure; };
    await assert.rejects(login(engine)); assert.ok(!server.calls.some(r => r.path.endsWith('/authenticate')));
  }
});
test('R5 rate limiting backs off queued UUID and retries automatically', async () => {
  const { engine, server, tick } = setup(); await login(engine); await engine.enqueue(room, 'later');
  server.before = async r => { if (r.method === 'POST' && r.path.endsWith('/messages')) throw new ChatError('rate_limited', 429); };
  await assert.rejects(engine.flush(), { status: 429 }); assert.notEqual(engine.pending()[0]!.state, 'failed');
  assert.equal(engine.pending()[0]!.client_uuid, UUID); tick(6000); server.before = undefined; await engine.flush();
  assert.equal(engine.pending().length, 0); assert.equal(server.messages.length, 1);
});
const incoming = (messageId = 10) => ({ id: messageId, author_user_id: 8, author_name: 'Bob', text: 'Visible text', created_at: '2026-10-18 12:00:00' });
test('R6 receipts require loaded scoped incoming messages and exact form, dedup concurrent ACKs', async () => {
  const { engine, server } = setup(); server.rooms = [{ ...room, unread_count: 1, last_message_id: 10 }]; server.messages = [incoming()];
  await login(engine); await assert.rejects(engine.acknowledge(room, 10, 'read'), { code: 'message_unavailable' });
  await engine.history(room);
  const [a, b] = await Promise.all([engine.acknowledge(room, 10, 'read'), engine.acknowledge(room, 10, 'read')]);
  assert.equal(a?.message_id, 10); assert.deepEqual(a, b); assert.equal(engine.rooms()[0]!.unread_count, 0);
  await engine.acknowledge(room, 10, 'delivered');
  assert.equal(server.calls.filter(call => call.path.endsWith('/receipts')).length, 1);
  await assert.rejects(engine.acknowledge({ ...room, membership_id: 999 }, 10, 'read'), { code: 'room_unavailable' });
});
test('R6 offline/own messages never emit receipts or optimistic unread changes', async () => {
  const { engine, server } = setup(); server.rooms = [{ ...room, unread_count: 1, last_message_id: 10 }];
  server.messages = [incoming(), { ...incoming(11), author_user_id: 7 }]; await login(engine); await engine.history(room);
  assert.equal(await engine.acknowledge(room, 11, 'read'), null);
  engine.markDisconnected(); assert.equal(await engine.acknowledge(room, 10, 'read'), null);
  assert.equal(engine.rooms()[0]!.unread_count, 1); assert.equal(server.calls.filter(call => call.path.endsWith('/receipts')).length, 0);
});
test('R6 receipt_unavailable409 skips old messages while temporary failures retry without fake ACK', async () => {
  const first = setup(); first.server.messages = [incoming()]; first.server.receiptUnavailable = true; await login(first.engine); await first.engine.history(room);
  assert.equal(await first.engine.acknowledge(room, 10, 'read'), null); assert.equal(await first.engine.acknowledge(room, 10, 'read'), null);
  assert.equal(first.server.calls.filter(call => call.path.endsWith('/receipts')).length, 1);
  const { engine, server } = setup(); server.rooms = [{ ...room, unread_count: 1, last_message_id: 10 }]; server.messages = [incoming()];
  await login(engine); await engine.history(room);
  server.before = async r => { if (r.path.endsWith('/receipts')) throw new ChatError('connection_failed'); };
  await assert.rejects(engine.acknowledge(room, 10, 'read')); assert.equal(engine.rooms()[0]!.unread_count, 1);
  server.before = undefined; const ack = await engine.acknowledge(room, 10, 'read'); assert.equal(ack?.message_id, 10);
  assert.equal(server.calls.filter(call => call.path.endsWith('/receipts')).length, 2);
});
test('R6 mismatched and late receipt ACKs cannot update unread or another session', async () => {
  const { engine, server } = setup(); server.rooms = [{ ...room, unread_count: 1, last_message_id: 10 }]; server.messages = [incoming()];
  await login(engine); await engine.history(room); server.receiptWrongAck = true;
  await assert.rejects(engine.acknowledge(room, 10, 'read'), { code: 'invalid_receipt_ack' }); assert.equal(engine.rooms()[0]!.unread_count, 1);
  server.receiptWrongAck = false; let release!: () => void; let started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }); const waiting = new Promise<void>(resolve => { started = resolve; });
  server.before = async r => { if (r.path.endsWith('/receipts')) { started(); await wait; } };
  const ack = engine.acknowledge(room, 10, 'read'); const outcome = assert.rejects(ack, { code: 'stale_session' });
  await waiting; await engine.logout(); release(); await outcome; assert.equal(engine.identity, null);
});
test('R6 old-membership receipt cannot mutate or remove a newly joined membership', async () => {
  const { engine, server } = setup(); server.rooms = [{ ...room, unread_count: 1, last_message_id: 10 }]; server.messages = [incoming()];
  await login(engine); await engine.history(room);
  let release!: () => void; let started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }); const waiting = new Promise<void>(resolve => { started = resolve; });
  server.before = async r => { if (r.path.endsWith('/receipts')) { started(); await wait; } };
  const ack = engine.acknowledge(room, 10, 'read'); const outcome = assert.rejects(ack, { code: 'room_unavailable' });
  await waiting; server.rooms = [{ ...room, membership_id: 22, unread_count: 3, last_message_id: 10 }];
  await engine.refresh(); release(); await outcome;
  assert.equal(engine.rooms()[0]!.membership_id, 22); assert.equal(engine.rooms()[0]!.unread_count, 3);
});
function syntheticHistoryServer(count: number, perRoom: number, text: string) {
  const server = new Server(); const roomRows = Array.from({ length: count }, (_, index) => ({ ...room, id: 11 + index, membership_id: 21 + index }));
  server.rooms = roomRows;
  const request = server.request.bind(server);
  server.request = async r => {
    const match = /^\/bchat\/api\/v2\/rooms\/(\d+)\/messages$/.exec(r.path);
    if (match && r.method === 'GET') return { api_version: 2, messages: Array.from({ length: perRoom }, (_, index) => ({ ...incoming(index + 1), text })), next_before_id: null };
    return request(r);
  };
  return { server, roomRows };
}
const storedHistories = (storage: MemoryStorage) => [...storage.data.entries()].filter(([key]) => key.endsWith('/history'));
const historyBytes = (storage: MemoryStorage) => storedHistories(storage).reduce((total, [, json]) => total + new TextEncoder().encode(json).length, 0);
test('history room/account UTF8 byte quotas trim valid JSON and evict only least-recent histories', async () => {
  const { server, roomRows } = syntheticHistoryServer(6, 40, 'ع'.repeat(7000));
  const { engine, storage } = setup(undefined, server); await login(engine);
  await engine.enqueue(roomRows[0]!, 'pending must survive cache eviction');
  for (let index = 0; index < 3; index++) await engine.history(roomRows[index]!);
  await engine.history(roomRows[0]!); // Touch room zero, making room one the oldest.
  for (let index = 3; index < 6; index++) await engine.history(roomRows[index]!);
  await engine.history(roomRows[0]!); // Archive whole-scope quota differs from legacy fitted-JSON quota.
  for (const [, json] of storedHistories(storage)) {
    assert.ok(new TextEncoder().encode(json).length <= HISTORY_LIMITS.roomBytes);
    assert.ok(JSON.parse(json).messages.length <= HISTORY_LIMITS.roomMessages);
  }
  assert.ok(historyBytes(storage) <= HISTORY_LIMITS.accountBytes);
  assert.equal(engine.pending().length, 1);
  assert.ok([...storage.data.keys()].some(key => key.includes('/outbox/')));
  engine.markDisconnected();
  assert.ok((await engine.history(roomRows[0]!)).messages.length > 0, 'recently touched room survives');
  assert.equal((await engine.history(roomRows[1]!)).messages.length, 0, 'least recently used history was evicted');
  let messages = 0;
  for (const scopedRoom of roomRows) messages += (await engine.history(scopedRoom)).messages.length;
  assert.ok(messages <= HISTORY_LIMITS.accountMessages);
});
test('bounded180 hot windows obey account cap and separate archive survives restart without rewriting outbox', async () => {
  const { server, roomRows } = syntheticHistoryServer(12, 180, 'small');
  const { engine, storage } = setup(undefined, server); await login(engine); await engine.enqueue(roomRows[0]!, 'durable');
  for (const scopedRoom of roomRows) await engine.history(scopedRoom);
  engine.markDisconnected(); let messages = 0;
  for (const scopedRoom of roomRows) messages += (await engine.history(scopedRoom)).messages.length;
  assert.ok(messages <= HISTORY_LIMITS.accountMessages); assert.ok(messages >= ARCHIVE_LIMITS.windowMessages); assert.equal(storedHistories(storage).length, 0);
  const next = setup(storage, server); assert.equal(await next.engine.restoreOffline(), true);
  let restored = 0;
  for (const scopedRoom of roomRows) restored += (await next.engine.history(scopedRoom)).messages.length;
  assert.ok(restored <= HISTORY_LIMITS.accountMessages); assert.ok(restored >= ARCHIVE_LIMITS.windowMessages); assert.equal(next.engine.pending()[0]!.client_uuid, UUID);
  assert.ok(storedHistories(storage).every(([, json]) => new TextEncoder().encode(json).length <= HISTORY_LIMITS.roomBytes));
});
test('restore trims legacy oversized history keys without deleting pending operations', async () => {
  const { server, roomRows } = syntheticHistoryServer(6, 1, 'tiny'); const { engine, storage } = setup(undefined, server);
  await login(engine); await engine.enqueue(roomRows[0]!, 'do not discard');
  for (const scopedRoom of roomRows) await engine.history(scopedRoom);
  const identityKey = [...storage.data.keys()].find(key => key.endsWith('/identity'))!;
  const prefix = identityKey.slice(0, -'identity'.length) + 'u/7/';
  for (const scopedRoom of roomRows) storage.data.set(`${prefix}c/1/r/${scopedRoom.id}/m/${scopedRoom.membership_id}/history`, JSON.stringify({ api_version: 2, messages: Array.from({ length: 500 }, (_, index) => ({ ...incoming(index + 1), text: '😀'.repeat(4000) })), next_before_id: null }));
  const next = setup(storage, server); assert.equal(await next.engine.restoreOffline(), true);
  assert.equal(next.engine.pending()[0]!.client_uuid, UUID); assert.ok(historyBytes(storage) <= HISTORY_LIMITS.accountBytes);
  for (const [, json] of storedHistories(storage)) { assert.ok(new TextEncoder().encode(json).length <= HISTORY_LIMITS.roomBytes); assert.ok(Array.isArray(JSON.parse(json).messages)); }
  let messages = 0; for (const scopedRoom of roomRows) messages += (await next.engine.history(scopedRoom)).messages.length;
  assert.ok(messages <= HISTORY_LIMITS.accountMessages);
});
test('CursorWindow-unreadable legacy history evicts only cache and preserves durable outbox', async () => {
  const { engine, storage, server } = setup(); await login(engine); await engine.enqueue(room, 'durable through cache failure'); await engine.history(room);
  const getItem = storage.getItem.bind(storage);
  storage.getItem = async key => { if (key.endsWith('/history')) throw new Error('Row too big to fit into CursorWindow'); return getItem(key); };
  const next = setup(storage, server); assert.equal(await next.engine.restoreOffline(), true);
  assert.equal(next.engine.pending()[0]!.client_uuid, UUID); assert.equal(storedHistories(storage).length, 0);
});

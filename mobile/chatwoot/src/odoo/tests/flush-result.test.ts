import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ChatEngine, ChatError } from '../core/ChatEngine.ts';
import type { FlushResult, Message, Request, Room, Storage } from '../core/ChatEngine.ts';

const room: Room = { id: 11, company_id: 1, membership_id: 21, name: 'Synthetic room', is_group: true };
const other: Room = { id: 12, company_id: 2, membership_id: 22, name: 'Other synthetic room', is_group: true };
class Memory implements Storage {
  data = new Map<string, string>();
  async getItem(key: string) { return this.data.get(key) ?? null; }
  async setItem(key: string, value: string) { this.data.set(key, value); }
  async removeItem(key: string) { this.data.delete(key); }
  async getAllKeys() { return [...this.data.keys()]; }
}
class Server {
  calls: Request[] = []; rooms: Room[] = [room, other]; companies = [1, 2];
  media = true; view = true; badAck = false; failHistory = false;
  messages = new Map<number, Message[]>(); before?: (request: Request) => Promise<void>;
  async request(request: Request): Promise<unknown> {
    this.calls.push(request); await this.before?.(request);
    if (request.path === '/web/session/destroy') return { result: null };
    if (request.path === '/web/session/authenticate') return { result: { uid: 7, db: 'trial' } };
    if (request.path.endsWith('/bootstrap')) return { api_version: 2, user_id: 7, database: 'trial', company_ids: this.companies,
      csrf_token: 'synthetic', permissions: { chat_view: this.view, chat_send: true, media: this.media } };
    if (request.path === '/bchat/api/v2/rooms') return { api_version: 2, rooms: this.rooms };
    if (request.path.startsWith('/bchat/api/v2/changes')) return { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
    const match = /^\/bchat\/api\/v2\/rooms\/(\d+)\/messages(?:\?.*)?$/.exec(request.path);
    if (!match) throw new Error('Unexpected synthetic route');
    const id = Number(match[1]), selected = this.rooms.find(value => value.id === id)!;
    if (request.method === 'POST') {
      const payload = JSON.parse(request.form!.payload!);
      const messages = this.messages.get(id) ?? [], messageId = messages.length + 1;
      messages.push({ id: messageId, author_user_id: 7, author_name: 'Synthetic', text: payload.text, created_at: '2026-10-20 10:00:00' });
      this.messages.set(id, messages);
      return { api_version: 2, room_id: id, membership_id: selected.membership_id, client_uuid: payload.client_uuid,
        message_id: messageId, state: this.badAck ? 'unknown' : 'sent' };
    }
    if (this.failHistory) throw new ChatError('request_failed', 503);
    return { api_version: 2, messages: this.messages.get(id) ?? [], next_before_id: null };
  }
}
async function fixture(media = true) {
  const server = new Server(); server.media = media;
  let time = 1000000, sequence = 0;
  const engine = new ChatEngine({ origin: 'https://synthetic.example', database: 'trial', storage: new Memory(), transport: server,
    now: () => time, uuid: () => `${(++sequence).toString(16).padStart(8, '0')}-777e-414f-ad44-256b06df8910` });
  await engine.login('synthetic', 'synthetic', true); server.calls = [];
  return { engine, server, tick: (ms: number) => { time += ms; } };
}
const histories = (server: Server) => server.calls.filter(value => value.method === 'GET' && value.path.includes('/messages'));
const sent = async (engine: ChatEngine, value = room): Promise<FlushResult> => {
  await engine.enqueue(value, 'canonical text'); return await engine.flush() as unknown as FlushResult;
};

test('flush exposes only its successful post-ACK canonical page without another HTTP or media permission', async () => {
  const { engine, server } = await fixture(false);
  const result = await sent(engine), before = server.calls.length, lease = engine.leaseRemainingMs;
  assert.equal(result.historyFor(room)!.messages[0]!.text, 'canonical text');
  assert.equal(result.historyFor(room.id)!.messages[0]!.text, 'canonical text');
  assert.equal(server.calls.length, before); assert.equal(engine.leaseRemainingMs, lease);
  assert.equal(histories(server).length, 1); assert.equal(engine.pending().length, 0);
});

test('concurrent flush callers share one settlement and the same guarded result', async () => {
  const { engine, server } = await fixture();
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }), seen = new Promise<void>(resolve => { started = resolve; });
  server.before = async request => { if (request.method === 'POST') { started(); await wait; } };
  await engine.enqueue(room, 'one'); const first = engine.flush(); await seen;
  const second = engine.flush(); release();
  const [a, b] = await Promise.all([first, second]) as unknown as [FlushResult, FlushResult];
  assert.equal(a, b); assert.equal(a.historyFor(room)!.messages.length, 1);
  assert.equal(server.calls.filter(value => value.method === 'POST').length, 1); assert.equal(histories(server).length, 1);
});

test('flush result uses defensive copies and retains only the last successful page per scoped room', async () => {
  const { engine } = await fixture();
  await engine.enqueue(room, 'first'); await engine.enqueue(room, 'second'); await engine.enqueue(other, 'other company');
  const result = await engine.flush() as unknown as FlushResult;
  const page = result.historyFor(room)!; page.messages[0]!.text = 'mutated'; page.messages.length = 0;
  assert.equal(result.historyFor(room)!.messages.length, 2);
  assert.equal(result.historyFor(room)!.messages[0]!.text, 'first');
  assert.equal(result.historyFor(other)!.messages[0]!.text, 'other company');
  assert.throws(() => result.historyFor({ ...room, company_id: 2 }), { code: 'room_unavailable' });
});

test('empty flush and failed post-ACK read never label an older cached page as a fresh result', async () => {
  const { engine, server } = await fixture();
  await engine.history(room);
  const empty = await engine.flush() as unknown as FlushResult; assert.equal(empty.historyFor(room), null);
  server.failHistory = true;
  const failedRead = await sent(engine); assert.equal(engine.pending().length, 0, 'successful ACK remains settled');
  assert.equal(failedRead.historyFor(room), null);
  server.failHistory = false;
  const before = histories(server).length;
  const fallback = failedRead.historyFor(room) ?? await engine.history(room);
  assert.equal(histories(server).length, before + 1); assert.equal(fallback.messages[0]!.text, 'canonical text');
});

test('failed ACK never exposes a flush result or a fabricated canonical page', async () => {
  const { engine, server } = await fixture(); server.badAck = true;
  await engine.enqueue(room, 'unsettled'); await assert.rejects(engine.flush(), { code: 'invalid_ack' });
  assert.equal(histories(server).length, 0); assert.equal(engine.pending().length, 1);
});

test('flush result refuses logout, new account incarnation, company/member withdrawal, chat denial and expired lease', async () => {
  for (const transition of ['logout', 'login', 'company', 'member', 'denied', 'expiry', 'rollback']) {
    const { engine, server, tick } = await fixture(); const result = await sent(engine);
    if (transition === 'logout') await engine.logout();
    if (transition === 'login') await engine.login('synthetic', 'synthetic', true);
    if (transition === 'company') { server.companies = [2]; server.rooms = [other]; await engine.refresh(); }
    if (transition === 'member') { server.rooms = [{ ...room, membership_id: 23 }, other]; await engine.refresh(); }
    if (transition === 'denied') { server.view = false; await assert.rejects(engine.refresh()); }
    if (transition === 'expiry' || transition === 'rollback') { engine.markDisconnected(); tick(transition === 'expiry' ? 86400001 : -1); }
    assert.throws(() => result.historyFor(room), ChatError, transition);
    if (transition === 'member') assert.throws(() => result.historyFor(room.id), ChatError, transition);
  }
});

test('flush result falls back after another canonical history replaces its internal snapshot', async () => {
  const { engine } = await fixture(); const result = await sent(engine);
  await engine.history(room); assert.equal(result.historyFor(room), null);
});

test('window navigation invalidates a flush page immediately before its new history request finishes', async () => {
  const { engine, server } = await fixture(); const result = await sent(engine);
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }), seen = new Promise<void>(resolve => { started = resolve; });
  server.before = async request => { if (request.path.includes('/messages')) { started(); await wait; } };
  const navigation = engine.latest(room); await seen;
  assert.equal(result.historyFor(room), null, 'window version changes before a replacement object exists');
  release(); await navigation;
});

test('navigation during post-ACK history cannot publish a late page for a newer window', async () => {
  const { engine, server } = await fixture();
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; }), seen = new Promise<void>(resolve => { started = resolve; });
  server.before = async request => {
    if (request.method === 'GET' && request.path.includes('/messages')) { server.before = undefined; started(); await wait; }
  };
  const flushing = sent(engine); await seen;
  await engine.latest(room); release();
  const result = await flushing; assert.equal(result.historyFor(room), null);
});

test('a failed later post-ACK read removes the earlier same-room flush page without recreating settled sends', async () => {
  const { engine, server } = await fixture();
  server.before = async request => {
    if (request.method === 'GET' && request.path.includes('/messages') && server.messages.get(room.id)?.length === 2)
      throw new ChatError('request_failed', 503);
  };
  await engine.enqueue(room, 'first'); await engine.enqueue(room, 'second');
  const result = await engine.flush();
  assert.equal(engine.pending().length, 0); assert.equal(server.messages.get(room.id)!.length, 2);
  assert.equal(result.historyFor(room), null, 'first message page must not masquerade as the last settled message page');
});

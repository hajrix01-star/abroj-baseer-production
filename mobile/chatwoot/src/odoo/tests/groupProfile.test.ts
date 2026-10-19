import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ChatEngine, ChatError, groupDescription } from '../core/ChatEngine.ts';
import type { Options, Request, Room } from '../core/ChatEngine.ts';

const room: Room = { id: 4, company_id: 1, membership_id: 12, name: 'Group', is_group: true, avatar_version: 1 };
function harness(extra: Partial<Options> = {}) {
  const data = new Map<string, string>(); const calls: Request[] = [];
  const detail = { api_version: 2, room: { id: 4, company_id: 1, name: 'Group', description: 'Saved', avatar_version: 1, is_group: true }, members: [{ user_id: 7, name: 'User', is_admin: true }], can_manage: true };
  let before: ((request: Request) => Promise<void>) | undefined;
  const engine = new ChatEngine({ origin: 'https://synthetic.example', database: 'trial',
    storage: { getItem: async k => data.get(k) ?? null, setItem: async (k, v) => { data.set(k, v); }, removeItem: async k => { data.delete(k); }, getAllKeys: async () => [...data.keys()] },
    transport: { request: async request => {
      calls.push(request); if (before) await before(request);
      if (request.path === '/web/session/destroy') return { result: null };
      if (request.path === '/web/session/authenticate') return { result: { uid: 7, db: 'trial' } };
      if (request.path.endsWith('/bootstrap')) return { api_version: 2, database: 'trial', user_id: 7, company_ids: [1], csrf_token: 'synthetic-csrf', permissions: { chat_view: true, chat_send: false, media: false } };
      if (request.path === '/bchat/api/v2/rooms') return { rooms: [{ ...room, avatar_version: detail.room.avatar_version }] };
      if (request.path.includes('/changes')) return { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
      if (request.path.endsWith('/group') && request.method === 'GET') return structuredClone(detail);
      if (request.path.endsWith('/group')) {
        const payload = JSON.parse(request.form!.payload!);
        if (payload.action === 'set_description') detail.room.description = payload.description;
        return { api_version: 2, room_id: 4, action: payload.action };
      }
      throw new Error('unexpected synthetic route');
    } }, ...extra });
  return { engine, detail, calls, before(value: typeof before) { before = value; } };
}
const login = (engine: ChatEngine) => engine.login('synthetic', 'not-a-real-secret', false);
test('group description mirrors UTF8/normalization/control limits and allows clearing', () => {
  assert.equal(groupDescription('  first\r\nsecond  '), 'first\nsecond');
  assert.equal(groupDescription('أ'.repeat(512)).length, 512);
  assert.equal(groupDescription(''), '');
  for (const value of ['أ'.repeat(513), '\ud800', 'bad\u0000text', 'a\tb', 42, null]) assert.throws(() => groupDescription(value), { code: 'description_invalid' });
});
test('group details are scoped typed metadata, readable without message-send/media permissions', async () => {
  const { engine, detail } = harness(); await login(engine);
  const result = await engine.groupInfo(room);
  assert.equal(result.can_manage, true); assert.equal(result.room.description, 'Saved');
  assert.equal('membership_id' in result.room, false);
  result.members.length = 0; assert.equal(detail.members.length, 1);
  assert.match(engine.accountScope!, /synthetic.example.*trial/);
  const mutations: (() => void)[] = [() => { detail.room.company_id = 2; }, () => { detail.room.avatar_version = -1; },
    () => { detail.members.push({ user_id: 7, name: 'Duplicate', is_admin: false }); }, () => { detail.room.description = 'x'.repeat(1025); }];
  for (const mutate of mutations) {
    const app = harness(); await login(app.engine);
    const saved = structuredClone(detail); mutate(); Object.assign(app.detail, structuredClone(detail));
    await assert.rejects(app.engine.groupInfo(room)); Object.assign(detail, saved);
  }
});
test('description uses the existing exact form/action contract and authoritative readback', async () => {
  const { engine, calls } = harness(); await login(engine);
  await engine.groupChange(room, { action: 'set_description', description: '  new\r\nvalue ' });
  const post = calls.find(call => call.path.endsWith('/group') && call.method === 'POST')!;
  assert.deepEqual(Object.keys(post.form!).sort(), ['csrf_token', 'payload']);
  assert.deepEqual(JSON.parse(post.form!.payload!), { api_version: 2, action: 'set_description', description: 'new\nvalue' });
  assert.equal((await engine.groupInfo(room)).room.description, 'new\nvalue');
  await engine.groupChange(room, { action: 'set_description', description: '' });
  assert.equal((await engine.groupInfo(room)).room.description, '');
});

test('presentation account scope changes on same-actor relogin without changing durable storage namespace', async () => {
  const { engine } = harness(); await login(engine);
  const before = engine.accountScope!;
  assert.match(before, /\/epoch:\d+$/);
  await engine.logout(); assert.equal(engine.accountScope, null);
  await login(engine); const after = engine.accountScope!;
  assert.equal(engine.identity!.user_id, 7);
  assert.notEqual(after, before);
  assert.equal(after.replace(/\/epoch:\d+$/, ''), before.replace(/\/epoch:\d+$/, ''));
});
test('avatar upload is managerial, epoch fenced, ACK checked and read back without message-media ACLs', async () => {
  let uploads = 0;
  const app = harness({ uploadGroupAvatar: async (target, _input, csrf, signal) => {
    uploads++; assert.equal(target.membership_id, 12); assert.equal(csrf, 'synthetic-csrf'); assert.equal(signal.aborted, false);
    app.detail.room.avatar_version++; return { api_version: 2, room_id: 4, avatar_version: app.detail.room.avatar_version };
  } });
  await login(app.engine);
  const result = await app.engine.setGroupAvatar(room, { uri: 'file:///synthetic.png', name: 'group.png', mime: 'image/png' });
  assert.equal(result.room.avatar_version, 2); assert.equal(uploads, 1);
  app.detail.can_manage = false;
  await assert.rejects(app.engine.setGroupAvatar(room, { uri: 'file:///synthetic.png', name: 'group.png', mime: 'image/png' }), { code: 'group_manage_denied' });
  assert.equal(uploads, 1);
});
test('lost avatar ACK never retries or reports success even when readback has a newer version', async () => {
  let uploads = 0;
  const app = harness({ uploadGroupAvatar: async () => { uploads++; app.detail.room.avatar_version++; throw new ChatError('connection_failed'); } });
  await login(app.engine);
  await assert.rejects(app.engine.setGroupAvatar(room, { uri: 'file:///synthetic.png', name: 'group.png', mime: 'image/png' }), { code: 'avatar_uncertain' });
  assert.equal(uploads, 1); assert.equal(app.engine.rooms()[0]!.avatar_version, 2);
});
test('a logout during an avatar upload discards its late ACK', async () => {
  let resolve!: (value: any) => void;
  const app = harness({ uploadGroupAvatar: () => new Promise(done => { resolve = done; }) }); await login(app.engine);
  const upload = app.engine.setGroupAvatar(room, { uri: 'file:///synthetic.png', name: 'group.png', mime: 'image/png' });
  while (!resolve) await new Promise(done => setImmediate(done));
  await app.engine.logout(); resolve({ api_version: 2, room_id: 4, avatar_version: 2 });
  await assert.rejects(upload, { code: 'stale_session' });
});

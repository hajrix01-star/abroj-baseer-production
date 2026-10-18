import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ChatEngine, ChatError } from '../core/ChatEngine.ts';
import type { History, Message, Request, Room } from '../core/ChatEngine.ts';
import { MemoryHistoryArchive } from '../core/MemoryHistoryArchive.ts';
import { ARCHIVE_LIMITS, mergeCoverage, pageCoverage } from '../core/HistoryArchive.ts';
import type { Guard, HistoryScope } from '../core/HistoryArchive.ts';

const room: Room = { id: 4, company_id: 1, membership_id: 12, name: 'Synthetic', is_group: true };
const message = (n: number): Message => ({ id: n * 3 + 2, author_user_id: n % 2 ? 8 : 7, author_name: 'Synthetic', text: `Message ${n}`, created_at: '2026-10-18 00:00:00' });
const guard = () => {};
function deferred() { let resolve!: () => void; const promise = new Promise<void>(done => { resolve = done; }); return { promise, resolve }; }
const scope: HistoryScope = { account: 'synthetic/db/u7', companyId: 1, roomId: 4, membershipId: 12 };
function app(archive = new MemoryHistoryArchive(), storage = new Map<string, string>()) {
  const calls: Request[] = []; let total = 720, changed = false, cursor = 0, allowed = true, now = 100000000;
  let before: ((request: Request) => Promise<void>) | undefined;
  const engine = new ChatEngine({ archive, origin: 'https://synthetic.invalid', database: 'db', now: () => now,
    uuid: () => '12345678-1234-4234-8234-123456789abc', storage: { getItem: async key => storage.get(key) ?? null, setItem: async (key, value) => { storage.set(key, value); }, removeItem: async key => { storage.delete(key); }, getAllKeys: async () => [...storage.keys()] },
    transport: { request: async request => {
      calls.push(request); if (before) await before(request);
      if (request.path === '/web/session/destroy') return { result: null };
      if (request.path === '/web/session/authenticate') return { result: { uid: 7, db: 'db' } };
      if (request.path.endsWith('/bootstrap')) return { api_version: 2, user_id: 7, database: 'db', company_ids: [1], csrf_token: 'synthetic', permissions: { chat_view: true, chat_send: true, media: true } };
      if (request.path === '/bchat/api/v2/rooms') return { api_version: 2, rooms: allowed ? [room] : [] };
      if (request.path.includes('/changes?')) { const changes = changed ? [{ kind: 'message', room_id: room.id }] : []; if (changed) cursor++; changed = false; return { api_version: 2, changes, next_after: cursor, watermark: cursor, reset_required: false }; }
      if (request.method === 'GET' && request.path.includes('/messages')) {
        if (!allowed) throw new ChatError('membership_changed', 403);
        const value = new URL(request.path, 'https://synthetic.invalid').searchParams.get('before_id');
        const end = value ? Math.min(total, Math.floor((Number(value) - 3) / 3)) : total;
        const start = Math.max(1, end - 29), messages: Message[] = [];
        for (let n = start; n <= end; n++) messages.push(message(n));
        return { api_version: 2, messages, next_before_id: start > 1 ? message(start).id : null };
      }
      throw new Error('unexpected synthetic route');
    } } });
  return { engine, archive, storage, calls, total(n: number) { total = n; }, add(n: number) { total += n; changed = true; }, revoke() { allowed = false; }, before(fn: typeof before) { before = fn; }, advance(ms: number) { now += ms; } };
}
const login = (engine: ChatEngine) => engine.login('synthetic', 'not-real', true);

test('page proof validates sparse IDs/progress, merges only touching proven ranges', () => {
  assert.deepEqual(pageCoverage(null, { api_version: 2, messages: [message(5), message(7)], next_before_id: message(5).id }).range, { low: 17, high: 24 });
  assert.deepEqual(mergeCoverage([{ low: 10, high: 20 }, { low: 20, high: 30 }, { low: 40, high: 50 }]), [{ low: 10, high: 30 }, { low: 40, high: 50 }]);
  assert.throws(() => pageCoverage(20, { api_version: 2, messages: [message(7)], next_before_id: 23 }));
  assert.throws(() => pageCoverage(null, { api_version: 2, messages: [message(7)], next_before_id: 22 }));
});

test('720-message sparse history traverses past500 with moving180 window, stable cursors and no duplicates', async () => {
  const { engine } = app(); await login(engine); let history = await engine.latest(room);
  const seen = new Set(history.messages.map(row => row.id)); let steps = 0, previous = Infinity;
  while (history.next_before_id !== null) {
    assert.ok(history.next_before_id < previous); previous = history.next_before_id;
    history = await engine.history(room, history.next_before_id); steps++;
    assert.ok(history.messages.length <= 180); assert.ok(new TextEncoder().encode(JSON.stringify(history)).length <= ARCHIVE_LIMITS.windowBytes);
    history.messages.forEach(row => seen.add(row.id)); assert.ok(steps <= 30);
  }
  assert.equal(seen.size, 720); assert.equal(history.messages[0]!.id, message(1).id); assert.equal(history.archive!.older.kind, 'end');
});

test('polling archives a disconnected new head without snapping browsing, explicit latest never uses before_id', async () => {
  const testApp = app(); await login(testApp.engine); let history = await testApp.engine.latest(room);
  history = await testApp.engine.history(room, history.next_before_id!); const ids = history.messages.map(row => row.id);
  testApp.add(75); await testApp.engine.refresh(); const polled = await testApp.engine.history(room);
  assert.deepEqual(polled.messages.map(row => row.id), ids); assert.equal(polled.archive!.browsing, true);
  assert.equal(polled.archive!.newer.kind, 'gap');
  const latest = await testApp.engine.latest(room); assert.equal(latest.messages.at(-1)!.id, message(795).id);
  assert.equal(testApp.calls.at(-1)!.path, '/bchat/api/v2/rooms/4/messages');
  assert.equal(latest.archive!.browsing, false); assert.equal(latest.archive!.partial, true);
});

test('offline cached pages remain navigable, unknown gap is not end, and TTL blocks archive after await', async () => {
  const testApp = app(); await login(testApp.engine); let history = await testApp.engine.latest(room);
  for (let i = 0; i < 7; i++) history = await testApp.engine.history(room, history.next_before_id!);
  await testApp.engine.latest(room); testApp.engine.markDisconnected(); const before = testApp.calls.length;
  const older = await testApp.engine.history(room, message(691).id); assert.ok(older.messages[0]!.id < message(691).id);
  assert.equal(testApp.calls.length, before); assert.notEqual(older.archive!.older.kind, 'end');
  testApp.advance(24 * 60 * 60 * 1000 + 1); await assert.rejects(testApp.engine.history(room), { code: 'offline_expired' });
});

test('legacy internal holes have no proof, partial rows revalidate online, and migration never rewrites outbox', async () => {
  const testApp = app(); await login(testApp.engine); await testApp.engine.enqueue(room, 'Durable unsent');
  const root = 'odoo-chat/v1/https%3A%2F%2Fsynthetic.invalid/db/', key = `${root}u/7/c/1/r/4/m/12/history`;
  const legacy: History = { api_version: 2, messages: [...Array.from({ length: 30 }, (_, i) => message(i + 1)), ...Array.from({ length: 31 }, (_, i) => message(i + 100))], next_before_id: null };
  testApp.storage.set(key, JSON.stringify(legacy));
  const pending = [...testApp.storage].filter(([name]) => name.includes('/outbox/'));
  const restored = app(testApp.archive, testApp.storage); assert.equal(await restored.engine.restoreOffline(), true);
  const cached = await restored.engine.history(room); assert.equal(cached.archive!.partial, true); assert.notEqual(cached.archive!.older.kind, 'end');
  assert.equal(restored.storage.has(key), false); assert.deepEqual([...restored.storage].filter(([name]) => name.includes('/outbox/')), pending);
  await login(restored.engine);
  const before = restored.calls.length; await restored.engine.history(room, message(100).id);
  assert.equal(restored.calls.slice(before).filter(request => request.path.includes('/messages?before_id=')).length, 1);
});

test('offline legacy islands revalidate as one proven window and every internal-hole message remains reachable', async () => {
  const original = app(); await login(original.engine);
  const key = 'odoo-chat/v1/https%3A%2F%2Fsynthetic.invalid/db/u/7/c/1/r/4/m/12/history';
  original.storage.set(key, JSON.stringify({ api_version: 2, messages: [...Array.from({ length: 30 }, (_, i) => message(i + 1)), ...Array.from({ length: 31 }, (_, i) => message(i + 100))], next_before_id: null }));
  const restored = app(original.archive, original.storage); restored.total(130);
  assert.equal(await restored.engine.restoreOffline(), true);
  let page = await restored.engine.history(room);
  page = await restored.engine.history(room, page.next_before_id!); // User has already reached provisional first1 offline.
  assert.equal(page.messages[0]!.id, message(1).id);
  await restored.engine.refresh();
  const seen = new Set<number>(); let steps = 0;
  do {
    const before = restored.calls.length;
    page = await restored.engine.history(room, page.next_before_id!);
    assert.ok(restored.calls.slice(before).filter(request => request.path.includes('/messages')).length <= 1);
    page.messages.forEach(row => seen.add(row.id));
    assert.ok(++steps < 10, 'validated cursor must progress through the internal hole');
  } while (page.next_before_id !== null);
  assert.deepEqual([...seen].sort((a, b) => a - b), Array.from({ length: 130 }, (_, i) => message(i + 1).id));
  assert.equal(page.archive!.unverified, false);
  assert.equal(page.archive!.older.kind, 'end');
});

test('archive media lookup is scoped beyond hot window and purged on member revocation', async () => {
  const testApp = app(); await login(testApp.engine);
  const mediaRow = { ...message(5), media: { id: 99, size: 1, sha256: 'a'.repeat(64), kind: 'file', mime: 'text/plain', name: 'synthetic.txt' } };
  const actor = 'odoo-chat/v1/https%3A%2F%2Fsynthetic.invalid/db/u/7/';
  await testApp.archive.importLegacy({ ...scope, account: actor }, { api_version: 2, messages: [mediaRow], next_before_id: null }, guard);
  await testApp.engine.latest(room); assert.equal((await testApp.engine.mediaAssociation(room, 99))!.id, mediaRow.id);
  testApp.revoke(); await testApp.engine.refresh(); await assert.rejects(testApp.engine.mediaAssociation(room, 99), { code: 'room_unavailable' });
});

test('failed legacy transaction retains source and queued sends for same-user recovery', async () => {
  class FailingArchive extends MemoryHistoryArchive { override async importLegacy(_scope: HistoryScope, _history: History, _guard: Guard) { throw new Error('synthetic DB full'); } }
  const original = app(); await login(original.engine); await original.engine.enqueue(room, 'Still queued');
  const key = 'odoo-chat/v1/https%3A%2F%2Fsynthetic.invalid/db/u/7/c/1/r/4/m/12/history';
  original.storage.set(key, JSON.stringify({ api_version: 2, messages: [message(1)], next_before_id: null }));
  const pending = [...original.storage].filter(([name]) => name.includes('/outbox/'));
  const restored = app(new FailingArchive(), original.storage); assert.equal(await restored.engine.restoreOffline(), false);
  assert.equal(original.storage.has(key), true); assert.deepEqual([...original.storage].filter(([name]) => name.includes('/outbox/')), pending);
});

test('proven cached pages with a distant gap do not re-fetch, while legacy internal holes still revalidate', async () => {
  const testApp = app(); await login(testApp.engine); let page = await testApp.engine.latest(room);
  for (let i = 0; i < 7; i++) page = await testApp.engine.history(room, page.next_before_id!);
  testApp.add(75); await testApp.engine.refresh();
  const before = testApp.calls.length;
  const cached = await testApp.engine.history(room, message(691).id);
  assert.ok(cached.messages.length > 0); assert.equal(testApp.calls.length, before, 'proven cached page is not revalidated because of a separate gap');
});

test('duplicate older action emits one server page and denied older response purges exact membership', async () => {
  const testApp = app(); await login(testApp.engine); const page = await testApp.engine.latest(room);
  const wait = deferred(), started = deferred();
  testApp.before(async request => { if (request.path.includes('/messages?before_id=')) { started.resolve(); await wait.promise; } });
  const first = testApp.engine.history(room, page.next_before_id!), second = testApp.engine.history(room, page.next_before_id!);
  await started.promise; const result1 = assert.rejects(first, { code: 'membership_changed' }), result2 = assert.rejects(second, { code: 'membership_changed' });
  testApp.revoke(); wait.resolve(); await Promise.all([result1, result2]);
  assert.equal(testApp.calls.filter(request => request.path.includes('/messages?before_id=')).length, 1);
  assert.equal(testApp.engine.rooms().length, 0);
});

test('logout cleanup survives account reset and drains before immediate same-user re-login archive writes', async () => {
  class DelayedPurge extends MemoryHistoryArchive {
    block = false; waiting = deferred(); started = deferred();
    override async purgeAccount(account: string, assertCurrent: Guard) {
      if (this.block) { this.block = false; this.started.resolve(); await this.waiting.promise; }
      return super.purgeAccount(account, assertCurrent);
    }
  }
  const archive = new DelayedPurge(), testApp = app(archive); await login(testApp.engine);
  const actor = 'odoo-chat/v1/https%3A%2F%2Fsynthetic.invalid/db/u/7/';
  await archive.importLegacy({ ...scope, account: actor }, { api_version: 2, messages: [{ ...message(1), media: { id: 99 } }], next_before_id: null }, guard);
  archive.block = true; const logout = testApp.engine.logout(); const stale = assert.rejects(logout, { code: 'stale_session' });
  await archive.started.promise; const relogin = login(testApp.engine); archive.waiting.resolve(); await stale; await relogin;
  assert.equal(testApp.engine.identity!.user_id, 7); assert.equal(await testApp.engine.mediaAssociation(room, 99), null, 'prior-generation data purged before bind');
  const fresh = await testApp.engine.latest(room); assert.equal(fresh.messages.at(-1)!.id, message(720).id);
  assert.equal((await testApp.engine.history(room)).messages.at(-1)!.id, message(720).id, 'late cleanup cannot clear new session data');
});

test('offline lease expiring during a deferred archive read never returns retained rows', async () => {
  class DelayedRead extends MemoryHistoryArchive {
    block = false; waiting = deferred(); started = deferred();
    override async read(...args: Parameters<MemoryHistoryArchive['read']>) {
      if (this.block) { this.block = false; this.started.resolve(); await this.waiting.promise; }
      return super.read(...args);
    }
  }
  const archive = new DelayedRead(), testApp = app(archive); await login(testApp.engine); await testApp.engine.latest(room);
  await testApp.engine.enqueue(room, 'Keep durable pending'); testApp.engine.markDisconnected(); archive.block = true;
  const read = testApp.engine.history(room), rejected = assert.rejects(read, { code: 'offline_expired' });
  await archive.started.promise; testApp.advance(24 * 60 * 60 * 1000 + 1); archive.waiting.resolve(); await rejected;
  assert.ok([...testApp.storage.keys()].some(key => key.includes('/outbox/')));
});

test('restore reconciliation DB failure cannot purge existing durable outbox', async () => {
  class FailedReconcile extends MemoryHistoryArchive { override async reconcile() { throw new Error('synthetic SQLite IO'); } }
  const original = app(); await login(original.engine); await original.engine.enqueue(room, 'Must remain durable');
  const before = [...original.storage].filter(([key]) => key.includes('/outbox/'));
  const next = app(new FailedReconcile(), original.storage);
  assert.equal(await next.engine.restoreOffline(), false);
  assert.deepEqual([...original.storage].filter(([key]) => key.includes('/outbox/')), before);
  assert.equal(next.engine.status, 'authentication_required');
});

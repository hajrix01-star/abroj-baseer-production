import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LeadershipEngine } from '../LeadershipEngine.ts';
import { LeadershipSnapshots } from '../LeadershipSnapshots.ts';
import { identity, options, report } from './fixtures.ts';
import type { SnapshotAuthority } from '../LeadershipSnapshots.ts';

const query = { month: '2026-10', period: 'month' as const };
function setup() {
  const values = new Map<string, string>(); let now = Date.parse('2026-10-19T12:00:00Z'), offline = false;
  let scope: SnapshotAuthority | null = { ...identity, revision: 1, leaseRemainingMs: 3600000 };
  let failure: unknown, falseOptions = false, requests = 0;
  const storage = { async getItem(k: string) { return values.get(k) ?? null; }, async setItem(k: string, v: string) { values.set(k, v); }, async removeItem(k: string) { values.delete(k); }, async getAllKeys() { return [...values.keys()]; } };
  const make = () => new LeadershipEngine({
    now: () => now, offline: () => offline, displayScope: () => scope,
    identityScope: () => offline ? null : { ...identity, epoch: `${identity.epoch}/orders`, revision: 1 },
    snapshots: new LeadershipSnapshots({ storage, current: () => scope, now: () => now }),
    transport: { request: async req => { requests++; if (failure) throw failure; return req.path.endsWith('options') ? falseOptions ? { ...options, can_view: false, companies: [] } : options : report(); } },
  });
  return { make, get requests() { return requests; }, set offline(v: boolean) { offline = v; }, set scope(v: SnapshotAuthority | null) { scope = v; }, set failure(v: unknown) { failure = v; }, set falseOptions(v: boolean) { falseOptions = v; }, set now(v: number) { now = v; } };
}

test('remembered leadership snapshots survive restart without granting HTTP authority or changing decimals', async () => {
  const f = setup(), online = f.make(); await online.options(); const source = await online.read(query), count = f.requests;
  f.offline = true; const reopened = f.make();
  assert.equal((await reopened.options()).companies.length, 2);
  assert.deepEqual(await reopened.read(query), source);
  assert.equal(f.requests, count); assert.equal(source.overview.sales.value, '123456.78');
  assert.equal(reopened.displayLeaseRemainingMs, 3600000);
  f.scope = null; await assert.rejects(reopened.read(query), { code: 'snapshot_unavailable' });
  assert.equal(reopened.displayLeaseRemainingMs, 0);
});

test('only explicit offline mode reads snapshots; server errors and malformed responses never fallback', async () => {
  const f = setup(), engine = f.make(); await engine.options(); await engine.read(query);
  f.failure = { status: 503 }; await assert.rejects(engine.read(query), { code: 'server_update_required' });
  f.failure = { code: 'invalid_response' }; await assert.rejects(engine.read(query), { code: 'invalid_response' });
  f.failure = { code: 'connection_failed' }; await assert.rejects(engine.read(query), { code: 'network_error' });
  f.offline = true; const count = f.requests; await engine.options(); await engine.read(query); assert.equal(f.requests, count);
  await assert.rejects(engine.read({ ...query, companyId: 1 }), { code: 'snapshot_unavailable' });
});

test('denied options revoke snapshots across clear and restart until a new verified report', async () => {
  const f = setup(), engine = f.make(); await engine.options(); await engine.read(query);
  f.falseOptions = true; await assert.rejects(engine.options(), { code: 'forbidden' });
  engine.clear(); f.offline = true; await assert.rejects(f.make().options(), { code: 'snapshot_unavailable' });
  f.falseOptions = false; f.offline = false; const next = f.make(); await next.options(); await next.read(query);
  f.offline = true; await f.make().options();
});

test('denied report invalidates financial snapshots instead of retaining a remembered permission', async () => {
  const f = setup(), engine = f.make(); await engine.options(); await engine.read(query);
  f.failure = { status: 403 }; await assert.rejects(engine.read(query), { code: 'forbidden' });
  f.offline = true; await assert.rejects(f.make().options(), { code: 'snapshot_unavailable' });
});

test('same-authority reconnect preserves the original cached display deadline during online verification', async () => {
  const f = setup(), engine = f.make(); await engine.options(); await engine.read(query);
  f.offline = true; const reopened = f.make(); await reopened.options(); await reopened.read(query);
  const deadline = reopened.displayLeaseRemainingMs;
  f.offline = false; await reopened.options();
  assert.equal(reopened.displayLeaseRemainingMs, deadline); assert.equal(reopened.displayIsCached, true);
  await reopened.read(query); assert.equal(reopened.displayIsCached, false); assert.equal(reopened.displayLeaseRemainingMs, Infinity);
});

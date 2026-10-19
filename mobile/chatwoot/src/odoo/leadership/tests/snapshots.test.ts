import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { Storage } from '../../core/ChatEngine.ts';
import { LeadershipSnapshots } from '../LeadershipSnapshots.ts';
import type { SnapshotAuthority } from '../LeadershipSnapshots.ts';
import type { LeadershipOptions, LeadershipQuery } from '../types.ts';
import { optionsResponse } from '../validation.ts';
import { identity, options as wireOptions, report } from './fixtures.ts';

const DAY = 24 * 60 * 60 * 1000, NOW = Date.parse('2026-10-19T12:00:00Z');
const query: LeadershipQuery = { month: '2026-10', period: 'month' };
const opts = optionsResponse(wireOptions, identity);
const waiting = () => { let resolve!: () => void; const promise = new Promise<void>(done => { resolve = done; }); return { promise, resolve }; };
class Memory implements Storage {
  data = new Map<string, string>(); log: Array<{ kind: string; key: string; value?: string }> = [];
  hook: (kind: string, key: string, value?: string) => void | Promise<void> = () => undefined;
  async getItem(key: string) { this.log.push({ kind: 'get', key }); await this.hook('get', key); return this.data.get(key) ?? null; }
  async setItem(key: string, value: string) { this.log.push({ kind: 'set', key, value }); await this.hook('set', key, value); this.data.set(key, value); }
  async removeItem(key: string) { this.log.push({ kind: 'remove', key }); await this.hook('remove', key); this.data.delete(key); }
  async getAllKeys(): Promise<readonly string[]> { throw new Error('Snapshot implementation must not enumerate unrelated storage'); }
}
function setup(leaseRemainingMs = DAY) {
  const authority: SnapshotAuthority = { origin: identity.origin, db: identity.db, uid: identity.uid, companyIds: [1, 2], canView: true, revision: 1, epoch: 1, leaseRemainingMs };
  const state = { authority: authority as SnapshotAuthority | null, now: NOW }, storage = new Memory();
  const create = () => new LeadershipSnapshots({ storage, current: () => state.authority, now: () => state.now });
  return { state, storage, create, cache: create(), authority };
}
const key = (storage: Memory, suffix: string) => [...storage.data.keys()].find(k => k.endsWith(suffix))!;
const denied = { code: 'snapshot_unavailable' };

test('snapshot exact decimals/server displays survive restart, unknown data is never persisted, options alone has no report deadline', async () => {
  const h = setup(), raw = report(); raw.overview.sales.value = '12345678901234567890.1234567890123456'; raw.overview.sales.display = 'Server display';
  (raw as any).private_source_ids = ['must-not-persist'];
  await h.cache.save(h.authority, opts, query, raw);
  assert.ok(![...h.storage.data.values()].join('').includes('must-not-persist'));
  h.state.authority = { ...h.authority, epoch: 'restart' };
  const restarted = h.create();
  await restarted.options(h.state.authority); assert.equal(restarted.displayExpiresAt, 0);
  const restored = await restarted.read(h.state.authority, query);
  assert.equal(restored.overview.sales.value, raw.overview.sales.value); assert.equal(restored.overview.sales.display, 'Server display');
  assert.equal(restarted.displayExpiresAt, NOW + DAY);
  await assert.rejects(restarted.read(h.state.authority, { ...query, companyId: 1 }), denied);
  assert.equal(restarted.displayExpiresAt, 0);
});
test('no remembered/current authority, expired lease and each actor/grant/revision change deny cached access', async () => {
  for (const change of [
    () => null, (a: SnapshotAuthority) => ({ ...a, leaseRemainingMs: 0 }), (a: SnapshotAuthority) => ({ ...a, canView: false }),
    (a: SnapshotAuthority) => ({ ...a, origin: 'https://other.test' }), (a: SnapshotAuthority) => ({ ...a, db: 'other' }),
    (a: SnapshotAuthority) => ({ ...a, uid: 10 }), (a: SnapshotAuthority) => ({ ...a, companyIds: [1] }), (a: SnapshotAuthority) => ({ ...a, revision: 2 }),
  ]) {
    const h = setup(); await h.cache.save(h.authority, opts, query, report()); h.state.authority = change(h.authority);
    await assert.rejects(h.cache.read(h.state.authority ?? h.authority, query));
    assert.equal(h.cache.displayExpiresAt, 0);
  }
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  h.state.authority = { ...h.authority, companyIds: [2, 1] };
  assert.equal((await h.create().read(h.state.authority, query)).company_id, null);
});
test('only previously visited exact company/month/period/custom-date tuples exist; unauthorized company cannot be saved', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  for (const q of [{ ...query, month: '2026-09' }, { ...query, companyId: 1 }, { ...query, period: 'date' as const, date: '2026-10-10' }])
    await assert.rejects(h.cache.read(h.authority, q), denied);
  const single = { ...query, companyId: 1 }; await h.cache.save(h.authority, opts, single, report(1));
  assert.equal((await h.cache.read(h.authority, single)).company_id, 1);
  const raw = report(); raw.company_id = 99; raw.companies = [{ id: 99, name: 'Forbidden' }];
  await assert.rejects(h.cache.save(h.authority, opts, { ...query, companyId: 99 }, raw), denied);
});
test('24h and initial shorter lease expiry are immutable across later renewed chat leases and reads', async () => {
  for (const lease of [DAY, 30000]) {
    const h = setup(lease); await h.cache.save(h.authority, opts, query, report());
    h.state.now += 1000; h.state.authority = { ...h.authority, leaseRemainingMs: DAY };
    await h.cache.read(h.state.authority, query); assert.equal(h.cache.displayExpiresAt, NOW + lease);
    h.state.now = NOW + lease;
    await assert.rejects(h.create().read(h.state.authority, query), denied);
    await assert.rejects(h.create().options(h.state.authority), denied);
  }
});
test('today/yesterday bind report as_of and actual Riyadh date on save and restart lookup across midnight', async () => {
  for (const period of ['today', 'yesterday'] as const) {
    const h = setup(), q = { ...query, period }, selected = period === 'today' ? '2026-10-19' : '2026-10-18';
    h.state.now = Date.parse('2026-10-19T20:59:59Z');
    await h.cache.save(h.authority, opts, q, report(undefined, '2026-10', period, selected));
    assert.equal((await h.create().read(h.authority, q)).filters.from, selected);
    h.state.now = Date.parse('2026-10-19T21:00:00Z');
    await assert.rejects(h.create().read(h.authority, q), denied);
    await assert.rejects(h.create().save(h.authority, opts, q, report(undefined, '2026-10', period, selected)), denied);
  }
});
test('persistent highwater rejects rollback after restart, including rollback above original save time', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  h.state.now += 60000; await h.cache.read(h.authority, query);
  h.state.now -= 1000; await assert.rejects(h.create().read(h.authority, query), denied);
  await assert.rejects(h.create().save(h.authority, opts, query, report()), denied);
});
test('failed highwater write and rollback during highwater await return no financial report/deadline', async () => {
  for (const rollback of [false, true]) {
    const h = setup(); await h.cache.save(h.authority, opts, query, report()); h.state.now += 5000;
    h.storage.hook = (kind, name) => { if (kind === 'set' && name.endsWith('/control')) { if (rollback) h.state.now -= 1000; else throw new Error('disk'); } };
    await assert.rejects(h.cache.read(h.authority, query), denied); assert.equal(h.cache.displayExpiresAt, 0);
  }
});
test('malformed, oversized, wrong-company/fingerprint/decimal or extended-expiry cache never yields a report', async () => {
  for (const damage of [
    () => '{', () => 'x'.repeat(1048577),
    (v: any) => ({ ...v, fingerprint: 'foreign' }),
    (v: any) => { v.entries[0].report.overview.sales.value = 12; return v; },
    (v: any) => { v.entries[0].report.companies.pop(); return v; },
    (v: any) => { v.entries[0].expiresAt += 1; return v; },
  ]) {
    const h = setup(); await h.cache.save(h.authority, opts, query, report());
    const name = key(h.storage, '/envelope'), changed = damage(JSON.parse(h.storage.data.get(name)!));
    h.storage.data.set(name, typeof changed === 'string' ? changed : JSON.stringify(changed));
    await assert.rejects(h.create().read(h.authority, query), denied);
  }
});
test('eight-visited-query cap evicts oldest save, not the last-read snapshot', async () => {
  const h = setup();
  for (let i = 1; i <= 8; i++) {
    const month = '2026-' + String(i).padStart(2, '0');
    await h.cache.save(h.authority, opts, { month, period: 'month' }, report(undefined, month)); h.state.now++;
  }
  await h.cache.read(h.authority, { month: '2026-01', period: 'month' });
  await h.cache.save(h.authority, opts, query, report());
  assert.equal(JSON.parse(h.storage.data.get(key(h.storage, '/envelope'))!).entries.length, 8);
  await assert.rejects(h.cache.read(h.authority, { month: '2026-01', period: 'month' }), denied);
  assert.equal((await h.cache.read(h.authority, query)).filters.month, '2026-10');
});
test('whole actor envelope is UTF8 bounded and oldest entries evict below1MiB', async () => {
  const h = setup(), heavy = (month: string) => {
    const r = report(undefined, month);
    for (const c of [r.calendar, r.previous_calendar]) for (const d of c.days) { d.status_label = '界'.repeat(512); d.coverage_label = '界'.repeat(512); }
    return r;
  };
  for (let i = 1; i <= 8; i++) {
    const month = '2026-' + String(i).padStart(2, '0'); await h.cache.save(h.authority, opts, { month, period: 'month' }, heavy(month)); h.state.now++;
  }
  const raw = h.storage.data.get(key(h.storage, '/envelope'))!, envelope = JSON.parse(raw);
  assert.ok(Buffer.byteLength(raw, 'utf8') <= 1048576); assert.ok(envelope.entries.length < 8);
  await assert.rejects(h.cache.read(h.authority, { month: '2026-01', period: 'month' }), denied);
});
test('a single tuple exceeding total UTF8 budget is skipped/rejected without hiding or persisting online raw response', async () => {
  const h = setup(); h.state.authority!.companyIds = Array.from({ length: 1000 }, (_, i) => i + 1);
  const many: LeadershipOptions = { ...opts, companies: h.state.authority!.companyIds.map(id => ({ id, name: '界'.repeat(256) })) };
  const raw = report(1);
  for (const c of [raw.calendar, raw.previous_calendar]) for (const d of c.days) {
    d.status_label = '界'.repeat(512); d.coverage_label = '界'.repeat(512);
    for (const amount of [d.sales, d.target, d.basis, d.ratio]) amount.display = '界'.repeat(128);
  }
  assert.ok(Buffer.byteLength(JSON.stringify(many)) < 1048576); assert.ok(Buffer.byteLength(JSON.stringify(raw)) < 1048576);
  await assert.rejects(h.cache.save(h.state.authority!, many, { ...query, companyId: 1 }, raw), denied);
  assert.equal(key(h.storage, '/envelope'), undefined); assert.equal(raw.overview.sales.value, '123456.78');
});
test('revoke writes durable blocked marker before deletion; deletion failure stays denied after restart; only fresh save unlocks after deletion', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report()); await h.cache.read(h.authority, query);
  h.storage.hook = (kind) => { if (kind === 'remove') throw new Error('delete failed'); };
  await assert.rejects(h.cache.revoke(h.authority), denied); assert.equal(h.cache.displayExpiresAt, 0);
  assert.equal(JSON.parse(h.storage.data.get(key(h.storage, '/control'))!).blocked, true);
  await assert.rejects(h.create().read(h.authority, query), denied);
  await assert.rejects(h.cache.save(h.authority, opts, query, report()), denied);
  h.storage.hook = () => undefined; h.storage.log = [];
  await h.cache.save(h.authority, opts, { ...query, companyId: 1 }, report(1));
  const deleted = h.storage.log.findIndex(e => e.kind === 'remove' && e.key.endsWith('/envelope'));
  const unblocked = h.storage.log.findIndex(e => e.kind === 'set' && e.key.endsWith('/control') && !JSON.parse(e.value!).blocked);
  assert.ok(deleted >= 0 && unblocked > deleted);
  await assert.rejects(h.cache.read(h.authority, query), denied);
  assert.equal((await h.create().read(h.authority, { ...query, companyId: 1 })).company_id, 1);
});
test('revocation still persists denial if metadata read fails; zero lease/no-view cleanup is accepted', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  h.storage.hook = (kind) => { if (kind === 'get') throw new Error('read failed'); };
  await h.cache.revoke({ ...h.authority, canView: false, leaseRemainingMs: 0 });
  h.storage.hook = () => undefined;
  await assert.rejects(h.create().read(h.authority, query), denied);
});
test('pending write cannot resurrect a revoked actor even when storage ignores cancellation', async () => {
  const h = setup(), entered = waiting(), held = waiting(); let once = true;
  h.storage.hook = async (kind, name) => { if (once && kind === 'set' && name.endsWith('/envelope')) { once = false; entered.resolve(); await held.promise; } };
  const saving = h.cache.save(h.authority, opts, query, report()), rejection = assert.rejects(saving, { code: 'stale' });
  await entered.promise; const revoked = h.cache.revoke(h.authority); held.resolve(); await rejection; await revoked;
  await assert.rejects(h.create().read(h.authority, query), denied);
});
test('current new-epoch logout tombstones prior writer before any new save, including current null after logout', async () => {
  for (const cleared of [false, true]) {
    const h = setup(); await h.cache.save(h.authority, opts, query, report());
    const next = { ...h.authority, epoch: 2 }; h.state.authority = cleared ? null : next;
    await h.cache.revoke(next); h.state.authority = next;
    await assert.rejects(h.create().read(next, query), denied);
  }
});
test('current new-epoch revoke cancels its pending save although last successful writer was older', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  const next = { ...h.authority, epoch: 2 }; h.state.authority = next;
  const entered = waiting(), held = waiting(); let once = true;
  h.storage.hook = async (kind, name) => { if (once && kind === 'set' && name.endsWith('/envelope')) { once = false; entered.resolve(); await held.promise; } };
  const saving = h.cache.save(next, opts, query, report()), rejection = assert.rejects(saving, { code: 'stale' });
  await entered.promise; const revoked = h.cache.revoke(next); held.resolve(); await rejection; await revoked;
  await assert.rejects(h.create().read(next, query), denied);
});
test('late old-epoch cleanup cannot erase newer successful save, even if current temporarily null/background', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  const next = { ...h.authority, epoch: 2 }; h.state.authority = next;
  await h.cache.save(next, opts, query, report()); h.state.authority = null;
  await h.cache.revoke(h.authority); h.state.authority = next;
  assert.equal((await h.create().read(next, query)).currency, 'SAR');
});
test('unknown cleanup epoch is never treated as positively old and denial survives restart', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  await h.cache.revoke({ ...h.authority, epoch: 'unknown/orders' });
  await assert.rejects(h.create().read(h.authority, query), denied);
});
test('actor/epoch changes across awaited reads are stale; queued concurrent saves serialize without lost tuples', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  const entered = waiting(), held = waiting(); let once = true;
  h.storage.hook = async (kind, name) => { if (once && kind === 'get' && name.endsWith('/envelope')) { once = false; entered.resolve(); await held.promise; } };
  const reading = h.cache.read(h.authority, query), rejection = assert.rejects(reading, { code: 'stale' });
  await entered.promise; h.state.authority = { ...h.authority, epoch: 2 }; held.resolve(); await rejection;
  h.storage.hook = () => undefined;
  await Promise.all([1, 2, 3].map(companyId => {
    const date = '2026-10-' + String(companyId).padStart(2, '0'), q = { ...query, period: 'date' as const, date };
    return h.cache.save(h.state.authority!, opts, q, report(undefined, '2026-10', 'date', date));
  }));
  for (const day of [1, 2, 3]) assert.equal((await h.cache.read(h.state.authority!, { ...query, period: 'date', date: '2026-10-0' + day })).filters.from, '2026-10-0' + day);
});
test('total persistent I/O failure rejects revoke and blocks in-process; no crash-durability claim', async () => {
  const h = setup(); await h.cache.save(h.authority, opts, query, report());
  h.storage.hook = () => { throw new Error('all IO unavailable'); };
  await assert.rejects(h.cache.revoke(h.authority), denied);
  await assert.rejects(h.cache.read(h.authority, query), denied); assert.equal(h.cache.displayExpiresAt, 0);
});

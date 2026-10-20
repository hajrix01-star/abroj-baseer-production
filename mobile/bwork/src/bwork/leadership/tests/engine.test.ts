import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LeadershipEngine } from '../LeadershipEngine.ts';
import { optionsResponse, reportResponse } from '../validation.ts';
import { identity, money, options, report } from './fixtures.ts';
const waiting = () => { let resolve!: (value: unknown) => void, reject!: (error: unknown) => void; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const validReport = (...args: Parameters<typeof report>) => { const r = report(...args); r.overview.current_month.sales = money('999.99'); return r; };

test('combined spending v2 requires server breakdown and rejects legacy bill-only payloads', () => {
  const opts = optionsResponse(options, identity), raw = validReport();
  raw.overview.spending = money('999.91');
  (raw.overview.spending_breakdown as any).private_source_ids = [88];
  const decoded = reportResponse(raw, { month: '2026-10', period: 'month' }, opts);
  assert.equal(decoded.overview.spending.value, '999.91'); // Display server total, never recompute in JS.
  assert.equal(decoded.overview.spending_breakdown.purchases.value, '16000.00');
  assert.equal(decoded.overview.spending_breakdown.operating.value, '4000.00');
  assert.equal('private_source_ids' in decoded.overview.spending_breakdown, false);
  assert.throws(() => optionsResponse({ ...options, leadership_version: 1 }, identity));
  for (const mutate of [(r: any) => r.leadership_version = 1, (r: any) => delete r.overview.spending_breakdown,
    (r: any) => r.overview.spending_breakdown.operating.value = 4]) {
    const invalid = validReport(); mutate(invalid);
    assert.throws(() => reportResponse(invalid, { month: '2026-10', period: 'month' }, opts));
  }
});
test('strict wire decoder preserves server decimals/displays and strips unknown data', () => {
  const raw = validReport(); (raw as any).private_source_ids = [77];
  const result = reportResponse(raw, { month: '2026-10', period: 'month' }, optionsResponse(options, identity));
  assert.equal(result.overview.sales.value, '123456.78'); assert.equal(result.overview.sales.display, '123,456.78'); assert.equal('private_source_ids' in result, false);
  assert.equal(result.overview.current_month.sales.value, '999.99'); assert.equal(result.previous_calendar.days.length, 30);
});

test('all-company options cannot silently omit any verified authorized company', () => {
  assert.throws(() => optionsResponse({ ...options, companies: options.companies.slice(0, 1) }, identity), { code: 'invalid_response' });
  assert.equal(optionsResponse(options, identity).companies.length, identity.companyIds.length);
  assert.equal(optionsResponse({ ...options, can_view: false, companies: [] }, identity).can_view, false);
});
test('wire fails closed for wrong company/filter/decimal/day, unavailable mismatch and size', () => {
  for (const mutate of [(r: any) => r.companies.pop(), (r: any) => r.company_id = 99, (r: any) => r.filters.from = '2026-10-02', (r: any) => r.overview.sales.value = 12, (r: any) => r.overview.sales.value = '1e3', (r: any) => r.overview.sales.display = '١٢', (r: any) => r.calendar.days[0].date = '2026-10-02', (r: any) => r.calendar.days.pop(), (r: any) => r.calendar.weekdays[0].weekday = 1, (r: any) => r.overview.sales.available = false, (r: any) => r.extra = 'x'.repeat(1048576)]) {
    const raw = validReport(); mutate(raw); assert.throws(() => reportResponse(raw, { month: '2026-10', period: 'month' }, optionsResponse(options, identity)));
  }
});
test('preset and independent current-month bounds use server as_of in Riyadh, not chart or device dates', () => {
  const opts = optionsResponse(options, identity);
  for (const period of ['today', 'yesterday'] as const) {
    const correct = period === 'today' ? '2026-10-19' : '2026-10-18', raw = validReport(undefined, '2026-09', period, correct);
    assert.equal(reportResponse(raw, { month: '2026-09', period }, opts).filters.from, correct);
    raw.filters.from = raw.filters.to = '2026-09-18'; assert.throws(() => reportResponse(raw, { month: '2026-09', period }, opts));
  }
  const raw = validReport(undefined, '2026-09'); raw.overview.current_month.month = '2026-09'; raw.overview.current_month.from = '2026-09-01'; raw.overview.current_month.to = '2026-09-18';
  assert.throws(() => reportResponse(raw, { month: '2026-09', period: 'month' }, opts));
  const boundary = validReport(undefined, '1900-01'); assert.equal(reportResponse(boundary, { month: '1900-01', period: 'month' }, opts).previous_calendar.month, '1899-12');
});
test('more than10 options remain selectable but all-company reads are blocked before transport', async () => {
  const many = { ...identity, companyIds: Array.from({ length: 11 }, (_, i) => i + 1) }, opts = { ...options, companies: many.companyIds.map(id => ({ id, name: `Company ${id}` })) }; let reads = 0;
  const engine = new LeadershipEngine({ identityScope: () => many, transport: { request: async req => { if (req.path.endsWith('options')) return opts; reads++; return validReport(1); } } });
  assert.equal((await engine.options()).companies.length, 11); await assert.rejects(engine.read({ month: '2026-10', period: 'month' }), { code: 'company_limit' }); assert.equal(reads, 0);
  assert.equal((await engine.read({ month: '2026-10', period: 'month', companyId: 1 })).company_id, 1);
});
test('engine requires verified scope/options and rejects unauthorized company without transport', async () => {
  let current = { ...identity }, requests = 0;
  const engine = new LeadershipEngine({ identityScope: () => current, transport: { request: async req => { requests++; return req.path.endsWith('options') ? options : validReport(); } } });
  await assert.rejects(engine.read({ month: '2026-10', period: 'month' }), { code: 'server_update_required' }); assert.equal(requests, 0);
  await engine.options(); await assert.rejects(engine.read({ month: '2026-10', period: 'month', companyId: 99 }), { code: 'forbidden' }); assert.equal(requests, 1);
  current = { ...current, verified: false }; await assert.rejects(engine.options(), { code: 'unauthorized' }); assert.equal(requests, 1);
});
test('filter and identity cancellation reject responses even if transport ignores abort', async () => {
  let current = { ...identity }; const waits = [waiting(), waiting()]; let index = 0;
  const engine = new LeadershipEngine({ identityScope: () => current, transport: { request: async req => req.path.endsWith('options') ? options : waits[index++].promise } });
  await engine.options(); const old = engine.read({ month: '2026-10', period: 'month' }); const rejected = assert.rejects(old, { code: 'stale' });
  const next = engine.read({ month: '2026-09', period: 'month' }); waits[0].resolve(validReport()); await rejected; waits[1].resolve(validReport(undefined, '2026-09')); await next;
  const another = waiting(); const other = new LeadershipEngine({ identityScope: () => current, transport: { request: async req => req.path.endsWith('options') ? options : another.promise } });
  await other.options(); const stale = other.read({ month: '2026-10', period: 'month' }); const check = assert.rejects(stale, { code: 'stale' }); current = { ...current, epoch: 2, companyIds: [1] }; another.resolve(validReport()); await check;
  await assert.rejects(other.read({ month: '2026-10', period: 'month' }), { code: 'server_update_required' });
});
test('403 clears options and prevents any retained read until fresh options authorization', async () => {
  let denied = false, revoked = 0, requests = 0;
  const engine = new LeadershipEngine({ identityScope: () => identity, onForbidden: () => revoked++, transport: { request: async req => { requests++; if (req.path.endsWith('options')) return options; if (denied) throw { status: 403 }; return validReport(); } } });
  await engine.options(); await engine.read({ month: '2026-10', period: 'month' }); denied = true;
  await assert.rejects(engine.read({ month: '2026-10', period: 'month' }), { code: 'forbidden' }); assert.equal(revoked, 1); const count = requests;
  await assert.rejects(engine.read({ month: '2026-10', period: 'month' }), { code: 'forbidden' }); assert.equal(requests, count);
});

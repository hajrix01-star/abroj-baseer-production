const { test } = require('node:test'), assert = require('node:assert/strict');
const { harness, nodes, one, byId, text } = require('./leadership-harness.cjs');
const waiting = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

test('percentages show their unit and sign with semantic colors without changing server amounts', async () => {
  const app = harness(), base = app.engine.read;
  app.engine.read = async q => { const r = await base(q); r.overview.current_month.spending_change = app.fixtures.money('9.00'); r.overview.current_month.difference_change = app.fixtures.money('-3.00'); return r; };
  const metric = (tree, value) => one(tree, 'Text', p => [p.children].flat().includes(value));
  try {
    await app.flush();
    assert.equal(metric(app.render(), '+8.00%').style.color, '#167447');
    assert.equal(metric(app.render(), '+9.00%').style.color, '#a12a32');
    assert.equal(metric(app.render(), '-3.00%').style.color, '#a12a32');
    assert.equal(metric(app.render(), '16.20%').style.color, '#101b36');
    assert.match(text(app.render()), /123,456.78/);
    app.engine.read = async q => { const r = await base(q); r.overview.current_month.sales_change = app.fixtures.unavailable(); r.overview.current_month.spending_change = app.fixtures.money('-2.00'); r.overview.current_month.difference_change = app.fixtures.money('0.00'); return r; };
    await app.act(() => one(app.render(), 'IconButton', p => p.label === 'Refresh').onPress());
    assert.equal(metric(app.render(), '-2.00%').style.color, '#167447');
    assert.equal(metric(app.render(), '0.00%').style.color, '#101b36');
    assert.doesNotMatch(text(app.render()), /—%/);
  } finally { await app.unmount(); }
});
test('overview defaults to all with adjacent three cards and server values; heat tab has no repeated cards', async () => {
  const app = harness(); try { await app.flush(); const query = app.calls.find(c => c[0] === 'read')[1]; assert.equal(query.companyId, undefined); assert.equal(query.period, 'month');
    assert.ok(byId(app.render(), 'leadership-company-0')); assert.ok(byId(app.render(), 'leadership-company-1'));
    assert.equal(nodes(app.render()).filter(n => /leadership-card-/.test(n.props.testID || '')).length, 3);
    assert.match(text(app.render()), /123,456.78/); assert.match(text(app.render()), /200.00/); assert.match(text(app.render()), /9000.00/); assert.equal(nodes(app.render()).some(n => n.props.testID === 'leadership-current-month'), false);
    await app.act(() => byId(app.render(), 'leadership-card-spending').onPress()); assert.match(text(app.render()), /Posted supplier bills and credits/); await app.act(() => one(app.render(), 'Sheet').close());
    await app.act(() => byId(app.render(), 'leadership-card-sales').onPress()); assert.ok(one(app.render(), 'Sheet')); assert.match(text(app.render()), /Previous sales/);
    await app.act(() => one(app.render(), 'Sheet').close()); await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress());
    assert.equal(nodes(app.render()).some(n => n.props.testID === 'leadership-three-cards'), false); assert.ok(byId(app.render(), 'leadership-heatmap')); assert.equal(byId(app.render(), 'leadership-weekday-averages').accessibilityLabel, 'Positive completed days only');
    await app.act(() => byId(app.render(), `leadership-day-${query.month}-01`).onPress()); assert.match(text(app.render()), /Central target/); assert.match(text(app.render()), /All companies complete/);
  } finally { await app.unmount(); }
});
test('one company is automatic, month/date controls send server filters and current month remains independent', async () => {
  const app = harness(); app.options.companies = [app.options.companies[0]]; app.props.identity.company_ids = [1];
  try { await app.flush(); assert.equal(nodes(app.render()).some(n => n.type === 'CompanySelector'), false); assert.equal(app.calls.find(c => c[0] === 'read')[1].companyId, 1);
    await app.act(() => byId(app.render(), 'leadership-month').onChange('2026-09-10T12:00:00Z')); assert.equal(app.calls.filter(c => c[0] === 'read').at(-1)[1].month, '2026-09');
    await app.act(() => byId(app.render(), 'leadership-card-sales').onPress()); assert.match(text(app.render()), /2026-10/); assert.match(text(app.render()), /999.99/); await app.act(() => one(app.render(), 'Sheet').close());
    await app.act(() => byId(app.render(), 'leadership-period-date').onPress()); await app.act(() => byId(app.render(), 'leadership-date').onChange('2026-09-12T12:00:00Z'));
    const q = app.calls.filter(c => c[0] === 'read').at(-1)[1]; assert.equal(q.date, '2026-09-12'); assert.equal(q.period, 'date');
  } finally { await app.unmount(); }
});
test('silent refresh retains same report; changed scope cannot show late old report; denial clears values', async () => {
  const app = harness(); try { await app.flush(); const oldMonth = app.calls.find(c => c[0] === 'read')[1].month;
    const old = waiting(); app.engine.read = async q => { app.calls.push(['read', q]); return old.promise; };
    await app.act(() => one(app.render(), 'IconButton', p => p.label === 'Refresh').onPress()); assert.match(text(app.render()), /123,456.78/);
    const next = waiting(); app.engine.read = async q => { app.calls.push(['read', q]); return next.promise; };
    await app.act(() => byId(app.render(), 'leadership-company-1').onPress()); assert.doesNotMatch(text(app.render()), /123,456.78/);
    await app.act(() => old.resolve(app.fixtures.report(undefined, oldMonth, 'yesterday'))); assert.doesNotMatch(text(app.render()), /123,456.78/);
    await app.act(() => next.resolve(app.fixtures.report(1, oldMonth, 'yesterday'))); assert.match(text(app.render()), /123,456.78/);
    app.engine.read = async () => { throw { status: 403, code: 'forbidden' }; };
    await app.act(() => one(app.render(), 'IconButton', p => p.label === 'Refresh').onPress()); assert.doesNotMatch(text(app.render()), /123,456.78/); assert.ok(app.calls.some(c => c[0] === 'clear'));
  } finally { await app.unmount(); }
});
test('hidden and revoked states expose no financial children and do not read; AR uses RTL with English server digits', async () => {
  const app = harness({ language: 'ar' }); try { await app.flush(); assert.match(text(app.render()), /نظرة الإدارة/); assert.match(text(app.render()), /123,456.78/);
    assert.ok(nodes(app.render()).some(n => n.type === 'Text' && Array.isArray(n.props.style) && n.props.style.some(s => s?.writingDirection === 'rtl')));
    await app.act(() => byId(app.render(), 'leadership-card-sales').onPress()); app.props.presented = false; await app.flush(); assert.ok(byId(app.render(), 'leadership-privacy-cover')); assert.doesNotMatch(text(app.render()), /123,456.78/); assert.equal(nodes(app.render()).some(n => n.type === 'Sheet'), false);
    app.props.presented = true; app.props.identity = { ...app.props.identity, permissions: { ...app.props.identity.permissions, dashboard_view: false, revision: 2 } }; const count = app.calls.filter(c => ['read', 'options'].includes(c[0])).length; await app.flush(); assert.equal(app.calls.filter(c => ['read', 'options'].includes(c[0])).length, count); assert.doesNotMatch(text(app.render()), /123,456.78/);
  } finally { await app.unmount(); }
});
test('server zero, missing, partial and future labels stay distinct and unavailable never becomes zero', async () => {
  const app = harness(); const base = app.engine.read;
  app.engine.read = async q => { const r = await base(q); const days = r.calendar.days;
    Object.assign(days[0], { sales: app.fixtures.money('0.00'), status_label: 'Recorded zero', status: 'complete' });
    Object.assign(days[1], { sales: app.fixtures.unavailable(), has_sales: false, status_label: 'Missing', status: 'missing' });
    Object.assign(days[2], { status_label: 'Incomplete', status: 'incomplete' }); Object.assign(days[20], { status_label: 'English future evidence', status: 'incomplete' }); return r; };
  try { await app.flush(); await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress()); const month = app.calls.find(c => c[0] === 'read')[1].month;
    const zero = byId(app.render(), `leadership-day-${month}-01`), missing = byId(app.render(), `leadership-day-${month}-02`); assert.match(zero.accessibilityLabel, /0.00, Recorded zero/); assert.match(missing.accessibilityLabel, /—, Missing/);
    assert.notEqual(zero.style[1].backgroundColor, missing.style[1].backgroundColor); assert.match(byId(app.render(), `leadership-day-${month}-03`).accessibilityLabel, /Incomplete/); assert.match(byId(app.render(), `leadership-day-${month}-21`).accessibilityLabel, /Future/);
  } finally { await app.unmount(); }
});
test('same-actor return retains pixels while options verify, disables actions, and clears on denied verification', async () => {
  const app = harness(); try { await app.flush(); const oldCard = byId(app.render(), 'leadership-card-sales').onPress;
    app.props.presented = false; await app.flush(); assert.doesNotMatch(text(app.render()), /123,456.78/);
    const held = waiting(); app.engine.options = async () => { app.calls.push(['options']); return held.promise; };
    app.props.presented = true; await app.flush(); assert.match(text(app.render()), /123,456.78/); assert.equal(byId(app.render(), 'leadership-card-sales').disabled, true); assert.equal(byId(app.render(), 'leadership-company-1').disabled, true);
    const count = app.calls.filter(c => c[0] === 'read').length; await app.act(() => { oldCard(); byId(app.render(), 'leadership-period-today').onPress(); });
    assert.equal(nodes(app.render()).some(n => n.type === 'Sheet'), false); assert.equal(app.calls.filter(c => c[0] === 'read').length, count);
    await app.act(() => held.reject({ status: 403, code: 'forbidden' })); assert.doesNotMatch(text(app.render()), /123,456.78/);
  } finally { await app.unmount(); }
});
test('Arabic presentation never echoes English server prose or weekdays and leaves server amounts unchanged', async () => {
  const app = harness({ language: 'ar' }); try { await app.flush(); await app.act(() => byId(app.render(), 'leadership-card-spending').onPress());
    assert.match(text(app.render()), /فواتير الموردين/); assert.doesNotMatch(text(app.render()), /Gross signed|Posted supplier|credits/); await app.act(() => one(app.render(), 'Sheet').close());
    await app.act(() => byId(app.render(), 'leadership-card-sales').onPress()); assert.doesNotMatch(text(app.render()), /Completed October|September/); await app.act(() => one(app.render(), 'Sheet').close());
    await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress()); const month = app.calls.find(c => c[0] === 'read')[1].month;
    await app.act(() => byId(app.render(), `leadership-day-${month}-01`).onPress()); assert.match(text(app.render()), /مكتمل/); assert.match(text(app.render()), /100.00/);
    const allLabels = nodes(app.render()).map(n => n.props.accessibilityLabel || '').join(' '); assert.doesNotMatch(text(app.render()) + allLabels, /All companies complete|Completed|Mon|Tue|Wed|Thu|Fri|Sat|Sun/);
  } finally { await app.unmount(); }
});
test('blue path excludes current/future/incomplete days, grey preserves full prior month, signed refunds remain negative in detail', async () => {
  const app = harness(); app.engine.read = async q => {
    const r = app.fixtures.report(q.companyId, '2026-10', 'month'); app.calls.push(['read', q]);
    r.calendar.days.forEach((d, i) => { d.status = i < 18 ? 'complete' : 'incomplete'; });
    r.calendar.days[2].sales = app.fixtures.money('-25.00'); r.calendar.days[4].status = 'incomplete'; return r;
  };
  try { await app.flush(); const paths = nodes(app.render()).filter(n => n.type === 'Path'), actual = paths.find(n => n.props.strokeWidth === 2.5).props.d, previous = paths.find(n => n.props.strokeWidth === 1.5).props.d;
    assert.equal((actual.match(/[ML]/g) || []).length, 17); assert.equal((previous.match(/[ML]/g) || []).length, 30); assert.equal((actual.match(/M/g) || []).length, 2);
    await app.act(() => byId(app.render(), 'leadership-inspect-3').onPress()); assert.match(text(app.render()), /-25.00/);
  } finally { await app.unmount(); }
});

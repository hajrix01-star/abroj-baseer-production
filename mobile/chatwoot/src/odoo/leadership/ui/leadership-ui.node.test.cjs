const { test } = require('node:test'), assert = require('node:assert/strict');
const { harness, nodes, one, byId, text } = require('./leadership-harness.cjs');
const waiting = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

test('offline leadership keeps readonly cards and details without new warning time or live-day claims', async () => {
  for (const language of ['ar', 'en']) {
    const app = harness({ language, online: false }); app.engine.displayLeaseRemainingMs = Infinity;
    try {
      await app.flush(); assert.match(text(app.render()), /123,456.78/);
      await app.act(() => byId(app.render(), 'leadership-card-sales').onPress()); assert.ok(one(app.render(), 'Sheet'));
      await app.act(() => one(app.render(), 'Sheet').close());
      await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress());
      assert.equal(nodes(app.render()).some(n => /leadership-day-live-/.test(n.props.testID || '')), false);
      const day = byId(app.render(), 'leadership-day-2026-10-19');
      assert.doesNotMatch(day.accessibilityLabel, /In progress|Live|جارٍ/);
      assert.notEqual(day.style[1].borderColor, '#1256da');
      await app.act(() => day.onPress());
      assert.match(text(app.render()), /100.00/); assert.doesNotMatch(text(app.render()), /In progress|Live|جارٍ|Updated|آخر تحديث/);
      assert.equal(nodes(app.render()).some(n => n.props.testID === 'leadership-warning'), false);
    } finally { await app.unmount(); }
  }
});

test('reconnection verifies silently and does not revive live styling before a fresh server report', async () => {
  const app = harness({ online: false }); app.engine.displayLeaseRemainingMs = Infinity;
  try {
    await app.flush(); await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress());
    const held = waiting(); app.engine.options = async () => held.promise;
    app.props.online = true; await app.flush();
    assert.match(text(app.render()), /100/); assert.equal(byId(app.render(), 'leadership-day-2026-10-19').disabled, true);
    assert.equal(nodes(app.render()).some(n => /leadership-day-live-/.test(n.props.testID || '')), false);
    await app.act(() => held.resolve(app.options));
    assert.ok(byId(app.render(), 'leadership-day-live-2026-10-19'));
    assert.equal(byId(app.render(), 'leadership-day-2026-10-19').disabled, false);
  } finally { await app.unmount(); }
});

test('an unavailable offline filter clears prior values rather than displaying zero or another scope', async () => {
  const app = harness({ online: false }); app.engine.displayLeaseRemainingMs = Infinity;
  try {
    await app.flush(); app.engine.read = async () => { throw { code: 'snapshot_unavailable' }; };
    await app.act(() => byId(app.render(), 'leadership-company-1').onPress());
    assert.doesNotMatch(text(app.render()), /123,456.78/); assert.match(text(app.render()), /Unavailable/);
  } finally { await app.unmount(); }
});

test('cached financial pixels and open details disappear at their display lease deadline', async () => {
  const app = harness({ online: false }); app.engine.displayLeaseRemainingMs = 40;
  try {
    await app.flush(); await app.act(() => byId(app.render(), 'leadership-card-sales').onPress());
    assert.match(text(app.render()), /123,456.78/);
    await app.act(() => new Promise(resolve => setTimeout(resolve, 60)));
    assert.doesNotMatch(text(app.render()), /123,456.78/);
    assert.equal(nodes(app.render()).some(n => n.type === 'Sheet'), false);
  } finally { await app.unmount(); }
});

test('calendar integer display rounds upward exactly while original decimal details stay unchanged in either language', async () => {
  for (const language of ['en', 'ar']) {
    const app = harness({ language });
    const displays = ['7,000.00', '1,234,567.89', '-25,000.75', '0.00', '—'];
    const visible = ['7,000', '1,234,568', '-25,000', '0', '—'];
    let source, sourceSnapshot;
    app.engine.read = async q => {
      const r = app.fixtures.report(q.companyId, '2026-10', 'month');
      ['7000.00', '1234567.89', '-25000.75', '0.00'].forEach((value, i) => {
        r.calendar.days[i].sales = { ...app.fixtures.money(value), display: displays[i] };
      });
      Object.assign(r.calendar.days[4], { has_sales: false, sales: app.fixtures.unavailable(), status: 'missing' });
      r.calendar.weekdays[5].average = app.fixtures.money('1234567.89');
      source = r; sourceSnapshot = JSON.stringify(r);
      return r;
    };
    try {
      await app.flush(); await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress());
      for (const width of [270, 710]) {
        await app.act(() => byId(app.render(), 'leadership-heatmap').onLayout({ nativeEvent: { layout: { width } } }));
        for (let i = 0; i < displays.length; i++) {
          const date = `2026-10-0${i + 1}`, amount = byId(app.render(), `leadership-day-sales-${date}`);
          assert.equal(text({ type: 'Text', props: amount }).replace(/\u200b/g, ''), visible[i]);
          assert.doesNotMatch(text({ type: 'Text', props: amount }), /\./);
          assert.equal(amount.numberOfLines, undefined); assert.equal(amount.adjustsFontSizeToFit, undefined);
          assert.equal(amount.style[1].fontSize, width < 420 ? 10 : 12);
          assert.equal(amount.style[0].writingDirection, 'ltr');
          assert.ok(byId(app.render(), `leadership-day-${date}`).accessibilityLabel.includes(visible[i]));
        }
      }
      await app.act(() => byId(app.render(), 'leadership-day-2026-10-03').onPress());
      assert.match(text(app.render()), /-25,000.75/);
      assert.equal(JSON.stringify(source), sourceSnapshot, 'presentation never mutates original decimal amounts, totals or comparisons');
      byId(app.render(), 'leadership-weekday-averages').children.forEach((header, index) => {
        const average = one(header, 'Text', p => p.style?.fontWeight === '700');
        assert.equal(text({ type: 'Text', props: average }).replace(/\u200b/g, ''), index === 0 ? '1,234,568' : '102');
        assert.equal(average.numberOfLines, undefined); assert.equal(average.adjustsFontSizeToFit, undefined);
        assert.equal(average.style.fontSize, 11);
      });
    } finally { await app.unmount(); }
  }
});

test('calendar ceil formatter preserves decimal precision, carry, signed refunds and unavailable without Number rounding', () => {
  const { presentation, fixtures } = harness();
  const cases = [
    ['53.10', '54'], ['53.90', '54'], ['53.00', '53'], ['53', '53'],
    ['999.01', '1,000'], ['999999.99', '1,000,000'], ['0.00', '0'],
    ['0.0000000000000001', '1'], ['-0.0000000000000001', '0'], ['-0.00', '0'],
    ['-53.10', '-53'], ['-53.00', '-53'], ['-25000.75', '-25,000'],
    ['9007199254740992.01', '9,007,199,254,740,993'],
    ['999999999999999999999999999999.01', '1,000,000,000,000,000,000,000,000,000,000'],
  ];
  for (const [value, expected] of cases) {
    const amount = Object.freeze(fixtures.money(value));
    assert.equal(presentation.calendarIntegerDisplay(amount), expected, value);
    assert.equal(amount.value, value);
  }
  assert.equal(presentation.calendarIntegerDisplay(fixtures.unavailable()), '—');
  assert.equal(presentation.calendarIntegerDisplay(undefined), '—');
});

test('compact calendar gains side space without horizontal scrolling and selected-day details remain outside its card', async () => {
  for (const language of ['ar', 'en']) {
    const app = harness({ language });
    try {
      await app.flush();
      const basePadding = byId(app.render(), 'leadership-scroll').contentContainerStyle[0].padding;
      await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress());
      const scroll = byId(app.render(), 'leadership-scroll');
      assert.equal(scroll.contentContainerStyle[1].paddingHorizontal, 6);
      assert.ok(scroll.contentContainerStyle[1].paddingHorizontal < basePadding);
      assert.equal(byId(app.render(), 'leadership-calendar-panel').style[1].paddingHorizontal, 6);
      assert.equal(nodes(app.render()).some(n => n.type === 'ScrollView' && n.props.horizontal), false);
      await app.act(() => byId(app.render(), 'leadership-day-2026-10-01').onPress());
      assert.ok(byId(app.render(), 'leadership-day-detail'));
      assert.equal(nodes({type:'View', props:byId(app.render(), 'leadership-calendar-panel')}).some(n => n.props.testID === 'leadership-day-detail'), false);
    } finally { await app.unmount(); }
  }
});

test('only the Riyadh snapshot day is live and blue, even without sales, without masking other day evidence', async () => {
  for (const language of ['en', 'ar']) {
    const app = harness({ language }); let hasSales = true;
    app.engine.read = async q => {
      const r = app.fixtures.report(q.companyId, '2026-10', 'month');
      // UTC date is the 18th, but the server business date in Riyadh is the 19th.
      r.as_of = '2026-10-18T22:30:00Z';
      Object.assign(r.calendar.days[17], { status: 'incomplete' });
      if (!hasSales) Object.assign(r.calendar.days[18], { has_sales: false, sales: app.fixtures.unavailable(), status: 'missing' });
      return r;
    };
    try {
      await app.flush(); await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress());
      for (const present of [true, false]) {
        if (!present) {
          hasSales = false;
          await app.act(() => one(app.render(), 'IconButton', p => p.label === (language === 'ar' ? 'تحديث' : 'Refresh')).onPress());
        }
        const day = byId(app.render(), 'leadership-day-2026-10-19');
        assert.equal(day.style[1].borderColor, '#1256da');
        assert.equal(day.style[1].borderStyle, 'solid');
        assert.match(day.accessibilityLabel, language === 'ar' ? /جارٍ/ : /In progress/);
        assert.match(text({ type: 'View', props: day }), language === 'ar' ? /جارٍ/ : /Live/);
        assert.ok(nodes(app.render()).filter(n => /^leadership-day-live-/.test(n.props.testID || '')).length === 1);
        assert.match(byId(app.render(), 'leadership-day-2026-10-18').accessibilityLabel, language === 'ar' ? /غير مكتمل/ : /Incomplete/);
        assert.match(byId(app.render(), 'leadership-day-2026-10-20').accessibilityLabel, language === 'ar' ? /مستقبلي/ : /Future/);
        if (!present) assert.match(day.accessibilityLabel, /—/);
      }
      await app.act(() => byId(app.render(), 'leadership-day-2026-10-19').onPress());
      assert.match(text(app.render()), language === 'ar' ? /جارٍ/ : /In progress/);
    } finally { await app.unmount(); }
  }
});

test('calendar weeks always contain seven equal slots aligned with centered weekday averages', async () => {
  for (const language of ['en', 'ar']) {
    const app = harness({ language });
    app.engine.read = async q => app.fixtures.report(q.companyId, '2026-10', 'month');
    try {
      await app.flush();
      await app.act(() => byId(app.render(), 'leadership-tab-heatmap').onPress());
      const weeks = nodes(app.render()).filter(n => /^leadership-week-\d+$/.test(n.props.testID || ''));
      assert.equal(weeks.length, 6);
      for (const week of weeks) {
        assert.equal(week.props.style.flexDirection, 'row');
        assert.notEqual(week.props.style.flexWrap, 'wrap');
        const slots = week.props.children;
        assert.equal(slots.length, 7);
        slots.forEach(slot => { assert.equal(slot.props.style.flex, 1); assert.equal(slot.props.style.minWidth, 0); assert.equal(slot.props.style.width, undefined); });
      }
      assert.equal(one(weeks[0].props.children[5], 'Pressable').testID, 'leadership-day-2026-10-01');
      assert.equal(one(weeks[0].props.children[6], 'Pressable').testID, 'leadership-day-2026-10-02');
      assert.equal(one(weeks[1].props.children[0], 'Pressable').testID, 'leadership-day-2026-10-03');
      const headers = byId(app.render(), 'leadership-weekday-averages');
      assert.equal(headers.children.length, 7);
      assert.equal(headers.style.gap || 0, 0);
      headers.children.forEach(header => {
        const average = nodes(header).find(n => n.type === 'Text' && n.props.style?.fontWeight === '700');
        assert.ok(average);
        assert.equal(average.props.style.textAlign, 'center');
        assert.equal(average.props.style.alignSelf, 'stretch');
      });
    } finally { await app.unmount(); }
  }
});

test('chart drawing and day inspection share the full touch width in both languages', async () => {
  for (const language of ['en', 'ar']) {
    const app = harness({ language });
    app.engine.read = async q => { app.calls.push(['read', q]); return app.fixtures.report(q.companyId, '2026-10', 'month'); };
    try {
      await app.flush();
      // Native SVG otherwise defaults to a centered `meet` viewBox, while
      // locationX spans the entire Pressable. Host doubles cannot render that
      // mismatch: bind its explicit drawing policy as well as its hit mapping.
      assert.equal(one(app.render(), 'Svg').preserveAspectRatio, 'none');
      const reads = app.calls.filter(c => c[0] === 'read').length;
      for (const width of [246, 710]) {
        await app.act(() => byId(app.render(), 'leadership-chart').onLayout({ nativeEvent: { layout: { width } } }));
        for (const day of [1, 3, 6, 18, 31]) {
          const locationX = (14 + (day - 1) * 292 / 30) * width / 320;
          await app.act(() => byId(app.render(), 'leadership-chart').onPress({ nativeEvent: { locationX } }));
          assert.match(text(app.render()), new RegExp(`2026-10-${String(day).padStart(2, '0')}`));
        }
      }
      assert.equal(app.calls.filter(c => c[0] === 'read').length, reads);
    } finally { await app.unmount(); }
  }
});

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
    const zero = byId(app.render(), `leadership-day-${month}-01`), missing = byId(app.render(), `leadership-day-${month}-02`); assert.match(zero.accessibilityLabel, /0, Recorded zero/); assert.match(missing.accessibilityLabel, /—, Missing/);
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

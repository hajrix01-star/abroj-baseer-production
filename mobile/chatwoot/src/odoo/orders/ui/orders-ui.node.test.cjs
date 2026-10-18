const assert = require('node:assert/strict');
const { test } = require('node:test');
const { harness, nodes, one, text, byId, button } = require('./orders-harness.cjs');

async function ready(initial) { const app = harness(initial); await app.flush(); return app; }
function choose(app, id, value) { byId(app.render(), id).onPress(); byId(app.render(), `${id}-option-${value}`).onPress(); }
async function cart(app) {
  one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress();
  button(app.render(), 'Review cart (1)').onPress();
  button(app.render(), 'Get Odoo quote').onPress(); await app.flush();
}
async function receipt(app) {
  byId(app.render(), 'orders-tab-receiving').onPress(); await app.flush();
  byId(app.render(), 'receipt-row-12').onPress(); await app.flush();
}
const waiting = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

test('real orders screen honors view/create/receive separately, including orders-only users', async () => {
  const app = await ready();
  assert.ok(byId(app.render(), 'catalog-search'));
  assert.equal(app.calls.filter(call => call[0] === 'catalog').length, 1);
  assert.equal(app.props.identity.permissions.chat_view, false);
  for (const permission of ['view', 'receive', 'none']) {
    const next = harness();
    next.options.can_create = false; next.options.can_receive = permission === 'receive';
    next.props.identity.permissions = { order_view: permission !== 'none', order_create: false, order_receive: permission === 'receive', chat_view: false };
    await next.flush();
    assert.equal(nodes(next.render()).some(node => node.props.testID === 'orders-tab-catalog'), false);
    assert.equal(nodes(next.render()).some(node => node.props.testID === 'orders-tab-receiving'), permission === 'receive');
    assert.equal(next.calls.some(call => call[0] === 'catalog'), false);
    assert.equal(next.calls.some(call => call[0] === 'options' && call[1] !== undefined), false, 'receive-only never needs create options');
  }
});

test('catalog debounces search, keeps option identity/unit, and discards earlier query responses', async () => {
  const app = await ready(), older = waiting(), newer = waiting();
  const calls = [];
  app.engine.catalog = async (company, query) => { calls.push(query); return query.q === 'older' ? older.promise : newer.promise; };
  byId(app.render(), 'catalog-search').onChangeText('o'); app.render();
  byId(app.render(), 'catalog-search').onChangeText('older'); app.render();
  assert.equal(calls.length, 0);
  await app.flush(); assert.equal(calls.length, 1);
  byId(app.render(), 'catalog-search').onChangeText('newer'); await app.flush();
  newer.resolve({ items: [{ ...app.item, product_name: 'Current product' }], next_after_id: null }); await app.flush();
  older.resolve({ items: [{ ...app.item, product_name: 'Old product' }], next_after_id: null }); await app.flush();
  assert.ok(text(app.render()).includes('Current product'));
  assert.equal(text(app.render()).includes('Old product'), false);
  assert.ok(text(app.render()).includes('Case · Box'));
});

test('quote values come directly from Odoo, cart edits invalidate them, and create requires a review', async () => {
  const app = await ready(); await cart(app);
  assert.ok(text(app.render()).includes('991.73 SAR'));
  assert.equal(app.calls.some(call => call[0] === 'create'), false);
  const quoteInput = app.calls.find(call => call[0] === 'quote')[1];
  assert.deepEqual(JSON.parse(JSON.stringify(quoteInput.lines)), [{ option_id: 81, quantity: '1' }]);
  byId(app.render(), 'cart-quantity-81').onChangeText('3.5');
  assert.equal(text(app.render()).includes('991.73 SAR'), false);
  assert.equal(button(app.render(), 'Review order').disabled, true);
  button(app.render(), 'Get Odoo quote').onPress(); await app.flush();
  button(app.render(), 'Review order').onPress();
  assert.ok(button(app.render(), 'Submit order'));
  assert.equal(app.calls.some(call => call[0] === 'create'), false);
  const submit = button(app.render(), 'Submit order'); submit.onPress(); submit.onPress(); await app.flush();
  const writes = app.calls.filter(call => call[0] === 'create'); assert.equal(writes.length, 1);
  assert.equal(writes[0][1].company_id, 1); assert.equal(writes[0][1].representative_partner_id, 9);
  assert.equal('room_id' in writes[0][1], false, 'no-room intent is omitted rather than fabricated');
});

test('changing operation company clears the cart immediately and retained old actions cannot write', async () => {
  const app = await ready(); await cart(app);
  button(app.render(), 'Review order').onPress(); const staleSubmit = button(app.render(), 'Submit order').onPress;
  choose(app, 'orders-company', 2); const next = app.render();
  staleSubmit(); await app.flush();
  assert.equal(app.calls.some(call => call[0] === 'create'), false);
  assert.equal(text(next).includes('991.73'), false);
  assert.equal(nodes(app.render()).some(node => node.props.title === 'Review cart (1)'), false);
  assert.ok(button(app.render(), 'Review cart (0)'));
  assert.equal(app.calls.filter(call => call[0] === 'catalog').at(-1)[1], 2);
});

test('offline and account/permission changes hide all old order data and actions', async () => {
  const app = await ready(); await cart(app);
  button(app.render(), 'Review order').onPress(); const submit = button(app.render(), 'Submit order').onPress;
  app.props.online = false; const tree = app.render(); submit(); await app.flush();
  assert.ok(text(tree).includes('Connect to open orders'));
  assert.equal(text(tree).includes('Fixture product'), false);
  assert.equal(app.calls.some(call => call[0] === 'create'), false);
  assert.ok(app.calls.some(call => call[0] === 'cancelReads'));
  app.props.online = true; app.props.identity = { ...app.props.identity, user_id: 44, permissions: { order_view: false } };
  assert.ok(text(app.render()).includes('No permission to view orders'));
});

test('all-order details use the row company, while list filters stay local and pages are bounded', async () => {
  const app = await ready(); byId(app.render(), 'orders-tab-allOrders').onPress(); await app.flush();
  byId(app.render(), 'orders-row-12').onPress(); await app.flush();
  assert.deepEqual(app.calls.filter(call => call[0] === 'detail').at(-1), ['detail', 2, 12]);
  assert.ok(text(app.render()).includes('Original request values'));
  button(app.render(), 'Back').onPress(); choose(app, 'orders-list-company', 1);
  assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-row-12'), false);
  assert.equal(app.calls.filter(call => call[0] === 'list').length, 1);
  choose(app, 'orders-list-company', 0);
  let page = 0;
  app.engine.list = async () => { page++; return { orders: Array.from({ length: 30 }, (_, i) => app.summary(page * 30 + i, 2)), next_before_id: page * 30 }; };
  button(app.render(), 'Reload').onPress(); await app.flush();
  for (let i = 0; i < 7; i++) { const more = nodes(app.render()).find(node => node.type === 'Button' && node.props.title === 'Load more'); if (more) { more.props.onPress(); await app.flush(); } }
  assert.equal(nodes(app.render()).filter(node => node.props.testID?.startsWith('orders-row-')).length, 200);
  assert.equal(nodes(app.render()).some(node => node.type === 'Button' && node.props.title === 'Load more'), false);
});

test('receipt requires every exact decimal line and a deliberate review; confirm and share are separate', async () => {
  const app = await ready({ rooms: [{ id: 55, company_id: 1, membership_id: 5, name: 'Original room' }] });
  app.props.identity.permissions.chat_send = true; await app.flush(); await receipt(app);
  button(app.render(), 'Review receipt').onPress();
  assert.equal(nodes(app.render()).some(node => node.type === 'Button' && node.props.title === 'Confirm receipt'), false);
  byId(app.render(), 'receipt-price-1').onChangeText('1.234'); byId(app.render(), 'receipt-price-2').onChangeText('2.00');
  button(app.render(), 'Review receipt').onPress();
  assert.equal(nodes(app.render()).some(node => node.type === 'Button' && node.props.title === 'Confirm receipt'), false);
  byId(app.render(), 'receipt-price-1').onChangeText('1.23');
  byId(app.render(), 'receipt-quantity-2').onChangeText('0'); byId(app.render(), 'receipt-price-2').onChangeText('0');
  button(app.render(), 'Review receipt').onPress();
  const review = app.render();
  assert.ok(text(review).includes('Returned by Odoo after confirmation'));
  assert.equal(text(review).includes('2.46'), false, 'no actual total is calculated locally');
  assert.equal(app.calls.some(call => call[0] === 'confirm'), false);
  const confirm = button(review, 'Confirm receipt'); confirm.onPress(); confirm.onPress(); await app.flush();
  const calls = app.calls.filter(call => call[0] === 'confirm'); assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].slice(1))), [12, { company_id: 1, lines: [{ line_id: 1, actual_qty: '2', actual_price: '1.23' }, { line_id: 2, actual_qty: '0', actual_price: '0' }] }, [1, 2]]);
  assert.ok(text(app.render()).includes('831.49 SAR'));
  assert.equal(app.calls.some(call => call[0] === 'share'), false);
  app.engine.share = async (company, id) => { app.calls.push(['share', company, id]); throw new Error('fixture lost response'); };
  button(app.render(), 'Share receipt result').onPress(); await app.flush();
  button(app.render(), 'Share receipt result').onPress(); await app.flush();
  assert.equal(app.calls.filter(call => call[0] === 'share').length, 2);
  assert.equal(app.calls.filter(call => call[0] === 'confirm').length, 1);
});

test('unknown create blocks another create and exposes an explicit saved UUID retry', async () => {
  const app = await ready();
  app.engine.create = async input => { app.calls.push(['create', input]); throw { code: 'unknown', attemptId: 'saved-uuid' }; };
  app.engine.pending = async () => [{ uuid: 'saved-uuid', kind: 'create', companyId: 1, createdAt: 1 }];
  await cart(app); button(app.render(), 'Review order').onPress(); button(app.render(), 'Submit order').onPress(); await app.flush();
  assert.ok(text(app.render()).includes('Result unknown'));
  assert.equal(button(app.render(), 'Submit order').disabled, true);
  assert.equal(app.calls.some(call => call[0] === 'retry'), false);
  button(app.render(), 'Retry saved attempt').onPress(); await app.flush();
  assert.deepEqual(app.calls.filter(call => call[0] === 'retry'), [['retry', 'saved-uuid']]);
  assert.equal(app.calls.filter(call => call[0] === 'create').length, 1);
});

test('AR/EN and 320/900 render the same genuine workflows with ASCII server numbers', async () => {
  for (const language of ['ar', 'en']) for (const width of [320, 900]) {
    const app = await ready({ language }); app.setWidth(width);
    const tree = app.render(); assert.ok(byId(tree, 'catalog-option-81'));
    const option = byId(tree, 'catalog-option-81');
    assert.equal(option.style[1].width, width >= 650 ? '48.8%' : '100%');
    const tabs = nodes(tree).filter(node => node.props.accessibilityRole === 'tab'); assert.equal(tabs.length, 3);
    assert.ok(tabs.every(node => node.props.style[0].minHeight >= 44));
    assert.equal(one(tree, 'KeyboardAvoidingView').behavior, 'height');
    assert.equal(one(tree, 'ScrollView').keyboardShouldPersistTaps, 'handled');
    const dictionary = app.module('../dictionary.ts');
    assert.equal(dictionary.displayNumber('١٢.۳۴'), '12.34');
    assert.equal(dictionary.orderTranslator(language)('cancel').includes('undefined'), false);
  }
});

test('actual React 19 effects mount the workflow, invalidate quotes and clean up old-company writes', async () => {
  const app = harness({}, true);
  try {
    await app.flush();
    assert.ok(byId(app.render(), 'catalog-option-81'));
    await app.act(() => one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress());
    await app.act(() => button(app.render(), 'Review cart (1)').onPress());
    await app.act(() => button(app.render(), 'Get Odoo quote').onPress());
    assert.ok(text(app.render()).includes('991.73 SAR'));
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('٢٫٥'));
    assert.equal(byId(app.render(), 'cart-quantity-81').value, '2.5');
    assert.equal(text(app.render()).includes('991.73 SAR'), false);
    await app.act(() => button(app.render(), 'Get Odoo quote').onPress());
    await app.act(() => button(app.render(), 'Review order').onPress());
    const stale = button(app.render(), 'Submit order').onPress;
    await app.act(() => byId(app.render(), 'orders-company').onPress());
    await app.act(() => byId(app.render(), 'orders-company-option-2').onPress());
    await app.act(() => stale());
    assert.equal(app.calls.some(call => call[0] === 'create'), false);
    assert.ok(button(app.render(), 'Review cart (0)'));
    app.props.online = false; await app.flush();
    assert.ok(text(app.render()).includes('Connect to open orders'));
    assert.ok(app.calls.some(call => call[0] === 'cancelReads'));
  } finally { await app.unmount(); }
});

test('actual React quantity buttons preserve fractional text, reject invalid input and never reduce an upper-bound quantity', async () => {
  const app = harness({}, true);
  try {
    await app.flush();
    await app.act(() => one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress());
    await app.act(() => button(app.render(), 'Review cart (1)').onPress());
    for (const [input, expected] of [['999999.99', '999999.99'], ['999998.99', '999999.99'], ['1.999', '1.999'], ['1.25', '2.25'], ['1.01', '2.01'], ['1.20', '2.20'], ['0.25', '1.25']]) {
      await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText(input));
      await app.act(() => one(app.render(), 'IconButton', p => p.icon === 'plus').onPress());
      assert.equal(byId(app.render(), 'cart-quantity-81').value, expected, `${input} + 1`);
    }
    for (const [input, expected] of [['999999.99', '999998.99'], ['2.25', '1.25'], ['2.01', '1.01'], ['2.20', '1.20'], ['1.25', '0.25'], ['1.999', '1.999']]) {
      await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText(input));
      await app.act(() => button(app.render(), '−').onPress());
      assert.equal(byId(app.render(), 'cart-quantity-81').value, expected, `${input} - 1`);
    }
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('999999.99'));
    await app.act(() => button(app.render(), 'Get Odoo quote').onPress());
    const quoteCount = app.calls.filter(call => call[0] === 'invalidateQuote').length;
    await app.act(() => one(app.render(), 'IconButton', p => p.icon === 'plus').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'invalidateQuote').length, quoteCount, 'a no-op upper-bound press keeps the current quote');
    assert.ok(text(app.render()).includes('991.73 SAR'));
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('1.999'));
    const invalidCount = app.calls.filter(call => call[0] === 'invalidateQuote').length;
    await app.act(() => one(app.render(), 'IconButton', p => p.icon === 'plus').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'invalidateQuote').length, invalidCount, 'invalid input is not rewritten or invalidated again by a no-op press');
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('1.01'));
    await app.act(() => button(app.render(), '−').onPress());
    assert.equal(byId(app.render(), 'cart-quantity-81').value, '0.01');
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('1.00'));
    await app.act(() => button(app.render(), '−').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'cart-quantity-81'), false, 'exact zero removes the cart line');
    assert.ok(text(app.render()).includes('Your cart is empty'));
  } finally { await app.unmount(); }
});

async function confirmWithActualReact(app) {
  await app.flush();
  await app.act(() => byId(app.render(), 'orders-tab-receiving').onPress());
  await app.act(() => byId(app.render(), 'receipt-row-12').onPress());
  for (const id of [1, 2]) await app.act(() => byId(app.render(), `receipt-price-${id}`).onChangeText('1'));
  await app.act(() => button(app.render(), 'Review receipt').onPress());
  await app.act(() => button(app.render(), 'Confirm receipt').onPress());
}

test('actual React orders-only receipt sharing uses authorized order detail with rooms empty and never repeats confirm on 403', async () => {
  const app = harness({ rooms: [] }, true);
  app.props.identity.permissions.chat_send = true;
  app.engine.share = async (company, id) => { app.calls.push(['share', company, id]); throw { code: 'forbidden', status: 403 }; };
  try {
    await confirmWithActualReact(app);
    assert.equal(app.props.identity.permissions.chat_view, false);
    assert.deepEqual(app.props.rooms, []);
    assert.deepEqual(app.calls.filter(call => call[0] === 'detail'), [['detail', 1, 12]]);
    assert.equal(app.calls.filter(call => call[0] === 'share').length, 0, 'detail is read without automatically sharing');
    assert.equal(button(app.render(), 'Share receipt result').disabled, false);
    const share = button(app.render(), 'Share receipt result').onPress;
    await app.act(() => share());
    assert.deepEqual(app.calls.filter(call => call[0] === 'share'), [['share', 1, 12]]);
    assert.equal(button(app.render(), 'Share receipt result').disabled, true);
    await app.act(() => share());
    assert.equal(app.calls.filter(call => call[0] === 'share').length, 1, 'retained sharing action is revoked after 403');
    assert.equal(app.calls.filter(call => call[0] === 'confirm').length, 1, 'membership failure never repeats stock confirmation');
  } finally { await app.unmount(); }
});

test('actual React share stays disabled without chat_send or an original room, and late detail cannot escape an unmounted scope', async () => {
  for (const scenario of ['no-send', 'no-original-room', 'late-detail']) {
    const app = harness({ rooms: [] }, true), delayed = waiting();
    app.props.identity.permissions.chat_send = scenario !== 'no-send';
    if (scenario !== 'no-send') app.engine.detail = async (company, id) => {
      app.calls.push(['detail', company, id]);
      if (scenario === 'late-detail') return delayed.promise;
      return { order: { ...app.summary(id, company), room_id: null }, lines: [] };
    };
    try {
      await confirmWithActualReact(app);
      assert.equal(button(app.render(), 'Share receipt result').disabled, true, scenario);
      assert.equal(app.calls.filter(call => call[0] === 'detail').length, scenario === 'no-send' ? 0 : 1);
      if (scenario === 'late-detail') {
        const stale = button(app.render(), 'Share receipt result').onPress;
        app.props.online = false; await app.flush();
        await app.act(() => delayed.resolve({ order: app.summary(12, 1), lines: [] }));
        await app.act(() => stale());
        assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-write-result'), false);
      }
      assert.equal(app.calls.filter(call => call[0] === 'share').length, 0, scenario);
      assert.equal(app.calls.filter(call => call[0] === 'confirm').length, 1, scenario);
    } finally { await app.unmount(); }
  }
});

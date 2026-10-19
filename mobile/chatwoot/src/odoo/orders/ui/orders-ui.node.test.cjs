const assert = require('node:assert/strict');
const { test } = require('node:test');
const { harness, nodes, one, text, byId, button } = require('./orders-harness.cjs');

async function ready(initial) { const app = harness(initial); await app.flush(); return app; }
function choose(app, id, value) { byId(app.render(), id).onPress(); byId(app.render(), `${id}-option-${value}`).onPress(); }
async function cart(app) {
  one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress();
  button(app.render(), 'Review cart (1)').onPress();
  await app.flush();
}
async function receipt(app) {
  byId(app.render(), 'orders-tab-receiving').onPress(); await app.flush();
  byId(app.render(), 'receipt-row-12').onPress(); await app.flush();
}
const waiting = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

test('orders keyboard avoidance includes the measured shell offset without resetting the cart', async () => {
  const app = await ready();
  one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress(); await app.flush();
  const frame = byId(app.render(), 'orders-workspace-frame');
  frame.ref.current = { measureInWindow: callback => callback(0, 82, 320, 530) };
  frame.onLayout();
  assert.equal(one(app.render(), 'KeyboardAvoidingView').keyboardVerticalOffset, 82);
  assert.equal(byId(app.render(), 'cart-quantity-81').value, '1');
  frame.ref.current = { measureInWindow: callback => callback(0, 24, 320, 588) };
  frame.onLayout();
  assert.equal(one(app.render(), 'KeyboardAvoidingView').keyboardVerticalOffset, 24);
  frame.ref.current = { measureInWindow: callback => callback(0, NaN, 320, 588) };
  frame.onLayout();
  assert.equal(one(app.render(), 'KeyboardAvoidingView').keyboardVerticalOffset, 24);
  assert.equal(byId(app.render(), 'cart-quantity-81').value, '1');
  const callbacks = [];
  frame.ref.current = { measureInWindow: callback => callbacks.push(callback) };
  frame.onLayout(); frame.onLayout();
  callbacks[1](0, 48); callbacks[0](0, 120);
  assert.equal(one(app.render(), 'KeyboardAvoidingView').keyboardVerticalOffset, 48, 'older asynchronous measurement cannot replace the latest');
  frame.onLayout(); await app.unmount();
  const writes = app.writes(); callbacks[2](0, 99);
  assert.equal(app.writes(), writes, 'a measurement after unmount cannot set state');
});

test('catalog cards keep name, unit beside price, and add or quantity controls in three rows without shrinking text', async () => {
  for (const language of ['ar', 'en']) {
    const app = harness({ language }, true);
    try {
      app.item.product_name = language === 'ar' ? 'اسم صنف طويل محفوظ بالكامل دون إخفاء المعلومات' : 'A long product name preserved without removing information';
      await app.flush();
      const tree = app.render();
      const metadata = byId(tree, 'catalog-metadata-81');
      assert.equal(metadata.style.at(-1).flexWrap, 'nowrap');
      assert.equal(metadata.style[1].flexDirection, language === 'ar' ? 'row-reverse' : 'row');
      assert.ok(text({ props: metadata }).includes('Case · Box'));
      assert.ok(text({ props: metadata }).includes('17.30 SAR'));
      assert.ok(text(tree).includes(app.item.product_name));
      const rows = [byId(tree, 'catalog-option-81').children].flat(Infinity).filter(child => child && typeof child === 'object');
      assert.equal(rows.length, 3);
      assert.equal(rows[2].type, 'Button');
      await app.act(() => rows[2].props.onPress());
      const selected = [byId(app.render(), 'catalog-option-81').children].flat(Infinity).filter(child => child && typeof child === 'object');
      assert.equal(selected.length, 3);
      assert.ok(byId(app.render(), 'cart-quantity-81'));
      assert.equal(one(app.render(), 'Field', p => p.testID === 'cart-quantity-81').style.minHeight, 44);
      assert.equal(app.module('./OrdersPrimitives.tsx').ordersStyles.strong.fontSize, 16);
      assert.equal(app.calls.some(call => call[0] === 'create'), false);
    } finally { await app.unmount(); }
  }
});

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
  await app.flush();
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

test('all-order details use the row company, company changes fetch scoped pages, and pages are bounded', async () => {
  const app = await ready({ selectedCompanyId: 0 }); byId(app.render(), 'orders-tab-allOrders').onPress(); await app.flush();
  byId(app.render(), 'orders-row-12').onPress(); await app.flush();
  assert.deepEqual(app.calls.filter(call => call[0] === 'detail').at(-1), ['detail', 2, 12]);
  assert.ok(text(app.render()).includes('Original request values'));
  button(app.render(), 'Back').onPress(); choose(app, 'orders-list-company', 1);
  assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-row-12'), false);
  await app.flush();
  assert.deepEqual(app.calls.filter(call => call[0] === 'list').at(-1), ['list', undefined, 1]);
  choose(app, 'orders-list-company', 0);
  await app.flush();
  let page = 0;
  app.engine.list = async () => { page++; return { orders: Array.from({ length: 30 }, (_, i) => app.summary(page * 30 + i, 2)), next_before_id: page * 30 }; };
  button(app.render(), 'Reload').onPress(); await app.flush();
  for (let i = 0; i < 7; i++) { const more = nodes(app.render()).find(node => node.type === 'Button' && node.props.title === 'Load more'); if (more) { more.props.onPress(); await app.flush(); } }
  assert.equal(nodes(app.render()).filter(node => node.props.testID?.startsWith('orders-row-')).length, 200);
  assert.equal(nodes(app.render()).some(node => node.type === 'Button' && node.props.title === 'Load more'), false);
});

test('receipt requires every exact decimal line and a deliberate review; automatic sharing never repeats confirm', async () => {
  const app = await ready({ rooms: [{ id: 55, company_id: 1, membership_id: 5, name: 'Original room' }] });
  app.props.identity.permissions.chat_send = true; await app.flush(); await receipt(app);
  app.engine.share = async (company, id) => { app.calls.push(['share', company, id]); throw new Error('fixture lost response'); };
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
  assert.equal(app.calls.filter(call => call[0] === 'share').length, 1, 'one automatic share follows the ACK');
  assert.ok(text(app.render()).includes('The receipt is confirmed, but sharing failed'));
  button(app.render(), 'Retry sharing').onPress(); await app.flush();
  button(app.render(), 'Retry sharing').onPress(); await app.flush();
  assert.equal(app.calls.filter(call => call[0] === 'share').length, 3);
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
    assert.ok(text(app.render()).includes('991.73 SAR'));
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('٢٫٥'));
    assert.equal(byId(app.render(), 'cart-quantity-81').value, '2.5');
    assert.ok(text(app.render()).includes('991.73 SAR'));
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
    assert.equal(app.calls.filter(call => call[0] === 'share').length, 1, 'one automatic share follows confirmed ACK and authorized original room');
    assert.deepEqual(app.calls.filter(call => call[0] === 'share'), [['share', 1, 12]]);
    assert.equal(button(app.render(), 'Retry sharing').disabled, true);
    const share = button(app.render(), 'Retry sharing').onPress;
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

test('actual central Button resets disabled to false after adding, and catalog footer is outside the single body ScrollView', async () => {
  const app = harness({}, true, true);
  const page = Array.from({ length: 24 }, (_, index) => ({ ...app.item, id: app.item.id + index, product_id: app.item.product_id + index }));
  app.engine.catalog = async () => ({ api_version: 2, items: page, next_after_id: null });
  try {
    await app.flush();
    let tree = app.render();
    const composer = nodes(tree).find(node => node.props.testID === 'orders-composer');
    const children = [composer.props.children].flat().filter(Boolean);
    assert.equal(children[0].type, 'ScrollView');
    assert.equal(children[0].props.testID, 'orders-composer-body');
    assert.equal(children[1].props.testID, 'orders-catalog-footer', 'footer is a sibling, not catalog content');
    assert.equal(nodes(tree).filter(node => node.type === 'ScrollView').length, 1, 'Workspace does not wrap the composer in another ScrollView');
    assert.equal(nodes(children[0]).some(node => node.props.testID === 'orders-company'), true, 'company selector is composed into the body');
    assert.equal(nodes(children[0]).some(node => node.props.testID === 'orders-catalog-footer'), false);
    assert.equal(nodes(children[0]).filter(node => node.props.testID?.startsWith('catalog-option-')).length, 24);
    assert.equal(children[1].props.style[1].maxWidth, 940);
    assert.ok(nodes(tree).find(node => node.type === 'KeyboardAvoidingView' && nodes(node).includes(composer)), 'body and footer share the keyboard-safe frame');
    assert.equal(one(tree, 'Pressable', p => p.accessibilityLabel === 'Review cart (0)').disabled, true);
    await app.act(() => one(app.render(), 'Pressable', p => p.accessibilityLabel === 'Add Fixture product Case').onPress());
    tree = app.render();
    assert.equal(one(tree, 'Pressable', p => p.accessibilityLabel === 'Review cart (1)').disabled, false, 'actual central Button receives false, never undefined');
    const waitingCatalog = waiting(); app.engine.catalog = async () => waitingCatalog.promise;
    await app.act(() => byId(app.render(), 'catalog-search').onChangeText('newer'));
    assert.equal(one(app.render(), 'Pressable', p => p.accessibilityLabel === 'Review cart (1)').disabled, true, 'footer respects a pending catalog load');
    await app.act(() => waitingCatalog.resolve({ api_version: 2, items: page, next_after_id: null }));
    assert.equal(one(app.render(), 'Pressable', p => p.accessibilityLabel === 'Review cart (1)').disabled, false);
    await app.act(() => one(app.render(), 'Pressable', p => p.accessibilityLabel === 'Review cart (1)').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-catalog-footer'), false);
    assert.equal(nodes(app.render()).filter(node => node.type === 'ScrollView').length, 1);
  } finally { await app.unmount(); }
});

test('actual automatic quote coalesces valid edits, replaces an inflight quote and never loops on failure', async () => {
  const app = harness({}, true), older = waiting(), newer = waiting();
  try {
    await app.flush();
    await app.act(() => one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress(), false);
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('1.5'), false);
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('2'), false);
    assert.equal(app.calls.filter(call => call[0] === 'quote').length, 0);
    assert.equal(app.timers.size, 1);
    await app.flush();
    assert.equal(app.calls.filter(call => call[0] === 'quote').length, 1);
    assert.equal(app.calls.find(call => call[0] === 'quote')[1].lines[0].quantity, '2');
    assert.ok(text(app.render()).includes('991.73 SAR'));
    app.engine.quote = async input => { app.calls.push(['quote', input]); return input.lines[0].quantity === '3' ? older.promise : newer.promise; };
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('3'), false);
    assert.equal(text(app.render()).includes('991.73 SAR'), false, 'old amount clears before debounce');
    await app.flush();
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('4'), false);
    await app.flush();
    const current = app.calls.filter(call => call[0] === 'quote').at(-1)[1];
    await app.act(() => newer.resolve({ company_id: 1, cart_revision: current.cart_revision, estimated_total: '444.40', currency_symbol: 'SAR' }));
    await app.act(() => older.resolve({ company_id: 1, cart_revision: 0, estimated_total: '333.30', currency_symbol: 'SAR' }));
    assert.ok(text(app.render()).includes('444.40 SAR')); assert.equal(text(app.render()).includes('333.30'), false);
    app.engine.quote = async input => { app.calls.push(['quote', input]); throw new Error('synthetic quote failure'); };
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('5'));
    const failedCalls = app.calls.filter(call => call[0] === 'quote').length;
    await app.flush(); await app.flush();
    assert.equal(app.calls.filter(call => call[0] === 'quote').length, failedCalls, 'failure cannot schedule itself');
    await app.act(() => button(app.render(), 'Try again').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'quote').length, failedCalls + 1);
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('1.999'));
    assert.equal(app.calls.filter(call => call[0] === 'quote').length, failedCalls + 1, 'invalid decimal never gets a quote');
  } finally { await app.unmount(); }
});

test('company all never chooses an operation company; explicit selection is inherited by catalog and receiving', async () => {
  const app = await ready({ selectedCompanyId: 0 });
  assert.equal(app.calls.some(call => call[0] === 'catalog' || call[0] === 'receipts'), false);
  assert.ok(text(app.render()).includes('Choose a company'));
  choose(app, 'orders-company', 2); await app.flush();
  assert.equal(app.props.selectedCompanyId, 2);
  assert.equal(app.calls.filter(call => call[0] === 'catalog').at(-1)[1], 2);
  byId(app.render(), 'orders-tab-receiving').onPress(); await app.flush();
  assert.equal(app.calls.filter(call => call[0] === 'receipts').at(-1)[1], 2);
  app.props.selectedCompanyId = 77; await app.flush();
  assert.equal(nodes(app.render()).some(node => node.props.testID === 'receipt-row-12'), false);
  assert.ok(text(app.render()).includes('Choose a company'));
});

test('one warehouse is hidden, no warehouse blocks pricing, and several warehouses use the server default', async () => {
  for (const count of [0, 1, 2]) {
    const app = harness(); app.options.warehouses = Array.from({ length: count }, (_, index) => ({ id: 7 + index, name: `Warehouse ${index}` }));
    app.options.default_warehouse_id = count === 2 ? 8 : 7;
    await app.flush();
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-warehouse'), count > 1);
    one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress(); await app.flush();
    if (!count) { assert.ok(text(app.render()).includes('No warehouse')); assert.equal(app.calls.some(call => call[0] === 'quote'), false); }
    else assert.equal(app.calls.find(call => call[0] === 'quote')[1].warehouse_id, count === 2 ? 8 : 7);
  }
});

async function createWithActualReact(app) {
  await app.flush();
  await app.act(() => one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress());
  await app.act(() => button(app.render(), 'Review cart (1)').onPress());
  await app.act(() => button(app.render(), 'Review order').onPress());
  await app.act(() => button(app.render(), 'Submit order').onPress());
  await app.flush();
}

test('post-create defaults are freshly validated beyond page50, remembered by id only, and shared only on an explicit press', async () => {
  const app = harness({}, true); app.props.identity.permissions.chat_send = true;
  app.engine.savedRoom = async company => { app.calls.push(['savedRoom', company]); return 999; };
  app.engine.rooms = async (company, query) => { app.calls.push(['rooms', company, query]); return { company_id: company,
    rooms: Array.from({ length: 50 }, (_, index) => ({ id: index + 1, name: `Room ${index + 1}` })), next_after_id: 50, preferred_room: { id: 999, name: 'Verified default outside page' } }; };
  try {
    await createWithActualReact(app);
    assert.equal(app.calls.filter(call => call[0] === 'create').length, 1);
    assert.equal('room_id' in app.calls.find(call => call[0] === 'create')[1], false);
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-room'), false);
    assert.deepEqual(JSON.parse(JSON.stringify(app.calls.find(call => call[0] === 'rooms')[2])), { preferredRoomId: 999 });
    assert.ok(button(app.render(), 'Verified default outside page'));
    assert.equal(app.calls.some(call => call[0] === 'shareOrder'), false);
    await app.act(() => button(app.render(), 'Clear default conversation').onPress());
    assert.deepEqual(app.calls.filter(call => call[0] === 'saveRoom').at(-1), ['saveRoom', 1, null]);
    await app.act(() => button(app.render(), 'Verified default outside page').onPress());
    await app.act(() => byId(app.render(), 'orders-share-room-3').onPress());
    await app.act(() => button(app.render(), 'Remember this conversation').onPress());
    assert.deepEqual(app.calls.filter(call => call[0] === 'saveRoom').at(-1), ['saveRoom', 1, 3]);
    const share = button(app.render(), 'Share order').onPress;
    await app.act(() => { share(); share(); });
    assert.deepEqual(app.calls.filter(call => call[0] === 'shareOrder'), [['shareOrder', 1, 14, 3]]);
    assert.equal(app.calls.filter(call => call[0] === 'create').length, 1);
    assert.ok(text(app.render()).includes('Order shared'));
  } finally { await app.unmount(); }
});

test('missing or removed room preferences never silently pick another room; share failure retries sharing only', async () => {
  const app = harness({}, true); app.props.identity.permissions.chat_send = true;
  app.engine.savedRoom = async () => 999;
  app.engine.shareOrder = async (...args) => { app.calls.push(['shareOrder', ...args]); throw { code: 'room_message_too_long' }; };
  try {
    await createWithActualReact(app);
    assert.ok(text(app.render()).includes('saved conversation is unavailable'));
    assert.equal(button(app.render(), 'Share order').disabled, true);
    await app.act(() => button(app.render(), 'Choose a conversation').onPress());
    await app.act(() => byId(app.render(), 'orders-share-room-55').onPress());
    await app.act(() => button(app.render(), 'Share order').onPress());
    assert.ok(text(app.render()).includes('Order saved'));
    assert.ok(text(app.render()).includes('message exceeds'));
    const count = app.calls.filter(call => call[0] === 'shareOrder').length;
    await app.flush(); assert.equal(app.calls.filter(call => call[0] === 'shareOrder').length, count);
    await app.act(() => button(app.render(), 'Retry sharing').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'shareOrder').length, 2);
    assert.equal(app.calls.filter(call => call[0] === 'create').length, 1);
  } finally { await app.unmount(); }
});

test('old server blocks new creates but saved unknown retries retain their original ACK and show the upgrade requirement', async () => {
  const app = harness(); delete app.options.workflow_version; app.props.identity.permissions.chat_send = true;
  app.engine.pending = async () => [{ uuid: 'old-uuid', kind: 'create', companyId: 1, createdAt: 1 }];
  app.engine.retry = async uuid => { app.calls.push(['retry', uuid]); return { order: { ...app.summary(14, 1), room_id: null }, client_uuid: uuid, replayed: true }; };
  await app.flush();
  one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress(); await app.flush();
  assert.ok(text(app.render()).includes('requires a server update'));
  assert.equal(app.calls.some(call => call[0] === 'quote' || call[0] === 'create' || call[0] === 'rooms'), false);
  button(app.render(), 'Retry saved attempt').onPress(); await app.flush();
  assert.deepEqual(app.calls.filter(call => call[0] === 'retry'), [['retry', 'old-uuid']]);
  assert.ok(text(app.render()).includes('Order submitted'));
  assert.ok(text(app.render()).includes('requires a server update'));
  assert.equal(app.calls.some(call => call[0] === 'shareOrder' || call[0] === 'rooms'), false);
});

test('a corrupt optional room preference still loads eligible rooms and offers an explicit id-only reset', async () => {
  const app = harness({}, true); app.props.identity.permissions.chat_send = true;
  app.engine.savedRoom = async () => { throw { code: 'preference_corrupt' }; };
  try {
    await createWithActualReact(app);
    assert.equal(app.calls.filter(call => call[0] === 'rooms').length, 1);
    assert.ok(text(app.render()).includes('preference is invalid'));
    assert.equal(app.calls.some(call => call[0] === 'saveRoom'), false, 'a bad preference is never erased automatically');
    await app.act(() => button(app.render(), 'Clear default conversation').onPress());
    assert.deepEqual(app.calls.filter(call => call[0] === 'saveRoom'), [['saveRoom', 1, null]]);
    await app.act(() => button(app.render(), 'Choose a conversation').onPress());
    await app.act(() => byId(app.render(), 'orders-share-room-55').onPress());
    await app.act(() => button(app.render(), 'Share order').onPress());
    assert.deepEqual(app.calls.filter(call => call[0] === 'shareOrder'), [['shareOrder', 1, 14, 55]]);
    assert.equal(app.calls.filter(call => call[0] === 'create').length, 1);
  } finally { await app.unmount(); }
});

test('receipt detail failure has a manual read retry and failed post-ACK share never automatically repeats', async () => {
  const app = harness({}, true); app.props.identity.permissions.chat_send = true;
  let detailCalls = 0;
  app.engine.detail = async (company, id) => { app.calls.push(['detail', company, id]); if (++detailCalls === 1) throw new Error('synthetic read failure'); return { order: app.summary(id, company), lines: [] }; };
  app.engine.share = async (...args) => { app.calls.push(['share', ...args]); throw new Error('synthetic share failure'); };
  try {
    await confirmWithActualReact(app);
    assert.equal(detailCalls, 1); assert.equal(app.calls.some(call => call[0] === 'share'), false);
    await app.flush(); assert.equal(detailCalls, 1, 'failed detail is not polled');
    await app.act(() => button(app.render(), 'Try again').onPress());
    assert.equal(detailCalls, 2); assert.equal(app.calls.filter(call => call[0] === 'share').length, 1);
    await app.flush(); await app.flush();
    assert.equal(app.calls.filter(call => call[0] === 'share').length, 1, 'failed share is not retriggered by rendering');
    await app.act(() => button(app.render(), 'Retry sharing').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'share').length, 2);
    assert.equal(app.calls.filter(call => call[0] === 'confirm').length, 1);
  } finally { await app.unmount(); }
});

test('rooms search discards older results, bounds the whole picker including preferred to200, and old-scope callbacks cannot share', async () => {
  const app = harness({}, true), older = waiting(), newer = waiting(); app.props.identity.permissions.chat_send = true;
  app.engine.savedRoom = async () => 999;
  app.engine.rooms = async (company, query) => {
    app.calls.push(['rooms', company, query]);
    if (query.q === 'old') return older.promise;
    if (query.q === 'new') return newer.promise;
    const after = query.afterId || 0;
    return { company_id: company, rooms: Array.from({ length: 50 }, (_, index) => ({ id: after + index + 1, name: `Room ${after + index + 1}` })), next_after_id: after + 50, preferred_room: { id: 999, name: 'Outside preferred' } };
  };
  try {
    await createWithActualReact(app);
    await app.act(() => button(app.render(), 'Outside preferred').onPress());
    for (let index = 0; index < 3; index++) await app.act(() => button(app.render(), 'Load more').onPress());
    assert.equal(nodes(app.render()).filter(node => node.props.testID?.startsWith('orders-share-room-')).length, 200);
    assert.equal(nodes(app.render()).some(node => node.type === 'Button' && node.props.title === 'Load more'), false);
    await app.act(() => byId(app.render(), 'orders-room-search').onChangeText('old'));
    await app.act(() => byId(app.render(), 'orders-room-search').onChangeText('new'));
    await app.act(() => newer.resolve({ company_id: 1, rooms: [{ id: 888, name: 'Newest room' }], next_after_id: null, preferred_room: { id: 999, name: 'Outside preferred' } }));
    await app.act(() => older.resolve({ company_id: 1, rooms: [{ id: 777, name: 'Stale room' }], next_after_id: null, preferred_room: null }));
    assert.ok(byId(app.render(), 'orders-share-room-888'));
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-share-room-777'), false);
    const oldShare = button(app.render(), 'Share order').onPress;
    const oldSave = button(app.render(), 'Clear default conversation').onPress;
    app.props.selectedCompanyId = 2; await app.flush();
    await app.act(() => { oldShare(); oldSave(); });
    assert.equal(app.calls.some(call => call[0] === 'shareOrder' || call[0] === 'saveRoom'), false);
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'orders-post-create-share'), false);
  } finally { await app.unmount(); }
});

test('saved create ACK recovery opens post-share without another create; own unlinked and purchased details recover their distinct share actions', async () => {
  const app = harness({}, true); app.props.identity.permissions.chat_send = true;
  app.engine.pending = async () => [{ uuid: 'saved-create', kind: 'create', companyId: 1, createdAt: 1 }];
  app.engine.retry = async uuid => { app.calls.push(['retry', uuid]); return { order: { ...app.summary(14, 1), room_id: null }, client_uuid: uuid, replayed: true }; };
  try {
    await app.flush(); await app.act(() => button(app.render(), 'Retry saved attempt').onPress()); await app.flush();
    assert.ok(byId(app.render(), 'orders-post-create-share'));
    assert.equal(app.calls.some(call => call[0] === 'create' || call[0] === 'shareOrder'), false);
    await app.act(() => button(app.render(), 'Go to all orders').onPress());
    app.engine.detail = async (company, id) => ({ order: { ...app.summary(id, company), room_id: null }, lines: [] });
    await app.act(() => byId(app.render(), 'orders-row-12').onPress()); await app.flush();
    assert.ok(byId(app.render(), 'orders-post-create-share'), 'own unlinked order can be shared after returning');
    await app.act(() => button(app.render(), 'Back').onPress());
    app.engine.detail = async (company, id) => ({ order: { ...app.summary(id, company), state: 'purchased', room_id: 55 }, lines: [] });
    await app.act(() => byId(app.render(), 'orders-row-12').onPress());
    assert.ok(byId(app.render(), 'orders-receipt-share'));
    assert.equal(app.calls.some(call => call[0] === 'share'), false, 'returning to purchased details does not auto-share');
    await app.act(() => button(app.render(), 'Share receipt result').onPress());
    assert.deepEqual(app.calls.filter(call => call[0] === 'share'), [['share', 1, 12]]);
    assert.equal(app.calls.some(call => call[0] === 'confirm'), false);
  } finally { await app.unmount(); }
});

test('cart and review show server quote unit and line prices rather than historical catalog prices, and clear them immediately on edits', async () => {
  const app = harness({}, true);
  try {
    await app.flush(); assert.ok(text(app.render()).includes('17.30 SAR'));
    await app.act(() => one(app.render(), 'Button', p => p.accessibilityLabel === 'Add Fixture product Case').onPress());
    await app.act(() => button(app.render(), 'Review cart (1)').onPress());
    assert.ok(text(app.render()).includes('29.81 SAR'));
    assert.ok(text(app.render()).includes('61.13 SAR'));
    assert.equal(text(app.render()).includes('17.30 SAR'), false, 'last recorded price is not presented as current cart price');
    await app.act(() => button(app.render(), 'Review order').onPress());
    assert.ok(text(app.render()).includes('Estimated unit price 29.81 SAR'));
    assert.ok(text(app.render()).includes('Line total 61.13 SAR'));
    assert.ok(byId(app.render(), 'orders-cart-footer'));
    await app.act(() => button(app.render(), 'Back').onPress());
    await app.act(() => byId(app.render(), 'cart-quantity-81').onChangeText('2'), false);
    assert.equal(text(app.render()).includes('29.81 SAR'), false);
    assert.equal(text(app.render()).includes('61.13 SAR'), false);
    assert.equal(text(app.render()).includes('991.73 SAR'), false);
    assert.equal(button(app.render(), 'Review order').disabled, true);
  } finally { await app.unmount(); }
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validCompanyPreferences } from '../core/companyPreferences.ts';
import { authorizedCompanies, identityCompanyName, isCompanyVisible, visibleCompanyIds } from '../ui/companyNames.ts';
import { ordersOnlyBootstrap } from '../session/OrdersOnlySession.ts';
import type { Bootstrap } from '../core/ChatEngine.ts';

const preference = (id: number, hidden = false) => ({ id, name: `Company ${id}`, short_name_ar: 'مختصر', short_name_en: 'Short', hidden });
const identity = (): Bootstrap => ({ api_version: 2, database: 'fixture', user_id: 7, company_ids: [1, 2], csrf_token: 'csrf', permissions: { chat_view: false, chat_send: false, order_view: true, order_create: true, order_receive: true } });

test('metadata label bounds count Unicode code points consistently with the server', () => {
  const row = { ...preference(1), short_name_ar: '😀'.repeat(40), short_name_en: '😀'.repeat(64), name: '😀'.repeat(512) };
  assert.equal(validCompanyPreferences([row], [1]), true);
  assert.equal(ordersOnlyBootstrap({ ...identity(), company_preferences: [row] }, 7, 'fixture')!.company_preferences![0].short_name_ar, row.short_name_ar);
  assert.equal(validCompanyPreferences([{ ...row, short_name_en: '😀'.repeat(65) }], [1]), false);
  assert.equal(validCompanyPreferences([{ ...row, name: '😀'.repeat(513) }], [1]), false);
});
test('company preferences validate optional legacy metadata and reject injected IDs, duplicate IDs, unsafe labels and non-boolean hide', () => {
  assert.equal(validCompanyPreferences(undefined, [1, 2]), true);
  assert.equal(validCompanyPreferences([preference(1)], [1, 2]), true);
  for (const value of [null, {}, [preference(99)], [preference(1), preference(1)], [{ ...preference(1), hidden: 'true' }],
    [{ ...preference(1), short_name_ar: 'x'.repeat(65) }], [{ ...preference(1), name: 'bad\u0000name' }]]) {
    assert.equal(validCompanyPreferences(value, [1, 2]), false);
    assert.throws(() => ordersOnlyBootstrap({ ...identity(), company_preferences: value }, 7, 'fixture'), { code: 'identity_mismatch' });
  }
});
test('profile failure cannot unhide metadata companies or add unauthorized picker entries; aliases localize independently', () => {
  const value = { ...identity(), company_preferences: [preference(1, true), preference(2)] };
  assert.deepEqual(visibleCompanyIds(value), [2]);
  assert.equal(isCompanyVisible(value, 1), false);
  assert.deepEqual(authorizedCompanies(value, 'ar'), [{ id: 2, name: 'مختصر' }]);
  assert.equal(identityCompanyName(value, 'en', 2), 'Short');
  const decoded = ordersOnlyBootstrap(value, 7, 'fixture')!;
  value.company_preferences[1].hidden = true;
  assert.deepEqual(visibleCompanyIds(decoded), [2], 'decoder isolates metadata from mutable wire payload');
  assert.deepEqual(decoded.company_ids, [1, 2], 'native authorization is never narrowed');
  const legacy = identity(); legacy.profile = { name: 'Owner', companies: [{ id: 99, name: 'Injected' }] };
  assert.deepEqual(visibleCompanyIds(legacy), [1, 2]);
  assert.deepEqual(authorizedCompanies(legacy, 'en').map(company => company.id), [1, 2]);
});
test('all hidden produces the exact empty visible set, fallback compacts known legal wrappers and keeps unknown names', () => {
  const value = { ...identity(), company_preferences: [preference(1, true), preference(2, true)] };
  assert.deepEqual(visibleCompanyIds(value), []); assert.deepEqual(authorizedCompanies(value, 'ar'), []);
  const fallback = { ...identity(), profile: { name: 'Owner', companies: [{ id: 1, name: 'شركة بصير ذات مسؤولية محدودة' }, { id: 2, name: 'Independent Name' }] } };
  assert.equal(identityCompanyName(fallback, 'ar', 1), 'بصير');
  assert.equal(identityCompanyName(fallback, 'en', 2), 'Independent Name');
});

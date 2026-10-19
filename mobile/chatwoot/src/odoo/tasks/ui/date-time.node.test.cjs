const { test } = require('node:test');
const assert = require('node:assert/strict');
const ts = require('typescript');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const moduleObject = { exports: {} };
vm.runInNewContext(ts.transpileModule(readFileSync(resolve(__dirname, '../../ui/dateTime.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: moduleObject, exports: moduleObject.exports, Date, Intl });
const { partsToUTC, localParts, dateTimeLabel, calendarDays, westernDigits } = moduleObject.exports;
test('date entry preserves a valid local minute as canonical UTC, rejecting normalized invalid dates', () => {
  const parts = { year: '2028', month: '02', day: '29', hour: '23', minute: '07' };
  const value = partsToUTC(parts);
  assert.match(value, /^2028-02-\d{2}T\d{2}:07:00Z$/);
  assert.deepEqual(JSON.parse(JSON.stringify(localParts(value))), parts);
  for (const invalid of [{ year: '2027', month: '02', day: '29' }, { month: '13' }, { day: '32' }, { hour: '24' }, { minute: '60' }, { year: '0' }, { day: '' }, { year: '2028.0' }]) assert.equal(partsToUTC({ ...parts, ...invalid }), null);
});
test('calendar bounds leap years and weekday padding without downloading a calendar or history', () => {
  const days = calendarDays(2028, 2);
  assert.ok(days.length <= 42); assert.equal(days.filter(Boolean).length, 29);
  assert.equal(calendarDays(2027, 2).filter(Boolean).length, 28);
  assert.equal(calendarDays(2026, 12).filter(Boolean).at(-1), 31);
});
test('all app-owned date labels are Gregorian with Western digits in either language', () => {
  assert.equal(westernDigits('٢٠٢٨ ۰۲ 29'), '2028 02 29');
  for (const language of ['ar', 'en']) {
    const label = dateTimeLabel('2026-11-19T09:30:00Z', language);
    assert.match(label, /2026/); assert.equal(/[٠-٩۰-۹]/.test(label), false);
    assert.equal(dateTimeLabel('not-a-date', language), '');
  }
});

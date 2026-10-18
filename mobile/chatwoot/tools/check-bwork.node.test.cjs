const { test } = require('node:test');
const assert = require('node:assert/strict');
const { assertBaseline, assertExecuted, nodeArgs } = require('./check-bwork.cjs');
const baseline = { schema: 1, suites: ['fast'], invariants: [{ id: 'reply', description: 'Approved reply action', suite: 'fast', test: 'reply exists' }] };
const result = stdout => ({ fast: { status: 0, stdout } });
test('baseline gate requires the approved test to execute and pass, not merely appear in a file', () => {
  assert.doesNotThrow(() => assertExecuted(baseline, result('ok 1 - reply exists\n')));
  assert.throws(() => assertExecuted(baseline, result('ok 1 - another test\n')), /reply/);
  assert.throws(() => assertExecuted(baseline, result('# reply exists\n')), /reply/);
});
test('baseline gate rejects skipped, todo, failed and interrupted approved cases', () => {
  for (const output of ['ok 1 - reply exists # SKIP\n', 'ok 1 - reply exists # TODO later\n', 'not ok 1 - reply exists\n']) assert.throws(() => assertExecuted(baseline, result(output)), /reply/);
  for (const change of [{ status: 1 }, { status: null, signal: 'SIGTERM' }, { error: Error('spawn failed') }]) assert.throws(() => assertExecuted(baseline, { fast: { ...result('ok 1 - reply exists\n').fast, ...change } }), /reply/);
});
test('baseline gate rejects duplicate IDs and unknown suites', () => {
  assert.throws(() => assertBaseline({ ...baseline, invariants: [...baseline.invariants, ...baseline.invariants] }), /duplicate/);
  assert.throws(() => assertBaseline({ ...baseline, suites: ['other'] }), /Invalid/);
});
test('gate uses existing Node tests without shell interpolation or silent reporter changes', () => {
  assert.deepEqual(nodeArgs('node --experimental-strip-types --test src/odoo/tests/*.test.ts'), ['--test-reporter=tap', '--experimental-strip-types', '--test', 'src/odoo/tests/*.test.ts']);
  for (const script of ['npm test', 'node --test test.cjs && echo pass', 'node --test-reporter=spec --test test.cjs']) assert.throws(() => nodeArgs(script));
});

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { assertBaseline, assertExecuted, nodeArgs } = require('./check-bwork.cjs');
const baseline = { schema: 1, suites: ['fast'], invariants: [{ id: 'reply', description: 'Approved reply action', suite: 'fast', test: 'reply exists' }] };
const result = stdout => ({ fast: { status: 0, stdout } });

test('reviewed vendor patches keep exact content and their lockfile hashes', () => {
  const root = path.resolve(__dirname, '..');
  const lock = fs.readFileSync(path.join(root, 'pnpm-lock.yaml'), 'utf8');
  const approved = {
    '@react-native-clipboard__clipboard@1.16.2.patch': '8bdca003bee8df1b0cc91f3d25cef61b84e7e0419962a0a3fcaa4176fa9933dc',
    '@react-native-menu__menu@1.2.3.patch': 'acdf5a60992519e11fc88cf4091d143b148fee4d21040c87d22bf9d1c6a0cb94',
    'ffmpeg-kit-react-native.patch': '794355498b3b3909d58e8e44d6f4f563f85d4920b1b01e020e7d63afd0b01a90',
    'react-native-ios-utilities@5.2.0.patch': '67aff11da197478ec84900a80152fc04e0fd994cc1a2e71ba311b50a0a04e4ef',
    'react-native-reanimated@4.5.5.patch': 'a303a93fac4f0d13bfbfc4d47c7a34dd24259c801cdf4db6c0dded6c89b8289f',
  };
  for (const [file, expected] of Object.entries(approved)) {
    const source = fs.readFileSync(path.join(root, 'patches', file), 'utf8').replace(/\r\n/g, '\n');
    assert.equal(createHash('sha256').update(source).digest('hex'), expected, file);
    assert.doesNotMatch(source, /[\t ]+$/m, `${file}: do not reintroduce patch-file whitespace`);
    assert.ok(lock.includes(`hash: ${expected}`) && lock.includes(`patch_hash=${expected}`), `${file}: frozen lock references`);
  }
});
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
  assert.deepEqual(nodeArgs('node --experimental-strip-types --test src/bwork/tests/*.test.ts'), ['--test-reporter=tap', '--experimental-strip-types', '--test', 'src/bwork/tests/*.test.ts']);
  for (const script of ['npm test', 'node --test test.cjs && echo pass', 'node --test-reporter=spec --test test.cjs']) assert.throws(() => nodeArgs(script));
});

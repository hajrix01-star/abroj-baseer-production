import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../static/src/app_order.js', import.meta.url), 'utf8');
const { APP_ORDER, orderApps } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const requested = APP_ORDER.map((xmlid, id) => Object.freeze({ xmlid, id }));
const other = [{ xmlid: 'mail.menu_root_discuss' }, { xmlid: 'other.app' }];
const input = Object.freeze([other[0], ...requested.toReversed(), other[1]]);
assert.deepEqual(orderApps(input), [...requested, ...other]);
assert.equal(input[0], other[0]);
assert.deepEqual(orderApps([]), []);
// Missing / forbidden apps must not be synthesized, and unlisted apps stay stable.
assert.deepEqual(orderApps([other[0], requested[7], other[1], requested[1]]), [requested[1], requested[7], ...other]);
assert.deepEqual(orderApps(other), other);
assert.deepEqual(orderApps(orderApps(input)), orderApps(input));
assert.equal(new Set(APP_ORDER).size, 10);
console.log('PASS: exact order, visibility subset, stable remainder, immutable input, empty, idempotent');

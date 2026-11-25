import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../static/src/app/line_actions.js', import.meta.url), 'utf8');
const section = source.slice(source.indexOf('function preparationLine('), source.indexOf('patch(PosOrder.prototype'))
    .replaceAll('export function ', 'function ');
const context = vm.createContext({ crypto: { randomUUID: () => 'test-action' } });
vm.runInContext(section, context);

test('historical discount lines stay out of kitchen actions', () => {
    const line = (uuid, extra = {}) => ({ uuid, getQuantity: () => 1, ...extra });
    const order = { getOrderlines: () => [line('food'), line('legacy', { baseer_global_discount_line: true })],
        last_order_preparation_change: { lines: {} } };
    const result = context.buildBaseerPreparationAction(order, 'send_before_payment');
    assert.deepEqual(Array.from(result.lines, row => row.line_uuid), ['food']);
});

test('native discount product and marked lines stay out of kitchen actions', () => {
    const line = (uuid, product, extra = {}) => ({ uuid, product_id: { id: product }, getQuantity: () => 1, ...extra });
    const order = {
        config_id: { discount_product_id: { id: 5253 } },
        getOrderlines: () => [line('food', 1), line('native', 5253), line('marked', 2, { baseer_discount_kind: 'fixed' })],
        uiState: {}, last_order_preparation_change: { lines: {} },
    };
    const result = context.buildBaseerPreparationAction(order, 'send_before_payment');
    assert.deepEqual(Array.from(result.lines, row => row.line_uuid), ['food']);
    const explicit = context.buildBaseerPreparationAction(order, 'line_change', [
        { line_uuid: 'food' }, { line_uuid: 'native' }, { line_uuid: 'marked' },
        { line_uuid: 'removed' },
    ]);
    assert.deepEqual(Array.from(explicit.lines, row => row.line_uuid), ['food', 'removed']);
});

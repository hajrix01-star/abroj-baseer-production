import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../static/src/app/line_actions.js', import.meta.url), 'utf8');
const section = source.slice(source.indexOf('function preparationLine('), source.indexOf('patch(PosOrder.prototype'))
    .replaceAll('export function ', 'function ');
const context = vm.createContext({ crypto: { randomUUID: () => 'test-action' } });
vm.runInContext(section, context);

for (const kind of ['fixed', 'percent']) {
    test(`${kind} discount and offline preview stay out of kitchen actions`, () => {
        const line = (uuid, extra = {}) => ({ uuid, getQuantity: () => 1, ...extra });
        const normal = line('food');
        const discount = line('server-discount', { baseer_global_discount_line: true });
        const preview = line('preview-discount');
        const refund = line('refund', { refunded_orderline_id: { id: 1 }, getQuantity: () => -1 });
        const order = { getOrderlines: () => [normal, discount, preview, refund],
            uiState: { baseerOfflineDiscount: { preview_line_uuids: ['preview-discount'], kind } },
            last_order_preparation_change: { lines: {} } };
        const result = context.buildBaseerPreparationAction(order, 'send_before_payment');
        assert.deepEqual(Array.from(result.lines, row => row.line_uuid), ['food']);
    });
}

import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../static/src/app/legacy_history_guard.js', import.meta.url), 'utf8')
    .replace(/^import .*;\s*$/gm, '').replace('export function', 'function');
let patchBody;
class TicketScreen {}
const dialogType = class {};
new Function('_t', 'AlertDialog', 'patch', 'TicketScreen', source)(s => s, dialogType, (_target, body) => { patchBody = body; }, TicketScreen);
test('legacy orders are blocked before refund lines are created', async () => {
    for (const order of [{ baseer_global_discount_locked: true, lines: [] }, { lines: [{ baseer_global_discount_line: true }] }]) {
        let notice;
        const screen = { getSelectedOrder: () => order, dialog: { add: (type, options) => { notice = { type, ...options }; } } };
        await patchBody.onDoRefund.call(screen);
        assert.equal(notice.type, dialogType);
        assert.match(notice.body, /credit note/);
    }
});

test('ordinary refunds proceed and historical allowance details are excluded', async () => {
    Object.setPrototypeOf(patchBody, {
        async onDoRefund() { this.called = true; return 'native'; },
        _getRefundableDetails() { return [{ line: {} }, { line: { baseer_global_discount_line: true } }]; },
    });
    const screen = { getSelectedOrder: () => ({ lines: [{}] }) };
    assert.equal(await patchBody.onDoRefund.call(screen), 'native');
    assert.equal(screen.called, true);
    assert.equal(patchBody._getRefundableDetails.call(screen).length, 1);
});

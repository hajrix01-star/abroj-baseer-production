import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

// Mirrors QA asset 84f9e15 native lifecycle / accounting contracts. No RPC or
// persistent Odoo data is used: integration payment checks remain necessary.
function fixture({ methods = [{ id: 7, type: 'bank', is_cash_count: false }], total = 12.65, addResult = true } = {}) {
    const currency = { round: n => Math.round((n + Number.EPSILON) * 100) / 100,
        isZero: n => Math.abs(n) < 0.005 };
    class PosPayment {
        constructor(order, method, uuid = 'payment-1', amount = 0) {
            this.pos_order_id = order; this.payment_method_id = method; this.uuid = uuid; this.amount = amount;
            this.payment_status = false; this.is_change = false;
        }
        getAmount() { return this.amount || 0; }
        setAmount(amount) { this.amount = currency.round(parseFloat(amount) || 0); }
        isDone() { return !this.payment_status || ['done', 'reversed'].includes(this.payment_status); }
    }
    class PosOrder {
        constructor(uuid = 'order-1') {
            this.uuid = uuid; this.state = 'draft'; this.config_id = { id: 1 }; this.session_id = { id: 2 };
            this.isRefund = false; this.payment_ids = []; this.total = total; this.currency = currency;
        }
        isRefundInProcess() { return false; }
        get amountPaid() { return currency.round(this.payment_ids.filter(p => p.isDone() && !p.is_change).reduce((s, p) => s + p.getAmount(), 0)); }
        get remainingDue() { return Math.max(0, currency.round(this.total - this.amountPaid)); }
        get change() { return this.amountPaid > this.total ? currency.round(this.total - this.amountPaid) : 0; }
        getDefaultAmountDueToPayIn() { return this.remainingDue || this.change; }
        addPaymentline(method) {
            const due = this.getDefaultAmountDueToPayIn(method);
            const line = new PosPayment(this, method, `p${this.payment_ids.length + 1}`);
            this.payment_ids.push(line); line.setAmount(due); this.selected = line;
            return { status: true, data: line };
        }
        removePaymentline(line) { this.payment_ids = this.payment_ids.filter(p => p !== line); }
    }
    class PaymentScreen {
        constructor(pos) { this.pos = pos; this.currentOrder = pos.getOrder(); this.payment_methods_from_config = methods; this.numberBuffer = pos.numberBuffer; this.dialog = pos.dialog; }
        get paymentLines() { return this.currentOrder.payment_ids; }
        onMounted() {
            const order = this.pos.getOrder();
            for (const line of [...order.payment_ids]) {
                if (!this.pos.config.payment_method_ids.some(method => method.id === line.payment_method_id.id)) order.removePaymentline(line);
            }
            if (this.payment_methods_from_config.length === 1 && this.paymentLines.length === 0) this.addNewPaymentLine(this.payment_methods_from_config[0]);
        }
        async addNewPaymentLine(method) { const result = this.currentOrder.addPaymentline(method); this.numberBuffer.set(result.data.amount.toString()); return addResult; }
        updateSelectedPaymentline(amount) { this.currentOrder.payment_ids[0].setAmount(amount); }
        deletePaymentLine(uuid) { const line = this.paymentLines.find(p => p.uuid === uuid); this.currentOrder.removePaymentline(line); }
    }
    class OrderPaymentValidation {
        constructor(pos) { this.pos = pos; }
        get order() { return this.pos.getOrder(); }
        async isOrderValid() { return true; }
        async validateOrder() { this.pos.numberBuffer.capture(); return this.isOrderValid(); }
    }
    const alerts = [];
    const numberBuffer = { value: '', set(value) { this.value = value; }, capture() { if (this.handler) this.handler(); } };
    const initial = new PosOrder();
    let current = initial;
    const pos = { config: { id: 1, payment_method_ids: methods }, currency, numberBuffer,
        dialog: { add(_component, options) { alerts.push(options); } }, getOrder: () => current };
    const sandbox = { PaymentScreen, PosOrder, PosPayment, OrderPaymentValidation, AlertDialog: class {},
        _t: s => s, patch(target, extension) {
            Object.setPrototypeOf(extension, Object.create(null, Object.getOwnPropertyDescriptors(target)));
            Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
        }, console };
    vm.createContext(sandbox);
    const source = readFileSync(new URL('../static/src/app/auto_payment_refresh.js', import.meta.url), 'utf8')
        .replace(/^import .*;\r?\n/gm, '');
    vm.runInContext(source, sandbox);
    return { PosOrder, PosPayment, PaymentScreen, OrderPaymentValidation, pos, initial, alerts, numberBuffer,
        setCurrent(order) { current = order; }, screen() { return new PaymentScreen(pos); } };
}

test('untouched auto payment is refreshed after replacement snapshot', async () => {
        const f = fixture(); const first = f.screen(); first.onMounted();
        await Promise.resolve();
        assert.equal(f.initial.payment_ids[0].amount, 12.65);
        // A protected snapshot can replace the whole order object. Only UUID,
        // config/session, method, amount and payment UUID establish continuity.
        const rebuilt = new f.PosOrder(f.initial.uuid); rebuilt.total = 11.50;
        rebuilt.payment_ids = [new f.PosPayment(rebuilt, f.pos.config.payment_method_ids[0], 'p1', 12.65)];
        f.setCurrent(rebuilt); const reopened = f.screen(); reopened.onMounted();
        assert.equal(rebuilt.payment_ids[0].amount, 11.50);
        assert.equal(f.numberBuffer.value, '11.5');
        // Native capture can deliver buffered input after screen mount; it must
        // never write the stale pre-return amount over the refreshed one.
        f.numberBuffer.handler = () => reopened.updateSelectedPaymentline(Number(f.numberBuffer.value));
        assert.equal(await new f.OrderPaymentValidation(f.pos).validateOrder(), true);
        assert.equal(rebuilt.payment_ids[0].amount, 11.50);
});

test('manual same-amount edit loses provenance and is never changed on return', async () => {
    const f = fixture(); const screen = f.screen(); screen.onMounted();
    screen.updateSelectedPaymentline(12.65); f.initial.total = 11.50;
    f.screen().onMounted(); assert.equal(f.initial.payment_ids[0].amount, 12.65);
    assert.equal(await new f.OrderPaymentValidation(f.pos).isOrderValid(), false);
    assert.equal(f.initial.payment_ids[0].amount, 12.65); assert.equal(f.alerts.length, 1);
});

test('bank chosen with multiple methods refreshes the untouched default amount', async () => {
    const bank = { id: 7, type: 'bank', is_cash_count: false }, other = { id: 8, type: 'bank', is_cash_count: false };
    const f = fixture({ methods: [bank, other] }); const screen = f.screen(); screen.onMounted();
    await screen.addNewPaymentLine(bank); f.initial.total = 11.50; f.screen().onMounted();
    assert.equal(f.initial.payment_ids[0].amount, 11.50);
    assert.equal(await new f.OrderPaymentValidation(f.pos).isOrderValid(), true);
});

test('bank chosen with multiple methods preserves an explicitly entered amount and warns locally', async () => {
    const bank = { id: 7, type: 'bank', is_cash_count: false }, other = { id: 8, type: 'bank', is_cash_count: false };
    const f = fixture({ methods: [bank, other] }); const screen = f.screen(); screen.onMounted();
    await screen.addNewPaymentLine(bank);
    screen.updateSelectedPaymentline(12.65);
    f.initial.total = 11.50; f.screen().onMounted();
    assert.equal(f.initial.payment_ids[0].amount, 12.65);
    assert.equal(await new f.OrderPaymentValidation(f.pos).isOrderValid(), false);
    assert.equal(f.initial.payment_ids[0].amount, 12.65);
});

for (const excluded of [
    { name: 'QR', method: { id: 7, type: 'bank', payment_method_type: 'qr_code' } },
    { name: 'terminal', method: { id: 7, type: 'bank', use_payment_terminal: true } },
    { name: 'online', method: { id: 7, type: 'bank', is_online_payment: true } },
    { name: 'cash', method: { id: 7, type: 'cash', is_cash_count: true } },
    { name: 'pay later', method: { id: 7, type: 'pay_later', is_cash_count: false } },
]) test(`${excluded.name} payment is never refreshed`, () => {
    const f = fixture({ methods: [excluded.method] }); f.screen().onMounted(); f.initial.total = 11.50;
    f.screen().onMounted(); assert.equal(f.initial.payment_ids[0].amount, 12.65);
});

test('failure in native amount calculation restores the original amount', async () => {
    const f = fixture(); f.screen().onMounted(); await Promise.resolve(); f.initial.total = 11.50;
    f.initial.getDefaultAmountDueToPayIn = () => { throw new Error('failure'); };
    f.screen().onMounted(); assert.equal(f.initial.payment_ids[0].amount, 12.65);
});

test('missing provenance and a different session never cause automatic writes', async () => {
    const f = fixture(); f.initial.addPaymentline(f.pos.config.payment_method_ids[0]); f.initial.total = 11.50;
    f.screen().onMounted(); assert.equal(f.initial.payment_ids[0].amount, 12.65);
    const g = fixture(); g.screen().onMounted(); await Promise.resolve(); g.initial.total = 11.50; g.initial.session_id = { id: 4 };
    g.screen().onMounted(); assert.equal(g.initial.payment_ids[0].amount, 12.65);
});

test('adding and then removing a payment invalidates automatic provenance', () => {
    const f = fixture(); f.screen().onMounted();
    const original = f.initial.payment_ids[0];
    f.initial.addPaymentline(f.pos.config.payment_method_ids[0]);
    f.initial.removePaymentline(f.initial.payment_ids[1]);
    f.initial.total = 11.50; f.screen().onMounted();
    assert.equal(original.amount, 12.65);
});

test('refund orders never acquire automatic payment provenance', () => {
    const f = fixture(); f.initial.isRefund = true; f.screen().onMounted();
    f.initial.isRefund = false; f.initial.total = 11.50; f.screen().onMounted();
    assert.equal(f.initial.payment_ids[0].amount, 12.65);
});

test('repeated re-entry handles both increased and reduced total without changing payment identity', async () => {
    const f = fixture(); f.screen().onMounted(); await Promise.resolve(); const payment = f.initial.payment_ids[0];
    payment.ticket = 'keep'; f.initial.total = 15.15; f.screen().onMounted();
    assert.equal(payment.amount, 15.15); assert.equal(payment.uuid, 'p1'); assert.equal(payment.ticket, 'keep');
    f.initial.total = 11.50; f.screen().onMounted(); assert.equal(payment.amount, 11.50);
    f.screen().onMounted(); assert.equal(payment.amount, 11.50); assert.equal(payment.ticket, 'keep');
});

test('the native default amount, including rounding, is used without reproducing its calculation', async () => {
    const f = fixture(); f.screen().onMounted(); await Promise.resolve(); f.initial.total = 11.50;
    f.initial.getDefaultAmountDueToPayIn = () => 11.55;
    f.screen().onMounted(); assert.equal(f.initial.payment_ids[0].amount, 11.55);
});

test('a previously automatic line with terminal status done is never changed', async () => {
    const f = fixture(); f.screen().onMounted(); await Promise.resolve();
    f.initial.payment_ids[0].payment_status = 'done'; f.initial.total = 11.50;
    f.screen().onMounted(); assert.equal(f.initial.payment_ids[0].amount, 12.65);
});

test('an unsuccessful payment method addition cannot establish an automatic amount', async () => {
    const f = fixture({ addResult: false }); const screen = f.screen();
    await screen.addNewPaymentLine(f.pos.config.payment_method_ids[0]);
    f.initial.total = 11.50; f.screen().onMounted();
    assert.equal(f.initial.payment_ids[0].amount, 12.65);
});

test('a user edit while the payment creation promise is pending stays manual', async () => {
    let finish;
    const waiting = new Promise(resolve => { finish = resolve; });
    const f = fixture({ addResult: waiting }); const screen = f.screen();
    const pending = screen.addNewPaymentLine(f.pos.config.payment_method_ids[0]);
    screen.updateSelectedPaymentline(12.65); finish(true); await pending;
    f.initial.total = 11.50; f.screen().onMounted();
    assert.equal(f.initial.payment_ids[0].amount, 12.65);
});

test('pending creation cannot refresh until native success is confirmed', async () => {
    let finish;
    const waiting = new Promise(resolve => { finish = resolve; });
    const f = fixture({ addResult: waiting }); const screen = f.screen();
    const pending = screen.addNewPaymentLine(f.pos.config.payment_method_ids[0]);
    f.initial.total = 11.50; f.screen().onMounted();
    assert.equal(f.initial.payment_ids[0].amount, 12.65);
    finish(true); await pending; await Promise.resolve(); f.screen().onMounted();
    assert.equal(f.initial.payment_ids[0].amount, 11.50);
});

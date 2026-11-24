import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../static/src/app/native_fixed_discount.js', import.meta.url), 'utf8').replace(/^import .*;\n/gm, '');
function harness() {
    class PosStore { async setup() {} async applyDiscount(percent, order = this.getOrder()) { order.discountLines.forEach(l => l.extra_tax_data = { discount_percentage: percent }); } }
    class ControlButtons { async clickDiscount() { this.native = true; } }
    class PaymentScreen { async validateOrder() { this.validated = true; } }
    const patch = (target, extension) => { const old = Object.create(Object.getPrototypeOf(target)); Object.defineProperties(old, Object.getOwnPropertyDescriptors(target)); Object.setPrototypeOf(extension, old); Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension)); };
    const accountTaxHelpers = {
        prepare_base_line_for_taxes_computation: line => line,
        add_tax_details_in_base_lines() {}, round_base_lines_tax_details() {},
        prepare_discountable_base_lines: lines => lines,
        aggregate_base_lines_tax_details: lines => lines,
        aggregate_base_lines_aggregated_values: lines => ({ all: { total_excluded_currency: lines.reduce((s, l) => s + l.total, 0), tax_amount_currency: 0 } }),
        prepare_global_discount_lines(lines, company, type, amount, options) {
            assert.equal(type, 'fixed');
            const total = lines.reduce((s, l) => s + l.total, 0);
            let assigned = 0;
            return lines.map((line, index) => {
                const part = index === lines.length - 1 ? amount - assigned : Math.round(amount * line.total / total * 100) / 100;
                assigned += part;
                return { product_id: options.grouping_function().grouping_key.product_id, tax_ids: line.tax_ids, quantity: 1, price_unit: -part, extra: { amount: -part } };
            });
        },
        export_base_line_extra_tax_data: line => line.extra,
    };
    const user = { hasGroup: async () => false };
    const SelectionPopup = {}, NumberPopup = {}, AlertDialog = {};
    let choice;
    const makeAwaitable = async () => choice;
    const debounce = fn => fn;
    const PosOrderAccounting = { accountingFields: new Set(['lines']) };
    new Function('patch','debounce','_t','user','AlertDialog','accountTaxHelpers','PosStore','PosOrderAccounting','ControlButtons','PaymentScreen','NumberPopup','SelectionPopup','makeAwaitable','isDiscountFrozen', src)(patch,debounce,x=>x,user,AlertDialog,accountTaxHelpers,PosStore,PosOrderAccounting,ControlButtons,PaymentScreen,NumberPopup,SelectionPopup,makeAwaitable, () => false);
    return { PosStore, ControlButtons, PaymentScreen, user, setChoice: x => choice = x };
}
function fixture(h) {
    const pos = new h.PosStore();
    pos.baseerIsDiscountFrozen = () => false; pos.user = { id: 1 }; pos.getCashier = () => pos.user;
    pos.config = { discount_product_id: { id: 9, product_tmpl_id: {} }, baseer_fixed_discount_enabled: true, baseer_fixed_discount_allowed: 'all' };
    const order = { state: 'draft', company_id: {}, discountLines: [], lines: [], getOrderlines() { return this.lines; } };
    pos.getOrder = () => order;
    pos.addLineToOrder = async (values) => {
        const line = { ...values, tax_ids: values.tax_ids[0].slice(1), update(v) { Object.assign(this, v); }, delete() { order.discountLines.splice(order.discountLines.indexOf(this), 1); } };
        order.discountLines.push(line); return line;
    };
    const source = (total, id) => ({ total, tax_ids: [{ id }], isGlobalDiscountApplicable: () => true, prepareBaseLineForTaxesComputationExtraValues: () => ({}) });
    order.lines = [source(115, 15), source(100, 0)];
    return { pos, order };
}
test('fixed tax groups, cap, eligible total, reapplication and removal', async () => {
    const h = harness(), { pos, order } = fixture(h);
    await pos.baseerApplyFixedDiscount(10, order);
    assert.equal(order.discountLines.length, 2);
    assert.equal(Math.round(order.discountLines.reduce((s,l) => s + l.price_unit, 0) * 100), -1000);
    assert.ok(order.discountLines.every(l => l.baseer_discount_kind === 'fixed' && !l.extra_tax_data.discount_percentage));
    order.lines[0].total = 230;
    await pos.baseerApplyFixedDiscount(order.discountLines[0].baseer_discount_input, order);
    assert.equal(Math.round(order.discountLines.reduce((s,l) => s + l.price_unit, 0) * 100), -1000);
    pos.config.baseer_fixed_discount_max_amount = 5;
    await pos.baseerApplyFixedDiscount(10, order);
    assert.equal(order.discountLines.reduce((s,l) => s + l.price_unit, 0), -5);
    pos.config.baseer_fixed_discount_max_amount = 0;
    await pos.baseerApplyFixedDiscount(999, order);
    assert.equal(order.discountLines.reduce((s,l) => s + l.price_unit, 0), -330);
    order.lines = []; await pos.baseerApplyFixedDiscount(10, order);
    assert.equal(order.discountLines.length, 0);
});
test('percent retains native calculation and fixed choice respects settings', async () => {
    const h = harness(), { pos, order } = fixture(h);
    await pos.baseerApplyFixedDiscount(10, order); await pos.applyDiscount(20);
    assert.ok(order.discountLines.every(l => l.baseer_discount_kind === 'percent' && l.extra_tax_data.discount_percentage === 20));
    const button = new h.ControlButtons(); button.pos = pos; button.dialog = {};
    pos.config.baseer_fixed_discount_enabled = false; await button.clickDiscount(); assert.equal(button.native, true);
    button.native = false; pos.config.baseer_fixed_discount_enabled = true; pos.config.baseer_fixed_discount_allowed = 'managers';
    await button.clickDiscount(); assert.equal(button.native, true);
});
test('offline fixed payment is blocked', async () => {
    const h = harness(), { pos, order } = fixture(h); await pos.baseerApplyFixedDiscount(10, order);
    pos.data = { network: { offline: true } }; const screen = new h.PaymentScreen(); screen.pos = pos; screen.currentOrder = order;
    let notice; screen.dialog = { add: (_, props) => notice = props.body };
    await screen.validateOrder(); assert.ok(notice.includes('بدون اتصال')); assert.equal(screen.validated, undefined);
    pos.data.network.offline = false; await screen.validateOrder(); assert.equal(screen.validated, true);
});
test('line and order accounting events schedule fixed reapplication', async () => {
    const h = harness(), { pos, order } = fixture(h);
    const callbacks = {}; const line = order.lines[0]; line.order_id = order;
    pos.models = {
        'pos.order.line': { addEventListener: (_, cb) => callbacks.line = cb, get: () => line },
        'pos.order': { addEventListener: (_, cb) => callbacks.order = cb, get: () => order },
    };
    await pos.setup(); await pos.baseerApplyFixedDiscount(10, order);
    line.total = 230; callbacks.line({ id: 1 });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(Math.round(order.discountLines.reduce((sum, item) => sum + item.price_unit, 0) * 100), -1000);
    order.lines = []; callbacks.order({ id: 1, fields: ['lines'] });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(order.discountLines.length, 0);
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../static/src/app/native_discount_refund.js', import.meta.url), 'utf8');
const pure = source.slice(source.indexOf('export function refundShare'), source.indexOf('\npatch(PosStore')).replace('export ', '');
const roundPrecision = (n, p) => Math.round((n + Number.EPSILON) / p) * p;
const refundShare = new Function('roundPrecision', `${pure}; return refundShare;`)(roundPrecision);

test('three partial refunds return the exact remaining shares', () => {
    const original = { qty: 3, baseer_discount_share_incl: -1, baseer_discount_share_excl: -0.87 };
    const previous = [];
    for (let i = 0; i < 3; i++) previous.push({ qty: -1, ...refundShare(original, previous, -1, 0.01) });
    assert.deepEqual(previous.map((line) => Math.round(line.baseer_discount_share_incl * 100)), [33, 33, 34]);
    assert.equal(Math.round(previous.reduce((sum, line) => sum + line.baseer_discount_share_excl, 0) * 100), 87);
});

test('native ticket refund uses stored shares to create its discount line', async () => {
    class PosStore { applyDiscount() { throw new Error('native percent path used'); } }
    class TicketScreen { async onDoRefund() { this.pos.applyDiscount(50, this.pos.getOrder()); } }
    const patch = (target, extension) => { const old = Object.create(Object.getPrototypeOf(target)); Object.defineProperties(old, Object.getOwnPropertyDescriptors(target)); Object.setPrototypeOf(extension, old); Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension)); };
    const helpers = {
        prepare_base_line_for_taxes_computation: line => ({ line, tax_details: { total_excluded_currency: 0.29, delta_total_excluded_currency: 0, total_included_currency: 0.33, taxes_data: [{ tax_amount_currency: 0.04, tax_amount: 0.04 }] } }),
        add_tax_details_in_base_lines() {}, round_base_lines_tax_details() {},
        fix_base_lines_tax_details_on_manual_tax_amounts() {}, export_base_line_extra_tax_data: base => ({ target: base.tax_details }),
    };
    const code = source.replace(/^import .*;\n/gm, '').replace('export function refundShare', 'function refundShare');
    new Function('patch', 'roundPrecision', 'accountTaxHelpers', 'PosStore', 'TicketScreen', code)(patch, roundPrecision, helpers, PosStore, TicketScreen);
    const original = { qty: 3, baseer_discount_share_incl: -1, baseer_discount_share_excl: -0.87, order_id: {}, refund_orderline_ids: [] };
    const tax = { id: 15 };
    const line = { qty: -1, id: 1, tax_ids: [tax], refunded_orderline_id: original, prepareBaseLineForTaxesComputationExtraValues() { return { tax_ids: this.tax_ids }; }, update(values) { Object.assign(this, values); } };
    const order = { is_refund: true, currency: { rounding: 0.01 }, company_id: {}, lines: [line], discountLines: [] };
    line.order_id = order; original.refund_orderline_ids = [line];
    const pos = new PosStore(); pos.getOrder = () => order; pos.config = { discount_product_id: { product_tmpl_id: {} } };
    pos.addLineToOrder = async values => { const result = { ...values, prepareBaseLineForTaxesComputationExtraValues: () => ({}), update(v) { Object.assign(this, v); } }; order.discountLines.push(result); return result; };
    const screen = new TicketScreen(); screen.pos = pos;
    await screen.onDoRefund();
    assert.equal(Math.round(line.baseer_discount_share_incl * 100), 33);
    assert.equal(Math.round(order.discountLines[0].price_unit * 100), -29);
    assert.equal(order.discountLines[0].qty, -1);
    assert.ok(order.discountLines[0].extra_tax_data);
});

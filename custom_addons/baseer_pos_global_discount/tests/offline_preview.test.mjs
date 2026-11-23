import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { test } from "node:test";

globalThis.crypto ||= webcrypto;
globalThis.testTaxHelpers = {
    prepare_base_line_for_taxes_computation: (line) => ({ line, tax_details: { total_included_currency: line.price_unit * line.qty } }),
    add_tax_details_in_base_lines() {}, round_base_lines_tax_details() {},
    prepare_global_discount_lines(bases, _company, mode, value) {
        const total = bases.reduce((sum, item) => sum + item.tax_details.total_included_currency, 0);
        return [{ price_unit: -(mode === "fixed" ? value : total * value / 100), quantity: 1, tax_ids: [bases[0].line.tax_ids[0]] }];
    },
    export_base_line_extra_tax_data: () => ({}),
};
const source = readFileSync(new URL("../static/src/app/offline_preview.js", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "")
    .replaceAll("export function ", "function ");
const { calculateOfflineDiscount, refreshOfflineDiscount, wireOfflineDiscount } = new Function("accountTaxHelpers", "_t", `${source}\nreturn { calculateOfflineDiscount, refreshOfflineDiscount, wireOfflineDiscount };`)(globalThis.testTaxHelpers, (value) => value);

function fixture(kind, value) {
    const tax = { id: 1, amount_type: "percent" };
    const product = { id: 9, type: "service", product_tmpl_id: {} };
    const intent = { version: 1, order_uuid: "order", action_uuid: "action", kind, value, account_proofs: { "0": "a".repeat(64), "7": "b".repeat(64) }, preview_line_uuids: [] };
    const order = { uuid: "order", state: "draft", uiState: { baseerOfflineDiscount: intent }, lines: [], company_id: {}, currency: { round: (n) => Math.round(n * 100) / 100 }, triggerRecomputeAllPrices() {}, _markDirty() {} };
    Object.defineProperties(order, {
        priceIncl: { get() { return this.lines.reduce((sum, line) => sum + line.price_unit * line.qty, 0); } },
        amountTaxes: { get() { return 0; } },
    });
    function addLine(values) {
        const line = { ...values, tax_ids: values.tax_ids?.[0]?.[0] === "link" ? values.tax_ids[0].slice(1) : values.tax_ids,
            delete() { order.lines.splice(order.lines.indexOf(this), 1); }, prepareBaseLineForTaxesComputationExtraValues() { return {}; } };
        order.lines.push(line);
        return line;
    }
    const pos = { config: { baseer_global_discount_product_id: product, baseer_global_discount_max_percent: 100, baseer_global_discount_max_amount: 0 }, models: { "pos.order.line": { create: addLine } } };
    addLine({ uuid: "item", product_id: { id: 1, type: "consu", tracking: 'none' }, price_unit: 100, qty: 1, tax_ids: [tax] });
    return { pos, order, intent, addLine, tax };
}

test("fixed and percentage previews recalculate on quantity and added items", () => {
    for (const [kind, expected] of [["fixed", "110.00"], ["percent", "108.00"]]) {
        const { pos, order, intent, addLine, tax } = fixture(kind, "10");
        refreshOfflineDiscount(pos, order);
        assert.equal(intent.expected_total, "90.00");
        addLine({ uuid: "item-2", product_id: { id: 2, type: "consu", tracking: 'none' }, price_unit: 20, qty: 1, tax_ids: [tax] });
        refreshOfflineDiscount(pos, order);
        assert.equal(intent.expected_total, expected);
        assert.equal(intent.preview_line_uuids.length, 1);
        assert.equal(order.lines.length, 3);
        assert.deepEqual(Object.keys(wireOfflineDiscount(intent)).sort(), ["action_uuid", "expected_tax", "expected_total", "kind", "order_uuid", "preview_line_uuids", "value", "version", "account_proof"].sort());
    }
});

test("fiscal position selects the original signed account proof; missing proof blocks payment", () => {
    const { pos, order, intent } = fixture("fixed", "10");
    refreshOfflineDiscount(pos, order);
    assert.equal(wireOfflineDiscount(intent).account_proof, "a".repeat(64));
    order.fiscal_position_id = { id: 7 };
    refreshOfflineDiscount(pos, order);
    assert.equal(wireOfflineDiscount(intent).account_proof, "b".repeat(64));
    order.fiscal_position_id = { id: 8 };
    refreshOfflineDiscount(pos, order);
    assert.match(intent.error, /account needs verification/);
});

test("a fixed amount above the basket is blocked and can recover after correction", () => {
    const { pos, order, intent } = fixture("fixed", "20");
    order.lines[0].price_unit = 15;
    refreshOfflineDiscount(pos, order);
    assert.match(intent.error, /exceeds/);
    assert.equal(intent.preview_line_uuids.length, 0);
    order.lines[0].price_unit = 30;
    refreshOfflineDiscount(pos, order);
    assert.equal(intent.error, false);
    assert.equal(intent.expected_total, "10.00");
});

test('preview calculation excludes server allowance and preserves the graph and total when verification fails', () => {
    const { pos, order, intent, addLine, tax } = fixture('fixed', '10');
    const server = addLine({ uuid: 'server', id: 33, baseer_global_discount_line: true,
        product_id: { id: 9, type: 'service' }, price_unit: -10, qty: 1, tax_ids: [tax] });
    const before = [...order.lines];
    const total = order.priceIncl;
    const calculated = calculateOfflineDiscount(pos, order, intent);
    assert.equal(calculated.discountBases[0].price_unit, -10);
    assert.deepEqual(order.lines, before);
    assert.equal(order.priceIncl, total);
    assert.equal(intent.account_proof, undefined);
    intent.account_proofs = {};
    assert.throws(() => calculateOfflineDiscount(pos, order, intent), /account needs verification/);
    assert.equal(order.lines.includes(server), true);
    assert.deepEqual(order.lines, before);
    assert.equal(order.priceIncl, total);
});

test('failed recalculation preserves the existing preview and blocks confirmation', () => {
    const { pos, order, intent } = fixture('fixed', '10');
    refreshOfflineDiscount(pos, order);
    const lines = [...order.lines];
    const total = order.priceIncl;
    const preview = [...intent.preview_line_uuids];
    intent.account_proofs = {};
    refreshOfflineDiscount(pos, order);
    assert.match(intent.error, /account needs verification/);
    assert.deepEqual(order.lines, lines);
    assert.deepEqual(intent.preview_line_uuids, preview);
    assert.equal(order.priceIncl, total);
});

test('lot, serial, missing tracking and lot rows are blocked before a discount can be paid', () => {
    for (const tracking of ['lot', 'serial', undefined]) {
        const { pos, order, intent } = fixture('fixed', '10');
        order.lines[0].product_id.tracking = tracking;
        refreshOfflineDiscount(pos, order);
        assert.match(intent.error, /Tracked products/);
        assert.equal(order.lines.length, 1);
    }
    const { pos, order, intent } = fixture('fixed', '10');
    order.lines[0].pack_lot_ids = [{ lot_name: 'lot-1' }];
    refreshOfflineDiscount(pos, order);
    assert.match(intent.error, /Tracked products/);
});

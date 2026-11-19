import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const memory = new Map();
globalThis.localStorage = {
    getItem: (key) => memory.get(key) ?? null,
    setItem: (key, val) => memory.set(key, val),
    removeItem: (key) => memory.delete(key),
};
const source = readFileSync(new URL("../static/src/app/global_discount.js", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "").replace("export class", "class");
const mocks = `
const extensions = new Map();
const patch = (target, extension) => { Object.setPrototypeOf(extension, target); extensions.set(target.constructor.name, extension); };
const _t = (value) => value; const session = { db: 'qa' };
const discountStorageKey = (db, config, uuid) => [db, config, uuid].join(':');
const pendingDiscount = (pos, order) => localStorage.getItem(pos.baseerDiscountKey(order));
const needsDiscountRefund = (order) => order.needsRefund;
const useState = (value) => value;
const useAutofocus = () => {};
class Component {} class Dialog {} class AlertDialog {};
class ControlButtons { clickFiscalPosition() { this.nativeCalled = true; } }
class PosStore { applyDiscount() { this.nativeCalled = true; } }
class PosOrder { removeOrderline() { this.nativeCalled = true; } }
class PosOrderline { setQuantity() { this.nativeCalled = true; } }
class OrderSummary { updateSelectedOrderline() { this.nativeCalled = true; } }
class TicketScreen {
    _getRefundableDetails() { return this.details; }
    _onUpdateSelectedOrderline() { this.nativeCalled = true; }
}
class PaymentScreen { validateOrder() { this.nativeCalled = true; } }
`;
const load = new Function(`${mocks}\n${source}\nreturn { extensions, BaseerGlobalDiscountDialog };`);
const { extensions, BaseerGlobalDiscountDialog } = load();
const storageKey = "qa:2:order";
function order(pending = false) {
    memory.clear();
    if (pending) memory.set(storageKey, "pending-intent");
    return { config_id: { id: 2 }, uuid: "order", baseer_global_discount_locked: !pending };
}
test("quantity and removal are frozen during an unknown discount response", () => {
    const draft = order(true);
    const line = { order_id: draft, qty: 1 };
    assert.equal(extensions.get("PosOrderline").setQuantity.call(line, 2), false);
    assert.equal(line.nativeCalled, undefined);
    assert.equal(extensions.get("PosOrder").removeOrderline.call(draft, {}), false);
    assert.equal(draft.nativeCalled, undefined);
});
test("fiscal position action is blocked before native direct tax assignment", async () => {
    const calls = [];
    const control = { currentOrder: order(), pos: { dialog: { add: (...args) => calls.push(args) } } };
    await extensions.get("ControlButtons").clickFiscalPosition.call(control);
    assert.equal(control.nativeCalled, undefined);
    assert.equal(calls.length, 1);
});
test("owned discounts never trigger native automatic percentage reapplication", async () => {
    for (const scenario of ["locked", "refund"]) {
        const pos = { config: { baseer_global_discount_enabled: true } };
        const draft = { baseer_global_discount_locked: scenario === "locked", needsRefund: scenario === "refund" };
        await extensions.get("PosStore").applyDiscount.call(pos, 10, draft);
        assert.equal(pos.nativeCalled, undefined, scenario);
    }
    const normal = { config: {} };
    await extensions.get("PosStore").applyDiscount.call(normal, 10, {});
    assert.equal(normal.nativeCalled, true);
});
test("enabling the new feature preserves native historical discount refunds", async () => {
    const pos = { config: { baseer_global_discount_enabled: true } };
    const historicalRefund = { baseer_global_discount_locked: false, needsRefund: false };
    await extensions.get("PosStore").applyDiscount.call(pos, 10, historicalRefund);
    assert.equal(pos.nativeCalled, true);
});
test("native percentage reapplication waits for a managed command with an unknown result", async () => {
    const pending = order(true);
    const pos = { config: { baseer_global_discount_enabled: true } };
    await extensions.get("PosStore").applyDiscount.call(pos, 10, pending);
    assert.equal(pos.nativeCalled, undefined);
});
test("refund picker excludes standalone allowances and explains manual selection", () => {
    const allowance = { id: 2, baseer_global_discount_line: true };
    const regular = { id: 1 };
    const screen = {
        details: [{ line: regular }, { line: allowance }],
        getSelectedOrder: () => ({ lines: [regular, allowance] }), getSelectedOrderlineId: () => 2,
        dialog: { add: () => { screen.explained = true; } },
    };
    assert.deepEqual(extensions.get("TicketScreen")._getRefundableDetails.call(screen), [{ line: regular }]);
    extensions.get("TicketScreen")._onUpdateSelectedOrderline.call(screen);
    assert.equal(screen.nativeCalled, undefined);
    assert.equal(screen.explained, true);
});
test("payment waits for confirmation and original-discount refund preparation", async () => {
    for (const scenario of ["pending", "running", "unprepared-refund"]) {
        const draft = order(scenario === "pending");
        draft.baseer_global_discount_locked = false;
        draft.needsRefund = scenario === "unprepared-refund";
        const screen = {
            currentOrder: draft,
            pos: { _baseerDiscountRunning: scenario === "running", baseerDiscountKey: () => storageKey },
            dialog: { add: () => { screen.explained = true; } },
        };
        await extensions.get("PaymentScreen").validateOrder.call(screen);
        assert.equal(screen.nativeCalled, undefined, scenario);
        assert.equal(screen.explained, true, scenario);
    }
});
test("discount opens as a fixed amount and submits without a reason prompt", () => {
    const dialog = new BaseerGlobalDiscountDialog();
    dialog.setup();
    assert.equal(dialog.state.kind, "fixed");
    let payload;
    let closed = false;
    dialog.props = { getPayload: (value) => { payload = value; }, close: () => { closed = true; } };
    dialog.state.value = "20";
    dialog.confirm();
    assert.deepEqual(payload, { kind: "fixed", value: "20" });
    assert.equal(closed, true);
    const xml = readFileSync(new URL("../static/src/app/global_discount.xml", import.meta.url), "utf8");
    assert.equal(xml.includes("baseer-discount-reason"), false);
    assert.equal(xml.includes("baseer-global-discount"), false, "reuse the original native button instead of adding a second one");
    assert.ok(xml.includes("hasclass('js_discount')"));
});

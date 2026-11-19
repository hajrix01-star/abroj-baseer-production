import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../static/src/app/discount_flow.js", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "const _t = (v) => v;\n");
const flow = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const store = new Map();
globalThis.localStorage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => store.set(key, value),
    removeItem: (key) => store.delete(key),
};
function fixture() {
    store.clear();
    const order = { id: 10, uuid: "order-a", payment_ids: [], isSynced: true, baseer_protected_revision: "r1" };
    const calls = [];
    const pos = {
        data: { network: { offline: false }, call: async (...args) => {
            calls.push(args);
            const saved = JSON.parse(store.values().next().value);
            assert.equal(saved.actionUuid, args[2].at(-2));
            return { accepted: true, action_uuid: saved.actionUuid, data: { "pos.order": [order] } };
        } },
        baseerDiscountKey: (o) => flow.discountStorageKey("qa", 2, o.uuid),
        baseerHasPendingProtectedAction: () => false,
        baseerResolvePendingKitchenAction: async () => true,
        syncAllOrders: async () => [order],
        baseerReconcileProtectedState: async () => order,
    };
    return { pos, order, calls };
}
test("saves intent before RPC; sends raw decimal and canonical revision without browser math", async () => {
    const { pos, order, calls } = fixture();
    assert.equal(await flow.submitDiscount(pos, order, { kind: "fixed", value: "20.01", reason: "Loyalty" }), order);
    assert.deepEqual(calls[0].slice(0, 2), ["pos.order", "baseer_apply_global_discount"]);
    assert.deepEqual(calls[0][2].slice(0, 4), [[10], "fixed", "20.01", "Loyalty"]);
    assert.equal(store.size, 0);
});
test("lost reply retains intent; retry reuses exact action and never re-syncs stale order", async () => {
    const { pos, order } = fixture();
    pos.data.call = async () => { throw new Error("lost reply"); };
    await assert.rejects(() => flow.submitDiscount(pos, order, { kind: "percent", value: "10" }), /lost reply/);
    const intent = flow.pendingDiscount(pos, order);
    assert.ok(intent.actionUuid);
    pos.syncAllOrders = async () => { throw new Error("must not resync"); };
    pos.data.call = async (_model, _method, args) => {
        assert.equal(args.at(-2), intent.actionUuid);
        return { accepted: true, action_uuid: intent.actionUuid };
    };
    await flow.submitDiscount(pos, order, { kind: "fixed", value: "999" });
    assert.equal(store.size, 0);
});
test("canonical persistence failure retains payment-blocking intent", async () => {
    const { pos, order } = fixture();
    pos.baseerReconcileProtectedState = async () => { throw new Error("IndexedDB unavailable"); };
    await assert.rejects(() => flow.submitDiscount(pos, order, { kind: "fixed", value: "20" }), /IndexedDB/);
    assert.ok(flow.pendingDiscount(pos, order));
});
test("offline, terminal/payment, pending protected edits and missing acknowledgement stop before command", async () => {
    for (const mode of ["offline", "payment", "terminal", "protected", "kitchen", "unsynced", "revision"]) {
        const { pos, order, calls } = fixture();
        if (mode === "offline") pos.data.network.offline = true;
        if (mode === "payment") order.payment_ids.push({});
        if (mode === "terminal") pos.paymentTerminalInProgress = true;
        if (mode === "protected") pos.baseerHasPendingProtectedAction = () => true;
        if (mode === "kitchen") pos.baseerResolvePendingKitchenAction = async () => false;
        if (mode === "unsynced") order.isSynced = false;
        if (mode === "revision") delete order.baseer_protected_revision;
        await assert.rejects(() => flow.submitDiscount(pos, order, { kind: "fixed", value: "20" }));
        assert.equal(calls.length, 0, mode);
        assert.equal(store.size, 0, mode);
    }
});
test("refund command sends no client allocation or totals", async () => {
    const { pos, order, calls } = fixture();
    pos.data.call = async (...args) => {
        calls.push(args);
        const intent = flow.pendingDiscount(pos, order);
        return { accepted: true, action_uuid: intent.actionUuid };
    };
    await flow.submitDiscount(pos, order, { refund: true });
    assert.equal(calls[0][1], "baseer_prepare_global_discount_refund");
    assert.equal(calls[0][2].length, 3);
});
test("bad acknowledgement and malformed stored intent never unlock payment", async () => {
    const { pos, order } = fixture();
    pos.data.call = async () => ({ accepted: true, action_uuid: "different-command" });
    await assert.rejects(() => flow.submitDiscount(pos, order, { kind: "fixed", value: "1" }), /did not confirm/);
    assert.ok(flow.pendingDiscount(pos, order));
    store.set(pos.baseerDiscountKey(order), "broken");
    await assert.rejects(() => flow.submitDiscount(pos, order, {}), /needs verification/);
    assert.equal(store.get(pos.baseerDiscountKey(order)), "broken");
});
test("refund detection follows original server-owned order metadata", () => {
    assert.equal(flow.needsDiscountRefund({ is_refund: true, lines: [{ refunded_orderline_id: { order_id: { baseer_global_discount_locked: true } } }] }), true);
    assert.equal(flow.needsDiscountRefund({ is_refund: true, lines: [] }), false);
});
test("Saudi anonymous customer is resolved before synchronizing the frozen fiscal snapshot", async () => {
    const { pos, order } = fixture();
    let assigned = false;
    order.baseerAssignAnonymousB2cPartner = () => { assigned = true; };
    pos.syncAllOrders = async () => { assert.equal(assigned, true); return [order]; };
    await flow.submitDiscount(pos, order, { kind: "percent", value: "10", reason: "QA" });
});

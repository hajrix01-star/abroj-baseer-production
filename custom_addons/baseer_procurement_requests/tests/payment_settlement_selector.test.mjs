// Run: node --test custom_addons/baseer_procurement_requests/tests/payment_settlement_selector.test.mjs
// Exercise the actual field class with mocked Odoo services/lifecycle hooks.
// This checks RPC/record behavior; it does not claim browser rendering coverage.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../static/src/payment_settlement_selector.js", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "")
    .replace(/export class /g, "class ");
const choices = {
    payment_points: [{ id: 7, name: "Branch bank" }],
    representatives: [{ id: 8, name: "Buyer", available_balance: 50 }],
    can_use_representative: true,
};
const tick = () => new Promise((resolve) => setImmediate(resolve));

function fixture({ readonly = false, groups = [], data = {}, call } = {}) {
    const effects = [];
    const calls = [];
    const updates = [];
    const orm = { call: async (...args) => {
        calls.push(args);
        return call ? await call(...args) : choices;
    } };
    const context = {
        Component: class {}, Dropdown: class {}, DropdownItem: class {},
        useEffect: (effect, deps) => effects.push({ effect, deps }), useState: (state) => state,
        useService: () => orm, standardFieldProps: {}, _t: (value) => value,
        user: { hasGroup: async (group) => groups.includes(group) },
        registry: { category: () => ({ add() {} }) },
    };
    const Selector = runInNewContext(source + "\nPaymentSettlementSelector;", context);
    const field = new Selector();
    field.props = { readonly, record: {
        data: { company_id: [2, "Branch"], payment_source_type: "payment_method", ...data },
        update: async (values) => { updates.push(values); Object.assign(field.props.record.data, values); },
    } };
    field.setup();
    return { field, calls, updates, effects };
}

test("readonly cash/bank fields show the saved name without requesting options", async () => {
    const f = fixture({ readonly: true, data: { payment_method_line_id: [7, "Saved bank"] } });
    await f.effects[0].effect();
    await tick();
    assert.equal(f.calls.length, 0);
    assert.equal(f.field.label, "Saved bank");
    assert.equal(f.field.state.loading, false);
    assert.equal(f.field.representativeBalance, false);
});

test("readonly representative and credit names remain available without balances", async () => {
    const f = fixture({ readonly: true, data: {
        payment_source_type: "representative_petty_cash", is_credit: true,
        representative_petty_cash_representative_id: { id: 8, display_name: "Saved buyer" },
    } });
    await f.field.refreshChoices();
    assert.equal(f.field.label, "Saved buyer");
    assert.equal(f.field.representativeBalance, false);
    f.field.props.record.data.representative_petty_cash_representative_id = false;
    f.field.props.record.data.payment_source_type = "credit";
    assert.equal(f.field.label, "Credit");
    assert.equal(f.calls.length, 0);
});

test("unprivileged viewers do not request or update settlement options", async () => {
    const f = fixture();
    await f.field.refreshChoices();
    await f.field.choosePaymentPoint(choices.payment_points[0]);
    await f.field.chooseRepresentative(choices.representatives[0]);
    assert.equal(f.calls.length, 0);
    assert.equal(f.updates.length, 0);
    assert.equal(f.field.state.canChooseSettlement, false);
});

test("branch operators load payment points and save the selection without approval", async () => {
    const f = fixture({ groups: ["baseer_procurement_requests.group_procurement_cashier"],
        call: async () => ({ payment_points: choices.payment_points, representatives: [], can_use_representative: false }) });
    await f.field.refreshChoices();
    assert.equal(f.calls.length, 1);
    assert.equal(f.field.state.canChooseSettlement, true);
    assert.equal(f.field.state.choices.can_use_representative, false);
    await f.field.choosePaymentPoint(choices.payment_points[0]);
    assert.equal(f.updates.length, 1);
    assert.equal(f.field.props.record.data.payment_method_line_id.id, 7);
    assert.equal(f.calls[0][1], "payment_settlement_choices");
});

test("an accountant entering edit mode loads choices and changes credit atomically", async () => {
    const f = fixture({ readonly: true, groups: ["account.group_account_invoice"], data: {
        payment_source_type: "credit", is_credit: true,
    } });
    await f.field.refreshChoices();
    assert.equal(f.calls.length, 0);
    f.field.props.readonly = false;
    f.effects[0].effect();
    await tick();
    assert.equal(f.calls.length, 1);
    await f.field.choosePaymentPoint(choices.payment_points[0]);
    assert.equal(f.field.props.record.data.payment_source_type, "payment_method");
    assert.equal(f.field.props.record.data.is_credit, false);
    assert.equal(f.updates.length, 1);
});

test("a late request cannot enable a readonly row or display its balance", async () => {
    let finish;
    const f = fixture({ groups: ["baseer_procurement_requests.group_procurement_accountant"],
        call: () => new Promise((resolve) => { finish = resolve; }) });
    const request = f.field.refreshChoices();
    await tick();
    f.field.props.readonly = true;
    finish(choices);
    await request;
    assert.equal(f.field.state.canChooseSettlement, false);
    assert.equal(f.field.representativeBalance, false);
    await f.field.choosePaymentPoint(choices.payment_points[0]);
    assert.equal(f.updates.length, 0);
});

test("switching companies ignores late options from the previous company", async () => {
    let finish;
    const f = fixture({ groups: ["account.group_account_invoice"],
        call: () => new Promise((resolve) => { finish = resolve; }) });
    const request = f.field.refreshChoices();
    await tick();
    f.field.props.record.data.company_id = [3, "Other branch"];
    finish(choices);
    await request;
    assert.equal(f.field.state.canChooseSettlement, false);
    assert.equal(f.field.state.choices.payment_points.length, 0);
});

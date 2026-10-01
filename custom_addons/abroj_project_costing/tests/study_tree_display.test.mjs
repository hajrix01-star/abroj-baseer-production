import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../static/src/js/study_tree.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?$/gm, '').replace('export class AbrojStudyTree', 'class AbrojStudyTree');
function component(orm) {
    const Tree = runInNewContext(`${source}\nAbrojStudyTree`, {
        Component: class { constructor(props) { this.props = props; } },
        onWillStart: () => {}, onWillUpdateProps: () => {}, useState: (value) => value,
        ConfirmationDialog: class {}, registry: { category: () => ({ add: () => {} }) },
        useService: (name) => name === 'orm' ? orm : { add: () => {} },
        standardFieldProps: {}, console,
    });
    const tree = new Tree({ record: { resId: 5 } });
    tree.setup();
    return tree;
}
const quantity = (unit, amount) => ({ uom_type: unit, label: unit || 'بدون وحدة', quantity: amount });
const clone = (value) => JSON.parse(JSON.stringify(value));

test('header quantities combine roots only and retain distinct units', () => {
    const tree = component({});
    tree.state.nodes = [
        { quantity_totals: [quantity('unit', 8), quantity('m2', 12.5)], children: [{ quantity_totals: [quantity('unit', 8)] }] },
        { quantity_totals: [quantity('unit', 3)] },
    ];
    assert.deepEqual(clone(tree.totalQuantities), [quantity('unit', 11), quantity('m2', 12.5)]);
    assert.equal(tree.formatQuantities([quantity(false, 30)]), '30 بدون وحدة');
    assert.equal(tree.formatQuantities([]), '0');
});

test('refresh reads authoritative totals in the same tree request and does not sum parents twice', async () => {
    let amount = 100;
    const calls = [];
    const tree = component({ call: async (...args) => {
        calls.push(args);
        return {
            lines: [
                { id: 1, parent_id: false, estimated_total: amount, quantity_totals: [quantity(false, 8)] },
                { id: 2, parent_id: [1, 'أثاث'], estimated_total: amount, quantity_totals: [quantity(false, 8)] },
            ],
            summary: { estimated_total: amount, actual_total: 55, variance_amount: 55 - amount, currency_id: [1, 'SAR'] },
        };
    } });
    await tree.load();
    assert.equal(calls[0][1], 'get_study_tree_view_data');
    assert.equal(tree.state.summary.estimated_total, 100);
    assert.equal(tree.state.summary.actual_total, 55);
    assert.equal(tree.totalQuantities[0].quantity, 8);
    amount = 125;
    await tree.load();
    assert.equal(tree.state.summary.estimated_total, 125);
});

test('a delayed old project response cannot replace the new project summary', async () => {
    let resolveOld;
    const old = new Promise((resolve) => { resolveOld = resolve; });
    const tree = component({ call: async (_model, _method, [[id]]) => id === 5 ? old : { lines: [], summary: { estimated_total: 250 } } });
    const first = tree.load();
    await tree.load({ record: { resId: 6 } });
    resolveOld({ lines: [], summary: { estimated_total: 100 } });
    await first;
    assert.equal(tree.state.summary.estimated_total, 250);
});

test('unsaved project clears all previous nodes and totals without an RPC', async () => {
    const tree = component({ call: async () => { throw new Error('unexpected RPC'); } });
    tree.state.nodes = [{ quantity_totals: [quantity('unit', 8)] }];
    tree.state.flatNodes = [{ id: 1 }];
    tree.state.summary = { estimated_total: 100 };
    await tree.load({ record: { resId: false } });
    assert.equal(tree.state.nodes.length, 0);
    assert.equal(tree.state.flatNodes.length, 0);
    assert.deepEqual(clone(tree.state.summary), {});
    assert.equal(tree.totalQuantities.length, 0);
});

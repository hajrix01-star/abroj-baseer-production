import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/app/shared_draft_relink.js', import.meta.url), 'utf8');
const { relinkSharedDraftForKitchen } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function fixture() {
    let generation = 8;
    const tracker = { get: () => generation };
    const order = { uuid: 'fixture-order', id: 'fixture-order', state: 'draft', isSynced: false,
        session_id: { id: 11 }, config_id: { id: 12 }, company_id: { id: 13 },
        models: { _baseerDraftGenerationTracker: tracker },
        uiState: { baseerSharedDraftGeneration: 8, baseerSharedDraftRevision: 3,
            baseerSharedDraftServerOrderId: 21, baseerSharedDraftLineIds: { 'line-1': 31 } },
        lines: [{ uuid: 'line-1', id: 'line-1', product_id: { id: 14 }, qty: 2,
            price_unit: 5, discount: 0, tax_ids: [{ id: 18 }, { id: 17 }] }] };
    const calls = [];
    const pos = { config: { id: 12, company_id: { id: 13 }, current_session_id: { id: 11 } },
        data: { network: { offline: false } }, getOrder: () => order,
        models: { 'pos.order': { getBy: () => order } },
        async baseerRefreshCleanSharedDraftExperiment(record, options) {
            calls.push(options);
            record.id = 21;
            record.isSynced = true;
            record.lines[0].id = 31;
            return true;
        } };
    return { pos, order, calls, change: () => { generation++; } };
}

test('relinks exactly the acknowledged order and item identity', async () => {
    const { pos, order, calls } = fixture();
    assert.equal(await relinkSharedDraftForKitchen(pos, order), order);
    assert.deepEqual(calls[0].expected, { serverId: 21, revision: 3, uuid: 'fixture-order',
        sessionId: 11, configId: 12, companyId: 13,
        lines: [{ uuid: 'line-1', id: 31, productId: 14, qty: 2, priceUnit: 5, discount: 0, taxIds: [17, 18] }] });
    assert.equal(order.id, 21);
    assert.equal(order.lines[0].id, 31);
});

test('does not refresh or overwrite an unsynchronized graph', async () => {
    const { pos, order, calls, change } = fixture();
    change();
    await assert.rejects(relinkSharedDraftForKitchen(pos, order));
    assert.equal(calls.length, 0);
    assert.equal(order.id, 'fixture-order');
});

test('rejects unverified server line identity before fetching the graph', async () => {
    const { pos, order, calls } = fixture();
    delete order.uiState.baseerSharedDraftLineIds['line-1'];
    await assert.rejects(relinkSharedDraftForKitchen(pos, order));
    assert.equal(calls.length, 0);
    assert.equal(order.id, 'fixture-order');
});

test('rejects stale server identity and lost response without advancing the order', async () => {
    for (const lost of [false, true]) {
        const { pos, order } = fixture();
        pos.baseerRefreshCleanSharedDraftExperiment = async () => {
            if (lost) throw new Error('connection lost');
            return false;
        };
        await assert.rejects(relinkSharedDraftForKitchen(pos, order));
        assert.equal(order.id, 'fixture-order');
        assert.equal(order.lines[0].id, 'line-1');
    }
});

test('rejects graph mutations that occur while the refreshed data is persisted', async () => {
    const { pos, order, change } = fixture();
    pos.baseerRefreshCleanSharedDraftExperiment = async () => {
        order.id = 21;
        order.isSynced = true;
        order.lines[0].id = 31;
        change();
        return true;
    };
    await assert.rejects(relinkSharedDraftForKitchen(pos, order));
    assert.equal(order.uiState.baseerSharedDraftGeneration, 8);
});

test('rejects a financial line that changed after native relinking', async () => {
    const { pos, order } = fixture();
    pos.baseerRefreshCleanSharedDraftExperiment = async () => {
        order.id = 21;
        order.isSynced = true;
        order.lines[0].id = 31;
        order.lines[0].price_unit = 6;
        return true;
    };
    await assert.rejects(relinkSharedDraftForKitchen(pos, order));
});

test('rejects missing or duplicate tax identity before refresh', async () => {
    for (const taxes of [undefined, [{ id: 17 }, { id: 17 }], [{ id: '17' }]]) {
        const { pos, order, calls } = fixture();
        order.lines[0].tax_ids = taxes;
        await assert.rejects(relinkSharedDraftForKitchen(pos, order));
        assert.equal(calls.length, 0);
    }
});

test('rejects changed tax identity after native relinking', async () => {
    const { pos, order } = fixture();
    pos.baseerRefreshCleanSharedDraftExperiment = async () => {
        order.id = 21;
        order.isSynced = true;
        order.lines[0].id = 31;
        order.lines[0].tax_ids = [{ id: 19 }];
        return true;
    };
    await assert.rejects(relinkSharedDraftForKitchen(pos, order));
});

test('accepts a verified item with no taxes', async () => {
    const { pos, order, calls } = fixture();
    order.lines[0].tax_ids = [];
    assert.equal(await relinkSharedDraftForKitchen(pos, order), order);
    assert.deepEqual(calls[0].expected.lines[0].taxIds, []);
});

test('uses native zero default for discount on a new local order line', async () => {
    const { pos, order, calls } = fixture();
    const line = order.lines[0];
    delete line.discount;
    line.getDiscount = function () { return this.discount || 0; };
    const refresh = pos.baseerRefreshCleanSharedDraftExperiment;
    pos.baseerRefreshCleanSharedDraftExperiment = async (...args) => {
        const result = await refresh(...args);
        line.discount = 0;
        return result;
    };
    assert.equal(await relinkSharedDraftForKitchen(pos, order), order);
    assert.equal(calls[0].expected.lines[0].discount, 0);
});

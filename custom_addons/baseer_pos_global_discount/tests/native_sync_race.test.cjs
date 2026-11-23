// Regression reproducer against the exact native syncAllOrders source copied
// from the candidate Odoo image into the worktree's temporary directory.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync, existsSync } = require('node:fs');
const { resolve } = require('node:path');
const sourcePath = resolve(__dirname, '../../../tmp/pos-discount-native-pos-store.js');
const modelsPath = resolve(__dirname, '../../../tmp/pos-discount-native-related-models.js');

test('native sync clears edits made while its older RPC response is pending', { skip: !existsSync(sourcePath) }, async () => {
    const source = readFileSync(sourcePath, 'utf8');
    const start = source.indexOf('    async syncAllOrders(options = {}) {');
    const end = source.indexOf('\n    pushSingleOrder(', start);
    assert.ok(start >= 0 && end > start, 'native method was not found');
    const make = new Function('ConnectionLostError', 'logPosMessage', 'CONSOLE_COLOR',
        `return class { ${source.slice(start, end)} }`);
    class ConnectionLostError extends Error {}
    const Native = make(ConnectionLostError, () => {}, '');
    const store = new Native();
    let started, release;
    const requestStarted = new Promise((resolve) => { started = resolve; });
    const responseGate = new Promise((resolve) => { release = resolve; });
    const order = { uuid: 'order', lines: ['A'], commands: [], isDirty: () => true,
        serializeForORM(options = {}) {
            const payload = { lines: [...this.lines], commands: [...this.commands] };
            if (!options.keepCommands) this.commands = [];
            return payload;
        } };
    Object.assign(store, {
        syncingOrders: new Set(),
        getPendingOrder: () => ({ orderToCreate: [], orderToUpdate: [order] }),
        getOrderIdsToDelete: () => [], getSyncAllOrdersContext: () => ({}),
        preSyncAllOrders: async (orders) => orders, postSyncAllOrders: async () => {},
        removePendingOrder: () => { store.pendingRemoved = true; },
        data: { network: { offline: false }, async call(model, method, [[payload]]) {
            started(); await responseGate;
            return { 'pos.order': [{ lines: payload.lines }], 'pos.order.line': [], 'pos.session': [] };
        }, missingRecursive: async (data) => data },
        models: { loadConnectedData(data) {
            // Native related-model loading replaces the old raw graph.
            order.lines = [...data['pos.order'][0].lines];
            return { 'pos.order': [order], 'pos.order.line': [] };
        } },
    });
    const sync = store.syncAllOrders();
    await requestStarted;
    order.lines.push('B');
    order.commands.push('new-local-edit');
    release();
    await sync;
    assert.deepEqual(order.lines, ['A']);
    assert.deepEqual(order.commands, []);
    assert.equal(store.pendingRemoved, true);
});

test('experimental tracker subscribes to the exact native model event API', { skip: !existsSync(modelsPath) }, () => {
    const source = readFileSync(modelsPath, 'utf8');
    const start = source.indexOf('        addEventListener(event, callback) {');
    const end = source.indexOf('\n        _sanitizeRawData(', start);
    assert.ok(start >= 0 && end > start, 'native model event methods were not found');
    const methods = source.slice(start, end);
    const exp = readFileSync(resolve(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8')
        .replaceAll('export async function', 'async function').replaceAll('export function', 'function');
    const make = new Function(`
        const AVAILABLE_EVENT = ['create', 'update', 'delete'];
        const callbacks = {};
        let next = 0;
        const uuidv4 = () => String(++next);
        class Model { constructor(name) { this.name = name; callbacks[name] = {}; } ${methods} }
        ${exp}
        return { Model, trackDraftGraphGeneration };
    `);
    const { Model, trackDraftGraphGeneration } = make();
    const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
    const models = Object.fromEntries(names.map((name) => [name, new Model(name)]));
    const tracker = trackDraftGraphGeneration(models);
    models['pos.order.line'].triggerEvents('delete', { id: 12 });
    models['pos.payment'].triggerEvents('update', { id: 13 });
    assert.equal(tracker.get(), 2);
    tracker.dispose();
    models['pos.order.line'].triggerEvents('create', { ids: [14] });
    assert.equal(tracker.get(), 2);
});

test('experimental allowance detach removes the unlink created by native Odoo deletion', { skip: !existsSync(modelsPath) }, () => {
    const source = readFileSync(modelsPath, 'utf8');
    const start = source.indexOf('        _delete(record, opts = {}) {');
    const end = source.indexOf('\n        backLink(', start);
    assert.ok(start >= 0 && end > start, 'native model deletion was not found');
    const exp = readFileSync(resolve(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8')
        .replaceAll('export async function', 'async function').replaceAll('export function', 'function');
    const make = new Function(`
        const STORE_SYMBOL = Symbol();
        const X2MANY_TYPES = new Set(['one2many', 'many2many']);
        const field = { name: 'order_id', type: 'many2one', relation: 'pos.order' };
        const inverseMap = new Map([[field, { name: 'lines', dummy: false }]]);
        const getFields = () => ({ order_id: field });
        const commands = { 'pos.order': { unlink: new Map(), delete: new Map() } };
        const database = {};
        const models = { commands, _disconnect(field, record, parent) { parent.lines = parent.lines.filter((item) => item !== record); record.order_id = null; } };
        class AggregatedUpdates { remove() {} fireEventAndDirty() {} }
        class Model { constructor() { this.name = 'pos.order.line'; this[STORE_SYMBOL] = { remove() {} }; }
            delete(record, opts) { return this._delete(record, opts); } triggerEvents() {} ${source.slice(start, end)} }
        ${exp}
        return { Model, models, commands, detachServerAllowancesExperiment };
    `);
    const { Model, models, commands, detachServerAllowancesExperiment } = make();
    const order = { id: 42, models, lines: [] };
    const allowance = { id: 33, isSynced: true, baseer_global_discount_line: true, order_id: order, model: new Model() };
    order.lines.push(allowance);
    assert.deepEqual(detachServerAllowancesExperiment(order), [33]);
    assert.deepEqual(order.lines, []);
    assert.equal(commands['pos.order'].unlink.has('lines'), false);
});

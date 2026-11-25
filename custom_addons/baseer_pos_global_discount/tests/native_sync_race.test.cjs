// Regression reproducer against the exact native syncAllOrders source copied
// from the candidate Odoo image into the worktree's temporary directory.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const sourcePath = resolve(__dirname, '../../../tmp/pos-discount-native-pos-store.js');
const modelsPath = resolve(__dirname, '../../../tmp/pos-discount-native-related-models.js');

test('native sync clears edits made while its older RPC response is pending', async () => {
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
        device: { removeUsedNumbers: () => {} },
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

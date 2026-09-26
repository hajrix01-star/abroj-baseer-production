// Run: node custom_addons/baseer_pos_product_substitution/static/tests/protected_command.node.cjs
// Deterministic unit tests of the actual patch methods. Native model/UI integration
// is tested separately in Odoo QA; these mocks do not claim browser coverage.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/app/substitution.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace('export class ', 'class ');
const patches = new Map();
const storage = new Map();
const classes = Object.fromEntries(['Component', 'Dialog', 'AlertDialog', 'SelectionPopup', 'TextInputPopup', 'PosOrder', 'PosStore', 'PosData', 'PaymentScreen', 'OrderSummary'].map(name => [name, class {}]));
const context = {
    ...classes, session: { db: 'test' }, console,
    _t: value => value, useState: value => value, makeAwaitable: async () => null,
    crypto: { randomUUID: () => 'fixed-action-uuid' },
    localStorage: new Proxy({ getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }, {
        ownKeys: () => [...storage.keys()],
        getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
    }),
    patch: (target, methods) => patches.set(target, methods),
};
vm.runInNewContext(source + '\nglobalThis.helpers = { pendingKey, readPending, substitutionLock, isSubstitutionOutputLine };', context);
const posMethods = patches.get(classes.PosStore.prototype);
const orderMethods = patches.get(classes.PosOrder.prototype);
const order = { id: 100, uuid: 'order-uuid', config_id: { id: 40 }, isSynced: true, baseer_protected_revision: 'revision-1' };
const intent = { orderId: 100, orderUuid: order.uuid, kind: 'edit', action: { action_uuid: 'stable-id', source_line_uuid: 'source' }, expectedRevision: 'revision-1' };
const key = context.helpers.pendingKey(order);
function mockPos() {
    return {
        ...posMethods,
        env: { services: { ui: { block() {}, unblock() {} } } },
        notification: { add() {} }, dialog: { add() {} },
        data: { network: { offline: false }, call: async () => ({ accepted: true, action_uuid: 'stable-id', data: {} }) },
        baseerReconcileProtectedState: async () => order,
    };
}
async function test(name, run) {
    storage.clear();
    await run();
    console.log('PASS', name);
}
(async () => {
    await test('pending intent blocks generic payment/autosync serialization', () => {
        storage.set(key, JSON.stringify(intent));
        assert.throws(() => orderMethods.serializeForORM.call(order), /previous edit/);
    });
    await test('corrupt pending record fails closed', () => {
        storage.set(key, '{');
        assert.throws(() => orderMethods.serializeForORM.call(order), /previous edit/);
    });
    await test('accepted action clears durable intent only after canonical reconciliation', async () => {
        storage.set(key, JSON.stringify(intent));
        const pos = mockPos();
        pos.baseerReconcileProtectedState = async () => assert.ok(storage.has(key));
        assert.equal(await pos.baseerExecuteProtectedIntent(intent, key), true);
        assert.equal(storage.has(key), false);
    });
    await test('lost response retains exact same action ID for retry; no optimistic mutation', async () => {
        storage.set(key, JSON.stringify(intent));
        const pos = mockPos(); let calls = 0;
        pos.data.call = async (model, method, args) => {
            assert.equal(args[2].action_uuid, 'stable-id');
            if (++calls === 1) throw new Error('Connection lost');
            return { accepted: true, action_uuid: 'stable-id' };
        };
        assert.equal(await pos.baseerExecuteProtectedIntent(intent, key), false);
        assert.equal(JSON.parse(storage.get(key)).action.action_uuid, 'stable-id');
        assert.equal(await pos.baseerRetryProtectedAction(order), true);
        assert.equal(calls, 2);
        assert.equal(storage.has(key), false);
    });
    await test('accepted server command with failed local refresh remains recoverable', async () => {
        storage.set(key, JSON.stringify(intent));
        const pos = mockPos();
        pos.baseerReconcileProtectedState = async () => { throw new Error('IndexedDB failure'); };
        assert.equal(await pos.baseerExecuteProtectedIntent(intent, key), false);
        assert.ok(storage.has(key));
    });
    await test('wrong acknowledgement ID never unblocks payment', async () => {
        storage.set(key, JSON.stringify(intent));
        const pos = mockPos();
        pos.data.call = async () => ({ accepted: true, action_uuid: 'different' });
        assert.equal(await pos.baseerExecuteProtectedIntent(intent, key), false);
        assert.ok(storage.has(key));
    });
    await test('definitive rejection refreshes authoritative order before removing intent', async () => {
        storage.set(key, JSON.stringify(intent));
        const pos = mockPos(); const methods = [];
        pos.data.call = async (model, method) => {
            methods.push(method);
            if (method === 'baseer_apply_protected_action') throw { data: { name: 'odoo.exceptions.ValidationError', message: 'stale revision' } };
            return { data: {} };
        };
        assert.equal(await pos.baseerExecuteProtectedIntent(intent, key), false);
        assert.deepEqual(methods, ['baseer_apply_protected_action', 'baseer_read_protected_state']);
        assert.equal(storage.has(key), false);
    });
    await test('rejected action with failed refresh remains blocked', async () => {
        storage.set(key, JSON.stringify(intent));
        const pos = mockPos();
        pos.data.call = async () => { throw { data: { name: 'odoo.exceptions.ValidationError' } }; };
        await pos.baseerExecuteProtectedIntent(intent, key);
        assert.ok(storage.has(key));
    });
    await test('native sync skip cannot dispatch the protected command', async () => {
        const pos = mockPos(); let calls = 0;
        pos.syncAllOrders = async () => undefined;
        pos.data.call = async () => { calls++; };
        assert.equal(await pos.baseerSubmitProtectedAction({ order_id: order, uuid: 'source' }, 'cancel', {}), false);
        assert.equal(calls, 0);
        assert.equal(storage.size, 0);
    });
    await test('accepted output lock survives disabling the feature', () => {
        const line = { uuid: 'replacement', order_id: { finalized: false }, baseer_substitution_minimum_quantity: 2 };
        assert.equal(context.helpers.isSubstitutionOutputLine(line, { config: { baseer_substitution_enabled: false } }), true);
    });
    await test('startup reload recovers the durable intent with its original identity', async () => {
        storage.set(key, JSON.stringify(intent));
        const pos = mockPos(); pos.config = { id: 40 };
        let seen;
        pos.data.call = async (model, method, args) => { seen = args[2].action_uuid; return { accepted: true, action_uuid: seen }; };
        await pos.baseerRecoverProtectedActions();
        assert.equal(seen, 'stable-id');
        assert.equal(storage.has(key), false);
    });
    await test('concurrent submission cannot replace an in-flight durable intent', async () => {
        const pos = mockPos(); pos._baseerProtectedSubmissionRunning = true;
        pos.syncAllOrders = async () => { throw new Error('must not sync'); };
        assert.equal(await pos.baseerSubmitProtectedAction({ order_id: order, uuid: 'source' }, 'cancel', {}), false);
        assert.equal(storage.size, 0);
    });
    await test('canonical reconciliation drains removed-line commands before reload and persists before acknowledgement', async () => {
        const pos = mockPos(); const sequence = [];
        const local = { ...order, lines: [{ uuid: 'source', delete: () => sequence.push('delete-source') }] };
        const accepted = { ...order, state: 'draft', uiState: {}, lines: [{ uuid: 'replacement' }] };
        pos.models = {
            'pos.order': { getBy: () => local, serializeForORM: () => sequence.push('drain-commands') },
            loadConnectedData: () => { sequence.push('load-canonical'); return { 'pos.order': [accepted] }; },
        };
        pos.data.missingRecursive = async value => value;
        pos.data.deleteRecordsInIndexedDB = async () => sequence.push('delete-cache');
        pos.data.synchronizeLocalDataInIndexedDB = async () => sequence.push('persist');
        pos.removePendingOrder = () => sequence.push('remove-pending');
        await posMethods.baseerReconcileProtectedState.call(pos, { data: {
            'pos.order': [{ uuid: order.uuid }], 'pos.order.line': [{ uuid: 'replacement' }],
        } }, order.uuid);
        assert.deepEqual(sequence, ['delete-cache', 'delete-source', 'drain-commands', 'load-canonical', 'remove-pending', 'persist']);
        assert.equal(accepted.uiState.selected_orderline_uuid, 'replacement');
    });
})().catch(error => { console.error(error); process.exitCode = 1; });

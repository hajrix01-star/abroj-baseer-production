import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../static/src/app/draft_snapshot_experiment.js', import.meta.url), 'utf8');
const { syncDraftSnapshot, cancelDraftSnapshot, singleFlightDraftExperiment, createDraftSyncAdapterExperiment, runPaidAfterDraftExperiment, verifyPaidInvoiceExperiment, trackDraftGraphGeneration, attachDraftGenerationExperiment, detachServerAllowancesExperiment, acknowledgeDraftTombstonesExperiment, planDraftAckExperiment, mappedDraftDeletionExperiment } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('invoice remains pending without permission or an explicitly posted matching move', async () => {
    const pending = { order_uuid: 'order', payload_json: JSON.stringify({ to_invoice: true }) };
    const response = { 'pos.order': [{ uuid: 'order', account_move: 77 }] };
    assert.deepEqual(await verifyPaidInvoiceExperiment({ pending, response, readInvoice: async () => { throw new Error('access denied'); } }), { required: true, confirmed: false });
    assert.deepEqual(await verifyPaidInvoiceExperiment({ pending, response, readInvoice: async () => [{ id: 77, state: 'draft' }] }), { required: true, confirmed: false });
    assert.deepEqual(await verifyPaidInvoiceExperiment({ pending, response, readInvoice: async () => [{ id: 77, state: 'posted' }] }), { required: true, confirmed: true });
});

test('paid command waits for draft revision and lost ACK retries without collecting again', async () => {
    const makePending = (revision, cmd, state) => ({ order_uuid: 'order', revision, command_uuid: cmd, target_state: state,
        source_line_uuids: ['A'], source_payment_uuids: state === 'paid' ? ['P'] : [],
        payload_json: JSON.stringify({ uuid: 'order', state, baseer_offline_discount_intent: { expected_total: '90.00', expected_tax: '0.00' }, baseer_offline_draft_command: { revision, command_uuid: cmd, operation: 'keep' } }) });
    const state = { revision: 3, pending: makePending(3, 'draft-cmd', 'draft'), requests: [], collections: 1, losePaid: true };
    const adapter = {
        readPending: () => state.pending,
        createSnapshot: () => makePending(state.revision, 'paid-cmd', 'paid'),
        persistPending: async (pending) => { state.pending = structuredClone(pending); },
        send: async (payload) => {
            state.requests.push(JSON.stringify(payload));
            if (payload.state === 'paid' && state.losePaid) throw new Error('lost ACK');
            return { 'pos.order': [{ id: 42, uuid: 'order', state: payload.state, baseer_offline_draft_revision: payload.baseer_offline_draft_command.revision + 1,
                baseer_global_discount_locked: payload.state === 'paid', amount_total: 90, amount_tax: 0 }],
                'pos.order.line': [{ id: 12, uuid: 'A' }, ...(payload.state === 'paid' ? [{ id: 13, uuid: 'allowance', baseer_global_discount_line: true }] : [])],
                'pos.payment': payload.state === 'paid' ? [{ id: 20, uuid: 'P' }] : [] };
        },
        commitAck: async ({ revision }) => { state.revision = revision; state.pending = null; },
    };
    await assert.rejects(() => runPaidAfterDraftExperiment(adapter, { state: 'paid' }), /lost ACK/);
    assert.equal(state.revision, 4);
    assert.equal(state.pending.revision, 4);
    assert.equal(state.pending.target_state, 'paid');
    const pending = structuredClone(state.pending);
    const send = adapter.send;
    adapter.send = async () => { throw new Error('stale revision'); };
    await assert.rejects(() => runPaidAfterDraftExperiment(adapter, { state: 'paid' }), /stale revision/);
    assert.deepEqual(state.pending, pending);
    assert.equal(state.collections, 1);
    adapter.send = send;
    state.losePaid = false;
    await runPaidAfterDraftExperiment(adapter, { state: 'paid' });
    assert.equal(state.requests[1], state.requests[2]);
    assert.equal(state.revision, 5);
    assert.equal(state.collections, 1);
});

test('invoiced paid ACK requires the returned account move before it can be retained', async () => {
    const { input, state, snapshot } = fixture();
    const payload = JSON.parse(snapshot.payload_json);
    payload.to_invoice = true; payload.state = 'paid'; payload.baseer_offline_discount_intent = { expected_total: '90.00', expected_tax: '0.00' };
    snapshot.payload_json = JSON.stringify(payload); snapshot.target_state = 'paid';
    input.createSnapshot = () => structuredClone(snapshot);
    let committed;
    input.commitAck = async (ack) => { committed = ack; };
    input.send = async () => ({ 'pos.order': [{ id: 42, uuid: 'order', state: 'paid', account_move: 77, baseer_offline_draft_revision: 4, baseer_global_discount_locked: true, amount_total: 90, amount_tax: 0 }],
        'pos.order.line': [{ id: 12, uuid: 'A' }, { id: 13, uuid: 'allowance', baseer_global_discount_line: true }], 'account.move': [] });
    await assert.rejects(() => syncDraftSnapshot(input), /invoice acknowledgement/);
    assert.ok(state.pending);
    assert.equal(committed, undefined);
    input.send = async () => ({ 'pos.order': [{ id: 42, uuid: 'order', state: 'paid', account_move: 77, baseer_offline_draft_revision: 4, baseer_global_discount_locked: true, amount_total: 90, amount_tax: 0 }],
        'pos.order.line': [{ id: 12, uuid: 'A' }, { id: 13, uuid: 'allowance', baseer_global_discount_line: true }], 'account.move': [{ id: 77, name: 'INV/77' }] });
    await syncDraftSnapshot(input);
    assert.equal(committed.serverResponse['account.move'][0].id, 77);
});

test('POS draft adapter builds explicit set, keep and remove commands', () => {
    const intent = { kind: 'fixed', value: '10', preview_line_uuids: ['preview'] };
    const order = { uuid: 'order', state: 'draft', baseer_offline_draft_revision: 0,
        uiState: { baseerOfflineDiscount: intent }, lines: [{ uuid: 'A' }, { uuid: 'preview' }], payment_ids: [],
        serializeForORM: () => ({ uuid: 'order', baseer_offline_discount_intent: intent }) };
    const adapter = createDraftSyncAdapterExperiment({ data: { network: { offline: false }, orm: { call() {} } }, order,
        tracker: { get: () => 7 }, protect() {}, prepare() {}, getContext: () => ({ device: 1 }), offlineError: () => new Error('offline') });
    let snapshot = adapter.createSnapshot();
    assert.equal(JSON.parse(snapshot.payload_json).baseer_offline_draft_command.operation, 'set');
    assert.deepEqual(snapshot.source_line_uuids, ['A']);
    assert.equal(snapshot.generation, 7);
    order.uiState.baseerSharedDraftRevision = 1;
    order.uiState.baseerSharedDraftKind = 'fixed'; order.uiState.baseerSharedDraftValue = '10';
    snapshot = adapter.createSnapshot();
    assert.equal(JSON.parse(snapshot.payload_json).baseer_offline_draft_command.operation, 'keep');
    delete order.uiState.baseerOfflineDiscount;
    order.serializeForORM = () => ({ uuid: 'order' });
    snapshot = adapter.createSnapshot();
    assert.equal(JSON.parse(snapshot.payload_json).baseer_offline_draft_command.operation, 'remove');
});

test('shared draft edit sends intent and lines without stale server-owned discount fields', () => {
    const metadata = ['baseer_global_discount_kind', 'baseer_global_discount_value', 'baseer_global_discount_gross',
        'baseer_global_discount_locked', 'baseer_global_discount_reason', 'baseer_global_discount_snapshot',
        'baseer_offline_draft_kind', 'baseer_offline_draft_value', 'baseer_offline_draft_revision',
        'baseer_offline_draft_command_uuid', 'baseer_offline_draft_digest'];
    const intent = { kind: 'fixed', value: '10', preview_line_uuids: ['preview'] };
    const order = { uuid: 'shared', state: 'draft', baseer_offline_draft_revision: 1,
        uiState: { baseerOfflineDiscount: intent, baseerSharedDraftRevision: 1, baseerSharedDraftKind: 'fixed', baseerSharedDraftValue: '10' },
        lines: [{ uuid: 'original' }, { uuid: 'new-product' }, { uuid: 'preview' }], payment_ids: [],
        serializeForORM() { return { uuid: 'shared', lines: [[0, 0, { uuid: 'new-product', price_unit: 20 }]],
            baseer_offline_discount_intent: intent, ...Object.fromEntries(metadata.map((field) => [field, 'stale-server-value'])) }; } };
    const adapter = createDraftSyncAdapterExperiment({ data: { network: { offline: false }, orm: { call() {} } }, order,
        tracker: { get: () => 1 }, protect() {}, prepare() {}, getContext: () => ({}), offlineError: () => new Error('offline') });
    const payload = JSON.parse(adapter.createSnapshot().payload_json);
    for (const field of metadata) assert.equal(Object.hasOwn(payload, field), false, field);
    assert.equal(payload.baseer_offline_draft_command.operation, 'keep');
    assert.equal(payload.baseer_offline_discount_intent.value, '10');
    assert.equal(payload.lines[0][2].price_unit, 20);
});

test('single flight binds UUID and exact payload while other cashier edits continue', async () => {
    let release, calls = 0, local = ['A'];
    const gate = new Promise((resolve) => { release = resolve; });
    const first = singleFlightDraftExperiment('order', 'cmd', '{"v":1}', async () => { calls++; await gate; return 'ack'; });
    const retry = singleFlightDraftExperiment('order', 'cmd', '{"v":1}', () => { calls++; });
    assert.equal(first, retry);
    assert.throws(() => singleFlightDraftExperiment('order', 'cancel', '{"v":1}', () => {}), /pending/);
    assert.throws(() => singleFlightDraftExperiment('order', 'cmd', '{"v":2}', () => {}), /pending/);
    local.push('B');
    release();
    assert.equal(await first, 'ack');
    assert.equal(calls, 1);
    assert.deepEqual(local, ['A', 'B']);
    assert.equal(await singleFlightDraftExperiment('order', 'next', '{"v":2}', async () => 'next'), 'next');
});

test('experimental model adapter resumes the highest saved generation without adding a registry model', () => {
    const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
    const model = () => ({ addEventListener: () => () => {} });
    const models = Object.fromEntries(names.map((name) => [name, model()]));
    models['pos.order'].getAll = () => [{ uiState: { baseerSharedDraftGeneration: 8, baseerSharedDraftPending: { generation: 12 } } }];
    const tracker = attachDraftGenerationExperiment(models);
    assert.equal(tracker.get(), 12);
    assert.equal(attachDraftGenerationExperiment(models), tracker);
    assert.equal(Object.keys(models).includes('_baseerDraftGenerationTracker'), false);
    tracker.dispose();
});

test('ACK plan keeps later edits and refuses relinking an already deleted server record', () => {
    const pending = { order_uuid: 'order', command_uuid: 'cmd', revision: 3, generation: 5,
        source_line_uuids: ['A'], source_payment_uuids: ['P'], sent_line_deletion_tokens: ['old'], sent_line_deletion_ids: [19] };
    const current = { order_uuid: 'order', pending_command_uuid: 'cmd', generation: 7,
        line_uuids: ['B'], line_ids: [15], payment_uuids: [], payment_ids: [],
        line_deletions: [{ id: 19, token: 'old' }, { id: 19, token: 'later' }], payment_deletions: [] };
    const plan = planDraftAckExperiment({ pending, revision: 4, serverOrderId: 42, lineIds: { A: 12 }, paymentIds: { P: 21 }, current });
    assert.deepEqual(plan.line_deletions, [{ id: 19, token: 'later' }, { id: 12, token: 'cmd:line:A' }]);
    assert.deepEqual(plan.payment_deletions, [{ id: 21, token: 'cmd:payment:P' }]);
    assert.equal(plan.needs_sync, true);
    assert.equal(plan.server_order_id, 42);
    const stillLive = planDraftAckExperiment({ pending, revision: 4, serverOrderId: 42, lineIds: { A: 12 }, paymentIds: { P: 21 },
        current: { ...current, line_uuids: ['A', 'B'], payment_uuids: ['P'] } });
    assert.deepEqual(stillLive.line_ids_by_uuid, { A: 12 });
    assert.deepEqual(stillLive.payment_ids_by_uuid, { P: 21 });
    assert.deepEqual(mappedDraftDeletionExperiment({ uuid: 'A', token: 'later-delete', mapping: stillLive.line_ids_by_uuid, events: [] }), [{ id: 12, token: 'later-delete' }]);
    assert.throws(() => mappedDraftDeletionExperiment({ uuid: 'B', token: 'later-delete', mapping: stillLive.line_ids_by_uuid, events: [] }), /identity/);
    assert.throws(() => planDraftAckExperiment({ pending, revision: 4, serverOrderId: 42, lineIds: { A: 12 }, paymentIds: { P: 21 },
        current: { ...current, line_ids: [19] } }), /needs review/);
    assert.throws(() => planDraftAckExperiment({ pending, revision: 4, serverOrderId: 42, lineIds: { A: 12 }, paymentIds: { P: 21 },
        current: { ...current, pending_command_uuid: 'other' } }), /stale/);
});

test('acknowledgement removes only the sent deletion event, even if the same ID was deleted again', () => {
    const events = [{ id: 12, token: 'old' }, { id: 12, token: 'new' }, { id: 13, token: 'other' }];
    assert.deepEqual(acknowledgeDraftTombstonesExperiment(events, ['old']), events.slice(1));
    assert.throws(() => acknowledgeDraftTombstonesExperiment([events[0], events[0]], ['old']), /Invalid/);
});

test('local server-allowance detach keeps unrelated native removal commands', () => {
    const commands = { unlink: new Map([['lines', [{ parentId: 42, id: 12 }, { parentId: 99, id: 7 }]]]), delete: new Map() };
    const order = { id: 42, models: { commands: { 'pos.order': commands } }, lines: [] };
    const line = { id: 33, baseer_global_discount_line: true, model: { delete(record) {
        order.lines = order.lines.filter((item) => item !== record);
        commands.unlink.get('lines').push({ parentId: order.id, id: record.id });
    } } };
    order.lines.push(line, { id: 11, baseer_global_discount_line: false });
    assert.deepEqual(detachServerAllowancesExperiment(order), [33]);
    assert.deepEqual(order.lines.map((item) => item.id), [11]);
    assert.deepEqual(commands.unlink.get('lines'), [{ parentId: 42, id: 12 }, { parentId: 99, id: 7 }]);
    order.lines.push(line);
    commands.delete.set('lines', [{ parentId: 42, id: 33 }]);
    assert.throws(() => detachServerAllowancesExperiment(order), /already has/);
    assert.ok(order.lines.includes(line));
});

test('generation invalidates on any order, line, payment or custom attribute graph event', () => {
    const model = () => {
        const events = new Map();
        return { addEventListener(name, fn) { events.set(name, fn); return () => events.delete(name); },
            fire(name) { events.get(name)?.(); }, size: () => events.size };
    };
    const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
    const models = Object.fromEntries(names.map((name) => [name, model()]));
    const tracker = trackDraftGraphGeneration(models);
    for (const name of names) for (const event of ['create', 'update', 'delete']) models[name].fire(event);
    assert.equal(tracker.get(), 12);
    tracker.touch();
    assert.equal(tracker.get(), 13);
    tracker.dispose();
    assert.ok(names.every((name) => models[name].size() === 0));
    assert.throws(() => trackDraftGraphGeneration({}), /unavailable/);
});

function fixture() {
    const payload = { uuid: 'order', lines: [{ uuid: 'A' }], baseer_offline_draft_command: { revision: 3, command_uuid: 'command', operation: 'set' } };
    const snapshot = { order_uuid: 'order', revision: 3, command_uuid: 'command', source_line_uuids: ['A'], payload_json: JSON.stringify(payload) };
    const state = { pending: null, live: ['A'], removed: [], revision: 3, queue: true, calls: [] };
    const input = {
        readPending: () => state.pending,
        createSnapshot: () => structuredClone(snapshot),
        persistPending: async (saved) => { state.pending = structuredClone(saved); },
        send: async (sent) => { state.calls.push(JSON.stringify(sent)); return {
            'pos.order': [{ id: 42, uuid: 'order', baseer_offline_draft_revision: 4 }],
            'pos.order.line': [{ uuid: 'A', id: 12, baseer_global_discount_line: false }],
        }; },
        commitAck: async ({ pending, revision, lineIds }) => {
            assert.equal(state.pending.command_uuid, pending.command_uuid);
            for (const [uuid, id] of Object.entries(lineIds)) if (!state.live.includes(uuid)) state.removed.push(id);
            state.revision = revision; state.pending = null;
        },
    };
    return { input, state, snapshot };
}

test('isolated response preserves edits made while the RPC is pending', async () => {
    const { input, state } = fixture();
    let release, started;
    const gate = new Promise((resolve) => { release = resolve; });
    const begin = new Promise((resolve) => { started = resolve; });
    const send = input.send;
    input.send = async (payload) => { started(); await gate; return send(payload); };
    const running = syncDraftSnapshot(input);
    await begin;
    state.live = ['B'];
    release();
    await running;
    assert.deepEqual(state.live, ['B']);
    assert.deepEqual(state.removed, [12]);
    assert.equal(state.revision, 4);
    assert.equal(state.queue, true);
});

test('lost ACK after restart retries exactly and a stale rejection retains the pending snapshot', async () => {
    const { input, state, snapshot } = fixture();
    input.send = async (payload) => { state.calls.push(JSON.stringify(payload)); throw new Error('lost response'); };
    await assert.rejects(() => syncDraftSnapshot(input), /lost response/);
    const saved = structuredClone(state.pending);
    assert.deepEqual(saved, snapshot);
    state.pending = saved; // same native graph and intent after reopening
    input.createSnapshot = () => { throw new Error('must not rebuild'); };
    input.send = async (payload) => { state.calls.push(JSON.stringify(payload)); throw new Error('stale revision'); };
    await assert.rejects(() => syncDraftSnapshot(input), /stale revision/);
    assert.equal(state.calls[0], state.calls[1]);
    assert.deepEqual(state.pending, saved);
    assert.equal(state.revision, 3);
    assert.equal(state.queue, true);
});

test('persistence failure and incomplete acknowledgement never advance the revision', async () => {
    const { input, state } = fixture();
    input.persistPending = async () => { throw new Error('quota'); };
    await assert.rejects(() => syncDraftSnapshot(input), /quota/);
    assert.equal(state.calls.length, 0);
    input.persistPending = async (saved) => { state.pending = structuredClone(saved); };
    input.send = async () => ({ 'pos.order': [{ id: 42, uuid: 'order', baseer_offline_draft_revision: 4 }], 'pos.order.line': [] });
    await assert.rejects(() => syncDraftSnapshot(input), /line acknowledgement/);
    assert.equal(state.revision, 3);
    assert.ok(state.pending);
});

test('draft payment IDs must be present and are passed to guarded acknowledgement', async () => {
    const { input, state, snapshot } = fixture();
    snapshot.source_payment_uuids = ['pay'];
    input.createSnapshot = () => structuredClone(snapshot);
    let received;
    input.commitAck = async (value) => { received = value; };
    await assert.rejects(() => syncDraftSnapshot(input), /payment acknowledgement/);
    assert.ok(state.pending);
    input.send = async () => ({ 'pos.order': [{ id: 42, uuid: 'order', baseer_offline_draft_revision: 4 }],
        'pos.order.line': [{ uuid: 'A', id: 12 }], 'pos.payment': [{ uuid: 'pay', id: 20 }] });
    await syncDraftSnapshot(input);
    assert.deepEqual(received.paymentIds, { pay: 20 });
});

test('cancellation retries the same UUID and retains the order until verified acknowledgement', async () => {
    const state = { pending: null, exists: true, calls: [] };
    const input = {
        readPending: () => state.pending,
        createCancel: () => ({ order_uuid: 'order', revision: 3, command_uuid: 'cancel-cmd' }),
        persistPending: async (value) => { state.pending = structuredClone(value); },
        sendCancel: async (...args) => { state.calls.push(args); throw new Error('lost response'); },
        commitAck: async () => { state.exists = false; state.pending = null; },
    };
    await assert.rejects(() => cancelDraftSnapshot(input), /lost response/);
    assert.equal(state.exists, true);
    input.createCancel = () => { throw new Error('must not change cancellation UUID'); };
    input.sendCancel = async (...args) => { state.calls.push(args); throw new Error('stale revision'); };
    await assert.rejects(() => cancelDraftSnapshot(input), /stale revision/);
    assert.equal(state.exists, true);
    assert.deepEqual(state.calls[0], state.calls[1]);
    input.sendCancel = async () => ({ uuid: 'order', state: 'cancel', revision: 4 });
    await cancelDraftSnapshot(input);
    assert.equal(state.exists, false);
});

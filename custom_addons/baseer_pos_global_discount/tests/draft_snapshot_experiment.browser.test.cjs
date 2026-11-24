const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('playwright');

test('refreshing the POS catalog keeps drafts and pending payments in real IndexedDB', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const page = await browser.newPage();
        await page.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        await page.goto('http://baseer-pos-session-refresh.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/global_discount.js'), 'utf8');
        const start = source.indexOf('const localOrderStores');
        const end = source.indexOf('function localRecordsForRefresh', start);
        await page.addScriptTag({ content: source.slice(start, end) + '\nwindow.replacePosCatalog = replacePosCatalog;' });
        const result = await page.evaluate(async () => {
            const request = indexedDB.open('pos-session-refresh', 1);
            const models = ['pos.session', 'pos.config', 'product.product', 'pos.order', 'pos.order.line', 'pos.payment'];
            request.onupgradeneeded = () => {
                for (const model of models) request.result.createObjectStore(model, { keyPath: 'id' });
            };
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = reject; });
            const otherTabRequest = indexedDB.open('pos-session-refresh', 1);
            const otherTab = await new Promise((resolve, reject) => { otherTabRequest.onsuccess = () => resolve(otherTabRequest.result); otherTabRequest.onerror = reject; });
            const complete = (tx) => new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onabort = reject; });
            const first = db.transaction(models, 'readwrite');
            first.objectStore('pos.session').put({ id: 1, state: 'closed' });
            first.objectStore('pos.config').put({ id: 2, name: 'old' });
            first.objectStore('product.product').put({ id: 100 });
            first.objectStore('pos.order').put({ id: 42, state: 'draft', session_id: 1 });
            first.objectStore('pos.order.line').put({ id: 43, order_id: 42, product_id: 100 });
            await complete(first);
            const data = { indexedDB: { db }, opts: { databaseTable: {} } };
            const updating = window.replacePosCatalog(data, {
                'pos.session': [{ id: 3, state: 'opened' }],
                'pos.config': [{ id: 2, name: 'updated' }],
                'product.product': [{ id: 101 }],
                'pos.order': [{ id: 42, state: 'cancel' }],
                'pos.payment': [],
            });
            const concurrentPayment = otherTab.transaction(['pos.payment'], 'readwrite');
            concurrentPayment.objectStore('pos.payment').put({ id: 44, pos_order_id: 42, amount: 3 });
            await Promise.all([updating, complete(concurrentPayment)]);
            let aborted = false;
            try { await window.replacePosCatalog(data, { 'pos.session': [{ id: 4 }], 'pos.config': [{ name: 'missing key' }] }); }
            catch { aborted = true; }
            const read = db.transaction(models);
            const rows = await Promise.all(models.map((model) => new Promise((resolve, reject) => {
                const query = read.objectStore(model).getAll();
                query.onsuccess = () => resolve(query.result);
                query.onerror = reject;
            })));
            otherTab.close();
            db.close();
            return { aborted, rows };
        });
        assert.equal(result.aborted, true);
        assert.deepEqual(result.rows, [
            [{ id: 3, state: 'opened' }], [{ id: 2, name: 'updated' }], [{ id: 101 }],
            [{ id: 42, state: 'draft', session_id: 1 }], [{ id: 43, order_id: 42, product_id: 100 }],
            [{ id: 44, pos_order_id: 42, amount: 3 }],
        ]);
    } finally {
        await browser.close();
    }
});

test('fenced cancellation atomically keeps edited basket while removing old pending command', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const page = await browser.newPage();
        await page.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        await page.goto('http://baseer-fence-recovery.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `${source}\nwindow.persistCancelFenceRecovery = persistCancelFenceRecovery;` });
        const result = await page.evaluate(async () => {
            const request = indexedDB.open('fence-proof', 1);
            request.onupgradeneeded = () => {
                for (const name of ['pos.order', 'pos.order.line', 'pos.payment']) request.result.createObjectStore(name, { keyPath: 'uuid' });
                request.result.createObjectStore('product.attribute.custom.value', { keyPath: 'id' });
            };
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const pending = { order_uuid: 'order', revision: 3, command_uuid: 'old', generation: 1 };
            const order = { id: 42, uuid: 'order', state: 'draft', amount_total: 3,
                lines: [{ uuid: 'water', order_id: 42, quantity: 3, serializeForIndexedDB() { return { uuid: this.uuid, order_id: this.order_id, quantity: this.quantity }; } }], payment_ids: [],
                uiState: { baseerSharedDraftCancelPending: pending, baseerSharedDraftRemoveRequested: true, baseerSharedDraftNeedsSync: true },
                serializeForIndexedDB() { return { uuid: this.uuid, id: this.id, amount_total: this.amount_total, JSONuiState: JSON.stringify(this.uiState) }; } };
            const params = { data: { indexedDB: { db } }, order, tracker: { get: () => 2 }, pending, protect: () => {} };
            let rejected = false;
            try { await window.persistCancelFenceRecovery({ ...params, resolution: { outcome: 'fenced', uuid: 'order', state: 'draft', revision: 9 } }); }
            catch { rejected = true; }
            const retainedBefore = order.uiState.baseerSharedDraftCancelPending.command_uuid;
            await window.persistCancelFenceRecovery({ ...params, resolution: { outcome: 'fenced', uuid: 'order', state: 'draft', revision: 4 } });
            const read = (store, key) => new Promise((resolve, reject) => { const req = db.transaction(store).objectStore(store).get(key); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
            const persisted = await read('pos.order', 'order'); const line = await read('pos.order.line', 'water'); db.close();
            return { rejected, retainedBefore, persisted, line, memory: order.uiState };
        });
        assert.equal(result.rejected, true);
        assert.equal(result.retainedBefore, 'old');
        assert.equal(result.persisted.amount_total, 3);
        assert.equal(result.line.quantity, 3);
        const state = JSON.parse(result.persisted.JSONuiState);
        assert.equal(state.baseerSharedDraftRevision, 4);
        assert.equal(state.baseerSharedDraftNeedsSync, true);
        assert.equal(state.baseerSharedDraftRecoverySync, true);
        assert.equal(state.baseerSharedDraftRemoveRequested, true);
        assert.equal(state.baseerSharedDraftCancelPending, undefined);
        assert.equal(result.memory.baseerSharedDraftRevision, 4);
    } finally { await browser.close(); }
});

test('experimental isolated draft retains pending and later edits in real IndexedDB', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage();
        await page.goto('http://baseer-draft-snapshot.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `${source}\nwindow.syncDraftSnapshot = syncDraftSnapshot;` });
        const result = await page.evaluate(async () => {
            const open = indexedDB.open('snapshot-proof', 1);
            open.onupgradeneeded = () => open.result.createObjectStore('pos.order', { keyPath: 'uuid' });
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            const update = (change) => new Promise((resolve, reject) => {
                const tx = db.transaction(['pos.order'], 'readwrite');
                const store = tx.objectStore('pos.order');
                const request = store.get('order');
                request.onsuccess = () => store.put(change(request.result));
                tx.oncomplete = resolve; tx.onabort = () => reject(tx.error);
            });
            const read = () => new Promise((resolve, reject) => {
                const tx = db.transaction(['pos.order']); const request = tx.objectStore('pos.order').get('order');
                request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
            });
            await update(() => ({ uuid: 'order', revision: 3, lines: ['A'], removed: [], pending: null, queued: true }));
            const payload = { uuid: 'order', baseer_offline_draft_command: { revision: 3, command_uuid: 'cmd', operation: 'set' } };
            const snapshot = { order_uuid: 'order', command_uuid: 'cmd', revision: 3, source_line_uuids: ['A'], payload_json: JSON.stringify(payload) };
            let release, started;
            const gate = new Promise((resolve) => { release = resolve; });
            const begin = new Promise((resolve) => { started = resolve; });
            const pending = window.syncDraftSnapshot({
                readPending: () => null, createSnapshot: () => snapshot,
                persistPending: (value) => update((order) => ({ ...order, pending: value })),
                send: async () => { started(); await gate; return { 'pos.order': [{ id: 42, uuid: 'order', baseer_offline_draft_revision: 4 }],
                    'pos.order.line': [{ uuid: 'A', id: 12 }] }; },
                commitAck: ({ pending, revision, lineIds }) => update((order) => {
                    if (order.pending.command_uuid !== pending.command_uuid) throw new Error('conflicting command');
                    const removed = Object.entries(lineIds).filter(([uuid]) => !order.lines.includes(uuid)).map(([, id]) => id);
                    return { ...order, revision, removed, pending: null };
                }),
            });
            await begin;
            await update((order) => ({ ...order, lines: ['B'] }));
            release(); await pending;
            const saved = await read(); db.close(); return saved;
        });
        assert.deepEqual(result.lines, ['B']);
        assert.deepEqual(result.removed, [12]);
        assert.equal(result.revision, 4);
        assert.equal(result.pending, null);
        assert.equal(result.queued, true);
        await context.close();
    } finally { await browser.close(); }
});

test('experimental native-store transaction repeats on concurrent edit and preserves other orders', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage();
        await page.goto('http://baseer-draft-stores.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `${source}\nwindow.persistDraftGraphExperiment = persistDraftGraphExperiment;` });
        const result = await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const request = indexedDB.open('draft-native-stores', 1);
            request.onupgradeneeded = () => { for (const name of names) request.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); };
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const seed = db.transaction(names, 'readwrite');
            seed.objectStore('pos.order.line').put({ id: 11, uuid: 'old', order_id: 42 });
            seed.objectStore('pos.order.line').put({ id: 22, uuid: 'foreign', order_id: 99 });
            seed.objectStore('pos.payment').put({ uuid: 'old-pay', pos_order_id: 42 });
            seed.objectStore('product.attribute.custom.value').put({ id: 1, pos_order_line_id: 11 });
            seed.objectStore('product.attribute.custom.value').put({ id: 2, pos_order_line_id: 22 });
            await new Promise((resolve, reject) => { seed.oncomplete = resolve; seed.onabort = () => reject(seed.error); });
            let generation = 1, captures = 0, line = 'A';
            const capture = () => {
                captures++;
                const current = { generation, orderIds: [42, 'order'], records: {
                    'pos.order': [{ uuid: 'order', id: 42, revision: 4, pending: null, queued: true }],
                    'pos.order.line': [{ uuid: line, order_id: 42 }], 'pos.payment': [], 'product.attribute.custom.value': [],
                } };
                if (generation === 1) queueMicrotask(() => { generation = 2; line = 'B'; });
                return current;
            };
            await window.persistDraftGraphExperiment({ data: { indexedDB: { db } }, capture, currentGeneration: () => generation });
            let quota = false;
            try { await window.persistDraftGraphExperiment({ data: { indexedDB: { db: { transaction() { throw new DOMException('full', 'QuotaExceededError'); } } } }, capture, currentGeneration: () => generation }); }
            catch { quota = true; }
            let unstableAttempts = 0, unstableError = '';
            try { await window.persistDraftGraphExperiment({ data: { indexedDB: { db } }, currentGeneration: () => generation, capture: () => {
                unstableAttempts++;
                const result = capture();
                queueMicrotask(() => generation++);
                return result;
            } }); } catch (error) { unstableError = error.message; }
            db.close();
            const reopened = indexedDB.open('draft-native-stores', 1);
            const restored = await new Promise((resolve, reject) => { reopened.onsuccess = () => resolve(reopened.result); reopened.onerror = () => reject(reopened.error); });
            const tx = restored.transaction(names, 'readonly');
            const all = (name) => new Promise((resolve, reject) => { const r = tx.objectStore(name).getAll(); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
            const values = await Promise.all(names.map(all)); restored.close();
            return { captures, quota, unstableAttempts, unstableError, order: values[0], lines: values[1], payments: values[2], attributes: values[3] };
        });
        assert.equal(result.captures, 7); // two commits, one quota failure and four unstable captures
        assert.equal(result.unstableAttempts, 4);
        assert.match(result.unstableError, /kept changing/);
        assert.equal(result.quota, true);
        assert.equal(result.order[0].queued, true);
        assert.deepEqual(result.lines.map((line) => line.uuid).sort(), ['B', 'foreign']);
        assert.deepEqual(result.payments, []);
        assert.deepEqual(result.attributes.map((item) => item.id), [2]);
        await context.close();
    } finally { await browser.close(); }
});

test('remote deletion marker commits edited graph and survives database reopen; quota failure preserves previous graph', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-remote-delete.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        const ui = readFileSync(join(__dirname, '../static/src/app/global_discount.js'), 'utf8');
        const method = ui.slice(ui.indexOf('    async baseerAcceptRemoteSharedDeletionExperiment(order) {'), ui.indexOf('    async baseerReconcileSharedPaidExperiment(order) {'));
        await page.addScriptTag({ content: `${source}\nconst sharedRemoteDeleteOrders = new WeakSet(); const sharedLocalRecoveryOrders = new WeakSet(); const _t = x => x; const isManagedSharedDraft = () => true; attachDraftGenerationExperiment = () => ({get: () => 1}); const protectOfflineStorage = () => {}; window.remoteDelete = ({${method}}).baseerAcceptRemoteSharedDeletionExperiment;` });
        const result = await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const open = () => new Promise((resolve, reject) => { const req = indexedDB.open('remote-delete', 1); req.onupgradeneeded = () => { for (const name of names) req.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); }; req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
            let db = await open();
            const makeOrder = (uuid) => ({ id: 42, uuid, state: 'draft', payment_ids: [], uiState: { baseerOfflineDiscount: {} }, lines: [{ id: 11, uuid: 'edited-line', custom_attribute_value_ids: [], serializeForIndexedDB() { return { id: 11, uuid: this.uuid, order_id: 42, qty: 3 }; } }], serializeForIndexedDB() { return { id: this.id, uuid: this.uuid, JSONuiState: JSON.stringify(this.uiState) }; } });
            const first = makeOrder('order');
            await window.remoteDelete.call({ models: {}, data: { indexedDB: { db } } }, first);
            db.close(); db = await open();
            const read = (store) => new Promise((resolve, reject) => { const r = db.transaction([store]).objectStore(store).getAll(); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
            const orders = await read('pos.order'); const lines = await read('pos.order.line');
            const second = makeOrder('other'); let failed = false;
            try { await window.remoteDelete.call({ models: {}, data: { indexedDB: { db: { transaction() { throw new DOMException('full', 'QuotaExceededError'); } } } } }, second); } catch { failed = true; }
            const preserved = await read('pos.order'); db.close();
            return { state: JSON.parse(orders[0].JSONuiState), lines, failed, second: second.uiState, preserved };
        });
        assert.equal(result.state.baseerSharedDraftRemoteDeleted, true);
        assert.equal(result.lines[0].qty, 3);
        assert.equal(result.failed, true);
        assert.match(result.second.baseerSharedDraftRefreshError, /local storage/);
        assert.equal(result.preserved.length, 1);
        await context.close();
    } finally { await browser.close(); }
});

test('experimental lost ACK reuses the persisted command after real browser reload', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage();
        await page.goto('http://baseer-draft-retry.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        const install = () => page.addScriptTag({ content: `${source}\nwindow.syncDraftSnapshot = syncDraftSnapshot;` });
        await install();
        const first = await page.evaluate(async () => {
            const open = indexedDB.open('draft-retry', 1);
            open.onupgradeneeded = () => open.result.createObjectStore('pos.order', { keyPath: 'uuid' });
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            const payload = { uuid: 'order', lines: [{ uuid: 'A', qty: 1 }], baseer_offline_draft_command: { revision: 3, command_uuid: 'cmd', operation: 'set' } };
            const snapshot = { order_uuid: 'order', revision: 3, command_uuid: 'cmd', source_line_uuids: ['A'], payload_json: JSON.stringify(payload) };
            let sent;
            try { await window.syncDraftSnapshot({ readPending: () => null, createSnapshot: () => snapshot,
                persistPending: (pending) => new Promise((resolve, reject) => { const tx = db.transaction(['pos.order'], 'readwrite'); tx.objectStore('pos.order').put({ uuid: 'order', pending, queued: true }); tx.oncomplete = resolve; tx.onabort = () => reject(tx.error); }),
                send: async (value) => { sent = JSON.stringify(value); throw new Error('lost ACK'); }, commitAck: () => { throw new Error('must not acknowledge'); },
            }); } catch (error) { if (error.message !== 'lost ACK') throw error; }
            db.close(); return sent;
        });
        await page.reload(); await install();
        const second = await page.evaluate(async () => {
            const open = indexedDB.open('draft-retry', 1);
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            const read = db.transaction(['pos.order']).objectStore('pos.order').get('order');
            const saved = await new Promise((resolve, reject) => { read.onsuccess = () => resolve(read.result); read.onerror = () => reject(read.error); });
            let sent, committed = false;
            await window.syncDraftSnapshot({ readPending: () => saved.pending, createSnapshot: () => { throw new Error('recreated'); }, persistPending: () => { throw new Error('rewritten'); },
                send: async (value) => { sent = JSON.stringify(value); return { 'pos.order': [{ id: 42, uuid: 'order', baseer_offline_draft_revision: 4 }], 'pos.order.line': [{ uuid: 'A', id: 12 }] }; },
                commitAck: async () => { committed = true; },
            });
            db.close(); return { sent, committed, queued: saved.queued };
        });
        assert.equal(second.sent, first);
        assert.equal(second.committed, true);
        assert.equal(second.queued, true);
        await context.close();
    } finally { await browser.close(); }
});

test('experimental native order adapter commits pending command with the latest complete graph', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-draft-adapter.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `${source}\nwindow.persistPendingDraftOrderExperiment = persistPendingDraftOrderExperiment;` });
        const result = await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const open = indexedDB.open('draft-adapter', 1);
            open.onupgradeneeded = () => { for (const name of names) open.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); };
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            let generation = 0, protectedOrder = false, changed = false;
            const tracker = { get: () => generation, touch: () => { generation++; } };
            const line = (uuid) => ({ uuid, custom_attribute_value_ids: [], serializeForIndexedDB: () => ({ uuid, order_id: 42 }) });
            const order = { id: 42, uuid: 'order', state: 'draft', uiState: { discount: 10 }, lines: [line('A')], payment_ids: [],
                serializeForIndexedDB() {
                    if (!changed) { changed = true; queueMicrotask(() => { this.lines = [line('B')]; tracker.touch(); }); }
                    return { uuid: this.uuid, id: this.id, state: this.state, JSONuiState: JSON.stringify(this.uiState) };
                } };
            const payload = { uuid: 'order', baseer_offline_draft_command: { revision: 0, command_uuid: 'cmd', operation: 'set' } };
            const pending = { order_uuid: 'order', revision: 0, command_uuid: 'cmd', source_line_uuids: ['A'], payload_json: JSON.stringify(payload) };
            await window.persistPendingDraftOrderExperiment({ data: { indexedDB: { db } }, order, tracker, pending, protect: () => { protectedOrder = true; } });
            const tx = db.transaction(names, 'readonly');
            const all = (name) => new Promise((resolve, reject) => { const request = tx.objectStore(name).getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const [orders, lines] = await Promise.all([all('pos.order'), all('pos.order.line')]);
            db.close(); return { protectedOrder, order: orders[0], lines, memory: order.uiState, generation };
        });
        assert.equal(result.protectedOrder, true);
        assert.deepEqual(result.lines.map((line) => line.uuid), ['B']);
        assert.equal(JSON.parse(result.order.JSONuiState).baseerSharedDraftPending.command_uuid, 'cmd');
        assert.equal(result.memory.baseerSharedDraftPending.command_uuid, 'cmd');
        assert.equal(result.generation, 1);
        await context.close();
    } finally { await browser.close(); }
});

test('experimental ACK commit retains a newer graph and persists UUID deletion mapping atomically', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-draft-ack.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `${source}\nwindow.persistDraftAckExperiment = persistDraftAckExperiment;` });
        const result = await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const open = indexedDB.open('draft-ack', 1);
            open.onupgradeneeded = () => { for (const name of names) open.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); };
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            let generation = 1, changed = false;
            const tracker = { get: () => generation, touch: () => { generation++; } };
            const line = (uuid) => ({ id: uuid, uuid, custom_attribute_value_ids: [], serializeForIndexedDB: () => ({ uuid, order_id: 42 }) });
            const pending = { order_uuid: 'order', command_uuid: 'cmd', revision: 3, generation: 0, source_line_uuids: ['A'], source_payment_uuids: [], sent_legacy_line_deletion_ids: [17], payload_json: JSON.stringify({ baseer_offline_discount_intent: { kind: 'fixed', value: '10' } }) };
            const order = { id: 42, uuid: 'order', state: 'draft', lines: [line('B')], payment_ids: [], uiState: { baseerSharedDraftPending: pending,
                baseerSharedDraftLineDeletions: [{ id: 17, token: 'later' }], baseerOfflineDiscount: { kind: 'fixed', value: '10', preview_line_uuids: [], removed_line_ids: [17, 18] } },
                serializeForIndexedDB() {
                    if (!changed) { changed = true; queueMicrotask(() => {
                        this.lines = [line('C')]; this.state = 'paid';
                        this.payment_ids = [{ uuid: 'pay', serializeForIndexedDB: () => ({ uuid: 'pay', pos_order_id: 42, amount: 90 }) }];
                        tracker.touch();
                    }); }
                    return { uuid: this.uuid, id: this.id, state: this.state, JSONuiState: JSON.stringify(this.uiState) };
                } };
            const plan = await window.persistDraftAckExperiment({ data: { indexedDB: { db } }, order, tracker, pending, revision: 4, serverOrderId: 42, lineIds: { A: 12 }, paymentIds: {}, protect() {} });
            const tx = db.transaction(names, 'readonly');
            const all = (name) => new Promise((resolve, reject) => { const request = tx.objectStore(name).getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const [orders, lines, payments] = await Promise.all([all('pos.order'), all('pos.order.line'), all('pos.payment')]);
            db.close(); return { plan, saved: JSON.parse(orders[0].JSONuiState), state: orders[0].state, lines, payments, memory: order.uiState };
        });
        assert.deepEqual(result.lines.map((line) => line.uuid), ['C']);
        assert.equal(result.saved.baseerSharedDraftRevision, 4);
        assert.equal(result.saved.baseerSharedDraftPending, undefined);
        assert.equal(result.saved.baseerSharedDraftNeedsSync, true);
        assert.equal(result.state, 'paid');
        assert.equal(result.payments[0].amount, 90);
        assert.deepEqual(result.saved.baseerSharedDraftLineDeletions, [{ id: 17, token: 'later' }, { id: 12, token: 'cmd:line:A' }]);
        assert.deepEqual(result.saved.baseerOfflineDiscount.removed_line_ids, [18]);
        assert.deepEqual(result.memory, result.saved);
        await context.close();
    } finally { await browser.close(); }
});

test('paid ACK must not persist provisional warning if a real conflict arrives during IndexedDB transaction', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-paid-ack-conflict.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        const globalSource = readFileSync(join(__dirname, '../static/src/app/global_discount.js'), 'utf8');
        const start = globalSource.indexOf('function touchExperimentalDraftGraph('), end = globalSource.indexOf('\nfunction noteSharedDraftEdit(', start);
        assert.ok(start >= 0 && end > start);
        await page.addScriptTag({ content: `${source}\nconst sharedRevisionWarningOwners = new WeakMap();\n${globalSource.slice(start, end)}\nwindow.persistPaidAck = persistDraftAckExperiment; window.markProvisionalWarningConflicted = markProvisionalWarningConflicted;` });
        const result = await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const open = indexedDB.open('paid-ack-conflict', 1);
            open.onupgradeneeded = () => { for (const name of names) open.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); };
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            const pending = { order_uuid: 'order', command_uuid: 'paid', revision: 1, target_state: 'paid', generation: 5,
                source_line_uuids: ['food'], source_payment_uuids: ['bank'], payload_json: '{}' };
            const order = { id: 42, uuid: 'order', state: 'paid',
                uiState: { baseerSharedDraftPending: pending, baseerSharedDraftRevisionWarningProvisional: true,
                    baseerSharedDraftRefreshError: 'The shared order changed on another device. Keep your local changes for review.' },
                lines: [{ id: 'food', uuid: 'food', custom_attribute_value_ids: [], serializeForIndexedDB() { return { uuid: 'food', id: 'food', order_id: 42 }; } }],
                payment_ids: [{ id: 'bank', uuid: 'bank', serializeForIndexedDB() { return { uuid: 'bank', id: 'bank', pos_order_id: 42, amount: 3 }; } }],
                serializeForIndexedDB() { return { id: 42, uuid: 'order', state: 'paid', JSONuiState: JSON.stringify(this.uiState) }; } };
            let conflictBeforeComplete = false, generation = 5;
            const tracker = { get: () => generation, touch: () => { generation++; } };
            order.models = { _baseerDraftGenerationTracker: tracker };
            const proxyDb = { transaction(...args) {
                const tx = db.transaction(...args);
                if (!conflictBeforeComplete) queueMicrotask(() => { window.markProvisionalWarningConflicted(order); conflictBeforeComplete = true; });
                return tx;
            } };
            await window.persistPaidAck({ data: { indexedDB: { db: proxyDb } }, order, tracker, pending,
                revision: 2, serverOrderId: 42, lineIds: { food: 11 }, paymentIds: { bank: 12 },
                serverResponse: { 'pos.order': [{ id: 42, uuid: 'order', state: 'paid' }] }, protect() {} });
            const saved = await new Promise((resolve, reject) => { const tx = db.transaction(['pos.order'], 'readonly');
                const request = tx.objectStore('pos.order').get('order'); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            db.close(); return { conflictBeforeComplete, live: order.uiState, saved: JSON.parse(saved.JSONuiState) };
        });
        assert.equal(result.conflictBeforeComplete, true);
        assert.equal(result.live.baseerSharedDraftRevisionWarningProvisional, undefined);
        assert.equal(result.saved.baseerSharedDraftRevisionWarningProvisional, undefined, 'durable ACK must retain the independent conflict');
        assert.equal(result.saved.baseerSharedDraftNeedsSync, true, 'a later edit requires review');
        assert.ok(result.saved.baseerSharedDraftRefreshError);
        await context.close();
    } finally { await browser.close(); }
});

test('experimental cancel ACK is durable and retains later edits for review', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-draft-cancel.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/draft_snapshot_experiment.js'), 'utf8').replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `${source}\nwindow.persistDraftCancelExperiment = persistDraftCancelExperiment;` });
        const result = await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const open = indexedDB.open('draft-cancel', 1);
            open.onupgradeneeded = () => { for (const name of names) open.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); };
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            let generation = 0;
            const tracker = { get: () => generation, touch: () => { generation++; } };
            const line = (uuid) => ({ uuid, custom_attribute_value_ids: [], serializeForIndexedDB: () => ({ uuid, order_id: 42 }) });
            const order = { id: 42, uuid: 'order', state: 'draft', lines: [line('A')], payment_ids: [], uiState: {},
                serializeForIndexedDB() { return { uuid: this.uuid, id: this.id, state: this.state, JSONuiState: JSON.stringify(this.uiState) }; } };
            const pending = { order_uuid: 'order', revision: 3, command_uuid: 'cancel', generation: 0 };
            const args = { data: { indexedDB: { db } }, order, tracker, pending, protect() {} };
            await window.persistDraftCancelExperiment(args);
            order.lines.push(line('B')); tracker.touch();
            const ack = await window.persistDraftCancelExperiment({ ...args, acknowledgement: { uuid: 'order', state: 'cancel', revision: 4 } });
            const tx = db.transaction(names, 'readonly');
            const all = (name) => new Promise((resolve, reject) => { const request = tx.objectStore(name).getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const [orders, lines] = await Promise.all([all('pos.order'), all('pos.order.line')]);
            db.close(); return { ack, state: JSON.parse(orders[0].JSONuiState), lines: lines.map((item) => item.uuid).sort() };
        });
        assert.equal(result.ack.needsReview, true);
        assert.deepEqual(result.lines, ['A', 'B']);
        assert.equal(result.state.baseerSharedDraftCancelPending, undefined);
        assert.equal(result.state.baseerSharedDraftCancelAcknowledged.revision, 4);
        assert.equal(result.state.baseerSharedDraftCancelAcknowledged.needs_review, true);
        await context.close();
    } finally { await browser.close(); }
});

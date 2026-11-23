const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('playwright');

test('native IndexedDB commits order, lines and payment together; abort and quota fail closed', async () => {
    const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage();
        await page.goto('http://baseer-native-pos-test.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/offline_persistence.js'), 'utf8').replace('export async function', 'async function');
        await page.addScriptTag({ content: `${source}\nwindow.persist = persistNativeOfflinePaidOrder;` });
        const result = await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const request = indexedDB.open('synthetic-native-pos', 1);
            request.onupgradeneeded = () => {
                for (const name of names) request.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' });
            };
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const record = (raw) => ({ ...raw, serializeForIndexedDB: () => raw });
            function makeOrder(suffix, badPayment = false) {
                const intent = { kind: 'fixed', value: '10', order_uuid: `order-${suffix}` };
                const order = record({ uuid: `order-${suffix}`, id: 42, state: 'paid', JSONuiState: JSON.stringify({ baseerOfflineDiscount: intent }) });
                order.uiState = { baseerOfflineDiscount: intent };
                order.lines = [record({ id: 22, uuid: `line-${suffix}`, order_id: 42, qty: 1 })];
                order.lines[0].custom_attribute_value_ids = [record({ id: 3, pos_order_line_id: 22, custom_value: 'retained' })];
                order.payment_ids = [record(badPayment ? { amount: 90, pos_order_id: 42 } : { uuid: `pay-${suffix}`, pos_order_id: 42, amount: 90 })];
                return order;
            }
            // A stale previous draft line and payment must be removed, while
            // rows owned by another order must survive the same transaction.
            await new Promise((resolve, reject) => {
                const tx = db.transaction(['pos.order.line', 'pos.payment', 'product.attribute.custom.value'], 'readwrite');
                tx.objectStore('pos.order.line').put({ id: 11, uuid: 'stale-line', order_id: 42 });
                tx.objectStore('pos.order.line').put({ id: 99, uuid: 'other-line', order_id: 99 });
                tx.objectStore('pos.order.line').put({ id: 44, uuid: 'moved-line', order_id: 42 });
                tx.objectStore('pos.payment').put({ uuid: 'stale-pay', pos_order_id: 42 });
                tx.objectStore('pos.payment').put({ uuid: 'other-pay', pos_order_id: 99 });
                for (const item of [{ id: 1, pos_order_line_id: 11 }, { id: 2, pos_order_line_id: 99 },
                    { id: 3, pos_order_line_id: 22 }, { id: 4, pos_order_line_id: 44 }]) tx.objectStore('product.attribute.custom.value').put(item);
                tx.oncomplete = resolve; tx.onabort = () => reject(tx.error);
            });
            const data = { indexedDB: { db }, models: { 'pos.order.line': { getBy: (_key, uuid) =>
                uuid === 'moved-line' ? { order_id: { id: 99 } } : undefined } } };
            await window.persist(data, makeOrder('ok'));
            let aborted = false;
            try { await window.persist({ indexedDB: { db } }, makeOrder('bad', true)); } catch { aborted = true; }
            let quotaRejected = false;
            try { await window.persist({ indexedDB: { db: { transaction() { throw new DOMException('full', 'QuotaExceededError'); } } } }, makeOrder('quota')); }
            catch (error) { quotaRejected = error.name === 'QuotaExceededError'; }
            db.close(); return { aborted, quotaRejected };
        });
        assert.deepEqual(result, { aborted: true, quotaRejected: true });
        await page.reload();
        const rows = await page.evaluate(async () => {
            const request = indexedDB.open('synthetic-native-pos', 1);
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const tx = db.transaction(names, 'readonly');
            const all = await Promise.all(names.map((name) => new Promise((resolve, reject) => {
                const req = tx.objectStore(name).getAll(); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
            })));
            db.close(); return all;
        });
        assert.deepEqual(rows.map((items) => items.length), [1, 3, 2, 3]);
        assert.equal(rows[0][0].id, 42);
        assert.equal(JSON.parse(rows[0][0].JSONuiState).baseerOfflineDiscount.value, '10');
        assert.deepEqual(rows[1].map((row) => row.uuid).sort(), ['line-ok', 'moved-line', 'other-line']);
        assert.deepEqual(rows[2].map((row) => row.uuid).sort(), ['other-pay', 'pay-ok']);
        assert.deepEqual(rows[3].map((row) => row.id).sort(), [2, 3, 4]);
        await context.close();
    } finally { await browser.close(); }
});

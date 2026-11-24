const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('playwright');

test('real IndexedDB reset guard preserves a locally paid order across reload', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage();
        await page.goto('http://baseer-reset-test.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/global_discount.js'), 'utf8')
            .replace(/^import .*;\r?\n/gm, '').replace('export class', 'class');
        const mocks = `
            const extensions = new Map();
            const patch = (target, extension) => { Object.setPrototypeOf(extension, target); extensions.set(target.constructor.name, extension); };
            const _t = (value) => value; const session = { db: 'synthetic' };
            class Component {} class Dialog {} class AlertDialog {} class PosData { async resetIndexedDB() { this.resetCalled = true; } }
            class DevicesSynchronisation {} class ControlButtons {} class PosStore {} class PosOrder {} class PosOrderline {}
            class TicketScreen {} class PaymentScreen {} class OrderSummary {} class OrderPaymentValidation {}
            class ConnectionLostError extends Error {} class RPCError extends Error {}
        `;
        await page.addScriptTag({ content: `${mocks}\n${source}\nwindow.resetExtension = extensions.get('PosData');` });
        const result = await page.evaluate(async () => {
            const request = indexedDB.open('synthetic-native-pos-cache', 1);
            request.onupgradeneeded = () => request.result.createObjectStore('pos.order', { keyPath: 'uuid' });
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const put = (value) => new Promise((resolve, reject) => {
                const tx = db.transaction(['pos.order'], 'readwrite');
                tx.objectStore('pos.order').put(value);
                tx.oncomplete = resolve; tx.onabort = () => reject(tx.error);
            });
            const order = { uuid: 'paid-order', id: 42, state: 'paid', baseer_global_discount_locked: false,
                JSONuiState: JSON.stringify({ baseerOfflineDiscount: { kind: 'fixed', value: '10' } }) };
            await put(order);
            const data = { indexedDB: { db, readAll: async () => {
                const tx = db.transaction(['pos.order'], 'readonly');
                const request = tx.objectStore('pos.order').getAll();
                const orders = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
                return { 'pos.order': orders, 'pos.order.line': [] };
            } } };
            let blocked = false;
            try { await window.resetExtension.resetIndexedDB.call(data); } catch { blocked = true; }
            const resetBeforeAcknowledgement = !!data.resetCalled;
            db.close();
            return { blocked, resetBeforeAcknowledgement };
        });
        assert.deepEqual(result, { blocked: true, resetBeforeAcknowledgement: false });
        await page.reload();
        const saved = await page.evaluate(async () => {
            const request = indexedDB.open('synthetic-native-pos-cache', 1);
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const tx = db.transaction(['pos.order'], 'readonly');
            const read = tx.objectStore('pos.order').get('paid-order');
            const order = await new Promise((resolve, reject) => { read.onsuccess = () => resolve(read.result); read.onerror = () => reject(read.error); });
            db.close(); return order;
        });
        assert.equal(saved.state, 'paid');
        assert.equal(saved.id, 42);
        assert.equal(JSON.parse(saved.JSONuiState).baseerOfflineDiscount.value, '10');
        await context.close();
    } finally { await browser.close(); }
});

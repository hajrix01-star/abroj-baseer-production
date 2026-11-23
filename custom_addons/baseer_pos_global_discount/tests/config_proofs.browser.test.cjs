const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('playwright');

test('missing account proofs refresh only the native config cache and survive reload', async () => {
    const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage();
        await page.goto('http://baseer-proof-test.invalid/');
        const source = readFileSync(join(__dirname, '../static/src/app/global_discount.js'), 'utf8');
        const helper = source.slice(source.indexOf('async function refreshMissingAccountProofs'), source.indexOf('\nfunction protectOfflineStorage'));
        await page.addScriptTag({ content: `${helper}\nwindow.refreshProofs = refreshMissingAccountProofs;` });
        const result = await page.evaluate(async () => {
            const request = indexedDB.open('proof-cache', 1);
            request.onupgradeneeded = () => {
                for (const name of ['pos.config', 'pos.order', 'pos.payment']) request.result.createObjectStore(name, { keyPath: 'id' });
            };
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const tx = db.transaction(['pos.config', 'pos.order', 'pos.payment'], 'readwrite');
            tx.objectStore('pos.config').put({ id: 97, name: 'original', baseer_global_discount_enabled: true });
            tx.objectStore('pos.order').put({ id: 42, state: 'paid', intent: { account_proof: 'old' } });
            tx.objectStore('pos.payment').put({ id: 7, amount: 90 });
            await new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onabort = () => reject(tx.error); });
            let reads = 0;
            const config = { id: 97, baseer_global_discount_enabled: true, update(values) { Object.assign(this, values); } };
            const pos = { config, data: { network: { offline: false }, indexedDB: { db }, orm: { read: async () => { reads++; return [{ id: 97, baseer_offline_discount_account_proofs: { 0: 'a'.repeat(64) } }]; } } } };
            await window.refreshProofs(pos);
            await window.refreshProofs(pos);
            const refreshed = config.baseer_offline_discount_account_proofs['0'];
            const offline = { ...pos, config: { id: 97, baseer_global_discount_enabled: true }, data: { ...pos.data, network: { offline: true } } };
            await window.refreshProofs(offline);
            const failed = { ...pos, config: { id: 97, baseer_global_discount_enabled: true }, data: { ...pos.data, indexedDB: { db: { transaction() { throw new DOMException('full', 'QuotaExceededError'); } } } } };
            let blocked = false;
            try { await window.refreshProofs(failed); } catch { blocked = true; }
            db.close();
            return { reads, refreshed, blocked, failedProofs: failed.config.baseer_offline_discount_account_proofs || null };
        });
        assert.deepEqual(result, { reads: 2, refreshed: 'a'.repeat(64), blocked: true, failedProofs: null });
        await page.reload();
        const saved = await page.evaluate(async () => {
            const request = indexedDB.open('proof-cache', 1);
            const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const tx = db.transaction(['pos.config', 'pos.order', 'pos.payment'], 'readonly');
            const get = (name, id) => new Promise((resolve, reject) => { const req = tx.objectStore(name).get(id); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
            const values = await Promise.all([get('pos.config', 97), get('pos.order', 42), get('pos.payment', 7)]); db.close(); return values;
        });
        assert.equal(saved[0].name, 'original');
        assert.equal(saved[0].baseer_offline_discount_account_proofs['0'], 'a'.repeat(64));
        assert.deepEqual(saved[1], { id: 42, state: 'paid', intent: { account_proof: 'old' } });
        assert.deepEqual(saved[2], { id: 7, amount: 90 });
        await context.close();
    } finally { await browser.close(); }
});

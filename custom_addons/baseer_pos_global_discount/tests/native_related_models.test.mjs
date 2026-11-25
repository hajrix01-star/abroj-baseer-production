import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '../../../tmp');
const related = resolve(root, 'odoo_related_models');
const files = [resolve(root, 'odoo_proxy_trap.js'), resolve(root, 'odoo_lazy_getter.js'),
    ...['utils', 'base', 'record_store', 'model_defs', 'model_classes', 'serialization', 'index'].map((name) => resolve(related, `${name}.js`))];
function nativeBundle() {
    const source = files.map((file) => readFileSync(file, 'utf8')
        .replace(/^import\s[\s\S]*?;\s*$/gm, '')
        .replace(/^export\s*\{[^}]+\}\s*from\s*[^;]+;\s*$/gm, '')
        .replace(/^export\s+(?=(?:class|function|const|let)\b)/gm, '')).join('\n');
    const stubs = `
        const luxon = { DateTime: {} }; let sequence = 0;
        const uuidv4 = () => 'generated-' + (++sequence);
        const reactive = (value) => value, toRaw = (value) => value;
        const effect = () => () => {};
        const serializeDateTime = (value) => value, serializeDate = (value) => value;
        const deserializeDateTime = (value) => value, deserializeDate = (value) => value;
    `;
    return `${stubs}\n${source}`;
}
function loadNative() { return new Function(`${nativeBundle()}\nreturn { createRelatedModels };`)(); }
test('native POS startup drops locally stored product lines if their product is absent from loaded models', async () => {
    const native = readFileSync('tmp/pos-discount-native-data-service.js', 'utf8');
    const method = (start, end) => { const a = native.indexOf(start), b = native.indexOf(end, a); assert.ok(a >= 0 && b > a); return native.slice(a, b); };
    const getLocal = method('    async getLocalDataFromIndexedDB(data = false) {', '    async getCachedServerDataFromIndexedDB(');
    const recursive = method('    async missingRecursive(recordMap, idsMap = {}, acc = {}) {', '    async syncData() {');
    const Native = new Function(`return class { ${getLocal} ${recursive} }`)();
    const data = { 'pos.order': [{ id: 'order', uuid: 'order', lines: ['food', 'preview'] }],
        'pos.order.line': [{ id: 'food', uuid: 'food', order_id: 'order', product_id: 264 }, { id: 'preview', uuid: 'preview', order_id: 'order', product_id: 266 }] };
    const run = async (products) => {
        const service = new Native(); service.opts = { databaseTable: {}, pohibitedAutoLoadedModels: [], prohibitedAutoLoadedFields: {} };
        service.network = { offline: false }; service.relations = {};
        service.models = { 'product.product': { map: (fn) => products.map((id) => fn({ id })) }, loadConnectedData(rows) { return rows; } };
        service.preLoadData = async (rows) => structuredClone(rows); service.checkAndDeleteMissingOrders = async () => {};
        return service.getLocalDataFromIndexedDB(structuredClone(data));
    };
    assert.deepEqual((await run([266]))['pos.order.line'].map((line) => line.uuid), ['preview']);
    assert.deepEqual((await run([264, 266]))['pos.order.line'].map((line) => line.uuid), ['food', 'preview']);
    const service = new Native(); service.network = { offline: false };
    service.opts = { pohibitedAutoLoadedModels: [], prohibitedAutoLoadedFields: {} };
    service.relations = { 'pos.order': { lines: { name: 'lines', model: 'pos.order', type: 'one2many', relation: 'pos.order.line' } } };
    service.models = { 'pos.order.line': { get: () => undefined } };
    service.fields = { 'pos.order.line': [] };
    service.orm = { read: async () => [{ id: 634, uuid: 'food', order_id: 260, product_id: 264 }] };
    const input = structuredClone(data); input['pos.order'].push({ id: 'other', uuid: 'other', lines: [634] });
    const resolved = await service.missingRecursive(input);
    assert.deepEqual(resolved['pos.order.line'].filter((line) => line.uuid === 'food').map((line) => line.id), ['food', 634]);
});

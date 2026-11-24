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
const expSource = readFileSync(new URL('../static/src/app/draft_snapshot_experiment.js', import.meta.url), 'utf8');
const { detachServerAllowancesExperiment, replaceServerAllowancesExperiment, hydrateSharedDraftExperiment, stageNativeServerGraphExperiment, stagePaidServerGraphExperiment, trackDraftGraphGeneration } = await import(`data:text/javascript;base64,${Buffer.from(expSource).toString('base64')}`);

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

test('native models restore an acknowledged numeric child under the local UUID order', async () => {
    const { createRelatedModels } = loadNative();
    const src = readFileSync(new URL('../static/src/app/global_discount.js', import.meta.url), 'utf8');
    const begin = src.indexOf('function reconnectAcknowledgedDraftRows('), end = src.indexOf('\nfunction pendingDeletedIds(', begin);
    assert.ok(begin >= 0 && end > begin);
    const { reconnect, preferLocal } = new Function('_t', `${src.slice(begin, end)}\nreturn { reconnect: reconnectAcknowledgedDraftRows, preferLocal: preferLocalDraftRows };`)((value) => value);
    const defs = {
        'pos.order': { id: { type: 'integer' }, uuid: { type: 'char' }, state: { type: 'char' }, lines: { name: 'lines', model: 'pos.order', type: 'one2many', relation: 'pos.order.line', inverse_name: 'order_id' }, payment_ids: { name: 'payment_ids', model: 'pos.order', type: 'one2many', relation: 'pos.payment', inverse_name: 'pos_order_id' } },
        'pos.order.line': { id: { type: 'integer' }, uuid: { type: 'char' }, qty: { type: 'float' }, order_id: { name: 'order_id', model: 'pos.order.line', type: 'many2one', relation: 'pos.order' } },
        'pos.payment': { id: { type: 'integer' }, uuid: { type: 'char' }, amount: { type: 'float' }, pos_order_id: { name: 'pos_order_id', model: 'pos.payment', type: 'many2one', relation: 'pos.order' } },
    };
    const makeModels = () => createRelatedModels(defs, {}, { dynamicModels: ['pos.order', 'pos.order.line', 'pos.payment'],
        databaseTable: { 'pos.order': { key: 'uuid' }, 'pos.order.line': { key: 'uuid' }, 'pos.payment': { key: 'uuid' } },
        databaseIndex: { 'pos.order': ['uuid'], 'pos.order.line': ['uuid'], 'pos.payment': ['uuid'] } }).models;
    const data = { 'pos.order': [{ id: 'order', uuid: 'order', state: 'draft', lines: ['food', 'preview'], payment_ids: ['pay'], JSONuiState: JSON.stringify({ baseerOfflineDiscount: {}, baseerSharedDraftServerOrderId: 260, baseerSharedDraftLineIds: { food: 634 }, baseerSharedDraftPaymentIds: { pay: 70 } }) }],
        'pos.order.line': [{ id: 634, uuid: 'food', order_id: 260, qty: 1 }, { id: 'preview', uuid: 'preview', order_id: 'order', qty: 1 }], 'pos.payment': [{ id: 70, uuid: 'pay', pos_order_id: 260, amount: 90 }] };
    const broken = makeModels(); broken.loadConnectedData(data);
    assert.deepEqual(broken['pos.order'].getBy('uuid', 'order').lines.map((line) => line.uuid), ['preview']);
    const corrected = reconnect(data);
    assert.equal(data['pos.order.line'][0].order_id, 260, 'does not mutate persisted snapshot');
    const restored = makeModels(); restored.loadConnectedData(corrected);
    assert.deepEqual(restored['pos.order'].getBy('uuid', 'order').lines.map((line) => line.uuid).sort(), ['food', 'preview']);
    assert.equal(restored['pos.order'].getBy('uuid', 'order').payment_ids[0].amount, 90);
    const localRows = structuredClone(data);
    localRows['pos.order.line'][0].id = 'food'; localRows['pos.order.line'][0].order_id = 'order';
    const local = makeModels(); local.loadConnectedData(reconnect(localRows));
    assert.deepEqual(local['pos.order'].getBy('uuid', 'order').lines.map((line) => line.uuid).sort(), ['food', 'preview']);
    const preloaded = makeModels();
    preloaded.loadConnectedData({ 'pos.order': [{ id: 260, uuid: 'order', lines: [634, 635], payment_ids: [] }],
        'pos.order.line': [{ id: 634, uuid: 'food', order_id: 260, qty: 1 }, { id: 635, uuid: 'server-allowance', order_id: 260, qty: 1 }], 'pos.payment': [] });
    preloaded.loadConnectedData(reconnect(localRows));
    assert.deepEqual(preloaded['pos.order'].getBy('uuid', 'order').lines.map((line) => line.uuid).sort(), ['food', 'preview']);
    const duplicates = structuredClone(localRows);
    duplicates['pos.order.line'].push({ id: 634, uuid: 'food', order_id: 260, qty: 99 });
    const beforeFix = makeModels(); beforeFix.loadConnectedData(duplicates);
    assert.deepEqual(beforeFix['pos.order'].getBy('uuid', 'order').lines.map((line) => line.uuid), ['preview']);
    const duplicatedModels = makeModels(); duplicatedModels.loadConnectedData(preferLocal(duplicates, localRows));
    assert.deepEqual(duplicatedModels['pos.order'].getBy('uuid', 'order').lines.map((line) => line.uuid).sort(), ['food', 'preview']);
    assert.equal(duplicatedModels['pos.order'].getBy('uuid', 'order').lines.find((line) => line.uuid === 'food').qty, 1, 'keep local edit, not stale server quantity');
    const paid = structuredClone(localRows);
    paid['pos.order'][0].state = 'paid';
    paid['pos.payment'][0] = { id: 'pay', uuid: 'pay', pos_order_id: 'order', amount: 90 };
    const paidDuplicates = structuredClone(paid);
    paidDuplicates['pos.order.line'].push({ id: 634, uuid: 'food', order_id: 260, qty: 99 });
    paidDuplicates['pos.payment'].push({ id: 70, uuid: 'pay', pos_order_id: 260, amount: 10 });
    const paidModels = makeModels(); paidModels.loadConnectedData(preferLocal(paidDuplicates, paid));
    const paidOrder = paidModels['pos.order'].getBy('uuid', 'order');
    assert.equal(paidOrder.lines.find((line) => line.uuid === 'food').qty, 1);
    assert.equal(paidOrder.payment_ids[0].amount, 90);
    const corrupt = structuredClone(paid); corrupt['pos.order'][0].JSONuiState = '{broken';
    assert.throws(() => preferLocal(paidDuplicates, corrupt), /cannot be verified/);
    const guardStart = src.indexOf('function isPendingOfflineDiscount('), guardEnd = src.indexOf('\nfunction touchExperimentalDraftGraph(', guardStart);
    const patchStart = src.indexOf('    async processDynamicRecords(records) {'), patchEnd = src.indexOf('    processDeletedRecords(records) {', patchStart);
    assert.ok(guardStart >= 0 && guardEnd > guardStart && patchStart >= 0 && patchEnd > patchStart);
    const guard = new Function(`const SHARED_DRAFT_FLOW_ENABLED=true; ${src.slice(guardStart, guardEnd)}\nreturn ({ ${src.slice(patchStart, patchEnd)} });`)();
    Object.setPrototypeOf(guard, { async processDynamicRecords(records) { this.models.loadConnectedData(records); } });
    const live = makeModels(); live.loadConnectedData(localRows);
    const liveOrder = live['pos.order'].getBy('uuid', 'order'); liveOrder.uiState = { baseerOfflineDiscount: {} };
    const previous = makeModels(); previous.loadConnectedData(localRows);
    const previousOrder = previous['pos.order'].getBy('uuid', 'order'); previousOrder.uiState = { baseerOfflineDiscount: {} };
    previous.loadConnectedData({ 'pos.order.line': [{ id: 634, uuid: 'food', order_id: 260, qty: 99 }] });
    assert.deepEqual(previousOrder.lines.map((line) => line.uuid), ['preview']);
    const device = { models: live };
    await guard.processDynamicRecords.call(device, { 'pos.order': [{ id: 260, uuid: 'order', lines: [634] }],
        'pos.order.line': [{ id: 634, uuid: 'food', order_id: 260, qty: 99 }] });
    assert.deepEqual(liveOrder.lines.map((line) => line.uuid).sort(), ['food', 'preview']);
    assert.equal(liveOrder.lines.find((line) => line.uuid === 'food').qty, 1);
    const mismatch = structuredClone(data);
    mismatch['pos.order.line'][0].id = 999;
    assert.equal(reconnect(mismatch)['pos.order.line'][0].order_id, 260, 'unproven IDs are never rebound');
    const conflict = structuredClone(data);
    conflict['pos.order'].push({ id: 'other', uuid: 'other', lines: [], JSONuiState: JSON.stringify({ baseerSharedDraftServerOrderId: 260 }) });
    assert.throws(() => reconnect(conflict), /Conflicting local draft ownership/);
});

test('browser IndexedDB restart reconnects numeric children and protects paid records from stale duplicates', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-mixed-identity.invalid/');
        const source = readFileSync(new URL('../static/src/app/global_discount.js', import.meta.url), 'utf8');
        const begin = source.indexOf('function reconnectAcknowledgedDraftRows('), end = source.indexOf('\nfunction pendingDeletedIds(', begin);
        await page.addScriptTag({ content: `${nativeBundle()}\nconst _t = value => value;\n${source.slice(begin, end)}\nwindow.restoreMixedIdentity = async () => {
            const defs = { 'pos.order': { id: {type:'integer'}, uuid:{type:'char'}, lines:{name:'lines',model:'pos.order',type:'one2many',relation:'pos.order.line',inverse_name:'order_id'}, payment_ids:{name:'payment_ids',model:'pos.order',type:'one2many',relation:'pos.payment',inverse_name:'pos_order_id'} },
                'pos.order.line': {id:{type:'integer'},uuid:{type:'char'},qty:{type:'float'},order_id:{name:'order_id',model:'pos.order.line',type:'many2one',relation:'pos.order'}},
                'pos.payment': {id:{type:'integer'},uuid:{type:'char'},amount:{type:'float'},pos_order_id:{name:'pos_order_id',model:'pos.payment',type:'many2one',relation:'pos.order'}} };
            const names = Object.keys(defs), open = () => new Promise((resolve,reject) => { const r=indexedDB.open('mixed-identity',1); r.onupgradeneeded=()=>names.forEach(n=>r.result.createObjectStore(n,{keyPath:'uuid'})); r.onsuccess=()=>resolve(r.result); r.onerror=()=>reject(r.error); });
            let db=await open(), tx=db.transaction(names,'readwrite');
            tx.objectStore('pos.order').put({id:'order',uuid:'order',lines:['food','preview'],payment_ids:['pay'],JSONuiState:JSON.stringify({baseerSharedDraftServerOrderId:260,baseerSharedDraftLineIds:{food:634},baseerSharedDraftPaymentIds:{pay:70}})});
            tx.objectStore('pos.order.line').put({id:634,uuid:'food',order_id:260,qty:1}); tx.objectStore('pos.order.line').put({id:'preview',uuid:'preview',order_id:'order',qty:1});
            tx.objectStore('pos.payment').put({id:70,uuid:'pay',pos_order_id:260,amount:90});
            await new Promise((resolve,reject)=>{tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error)}); db.close(); db=await open();
            const values=await Promise.all(names.map(name=>new Promise((resolve,reject)=>{const r=db.transaction([name]).objectStore(name).getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})));
            const rows=Object.fromEntries(names.map((name,i)=>[name,values[i]]));
            const {models}=createRelatedModels(defs,{}, {dynamicModels:names,databaseTable:Object.fromEntries(names.map(n=>[n,{key:'uuid'}])),databaseIndex:Object.fromEntries(names.map(n=>[n,['uuid']]))});
            const local=reconnectAcknowledgedDraftRows(rows);
            local['pos.order'][0].state='paid';
            local['pos.order'][0].JSONuiState=JSON.stringify({baseerOfflineDiscount:{},baseerSharedDraftPending:{target_state:'paid',source_line_uuids:['food'],source_payment_uuids:['pay']}});
            verifyStoredPaidDiscountGraph(local);
            const duplicated=structuredClone(local);
            duplicated['pos.order.line'].push({id:634,uuid:'food',order_id:260,qty:99});
            duplicated['pos.payment'].push({id:70,uuid:'pay',pos_order_id:260,amount:1});
            models.loadConnectedData(preferLocalDraftRows(duplicated,local)); const order=models['pos.order'].getBy('uuid','order');
            const missing=structuredClone(local); missing['pos.payment']=[]; let rejected=false;
            try { verifyStoredPaidDiscountGraph(missing); } catch (error) { rejected=error.message.includes('local order is incomplete'); }
            db.close(); return {lines:order.lines.map(l=>l.uuid).sort(),amount:order.payment_ids[0]?.amount,storedParent:rows['pos.order.line'][0].order_id,rejected};
        };` });
        assert.deepEqual(await page.evaluate(() => window.restoreMixedIdentity()), { lines: ['food','preview'], amount: 90, storedParent: 260, rejected: true });
        await context.close();
    } finally { await browser.close(); }
});

test('actual managed save and sync accept a verified ACK without a false failure', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-managed-save.invalid/');
        page.on('console', (message) => { if (message.type() === 'warning') console.warn(message.text()); });
        const src = readFileSync(new URL('../static/src/app/global_discount.js', import.meta.url), 'utf8');
        const get = (a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i); assert.ok(i >= 0 && j > i); return src.slice(i, j).replace(/},\s*$/, '}\n'); };
        const click = get('    async clickSaveOrder() {', '    async baseerSettleSharedDraftBeforePaymentExperiment(');
        const run = get('    async baseerRunSharedDraftExperiment(order) {', '    async baseerRecoverChangedCancellation(');
        const sync = get('    async syncAllOrders(options = {}) {', '    async preSyncAllOrders(');
        const protect = get('function protectOfflineStorage(', '// Native cleanup');
        const experiment = expSource.replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `const crypto = { randomUUID: () => '00000000-0000-4000-8000-000000000001' };\n${nativeBundle()}\n${experiment}\n${protect}
            const SHARED_DRAFT_FLOW_ENABLED=true, sharedRefreshOrders=new WeakSet(), sharedRevisionPromises=new WeakMap(), sharedRevisionWarningOwners=new WeakMap();
            const _t=value=>value, isManagedSharedDraft=order=>!!order.uiState?.baseerOfflineDiscount;
            const refreshOfflineDiscount=()=>{}, calculateOfflineDiscount=()=>{}, hydrateSharedDraftExperimentUnused=()=>{};
            const accountTaxHelpers={}; class ConnectionLostError extends Error {};
            class ParentStore { async syncAllOrders() { return []; } }
            class Store extends ParentStore { ${click} ${run} ${sync} }
            window.runManagedSave = async () => {
                const defs = { 'pos.order': {id:{type:'integer'},uuid:{type:'char'},state:{type:'char'},lines:{name:'lines',model:'pos.order',type:'one2many',relation:'pos.order.line',inverse_name:'order_id'},payment_ids:{name:'payment_ids',model:'pos.order',type:'one2many',relation:'pos.payment',inverse_name:'pos_order_id'}},
                    'pos.order.line': {id:{type:'integer'},uuid:{type:'char'},order_id:{name:'order_id',model:'pos.order.line',type:'many2one',relation:'pos.order'}},
                    'pos.payment': {id:{type:'integer'},uuid:{type:'char'},pos_order_id:{name:'pos_order_id',model:'pos.payment',type:'many2one',relation:'pos.order'}},
                    'product.attribute.custom.value':{id:{type:'integer'}} };
                class Order extends Base { static enableLazyGetters=false; setOrderPrices() {} serializeForORM() { return {uuid:this.uuid,baseer_offline_discount_intent:this.uiState.baseerOfflineDiscount,lines:[]}; } }
                const names=Object.keys(defs), dynamic=names.slice(0,3);
                const {models}=createRelatedModels(defs,{'pos.order':Order},{dynamicModels:dynamic,databaseTable:Object.fromEntries(dynamic.map(n=>[n,{key:'uuid'}])),databaseIndex:Object.fromEntries(dynamic.map(n=>[n,['uuid']]))});
                const order=models['pos.order'].create({uuid:'order',state:'draft',lines:[],payment_ids:[]});
                order.uiState={baseerOfflineDiscount:{kind:'fixed',value:'10',preview_line_uuids:[]}};
                models['pos.order.line'].create({uuid:'food',order_id:order});
                const opening=indexedDB.open('managed-save',1); opening.onupgradeneeded=()=>names.forEach(n=>opening.result.createObjectStore(n,{keyPath:n==='product.attribute.custom.value'?'id':'uuid'}));
                const db=await new Promise((resolve,reject)=>{opening.onsuccess=()=>resolve(opening.result);opening.onerror=()=>reject(opening.error)});
                let calls=0; const data={network:{offline:false},indexedDB:{db},orm:{async call(){calls++;return {'pos.order':[{id:260,uuid:'order',state:'draft',baseer_offline_draft_revision:1}],'pos.order.line':[{id:634,uuid:'food'}],'pos.payment':[]};}}};
                const store=new Store(); Object.assign(store,{models,data,config:{},syncingOrders:new Set(),getOrder:()=>order,getEmptyOrder:()=> 'empty',setOrder(v){this.switched=v},notification:{add(v){store.messages.push(v)}},messages:[],getPendingOrder:()=>({orderToCreate:[],orderToUpdate:[]}),addPendingOrder(){},removePendingOrder(){},getSyncAllOrdersContext:()=>({}),baseerCheckRestoredSharedDraftExperiment:async()=>true});
                await store.clickSaveOrder(); const result={calls,switched:store.switched,messages:store.messages,pending:!!order.uiState.baseerSharedDraftPending,revision:order.uiState.baseerSharedDraftRevision,clean:order.uiState.baseerSharedDraftHydratedOnly}; db.close(); return result;
            };` });
        assert.deepEqual(await page.evaluate(() => window.runManagedSave()), { calls: 1, switched: 'empty', messages: ['Order saved for later'], pending: false, revision: 1, clean: true });
        await context.close();
    } finally { await browser.close(); }
});

test('native related_models detach preserves source line and unrelated deletion commands', () => {
    const { createRelatedModels } = loadNative();
    const defs = {
        'pos.order': { id: { type: 'integer' }, uuid: { type: 'char' }, state: { type: 'char' }, baseer_offline_draft_kind: { type: 'char' },
            baseer_offline_draft_value: { type: 'char' }, baseer_offline_draft_revision: { type: 'integer' }, lines: { name: 'lines', model: 'pos.order', type: 'one2many', relation: 'pos.order.line', inverse_name: 'order_id' },
            payment_ids: { name: 'payment_ids', model: 'pos.order', type: 'one2many', relation: 'pos.payment', inverse_name: 'pos_order_id' } },
        'pos.order.line': { id: { type: 'integer' }, uuid: { type: 'char' }, order_id: { name: 'order_id', model: 'pos.order.line', type: 'many2one', relation: 'pos.order' },
            product_id: { name: 'product_id', model: 'pos.order.line', type: 'many2one', relation: 'product.product' },
            tax_ids: { name: 'tax_ids', model: 'pos.order.line', type: 'many2many', relation: 'account.tax', relation_table: 'line_tax_rel' },
            product_tmpl_id: { type: 'many2one', relation: 'product.template' }, price_unit: { type: 'float' }, discount: { type: 'float' },
            price_type: { type: 'char' }, extra_tax_data: { type: 'json' },
            baseer_global_discount_line: { type: 'boolean' }, qty: { type: 'float' } },
        'pos.payment': { id: { type: 'integer' }, uuid: { type: 'char' }, amount: { type: 'float' }, pos_order_id: { name: 'pos_order_id', model: 'pos.payment', type: 'many2one', relation: 'pos.order' } },
        'product.attribute.custom.value': { id: { type: 'integer' } },
        'product.product': { id: { type: 'integer' }, name: { type: 'char' }, type: { type: 'char' }, tracking: { type: 'char' }, product_tmpl_id: { type: 'many2one', relation: 'product.template' } },
        'account.tax': { id: { type: 'integer' }, name: { type: 'char' }, amount_type: { type: 'char' } },
    };
    const dynamicModels = ['pos.order', 'pos.order.line', 'pos.payment'];
    const { models } = createRelatedModels(defs, {}, { dynamicModels, databaseTable: {
        'pos.order': { key: 'uuid' }, 'pos.order.line': { key: 'uuid' }, 'pos.payment': { key: 'uuid' },
    }, databaseIndex: { 'pos.order': ['uuid'], 'pos.order.line': ['uuid'], 'pos.payment': ['uuid'] } });
    const order = models['pos.order'].create({ id: 42, uuid: 'order', lines: [] });
    const product = models['product.product'].create({ id: 9, name: 'discount', type: 'service', tracking: 'none' });
    const tax = models['account.tax'].create({ id: 5, name: 'vat', amount_type: 'percent' });
    const source = models['pos.order.line'].create({ id: 11, uuid: 'source', order_id: order, qty: 1 });
    Object.getPrototypeOf(source).getQuantity = function () { return this.qty; };
    order.getOrderlines = () => order.lines;
    order.uiState = { baseerOfflineDiscount: { preview_line_uuids: [] } };
    order.last_order_preparation_change = { lines: {} };
    const kitchenSource = readFileSync(new URL('../../baseer_pos_print_bridge/static/src/app/line_actions.js', import.meta.url), 'utf8');
    const kitchenSection = kitchenSource.slice(kitchenSource.indexOf('function preparationLine('), kitchenSource.indexOf('patch(PosOrder.prototype')).replaceAll('export function ', 'function ');
    const kitchenAction = new Function('crypto', `${kitchenSection}\nreturn buildBaseerPreparationAction;`)({ randomUUID: () => 'action' });
    const removed = models['pos.order.line'].create({ id: 12, uuid: 'removed', order_id: order, qty: 1 });
    const allowance = models['pos.order.line'].create({ id: 33, uuid: 'server', order_id: order, qty: -1, baseer_global_discount_line: true,
        product_id: product, tax_ids: [['link', tax]] });
    allowance.uiState = { reason: 'server-allowance' };
    const original = allowance.serializeForIndexedDB();
    assert.equal(source.order_id, order);
    assert.equal(order.lines.length, 3);
    const tracker = trackDraftGraphGeneration(models);
    removed.delete();
    const before = tracker.get();
    assert.deepEqual(detachServerAllowancesExperiment(order), [33]);
    assert.equal(order.lines.length, 1);
    assert.equal(order.lines[0], source);
    const serialized = order.serializeForORM({ keepCommands: true });
    assert.ok(serialized.lines.some((cmd) => [2, 3].includes(cmd[0]) && cmd[1] === 12));
    assert.ok(!serialized.lines.some((cmd) => [2, 3].includes(cmd[0]) && cmd[1] === 33));
    assert.ok(tracker.get() > before);
    assert.equal(allowance.order_id, undefined);
    original.order_id = order;
    const restored = models['pos.order.line'].create(original);
    assert.equal(restored.id, 33);
    assert.equal(restored.order_id, order);
    assert.equal(restored.uiState.reason, 'server-allowance');
    assert.equal(restored.baseer_global_discount_line, true);
    assert.equal(restored.product_id, product);
    assert.deepEqual(restored.tax_ids.map((item) => item.id), [5]);
    const afterRollback = order.serializeForORM({ keepCommands: true });
    assert.ok(!afterRollback.lines.some((cmd) => [2, 3].includes(cmd[0]) && cmd[1] === 33));
    const totalBefore = order.lines.reduce((sum, line) => sum + line.qty, 0);
    const stopFailure = models['pos.order.line'].addEventListener('create', ({ ids }) => {
        if (ids.includes('preview')) throw new Error('model create listener failed');
    });
    assert.throws(() => replaceServerAllowancesExperiment({ order, calculate: () => ({ valid: true }),
        buildPreview: (_result, register) => {
            register('preview');
            models['pos.order.line'].create({ uuid: 'preview', order_id: order, qty: -2 });
        } }), /model create listener failed/);
    stopFailure();
    assert.equal(order.lines.reduce((sum, line) => sum + line.qty, 0), totalBefore);
    assert.deepEqual(order.lines.map((line) => line.uuid).sort(), ['server', 'source']);
    const restoredAgain = order.lines.find((line) => line.uuid === 'server');
    assert.equal(restoredAgain.product_id, product);
    assert.deepEqual(restoredAgain.tax_ids.map((item) => item.id), [5]);
    assert.deepEqual(kitchenAction(order).lines.map((line) => line.line_uuid), ['source']);
    const afterFailedReplacement = order.serializeForORM({ keepCommands: true });
    assert.ok(afterFailedReplacement.lines.some((cmd) => [2, 3].includes(cmd[0]) && cmd[1] === 12));
    assert.ok(!afterFailedReplacement.lines.some((cmd) => [2, 3].includes(cmd[0]) && cmd[1] === 33));

    // Exercise the hydration adapter on real Odoo relation models. The tax
    // arithmetic is stubbed; tax and product relationships are real models.
    const shared = models['pos.order'].create({ id: 84, uuid: 'shared', lines: [] });
    shared.state = 'draft'; shared.company_id = {}; shared.currency = { round: (number) => Math.round(number * 100) / 100 };
    shared.baseer_offline_draft_kind = 'fixed'; shared.baseer_offline_draft_value = '10'; shared.baseer_offline_draft_revision = 1;
    shared.uiState = {}; shared.triggerRecomputeAllPrices = () => {}; shared.getOrderlines = () => shared.lines;
    shared.last_order_preparation_change = { lines: {} };
    Object.defineProperties(shared, {
        priceIncl: { get() { return this.lines.reduce((sum, line) => sum + line.qty * line.price_unit, 0); } },
        amountTaxes: { get() { return 0; } },
    });
    Object.getPrototypeOf(source).prepareBaseLineForTaxesComputationExtraValues = () => ({});
    models['pos.order.line'].create({ id: 51, uuid: 'shared-food', order_id: shared, product_id: product,
        qty: 1, price_unit: 100, tax_ids: [['link', tax]] });
    models['pos.order.line'].create({ id: 52, uuid: 'shared-allowance', order_id: shared, product_id: product,
        qty: 1, price_unit: -10, tax_ids: [['link', tax]], baseer_global_discount_line: true });
    const previewSource = readFileSync(new URL('../static/src/app/offline_preview.js', import.meta.url), 'utf8')
        .replace(/^import .*;\r?\n/gm, '').replaceAll('export function ', 'function ');
    const helpers = { prepare_base_line_for_taxes_computation: (line) => ({ line, tax_details: { total_included_currency: line.price_unit * line.qty } }),
        add_tax_details_in_base_lines() {}, round_base_lines_tax_details() {},
        prepare_global_discount_lines: (bases, _company, _kind, value) => [{ price_unit: -value, quantity: 1, tax_ids: [bases[0].line.tax_ids[0]] }] };
    const calculate = new Function('accountTaxHelpers', '_t', `${previewSource}\nreturn calculateOfflineDiscount;`)(helpers, (text) => text);
    const pos = { models, config: { baseer_global_discount_product_id: product, baseer_global_discount_max_percent: 100,
        baseer_global_discount_max_amount: 0, baseer_offline_discount_account_proofs: { 0: 'a'.repeat(64) } } };
    const hydration = () => hydrateSharedDraftExperiment({ pos, order: shared, calculate, exportExtraTaxData: () => ({}) });
    const stopHydrationFailure = models['pos.order.line'].addEventListener('create', ({ ids }) => {
        if (ids.some((id) => typeof id !== 'number')) throw new Error('simulated POS listener failure');
    });
    assert.throws(hydration, /simulated POS listener failure/);
    stopHydrationFailure();
    assert.equal(shared.priceIncl, 90);
    assert.deepEqual(shared.lines.map((line) => line.uuid).sort(), ['shared-allowance', 'shared-food']);
    assert.match(shared.uiState.baseerSharedDraftHydrationError, /listener failure/);
    assert.equal(shared.uiState.baseerOfflineDiscount, undefined);
    const intent = hydration();
    assert.equal(shared.priceIncl, 90);
    assert.equal(intent.expected_total, '90.00');
    assert.equal(shared.uiState.baseerSharedDraftHydrationError, undefined);
    assert.equal(shared.lines.filter((line) => line.baseer_global_discount_line).length, 0);
    assert.deepEqual(kitchenAction(shared).lines.map((line) => line.line_uuid), ['shared-food']);
    // Native server loading preserves an unsynced local one2many member.
    // Without removing the preview before import, both discounts are present.
    const previewUuid = intent.preview_line_uuids[0];
    models.loadConnectedData({
        'pos.order': [{ id: 84, uuid: 'shared', lines: [51, 52] }],
        'pos.order.line': [
            { id: 51, uuid: 'shared-food', order_id: 84, product_id: 9, qty: 1, price_unit: 100, tax_ids: [5] },
            { id: 52, uuid: 'shared-allowance', order_id: 84, product_id: 9, qty: 1, price_unit: -10, tax_ids: [5], baseer_global_discount_line: true },
        ],
    });
    assert.ok(shared.lines.some((line) => line.uuid === previewUuid));
    assert.ok(shared.lines.some((line) => line.uuid === 'shared-allowance'));
    assert.equal(shared.priceIncl, 80);
    detachServerAllowancesExperiment(shared);
    shared.state = 'paid';
    shared.uiState.baseerSharedDraftPaidAckPending = true;
    models['pos.payment'].create({ uuid: 'pay', pos_order_id: shared, amount: 90 });
    const serverGraph = {
        'pos.order': [{ id: 84, uuid: 'shared', state: 'paid', lines: [51, 52], payment_ids: [71] }],
        'pos.order.line': [
            { id: 51, uuid: 'shared-food', order_id: 84, product_id: 9, qty: 1, price_unit: 100, tax_ids: [5] },
            { id: 52, uuid: 'shared-allowance', order_id: 84, product_id: 9, qty: 1, price_unit: -10, tax_ids: [5], baseer_global_discount_line: true },
        ],
        'pos.payment': [{ id: 71, uuid: 'pay', pos_order_id: 84, amount: 90 }],
        'product.attribute.custom.value': [],
    };
    const pending = { order_uuid: 'shared' };
    const validateGraph = (saved) => {
        assert.equal(saved.priceIncl, 90);
        assert.equal(saved.lines.filter((line) => line.baseer_global_discount_line).length, 1);
        assert.equal(saved.payment_ids.length, 1);
        assert.equal(saved.payment_ids[0].id, 71);
    };
    assert.throws(() => stagePaidServerGraphExperiment({ order: shared, response: serverGraph, pending, verify: (saved) => {
        validateGraph(saved); throw new Error('simulated validation failure');
    } }), /simulated validation failure/);
    assert.equal(shared.priceIncl, 90);
    assert.ok(shared.lines.some((line) => line.uuid === previewUuid));
    assert.equal(shared.payment_ids.length, 1);
    assert.equal(shared.payment_ids[0].id, 'pay');
    const staged = stagePaidServerGraphExperiment({ order: shared, response: serverGraph, pending, verify: validateGraph });
    validateGraph(shared);
    staged.rollback(); // emulate IndexedDB quota/abort after staging
    assert.equal(shared.priceIncl, 90);
    assert.ok(shared.lines.some((line) => line.uuid === previewUuid));
    assert.equal(shared.payment_ids.length, 1);
    assert.equal(shared.payment_ids[0].id, 'pay');
    // An unchanged second device can stage a newer whole server graph; a
    // failed new preview must put back the old visible graph and intent.
    const remote = models['pos.order'].create({ id: 105, uuid: 'remote', state: 'draft', lines: [], payment_ids: [],
        baseer_offline_draft_kind: 'fixed', baseer_offline_draft_value: '10', baseer_offline_draft_revision: 1 });
    remote.company_id = {}; remote.currency = { round: (value) => Math.round(value * 100) / 100 }; remote.triggerRecomputeAllPrices = () => {};
    Object.defineProperties(remote, { priceIncl: { get() { return this.lines.reduce((sum, line) => sum + line.qty * line.price_unit, 0); } }, amountTaxes: { get() { return 0; } } });
    remote.uiState = { baseerOfflineDiscount: { kind: 'fixed', value: '10', preview_line_uuids: ['remote-preview'] }, baseerSharedDraftHydratedOnly: true };
    models['pos.order.line'].create({ id: 61, uuid: 'remote-food', order_id: remote, product_id: product, qty: 1, price_unit: 100, tax_ids: [['link', tax]] });
    models['pos.order.line'].create({ uuid: 'remote-preview', order_id: remote, product_id: product, qty: 1, price_unit: -10, tax_ids: [['link', tax]] });
    const remoteGraph = { 'pos.order': [{ id: 105, uuid: 'remote', state: 'draft', baseer_offline_draft_kind: 'percent', baseer_offline_draft_value: '10', baseer_offline_draft_revision: 2, lines: [61, 62], payment_ids: [] }],
        'pos.order.line': [{ id: 61, uuid: 'remote-food', order_id: 105, product_id: 9, qty: 1, price_unit: 100, tax_ids: [5] },
            { id: 62, uuid: 'remote-allowance', order_id: 105, product_id: 9, qty: 1, price_unit: -10, tax_ids: [5], baseer_global_discount_line: true }],
        'pos.payment': [], 'product.attribute.custom.value': [] };
    const stageRemote = () => stageNativeServerGraphExperiment({ order: remote, response: remoteGraph,
        beforeLoad: (saved) => { delete saved.uiState.baseerOfflineDiscount; },
        verify: (saved) => hydrateSharedDraftExperiment({ pos, order: saved, calculate, exportExtraTaxData: () => ({}) }) });
    pos.config.baseer_offline_discount_account_proofs = {};
    assert.throws(stageRemote, /account needs verification/);
    assert.deepEqual(remote.lines.map((line) => line.uuid).sort(), ['remote-food', 'remote-preview']);
    assert.equal(remote.priceIncl, 90);
    assert.equal(remote.uiState.baseerOfflineDiscount.kind, 'fixed');
    pos.config.baseer_offline_discount_account_proofs = { 0: 'a'.repeat(64) };
    models['pos.order.line'].create({ id: 63, uuid: 'stale-server-allowance', order_id: remote, product_id: product, qty: 1, price_unit: -10, tax_ids: [['link', tax]], baseer_global_discount_line: true });
    assert.equal(remote.priceIncl, 80, 'simulate a previously contaminated local graph');
    stageRemote();
    assert.equal(remote.baseer_offline_draft_revision, 2);
    assert.equal(remote.uiState.baseerOfflineDiscount.kind, 'percent');
    assert.equal(remote.lines.filter((line) => line.baseer_global_discount_line).length, 0);
    assert.equal(remote.lines.length, 2);
    assert.equal(remote.priceIncl, 90);
    const local = models['pos.order'].create({ uuid: 'restart-draft', state: 'draft', lines: [], payment_ids: [] });
    models['pos.order.line'].create({ uuid: 'restart-food', order_id: local, product_id: product, qty: 1, price_unit: 100, tax_ids: [['link', tax]] });
    models.loadConnectedData({ 'pos.order': [{ id: 260, uuid: 'restart-draft', state: 'draft', lines: [634], payment_ids: [] }],
        'pos.order.line': [{ id: 634, uuid: 'restart-food', order_id: 260, product_id: 9, qty: 1, price_unit: 100, tax_ids: [5] }], 'pos.payment': [] });
    const imported = models['pos.order'].getBy('uuid', 'restart-draft');
    assert.ok(imported.lines.some((line) => line.uuid === 'restart-food'), 'source line must remain related after server id is introduced');
    tracker.dispose();
});

test('native Odoo models and real IndexedDB retain a later draft edit during isolated RPC', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-real-models.invalid/');
        const experiment = expSource.replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        const posPatch = readFileSync(new URL('../static/src/app/global_discount.js', import.meta.url), 'utf8');
        const start = posPatch.indexOf('    serializeForIndexedDB() {', posPatch.indexOf('patch(PosOrder.prototype'));
        const end = posPatch.indexOf('    serializeForORM() {', start);
        assert.ok(start >= 0 && end > start);
        const nativeOrderPatch = posPatch.slice(start, end).replace(/},\s*$/, '}\n');
        const reconcileStart = posPatch.indexOf('    async baseerReconcileSharedPaidExperiment(order) {');
        const reconcileEnd = posPatch.indexOf('    async baseerVerifySharedInvoiceExperiment(', reconcileStart);
        const protectionStart = posPatch.indexOf('function protectOfflineStorage(');
        const protectionEnd = posPatch.indexOf('// Native cleanup', protectionStart);
        assert.ok(reconcileStart >= 0 && reconcileEnd > reconcileStart && protectionStart >= 0 && protectionEnd > protectionStart);
        const reconcileMethod = posPatch.slice(reconcileStart, reconcileEnd).replace(/},\s*$/, '}\n');
        const protectionFunction = posPatch.slice(protectionStart, protectionEnd);
        await page.addScriptTag({ content: `const crypto = { randomUUID: () => '00000000-0000-4000-8000-000000000001' };\n${nativeBundle()}\n${experiment}\nconst paidReconciliationOrders = new WeakSet();\n${protectionFunction}\nconst SHARED_DRAFT_FLOW_ENABLED = true; const isManagedSharedDraft = (order) => !!order.uiState?.baseerOfflineDiscount;\nclass TestStore { ${reconcileMethod} }\nwindow.runRealModelTest = async () => {
            const defs = {
                'pos.order': { id: { type: 'integer' }, uuid: { type: 'char' }, state: { type: 'char' }, amount_total: { type: 'float' }, amount_tax: { type: 'float' },
                    baseer_global_discount_locked: { type: 'boolean' }, to_invoice: { type: 'boolean' }, account_move: { type: 'many2one', relation: 'account.move' },
                    lines: { name: 'lines', model: 'pos.order', type: 'one2many', relation: 'pos.order.line', inverse_name: 'order_id' },
                    payment_ids: { name: 'payment_ids', model: 'pos.order', type: 'one2many', relation: 'pos.payment', inverse_name: 'pos_order_id' } },
                'pos.order.line': { id: { type: 'integer' }, uuid: { type: 'char' }, qty: { type: 'float' }, price_unit: { type: 'float' },
                    order_id: { name: 'order_id', model: 'pos.order.line', type: 'many2one', relation: 'pos.order' }, baseer_global_discount_line: { type: 'boolean' } },
                'pos.payment': { id: { type: 'integer' }, uuid: { type: 'char' }, amount: { type: 'float' }, pos_order_id: { name: 'pos_order_id', model: 'pos.payment', type: 'many2one', relation: 'pos.order' } },
                'product.attribute.custom.value': { id: { type: 'integer' } },
                'account.move': { id: { type: 'integer' }, name: { type: 'char' } },
            };
            class TestOrder extends Base { static enableLazyGetters = false; get currency() { return { round: (value) => Math.round(value * 100) / 100 }; }
                get priceIncl() { return this.lines.reduce((sum, line) => sum + line.qty * line.price_unit, 0); }
                get amountTaxes() { return 0; }
                ${nativeOrderPatch} serializeForORM(opts) {
                const payload = super.serializeForORM(opts);
                payload.baseer_offline_discount_intent = { ...this.uiState.baseerOfflineDiscount };
                return payload;
            } }
            const { models } = createRelatedModels(defs, { 'pos.order': TestOrder }, { dynamicModels: ['pos.order', 'pos.order.line', 'pos.payment'],
                databaseTable: { 'pos.order': { key: 'uuid' }, 'pos.order.line': { key: 'uuid' }, 'pos.payment': { key: 'uuid' } },
                databaseIndex: { 'pos.order': ['uuid'], 'pos.order.line': ['uuid'], 'pos.payment': ['uuid'] } });
            const order = models['pos.order'].create({ id: 42, uuid: 'order', state: 'draft', lines: [], payment_ids: [] });
            order.uiState = { baseerOfflineDiscount: { kind: 'fixed', value: '10', preview_line_uuids: [] } };
            const first = models['pos.order.line'].create({ id: 11, uuid: 'A', order_id: order, qty: 1, price_unit: 100 });
            const tracker = attachDraftGenerationExperiment(models);
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const opening = indexedDB.open('real-model-draft', 1);
            opening.onupgradeneeded = () => { for (const name of names) opening.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); };
            const db = await new Promise((resolve, reject) => { opening.onsuccess = () => resolve(opening.result); opening.onerror = () => reject(opening.error); });
            let started, release;
            const begin = new Promise((resolve) => { started = resolve; });
            const gate = new Promise((resolve) => { release = resolve; });
            const data = { network: { offline: false }, indexedDB: { db }, orm: { async call(_model, _method, [[payload]]) {
                started(); await gate;
                return { 'pos.order': [{ id: 42, uuid: 'order', state: 'draft', baseer_offline_draft_revision: 1 }],
                    'pos.order.line': [{ id: 11, uuid: 'A' }], 'pos.payment': [] };
            } } };
            const adapter = createDraftSyncAdapterExperiment({ data, order, tracker, protect() {}, prepare() {}, getContext: () => ({}), offlineError: () => new Error('offline') });
            const running = runDraftSnapshotExperiment(adapter);
            await begin;
            first.delete();
            models['pos.order.line'].create({ uuid: 'B', order_id: order, qty: 2, price_unit: 50 });
            // Exercise the production serializeForIndexedDB override on the
            // actual Odoo record after a later edit and before its old ACK.
            const editedOrder = order.serializeForIndexedDB();
            const stateBeforeAck = JSON.parse(editedOrder.JSONuiState);
            const savedGeneration = stateBeforeAck.baseerSharedDraftGeneration;
            const sentGeneration = stateBeforeAck.baseerSharedDraftPending.generation;
            release(); await running;
            const tx = db.transaction(names, 'readonly');
            const all = (name) => new Promise((resolve, reject) => { const r = tx.objectStore(name).getAll(); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
            const [orders, lines] = await Promise.all([all('pos.order'), all('pos.order.line')]);
            const draftResult = { savedGeneration, sentGeneration, lines: lines.map((line) => line.uuid), live: order.lines.map((line) => line.uuid), state: JSON.parse(orders[0].JSONuiState),
                commands: order.serializeForORM({ keepCommands: true }).lines };
            order.state = 'paid'; order.to_invoice = true;
            const preview = models['pos.order.line'].create({ uuid: 'preview-paid', order_id: order, qty: 1, price_unit: -10 });
            models['pos.payment'].create({ uuid: 'pay', pos_order_id: order, amount: 90 });
            order.uiState.baseerOfflineDiscount.preview_line_uuids = [preview.uuid];
            const paidPayload = { uuid: 'order', to_invoice: true, baseer_offline_discount_intent: { expected_total: '90.00', expected_tax: '0.00' } };
            const paidCommand = { order_uuid: 'order', revision: 1, command_uuid: 'paid', target_state: 'paid', generation: tracker.get(),
                source_line_uuids: ['B'], source_payment_uuids: ['pay'], payload_json: JSON.stringify(paidPayload) };
            const paidResponse = { 'pos.order': [{ id: 42, uuid: 'order', state: 'paid', to_invoice: true, account_move: 77, lines: [12, 13], payment_ids: [20],
                    baseer_global_discount_locked: true, amount_total: 90, amount_tax: 0 }],
                'pos.order.line': [{ id: 12, uuid: 'B', order_id: 42, qty: 2, price_unit: 50 },
                    { id: 13, uuid: 'server-allowance', order_id: 42, qty: 1, price_unit: -10, baseer_global_discount_line: true }],
                'pos.payment': [{ id: 20, uuid: 'pay', pos_order_id: 42, amount: 90 }],
                'account.move': [{ id: 77, name: 'INV/77' }], 'product.attribute.custom.value': [] };
            Object.assign(order.uiState, { baseerSharedDraftPaidAckPending: true, baseerSharedDraftPaidCommand: paidCommand,
                baseerSharedDraftPaidServerResponse: paidResponse, baseerSharedDraftNeedsSync: false });
            await persistDraftGraphExperiment({ data, currentGeneration: () => tracker.get(), capture: () => ({
                generation: tracker.get(), orderIds: [42, 'order'], records: {
                    'pos.order': [order.serializeForIndexedDB()], 'pos.order.line': order.lines.map((line) => line.serializeForIndexedDB()),
                    'pos.payment': order.payment_ids.map((payment) => payment.serializeForIndexedDB()), 'product.attribute.custom.value': [],
                },
            }) });
            data.missingRecursive = async (value) => value;
            data.orm.read = async () => { throw new Error('access denied'); };
            data.localUnsyncedPaidOrderUuids = new Set(['order']);
            const store = new TestStore(); store.models = models; store.data = data;
            store.pendingOrder = { create: new Set(), write: new Set([42]), delete: new Set() };
            const actualDb = data.indexedDB.db;
            data.indexedDB.db = { transaction() { throw new DOMException('full', 'QuotaExceededError'); } };
            let quota = false;
            try { await store.baseerReconcileSharedPaidExperiment(order); } catch { quota = true; }
            const afterFailure = { lines: order.lines.map((line) => line.uuid).sort(), payments: order.payment_ids.map((payment) => payment.uuid),
                pending: !!order.uiState.baseerSharedDraftPaidAckPending };
            data.indexedDB.db = actualDb;
            const persistedAfterFailure = await new Promise((resolve, reject) => {
                const tx = db.transaction(['pos.order', 'pos.payment'], 'readonly');
                const request = tx.objectStore('pos.order').get('order');
                const payments = tx.objectStore('pos.payment').getAll();
                tx.oncomplete = () => resolve({ state: request.result.state, pending: !!JSON.parse(request.result.JSONuiState).baseerSharedDraftPaidAckPending,
                    payments: payments.result.map((item) => item.uuid) });
                tx.onabort = () => reject(tx.error);
            });
            data.indexedDB.db = { transaction(...args) { const tx = actualDb.transaction(...args); queueMicrotask(() => tx.abort()); return tx; } };
            let aborted = false;
            try { await store.baseerReconcileSharedPaidExperiment(order); } catch { aborted = true; }
            const afterAbort = { lines: order.lines.map((line) => line.uuid).sort(), payments: order.payment_ids.map((payment) => payment.uuid),
                pending: !!order.uiState.baseerSharedDraftPaidAckPending };
            data.indexedDB.db = actualDb;
            const reconciled = await store.baseerReconcileSharedPaidExperiment(order);
            const final = { lines: order.lines.map((line) => line.uuid).sort(), payments: order.payment_ids.map((payment) => payment.uuid),
                total: order.priceIncl, invoicePending: reconciled.invoicePending, ackPending: !!order.uiState.baseerSharedDraftPaidAckPending,
                pendingOrders: store.pendingOrder.write.size };
            db.close(); return { ...draftResult, quota, afterFailure, persistedAfterFailure, aborted, afterAbort, final };
        };` });
        const result = await page.evaluate(() => window.runRealModelTest());
        assert.ok(result.savedGeneration > result.sentGeneration);
        assert.deepEqual(result.lines, ['B']);
        assert.deepEqual(result.live, ['B']);
        assert.equal(result.state.baseerSharedDraftRevision, 1);
        assert.equal(result.state.baseerSharedDraftNeedsSync, true);
        assert.deepEqual(result.state.baseerSharedDraftLineDeletions.map((item) => item.id), [11]);
        assert.ok(result.commands.some((command) => [2, 3].includes(command[0]) && command[1] === 11));
        assert.equal(result.quota, true);
        assert.deepEqual(result.afterFailure.lines, ['B', 'preview-paid']);
        assert.deepEqual(result.afterFailure.payments, ['pay']);
        assert.equal(result.afterFailure.pending, true);
        assert.deepEqual(result.persistedAfterFailure, { state: 'paid', pending: true, payments: ['pay'] });
        assert.equal(result.aborted, true);
        assert.deepEqual(result.afterAbort, result.afterFailure);
        assert.deepEqual(result.final.lines, ['B', 'server-allowance']);
        assert.deepEqual(result.final.payments, ['pay']);
        assert.equal(result.final.total, 90);
        assert.equal(result.final.invoicePending, true);
        assert.equal(result.final.ackPending, false);
        assert.equal(result.final.pendingOrders, 0);
        await context.close();
    } finally { await browser.close(); }
});

test('paid ACK is reconciled after browser reload using native related models', async () => {
    const browser = await chromium.launch({ headless: true, ...(process.platform === 'win32' ? { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' } : {}) });
    try {
        const context = await browser.newContext();
        await context.route('**/*', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html></html>' }));
        const page = await context.newPage(); await page.goto('http://baseer-paid-restart.invalid/');
        await page.addScriptTag({ content: `${expSource.replaceAll('export async function', 'async function').replaceAll('export function', 'function')}\nwindow.persistPaidAck = persistDraftAckExperiment;` });
        await page.evaluate(async () => {
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const open = indexedDB.open('paid-restart', 1);
            open.onupgradeneeded = () => { for (const name of names) open.result.createObjectStore(name, { keyPath: name === 'product.attribute.custom.value' ? 'id' : 'uuid' }); };
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            const payload = { uuid: 'order', to_invoice: true, baseer_offline_discount_intent: { expected_total: '90.00', expected_tax: '0.00' } };
            const command = { order_uuid: 'order', revision: 1, command_uuid: 'paid', target_state: 'paid', generation: 5,
                source_line_uuids: ['B'], source_payment_uuids: ['pay'], payload_json: JSON.stringify(payload) };
            const response = { 'pos.order': [{ id: 42, uuid: 'order', state: 'paid', to_invoice: true, account_move: 77, lines: [12, 13], payment_ids: [20],
                    baseer_global_discount_locked: true, amount_total: 90, amount_tax: 0 }],
                'pos.order.line': [{ id: 12, uuid: 'B', order_id: 42, qty: 2, price_unit: 50 },
                    { id: 13, uuid: 'server-allowance', order_id: 42, qty: 1, price_unit: -10, baseer_global_discount_line: true }],
                'pos.payment': [{ id: 20, uuid: 'pay', pos_order_id: 42, amount: 90 }],
                'account.move': [{ id: 77, name: 'INV/77' }], 'product.attribute.custom.value': [] };
            const ui = { baseerOfflineDiscount: { kind: 'fixed', value: '10', preview_line_uuids: ['preview-paid'] },
                baseerSharedDraftPending: command, baseerSharedDraftRevisionWarningProvisional: true,
                baseerSharedDraftRefreshError: 'The shared order changed on another device. Keep your local changes for review.' };
            const line = (uuid, qty, price_unit) => ({ id: uuid, uuid, custom_attribute_value_ids: [],
                serializeForIndexedDB() { return { uuid, id: uuid, order_id: 42, qty, price_unit }; } });
            const payment = { id: 'pay', uuid: 'pay', serializeForIndexedDB() { return { uuid: 'pay', id: 'pay', pos_order_id: 42, amount: 90 }; } };
            const order = { id: 42, uuid: 'order', state: 'paid', lines: [line('B', 2, 50), line('preview-paid', 1, -10)], payment_ids: [payment], uiState: ui,
                serializeForIndexedDB() { return { id: 42, uuid: 'order', state: 'paid', to_invoice: true, lines: ['B', 'preview-paid'], payment_ids: ['pay'], JSONuiState: JSON.stringify(this.uiState) }; } };
            await window.persistPaidAck({ data: { indexedDB: { db } }, order, tracker: { get: () => 5 }, pending: command,
                revision: 2, serverOrderId: 42, lineIds: { B: 12 }, paymentIds: { pay: 20 }, serverResponse: response, protect() {} });
            db.close();
        });
        await page.reload();
        const posPatch = readFileSync(new URL('../static/src/app/global_discount.js', import.meta.url), 'utf8');
        const reconcileStart = posPatch.indexOf('    async baseerReconcileSharedPaidExperiment(order) {');
        const reconcileEnd = posPatch.indexOf('    async baseerVerifySharedInvoiceExperiment(', reconcileStart);
        const protectionStart = posPatch.indexOf('function protectOfflineStorage(');
        const protectionEnd = posPatch.indexOf('// Native cleanup', protectionStart);
        assert.ok(reconcileStart >= 0 && reconcileEnd > reconcileStart && protectionStart >= 0 && protectionEnd > protectionStart);
        const reconcileMethod = posPatch.slice(reconcileStart, reconcileEnd).replace(/},\s*$/, '}\n');
        const syncStart = posPatch.indexOf('    async syncAllOrders(options = {}) {');
        const syncEnd = posPatch.indexOf('    async preSyncAllOrders(', syncStart);
        assert.ok(syncStart >= 0 && syncEnd > syncStart);
        const syncMethod = posPatch.slice(syncStart, syncEnd).replace(/},\s*$/, '}\n');
        const warningStart = posPatch.indexOf('function touchExperimentalDraftGraph('), warningEnd = posPatch.indexOf('\nfunction noteSharedDraftEdit(', warningStart);
        assert.ok(warningStart >= 0 && warningEnd > warningStart);
        const experiment = expSource.replaceAll('export async function', 'async function').replaceAll('export function', 'function');
        await page.addScriptTag({ content: `${nativeBundle()}\n${experiment}\nconst paidReconciliationOrders = new WeakSet(), sharedRefreshOrders = new WeakSet(), sharedRevisionPromises = new WeakMap(), sharedRevisionWarningOwners = new WeakMap();
            const SHARED_DRAFT_FLOW_ENABLED = true, _t = value => value, isManagedSharedDraft = order => Boolean(order.uiState?.baseerSharedDraftPaidAckPending);
            class ConnectionLostError extends Error {} class ParentStore { async syncAllOrders() { return []; } }
            ${posPatch.slice(protectionStart, protectionEnd)}\n${posPatch.slice(warningStart, warningEnd)}\nclass TestStore extends ParentStore { ${reconcileMethod} ${syncMethod} }\nwindow.resumePaid = async () => {
            const defs = {
                'pos.order': { id: { type: 'integer' }, uuid: { type: 'char' }, state: { type: 'char' }, amount_total: { type: 'float' }, amount_tax: { type: 'float' },
                    baseer_global_discount_locked: { type: 'boolean' }, to_invoice: { type: 'boolean' }, account_move: { type: 'many2one', relation: 'account.move' },
                    lines: { name: 'lines', model: 'pos.order', type: 'one2many', relation: 'pos.order.line', inverse_name: 'order_id' },
                    payment_ids: { name: 'payment_ids', model: 'pos.order', type: 'one2many', relation: 'pos.payment', inverse_name: 'pos_order_id' } },
                'pos.order.line': { id: { type: 'integer' }, uuid: { type: 'char' }, qty: { type: 'float' }, price_unit: { type: 'float' },
                    order_id: { name: 'order_id', model: 'pos.order.line', type: 'many2one', relation: 'pos.order' }, baseer_global_discount_line: { type: 'boolean' } },
                'pos.payment': { id: { type: 'integer' }, uuid: { type: 'char' }, amount: { type: 'float' }, pos_order_id: { name: 'pos_order_id', model: 'pos.payment', type: 'many2one', relation: 'pos.order' } },
                'product.attribute.custom.value': { id: { type: 'integer' } }, 'account.move': { id: { type: 'integer' }, name: { type: 'char' } },
            };
            class TestOrder extends Base { static enableLazyGetters = false; get currency() { return { round: (value) => Math.round(value * 100) / 100 }; }
                get priceIncl() { return this.lines.reduce((sum, line) => sum + line.qty * line.price_unit, 0); } get amountTaxes() { return 0; } }
            const { models } = createRelatedModels(defs, { 'pos.order': TestOrder }, { dynamicModels: ['pos.order', 'pos.order.line', 'pos.payment'],
                databaseTable: { 'pos.order': { key: 'uuid' }, 'pos.order.line': { key: 'uuid' }, 'pos.payment': { key: 'uuid' } },
                databaseIndex: { 'pos.order': ['uuid'], 'pos.order.line': ['uuid'], 'pos.payment': ['uuid'] } });
            const open = indexedDB.open('paid-restart', 1);
            const db = await new Promise((resolve, reject) => { open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error); });
            const names = ['pos.order', 'pos.order.line', 'pos.payment', 'product.attribute.custom.value'];
            const tx = db.transaction(names, 'readonly');
            const all = (name) => new Promise((resolve, reject) => { const request = tx.objectStore(name).getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
            const rows = await Promise.all(names.map(all));
            models.loadConnectedData(Object.fromEntries(names.map((name, index) => [name, rows[index]])));
            const order = models['pos.order'].getBy('uuid', 'order');
            const data = { indexedDB: { db }, missingRecursive: async (value) => value,
                orm: { read: async () => { throw new Error('access denied'); } }, localUnsyncedPaidOrderUuids: new Set(['order']) };
            const store = new TestStore(); store.models = models; store.data = data; store.getPendingOrder = () => ({ orderToCreate: [], orderToUpdate: [] });
            let reconciliations = 0, sent = 0;
            const actualReconcile = store.baseerReconcileSharedPaidExperiment.bind(store);
            store.baseerReconcileSharedPaidExperiment = async (...args) => { reconciliations++; return actualReconcile(...args); };
            store.baseerRunSharedDraftExperiment = async () => { sent++; throw new Error('must not send another payment'); };
            store.pendingOrder = { create: new Set(), write: new Set([42]), delete: new Set() };
            const result = await store.syncAllOrders({ orders: [order], throw: true });
            const final = { invoicePending: order.uiState.baseerSharedDraftInvoicePending, total: order.priceIncl, reconciliations, sent,
                lines: order.lines.map((line) => line.uuid).sort(), payments: order.payment_ids.map((payment) => payment.uuid),
                ackPending: !!order.uiState.baseerSharedDraftPaidAckPending };
            db.close(); return final;
        };` });
        const result = await page.evaluate(() => window.resumePaid());
        assert.deepEqual(result.lines, ['B', 'server-allowance']);
        assert.deepEqual(result.payments, ['pay']);
        assert.equal(result.total, 90);
        assert.equal(result.invoicePending, true);
        assert.equal(result.ackPending, false);
        assert.equal(result.reconciliations, 1); assert.equal(result.sent, 0);
        await context.close();
    } finally { await browser.close(); }
});

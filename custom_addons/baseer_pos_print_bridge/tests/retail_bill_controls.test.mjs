import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

test('retail split resumes only the linked unpaid order; restaurant delegates', () => {
    class PosStore {
        isContinueSplitting() { return 'native'; }
    }
    const sandbox = { PosStore, patch(target, extension) {
        Object.setPrototypeOf(extension, { ...Object.fromEntries(
            Object.getOwnPropertyNames(target).map((key) => [key, target[key]])
        ) });
        Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
    } };
    vm.createContext(sandbox);
    const source = readFileSync(new URL('../static/src/app/retail_bill_controls.js', import.meta.url), 'utf8');
    vm.runInContext(source.replace(/^import .*;\r?\n/gm, ''), sandbox);
    const store = new PosStore();
    store.config = { module_pos_restaurant: false, iface_splitbill: true };
    const original = { uuid: 'original', finalized: false };
    const paid = { originalSplittedOrder: original };
    assert.equal(store.isContinueSplitting(paid), true);
    original.finalized = true;
    assert.equal(store.isContinueSplitting(paid), false);
    assert.equal(store.isContinueSplitting({ originalSplittedOrder: undefined }), false);
    assert.equal(store.isContinueSplitting({ originalSplittedOrder: null }), false);
    store.config.module_pos_restaurant = true;
    assert.equal(store.isContinueSplitting(paid), 'native');
    store.config.module_pos_restaurant = false;
    store.config.iface_splitbill = false;
    assert.equal(store.isContinueSplitting(paid), 'native');
});

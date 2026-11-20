import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('native receipt is drawn at 576 pixels after its images load', async () => {
    const calls = [];
    globalThis.Node = { TEXT_NODE: 3 };
    globalThis.receiptCanvas = async (node, options) => { calls.push('canvas'); return { width: Math.round(options.width * options.pixelRatio), options }; };
    globalThis.receiptWait = async () => { calls.push('images'); };
    let source = readFileSync(new URL('../static/src/app/receipt_image.js', import.meta.url), 'utf8')
        .replace('import { _t } from "@web/core/l10n/translation";', 'const _t = value => value;')
        .replace('import { toCanvas } from "@point_of_sale/app/utils/html-to-image";', 'const toCanvas = globalThis.receiptCanvas;')
        .replace('import { waitImages } from "@point_of_sale/utils";', 'const waitImages = globalThis.receiptWait;');
    const { renderReceiptCanvas } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
    const text = { nodeType: 3, textContent: 'A\u0001B' };
    const element = { nodeType: 1, childNodes: [text], classList: { add(...args) { calls.push(args.join(' ')); } } };
    const renderer = { async toHtml(component, props) { assert.equal(props.order, 7); return element; }, async whenMounted({ el, callback }) { assert.equal(el, element); return callback({ clientWidth: 252, clientHeight: 800 }); } };
    const result = await renderReceiptCanvas(renderer, class {}, { order: 7 });
    assert.equal(result.width, 576);
    assert.equal(result.options.pixelRatio, 576 / 252);
    assert.equal(result.options.includeQueryParams, true);
    assert.equal(text.textContent, 'AB');
    assert.deepEqual(calls, ['pos-receipt-print p-3 baseer-receipt-image', 'images', 'canvas']);
});


test('receipt image font is scoped to the raster root and registered', () => {
    const css = readFileSync(new URL('../static/src/app/receipt_image.scss', import.meta.url), 'utf8');
    const manifest = readFileSync(new URL('../__manifest__.py', import.meta.url), 'utf8');
    assert.match(css, /\.pos-receipt\.baseer-receipt-image\s*\{/);
    assert.match(css, /font-family:\s*Tahoma, Arial, ['"]DejaVu Sans['"], ['"]Noto Sans Arabic['"], sans-serif/);
    assert.match(css, /--bs-font-monospace:\s*Tahoma, Arial/);
    assert.doesNotMatch(css, /\*|!important/);
    assert.match(manifest, /baseer_pos_print_bridge\/static\/src\/app\/receipt_image\.scss/);
});

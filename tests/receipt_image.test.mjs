import {readFileSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync('custom_addons/baseer_pos_print_bridge/static/src/app/receipt_image.js','utf8').replace('import { _t } from "@web/core/l10n/translation";', 'const _t = (value) => value;');
const {encodeReceiptJpeg}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const jpeg=bytes=>'data:image/jpeg;base64,'+Buffer.alloc(bytes,42).toString('base64');
function fixture(sizes){let calls=[];const canvas={getContext:()=>({fillRect(){},drawImage(){}}),toDataURL(type,q){calls.push(q);return jpeg(sizes[calls.length-1]??sizes.at(-1));}};return {canvas,calls,create:()=>canvas};}
let f=fixture([151055]);assert.equal(Buffer.from(encodeReceiptJpeg({width:576,height:1500},f.create),'base64').length,151055);assert.deepEqual(f.calls,[.95]);
f=fixture([310000,280000,240000]);assert.equal(Buffer.from(encodeReceiptJpeg({width:576,height:1500},f.create),'base64').length,240000);assert.deepEqual(f.calls,[.95,.9,.85]);assert.equal(f.canvas.width,576);assert.equal(f.canvas.height,1500);
f=fixture([262144]);assert.equal(Buffer.from(encodeReceiptJpeg({width:576,height:1500},f.create),'base64').length,262144);
f=fixture([262145]);assert.throws(()=>encodeReceiptJpeg({width:576,height:1500},f.create),/256 KB/);assert.equal(f.calls.length,4);
assert.throws(()=>encodeReceiptJpeg({width:0,height:0}),/rendered/);assert.throws(()=>encodeReceiptJpeg({width:576,height:9000}),/length/);
console.log('PASS: unchanged small images, adaptive compression, exact byte boundary, bounded quality, width preservation, invalid/long images');

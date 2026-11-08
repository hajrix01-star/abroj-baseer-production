import {readFileSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync('custom_addons/baseer_pos_print_bridge/static/src/app/receipt_image.js','utf8').replace('import { _t } from "@web/core/l10n/translation";', 'const _t = (value) => value;');
const {encodeReceiptJpeg}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const jpeg=bytes=>{const data=Buffer.alloc(bytes,42);Buffer.from([0xff,0xd8,0xff,0xda,0,2]).copy(data);return 'data:image/jpeg;base64,'+data.toString('base64');};
function fixture(sizes){let calls=[];const canvas={getContext:()=>({fillRect(){},drawImage(){}}),toDataURL(type,q){calls.push(q);return jpeg(sizes[calls.length-1]??sizes.at(-1));}};return {canvas,calls,create:()=>canvas};}
let f=fixture([151055]);assert.equal(Buffer.from(encodeReceiptJpeg({width:576,height:1500},f.create),'base64').length,151055);assert.deepEqual(f.calls,[.95]);
f=fixture([310000,280000,240000]);assert.equal(Buffer.from(encodeReceiptJpeg({width:576,height:1500},f.create),'base64').length,240000);assert.deepEqual(f.calls,[.95,.9,.85]);assert.equal(f.canvas.width,576);assert.equal(f.canvas.height,1500);
f=fixture([262144]);assert.equal(Buffer.from(encodeReceiptJpeg({width:576,height:1500},f.create),'base64').length,262144);
f=fixture([262145]);assert.throws(()=>encodeReceiptJpeg({width:576,height:1500},f.create),/256 KB/);assert.equal(f.calls.length,4);
assert.throws(()=>encodeReceiptJpeg({width:0,height:0}),/rendered/);assert.throws(()=>encodeReceiptJpeg({width:576,height:9000}),/length/);
// Safari can add an EXIF APP1 block even to a freshly drawn canvas. Removing
// that block must preserve the encoded JPEG scan and unrelated metadata.
const sample=Buffer.from('ffd8ffe000044142ffe1000c45786966000001020304ffda00020102ff00ffe1ff00ffd9','hex');
const cleaned=Buffer.from('ffd8ffe000044142ffda00020102ff00ffe1ff00ffd9','hex');
const safari=fixture([100]);safari.canvas.toDataURL=()=>`data:image/jpeg;base64,${sample.toString('base64')}`;
assert.deepEqual(Buffer.from(encodeReceiptJpeg({width:576,height:1500},safari.create),'base64'),cleaned);
const xmp=Buffer.from('ffd8ffe100086e6f74457869ffda00020102ffd9','hex');
safari.canvas.toDataURL=()=>`data:image/jpeg;base64,${xmp.toString('base64')}`;
assert.deepEqual(Buffer.from(encodeReceiptJpeg({width:576,height:1500},safari.create),'base64'),xmp);
const malformed=Buffer.from('ffd8ffe1001a457869660000','hex');
safari.canvas.toDataURL=()=>`data:image/jpeg;base64,${malformed.toString('base64')}`;
assert.throws(()=>encodeReceiptJpeg({width:576,height:1500},safari.create),/JPEG receipt/);
console.log('PASS: unchanged small images, adaptive compression, exact byte boundary, bounded quality, width preservation, invalid/long images');

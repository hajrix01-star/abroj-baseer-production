// Execute the actual QA-transpiled modules, including the native recovery alias.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
const acceptance = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const source = path.join(process.argv[3], 'custom_addons/baseer_pos_cache_resilience');
const modules = new Map();
const localStorage = {};
Object.defineProperties(localStorage, {
    getItem: {value(key) {return this[key] ?? null;}},
    setItem: {value(key,value) {this[key]=String(value);}},
    removeItem: {value(key) {delete this[key];}},
});
let reloads=0;
const context = vm.createContext({console,localStorage,Symbol,
    odoo:{access_token:'qa',pos_config_id:27,define(name,deps,factory) {
        assert(!modules.has(name),`Duplicate module ${name}`);
        modules.set(name,factory(key=>{assert(modules.has(key),`Missing dependency ${key}`);return modules.get(key);}));
    }},
    sessionStorage:{clear(){}},navigator:{},window:{},location:{reload(){reloads++;}},setTimeout,
    luxon:{DateTime:{now:()=>({year:2026})}},
});
modules.set('@web/core/utils/patch',{patch(target,extension){
    Object.setPrototypeOf(extension,Object.create(null,Object.getOwnPropertyDescriptors(target)));
    Object.defineProperties(target,Object.getOwnPropertyDescriptors(extension));
}});
vm.runInContext(fs.readFileSync(path.join(source,'static/tests/fixtures/device_sequence_20260817.js'),'utf8')
    .replace('export default class','class')+'\nglobalThis.DeviceIdentifierSequence=DeviceIdentifierSequence;',context);
vm.runInContext('const {DateTime}=luxon;\n'+fs.readFileSync(path.join(source,'static/tests/fixtures/store_numbering_20260817.js'),'utf8')+
    '\nglobalThis.PosStore=PosStore;',context);
modules.set('@point_of_sale/app/utils/devices_identifier_sequence',{[Symbol.for('default')]:context.DeviceIdentifierSequence});
modules.set('@point_of_sale/app/services/pos_store',{PosStore:context.PosStore});
for(const name of ['receipt_storage','reset_local_data','receipt_number_reservation']) {
    vm.runInContext(acceptance.compiled[name],context,{filename:name+'.compiled.js'});
}
const recovery=modules.get('@point_of_sale/app/components/loader/critical_pos_error/reset_local_data');
assert.equal(typeof recovery.resetLocalData,'function');
localStorage.setItem('qa-unique_device_identifier',JSON.stringify({device_identifier:'4',next_number:9,unsynced_number_stack:[8]}));
const device=new context.DeviceIdentifierSequence({orm:{}});
const order={pos_reference:'264-27-000008',isSynced:false};
const store=new context.PosStore();
Object.assign(store,{device,config:{id:27},models:{'pos.order':{getAll:()=>[order]}}});
const next={};store.setNextOrderRefs(next);
assert.equal(next.pos_reference,'264-27-000009');
assert.equal(order.pos_reference,'264-27-000008');
device.save({unsynced_number_stack:[9]});store.postSyncAllOrders([next]);
assert.equal(device.unsyncedNumberStack.length,0);
const frozen=localStorage.getItem('qa-unique_device_identifier');
localStorage.setItem('device_uuid','qa-uuid');localStorage.setItem('other-unique_device_identifier','other');localStorage.setItem('junk','remove');
await recovery.resetLocalData();
assert.equal(localStorage.getItem('qa-unique_device_identifier'),frozen);
assert.equal(localStorage.getItem('other-unique_device_identifier'),'other');
assert.equal(localStorage.getItem('device_uuid'),'qa-uuid');
assert.equal(localStorage.getItem('junk'),null);assert.equal(reloads,1);
console.log('QA_COMPILED_MODULES=PASS: allocation, offline-local allocation, sync reservation, native alias, critical reset counters');

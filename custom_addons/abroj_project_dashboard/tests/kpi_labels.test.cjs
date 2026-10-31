const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const js = path.join(__dirname, '..', 'static', 'pwa', 'js');
const i18n = fs.readFileSync(path.join(js, 'i18n.js'), 'utf8');
const app = fs.readFileSync(path.join(js, 'app.js'), 'utf8');
const cards = app.match(/^function cards\(ps,.*$/m)[0];
const context = vm.createContext({});
vm.runInContext(`${i18n}\nlet lang = 'ar';
const t = key => translations[key][lang];
const money = n => String(n);
${cards}`, context);

const project = [{contract: 100, actual: 40, expected_profit: 60, contract_profit: 55, remaining: 70, received: 30, paid: 5, liquidity: 25}];
assert.match(context.cards(project), /<small>الربح المتوقع<\/small><h3>60 /);
assert.match(context.cards(project), /<small>صافي التدفق النقدي<\/small><h3>25 /);
vm.runInContext("lang = 'en'", context);
assert.match(context.cards(project), /<small>Expected profit<\/small><h3>60 /);
assert.match(context.cards(project), /<small>Net cash flow<\/small><h3>25 /);

assert.match(context.cards(project), /<small>Contract profit<\/small><h3>55 /);
assert.match(context.cards(project), /<small>Remaining contract value<\/small><h3>70 /);
assert.match(context.cards(project), /<small>Received<\/small><h3>30 /);
assert.match(context.cards(project), /<small>Paid<\/small><h3>5 /);
const screens = fs.readFileSync(path.join(js, 'screens.js'), 'utf8');
for (const label of ['السجلات', 'سند أمر', 'التقارير اليومية']) assert.ok(screens.includes(label));

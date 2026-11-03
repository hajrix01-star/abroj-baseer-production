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
let data = {};
${cards}`, context);

const project = [{contract: 100, actual: 40, budget_available: true, budget: 40, over: 0,
    expected_profit: 60, contract_profit: 55, remaining: 70, received: 30, paid: 5,
    liquidity: 25, recognized_revenue: 20, recognized_profit: -20}];
context.project = project;
vm.runInContext('data = {financial_summary: project[0]}', context);
assert.match(context.cards(project), /<small>الهامش المتوقع حسب الميزانية<\/small><h3>60 /);
assert.match(context.cards(project), /<small>صافي التدفق النقدي<\/small><h3>25 /);
assert.match(context.cards(project), /<small>الإيراد المثبت محاسبيًا<\/small><h3>20 /);
assert.match(context.cards(project), /<small>الربح أو الخسارة المثبتة محاسبيًا<\/small><h3>-20 /);
vm.runInContext("lang = 'en'", context);
assert.match(context.cards(project), /<small>Expected margin against budget<\/small><h3>60 /);
assert.match(context.cards(project), /<small>Net cash flow<\/small><h3>25 /);
assert.match(context.cards(project), /<small>Recognized revenue<\/small><h3>20 /);
assert.match(context.cards(project), /<small>Recognized profit \/ loss<\/small><h3>-20 /);

assert.match(context.cards(project), /<small>Contract margin after commitments<\/small><h3>55 /);
assert.match(context.cards(project), /<small>Remaining contract value<\/small><h3>70 /);
assert.match(context.cards(project), /<small>Received<\/small><h3>30 /);
assert.match(context.cards(project), /<small>Paid<\/small><h3>5 /);
const screens = fs.readFileSync(path.join(js, 'screens.js'), 'utf8');
for (const label of ['السجلات', 'سند أمر', 'التقارير اليومية']) assert.ok(screens.includes(label));

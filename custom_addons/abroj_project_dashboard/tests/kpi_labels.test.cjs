const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const js = path.join(__dirname, '..', 'static', 'pwa', 'js');
const i18n = fs.readFileSync(path.join(js, 'i18n.js'), 'utf8');
const app = fs.readFileSync(path.join(js, 'app.js'), 'utf8');
const cards = app.match(/^function cards\(ps\).*$/m)[0];
const context = vm.createContext({});
vm.runInContext(`${i18n}\nlet lang = 'ar';
const t = key => translations[key][lang];
const money = n => String(n);
${cards}`, context);

const project = [{contract: 100, actual: 40, liquidity: 25}];
assert.match(context.cards(project), /<small>الربح المتوقع<\/small><h3>60 /);
assert.match(context.cards(project), /<small>صافي التدفق النقدي<\/small><h3>25 /);
vm.runInContext("lang = 'en'", context);
assert.match(context.cards(project), /<small>Expected profit<\/small><h3>60 /);
assert.match(context.cards(project), /<small>Net cash flow<\/small><h3>25 /);

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

const project = [{contract: 100, customer_received: 30, remaining: 70, actual: 40,
    advance_paid: 10, total_spent: 50, budget_available: true, budget_remaining: -10,
    budget_overrun: 10, project_cash: 25, projected_profit: 50}];
context.project = project;
vm.runInContext('data = {financial_summary: project[0]}', context);
for (const detail of [false, true]) {
    const html = context.cards(project, detail);
    assert.equal((html.match(/class="card"/g) || []).length, 6);
    for (const label of ['قيمة العقد', 'المحصّل من العميل', 'المنصرف', 'الباقي من الميزانية', 'الكاش بيد المشروع', 'الربح المتوقع']) assert.ok(html.includes(label));
    assert.match(html, /الباقي: 70/);
    assert.match(html, /فعلي 40 \+ مقدّم 10/);
    assert.match(html, /class="kpi-danger">تجاوز الميزانية: 10/);
    assert.match(html, /قيمة العقد − max\(الميزانية، المنصرف\)/);
}
project[0].budget_available = false;
project[0].budget_remaining = null;
project[0].budget_overrun = null;
assert.match(context.cards(project), /لا توجد ميزانية/);
assert.doesNotMatch(context.cards(project), /kpi-danger/);
vm.runInContext("lang = 'en'", context);
assert.match(context.cards(project), /Customer collections/);
assert.match(context.cards(project), /No budget/);
const screens = fs.readFileSync(path.join(js, 'screens.js'), 'utf8');
for (const label of ['السجلات', 'سند أمر', 'التقارير اليومية']) assert.ok(screens.includes(label));

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
    budget_overrun: 10, budget: 40, paid: 5, project_cash: 25, projected_profit: 50}];
context.project = project;
vm.runInContext('data = {financial_summary: project[0]}', context);
for (const detail of [false, true]) {
    const html = context.cards(project, detail);
    assert.equal((html.match(/class="card"/g) || []).length, 6);
    for (const label of ['قيمة العقد', 'المحصّل من العميل', 'المصروف', 'المتبقي من الميزانية', 'النقد المتاح للمشروع', 'الربح المتوقع']) assert.ok(html.includes(label));
    assert.match(html, /متبقي للتحصيل 70/);
    assert.match(html, /فعلي 40 \+ مقدّمات 10/);
    assert.match(html, /kpi-danger">تجاوز 10/);
    assert.match(html, /محصّل 30 − مدفوع 5/);
    assert.match(html, /<strong>100<\/strong><span class="kpi-currency">ر.س<\/span>/);
    assert.match(html, /قيمة العقد ناقص الأعلى من الميزانية أو المصروف/);
}
project[0].budget_overrun = 0;
assert.match(context.cards(project), /من ميزانية 40/);
project[0].budget_available = false;
project[0].budget_remaining = null;
project[0].budget_overrun = null;
assert.match(context.cards(project), /لا توجد ميزانية/);
assert.doesNotMatch(context.cards(project), /kpi-danger/);
vm.runInContext("lang = 'en'", context);
assert.match(context.cards(project), /Collected from client/);
assert.match(context.cards(project), /No budget/);
const screens = fs.readFileSync(path.join(js, 'screens.js'), 'utf8');
for (const label of ['السجلات', 'سند أمر', 'التقارير اليومية']) assert.ok(screens.includes(label));

const categoryCards = app.match(/^function categoryCards\(p\).*$/m)[0];
vm.runInContext(`const esc = s => s; const emptyState = s => s; ${categoryCards}`, context);
const categories = {categories: [{name: 'Parent', budget: 100, actual: 110, advance_paid: 10, total_spent: 120, remaining: -20}],
    categories_total: {budget: 100, actual: 110, advance_paid: 10, total_spent: 120, remaining: -20}};
categories.categories[0].phase = 'Foundation';
let categoryHtml = context.categoryCards(categories);
assert.match(categoryHtml, /Phase:.*title="Foundation"/);
categories.categories[0].phase = '';
assert.match(context.categoryCards(categories), /title="—"/);
assert.match(categoryHtml, /Remaining -20/);
assert.match(categoryHtml, /Total/);
assert.equal((categoryHtml.match(/class="kpi-danger"/g) || []).length, 2);
vm.runInContext("lang = 'ar'", context);
categoryHtml = context.categoryCards(categories);
assert.match(categoryHtml, /المتبقي -20/);
assert.match(categoryHtml, /المجموع/);
const xml = fs.readFileSync(path.join(__dirname, '..', 'static', 'src', 'dashboard.xml'), 'utf8');
for (const value of ['categoryLabels.remaining', 'categoryLabels.total', 'c.remaining', 'categories_total.budget', 'categories_total.actual', 'categories_total.advance_paid', 'categories_total.total_spent', 'categories_total.remaining']) assert.ok(xml.includes(value));
assert.match(xml, /categories_total.remaining &lt; 0/);

assert.ok(xml.includes('categoryLabels.phase'));
assert.ok(xml.includes('t-att-title="c.phase'));
assert.ok(app.includes("t('budgetPhase')"));
assert.ok(app.includes("esc(c.phase||'—')"));
const backend = fs.readFileSync(path.join(__dirname, '..', 'static', 'src', 'dashboard.js'), 'utf8');
for (const label of ['Collected from client', 'Left to collect', 'Spent', 'Advances', 'Budget remaining', 'of budget', 'Overrun', 'Project cash available', 'Collected', 'paid', 'Expected profit', 'Contract value minus the higher of budget or spent']) assert.ok(backend.includes(`_t('${label}')`), label);
assert.match(xml, /class="ab_kpi_amount"><strong t-esc="money\(card.value\)"\/><span class="ab_kpi_currency" t-esc="currency"\/>/);
vm.runInContext("lang = 'en'", context);
assert.match(context.cards(project), /<strong>100<\/strong><span class="kpi-currency">SAR<\/span>/);

// Real Chromium + the target Odoo's Owl runtime; no production sessions/data.
// node this-file.mjs /path/to/owl.js /path/to/node_modules [--expect-compile-error]
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const [owlPath, packages, expectedFailure] = process.argv.slice(2);
assert(owlPath && packages, 'Provide the target Owl runtime and Playwright package directory');
const require = createRequire(resolve(packages, '../package.json'));
const { chromium } = require('playwright');
let browser;
try {
    browser = await chromium.launch({ headless: true });
} catch {
    browser = await chromium.launch({ headless: true, channel: 'msedge' });
}
const page = await browser.newPage();
const template = readFileSync(process.env.BASEER_SETTLEMENT_TEMPLATE
    || new URL('../static/src/payment_settlement_selector.xml', import.meta.url), 'utf8');
const fieldSource = readFileSync(new URL('../static/src/payment_settlement_selector.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/export class /g, 'class ');
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
    await page.setContent('<html><body><div id="target"></div></body></html>');
    await page.addScriptTag({ content: readFileSync(owlPath, 'utf8') });
    await page.evaluate(({ template, fieldSource }) => {
        window.scenario = async ({ readonly = false, allowed = true, credit = false } = {}) => {
            document.getElementById('target').replaceChildren();
            const { Component, useEffect, useState } = owl;
            class Dropdown extends Component {
                static template = owl.xml`<div><t t-slot="default"/><div class="options"><t t-slot="content"/></div></div>`;
                static props = ['slots'];
            }
            class DropdownItem extends Component {
                static template = owl.xml`<button class="option" t-on-click="props.onSelected"><t t-slot="default"/></button>`;
                static props = ['onSelected', 'slots'];
            }
            const calls = [], updates = [];
            const useService = () => ({ call: async (...args) => {
                calls.push(args);
                return { payment_points: [{ id: 7, name: 'Branch bank' }], representatives: [], can_use_representative: false };
            } });
            const user = { hasGroup: async group => allowed && group.endsWith('group_procurement_cashier') };
            const standardFieldProps = { readonly: Boolean, record: Object };
            const _t = value => value;
            const registry = { category: () => ({ add() {} }) };
            const { Selector, Toggle } = eval(fieldSource + '\n({Selector: PaymentSettlementSelector, Toggle: PaymentCreditToggle})');
            const record = { data: {
                company_id: [1, 'Branch'], payment_method_line_id: [7, 'Saved bank'],
                payment_source_type: credit ? 'credit' : 'payment_method', is_credit: credit,
            }, update: async values => { updates.push(values); Object.assign(record.data, values); } };
            const app = new owl.App(Selector, { templates: template, props: { readonly, record } });
            const field = await app.mount(document.getElementById('target'));
            await field.refreshChoices();
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            window.current = { app, field, calls, updates, record, Toggle, template };
            return { calls: calls.length, disabled: document.querySelector('.o_baseer_settlement_picker__trigger').disabled,
                label: document.querySelector('.o_baseer_settlement_picker__trigger').textContent.trim() };
        };
    }, { template, fieldSource });
    if (expectedFailure === '--expect-compile-error') {
        await assert.rejects(page.evaluate(() => window.scenario({ readonly: true })), /Failed to compile template/);
        console.log('BASELINE_REPRODUCED: real Owl template compilation fails');
    } else {
        const readonly = await page.evaluate(() => window.scenario({ readonly: true }));
        assert.equal(readonly.disabled, true);
        assert.equal(readonly.calls, 0);
        assert.equal(readonly.label, 'Saved bank');
        await page.evaluate(() => window.current.app.destroy());
        const branch = await page.evaluate(() => window.scenario());
        assert.equal(branch.disabled, false);
        await page.locator('.options').getByRole('button', { name: 'Branch bank', exact: true }).click();
        const saved = await page.evaluate(() => window.current.updates);
        assert.equal(saved.length, 1);
        assert.equal(saved[0].payment_method_line_id.id, 7);
        await page.evaluate(() => window.current.app.destroy());
        const denied = await page.evaluate(() => window.scenario({ allowed: false }));
        assert.equal(denied.disabled, true);
        assert.equal(denied.calls, 0);
        await page.evaluate(() => window.current.app.destroy());
        const credit = await page.evaluate(() => window.scenario({ credit: true }));
        assert.equal(credit.disabled, true);
        assert.equal(credit.label, 'Credit');
        await page.evaluate(async () => {
            window.current.app.destroy();
            const toggleApp = new owl.App(window.current.Toggle, { templates: window.current.template,
                props: { readonly: false, record: window.current.record } });
            await toggleApp.mount(document.getElementById('target'));
            window.toggleApp = toggleApp;
        });
        assert.equal(await page.getByRole('checkbox').isChecked(), true);
        await page.getByRole('checkbox').uncheck();
        assert.equal(await page.evaluate(() => window.current.record.data.is_credit), false);
        assert.deepEqual(errors, []);
        console.log('OWL_BROWSER_PASS: both templates compile; readonly, branch selection, unauthorized, credit and credit toggle render correctly');
    }
} finally {
    await browser.close();
}

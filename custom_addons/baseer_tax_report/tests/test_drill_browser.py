"""Exercise the real web action service, not a mocked doAction response."""

import json

from odoo.tests.common import HttpCase, tagged

from .test_report_drill import TestVatDrillSelectors


@tagged('post_install', '-at_install', 'reports_source_browser')
class TestVatSourceBrowser(HttpCase):
    browser_size = '1280x812'
    _nonzero_reader_fixture = TestVatDrillSelectors._nonzero_reader_fixture

    def test_amount_to_authorized_source_list(self):
        self.env['res.lang']._activate_lang('ar_001')
        engine, _filters, move, _income, _journal = self._nonzero_reader_fixture()
        reader = engine.env.user
        reader.sudo().write({'password': 'vat-drill-synthetic', 'lang': 'ar_001'})
        self.env.flush_all()
        script = r"""
        (async () => {
            const moveName = __MOVE__;
            const wait = async (predicate, label) => {
                const deadline = performance.now() + 20000;
                while (performance.now() < deadline) {
                    const error = document.querySelector('.o_baseer_report_drill [role="alert"]');
                    if (error) { throw new Error(error.textContent); }
                    const result = predicate();
                    if (result) { return result; }
                    await new Promise(resolve => setTimeout(resolve, 25));
                }
                throw new Error('Timed out: ' + label);
            };
            const report = await wait(() => document.querySelector('.o_baseer_vat_report'), 'VAT report');
            await wait(() => report.querySelector('.o_baseer_vat_table'), 'initial RPC');
            const change = (selector, value) => {
                const input = report.querySelector(selector);
                input.value = value;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            };
            change('input[type="number"]', '2098');
            change('select[aria-label="الربع"]', '4');
            const apply = await wait(() => {
                const button = report.querySelector('.o_baseer_report_apply');
                return button && !button.disabled ? button : null;
            }, 'apply');
            apply.click();
            const amount = await wait(() => [...report.querySelectorAll('.o_baseer_vat_cell_button')]
                .find(button => button.getAttribute('aria-label') === 'عرض القيود الداعمة 1 الضريبة'
                    && button.textContent.trim() === '15.00'), 'synthetic tax amount');
            amount.click();
            await wait(() => [...document.querySelectorAll('.o_baseer_drill_table button')]
                .find(button => button.textContent.trim() === moveName), 'source in actual dialog');
            const directDialog = document.querySelector('.o_baseer_amount_details_dialog');
            if (!directDialog || directDialog.querySelector('.o_baseer_drill_value').textContent.trim() !== '15.00') {
                throw new Error('Direct VAT amount did not use the shared amount dialog');
            }
            directDialog.closest('.modal-content').querySelector('.o_baseer_drill_close').click();
            await wait(() => !document.querySelector('.o_baseer_report_drill'), 'direct dialog closed');

            const composite = await wait(() => [...report.querySelectorAll('.o_baseer_vat_cell_button')]
                .find(button => button.getAttribute('aria-label') === 'عرض القيود الداعمة 6 الضريبة'
                    && button.textContent.trim() === '15.00'), 'synthetic composite tax amount');
            composite.click();
            const loadedDialog = () => {
                const dialog = document.querySelector('.o_baseer_amount_details_dialog');
                return dialog?.getAttribute('aria-busy') === 'false' && dialog.querySelector('.o_baseer_drill_table')
                    ? dialog : null;
            };
            const compositeDialog = await wait(loadedDialog, 'composite shared amount dialog');
            const componentAmount = () => {
                const dialog = loadedDialog();
                if (!dialog) { return null; }
                const row = [...dialog.querySelectorAll('tbody tr')]
                    .find(item => item.querySelector('td')?.textContent.trim() === '1');
                return row?.querySelector('td[dir="ltr"] button');
            };
            if (compositeDialog.querySelector('.o_baseer_drill_value').textContent.trim() !== '15.00' ||
                report.querySelector('.o_baseer_vat_components')) {
                throw new Error('Composite VAT amount bypassed the shared dialog');
            }
            for (let visit = 0; visit < 2; visit++) {
                const child = await wait(componentAmount, 'box 1 tax component amount');
                if (child.textContent.trim() !== '+15.00') { throw new Error('Signed VAT component amount changed'); }
                child.click();
                await wait(() => loadedDialog()?.textContent.includes(moveName), 'component source detail');
                if (document.querySelectorAll('.o_baseer_amount_details_dialog').length !== 1 ||
                    loadedDialog() !== compositeDialog ||
                    loadedDialog().querySelector('.o_baseer_drill_value').textContent.trim() !== '15.00') {
                    throw new Error('VAT component did not stay in the same authoritative dialog');
                }
                if (visit === 0) {
                    compositeDialog.closest('.modal-content').querySelector('.o_baseer_drill_back').click();
                    await wait(componentAmount, 'return to composite component list');
                }
            }
            const source = await wait(() => [...document.querySelectorAll('.o_baseer_drill_table button')]
                .find(button => button.textContent.trim() === moveName), 'source after component revisit');
            source.click();
            const list = await wait(() => {
                const element = document.querySelector('.o_list_view');
                return element && element.textContent.includes(moveName) ? element : null;
            }, 'real account move line list');
            if (document.querySelector('.o_baseer_report_drill')) {
                throw new Error('Source action did not close the detail dialog');
            }
            if (list.querySelectorAll('tr.o_data_row').length !== 1) {
                throw new Error('Source list is not limited to the authorized line');
            }
            console.log('BASEER_VAT_SOURCE_ACTION_REAL_PASS');
            console.log('BASEER_VAT_UNIFORM_COMPOSITE_SOURCE_PASS');
            console.log('test successful');
        })().catch(error => { console.error(error); throw error; });
        """.replace('__MOVE__', json.dumps(move.name))
        self.browser_js('/odoo/action-%s' % self.env.ref('baseer_reports_menu.action_baseer_reports_hub').id,
                        script, ready="!!document.querySelector('.o_baseer_reports_hub')", login=reader.login)


@tagged('post_install', '-at_install', 'reports_source_browser')
class TestVatSourceBrowserMobile(TestVatSourceBrowser):
    browser_size = '375x812'
    touch_enabled = True

    def test_amount_to_authorized_source_list(self):
        super().test_amount_to_authorized_source_list()

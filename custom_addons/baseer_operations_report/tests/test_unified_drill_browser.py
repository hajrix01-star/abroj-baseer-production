"""Real shared-dialog journeys; synthetic, non-admin, Arabic, two viewports.

Timings describe this single-reader browser run, not a production/WAN SLA.
Focusability and visible keyboard-focus styling are checked; activation uses click.
"""

import json

from odoo import Command, fields
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'operations_browser', 'reports_unified_drill_browser')
class TestUnifiedDrillBrowser(HttpCase):
    browser_size = '1280x812'

    def test_actual_activity_and_profit_dialogs(self):
        if 'baseer.account.activity' not in self.env or 'baseer.profit.loss.report' not in self.env:
            self.skipTest('The combined report installation is required for this browser journey.')
        self.env['res.lang']._activate_lang('ar_001')
        company = self.env.company
        today = fields.Date.today()
        accounts = self.env['account.account'].with_company(company)
        cash = accounts.create({'code': '989971', 'name': 'اختبار حركة موحدة', 'account_type': 'asset_cash',
                                'company_ids': [Command.set(company.ids)]})
        income = accounts.create({'code': '989972', 'name': 'اختبار إيراد موحد', 'account_type': 'income',
                                  'company_ids': [Command.set(company.ids)]})
        journal = self.env['account.journal'].create({'name': 'Unified drill browser synthetic',
                    'code': 'UDB', 'type': 'general', 'company_id': company.id})
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'entry', 'date': today, 'journal_id': journal.id,
            'line_ids': [Command.create({'name': 'مصدر تجريبي موحد', 'account_id': cash.id, 'debit': 37}),
                         Command.create({'name': 'مصدر تجريبي موحد', 'account_id': income.id, 'credit': 37})],
        })
        move._post(soft=False)
        reader = self.env['res.users'].create({'name': 'Unified drill browser reader',
            'login': 'unified.drill.browser', 'password': 'unified.drill.browser', 'lang': 'ar_001',
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                      self.env.ref('account.group_account_readonly').id])],
        })
        self.env.flush_all()
        fixture = {'account': cash.id, 'accountCode': income.code, 'journal': journal.id,
                   'dateFrom': str(today.replace(day=1)), 'dateTo': str(today), 'move': move.name}
        script = r"""
        (async () => {
            const fixture = __FIXTURE__;
            const metrics = { viewport: [window.innerWidth, window.innerHeight], language: 'ar',
                environment: 'synthetic_single_reader', activation: 'click_after_keyboard_focus_check', timings_ms: {} };
            const waitFor = async (predicate, description) => {
                const deadline = performance.now() + 20000;
                while (performance.now() < deadline) {
                    const result = predicate();
                    if (result) { return result; }
                    const error = document.querySelector('.o_baseer_report_drill [role="alert"], .o_baseer_activity_alert');
                    if (error) { throw new Error(description + ': ' + error.textContent); }
                    await new Promise(resolve => setTimeout(resolve, 25));
                }
                throw new Error('Timed out: ' + description);
            };
            const elapsed = (name, start) => { metrics.timings_ms[name] = Math.round(performance.now() - start); };
            const visible = element => element && element.getClientRects().length > 0;
            const focusAmount = button => {
                if (!button || button.tagName !== 'BUTTON' || button.disabled || button.tabIndex < 0) {
                    throw new Error('Amount is not keyboard focusable');
                }
                button.focus({ preventScroll: true });
                if (document.activeElement !== button) { throw new Error('Amount focus failed'); }
                // Check the actual shared :focus-visible rule without claiming a native key press.
                const cssRules = [...document.styleSheets].flatMap(sheet => {
                    try { return [...sheet.cssRules]; } catch { return []; }
                });
                if (!cssRules.some(rule => rule.selectorText?.includes('.o_baseer_amount_link:focus-visible') && rule.style.outlineStyle !== 'none')) {
                    throw new Error('Visible keyboard focus rule is missing');
                }
            };
            const checkDialog = async dialog => {
                if (dialog.getAttribute('dir') !== 'rtl') { throw new Error('Arabic detail direction lost'); }
                await document.fonts.load('12px "IBM Plex Sans Arabic"', 'تفاصيل المبلغ 123');
                if (!document.fonts.check('12px "IBM Plex Sans Arabic"', 'تفاصيل المبلغ 123') ||
                    !getComputedStyle(dialog).fontFamily.includes('IBM Plex Sans Arabic')) {
                    throw new Error('Shared detail font did not load');
                }
                const modal = dialog.closest('.modal-content');
                const box = modal.getBoundingClientRect();
                if (box.left < -1 || box.right > window.innerWidth + 1 || modal.scrollWidth > modal.clientWidth + 1) {
                    throw new Error('Shared dialog overflowed the viewport');
                }
                const value = dialog.querySelector('.o_baseer_drill_value');
                if (!value || /[٠-٩]/.test(value.textContent) || value.getAttribute('dir') !== 'ltr') {
                    throw new Error('Detail value lost western digits or numeric direction');
                }
                if (!dialog.querySelector('.o_baseer_drill_basis')?.textContent.trim()) {
                    throw new Error('Authoritative amount basis missing');
                }
            };
            const loadedDialog = () => {
                const element = document.querySelector('.o_baseer_report_drill');
                return element?.getAttribute('aria-busy') === 'false' && element.querySelector('.o_baseer_drill_table') ? element : null;
            };
            const selectReport = async (pattern, selector) => {
                const switcher = await waitFor(() => [...document.querySelectorAll('.o_baseer_report_switcher')].find(visible), 'report switcher');
                switcher.click();
                const choice = await waitFor(() => [...document.querySelectorAll('.dropdown-item')].find(item => visible(item) && pattern.test(item.textContent.trim())), 'report menu item');
                const start = performance.now();
                choice.click();
                const report = await waitFor(() => document.querySelector(selector), 'mounted report');
                return { report, start };
            };
            await waitFor(() => document.querySelector('.o_baseer_reports_hub.o_action'), 'hub');
            const activity = await selectReport(/^حركة حساب$|^Account Activity$/, '.o_baseer_account_activity');
            const accountSelect = await waitFor(() => activity.report.querySelector(`select option[value="${fixture.account}"]`)?.parentElement, 'authorized account options');
            elapsed('activity_open', activity.start);
            accountSelect.value = String(fixture.account);
            accountSelect.dispatchEvent(new Event('change', { bubbles: true }));
            const periodSelect = activity.report.querySelector('select[aria-label="الفترة"]');
            periodSelect.value = 'custom';
            periodSelect.dispatchEvent(new Event('change', { bubbles: true }));
            const from = await waitFor(() => activity.report.querySelector('input[name="dateFrom"]'), 'custom date filters');
            from.value = fixture.dateFrom;
            from.dispatchEvent(new Event('change', { bubbles: true }));
            const to = activity.report.querySelector('input[name="dateTo"]');
            to.value = fixture.dateTo;
            to.dispatchEvent(new Event('change', { bubbles: true }));
            const apply = await waitFor(() => {
                const button = activity.report.querySelector('.o_baseer_report_apply');
                return button && !button.disabled ? button : null;
            }, 'enabled apply');
            let start = performance.now();
            apply.click();
            const summary = await waitFor(() => activity.report.querySelector('.o_baseer_activity_period_totals'), 'real activity RPC');
            elapsed('activity_filter_report', start);
            if (activity.report.getAttribute('dir') !== 'rtl') { throw new Error('Activity is not RTL'); }
            const totals = [...summary.querySelectorAll('.o_baseer_amount_link')];
            if (totals.length !== 4 || totals[3].textContent.trim() !== '37.00') { throw new Error('Activity fixture total mismatch'); }
            focusAmount(totals[3]);
            start = performance.now();
            totals[3].click();
            let dialog = await waitFor(loadedDialog, 'real activity detail RPC');
            elapsed('activity_detail', start);
            await checkDialog(dialog);
            if (dialog.querySelector('.o_baseer_drill_value').textContent.trim() !== '37.00') { throw new Error('Detail header mismatch'); }
            const activitySource = dialog.querySelector('tbody td[dir="ltr"] button');
            focusAmount(activitySource);
            if (!dialog.textContent.includes(fixture.move)) { throw new Error('Activity detail source mismatch'); }
            dialog.closest('.modal-content').querySelector('.modal-footer .btn-primary').click();
            await waitFor(() => !document.querySelector('.o_baseer_report_drill'), 'detail closed');

            const profit = await selectReport(/^الربح والخسارة$|^Profit and Loss$/, '.o_baseer_pl_report');
            await waitFor(() => profit.report.querySelector('.o_baseer_pl_table tbody tr'), 'real profit report RPC');
            elapsed('profit_open_report', profit.start);
            const journals = profit.report.querySelector('.o_baseer_pl_journals');
            journals.querySelector('summary').click();
            const journal = await waitFor(() => journals.querySelector(`input[value="${fixture.journal}"]`), 'fixture journal');
            const previousIncomeRow = profit.report.querySelector('.o_baseer_pl_income');
            start = performance.now();
            journal.click();
            const incomeAmount = await waitFor(() => {
                const row = profit.report.querySelector('.o_baseer_pl_income');
                const amount = row?.querySelector('td .o_baseer_amount_link');
                const exports = [...profit.report.querySelectorAll('.o_baseer_report_exports button')];
                return row && row !== previousIncomeRow && visible(amount) && !amount.disabled &&
                    profit.report.querySelector('.o_baseer_pl_partial') &&
                    !profit.report.querySelector('.o_baseer_reports_hub_status') &&
                    exports.length === 2 && exports.every(button => !button.disabled) ? amount : null;
            }, 'fresh selected-journal income row');
            elapsed('profit_journal_filter', start);
            journals.querySelector('summary').click();
            profit.report.querySelector('.o_baseer_pl_income .o_baseer_pl_toggle').click();
            const expandedAccountAmount = await waitFor(() => {
                const row = [...profit.report.querySelectorAll('.o_baseer_pl_account')]
                    .find(item => item.textContent.includes(fixture.accountCode));
                return row?.querySelector('.o_baseer_pl_account_amount');
            }, 'expanded profit account');
            if (expandedAccountAmount.textContent.trim() !== '37.00') {
                throw new Error('Expanded profit account fixture mismatch');
            }
            focusAmount(expandedAccountAmount);
            start = performance.now();
            expandedAccountAmount.click();
            dialog = await waitFor(() => loadedDialog()?.textContent.includes(fixture.move) ? loadedDialog() : null,
                'nonzero report account opens shared details before source');
            elapsed('profit_expanded_account_detail', start);
            await checkDialog(dialog);
            if (dialog.querySelector('.o_baseer_drill_value').textContent.trim() !== '37.00' ||
                [...document.querySelectorAll('.o_form_view')].some(visible)) {
                throw new Error('Account click bypassed authoritative amount details');
            }
            dialog.closest('.modal-content').querySelector('.modal-footer .btn-primary').click();
            await waitFor(() => !document.querySelector('.o_baseer_report_drill'), 'account detail closed');
            await waitFor(() => document.activeElement === expandedAccountAmount, 'return focus to account amount');
            focusAmount(incomeAmount);
            start = performance.now();
            incomeAmount.click();
            dialog = await waitFor(loadedDialog, 'profit row detail');
            elapsed('profit_row_detail', start);
            await checkDialog(dialog);
            const accountRow = [...dialog.querySelectorAll('tbody tr')].find(row => row.textContent.includes(fixture.accountCode));
            const accountAmount = accountRow?.querySelector('td[dir="ltr"] button');
            focusAmount(accountAmount);
            start = performance.now();
            accountAmount.click();
            dialog = await waitFor(() => loadedDialog()?.textContent.includes(fixture.move) ? loadedDialog() : null, 'profit account source details');
            elapsed('profit_account_detail', start);
            await checkDialog(dialog);
            const sourceAmount = dialog.querySelector('tbody td[dir="ltr"] button');
            focusAmount(sourceAmount);
            start = performance.now();
            sourceAmount.click();
            await waitFor(() => [...document.querySelectorAll('.o_form_view')].find(form => visible(form) && form.textContent.includes(fixture.move)), 'authorized source form');
            elapsed('profit_source_form', start);
            metrics.keyboard_focus_checked = true;
            metrics.rtl_font_overflow_checked = true;
            console.log('BASEER_UNIFIED_DRILL_METRICS ' + JSON.stringify(metrics));
            console.log('test successful');
        })().catch(error => { console.error(error); throw error; });
        """.replace('__FIXTURE__', json.dumps(fixture, ensure_ascii=True))
        self.browser_js('/odoo/action-%s' % self.env.ref('baseer_reports_menu.action_baseer_reports_hub').id,
                        script, ready="!!document.querySelector('.o_baseer_reports_hub.o_action')", login=reader.login)


@tagged('post_install', '-at_install', 'operations_browser', 'reports_unified_drill_browser')
class TestUnifiedDrillBrowserMobile(TestUnifiedDrillBrowser):
    browser_size = '375x812'
    touch_enabled = True

    def test_actual_activity_and_profit_dialogs(self):
        super().test_actual_activity_and_profit_dialogs()

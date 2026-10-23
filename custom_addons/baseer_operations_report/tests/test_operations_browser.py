"""Browser smoke for the activated operations report."""

from datetime import timedelta

from odoo import Command, fields
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'operations_browser')
class TestOperationsBrowser(HttpCase):

    browser_size = '1280x812'

    def test_preview_filters_detail_and_scroll(self):
        company = self.env.company
        account = self.env['account.account'].with_company(company).create({
            'code': '989901', 'name': 'Browser gross operations income',
            'account_type': 'income',
            'company_ids': [Command.set(company.ids)],
        })
        journal = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', '=', 'sale'),
        ], limit=1)
        self.assertTrue(journal)
        partner = self.env['res.partner'].create({'name': 'Browser gross operations customer'})
        invoice = self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice', 'journal_id': journal.id,
            'partner_id': partner.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'name': 'Browser gross operations sale', 'quantity': 1,
                'price_unit': 100, 'account_id': account.id,
                'tax_ids': [Command.clear()],
            })],
        })
        invoice.action_post()
        prior_month = fields.Date.today().replace(day=1) - timedelta(days=1)
        cash = self.env['account.account'].with_company(company).create({
            'code': '989902', 'name': 'Browser unproven cash',
            'account_type': 'asset_cash',
            'company_ids': [Command.set(company.ids)],
        })
        other_asset = self.env['account.account'].with_company(company).create({
            'code': '989903', 'name': 'Browser unproven asset',
            'account_type': 'asset_current',
            'company_ids': [Command.set(company.ids)],
        })
        general = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(general)
        cash_outflow = self.env['account.move'].with_company(company).create({
            'move_type': 'entry', 'date': prior_month, 'journal_id': general.id,
            'line_ids': [
                Command.create({'account_id': other_asset.id, 'debit': 10}),
                Command.create({'account_id': cash.id, 'credit': 10}),
            ],
        })
        cash_outflow._post(soft=False)
        self.env.flush_all()
        action = self.env.ref('baseer_reports_menu.action_baseer_reports_hub')
        script = r"""
        (async () => {
            const waitFor = async (predicate, description) => {
                for (let attempt = 0; attempt < 120; attempt++) {
                    if (predicate()) { return predicate(); }
                    await new Promise((resolve) => setTimeout(resolve, 100));
                }
                throw new Error('Timed out waiting for ' + description);
            };
            const hub = await waitFor(() => document.querySelector('.o_baseer_reports_hub.o_action'), 'real report action');
            // Exercise the real report transition. Mounting Operations in a
            // separate host concealed the awaited onWillStart regression.
            const host = hub.querySelector(':scope > .o_baseer_reports_hub_body');
            const switcher = await waitFor(() => host.querySelector('.o_baseer_report_switcher'), 'installed report selector');
            switcher.click();
            const operations = await waitFor(() => [...document.querySelectorAll('.dropdown-item')].find(
                (item) => /Sales and Payments Summary|ملخص المبيعات والمدفوعات/.test(item.textContent)), 'owner summary selector entry');
            operations.click();
            await waitFor(() => host.querySelector('.o_baseer_go_report'), 'operations mounted through selector');
            if (host.querySelector('.o_baseer_vat_report')) { throw new Error('Previous VAT report remained visible'); }
            await waitFor(() => host.querySelector('.o_baseer_go_report .o_baseer_owner_difference'), 'owner summary preview');
            if (host.querySelector('.o_baseer_go_incomplete')) { throw new Error('Proven source was hidden'); }
            const periodButton = () => host.querySelector('button[aria-label="Period"], button[aria-label="الفترة"]');
            periodButton().click();
            const quarter = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_period_menu .o_baseer_pl_menu_row')].find(
                (row) => /Quarter|ربع سنة/.test(row.textContent)), 'quarter filter');
            quarter.querySelector('.o_baseer_pl_menu_select').click();
            await waitFor(() => /Q[1-4]|ربع|Quarter/.test(periodButton().textContent), 'quarter selected');
            periodButton().click();
            const month = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_period_menu .o_baseer_pl_menu_row')].find(
                (row) => /Month|شهر/.test(row.textContent)), 'month filter');
            month.querySelector('.o_baseer_pl_menu_select').click();
            await waitFor(() => host.querySelector('.o_baseer_go_report .o_baseer_owner_difference') && !host.querySelector('.o_baseer_reports_hub_status'), 'month report');

            const comparison = host.querySelector('button[aria-label="Comparison"], button[aria-label="المقارنة"]');
            comparison.click();
            const lastYear = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_comparison_menu .dropdown-item')].find(
                (item) => /Same period last year|الفترة نفسها العام الماضي/.test(item.textContent)), 'last-year comparison');
            lastYear.click();
            await waitFor(() => host.querySelectorAll('.o_baseer_owner_period').length === 2, 'comparison periods');
            comparison.click();
            const none = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_comparison_menu .dropdown-item')].find(
                (item) => /No comparison|دون مقارنة/.test(item.textContent)), 'no comparison');
            none.click();
            await waitFor(() => host.querySelectorAll('.o_baseer_owner_period').length === 1, 'single period');

            const currentMonth = periodButton().textContent;
            periodButton().click();
            const previousMonth = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_period_menu .o_baseer_pl_menu_row')].find(
                (row) => /Month|شهر/.test(row.textContent)), 'month navigation');
            previousMonth.querySelector('.o_baseer_pl_row_navigation button').click();
            await waitFor(() => host.querySelector('.o_baseer_go_incomplete'), 'unproven prior month');
            if (host.querySelector('.o_baseer_owner_summary') || periodButton().textContent === currentMonth) {
                throw new Error('Unproven period leaked amounts or did not advance');
            }
            periodButton().click();
            const nextMonth = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_period_menu .o_baseer_pl_menu_row')].find(
                (row) => /Month|شهر/.test(row.textContent)), 'return month navigation');
            nextMonth.querySelectorAll('.o_baseer_pl_row_navigation button')[1].click();
            await waitFor(() => host.querySelector('.o_baseer_go_report .o_baseer_owner_difference'), 'proven month restored');
            if (periodButton().textContent !== currentMonth) { throw new Error('Month anchor was not restored'); }

            const journals = host.querySelector('.o_baseer_pl_journals');
            journals.querySelector('summary').click();
            const journal = journals.querySelector('input[value="__JOURNAL_ID__"]');
            if (!journal) { throw new Error('Fixture journal missing from filter'); }
            journal.click();
            await waitFor(() => host.querySelector('.o_baseer_pl_partial'), 'selected-journal marker');
            journals.querySelector('summary').click();
            const last = await waitFor(() => host.querySelector('.o_baseer_owner_difference'), 'owner summary after journal filter');
            if (host.querySelector('.o_baseer_pl_table, .o_baseer_go_detail_page')) {
                throw new Error('Legacy financial table or account-detail path remained visible');
            }
            const filler = document.createElement('div');
            filler.style.height = '1600px';
            filler.textContent = 'Scroll fixture';
            last.before(filler);
            if (hub.scrollHeight <= hub.clientHeight || getComputedStyle(hub).overflowY !== 'auto') {
                throw new Error('Report action is not vertically scrollable');
            }
            last.scrollIntoView({ block: 'end' });
            await new Promise((resolve) => requestAnimationFrame(resolve));
            const viewport = hub.getBoundingClientRect();
            const box = last.getBoundingClientRect();
            if (hub.scrollTop <= 0 || box.top < viewport.top - 1 || box.bottom > viewport.bottom + 1) {
                throw new Error('Last row is unreachable at this viewport');
            }
            if (document.scrollingElement.scrollTop !== 0) { throw new Error('Body scrolled instead of report action'); }
            console.log('test successful');
        })().catch((error) => { console.error(error); throw error; });
        """.replace('__JOURNAL_ID__', str(journal.id)).replace('__ACCOUNT_CODE__', account.code)
        self.browser_js(
            '/odoo/action-%s' % action.id, script,
            ready="!!document.querySelector('.o_baseer_reports_hub.o_action')",
            login='admin',
        )


@tagged('post_install', '-at_install', 'operations_browser')
class TestOperationsBrowserMobile(TestOperationsBrowser):
    browser_size = '375x812'
    touch_enabled = True

    def test_preview_filters_detail_and_scroll(self):
        # Give the inherited journey its own class-bound Odoo test spec so
        # the explicit mobile CI selector actually collects and executes it.
        super().test_preview_filters_detail_and_scroll()

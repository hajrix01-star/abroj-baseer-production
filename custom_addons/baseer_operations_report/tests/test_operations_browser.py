"""Browser smoke for the deliberately unactivated operations preview."""

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
            const env = await waitFor(() => odoo.__WOWL_DEBUG__?.root?.env?.services?.orm && odoo.__WOWL_DEBUG__.root.env, 'installed Odoo client services');
            const operationsModule = odoo.loader.modules.get('@baseer_operations_report/operations');
            const webEnvModule = odoo.loader.modules.get('@web/env');
            if (!operationsModule?.BaseerOperationsPreview || !webEnvModule?.mountComponent) {
                throw new Error('Installed operations browser modules unavailable');
            }
            const { BaseerOperationsPreview } = operationsModule;
            const { mountComponent } = webEnvModule;
            const existing = hub.querySelector(':scope > .o_baseer_reports_hub_body');
            if (existing) { existing.style.display = 'none'; }
            const host = document.createElement('div');
            host.className = 'o_baseer_reports_hub_body';
            hub.append(host);
            const app = await mountComponent(BaseerOperationsPreview, host, { env, props: { embedded: true } });
            await waitFor(() => host.querySelector('.o_baseer_go_report .o_baseer_pl_net_income'), 'operations preview');
            if (!host.querySelector('.o_baseer_go_incomplete')) { throw new Error('Incomplete source warning missing'); }
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
            await waitFor(() => host.querySelector('.o_baseer_go_report .o_baseer_pl_net_income') && !host.querySelector('.o_baseer_reports_hub_status'), 'month report');

            const comparison = host.querySelector('button[aria-label="Comparison"], button[aria-label="المقارنة"]');
            comparison.click();
            const lastYear = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_comparison_menu .dropdown-item')].find(
                (item) => /Same period last year|الفترة نفسها العام الماضي/.test(item.textContent)), 'last-year comparison');
            lastYear.click();
            await waitFor(() => host.querySelectorAll('.o_baseer_pl_table thead th').length === 3, 'comparison column');
            comparison.click();
            const none = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_comparison_menu .dropdown-item')].find(
                (item) => /No comparison|دون مقارنة/.test(item.textContent)), 'no comparison');
            none.click();
            await waitFor(() => host.querySelectorAll('.o_baseer_pl_table thead th').length === 2, 'single period');

            const journals = host.querySelector('.o_baseer_pl_journals');
            journals.querySelector('summary').click();
            const journal = journals.querySelector('input[value="__JOURNAL_ID__"]');
            if (!journal) { throw new Error('Fixture journal missing from filter'); }
            journal.click();
            await waitFor(() => host.querySelector('.o_baseer_pl_partial'), 'selected-journal marker');
            journals.querySelector('summary').click();
            host.querySelector('.o_baseer_pl_income .o_baseer_pl_toggle').click();
            const account = await waitFor(() => [...host.querySelectorAll('.o_baseer_pl_account')].find(
                (row) => row.textContent.includes('__ACCOUNT_CODE__')), 'source account');
            account.querySelector('button.o_baseer_pl_account_amount').click();
            await waitFor(() => host.querySelector('.o_baseer_go_detail_page .o_baseer_go_events tbody tr'), 'separate detail page');
            if (host.querySelector('.o_baseer_pl_table:not(.o_baseer_go_events)')) {
                throw new Error('Summary table still visible on detail page');
            }
            host.querySelector('.o_baseer_go_back').click();
            const last = await waitFor(() => host.querySelector('.o_baseer_pl_net_income'), 'returned summary');
            const filler = document.createElement('tr');
            filler.innerHTML = '<td colspan="2" style="height:1600px">Scroll fixture</td>';
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
            app.destroy();
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

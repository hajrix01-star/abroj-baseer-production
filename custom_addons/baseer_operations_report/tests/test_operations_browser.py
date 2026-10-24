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
            const openingStarted = performance.now();
            operations.click();
            await waitFor(() => host.querySelector('.o_baseer_go_report'), 'operations mounted through selector');
            if (host.querySelector('.o_baseer_vat_report')) { throw new Error('Previous VAT report remained visible'); }
            await waitFor(() => host.querySelector('.o_baseer_go_report .o_baseer_owner_difference'), 'owner summary preview');
            console.log('BASEER_METRIC owner_open_ms=' + Math.round(performance.now() - openingStarted));
            await document.fonts.load('12px "IBM Plex Sans Arabic"', 'ملخص المبيعات 123');
            await document.fonts.load('700 12px "IBM Plex Sans Arabic"', 'الإجمالي 123');
            if (!document.fonts.check('12px "IBM Plex Sans Arabic"', 'ملخص المبيعات 123') ||
                !getComputedStyle(hub).fontFamily.includes('IBM Plex Sans Arabic')) {
                throw new Error('Central professional report font did not load');
            }
            const exportButtons = [...host.querySelectorAll('.o_baseer_report_exports button')];
            if (exportButtons.length !== 2 || exportButtons.some(button => button.disabled)) {
                throw new Error('Unified Excel/PDF controls are unavailable for the loaded report');
            }
            const ownerTable = () => host.querySelector('.o_baseer_pl_table.o_baseer_owner_table');
            if (!ownerTable()) { throw new Error('Owner P&L table was not rendered'); }
            // Regression: percentages must share the amount's line at both
            // native test widths, not make every payment-channel row taller.
            const percentage = ownerTable().querySelector('.o_baseer_owner_percentage');
            if (!percentage) { throw new Error('Fixture payment-channel percentage missing'); }
            const amount = percentage.parentElement.querySelector('strong');
            const amountBox = amount.getBoundingClientRect();
            const percentageBox = percentage.getBoundingClientRect();
            if (Math.min(amountBox.bottom, percentageBox.bottom) <= Math.max(amountBox.top, percentageBox.top)) {
                throw new Error('Percentage added a second line to the owner row');
            }
            const rtl = getComputedStyle(host.querySelector('.o_baseer_go_report')).direction === 'rtl';
            if (rtl ? percentageBox.left < amountBox.right - 1 : percentageBox.right > amountBox.left + 1) {
                throw new Error('Percentage must precede the amount in the report reading direction');
            }
            if (getComputedStyle(host.querySelector('.o_baseer_owner_summary')).display !== 'block') {
                throw new Error('Owner paper retained the extra grid spacing');
            }
            if (ownerTable().scrollWidth > ownerTable().clientWidth + 1) {
                throw new Error('Compact owner table overflowed its viewport');
            }
            // Compare the rendered theme with the unchanged shared P&L styles.
            // No financial fixture or RPC is needed for this visual contract.
            const reference = document.createElement('div');
            reference.className = 'o_baseer_pl_report';
            reference.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none';
            reference.innerHTML = '<section class="o_baseer_report o_baseer_pl_paper">' +
                '<header class="o_baseer_report_head"><h1 class="o_baseer_report_title">Reference</h1></header>' +
                '<table class="o_baseer_pl_table"><tbody>' +
                '<tr class="o_baseer_pl_section"><th>Section</th><td><strong>100.00</strong></td></tr>' +
                '<tr class="o_baseer_pl_channel"><th>Channel</th><td><span>100.00</span></td></tr>' +
                '</tbody></table></section>';
            host.appendChild(reference);
            try {
                const paper = host.querySelector('.o_baseer_owner_summary');
                const sameStyle = (actual, expected, properties) => {
                    const actualStyle = getComputedStyle(actual), expectedStyle = getComputedStyle(expected);
                    for (const property of properties) {
                        if (actualStyle[property] !== expectedStyle[property]) {
                            throw new Error('Owner/P&L theme mismatch: ' + property);
                        }
                    }
                };
                sameStyle(paper.querySelector('h1'), reference.querySelector('h1'), ['fontSize', 'fontWeight', 'color']);
                const section = ownerTable().querySelector('.o_baseer_owner_section');
                sameStyle(section, reference.querySelector('.o_baseer_pl_section'), ['backgroundColor']);
                sameStyle(section.querySelector('[data-owner-row]'), reference.querySelector('th'), ['color', 'fontWeight']);
                sameStyle(section.querySelector('td strong'), reference.querySelector('td strong'), ['color', 'fontWeight']);
                sameStyle(amount, reference.querySelector('.o_baseer_pl_channel td span'), ['color', 'fontWeight']);
                sameStyle(section.querySelector('td'), reference.querySelector('td'), ['paddingTop', 'paddingBottom']);
                const basis = paper.querySelector('.o_baseer_owner_basis');
                if (!basis.textContent.trim() || basis.getBoundingClientRect().top < ownerTable().getBoundingClientRect().bottom) {
                    throw new Error('Accounting basis must remain visible below the table');
                }
                const caption = paper.querySelector('.o_baseer_report_period').textContent;
                const currentPeriod = ownerTable().querySelector('thead .is-number span').textContent;
                if (!caption.includes(currentPeriod)) { throw new Error('Header period missing'); }
                const amountButton = amount.closest('button');
                amountButton.focus();
                if (document.activeElement !== amountButton || getComputedStyle(amountButton).outlineStyle === 'none') {
                    throw new Error('Themed amount lost visible keyboard focus');
                }
            } finally { reference.remove(); }
            const salesToggle = ownerTable().querySelector('.o_baseer_owner_section .o_baseer_pl_toggle');
            if (!salesToggle || salesToggle.tagName !== 'BUTTON') { throw new Error('Sales fold is not keyboard accessible'); }
            salesToggle.focus();
            if (document.activeElement !== salesToggle || salesToggle.getAttribute('aria-expanded') !== 'true') {
                throw new Error('Sales fold did not expose its initial expanded state');
            }
            salesToggle.click();
            await waitFor(() => salesToggle.getAttribute('aria-expanded') === 'false', 'collapsed sales fold');
            salesToggle.click();
            await waitFor(() => salesToggle.getAttribute('aria-expanded') === 'true', 'expanded sales fold');
            const linkSpecs = [...ownerTable().querySelectorAll('[data-owner-row]')].map(button => ({
                row: button.dataset.ownerRow, period: button.dataset.ownerPeriod,
            }));
            if (linkSpecs.length < 8) { throw new Error('Some summary rows or amounts are not linked'); }
            for (const spec of linkSpecs) {
                const link = [...ownerTable().querySelectorAll('[data-owner-row]')].find(button =>
                    button.dataset.ownerRow === spec.row && button.dataset.ownerPeriod === spec.period);
                link.focus();
                if (document.activeElement !== link) { throw new Error('Detail link is not keyboard accessible'); }
                const detailStarted = performance.now();
                link.click();
                const details = await waitFor(() => host.querySelector('.o_baseer_owner_detail_page'), 'detail page');
                await waitFor(() => details.querySelector('.o_baseer_owner_detail_total'), 'real detail RPC');
                console.log('BASEER_METRIC owner_detail_ms=' + Math.round(performance.now() - detailStarted));
                if (details.querySelector('.alert-danger, .o_baseer_owner_refresh')) { throw new Error('Detail request failed'); }
                if (details.scrollWidth > details.clientWidth + 1) { throw new Error('Details overflowed viewport'); }
                if (spec.row === 'total:cash_total') {
                    if (details.querySelector('.o_baseer_owner_events')) { throw new Error('Zero cash has false events'); }
                } else {
                    const documentLink = details.querySelector('.o_baseer_owner_source');
                    if (!documentLink || !documentLink.textContent.trim()) { throw new Error('Source document link missing'); }
                    if (spec.row === 'total:incoming_total' && spec.period === 'current') {
                        documentLink.click();
                        const dialog = await waitFor(() => document.querySelector('.modal .o_form_view'), 'source form action');
                        if (!dialog.textContent.includes('__INVOICE_NAME__')) { throw new Error('Wrong source document opened'); }
                        const close = dialog.closest('.modal').querySelector('.btn-close');
                        if (!close) { throw new Error('Source dialog close missing'); }
                        close.click();
                        await waitFor(() => !document.querySelector('.modal .o_form_view'), 'source dialog closed');
                    }
                }
                details.querySelector('.o_baseer_owner_back').click();
                await waitFor(() => ownerTable(), 'summary restored');
            }
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
            await waitFor(() => ownerTable().querySelectorAll('thead .is-number').length === 4, 'comparison columns');
            comparison.click();
            const none = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_comparison_menu .dropdown-item')].find(
                (item) => /No comparison|دون مقارنة/.test(item.textContent)), 'no comparison');
            none.click();
            await waitFor(() => ownerTable().querySelectorAll('thead .is-number').length === 2, 'single period column');

            const currentMonth = periodButton().textContent;
            periodButton().click();
            const previousMonth = await waitFor(() => [...document.querySelectorAll('.o_baseer_pl_period_menu .o_baseer_pl_menu_row')].find(
                (row) => /Month|شهر/.test(row.textContent)), 'month navigation');
            previousMonth.querySelector('.o_baseer_pl_row_navigation button').click();
            await waitFor(() => host.querySelector('.o_baseer_go_incomplete'), 'unproven prior month');
            if ([...host.querySelectorAll('.o_baseer_report_exports button')].some(button => !button.disabled)) {
                throw new Error('Incomplete source exposed active export controls');
            }
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
            if (!ownerTable() || host.querySelector('.o_baseer_go_detail_page')) {
                throw new Error('Owner P&L table or its local-only hierarchy was lost');
            }
            if (window.innerWidth <= 400 && ownerTable().scrollWidth > ownerTable().clientWidth + 1) {
                throw new Error('Owner P&L table overflowed the narrow viewport');
            }
            const filler = document.createElement('div');
            filler.style.height = '1600px';
            filler.textContent = 'Scroll fixture';
            ownerTable().closest('.o_baseer_pl_table_wrap').before(filler);
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
        """.replace('__JOURNAL_ID__', str(journal.id)).replace('__ACCOUNT_CODE__', account.code).replace('__INVOICE_NAME__', invoice.name)
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

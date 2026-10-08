from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged

from ..models.tax_report_wizard import BaseerTaxReportWizard, _previous_quarter


@tagged('post_install', '-at_install')
class TestSaudiVatReport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.account_fiscal_country_id = self.env.ref('base.sa')
        self.wizard = self.env['baseer.tax.report.wizard'].create({
            'company_id': self.company.id, 'year': 2026, 'month': '9', 'quarter': '3',
        })

    def _copy_sa_tax(self, source, values):
        """Keep synthetic tax lines in the report's Saudi fiscal country."""
        sa = self.env.ref('base.sa')
        group = self.env['account.tax.group'].with_company(self.company).create({
            'name': 'Saudi VAT report test group',
            'company_id': self.company.id,
            'country_id': sa.id,
        })
        return source.copy({**values, 'tax_group_id': group.id, 'country_id': sa.id})

    def test_month_and_quarter_ranges(self):
        self.assertEqual(self.wizard.display_mode, 'simple')
        self.assertEqual(self.wizard.period_type, 'quarter')
        self.wizard.period_type = 'month'
        self.assertEqual(self.wizard._period_dates(), (date(2026, 9, 1), date(2026, 9, 30)))
        self.wizard.write({'period_type': 'quarter', 'quarter': '3'})
        self.assertEqual(self.wizard._period_dates(), (date(2026, 7, 1), date(2026, 9, 30)))
        self.wizard.write({'year': 2024, 'quarter': '1'})
        self.assertEqual(self.wizard._period_dates(), (date(2024, 1, 1), date(2024, 3, 31)))
        self.wizard.write({'year': 1999})
        with self.assertRaises(ValidationError):
            self.wizard._period_dates()

    def test_previous_completed_quarter_defaults_cross_year_boundary(self):
        for today, expected in (
            (date(2027, 1, 1), (2026, '4')),
            (date(2027, 4, 1), (2027, '1')),
            (date(2027, 7, 1), (2027, '2')),
            (date(2027, 10, 1), (2027, '3')),
        ):
            self.assertEqual(_previous_quarter(today), expected)
            with patch.object(fields.Date, 'context_today', return_value=today):
                defaults = self.env['baseer.tax.report.wizard'].default_get(
                    ['period_type', 'year', 'quarter'])
            self.assertEqual((defaults['period_type'], defaults['year'], defaults['quarter']),
                             ('quarter', *expected))

    def test_official_aggregation_and_tag_signs(self):
        balances = {
            '-1(B)': Decimal('53137.05'), '-1(T)': Decimal('7970.55'),
            '7(B)': Decimal('14136.41'), '7(T)': Decimal('2120.45'),
            '14(T)': Decimal('-10.00'), '15(T)': Decimal('-5.00'),
        }
        with patch.object(BaseerTaxReportWizard, '_base_domain', return_value=Domain.TRUE), \
                patch.object(BaseerTaxReportWizard, '_tax_tag_expression',
                             side_effect=lambda expression, domain: balances.get(expression.formula, Decimal('0'))), \
                patch.object(BaseerTaxReportWizard, '_untagged_vat',
                             return_value={'count': 0, 'amount': Decimal('0'), 'domain': Domain.FALSE,
                                           'other_count': 0, 'other_amount': Decimal('0'),
                                           'other_domain': Domain.FALSE}):
            rows = {row['number']: row for row in self.wizard._build_report()['rows']}
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows['6']['base'], Decimal('53137.05'))
        self.assertEqual(rows['6']['tax'], Decimal('7970.55'))
        self.assertEqual(rows['12']['base'], Decimal('14136.41'))
        self.assertEqual(rows['12']['tax'], Decimal('2120.45'))
        self.assertEqual(rows['13']['tax'], Decimal('5850.10'))
        self.assertEqual(rows['16']['tax'], Decimal('5835.10'))
        self.assertEqual(rows['16']['base_text'], '—')

    def test_simple_hides_zero_boxes_and_aggregates_reveal_signed_components(self):
        balances = {
            '-1(B)': Decimal('100'), '-1(T)': Decimal('15'),
            '7(B)': Decimal('40'), '7(T)': Decimal('6'),
        }
        exception = {'count': 0, 'amount': Decimal('0'), 'domain': Domain.FALSE,
                     'other_count': 0, 'other_amount': Decimal('0'),
                     'other_domain': Domain.FALSE}
        with patch.object(BaseerTaxReportWizard, '_base_domain', return_value=Domain.TRUE), \
                patch.object(BaseerTaxReportWizard, '_tax_tag_expression',
                             side_effect=lambda expression, domain: balances.get(expression.formula, Decimal('0'))), \
                patch.object(BaseerTaxReportWizard, '_untagged_vat', return_value=exception):
            simple = self.wizard._build_report()
            self.assertEqual([row['number'] for row in simple['visible_rows']],
                             ['1', '6', '7', '12', '13', '16'])
            box_13 = next(row for row in simple['rows'] if row['number'] == '13')
            self.assertEqual([(item['number'], item['amount_text']) for item in box_13['components']['tax']],
                             [('1', '+15.00'), ('7', '-6.00')])
            self.wizard.display_mode = 'detailed'
            detailed = self.wizard._build_report()
        self.assertEqual(len(detailed['visible_rows']), 16)
        self.assertEqual(detailed['rows'][-1]['tax'], simple['rows'][-1]['tax'])

    def test_aggregation_rejects_unexpected_formula(self):
        expression = type('Expression', (), {'formula': 'sa_1.tax;drop'})()
        with self.assertRaises(Exception):
            self.wizard._aggregation_expression(expression, {'sa_1.tax': Decimal('1')})

    def test_posted_sale_refund_purchase_and_draft_tags(self):
        """Exercise the real tagged journal lines and native posted/exigibility domain."""
        self.wizard.write({'year': 2034, 'month': '9'})
        account = self.env['account.account'].with_company(self.company)
        income = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'income')], limit=1)
        expense = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'expense')], limit=1)
        clearing = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'asset_current')], limit=1)
        journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(income and expense and clearing and journal)
        tags = self.env['account.account.tag']
        sa = self.env.ref('base.sa')
        tag = {name: tags._get_tax_tags(name, sa.id) for name in ('1(B)', '1(T)', '7(B)', '7(T)')}
        self.assertTrue(all(tag.values()))

        def entry(label, base, vat, source_account, base_tag, tax_tag, posted=True):
            # A real balanced entry; negative values model a credit note/refund.
            amount = base + vat
            move = self.env['account.move'].with_company(self.company).create({
                'date': date(2034, 9, 15), 'journal_id': journal.id,
                'ref': label, 'move_type': 'entry',
                'line_ids': [
                    Command.create({
                        'name': label + ' base', 'account_id': source_account.id,
                        'debit': max(base, 0), 'credit': max(-base, 0),
                        'tax_tag_ids': [Command.set(tag[base_tag].ids)],
                    }),
                    Command.create({
                        'name': label + ' VAT', 'account_id': source_account.id,
                        'debit': max(vat, 0), 'credit': max(-vat, 0),
                        'tax_tag_ids': [Command.set(tag[tax_tag].ids)],
                    }),
                    Command.create({
                        'name': label + ' counterpart', 'account_id': clearing.id,
                        'debit': max(-amount, 0), 'credit': max(amount, 0),
                    }),
                ],
            })
            if posted:
                move._post(soft=False)
            return move

        entry('sale', -100, -15, income, '1(B)', '1(T)')
        entry('refund', 20, 3, income, '1(B)', '1(T)')
        entry('purchase', 40, 6, expense, '7(B)', '7(T)')
        entry('draft ignored', -1000, -150, income, '1(B)', '1(T)', posted=False)
        rows = {row['number']: row for row in self.wizard._build_report()['rows']}
        self.assertEqual(rows['1']['base'], Decimal('80.00'))
        self.assertEqual(rows['1']['tax'], Decimal('12.00'))
        self.assertEqual(rows['7']['base'], Decimal('40.00'))
        self.assertEqual(rows['7']['tax'], Decimal('6.00'))
        self.assertEqual(rows['16']['tax'], Decimal('6.00'))
        action = self.wizard.action_open_cell('1', 'tax')
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertEqual(action['views'], [(False, 'list'), (False, 'form')])
        self.assertEqual(len(self.env['account.move.line'].search(action['domain'])), 2)
        with self.assertRaises(ValidationError):
            self.wizard.action_open_cell('6', 'tax')
        with self.assertRaises(ValidationError):
            self.wizard.action_open_cell('99', 'tax')
        other_journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('id', '!=', journal.id),
        ], limit=1)
        self.assertTrue(other_journal)
        self.wizard.journal_ids = other_journal
        filtered = {row['number']: row for row in self.wizard._build_report()['rows']}
        self.assertEqual(filtered['1']['tax'], Decimal('0.00'))
        self.assertTrue(self.wizard._build_report()['journal_names'])

    def test_cash_basis_is_excluded_until_reconciliation(self):
        """An unpaid CABA tax must not appear before Odoo creates its cash-basis entry."""
        self.wizard.write({'year': 2033, 'month': '9'})
        account = self.env['account.account'].with_company(self.company)
        income = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'income')], limit=1)
        receivable = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'asset_receivable')], limit=1)
        cash = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'asset_cash')], limit=1)
        journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        standard_tax = self.env['account.tax'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type_tax_use', '=', 'sale'),
            ('amount', '=', 15), ('tax_exigibility', '=', 'on_invoice'),
        ], limit=1)
        self.assertTrue(income and receivable and cash and journal and standard_tax)
        waiting = account.create({
            'name': 'VAT cash-basis waiting test', 'code': 'BVATWAIT33',
            'account_type': 'liability_current', 'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        base_account = account.create({
            'name': 'VAT cash-basis base test', 'code': 'BVATBASE33',
            'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.company.write({'tax_exigibility': True, 'account_cash_basis_base_account_id': base_account.id})
        tax = self._copy_sa_tax(standard_tax, {
            'name': 'VAT cash-basis report test', 'tax_exigibility': 'on_payment',
            'cash_basis_transition_account_id': waiting.id,
        })
        tax_line = tax.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == 'tax')[:1]
        self.assertTrue(tax_line)
        tags = self.env['account.account.tag']
        base_tag = tags._get_tax_tags('1(B)', self.env.ref('base.sa').id)
        tax_tag = tags._get_tax_tags('1(T)', self.env.ref('base.sa').id)
        tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'base',
        ).write({'tag_ids': [Command.set(base_tag.ids)]})
        tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).write({'tag_ids': [Command.set(tax_tag.ids)]})
        invoice = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry', 'date': date(2033, 9, 15), 'journal_id': journal.id,
            'line_ids': [
                Command.create({'name': 'CABA sale', 'account_id': income.id, 'credit': 100,
                                'tax_ids': [Command.set(tax.ids)],
                                'tax_tag_ids': [Command.set(base_tag.ids)]}),
                Command.create({'name': 'CABA VAT', 'account_id': waiting.id, 'credit': 15,
                                'tax_repartition_line_id': tax_line.id,
                                'tax_tag_ids': [Command.set(tax_tag.ids)]}),
                Command.create({'name': 'CABA receivable', 'account_id': receivable.id, 'debit': 115}),
            ],
        })
        invoice._post(soft=False)
        self.assertFalse(invoice.always_tax_exigible)
        before = {row['number']: row for row in self.wizard._build_report()['rows']}
        self.assertEqual(before['1']['base'], Decimal('0.00'))
        self.assertEqual(before['1']['tax'], Decimal('0.00'))
        payment = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry', 'date': date(2033, 9, 15), 'journal_id': journal.id,
            'line_ids': [
                Command.create({'name': 'CABA cash', 'account_id': cash.id, 'debit': 115}),
                Command.create({'name': 'CABA payment', 'account_id': receivable.id, 'credit': 115}),
            ],
        })
        payment._post(soft=False)
        (invoice.line_ids + payment.line_ids).filtered(lambda line: line.account_id == receivable).reconcile()
        caba = self.env['account.move'].search([('tax_cash_basis_rec_id', '!=', False),
                                                 ('date', '=', date(2033, 9, 15)),
                                                 ('company_id', '=', self.company.id)])
        self.assertTrue(caba)
        after = {row['number']: row for row in self.wizard._build_report()['rows']}
        self.assertEqual(after['1']['base'], Decimal('100.00'))
        self.assertEqual(after['1']['tax'], Decimal('15.00'))

    def test_untagged_vat_is_visible_but_not_in_official_boxes(self):
        self.wizard.write({'year': 2035, 'month': '9'})
        account = self.env['account.account'].with_company(self.company)
        income = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'income')], limit=1)
        clearing = account.search([('company_ids', 'in', self.company.id), ('account_type', '=', 'asset_current')], limit=1)
        journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        standard_tax = self.env['account.tax'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type_tax_use', '=', 'sale'),
            ('amount', '=', 15), ('tax_exigibility', '=', 'on_invoice'),
        ], limit=1)
        self.assertTrue(income and clearing and journal and standard_tax)
        tax = self._copy_sa_tax(standard_tax, {'name': 'Untagged VAT report test'})
        (tax.invoice_repartition_line_ids + tax.refund_repartition_line_ids).write({
            'tag_ids': [Command.clear()],
        })
        tax_line = tax.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == 'tax')[:1]
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry', 'date': date(2035, 9, 15), 'journal_id': journal.id,
            'line_ids': [
                Command.create({'name': 'Untagged VAT', 'account_id': income.id,
                                'credit': 15, 'tax_repartition_line_id': tax_line.id}),
                Command.create({'name': 'Counterpart', 'account_id': clearing.id, 'debit': 15}),
            ],
        })
        move._post(soft=False)
        data = self.wizard._build_report()
        self.assertEqual(data['exception']['count'], 1)
        self.assertEqual(data['exception']['amount'], Decimal('-15.0'))
        self.assertEqual(data['rows'][0]['tax'], Decimal('0.00'))

    def test_report_paper_and_preview(self):
        paper = self.env.ref('baseer_tax_report.paperformat_tax')
        self.assertEqual((paper.format, paper.orientation), ('A4', 'Portrait'))
        view = self.env.ref('baseer_tax_report.view_tax_report_wizard_form')
        arch = etree.fromstring(view.arch_db.encode())
        self.assertTrue(arch.xpath("//field[@name='preview_html'][@widget='baseer_tax_preview']"))
        self.assertTrue(arch.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' btr-report-preview ')]/field[@name='preview_html']"))
        self.assertTrue(arch.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' btr-review-actions ')]/button[@name='action_view_untagged']"))
        widget_template = etree.parse(str(Path(__file__).resolve().parents[1] / 'static/src/xml/tax_preview_field.xml'))
        self.assertTrue(widget_template.xpath("//t[@t-name='baseer_tax_report.TaxPreviewField']//div[@t-on-click='onPreviewClick'][contains(concat(' ', normalize-space(@class), ' '), ' w-100 ')]"))
        self.assertTrue(arch.xpath("//field[@name='display_mode']"))
        self.assertFalse(arch.xpath("//button[@name='action_view_entries']"))
        self.assertTrue(arch.xpath("//button[@name='action_view_untagged']"))
        for action in (self.wizard.action_view_untagged(), self.wizard.action_view_other_untagged()):
            self.assertEqual(action['views'], [(False, 'list'), (False, 'form')])
        self.wizard.display_mode = 'detailed'
        self.assertIn('data-id="1:base"', self.wizard.preview_html)
        self.assertIn('btr-row-link', self.wizard.preview_html)
        self.assertIn('btr-row-actions', self.wizard.preview_html)
        self.assertIn('btr-expand', self.wizard.preview_html)
        self.assertIn('btr-report-card', self.wizard.preview_html)
        report_template = etree.parse(str(Path(__file__).resolve().parents[1] / 'report/tax_report.xml'))
        self.assertTrue(report_template.xpath("//a[contains(concat(' ', normalize-space(@class), ' '), ' btr-help ')][@title][@aria-label]"))
        print_values = self.env['report.baseer_tax_report.report_tax']._get_report_values(self.wizard.ids)
        self.assertEqual(len(print_values['report_data']['visible_rows']), 16)
        self.assertFalse(print_values['report_data']['interactive'])

    def test_shared_preview_shell_and_amount_states(self):
        data = self.wizard.with_context(lang='ar_001')._build_report()
        data['interactive'] = True
        data['visible_rows'] = data['rows'][:4]
        samples = (
            (Decimal('15.00'), Decimal('0.00'), '15.00', '0.00'),
            (Decimal('0.00'), Decimal('-2.50'), '0.00', '-2.50'),
            (Decimal('-3.00'), None, '-3.00', '—'),
            (None, Decimal('4.00'), '—', '4.00'),
        )
        for row, (base, tax, base_text, tax_text) in zip(data['visible_rows'], samples):
            row.update(base=base, tax=tax, base_text=base_text, tax_text=tax_text)
        preview = self.env['ir.qweb']._render(
            'baseer_tax_report.preview_tax_report', {'report_data': data})
        html = etree.HTML(preview)
        self.assertTrue(html.xpath("//div[contains(@class, 'o_baseer_report')][@dir='rtl']"))
        rows = html.xpath("//table[contains(@class, 'btr-table')]/tbody/tr[contains(@class, 'btr-row') and not(contains(@class, 'btr-row-actions'))]")
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [[cell.get('class', ''), ''.join(cell.itertext()).strip()] for row in rows for cell in row.xpath('./td')[1:]],
            [
                ['btr-money text-end', '15.00'], ['btr-money text-end is-zero', '0.00'],
                ['btr-money text-end is-zero', '0.00'], ['btr-money text-end is-negative', '-2.50'],
                ['btr-money text-end is-negative', '-3.00'], ['btr-money text-end', '—'],
                ['btr-money text-end', '—'], ['btr-money text-end', '4.00'],
            ],
        )

    def test_exception_help_is_compact_in_preview_and_explicit_in_pdf(self):
        data = self.wizard.with_context(lang='ar_001')._build_report()
        data['exception']['count'] = 3
        data['exception']['other_count'] = 2
        data['interactive'] = True
        preview = self.env['ir.qweb']._render(
            'baseer_tax_report.preview_tax_report', {'report_data': data})
        self.assertIn('قيود ضريبة القيمة المضافة غير المصنفة', preview)
        self.assertIn('قيود ضرائب أخرى غير مصنفة', preview)
        self.assertIn('class="btr-help', preview)
        self.assertIn('title="هذه القيود لا تدخل', preview)
        self.assertNotIn('Review required', preview)
        data['interactive'] = False
        printed = self.env['ir.qweb']._render(
            'baseer_tax_report.tax_table', {'report_data': data})
        self.assertNotIn('class="btr-help', printed)
        self.assertIn('راجع وسومها الضريبية قبل اعتماد التقرير', printed)

    def test_arabic_box_labels_do_not_change_the_original_formulas(self):
        arabic = self.wizard.with_context(lang='ar_001')._build_report()
        self.assertTrue(arabic['is_rtl'])
        self.assertEqual(arabic['rows'][0]['name'], 'المبيعات الخاضعة للنسبة الأساسية')
        self.assertEqual(arabic['rows'][-1]['name'], 'صافي ضريبة القيمة المضافة المستحقة أو القابلة للاسترداد')
        english = self.wizard.with_context(lang='en_US')._build_report()
        self.assertEqual(english['rows'][0]['name'], '1. Standard rated sales')

    def test_company_scope_and_accounting_access(self):
        other = self.env['res.company'].create({
            'name': 'Other VAT report company', 'country_id': self.env.ref('base.sa').id,
            'account_fiscal_country_id': self.env.ref('base.sa').id,
        })
        groups = self.env.ref('base.group_user') | self.env.ref('account.group_account_readonly')
        user = self.env['res.users'].create({
            'name': 'VAT report scoped reader', 'login': 'vat-report-scoped-reader',
            'group_ids': [Command.set(groups.ids)],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
        })
        allowed = self.wizard.with_user(user).with_context(allowed_company_ids=[self.company.id])
        allowed._check_report_access()
        foreign = self.env['baseer.tax.report.wizard'].with_company(other).create({
            'company_id': other.id, 'year': 2026, 'month': '9',
        })
        with self.assertRaises(AccessError):
            foreign.with_user(user).with_context(allowed_company_ids=[self.company.id])._check_report_access()

    def _hub_options(self, **changes):
        return {
            'company_id': self.company.id, 'period_type': 'quarter',
            'year': 2026, 'month': '9', 'quarter': '3',
            'display_mode': 'simple', 'journal_ids': [],
            **changes,
        }

    def test_hub_report_is_primitive_and_matches_existing_calculator(self):
        model = self.env['baseer.tax.report.wizard']
        options = model.get_hub_options()
        self.assertIn(self.company.id, [company['id'] for company in options['companies']])
        self.assertTrue(all(journal['company_id'] in self.env.companies.ids
                            for journal in options['journals']))
        report = model.get_hub_report(self._hub_options(display_mode='detailed'))
        original = self.wizard._build_report()
        self.assertEqual((report['date_from'], report['date_to']), ('2026-07-01', '2026-09-30'))
        self.assertEqual(report['period_type'], 'quarter')
        self.assertEqual(len(report['rows']), 16)
        self.assertEqual(report['rows'][0]['base_text'], original['rows'][0]['base_text'])
        self.assertEqual(report['rows'][-1]['tax_text'], original['rows'][-1]['tax_text'])
        self.assertEqual(report['exception']['count'], original['exception']['count'])
        self.assertEqual(report['exception']['other_count'], original['exception']['other_count'])
        self.assertIsInstance(report['rows'][0]['components'], dict)

    def test_hub_options_do_not_replace_non_saudi_active_company(self):
        non_saudi = self.env['res.company'].create({
            'name': 'VAT non-Saudi active company',
            'country_id': self.env.ref('base.us').id,
            'account_fiscal_country_id': self.env.ref('base.us').id,
        })
        options = self.env['baseer.tax.report.wizard'].with_context(
            allowed_company_ids=[non_saudi.id, self.company.id],
        ).get_hub_options()
        self.assertFalse(options['default_company_id'])
        self.assertIn(self.company.id, [company['id'] for company in options['companies']])
        self.assertNotIn('domain', str(report))

    def test_hub_options_are_validated_before_read_or_print(self):
        model = self.env['baseer.tax.report.wizard']
        bad_options = (
            (self._hub_options(year=True), AccessError),
            (self._hub_options(year=1999), AccessError),
            (self._hub_options(period_type='year'), ValidationError),
            (self._hub_options(month='13'), ValidationError),
            (self._hub_options(quarter='5'), ValidationError),
            (self._hub_options(journal_ids=['1']), ValidationError),
            (self._hub_options(journal_ids=[1] * 101), ValidationError),
            (self._hub_options(company_id=999999999), AccessError),
            ({**self._hub_options(), 'unexpected': 1}, ValidationError),
        )
        for options, exception in bad_options:
            with self.subTest(options=options), self.assertRaises(exception):
                model.get_hub_report(options)
        with self.assertRaises(ValidationError):
            model.open_hub_cell(self._hub_options(), '99', 'tax')
        with self.assertRaises(ValidationError):
            model.open_hub_exception(self._hub_options(), 'invented')

    def test_hub_pdf_and_drilldown_use_existing_actions(self):
        model = self.env['baseer.tax.report.wizard']
        options = self._hub_options()
        direct = model.open_hub_cell(options, '1', 'tax')
        self.assertEqual(direct['res_model'], 'account.move.line')
        self.assertEqual(direct['context']['allowed_company_ids'], [self.company.id])
        exception = model.open_hub_exception(options, 'vat')
        self.assertEqual(exception['res_model'], 'account.move.line')
        self.assertEqual(exception['context']['allowed_company_ids'], [self.company.id])
        before = model.search_count([])
        # Odoo redirects an admin without a configured external layout to its
        # layout setup window. Bypass only that standard prompt for this action test.
        pdf = model.with_context(discard_logo_check=True).print_hub_report(options)
        self.assertEqual(pdf['type'], 'ir.actions.report')
        self.assertEqual(pdf['report_name'], 'baseer_tax_report.report_tax')
        self.assertEqual(model.search_count([]), before + 1)

    def test_hub_rejects_unauthorized_company_and_journal(self):
        model = self.env['baseer.tax.report.wizard']
        other = self.env['res.company'].create({
            'name': 'Other VAT hub company', 'country_id': self.env.ref('base.sa').id,
            'account_fiscal_country_id': self.env.ref('base.sa').id,
        })
        journal = self.env['account.journal'].with_company(other).search([
            ('company_id', '=', other.id),
        ], limit=1)
        if journal:
            with self.assertRaises(AccessError):
                model.get_hub_report(self._hub_options(journal_ids=[journal.id]))
        groups = self.env.ref('base.group_user') | self.env.ref('account.group_account_readonly')
        user = self.env['res.users'].create({
            'name': 'VAT hub scoped reader', 'login': 'vat-hub-scoped-reader',
            'group_ids': [Command.set(groups.ids)],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
        })
        restricted = model.with_user(user).with_context(allowed_company_ids=[self.company.id])
        with self.assertRaises(AccessError):
            restricted.get_hub_report(self._hub_options(company_id=other.id))

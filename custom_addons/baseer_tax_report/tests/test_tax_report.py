from datetime import date
from decimal import Decimal
from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged

from ..models.tax_report_wizard import BaseerTaxReportWizard


@tagged('post_install', '-at_install')
class TestSaudiVatReport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.account_fiscal_country_id = self.env.ref('base.sa')
        self.wizard = self.env['baseer.tax.report.wizard'].create({
            'company_id': self.company.id, 'year': 2026, 'month': '9', 'quarter': '3',
        })

    def test_month_and_quarter_ranges(self):
        self.assertEqual(self.wizard._period_dates(), (date(2026, 9, 1), date(2026, 9, 30)))
        self.wizard.write({'period_type': 'quarter', 'quarter': '3'})
        self.assertEqual(self.wizard._period_dates(), (date(2026, 7, 1), date(2026, 9, 30)))
        self.wizard.write({'year': 2024, 'quarter': '1'})
        self.assertEqual(self.wizard._period_dates(), (date(2024, 1, 1), date(2024, 3, 31)))
        self.wizard.write({'year': 1999})
        with self.assertRaises(ValidationError):
            self.wizard._period_dates()

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
        tax = standard_tax.copy({
            'name': 'VAT cash-basis report test', 'tax_exigibility': 'on_payment',
            'cash_basis_transition_account_id': waiting.id,
        })
        tax_line = tax.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == 'tax')[:1]
        self.assertTrue(tax_line)
        tags = self.env['account.account.tag']
        base_tag = tags._get_tax_tags('1(B)', self.env.ref('base.sa').id)
        tax_tag = tags._get_tax_tags('1(T)', self.env.ref('base.sa').id)
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
        tax = standard_tax.copy({'name': 'Untagged VAT report test'})
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
        self.assertTrue(arch.xpath("//field[@name='preview_html']"))
        self.assertTrue(arch.xpath("//button[@name='action_view_entries']"))
        self.assertTrue(arch.xpath("//button[@name='action_view_untagged']"))

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

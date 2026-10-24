from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestVatDrillSelectors(TransactionCase):
    def _nonzero_reader_fixture(self):
        company = self.env.company
        country = self.env.ref('base.sa')
        company.account_fiscal_country_id = country
        accounts = self.env['account.account'].with_company(company)
        income = accounts.search([
            ('company_ids', 'in', company.id), ('account_type', '=', 'income'),
        ], limit=1)
        clearing = accounts.search([
            ('company_ids', 'in', company.id), ('account_type', '=', 'asset_current'),
        ], limit=1)
        self.assertTrue(income and clearing)
        journal = self.env['account.journal'].create({
            'name': 'VAT drill synthetic journal', 'code': 'VDR',
            'type': 'general', 'company_id': company.id,
        })
        tags = self.env['account.account.tag']
        base_tags = tags._get_tax_tags('1(B)', country.id)
        tax_tags = tags._get_tax_tags('1(T)', country.id)
        self.assertTrue(base_tags and tax_tags)
        move = self.env['account.move'].with_company(company).create({
            'date': date(2098, 10, 15), 'journal_id': journal.id,
            'ref': 'Synthetic VAT drill sale', 'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'VAT drill base', 'account_id': income.id,
                                'credit': 100, 'tax_tag_ids': [Command.set(base_tags.ids)]}),
                Command.create({'name': 'VAT drill tax', 'account_id': income.id,
                                'credit': 15, 'tax_tag_ids': [Command.set(tax_tags.ids)]}),
                Command.create({'name': 'VAT drill counterpart', 'account_id': clearing.id, 'debit': 115}),
            ],
        })
        move._post(soft=False)
        groups = self.env.ref('base.group_user') | self.env.ref('account.group_account_readonly')
        reader = self.env['res.users'].create({
            'name': 'VAT drill readonly reader', 'login': 'vat_drill_readonly_reader',
            'group_ids': [Command.set(groups.ids)], 'company_id': company.id,
            'company_ids': [Command.set(company.ids)], 'lang': 'en_US',
        })
        engine = self.env['baseer.report.drill'].with_user(reader).sudo(False).with_context(
            allowed_company_ids=company.ids, lang='en_US',
        )
        filters = {'company_id': company.id, 'period_type': 'quarter', 'year': 2098,
                   'month': '10', 'quarter': '4', 'display_mode': 'detailed', 'journal_ids': [journal.id]}
        return engine, filters, move, income, journal

    def test_actual_nonzero_direct_cells_and_source_roundtrip_for_reader(self):
        engine, filters, move, _income, _journal = self._nonzero_reader_fixture()
        self.assertFalse(engine.env.su)
        for column, value, line_name in (
                ('base', '100.00', 'VAT drill base'), ('tax', '15.00', 'VAT drill tax')):
            with self.subTest(column=column):
                selector = {'kind': 'cell', 'box': '1', 'column': column}
                detail = engine.get_drilldown('vat', filters, selector, 1)
                self.assertEqual(detail['value'], value)
                self.assertEqual(len(detail['rows']), 1)
                row = detail['rows'][0]
                line = move.line_ids.filtered(lambda item: item.name == line_name)
                self.assertEqual(row['cells']['amount'], value)
                self.assertEqual(row['source'], {'kind': 'source', 'parent': selector, 'line_id': line.id})
                action = engine.open_source('vat', filters, row['source'])
                self.assertEqual(action['res_model'], 'account.move.line')
                self.assertEqual(action['views'], [[False, 'list'], [False, 'form']])
                self.assertEqual(action['domain'], [('id', '=', line.id)])
                actual = engine.env['account.move.line'].search(action['domain'])
                self.assertEqual(actual.ids, line.ids)
                self.assertEqual(actual.move_id.id, move.id)

    def test_hidden_linked_move_journal_or_account_denies_detail_and_source(self):
        engine, filters, move, income, journal = self._nonzero_reader_fixture()
        # Do not select a journal explicitly: exercise linked-source guards,
        # not merely the initial filter's journal visibility validation.
        filters = dict(filters, journal_ids=[])
        selector = {'kind': 'cell', 'box': '1', 'column': 'base'}
        detail = engine.get_drilldown('vat', filters, selector, 1)
        self.assertEqual(detail['value'], '100.00')
        source = detail['rows'][0]['source']
        for model, identity in (
                ('account.move', move.id), ('account.journal', journal.id), ('account.account', income.id)):
            with self.subTest(hidden_model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'VAT drill hidden linked record',
                    'model_id': self.env['ir.model']._get_id(model),
                    'domain_force': "[('id', '!=', %s)]" % identity,
                })
                try:
                    # Establish that this is an actual record-rule denial for
                    # the ordinary reader, including a previously issued token.
                    with self.assertRaises(AccessError):
                        engine.env[model].browse(identity).check_access('read')
                    with self.assertRaises(AccessError):
                        engine.get_drilldown('vat', filters, selector, 1)
                    with self.assertRaises(AccessError):
                        engine.open_source('vat', filters, source)
                finally:
                    rule.unlink()
                self.assertEqual(engine.get_drilldown('vat', filters, selector, 1)['value'], '100.00')

    def test_fixed_cell_selector_rejects_tampering_and_keeps_zero_cell(self):
        report = self.env['baseer.tax.report.wizard']
        data = {'rows': [{'number': '1', 'base': Decimal('0.00'), 'tax': Decimal('0.00'),
                          'direct': {'base': '1(B)', 'tax': '1(T)'}, 'components': {'base': [], 'tax': []}}]}
        row = report._drill_cell(None, data, {'kind': 'cell', 'box': '1', 'column': 'base'})
        self.assertEqual(row['base'], Decimal('0.00'))
        for selector in ({'kind': 'cell', 'box': [], 'column': 'base'},
                         {'kind': 'cell', 'box': '17', 'column': 'base'},
                         {'kind': 'cell', 'box': '1', 'column': 'total'}):
            with self.assertRaises(ValidationError):
                report._drill_cell(None, data, selector)

    def test_central_dispatch_uses_actual_zero_source_scope(self):
        self.env.company.account_fiscal_country_id = self.env.ref('base.sa')
        filters = {'company_id': self.env.company.id, 'period_type': 'quarter', 'year': 2099,
                   'month': '1', 'quarter': '4', 'display_mode': 'detailed', 'journal_ids': []}
        result = self.env['baseer.report.drill'].get_drilldown('vat', filters, {'kind': 'cell', 'box': '1', 'column': 'base'}, 1)
        self.assertEqual(result['value'], '0.00')
        self.assertEqual(result['rows'], [])

    def test_composite_parent_cannot_be_forged_as_a_source_action(self):
        report = self.env['baseer.tax.report.wizard']
        wizard = Mock()
        wizard._build_report.return_value = {'rows': []}
        selector = {'kind': 'source', 'parent': {'kind': 'cell', 'box': '6', 'column': 'base'}, 'line_id': 1}
        with patch.object(type(report), '_drill_wizard', return_value=wizard), \
                patch.object(type(report), '_direct_lines', return_value=({}, None, [])), \
                self.assertRaises(ValidationError):
            report._open_drill_source({'company_id': self.env.company.id, 'period_type': 'quarter', 'year': 2099,
                                       'month': '1', 'quarter': '4', 'display_mode': 'detailed', 'journal_ids': []}, selector)

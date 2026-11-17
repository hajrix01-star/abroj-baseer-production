"""Tests for the partner grouping used by the ledger engine."""
from odoo.tests.common import tagged

from .common import EngineCase


@tagged('post_install', '-at_install')
class TestPartnerLedgerGrouping(EngineCase):
    def test_grouping_includes_unknown_and_cumulative_opening(self):
        company = self._company('Partner grouping')
        engine = self._engine(company)
        journal = self._journal(company, 'PLG')
        receivable = self._account(company, '1100', 'asset_receivable')
        other = self._account(company, '4000', 'income')
        partner = self.env['res.partner'].create({'name': 'Grouping partner'})
        first = self._entry(company, journal, '2040-04-01', receivable, other, 10)
        second = self._entry(company, journal, '2041-04-01', receivable, other, 7)
        self._entry(company, journal, '2041-04-02', receivable, other, 3)
        (first | second).line_ids.filtered(lambda line: line.account_id == receivable).partner_id = partner
        report = engine._definition('general_ledger')
        options = engine._normalize_options(report, self._options(date_from='2041-04-01', date_to='2041-04-30'))
        initial, period = engine._ledger_partner_data(options, [('account_id', '=', receivable.id)])
        self.assertEqual(initial[partner.id]['balance'], 10)
        self.assertEqual(period[partner.id]['balance'], 7)
        self.assertEqual(period[0]['balance'], 3)

    def test_report_and_partner_page(self):
        company = self._company('Partner report')
        engine = self._engine(company)
        journal = self._journal(company, 'PLR')
        receivable = self._account(company, '1100', 'asset_receivable')
        other = self._account(company, '4000', 'income')
        partner = self.env['res.partner'].create({'name': 'Report partner'})
        move = self._entry(company, journal, '2041-04-01', receivable, other, 7)
        move.line_ids.filtered(lambda line: line.account_id == receivable).partner_id = partner
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        payload = engine.get_report('partner_ledger', options)
        row = next(row for row in payload['lines'] if row.get('partner_id') == partner.id)
        self.assertEqual(float(row['amounts'][-1]['value']), 7)
        page = engine.get_ledger_lines('partner_ledger', options, partner.id)
        self.assertEqual(page['rows'][0]['id'], move.line_ids.filtered(lambda line: line.account_id == receivable).id)
        self.assertEqual(engine.get_partner_action(partner.id)['res_id'], partner.id)
        action = engine.get_move_line_action('partner_ledger', options, row['code'], 'balance', partner.id)
        self.assertEqual(sum(self.env['account.move.line'].search(action['domain']).mapped('balance')), 7)

    def test_invalid_partner_options(self):
        from odoo.exceptions import ValidationError
        company = self._company('Partner options')
        engine = self._engine(company)
        for options in ({'account_types': []}, {'account_types': ['income']},
                        {'partner_ids': [True]}, {'unreconciled': 1}):
            with self.assertRaises(ValidationError):
                engine.get_report('partner_ledger', options)

    def test_unknown_opening_and_paging(self):
        company = self._company('Partner pages')
        engine = self._engine(company).with_context(baseer_gl_page_size=2)
        journal = self._journal(company, 'PLP')
        receivable = self._account(company, '1100', 'asset_receivable')
        other = self._account(company, '4000', 'income')
        for day, amount in [('2041-03-01', 5), ('2041-04-01', 2), ('2041-04-02', 3), ('2041-04-03', 4)]:
            self._entry(company, journal, day, receivable, other, amount)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        report = engine.get_report('partner_ledger', options)
        row = next(r for r in report['lines'] if r.get('partner_id') == 0)
        self.assertEqual(float(row['amounts'][-1]['value']), 14)
        page = engine.get_ledger_lines('partner_ledger', options, False)
        self.assertEqual(page['rows'][0]['type'], 'initial')
        self.assertTrue(page['has_more'])
        page = engine.get_ledger_lines('partner_ledger', options, False, offset=2)
        self.assertEqual(float(page['rows'][0]['amounts'][-1]['value']), 14)
        self.assertFalse(page['has_more'])

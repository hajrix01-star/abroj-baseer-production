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

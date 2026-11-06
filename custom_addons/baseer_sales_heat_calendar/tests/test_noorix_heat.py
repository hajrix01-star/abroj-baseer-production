"""Heat/day/detail parity for optional verified Noorix evidence, rollback-only."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.baseer_sales_dashboard.tests.test_noorix_evidence import NoorixEvidenceFixtures
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged, new_test_user


@tagged('post_install', '-at_install')
class TestNoorixHeat(NoorixEvidenceFixtures, AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_noorix_evidence_fixtures()
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')
        cls.heat = cls.env.ref('baseer_sales_heat_calendar.dashboard_sales_heat_calendar')
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_sales_summary')

    def _read(self, include):
        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 11, 6, 12)):
            return self.heat.get_baseer_heat_calendar('2026-11', include_noorix=include)

    def test_five_day_parity_customers_details_and_no_write(self):
        Evidence = self.env['baseer.noorix.sales.evidence']
        originals = []
        for day, gross, guests in ((1, '8113', 126), (2, '8167', 123), (3, '8733', 129),
                                   (4, '8293', 131), (5, '11498', 149)):
            source = f'heat-source-{day}'
            move = self._noorix_entry(source, f'2026-11-{day:02}', gross, agent_prefix=True)
            Evidence.import_evidence([self._noorix_row(move, source, guests)])
            originals.append(move)
        digests = [Evidence._ledger_digest(move) for move in originals]
        off = self._read(False)
        self.assertFalse(any(day['has_sales'] for week in off['weeks'] for day in week if day))
        on = self._read(True)
        days = [day for week in on['weeks'] for day in week if day and day['has_sales']]
        self.assertEqual(len(days), 5)
        self.assertEqual(sum(Decimal(day['sales_value']) for day in days), Decimal('44804.00'))
        self.assertEqual(sum(day['customers_value'] for day in days), 658)
        for day, move in zip(days, originals):
            self.assertEqual(day['status'], 'complete')
            self.assertEqual(day['source_kinds'], ['noorix'])
            self.assertEqual(day['source_kind'], 'noorix')
            self.assertEqual(day['source_action']['domain'][0][2], [move.id])
            self.assertEqual(len(day['shift_breakdown']), 1)
            result = self.dashboard.get_baseer_sales_metrics(
                {'preset': 'custom', 'date_from': day['date'], 'date_to': day['date']}, include_noorix=True)
            self.assertEqual(result['cards']['sales']['value'], day['sales_value'])
            self.assertEqual(result['cards']['customers']['value'], day['customers_value'])
        self.assertEqual([Evidence._ledger_digest(move) for move in originals], digests)
        self.assertEqual(self._read(False), off)

    def test_partial_source_does_not_claim_complete_day_or_heat(self):
        source = 'heat-partial'
        move = self._noorix_entry(source)
        self.env['baseer.noorix.sales.evidence'].import_evidence([
            self._noorix_row(move, source, 0, 'morning')])
        day = next(day for week in self._read(True)['weeks'] for day in week if day and day['day'] == 1)
        self.assertEqual(day['status'], 'incomplete')
        self.assertEqual(day['heat_level'], 'neutral')
        self.assertIsNone(day['customers_value'])
        self.assertIsNone(day['ratio_value'])

    def test_reversal_day_has_money_but_no_invented_day_completion(self):
        source = 'heat-reversal'
        move = self._noorix_entry(source)
        self.env['baseer.noorix.sales.evidence'].import_evidence([self._noorix_row(move, source)])
        reversal = move._reverse_moves([{'date': '2026-11-03'}], cancel=False)
        reversal.action_post()
        day = next(day for week in self._read(True)['weeks'] for day in week if day and day['day'] == 3)
        self.assertEqual(day['sales_value'], '-115.00')
        self.assertEqual(day['status'], 'incomplete')
        self.assertEqual(day['heat_level'], 'neutral')
        self.assertIsNone(day['ratio_value'])

    def test_heat_option_rejects_non_boolean(self):
        for value in ('false', 0, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self._read(value)

    def test_authorized_non_admin_heat_reader(self):
        source = 'heat-reader'
        move = self._noorix_entry(source)
        self.env['baseer.noorix.sales.evidence'].import_evidence([self._noorix_row(move, source)])
        reader = new_test_user(self.env, login='noorix_heat_reader',
            groups='base.group_user,point_of_sale.group_pos_user,sales_team.group_sale_salesman_all_leads,account.group_account_readonly',
            company_id=self.env.company.id, company_ids=[Command.set(self.env.company.ids)])
        heat = self.heat.with_user(reader).with_context(allowed_company_ids=self.env.company.ids)
        self.assertFalse(heat.env.su)
        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 11, 6, 12)):
            result = heat.get_baseer_heat_calendar('2026-11', include_noorix=True)
        day = next(day for week in result['weeks'] for day in week if day and day['day'] == 1)
        self.assertEqual(day['customers_value'], 3)

from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from ..models.dashboard import _card
from ..models.executive import _validate_company_ids


class ExecutiveCardsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_executive_center')

    def test_strict_company_input_and_authority(self):
        for invalid in (None, [], [True], ['1'], [1.0], [0], [1, 1], [1, 2, 3, 4]):
            with self.assertRaises(ValidationError):
                _validate_company_ids(invalid, [1, 2, 3, 4])
        with self.assertRaises(AccessError):
            _validate_company_ids([2], [1])
        _validate_company_ids([3, 1], [1, 2, 3])

    def test_separate_dashboard_and_home(self):
        sales = self.env.ref('baseer_sales_dashboard.dashboard_sales_summary')
        self.assertNotEqual(self.dashboard.id, sales.id)
        self.assertEqual(self.dashboard.baseer_dashboard_kind, 'executive_center')
        self.assertEqual(sales.baseer_dashboard_kind, 'sales_summary')
        self.assertEqual(self.env.ref('baseer_sales_dashboard.action_executive_home').params['dashboard_id'], self.dashboard.id)
        self.dashboard.is_published = False
        with self.assertRaises(AccessError):
            self.dashboard.get_baseer_executive_companies()

    def test_registered_selection_rpcs_and_standalone_frontend(self):
        """Keep every link required to render an existing executive dashboard."""
        selection = self.dashboard._fields['baseer_dashboard_kind']._description_selection(self.env)
        self.assertIn('executive_center', dict(selection))
        for method in ('get_baseer_executive_companies', 'get_baseer_executive_cards', 'get_baseer_executive_sessions'):
            self.assertTrue(callable(getattr(self.dashboard, method)))
        module = Path(__file__).resolve().parents[1]
        integration = (module / 'static/src/dashboard_integration.js').read_text(encoding='utf-8')
        self.assertIn('import { BaseerExecutiveCenter } from "./executive_center"', integration)
        self.assertIn('get isBaseerExecutiveDashboard()', integration)
        frontend = (module / 'static/src/executive_center.js').read_text(encoding='utf-8')
        self.assertIn('"get_baseer_executive_companies"', frontend)
        self.assertIn('"get_baseer_executive_cards"', frontend)
        template = ElementTree.parse(module / 'static/src/dashboard_integration.xml')
        sections = template.findall(".//section[@t-if='isBaseerExecutiveDashboard']")
        self.assertEqual(len(sections), 1)
        self.assertIsNotNone(sections[0].find('BaseerExecutiveCenter'))
        # Later dashboard extensions can replace native t-if attributes. Their
        # targets must retain an outer executive guard to prevent a blank sheet.
        guards = template.findall(".//t[@t-if='!isBaseerExecutiveDashboard']")
        guarded = {child.tag for guard in guards for child in guard}
        self.assertTrue({'DashboardSearchBar', 'SpreadsheetShareButton', 'MobileFigureContainer', 'div'} <= guarded)
        sales = ElementTree.parse(module / 'static/src/sales_dashboard.xml')
        self.assertEqual(sales.findall('.//BaseerExecutiveCenter'), [])

    def test_rpcs_reject_unrelated_dashboard_kind(self):
        self.dashboard.baseer_dashboard_kind = False
        with self.assertRaises(AccessError):
            self.dashboard.get_baseer_executive_companies()
        with self.assertRaises(AccessError):
            self.dashboard.get_baseer_executive_cards(self.env.company.ids)

    def test_change_zero_and_missing_are_distinct(self):
        change = self.dashboard._baseer_executive_change
        self.assertEqual(change(_card(0), _card(0), True)['direction'], 'flat')
        self.assertEqual(change(_card(12), _card(0), True)['direction'], 'new')
        result = change(_card(75), _card(100), True)
        self.assertEqual(result['display'], '-25.00%')
        self.assertEqual(result['amount_display'], '-25.00')
        self.assertFalse(change(_card(0), _card(None, False), True)['available'])

    def test_company_context_is_validated_and_replaced(self):
        sar = self.env.ref('base.SAR')
        company = self.env['res.company'].create({'name': 'EC permitted', 'currency_id': sar.id})
        other = self.env['res.company'].create({'name': 'EC forbidden', 'currency_id': sar.id})
        user = new_test_user(self.env, login='ec_reader', groups='base.group_user,point_of_sale.group_pos_user',
                             company_id=company.id, company_ids=[Command.set(company.ids)])
        dashboard = self.dashboard.with_user(user).with_context(
            allowed_company_ids=other.ids, active_test=False, arbitrary='discard')
        allowed = dashboard.get_baseer_executive_companies()
        self.assertEqual([row['id'] for row in allowed['companies']], company.ids)
        with self.assertRaises(AccessError):
            dashboard.get_baseer_executive_cards(other.ids)

        def capture(record, selected, period, now):
            self.assertEqual(record.env.company.id, company.id)
            self.assertEqual(record.env.context['allowed_company_ids'], company.ids)
            self.assertNotIn('arbitrary', record.env.context)
            self.assertNotIn('active_test', record.env.context)
            self.assertFalse(record.env.su)
            return {'company_id': selected.id}

        with patch.object(type(dashboard), '_baseer_executive_card', capture):
            self.assertEqual(dashboard.get_baseer_executive_cards(company.ids)['cards'],
                             [{'company_id': company.id}])

    def test_no_pos_permission_is_denied(self):
        user = new_test_user(self.env, login='ec_no_pos', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.dashboard.with_user(user).get_baseer_executive_companies()

    def test_authorized_selection_survives_different_header_company(self):
        sar = self.env.ref('base.SAR')
        companies = self.env['res.company'].create([
            {'name': 'EC header', 'currency_id': sar.id},
            {'name': 'EC selected', 'currency_id': sar.id},
        ])
        user = new_test_user(self.env, login='ec_multi', groups='base.group_user,point_of_sale.group_pos_user',
                             company_id=companies[0].id, company_ids=[Command.set(companies.ids)])
        dashboard = self.dashboard.with_user(user).with_context(allowed_company_ids=companies[0].ids)
        def capture(record, selected, period, now):
            self.assertEqual(record.env.company.id, selected.id)
            self.assertFalse(record.env.su)
            return {'id': selected.id}
        with patch.object(type(dashboard), '_baseer_executive_card', capture):
            self.assertEqual(dashboard.get_baseer_executive_cards(companies[1].ids)['cards'],
                             [{'id': companies[1].id}])
        self.dashboard.company_ids = [Command.set(companies[0].ids)]
        with self.assertRaises(AccessError):
            dashboard.get_baseer_executive_cards(companies[1].ids)

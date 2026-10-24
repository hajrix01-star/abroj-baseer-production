from datetime import date
from decimal import Decimal
from unittest.mock import patch
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from .test_activity import TestAccountActivity


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestActivityDrill(TransactionCase):
    _entry = TestAccountActivity._entry

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.asset = self.env['account.account'].create({'code': '915029', 'name': 'Activity drill asset',
            'account_type': 'asset_current', 'company_ids': [Command.set(self.company.ids)]})
        self.counterpart = self.env['account.account'].search([('company_ids', 'in', self.company.id), ('account_type', '=', 'expense')], limit=1)
        self.journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        self.report = self.env['baseer.account.activity']
        self.filters = {'company_id': self.company.id, 'account_id': self.asset.id, 'date_from': '2041-03-01', 'date_to': '2041-03-31'}
        self.opening = self._entry(date(2041, 2, 1), self.asset, debit=15)
        self.first = self._entry(date(2041, 3, 2), self.asset, debit=20)
        self.second = self._entry(date(2041, 3, 3), self.asset, credit=5)
        self.reader = self.env['res.users'].create({'name': 'Drill reader', 'login': 'activity.drill.reader',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('account.group_account_readonly').id])]})

    def test_summary_line_running_and_source_membership(self):
        engine = self.env['baseer.report.drill'].with_user(self.reader)
        for measure, expected in [('opening', '15.00'), ('debit', '20.00'), ('credit', '5.00'), ('closing', '30.00')]:
            result = engine.get_drilldown('activity', self.filters, {'kind': 'summary', 'measure': measure})
            self.assertEqual(result['value'], expected)
            self.assertEqual(sum((Decimal(row['cells']['amount']) for row in result['rows']), Decimal('0')), Decimal(expected))
            for row in result['rows']:
                action = engine.open_source('activity', self.filters, row['source'])
                self.assertEqual(action['res_model'], 'account.move')
        result = engine.get_drilldown('activity', self.filters, {'kind': 'line', 'line_id': self.first.id, 'measure': 'running'})
        self.assertEqual(result['value'], '35.00')
        self.assertEqual(result['total_count'], 2)
        token = result['rows'][0]['source']
        with self.assertRaises(AccessError):
            engine.open_source('activity', self.filters, dict(token, line_id=self.second.id))
        zero = engine.get_drilldown('activity', self.filters, {'kind': 'line', 'line_id': self.first.id, 'measure': 'credit'})
        self.assertEqual(zero['value'], '0.00')
        self.assertEqual(zero['total_count'], 1)

    def test_scope_denial_tampering_and_bounded_pagination(self):
        engine = self.env['baseer.report.drill'].with_user(self.reader)
        selector = {'kind': 'summary', 'measure': 'closing'}
        for invalid in [dict(selector, amount='999'), dict(selector, measure='domain'), {'kind': 'source'}, {'kind': 'line', 'measure': 'debit', 'line_id': True}]:
            with self.assertRaises(ValidationError):
                engine.get_drilldown('activity', self.filters, invalid)
        for page in (0, True, 2, 101):
            with self.assertRaises(ValidationError):
                engine.get_drilldown('activity', self.filters, selector, page)
        with self.assertRaises(AccessError):
            engine.get_drilldown('activity', dict(self.filters, company_id=self.company.id + 999), selector)
        with patch.object(type(self.report), 'EXPORT_SOURCE_LIMIT', 1), self.assertRaises(ValidationError):
            engine.get_drilldown('activity', self.filters, selector)
        self.env['ir.rule'].create({'name': 'Hide activity drill opening', 'model_id': self.env['ir.model']._get_id('account.move.line'),
            'domain_force': "[('id', '!=', %s)]" % self.opening.id})
        with self.assertRaises(AccessError):
            engine.get_drilldown('activity', self.filters, selector)

    def test_plain_user_is_denied(self):
        plain = self.env['res.users'].create({'name': 'Drill denied', 'login': 'activity.drill.denied',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)]})
        with self.assertRaises(AccessError):
            self.env['baseer.report.drill'].with_user(plain).get_drilldown('activity', self.filters, {'kind': 'summary', 'measure': 'debit'})

    def test_dispatch_and_page_contract_fail_closed(self):
        engine = self.env['baseer.report.drill']
        for value in (set(), b'bad'):
            with self.assertRaises(ValidationError):
                engine.get_drilldown('activity', self.filters, {'bad': value})
        circular = {}
        circular['self'] = circular
        with self.assertRaises(ValidationError):
            engine.get_drilldown('activity', self.filters, circular)
        from odoo.addons.baseer_reports_menu.report_drill import drill_result
        rows = [{'key': number, 'cells': {'amount': '1.00'}} for number in range(51)]
        detail = drill_result('Total', '51.00', 'Complete value', [{'key': 'amount', 'label': 'Amount'}], rows, 2)
        self.assertEqual(detail['value'], '51.00')
        self.assertEqual(detail['total_count'], 51)
        self.assertEqual(len(detail['rows']), 1)
        with self.assertRaises(ValidationError):
            drill_result('Total', '51.00', 'Complete value', [{'key': 'amount', 'label': 'Amount'}], rows, 3)

"""Real ORM QA fixtures: optional source, accounting invariance and coverage."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged

from .test_noorix_evidence import NoorixEvidenceFixtures


@tagged('post_install', '-at_install')
class TestNoorixSales(NoorixEvidenceFixtures, AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_noorix_evidence_fixtures()
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_sales_summary')
        cls.Evidence = cls.env['baseer.noorix.sales.evidence']

    def _import_day(self, day=1, gross='115.00', customers=3, scope='all'):
        source_id = f'synthetic-day-{day}'
        move = self._noorix_entry(source_id, f'2026-11-{day:02d}', gross, agent_prefix=True)
        row = self._noorix_row(move, source_id, customers, scope)
        evidence = self.Evidence.browse(self.Evidence.import_evidence([row]))
        return move, evidence

    def _metrics(self, include=False, first='2026-11-01', last='2026-11-30', dashboard=None):
        return (dashboard or self.dashboard).get_baseer_sales_metrics(
            {'preset': 'custom', 'date_from': first, 'date_to': last}, include_noorix=include)

    def _five(self):
        return [self._import_day(day, gross, guests) for day, gross, guests in (
            (1, '8113.00', 126), (2, '8167.00', 123), (3, '8733.00', 129),
            (4, '8293.00', 131), (5, '11498.00', 149))]

    def test_five_days_and_customers_once_without_financial_writes(self):
        records = self._five()
        moves = self.env['account.move'].browse([move.id for move, _evidence in records])
        fingerprints = {move.id: self.Evidence._ledger_digest(move) for move in moves}
        models = ('account.move', 'account.move.line', 'pos.order', 'pos.session',
                  'baseer.pos.summary', 'account.edi.document', 'ir.attachment')
        counts = {name: self.env[name].search_count([]) for name in models if name in self.env}
        off = self._metrics()
        self.assertEqual(off['cards']['sales']['value'], '0.00')
        for _read in range(2):
            on = self._metrics(True)
            self.assertEqual(on['cards']['sales']['value'], '44804.00')
            self.assertEqual(on['cards']['customers']['value'], 658)
            self.assertTrue(on['customer_coverage']['complete'])
            noorix = next(row for row in on['source_breakdown'] if row['key'] == 'noorix')
            self.assertEqual(noorix['sales']['value'], '44804.00')
            self.assertEqual(set(noorix['source_action']['domain'][0][2]), set(moves.ids))
            self.assertEqual(on['payment_performance']['coverage']['noorix_tender_unknown']['value'], '44804.00')
            self.assertFalse(on['payment_performance']['coverage']['complete'])
            self.assertEqual([point['customers'] for point in on['timeline']['points'][:5]],
                             [126, 123, 129, 131, 149])
        self.assertEqual({name: self.env[name].search_count([]) for name in counts}, counts)
        self.assertEqual({move.id: self.Evidence._ledger_digest(move) for move in moves}, fingerprints)
        self.assertEqual(self._metrics(), off)

    def test_bool_is_explicit_and_false_does_not_read_evidence(self):
        self._import_day()
        for value in ('true', 1, None, {}, []):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self._metrics(value)
        model = type(self.Evidence)
        with patch.object(model, '_validated_amounts', side_effect=AssertionError('Unexpected source read')):
            result = self._metrics(False, dashboard=self.dashboard.with_context(baseer_include_noorix=True))
            self.assertEqual(result['cards']['sales']['value'], '0.00')

    def test_missing_metadata_and_drift_fail_closed(self):
        move = self._noorix_entry('unmapped')
        with self.assertRaises(ValidationError):
            self._metrics(True)
        self.Evidence.import_evidence([self._noorix_row(move, 'unmapped')])
        self.assertEqual(self._metrics(True)['cards']['sales']['value'], '115.00')
        move.ref += ' edited'
        with self.assertRaises(ValidationError):
            self._metrics(True)
        self.assertEqual(self._metrics()['cards']['sales']['value'], '0.00')

    def test_full_reversal_has_own_date_and_never_repeats_customers(self):
        move, _evidence = self._import_day()
        reversal = move._reverse_moves([{'date': '2026-11-03'}], cancel=False)
        reversal.action_post()
        period = self._metrics(True)
        self.assertEqual(period['cards']['sales']['value'], '0.00')
        self.assertEqual(period['cards']['customers']['value'], 3)
        self.assertFalse(period['customer_coverage']['complete'])
        self.assertFalse(period['cards']['average_bill']['available'])
        self.assertEqual(self._metrics(True, '2026-11-03', '2026-11-03')['cards']['sales']['value'], '-115.00')
        self.assertEqual(self._metrics(True, '2026-11-01', '2026-11-01')['cards']['sales']['value'], '115.00')

    def test_unmapped_original_before_period_cannot_hide_its_reversal(self):
        move = self._noorix_entry('unmapped-ancestor')
        reversal = move._reverse_moves([{'date': '2026-11-03'}], cancel=False)
        reversal.action_post()
        with self.assertRaises(ValidationError):
            self._metrics(True, '2026-11-03', '2026-11-03')
        self.assertEqual(self._metrics(False, '2026-11-03', '2026-11-03')['cards']['sales']['value'], '0.00')

    def test_same_day_source_collision_is_not_silently_summed(self):
        self._import_day()
        move = self._noorix_entry('second-source', '2026-11-01', '115.00')
        self.Evidence.import_evidence([self._noorix_row(move, 'second-source')])
        with self.assertRaises(ValidationError):
            self._metrics(True)

    def test_native_invoice_overlap_is_explicit_even_for_one_riyal(self):
        self._import_day()
        product = self.env['product.product'].create({
            'name': 'Independent identity requires proof', 'type': 'service', 'invoice_policy': 'order',
            'property_account_income_id': self.company_data['default_account_revenue'].id,
            'taxes_id': [Command.clear()],
        })
        sale = self.env['sale.order'].create({'partner_id': self.partner_a.id,
            'order_line': [Command.create({'product_id': product.id, 'product_uom_qty': 1,
                                          'price_unit': 1, 'tax_ids': [Command.clear()]})]})
        sale.action_confirm()
        invoice = sale._create_invoices()
        invoice.invoice_date = '2026-11-01'
        invoice.action_post()
        self.assertEqual(self._metrics(False)['cards']['sales']['value'], '1.00')
        with self.assertRaises(ValidationError):
            self._metrics(True)

    def test_authorized_non_admin_reader_uses_same_secured_rpc(self):
        self._import_day()
        reader = new_test_user(self.env, login='noorix_report_reader',
            groups='base.group_user,point_of_sale.group_pos_user,sales_team.group_sale_salesman_all_leads,account.group_account_readonly',
            company_id=self.env.company.id, company_ids=[Command.set(self.env.company.ids)])
        dashboard = self.dashboard.with_user(reader).with_context(allowed_company_ids=self.env.company.ids)
        self.assertFalse(dashboard.env.su)
        self.assertFalse(reader.with_user(reader).has_group('base.group_system'))
        self.assertEqual(self._metrics(True, dashboard=dashboard)['cards']['customers']['value'], 3)

    def test_existing_edi_state_and_payload_remain_unchanged_without_sending(self):
        if 'account.edi.document' not in self.env:
            self.skipTest('The isolated EDI boundary test requires native account_edi.')
        move, _evidence = self._import_day()
        Edi = self.env['account.edi.document']
        fmt = self.env['account.edi.format'].create({'name': 'Synthetic NSI sentinel', 'code': 'nsi_qa_only'})
        document = Edi.create({'move_id': move.id, 'edi_format_id': fmt.id,
                               'state': 'to_send', 'error': '<p>Unsent QA sentinel</p>'})
        fields = ['id', 'move_id', 'edi_format_id', 'state', 'error', 'blocking_level']
        before = document.read(fields)
        with patch.object(type(Edi), '_process_job', side_effect=AssertionError('No EDI job from a report')), \
             patch('requests.sessions.Session.request', side_effect=AssertionError('No HTTP from a report')):
            self.assertEqual(self._metrics(True)['cards']['sales']['value'], '115.00')
            self._metrics(False)
            self._metrics(True)
        document.invalidate_recordset()
        self.assertEqual(document.read(fields), before)

    def test_all_time_and_previous_period_keep_source_option(self):
        self._import_day(5, '11498.00', 149)
        on = self.dashboard.get_baseer_sales_metrics({'native': None}, include_noorix=True)
        self.assertEqual(on['filters']['date_from'], '2026-11-05')
        self.assertEqual(on['filters']['date_to'], '2026-11-05')
        self.assertEqual(on['cards']['sales']['value'], '11498.00')
        result = self._metrics(True, '2026-11-06', '2026-11-06')
        self.assertEqual(result['cards']['sales']['comparison']['previous_display'], '11,498.00')

    def test_unauthorized_user_cannot_read_or_forge_metadata(self):
        _move, evidence = self._import_day()
        reader = new_test_user(self.env, login='noorix_pos_only', groups='base.group_user,point_of_sale.group_pos_user',
                               company_id=self.env.company.id, company_ids=[Command.set(self.env.company.ids)])
        with self.assertRaises(AccessError):
            evidence.with_user(reader).read(['customer_count'])
        with self.assertRaises(AccessError):
            self.Evidence.with_user(reader).import_evidence([])

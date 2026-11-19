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

    def test_missing_metadata_uses_posted_money_but_stored_evidence_drift_still_fails(self):
        move = self._noorix_entry('unmapped')
        digest = self.Evidence._ledger_digest(move)
        count = self.Evidence.search_count([])
        result = self._metrics(True)
        self.assertEqual(result['cards']['sales']['value'], '115.00')
        self.assertFalse(result['cards']['customers']['available'])
        self.assertFalse(result['customer_coverage']['complete'])
        self.assertEqual(self.Evidence.search_count([]), count)
        self.assertEqual(self.Evidence._ledger_digest(move), digest)
        self.Evidence.import_evidence([self._noorix_row(move, 'unmapped')])
        self.assertEqual(self._metrics(True)['cards']['sales']['value'], '115.00')
        self.assertEqual(self._metrics(True)['cards']['customers']['value'], 3)
        move.ref += ' edited'
        with self.assertRaises(ValidationError):
            self._metrics(True)
        self.assertEqual(self._metrics()['cards']['sales']['value'], '0.00')

    def test_legacy_entry_without_source_tag_uses_typed_odoo_identity_and_own_reversal_date(self):
        move = self._noorix_entry('legacy-without-src')
        move.ref = 'NOORIX-SALES SHAMI 2026-11-01'
        identity = self.Evidence._ledger_source_identity(move, self.env.company)
        self.assertEqual(identity, (self.env.company.id, 'SHAMI', ('odoo_move', move.id)))
        digest = self.Evidence._ledger_digest(move)
        evidence_count = self.Evidence.search_count([])
        for _read in range(2):
            result = self._metrics(True)
            self.assertEqual(result['cards']['sales']['value'], '115.00')
            self.assertFalse(result['cards']['customers']['available'])
        self.assertEqual(self.Evidence.search_count([]), evidence_count)
        self.assertEqual(self.Evidence._ledger_digest(move), digest)
        explicit = self._noorix_entry(f'odoo_move_{move.id}', '2026-11-02')
        explicit_identity = self.Evidence._ledger_source_identity(explicit, self.env.company)
        self.assertIsInstance(explicit_identity[2], str)
        self.assertNotEqual(identity, explicit_identity)
        self.assertEqual(self._metrics(True)['cards']['sales']['value'], '230.00')
        reversal = move._reverse_moves([{'date': '2026-11-03'}], cancel=False)
        reversal.action_post()
        self.assertEqual(self._metrics(True)['cards']['sales']['value'], '115.00')
        result = self._metrics(True, '2026-11-03', '2026-11-03')
        self.assertEqual(result['cards']['sales']['value'], '-115.00')
        self.assertFalse(result['cards']['customers']['available'])

    def test_present_invalid_or_duplicate_source_tag_never_uses_legacy_fallback(self):
        move = self._noorix_entry('invalid-source-tag')
        prefix = 'NOORIX-SALES SHAMI 2026-11-01 | '
        for suffix in ('src', 'src:', 'src:invalid!', 'src :value', 'SRC:value',
                       'src:first src:second', 'src:first src:', 'src:first |src:second'):
            with self.subTest(suffix=suffix):
                move.ref = prefix + suffix
                with self.assertRaises(ValidationError):
                    self._metrics(True)

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

    def test_original_without_metadata_before_period_resolves_its_reversal(self):
        move = self._noorix_entry('unmapped-ancestor')
        reversal = move._reverse_moves([{'date': '2026-11-03'}], cancel=False)
        reversal.action_post()
        result = self._metrics(True, '2026-11-03', '2026-11-03')
        self.assertEqual(result['cards']['sales']['value'], '-115.00')
        self.assertFalse(result['cards']['customers']['available'])
        self.assertEqual(self._metrics(False, '2026-11-03', '2026-11-03')['cards']['sales']['value'], '0.00')

    def test_ledger_identity_cannot_duplicate_evidence_on_another_day(self):
        self._import_day()
        self._noorix_entry('synthetic-day-1', '2026-11-02')
        with self.assertRaises(ValidationError):
            self._metrics(True)

    def test_missing_metadata_does_not_relax_money_identity_or_read_budget(self):
        move = self._noorix_entry('ledger-only-invalid')
        dashboard = self.dashboard.with_context(baseer_include_noorix=True)
        with self.assertRaises(ValidationError):
            dashboard._noorix_events(self.env.company, budget=1)
        original_ref = move.ref
        move.ref = original_ref.replace('2026-11-01', '2026-11-02')
        with self.assertRaises(ValidationError):
            self._metrics(True)
        move.ref = original_ref
        move.line_ids.filtered(lambda line: line.tax_tag_ids).tax_tag_ids = [Command.clear()]
        with self.assertRaises(ValidationError):
            self._metrics(True)

    def test_ledger_only_read_is_local_readonly_and_preserves_off(self):
        move = self._noorix_entry('ledger-only-readonly')
        models = ('account.move', 'account.move.line', 'baseer.noorix.sales.evidence')
        counts = {name: self.env[name].search_count([]) for name in models}
        digest = self.Evidence._ledger_digest(move)
        off = self._metrics(False)
        with patch('requests.sessions.Session.request', side_effect=AssertionError('No Noorix connection from a report')):
            for _read in range(2):
                self.assertEqual(self._metrics(True)['cards']['sales']['value'], '115.00')
        self.assertEqual(self._metrics(False), off)
        self.assertEqual({name: self.env[name].search_count([]) for name in models}, counts)
        self.assertEqual(self.Evidence._ledger_digest(move), digest)

    def test_same_day_source_collision_is_not_silently_summed(self):
        self._import_day()
        move = self._noorix_entry('second-source', '2026-11-01', '115.00')
        self.Evidence.import_evidence([self._noorix_row(move, 'second-source')])
        with self.assertRaises(ValidationError):
            self._metrics(True)

    def test_distinct_posted_ledger_sources_on_the_same_day_count_once_each(self):
        self._noorix_entry('ledger-first')
        self._noorix_entry('ledger-second', gross='230.00')
        for _read in range(2):
            result = self._metrics(True)
            self.assertEqual(result['cards']['sales']['value'], '345.00')
            self.assertFalse(result['cards']['customers']['available'])

    def test_ledger_original_and_reversal_with_native_payment_links_are_rejected(self):
        move = self._noorix_entry('ledger-linked')
        payment = self.env['account.payment'].create({
            'amount': 1, 'payment_type': 'inbound', 'partner_type': 'customer',
            'partner_id': self.partner_a.id, 'journal_id': self.company_data['default_journal_bank'].id,
            'date': '2026-11-01',
        })
        move.origin_payment_id = payment
        with self.assertRaises(ValidationError):
            self._metrics(True)
        move.origin_payment_id = False
        reversal = move._reverse_moves([{'date': '2026-11-03'}], cancel=False)
        reversal.action_post()
        reversal.origin_payment_id = payment
        with self.assertRaises(ValidationError):
            self._metrics(True)

    def test_native_invoice_overlap_is_explicit_even_for_one_riyal(self):
        move = self._noorix_entry('invoice-scope-overlap', '2026-11-01', '115.00')
        row = self._noorix_row(move, 'invoice-scope-overlap')
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
        heat = self.env.ref('baseer_sales_heat_calendar.dashboard_sales_heat_calendar', raise_if_not_found=False)
        heat_off = heat.get_baseer_heat_calendar('2026-11') if heat else None
        # Distinct posted documents sharing a date are not the same sale.
        self.assertEqual(self._metrics(True)['cards']['sales']['value'], '116.00')
        if heat:
            day = next(day for week in heat.get_baseer_heat_calendar('2026-11', include_noorix=True)['weeks']
                       for day in week if day and day['day'] == 1)
            self.assertEqual(day['sales_value'], '116.00')
            self.assertIsNone(day['customers_value'])
        # Defense in depth: a move already consumed by the native reader must
        # never be accepted again, even if a future adapter mislabels it.
        duplicate = {'move': invoice, 'evidence': False, 'ledger_only': True,
                     'day': invoice.invoice_date, 'amount': Decimal('1.00'),
                     'original': True, 'scope': 'all', 'customer_count': None}
        with patch.object(type(self.dashboard), '_noorix_events', return_value=[duplicate]):
            with self.assertRaises(ValidationError):
                self._metrics(True)
        for scope in ('all', 'morning', 'evening'):
            with self.subTest(scope=scope):
                evidence = self.Evidence.browse(self.Evidence.import_evidence([dict(row, period_scope=scope)]))
                self.assertEqual(self._metrics(False)['cards']['sales']['value'], '1.00')
                with self.assertRaises(ValidationError):
                    self._metrics(True)
                if heat:
                    self.assertEqual(heat.get_baseer_heat_calendar('2026-11'), heat_off)
                    with self.assertRaises(ValidationError):
                        heat.get_baseer_heat_calendar('2026-11', include_noorix=True)
                evidence.unlink()

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

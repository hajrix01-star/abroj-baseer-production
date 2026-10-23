"""Proof-bound drill-down tests for the owner summary."""

from decimal import Decimal, localcontext
from hashlib import sha256

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from . import test_owner_cash


@tagged('post_install', '-at_install', 'operations_owner_details')
class TestOwnerDetails(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.operations.report']
        self.income = self.env['account.account'].with_company(self.company).create({
            'code': '959311', 'name': 'Owner detail sales income',
            'account_type': 'income', 'company_ids': [Command.set(self.company.ids)],
        })
        self.expense = self.env['account.account'].with_company(self.company).create({
            'code': '959312', 'name': 'Owner detail operating expense',
            'account_type': 'expense', 'company_ids': [Command.set(self.company.ids)],
        })
        self.bank = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.sale = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'sale'),
        ], limit=1)
        self.assertTrue(self.bank and self.bank.default_account_id and self.sale)
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Owner detail customer and supplier',
        })
        self.filters = {
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30', 'journal_ids': [],
        }

    def _invoice(self, amount='100.00', move_type='out_invoice'):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': move_type, 'journal_id': self.sale.id, 'partner_id': self.partner.id,
            'invoice_date': '2026-06-18',
            'invoice_line_ids': [Command.create({
                'name': 'Owner detail sale', 'quantity': 1, 'price_unit': amount,
                'account_id': self.income.id, 'tax_ids': [Command.clear()],
            })],
        })
        move.action_post()
        return move

    def _statement(self, amount='40.00'):
        return test_owner_cash.TestOwnerCash._statement(self, amount, self.expense, '2026-06-18')

    def _period(self):
        snapshot = self.report.get_owner_snapshot(self.filters)
        self.assertTrue(snapshot['complete'])
        return snapshot['periods'][0]

    def _details(self, row_key, period=None, **kwargs):
        period = period or self._period()
        return self.report.get_owner_details(
            self.filters, row_key, period['key'], period['revision'], **kwargs,
        )

    def test_real_invoice_and_posted_cash_details_keep_exact_contributions(self):
        invoice = self._invoice()
        statement = self._statement()
        period = self._period()

        sales = self._details('total:incoming_total', period)
        self.assertFalse(sales['changed'])
        self.assertEqual((sales['amount'], sales['total_count']), ('100.00', 1))
        self.assertEqual(sales['events'][0]['amount'], '100.00')
        self.assertNotIn('source_id', sales['events'][0])

        channel = self._details('channel:%s' % period['channels'][0]['key'], period)
        self.assertEqual((channel['amount'], channel['total_count']), ('100.00', 1))
        self.assertEqual(channel['events'][0]['amount'], '100.00')

        cash = self._details('total:cash_total', period)
        self.assertEqual((cash['amount'], cash['total_count']), ('40.00', 1))
        self.assertEqual(cash['events'][0]['amount'], '40.00')
        self.assertNotIn('source_id', cash['events'][0])

        difference = self._details('total:difference', period)
        self.assertEqual((difference['amount'], difference['total_count']), ('60.00', 2))
        self.assertEqual({row['amount'] for row in difference['events']}, {'100.00', '-40.00'})

    def test_pagination_stale_revision_and_source_action_are_proof_bound(self):
        for _index in range(51):
            self._invoice('1.00')
        period = self._period()
        first = self._details('total:incoming_total', period)
        second = self._details('total:incoming_total', period, page=2)
        self.assertEqual((first['page_size'], first['total_count'], len(first['events'])), (50, 51, 50))
        self.assertEqual((second['page'], len(second['events'])), (2, 1))

        action = self.report.action_owner_source(
            self.filters, 'total:incoming_total', period['key'], period['revision'], first['events'][0]['event_key'],
        )
        self.assertEqual(action['target'], 'new')
        self.assertFalse(action['context']['create'])
        self.assertFalse(action['context']['edit'])

        # Equal net change still changes the proved fact digest.
        self._invoice('10.00')
        self._invoice('10.00', move_type='out_refund')
        changed = self._details('total:incoming_total', period)
        self.assertEqual(changed, {
            'company_id': self.company.id, 'period_key': period['key'],
            'row_key': 'total:incoming_total',
            'revision': self._period()['revision'], 'changed': True,
        })
        self.assertTrue(self.report.action_owner_source(
            self.filters, 'total:incoming_total', period['key'], period['revision'], first['events'][0]['event_key'],
        )['changed'])

    def test_tampered_company_period_row_and_event_are_rejected(self):
        self._invoice()
        period = self._period()
        other = self.env['res.company'].create({'name': 'Owner detail foreign company'})
        with self.assertRaises(AccessError):
            self.report.get_owner_details(
                {**self.filters, 'company_id': other.id}, 'total:incoming_total',
                period['key'], period['revision'],
            )
        with self.assertRaises(ValidationError):
            self.report.get_owner_details(
                self.filters, 'total:incoming_total', 'other-period', period['revision'],
            )
        with self.assertRaises(ValidationError):
            self.report.get_owner_details(
                self.filters, 'channel:' + '0' * 20, period['key'], period['revision'],
            )
        with self.assertRaises(ValidationError):
            self.report.action_owner_source(
                self.filters, 'total:incoming_total', period['key'], period['revision'], '0' * 64,
            )

    def test_zero_and_partial_sale_rows_do_not_create_client_math(self):
        self._invoice('100.00')
        self._invoice('100.00', move_type='out_refund')
        self._statement('25.00')
        period = self._period()
        sales = self._details('total:incoming_total', period)
        difference = self._details('total:difference', period)
        self.assertEqual((sales['amount'], sales['negative'], sales['total_count']), ('0.00', False, 2))
        self.assertEqual((difference['amount'], difference['negative']), ('-25.00', True))

    def test_purchase_and_unclassified_keys_select_only_their_proven_bucket(self):
        purchase_key = 'purchase:11/12'
        hashed = sha256(purchase_key.encode()).hexdigest()[:20]
        event = {
            'source_model': 'account.move', 'source_id': 41,
            'line_model': 'account.move.line', 'line_id': 42,
            'payment_line_id': 43, 'date': '2026-06-18', 'amount': Decimal('7.25'),
            'classification': 'purchase', 'category_path': [(11, 'Root'), (12, 'Leaf')],
        }
        data = {
            'sales': [], 'cash': {'events': [event]},
            'summary': {'cash_total': Decimal('7.25'), 'outflow_buckets': [{
                'key': purchase_key, 'classification': 'purchase', 'amount': Decimal('7.25'),
            }]},
            'display': {'outflows': [{'key': 'purchase', 'label': 'Purchases', 'rows': [{
                'key': hashed, 'label': 'Root / Leaf', 'amount': '7.25', 'negative': False,
            }]}]},
        }
        label, amount, rows = self.report._owner_selected_events(
            data, 'outflow:purchase:%s' % hashed, ('outflow', 'purchase', hashed))
        self.assertEqual((label, amount, len(rows)), ('Root / Leaf', Decimal('7.25'), 1))

        unclassified = {**event, 'classification': 'unclassified', 'amount': Decimal('3.00')}
        data['cash'] = {'events': [unclassified]}
        data['summary'] = {'cash_total': Decimal('3.00'), 'outflow_buckets': [{
            'key': 'unclassified', 'amount': Decimal('3.00'),
        }]}
        data['display'] = {'outflows': [{'key': 'unclassified', 'label': 'Unclassified', 'rows': [{
            'key': sha256(b'unclassified').hexdigest()[:20], 'label': 'Unclassified',
            'amount': '3.00', 'negative': False,
        }]}]}
        label, amount, rows = self.report._owner_selected_events(
            data, 'outflow:unclassified', ('outflow', 'unclassified', None))
        self.assertEqual((label, amount, len(rows)), ('Unclassified', Decimal('3.00'), 1))

    def test_difference_keeps_decimal_precision_under_a_low_caller_context(self):
        sales = {'source_model': 'account.move', 'source_id': 51, 'line_model': 'account.move',
                 'line_id': 51, 'date': '2026-06-18', 'amount': Decimal('999999999999999999.98'),
                 'channels': [('unallocated', 'Unallocated', Decimal('999999999999999999.98'))]}
        cash = {'source_model': 'account.payment', 'source_id': 52, 'line_model': 'account.move.line',
                'line_id': 52, 'payment_line_id': 53, 'date': '2026-06-18', 'amount': Decimal('0.01'),
                'classification': 'unclassified'}
        expected = Decimal('999999999999999999.97')
        data = {
            'sales': [sales], 'cash': {'events': [cash]},
            'summary': {'difference': expected},
            'display': {'totals': [{'key': 'difference', 'label': 'Difference'}]},
        }
        with localcontext() as context:
            context.prec = 4
            _label, amount, rows = self.report._owner_selected_events(
                data, 'total:difference', ('total', 'difference'))
        self.assertEqual((amount, [row['amount'] for row in rows]),
                         (expected, [Decimal('-0.01'), Decimal('999999999999999999.98')]))

    def test_channel_uses_its_partial_allocation_not_the_sales_header(self):
        raw_key = 'payment_77'
        event = {'source_model': 'pos.order', 'source_id': 61, 'line_model': 'pos.order',
                 'line_id': 61, 'date': '2026-06-18', 'amount': Decimal('100.00'),
                 'channels': [(raw_key, 'Cash', Decimal('40.00')), ('payment_78', 'Card', Decimal('60.00'))]}
        digest = sha256(raw_key.encode()).hexdigest()[:20]
        data = {
            'sales': [event], 'cash': {'events': []},
            'summary': {'channels': [{'key': raw_key, 'name': 'Cash', 'amount': Decimal('40.00')}]},
            'display': {'channels': [{'key': digest, 'label': 'Cash', 'amount': '40.00', 'negative': False}]},
        }
        label, amount, rows = self.report._owner_selected_events(
            data, 'channel:%s' % digest, ('channel', digest))
        self.assertEqual((label, amount, rows[0]['amount']), ('Cash', Decimal('40.00'), Decimal('40.00')))

    def test_hidden_source_rule_denies_action_after_a_snapshot_was_visible(self):
        self._invoice()
        period = self._period()
        event_key = self._details('total:incoming_total', period)['events'][0]['event_key']
        reader = self.env['res.users'].create({
            'name': 'Owner detail restricted reader', 'login': 'owner_detail_restricted_reader',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        self.env['ir.rule'].create({
            'name': 'Hide owner detail invoice source',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': "[('id', '=', 0)]",
            'perm_read': True,
        })
        with self.assertRaises(AccessError):
            self.report.with_user(reader).action_owner_source(
                self.filters, 'total:incoming_total', period['key'], period['revision'], event_key,
            )

"""Native POS tax preparation stays local, fresh and batch-equivalent."""

from collections import Counter
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS

from . import test_read_batches


@tagged('post_install', '-at_install', 'operations_native_preparation')
class TestOperationsNativePreparation(TransactionCase):
    """Compose fixtures only; do not inherit another class's test suite."""

    _account = test_read_batches.TestOperationsReadBatches._account
    _journal = test_read_batches.TestOperationsReadBatches._journal
    _tax = test_read_batches.TestOperationsReadBatches._tax
    _empty_native_reader = test_read_batches.TestOperationsReadBatches._empty_native_reader
    _empty_native_pos_order = test_read_batches.TestOperationsReadBatches._empty_native_pos_order
    _native_global_rounding_order = test_read_batches.TestOperationsReadBatches._native_global_rounding_order
    _empty_order_payment = test_read_batches.TestOperationsReadBatches._empty_order_payment
    _order = test_read_batches.TestOperationsReadBatches._order
    _mixed_orders = test_read_batches.TestOperationsReadBatches._mixed_orders
    _amounts = test_read_batches.TestOperationsReadBatches._amounts

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
        self.company.tax_calculation_rounding_method = 'round_globally'
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('954101', 'asset_receivable', True)
        self.payable = self._account('954102', 'liability_payable', True)
        self.income = self._account('954103', 'income')
        self.other_income = self._account('954104', 'income_other')
        self.tax_account = self._account('954105', 'liability_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Native preparation synthetic partner',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'NPR')
        self.tax = self._tax('sale', self.tax_account)
        self.tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).account_id = self.tax_account

    def _sections(self, orders, report=None):
        selected = self.report if report is None else report
        sections = {key: {} for key in SECTION_KEYS}
        excluded = Counter()
        selected._pos_amounts(selected.env['pos.order'].browse(orders.ids), self.company,
                              sections, excluded)
        return sections, excluded

    def _tracked_preparation(self):
        """Return a patch that records every source line prepared by native Odoo."""
        line_model = type(self.env['pos.order.line'])
        original = line_model._prepare_tax_base_line_values
        prepared = Counter()

        def tracked(lines, *args, **kwargs):
            bases = original(lines, *args, **kwargs)
            for base in bases:
                prepared[base['record'].id] += 1
            return bases

        return prepared, patch.object(line_model, '_prepare_tax_base_line_values', new=tracked)

    def test_native_batch_prepares_each_line_once_and_matches_singleton_reference(self):
        orders = self._mixed_orders()
        expected_lines = set(orders.lines.ids)
        original_batch = self.report._native_global_pos_amounts_batch
        batch_calls = []

        def observed_batch(report, order_bases, company):
            batch_calls.append([
                (order.id, tuple(lines.ids), tuple(base['record'].id for base in bases))
                for order, lines, bases in order_bases
            ])
            return original_batch(order_bases, company)

        prepared, preparation_patch = self._tracked_preparation()
        with preparation_patch, patch.object(
                type(self.report), '_native_global_pos_amounts_batch', new=observed_batch):
            batched, batched_excluded = self._sections(orders)

        self.assertEqual(prepared, Counter({line_id: 1 for line_id in expected_lines}))
        self.assertEqual(len(batch_calls), 1)
        self.assertEqual({order_id for order_id, _lines, _bases in batch_calls[0]}, set(orders.ids))
        for _order_id, lines, base_lines in batch_calls[0]:
            self.assertEqual(set(lines), set(base_lines))

        # Reference the former per-order boundary without regenerating bases:
        # each singleton uses the unchanged native batch helper on its own order.
        def singleton_reference(_report, order_bases, company):
            result = {}
            for order, lines, bases in order_bases:
                result.update(original_batch([(order, lines, bases)], company))
            return result

        prepared, preparation_patch = self._tracked_preparation()
        with preparation_patch, patch.object(
                type(self.report), '_native_global_pos_amounts_batch', new=singleton_reference):
            reference, reference_excluded = self._sections(orders)
        self.assertEqual(prepared, Counter({line_id: 1 for line_id in expected_lines}))
        self.assertEqual(reference, batched)
        self.assertEqual(reference_excluded, batched_excluded)

    def test_native_preparation_is_fresh_between_calls(self):
        orders = self._mixed_orders()
        regular = orders[-1]
        line = regular.lines
        expected_lines = set(orders.lines.ids)
        prepared, preparation_patch = self._tracked_preparation()

        with preparation_patch:
            original, original_excluded = self._sections(orders)
            line.write({
                'price_unit': 200, 'price_subtotal': 200, 'price_subtotal_incl': 230,
            })
            regular.write({'amount_total': 230, 'amount_tax': 30, 'amount_paid': 230})
            regular.payment_ids.amount = 230
            changed, changed_excluded = self._sections(orders)

        self.assertEqual(prepared, Counter({line_id: 2 for line_id in expected_lines}))
        self.assertNotEqual(changed, original)
        self.assertNotEqual(changed_excluded, Counter())
        self.assertEqual(changed_excluded, original_excluded)
        self.assertEqual(changed['income'][self.income.id]['raw'], Decimal('230.09'))

    def test_native_bases_are_never_reused_across_contexts(self):
        orders = self._mixed_orders()
        expected_lines = set(orders.lines.ids)
        injected = self.report.with_context(
            baseer_operations_batch_verified=True,
            baseer_operations_pos_lines_by_order={str(order.id): [] for order in orders},
            baseer_operations_read_batch=orders.ids,
        )
        prepared, preparation_patch = self._tracked_preparation()
        with preparation_patch:
            normal, normal_excluded = self._sections(orders)
            contextual, contextual_excluded = self._sections(orders, report=injected)

        self.assertEqual(prepared, Counter({line_id: 2 for line_id in expected_lines}))
        self.assertEqual(contextual, normal)
        self.assertEqual(contextual_excluded, normal_excluded)

    def test_native_batch_rechecks_mapped_tax_and_account_visibility(self):
        orders = self._mixed_orders()
        _rounded, mapped_order = orders
        mapped_order.lines.product_id.property_account_income_id = self.other_income
        mapped_tax = self.tax.copy({
            'name': 'Native preparation mapped VAT',
            'original_tax_ids': [Command.set(self.tax.ids)],
        })
        fiscal_position = self.env['account.fiscal.position'].with_company(self.company).create({
            'name': 'Native preparation mapped tax', 'company_id': self.company.id,
            'tax_ids': [Command.set(mapped_tax.ids)],
        })
        mapped_order.fiscal_position_id = fiscal_position
        expected, expected_excluded = self._sections(orders)
        secured = self._empty_native_reader()
        actual, actual_excluded = self._sections(orders, report=secured)
        self.assertEqual(actual, expected)
        self.assertEqual(actual_excluded, expected_excluded)

        for model, hidden in (
                ('account.account', self.other_income),
                ('account.tax', mapped_tax),
        ):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide native preparation source %s' % model,
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': "[('id', '!=', %s)]" % hidden.id,
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', hidden.id)]))
                    with self.assertRaises(AccessError):
                        self._sections(orders, report=secured)
                finally:
                    rule.unlink()

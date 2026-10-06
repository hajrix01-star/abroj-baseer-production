from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval, time

from ..models.tobacco_report import (
    BaseerPosTobaccoReport, TobaccoReportTooLarge, _format_money, _western,
)


class FakeAccount:
    def __init__(self, code):
        self.code = code

    def with_company(self, company):
        return self


class FakeTaxModel:
    def __init__(self, order_total):
        self.order_total = order_total

    def _get_tax_totals_summary(self, **kwargs):
        return {'total_amount_currency': self.order_total}


class FakeProduct:
    def __init__(self, display_name, name=None):
        self.display_name = display_name
        self.name = name or display_name

    def with_context(self, **kwargs):
        return SimpleNamespace(display_name=self.name)


@tagged('post_install', '-at_install')
class TestTobaccoReport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.report = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees']

    def test_print_button_is_visible_in_full_page_wizard(self):
        action = self.env.ref('baseer_pos_tobacco_report.action_pos_tobacco_report_wizard')
        view = self.env.ref('baseer_pos_tobacco_report.view_pos_tobacco_report_wizard_form')
        arch = etree.fromstring(view.arch_db.encode())

        self.assertEqual(action.target, 'current')
        self.assertEqual(
            len(arch.xpath("./header/button[@name='action_print_monthly'][@type='object']")),
            1,
        )
        self.assertTrue(arch.xpath("./sheet/field[@name='preview_html']"))
        self.assertTrue(arch.xpath("./sheet/group/field[@name='show_products']"))
        self.assertNotIn('Operational report, not an accounting ledger.', view.arch_db)
        self.assertFalse(arch.xpath('./footer/button'))

    def test_product_column_is_optional_in_preview_and_pdf(self):
        user = self.env.ref('base.user_admin')
        wizard = self.env['baseer.pos.tobacco.report.wizard'].with_user(user).new({
            'company_id': user.company_id.id, 'month': '9', 'year': 2026,
        })
        source = self.report.with_user(user)._build_report(wizard)
        self.assertFalse(source['show_products'])
        sample = dict(
            date='01-09-2026 00:00', order='ORDER-1', products='Visible Shisha × 1',
            type='Sale', debit='0.00', credit='25.00', running='25.00',
        )
        source.update(rows=[sample], order_count='1')
        with patch.object(BaseerPosTobaccoReport, '_build_report',
                          side_effect=lambda record: dict(source, show_products=record.show_products)):
            wizard._compute_preview()
            self.assertNotIn('Visible Shisha', str(wizard.preview_html))
            wizard.show_products = True
            wizard._compute_preview()
            self.assertIn('Visible Shisha', str(wizard.preview_html))

        template = self.env.ref('baseer_pos_tobacco_report.report_pos_tobacco_fees')
        pdf_arch = etree.fromstring(template.arch_db.encode())
        self.assertTrue(pdf_arch.xpath(".//th[@t-if=\"report_data['show_products']\"]"))
        self.assertFalse(pdf_arch.xpath(".//div[contains(@class, 'btf-note')]"))
        self.assertEqual(len(pdf_arch.xpath(".//*[@t-call='web.basic_layout']")), 1)
        self.assertFalse(pdf_arch.xpath(".//div[contains(@class, 'btf-brand')]"))
        self.assertEqual(len(pdf_arch.xpath(".//img[@alt='Company logo']")), 1)
        self.assertEqual(len(pdf_arch.xpath(".//th[@class='btf-number']")), 5)
        self.assertEqual(len(pdf_arch.xpath(".//th[@class='btf-id']")), 4)

    def test_month_selection_uses_full_riyadh_month(self):
        wizard = self.env['baseer.pos.tobacco.report.wizard'].new({
            'month': '2', 'year': 2028,
        })
        self.assertEqual(wizard._month_range(), (date(2028, 2, 1), date(2028, 2, 29)))
        wizard.year = 2101
        with self.assertRaises(ValidationError):
            wizard._month_range()

    def test_monthly_pdf_uses_the_selected_full_month(self):
        user = self.env.ref('base.user_admin')
        wizard = self.env['baseer.pos.tobacco.report.wizard'].with_user(user).create({
            'company_id': user.company_id.id,
            'month': '2', 'year': 2028,
        })
        action = wizard.action_print_monthly()
        self.assertEqual((wizard.date_from, wizard.date_to), (date(2028, 2, 1), date(2028, 2, 29)))
        self.assertEqual(action['type'], 'ir.actions.report')

    def test_monthly_pdf_uses_selected_month_in_filename_and_a4_layout(self):
        report = self.env.ref('baseer_pos_tobacco_report.action_report_pos_tobacco_fees')
        paperformat = self.env.ref('baseer_pos_tobacco_report.paperformat_pos_tobacco_fees')
        user = self.env.ref('base.user_admin')
        wizard = self.env['baseer.pos.tobacco.report.wizard'].with_user(user).create({
            'company_id': user.company_id.id,
            'month': '8', 'year': 2026,
        })
        wizard.action_print_monthly()

        self.assertEqual(
            safe_eval(report.print_report_name, {'object': wizard, 'time': time}),
            'رسوم التبغ لـ 8-2026',
        )
        self.assertEqual(
            safe_eval(
                report.with_context(lang='ar_001').print_report_name,
                {'object': wizard, 'time': time},
            ),
            'رسوم التبغ لـ 8-2026',
        )
        custom_wizard = self.env['baseer.pos.tobacco.report.wizard'].with_user(user).create({
            'company_id': user.company_id.id,
            'month': '8', 'year': 2026,
            'date_from': date(2026, 8, 3),
            'date_to': date(2026, 8, 19),
        })
        self.assertEqual(
            safe_eval(report.print_report_name, {'object': custom_wizard, 'time': time}),
            'رسوم التبغ من 03-08-2026 إلى 19-08-2026',
        )
        self.assertEqual(paperformat.format, 'A4')
        self.assertEqual(paperformat.orientation, 'Portrait')
        self.assertEqual((paperformat.margin_top, paperformat.margin_right,
                          paperformat.margin_bottom, paperformat.margin_left),
                         (14, 10, 20, 10))
        template = self.env.ref('baseer_pos_tobacco_report.report_pos_tobacco_fees')
        self.assertIn('@page {size: A4 portrait;', template.arch_db)

    def test_monthly_preview_is_paged_without_losing_month_total(self):
        user = self.env.ref('base.user_admin')
        wizard = self.env['baseer.pos.tobacco.report.wizard'].with_user(user).new({
            'company_id': user.company_id.id,
            'month': '9', 'year': 2026, 'preview_page': 1,
        })
        source = self.report.with_user(user)._build_report(
            self.env['baseer.pos.tobacco.report.wizard'].with_user(user).new({
                'company_id': user.company_id.id,
                'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 30),
            }),
        )
        rows = [dict(
            date='01-09-2026 00:00', order=f'ORDER-{index:03d}', products='Shisha × 1',
            type='Sale', debit='0.00', credit='1.00', running=f'{index}.00',
        ) for index in range(1, 102)]
        data = dict(source, rows=rows, order_count='101', closing='101.00')
        with patch.object(BaseerPosTobaccoReport, '_build_report', return_value=data):
            wizard._compute_preview()
            first_page = str(wizard.preview_html)
            self.assertEqual((wizard.preview_total_rows, wizard.preview_total_pages), (101, 2))
            self.assertIn('ORDER-001', first_page)
            self.assertIn('101.00', first_page)
            self.assertNotIn('ORDER-101', first_page)
            wizard.preview_page = 2
            wizard._compute_preview()
            self.assertIn('ORDER-101', str(wizard.preview_html))
            self.assertNotIn('ORDER-001', str(wizard.preview_html))

    def test_oversized_month_shows_split_action(self):
        user = self.env.ref('base.user_admin')
        wizard = self.env['baseer.pos.tobacco.report.wizard'].with_user(user).create({
            'company_id': user.company_id.id, 'month': '9', 'year': 2026,
        })
        with patch.object(BaseerPosTobaccoReport, '_build_report',
                          side_effect=TobaccoReportTooLarge('too many')):
            wizard._compute_preview()
        self.assertTrue(wizard.preview_overflow)
        self.assertFalse(wizard.preview_html)
        action = wizard.action_open_custom_range()
        self.assertEqual(action['res_model'], wizard._name)
        self.assertEqual(action['context']['default_date_from'], '2026-09-01')
        self.assertEqual(action['context']['default_date_to'], '2026-09-30')

    def test_riyadh_period_includes_both_full_days(self):
        wizard = self.env['baseer.pos.tobacco.report.wizard'].create({
            'company_id': self.env.company.id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })
        self.assertEqual(
            self.report._date_bounds_utc(wizard),
            (datetime(2026, 8, 31, 21), datetime(2026, 9, 30, 21)),
        )
        wizard.date_to = date(2027, 9, 3)
        with self.assertRaises(ValidationError):
            wizard._check_period()

    def _fee_case(self, rep_amounts, order_total, saved_total, refund=False):
        if not isinstance(rep_amounts, (list, tuple)):
            rep_amounts = [rep_amounts]
        tobacco = FakeAccount('201021')
        vat = FakeAccount('VAT')
        base_lines = []
        for rep_amount in rep_amounts:
            line = SimpleNamespace(
                qty=1.0,
                product_id=FakeProduct('Shisha'),
            )
            base_lines.append({
                'record': line,
                'tax_details': {'taxes_data': [
                    {'tax_reps_data': [
                        {'account': tobacco, 'tax_amount_currency': rep_amount},
                        {'account': vat, 'tax_amount_currency': 28.70},
                    ]},
                ]},
            })
        order = SimpleNamespace(
            is_refund=refund,
            amount_total=saved_total,
            company_id=self.env.company,
            config_id=SimpleNamespace(cash_rounding=False),
            currency_id=self.env.company.currency_id,
        )
        with patch.object(BaseerPosTobaccoReport, '_order_tax_base_lines',
                          return_value=(FakeTaxModel(order_total), base_lines)):
            return self.report._order_fee_data(order, Decimal('0.01'))

    def test_tobacco_excludes_vat_and_refund_sign_is_applied_once(self):
        sale = self._fee_case(100.0, 220.0, 220.0)
        refund = self._fee_case(100.0, 220.0, -220.0, refund=True)
        negative_line = self._fee_case(-95.65, 100.0, 100.0)
        self.assertEqual(sale[0][0][1], Decimal('100.00'))
        self.assertEqual(refund[0][0][1], Decimal('-100.00'))
        self.assertEqual(negative_line[0][0][1], Decimal('-95.65'))
        self.assertFalse(any(case[1] for case in (sale, refund, negative_line)))

    def test_unassigned_tax_repartition_is_ignored(self):
        line = SimpleNamespace(qty=1, product_id=FakeProduct('Shisha'))
        order = SimpleNamespace(
            is_refund=False, amount_total=220.0, company_id=self.env.company,
            config_id=SimpleNamespace(cash_rounding=False),
            currency_id=self.env.company.currency_id,
        )
        base_lines = [{'record': line, 'tax_details': {'taxes_data': [
            {'tax_reps_data': [
                {'account': False, 'tax_amount_currency': 28.70},
                {'account': FakeAccount('201021'), 'tax_amount_currency': 100.0},
            ]},
        ]}}]
        with patch.object(BaseerPosTobaccoReport, '_order_tax_base_lines',
                          return_value=(FakeTaxModel(220.0), base_lines)):
            fee_lines, mismatch, _, _ = self.report._order_fee_data(
                order, Decimal('0.01'),
            )
        self.assertEqual(fee_lines, [(line, Decimal('100.00'))])
        self.assertFalse(mismatch)

    def test_mixed_order_keeps_debit_and_credit_lines_separate(self):
        fee_lines, mismatch, _, _ = self._fee_case(
            [100.0, -25.0], 100.0, 100.0,
        )
        self.assertEqual([amount for _, amount in fee_lines], [
            Decimal('100.00'), Decimal('-25.00'),
        ])
        self.assertFalse(mismatch)

    def test_pdf_rows_keep_mixed_directions_and_zero_fee_exception(self):
        currency = self.env.company.currency_id
        order = SimpleNamespace(
            name='١٢', date_order=datetime(2026, 9, 1, 0), currency_id=currency,
        )
        sale = SimpleNamespace(qty=4, product_id=FakeProduct('[ARZ-PRD-026-65] شيشة ٥٥', 'شيشة ٥٥'))
        refund = SimpleNamespace(qty=-1, product_id=FakeProduct('[ARZ-PRD-026-65] شيشة ٥٥', 'شيشة ٥٥'))
        with patch.object(BaseerPosTobaccoReport, '_order_fee_data', return_value=(
            [(sale, Decimal('100.00')), (refund, Decimal('-25.00'))],
            False, Decimal('220.00'), Decimal('220.00'),
        )):
            rows, exceptions, debit, credit, running = self.report._collect_rows(
                [order], currency, Decimal('0.01'),
            )
        self.assertEqual([row['debit'] for row in rows], ['0.00', '25.00'])
        self.assertEqual([row['credit'] for row in rows], ['100.00', '0.00'])
        self.assertEqual([row['running'] for row in rows], ['100.00', '75.00'])
        self.assertIn('55', rows[0]['products'])
        self.assertNotIn('ARZ-PRD-026-65', rows[0]['products'])
        self.assertEqual((debit, credit, running), (
            Decimal('25.00'), Decimal('100.00'), Decimal('75.00'),
        ))
        self.assertFalse(exceptions)
        with patch.object(BaseerPosTobaccoReport, '_order_fee_data', return_value=(
            [], True, Decimal('220.00'), Decimal('219.99'),
        )):
            rows, exceptions, _, _, _ = self.report._collect_rows(
                [order], currency, Decimal('0.01'),
            )
        self.assertFalse(rows)
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0]['order'], '12')

    def test_drift_is_disclosed_not_silently_reconciled(self):
        fee_lines, mismatch, computed, saved = self._fee_case(
            100.0, 220.0, 219.99,
        )
        self.assertEqual(fee_lines[0][1], Decimal('100.00'))
        self.assertTrue(mismatch)
        self.assertEqual(computed, Decimal('220.0'))
        self.assertEqual(saved, Decimal('219.99'))

    def test_western_digits_and_two_decimal_currency(self):
        self.assertEqual(_western('١٢۳٤'), '1234')
        self.assertEqual(_format_money(Decimal('3554.6')), '3,554.60')

    def _qa_tobacco_line(self):
        line = self.env['pos.order.line'].search([
            ('product_id.default_code', '=', 'ARZ-PRD-026-55'),
            ('order_id.source', '=', 'pos'),
            ('order_id.state', 'in', ('paid', 'done')),
            ('order_id.company_id', '=', self.env.company.id),
        ], limit=1)
        if not line:
            self.skipTest('The QA tobacco POS fixture is unavailable in this database')
        return line

    def _real_order(self, quantities):
        source = self._qa_tobacco_line()
        vals = []
        for qty in quantities:
            vals.append(Command.create({
                'product_id': source.product_id.id,
                'tax_ids': [Command.set(source.tax_ids.ids)],
                'uuid': str(uuid4()),
                'qty': qty,
                'price_unit': source.price_unit,
                'price_subtotal': source.price_subtotal / source.qty * qty,
                'price_subtotal_incl': source.price_subtotal_incl / source.qty * qty,
                'full_product_name': source.full_product_name or source.product_id.display_name,
            }))
        order = self.env['pos.order'].create({
            'company_id': source.order_id.company_id.id,
            'session_id': source.order_id.session_id.id,
            'source': 'pos',
            'is_refund': all(qty < 0 for qty in quantities),
            'amount_tax': 0,
            'amount_total': 0,
            'amount_paid': 0,
            'amount_return': 0,
            'lines': vals,
        })
        order._compute_prices()
        return order

    def test_real_pos_tax_pipeline_and_global_rounding(self):
        order = self._real_order([4])
        fee_lines, mismatch, _, _ = self.report._order_fee_data(order, Decimal('0.01'))
        self.assertEqual(fee_lines[0][1], Decimal('100.00'))
        self.assertFalse(mismatch)
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        global_lines, _, _, _ = self.report._order_fee_data(order, Decimal('0.01'))
        self.assertEqual(global_lines[0][1], Decimal('100.00'))

    def test_real_pos_mixed_order_and_refund_order_keep_signs(self):
        mixed = self._real_order([4, -1])
        mixed_lines, _, _, _ = self.report._order_fee_data(mixed, Decimal('0.01'))
        self.assertEqual(len(mixed_lines), 2)
        self.assertGreater(mixed_lines[0][1], 0)
        self.assertLess(mixed_lines[1][1], 0)
        refund = self._real_order([-4])
        refund_lines, mismatch, _, _ = self.report._order_fee_data(refund, Decimal('0.01'))
        self.assertEqual(refund_lines[0][1], Decimal('-100.00'))
        self.assertFalse(mismatch)

    def test_real_pos_pipeline_honours_manual_tax_amount(self):
        order = self._real_order([4])
        line = order.lines
        original_lines, _, _, _ = self.report._order_fee_data(order, Decimal('0.01'))
        original_fee = next(amount for candidate, amount in original_lines if candidate == line)
        base_line = line._prepare_base_line_for_taxes_computation()
        sorted_taxes = base_line['tax_ids']._flatten_taxes_and_sort_them()[0]
        tobacco_tax = next(
            tax for tax in sorted_taxes
            if any(rep.account_id.with_company(order.company_id).code == '201021'
                   for rep in tax.invoice_repartition_line_ids if rep.repartition_type == 'tax')
        )
        manual = {str(tax.id): {} for tax in sorted_taxes}
        manual[str(tobacco_tax.id)] = {
            'tax_amount_currency': float(original_fee + Decimal('1.00')),
        }
        line.write({'extra_tax_data': {
            'currency_id': base_line['currency_id'].id,
            'price_unit': base_line['price_unit'],
            'discount': base_line['discount'],
            'quantity': base_line['quantity'],
            'rate': base_line['rate'],
            'manual_tax_amounts': manual,
        }})
        changed_lines, _, _, _ = self.report._order_fee_data(order, Decimal('0.01'))
        changed_fee = next(amount for candidate, amount in changed_lines if candidate == line)
        self.assertEqual(changed_fee, original_fee + Decimal('1.00'))

    def test_report_rejects_account_only_user(self):
        account_group = self.env.ref('account.group_account_readonly')
        user = self.env['res.users'].create({
            'name': 'Tobacco report account-only test',
            'login': 'tobacco-account-only-test',
            'group_ids': [Command.set((account_group | self.env.ref('base.group_user')).ids)],
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
        })
        wizard = self.env['baseer.pos.tobacco.report.wizard'].create({
            'company_id': self.env.company.id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })
        with self.assertRaises(AccessError):
            wizard.with_user(user)._check_report_access()
        monthly = self.env['baseer.pos.tobacco.report.wizard'].with_user(user).new({
            'company_id': self.env.company.id, 'month': '9', 'year': 2026,
        })
        with self.assertRaises(AccessError):
            monthly.preview_html

    def test_report_requires_allowed_company_even_with_both_groups(self):
        other_company = self.env['res.company'].search([
            ('id', '!=', self.env.company.id),
        ], limit=1)
        if not other_company:
            self.skipTest('Multi-company QA fixture is unavailable')
        groups = (
            self.env.ref('base.group_user')
            | self.env.ref('account.group_account_readonly')
            | self.env.ref('point_of_sale.group_pos_user')
        )
        user = self.env['res.users'].create({
            'name': 'Tobacco report scoped test',
            'login': 'tobacco-scoped-test',
            'group_ids': [Command.set(groups.ids)],
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
        })
        allowed = self.env['baseer.pos.tobacco.report.wizard'].create({
            'company_id': self.env.company.id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })
        allowed.with_user(user)._check_report_access()
        forbidden = allowed.copy({'company_id': other_company.id})
        with self.assertRaises(AccessError):
            forbidden.with_user(user)._check_report_access()

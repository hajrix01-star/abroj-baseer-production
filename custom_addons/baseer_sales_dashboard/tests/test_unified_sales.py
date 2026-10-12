"""Actual native Sales/POS invoicing in the isolated transaction-test database."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged


@tagged('post_install', '-at_install')
class TestUnifiedSales(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sar = cls.env.ref('base.SAR')
        sar.active = True
        cls.company = cls.env.company
        cls.company.currency_id = sar
        cls.env.user.group_ids |= (
            cls.env.ref('point_of_sale.group_pos_manager')
            | cls.env.ref('sales_team.group_sale_manager')
        )
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_sales_summary')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Unified actual customer',
            'property_account_receivable_id': cls.company_data['default_account_receivable'].id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Unified service', 'type': 'service', 'invoice_policy': 'order',
            'available_in_pos': True, 'list_price': 100,
            'taxes_id': [Command.clear()],
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
        })
        cls.unified_deposit_product = cls.env['product.product'].create({
            'name': 'Unified deposit', 'type': 'service', 'available_in_pos': True,
            'invoice_policy': 'order', 'taxes_id': [Command.clear()],
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
        })
        cls.method = cls.env['pos.payment.method'].create({
            'name': 'Unified bank', 'company_id': cls.company.id,
            'journal_id': cls.company_data['default_journal_bank'].id,
            'receivable_account_id': cls.company_data['default_account_receivable'].id,
            'outstanding_account_id': cls.company_data['default_account_receivable'].id,
        })
        cls.config = cls.env['pos.config'].create({
            'name': 'Unified ordinary POS', 'company_id': cls.company.id,
            'journal_id': cls.company_data['default_journal_sale'].id,
            'invoice_journal_id': cls.company_data['default_journal_sale'].id,
            'payment_method_ids': [Command.set(cls.method.ids)],
            'down_payment_product_id': cls.unified_deposit_product.id,
        })
        cls.config.open_ui()
        cls.session = cls.config.current_session_id
        cls.session.set_opening_control(0, 'Unified native fixture')
        cls.session.start_at = datetime(2026, 10, 1, 15)

    def _sale(self, pricelist=None):
        values = {
            'partner_id': self.partner.id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': 1,
                'price_unit': 100, 'tax_ids': [Command.clear()],
            })],
        }
        if pricelist is not None:
            values['pricelist_id'] = pricelist.id
        sale = self.env['sale.order'].create(values)
        sale.action_confirm()
        return sale

    def _invoice(self, sale, date='2026-10-02', final=False):
        invoice = sale._create_invoices(final=final)
        invoice.invoice_date = date
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')
        return invoice

    def _pos(self, sale=None, quantity=1, price=100, deposit=False, invoice=False, session=None):
        session = session if session is not None else self.session
        product = self.unified_deposit_product if deposit else self.product
        self.assertTrue(product.exists(), 'Native POS line product must exist')
        line_values = {
            'product_id': product.id, 'uuid': str(uuid4()), 'qty': quantity,
            'price_unit': price, 'price_subtotal': quantity * price,
            'price_subtotal_incl': quantity * price,
            'tax_ids': [Command.clear()], 'full_product_name': product.name,
        }
        if sale:
            line_values['sale_order_origin_id'] = sale.id
            if not deposit:
                line_values['sale_order_line_id'] = sale.order_line.filtered(
                    lambda line: not line.display_type and not line.is_downpayment,
                ).id
        payload = {
            'uuid': str(uuid4()), 'session_id': session.id,
            'company_id': self.company.id, 'partner_id': self.partner.id,
            'date_order': '2026-10-02 00:00:00', 'source': 'pos',
            'state': 'paid', 'to_invoice': invoice,
            'amount_total': price * quantity, 'amount_tax': 0,
            'amount_paid': price * quantity, 'amount_return': 0,
            'lines': [Command.create(line_values)],
            'payment_ids': [Command.create({
                'payment_method_id': self.method.id, 'amount': price * quantity,
                'payment_date': '2026-10-02 00:00:00',
            })],
        }
        order = self.env['pos.order'].browse(
            self.env['pos.order']._process_order(payload, False),
        )
        self.assertIn(order.state, ('paid', 'done'))
        if deposit:
            # Same native server helper chain called by pos_sale.sync_from_ui.
            # No manual sale downpayment line or residual amount is invented.
            base_lines = order.lines._prepare_tax_base_line_values()
            taxes = self.env['account.tax']
            taxes._add_tax_details_in_base_lines(base_lines, self.company)
            taxes._round_base_lines_tax_details(base_lines, self.company)
            sale._create_down_payment_section_line_if_needed()
            sale._create_down_payment_lines_from_base_lines(base_lines)
        return order

    def _metrics(self, first='2026-10-01', last='2026-10-31', dashboard=None):
        return (dashboard if dashboard is not None else self.dashboard).get_baseer_sales_metrics({
            'preset': 'custom', 'date_from': first, 'date_to': last,
        })

    def _assert_sales(self, expected, **kwargs):
        result = self._metrics(**kwargs)
        self.assertEqual(Decimal(result['cards']['sales']['value']), Decimal(str(expected)))
        self.assertEqual(sum(Decimal(row['sales']['value'])
                             for row in result['source_breakdown']), Decimal(str(expected)))
        return result

    def test_confirmed_sale_counts_only_posted_native_invoice_and_credit_note(self):
        sale = self._sale()
        self.assertFalse(self._metrics()['has_data'])
        invoice = self._invoice(sale)
        self.assertEqual(invoice.amount_total, 100)
        for term in self.dashboard._baseer_unified_invoice_domain(self.company):
            if isinstance(term, tuple) and not term[0].startswith('reversed_entry_id.'):
                with self.subTest(native_invoice_domain_term=term):
                    self.assertIn(invoice, self.env['account.move'].search([
                        ('id', '=', invoice.id), term,
                    ]))
        self.assertIn(invoice, self.env['account.move'].search([
            ('id', '=', invoice.id),
        ] + self.dashboard._baseer_unified_invoice_domain(self.company)))
        self._assert_sales(100)
        refund = invoice._reverse_moves([{
            'date': '2026-10-03', 'invoice_date': '2026-10-03',
        }], cancel=False)
        refund.action_post()
        self.assertEqual(refund.amount_total_signed, -100)
        self._assert_sales(0)
        restored = refund._reverse_moves([{
            'date': '2026-10-04', 'invoice_date': '2026-10-04',
        }], cancel=False)
        restored.action_post()
        self.assertTrue(restored.invoice_line_ids.sale_line_ids)
        self._assert_sales(100)

    def test_native_partial_pos_and_remaining_sales_invoice_total_once(self):
        sale = self._sale()
        pos = self._pos(sale, quantity=.4)
        self.assertEqual(pos.amount_total, 40)
        self.assertAlmostEqual(sale.order_line.qty_invoiced, .4)
        invoice = self._invoice(sale)
        self.assertEqual(invoice.amount_total, 60)
        self._assert_sales(100)
        self.assertEqual(pos.amount_total + invoice.amount_total, sale.amount_total)

    def test_native_pos_deposit_and_final_sales_invoice_total_once(self):
        sale = self._sale()
        pos = self._pos(sale, price=20, deposit=True)
        self.assertEqual(pos.amount_total, 20)
        self.assertTrue(sale.order_line.filtered('is_downpayment'))
        invoice = self._invoice(sale, final=True)
        self.assertEqual(invoice.amount_total, 80)
        self._assert_sales(100)

    def test_native_pos_customer_invoice_is_not_an_extra_sales_source(self):
        sale = self._sale()
        order = self._pos(sale, invoice=True)
        self.assertTrue(order.account_move)
        self.assertEqual(order.account_move.state, 'posted')
        # Native pos_sale deliberately leaves invoice sale_line_ids empty;
        # SO settlement is represented by the original POS order line links.
        self.assertFalse(order.account_move.invoice_line_ids.sale_line_ids)
        self.assertEqual(order.lines.sale_order_origin_id, sale)
        self._assert_sales(100)
        credit = order.account_move._reverse_moves([{
            'date': '2026-10-03', 'invoice_date': '2026-10-03',
        }], cancel=False)
        credit.action_post()
        self.assertFalse(credit.invoice_line_ids.sale_line_ids)
        self.assertEqual(credit.reversed_entry_id, order.account_move)
        # Accounting-only reversal of a POS-origin invoice is not a second
        # operational sale/refund. A POS refund is counted from its own POS row.
        self._assert_sales(100)
        restored = credit._reverse_moves([{
            'date': '2026-10-04', 'invoice_date': '2026-10-04',
        }], cancel=False)
        restored.action_post()
        self.assertFalse(restored.invoice_line_ids.sale_line_ids)
        self.assertEqual(restored.reversed_entry_id, credit)
        self._assert_sales(100)
        refund = order._refund()
        self.assertEqual(refund.lines.refunded_orderline_id, order.lines)
        self.env['pos.payment'].create({
            'pos_order_id': refund.id, 'payment_method_id': self.method.id,
            'amount': -100,
        })
        refund._compute_prices()
        refund.action_pos_order_paid()
        refund.with_context(generate_pdf=False).action_pos_order_invoice()
        self.assertTrue(refund.is_refund)
        self.assertEqual(refund.account_move.move_type, 'out_refund')
        self.assertEqual(refund.account_move.state, 'posted')
        self.assertEqual(refund.amount_total, -100)
        self._assert_sales(0)

    def test_pos_opening_date_and_invoice_date_keep_cross_period_origin(self):
        sale = self._sale()
        self.session.start_at = datetime(2026, 8, 1, 15)
        self._pos(sale, quantity=.4)
        self._invoice(sale, date='2026-09-02')
        self._assert_sales(40, first='2026-08-01', last='2026-08-31')
        self._assert_sales(60, first='2026-09-01', last='2026-09-30')

    def test_ordinary_all_source_reader_and_missing_account_permission(self):
        self._invoice(self._sale())
        reader = new_test_user(
            self.env, login='unified_reader',
            groups='base.group_user,point_of_sale.group_pos_user,sales_team.group_sale_salesman_all_leads,account.group_account_readonly',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        dashboard = self.dashboard.with_user(reader).with_context(allowed_company_ids=self.company.ids)
        result = self._assert_sales(100, dashboard=dashboard)
        for source in result['source_breakdown']:
            self.assertIn('views', source['source_action'])
            self.assertIn('domain', source['source_action'])
        insufficient = new_test_user(
            self.env, login='unified_pos_only', groups='base.group_user,point_of_sale.group_pos_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        with self.assertRaises(AccessError):
            self._metrics(dashboard=self.dashboard.with_user(insufficient))

    def test_real_foreign_posted_invoice_is_excluded_from_active_company(self):
        self._invoice(self._sale())
        foreign = self.env['res.company'].create({
            'name': 'Unified forbidden company', 'currency_id': self.company.currency_id.id,
        })
        accounts = self.env['account.account'].with_company(foreign)
        receivable = accounts.create({
            'name': 'Unified foreign receivable', 'code': 'UFREC',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(foreign.ids)],
        })
        income = accounts.create({
            'name': 'Unified foreign income', 'code': 'UFINC',
            'account_type': 'income', 'company_ids': [Command.set(foreign.ids)],
        })
        self.env['account.journal'].with_company(foreign).create({
            'name': 'Unified foreign sales', 'code': 'UFS', 'type': 'sale',
            'company_id': foreign.id, 'default_account_id': income.id,
        })
        partner = self.env['res.partner'].with_company(foreign).create({
            'name': 'Foreign customer', 'property_account_receivable_id': receivable.id,
        })
        product = self.env['product.product'].with_company(foreign).create({
            'name': 'Foreign service', 'type': 'service', 'invoice_policy': 'order',
            'property_account_income_id': income.id, 'taxes_id': [Command.clear()],
        })
        sale = self.env['sale.order'].with_company(foreign).create({
            'company_id': foreign.id, 'partner_id': partner.id,
            'order_line': [Command.create({
                'product_id': product.id, 'product_uom_qty': 1,
                'price_unit': 777, 'tax_ids': [Command.clear()],
            })],
        })
        sale.action_confirm()
        invoice = self._invoice(sale)
        self.assertEqual(invoice.amount_total, 777)
        reader = new_test_user(
            self.env, login='unified_two_company_reader',
            groups='base.group_user,point_of_sale.group_pos_user,sales_team.group_sale_salesman_all_leads,account.group_account_readonly',
            company_id=self.company.id, company_ids=[Command.set((self.company | foreign).ids)],
        )
        dashboard = self.dashboard.with_user(reader).with_context(
            allowed_company_ids=[self.company.id, foreign.id],
        )
        self._assert_sales(100, dashboard=dashboard)
        self._assert_sales(777, dashboard=dashboard.with_company(foreign))

    def test_normal_and_restaurant_sources_are_disjoint(self):
        self._pos(price=40)
        restaurant = self.config.copy({
            'name': 'Unified restaurant POS', 'module_pos_restaurant': True,
        })
        restaurant.open_ui()
        session = restaurant.current_session_id
        session.set_opening_control(0, 'Unified restaurant fixture')
        session.start_at = datetime(2026, 10, 1, 15)
        self._pos(price=60, session=session)
        result = self._assert_sales(100)
        nonempty = [row for row in result['source_breakdown']
                    if Decimal(row['sales']['value'])]
        self.assertEqual(sorted(Decimal(row['sales']['value']) for row in nonempty),
                         [Decimal('40'), Decimal('60')])

    def test_foreign_currency_invoice_uses_native_signed_company_amount(self):
        usd = self.env.ref('base.USD')
        usd.active = True
        self.env['res.currency.rate'].create({
            'currency_id': usd.id, 'company_id': self.company.id,
            'name': '2026-10-02', 'rate': .25,
        })
        pricelist = self.env['product.pricelist'].create({
            'name': 'Unified USD', 'currency_id': usd.id,
        })
        invoice = self._invoice(self._sale(pricelist))
        self.assertEqual(invoice.currency_id, usd)
        self.assertEqual(invoice.amount_total, 100)
        self.assertNotEqual(invoice.amount_total_signed, invoice.amount_total)
        self._assert_sales(Decimal(str(invoice.amount_total_signed)))

    def _approved_manual_fixture(self, zero=False):
        # Reuse the actual onboarding and approval path exercised by the
        # summary source contract, rather than forging protected bridge IDs.
        admin = self.env.ref('base.user_admin')
        company = self.env['res.company'].with_user(admin).create({'name': 'Unified manual native company'})
        action = company.action_baseer_open_onboarding()
        wizard = company.env[action['res_model']].browse(action['res_id'])
        wizard.write({'sales_mode': 'summary', 'setup_summary_jahez': True})
        wizard.action_apply_selected()
        summaries = company.env['baseer.pos.summary'].with_company(company).with_context(
            allowed_company_ids=company.ids,
        )
        config = summaries.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True),
        ], limit=1)
        method = config.payment_method_ids.filtered(
            lambda row: row.baseer_category_id.kind == 'platform',
        )
        self.assertEqual(len(method), 1)
        summary = summaries.create({
            'company_id': company.id, 'config_id': config.id,
            'business_date': '2026-10-02', 'period_scope': 'all',
            'day_schedule': 'all', 'customer_count': 0 if zero else 1,
            'zero_sales': zero,
            'allocation_ids': [Command.create({
                'payment_method_id': method.id, 'amount': 0 if zero else 115,
            })],
        })
        summary.action_approve()
        self.assertEqual(summary.state, 'approved')
        if zero:
            self.assertFalse(summary.order_id)
        else:
            self.assertEqual(summary.order_id.state, 'done')
            self.assertEqual(summary.order_id.baseer_summary_id, summary)
            self.assertEqual(summary.order_id.amount_total, 115)
        dashboard = self.dashboard.with_user(admin).with_company(company).with_context(allowed_company_ids=company.ids)
        return dashboard, summary

    def test_approved_manual_summary_and_generated_native_pos_count_once(self):
        dashboard, _summary = self._approved_manual_fixture()
        result = self._assert_sales(115, dashboard=dashboard)
        totals = {row['key']: Decimal(row['sales']['value'])
                  for row in result['source_breakdown']}
        self.assertEqual(totals, {
            'manual': Decimal('115'), 'pos': Decimal('0'),
            'restaurant': Decimal('0'), 'sales': Decimal('0'),
        })

    def test_selected_manual_bridge_validates_even_outside_pos_date_window(self):
        dashboard, summary = self._approved_manual_fixture()
        session = summary.session_id
        session.flush_recordset(['start_at'])
        # Import-corruption fault injection only. Not a business mutation path:
        # put its bridge outside October's POS window while the summary remains
        # selected by October business_date, then sever the native back-link.
        self.env.cr.execute('UPDATE pos_session SET start_at=%s WHERE id=%s',
                            [datetime(2026, 9, 1, 15), session.id])
        session.invalidate_recordset(['start_at'])
        self._assert_sales(115, dashboard=dashboard)
        bridge = summary.order_id
        bridge.flush_recordset(['baseer_summary_id'])
        self.env.cr.execute('UPDATE pos_order SET baseer_summary_id=NULL WHERE id=%s',
                            [bridge.id])
        bridge.invalidate_recordset(['baseer_summary_id'])
        with self.assertRaises(ValidationError):
            self._metrics(dashboard=dashboard)

    def test_native_approved_zero_summary_does_not_require_pos_bridge(self):
        dashboard, summary = self._approved_manual_fixture(zero=True)
        self.assertTrue(summary.zero_sales)
        self.assertFalse(summary.order_id)
        result = self._assert_sales(0, dashboard=dashboard)
        self.assertTrue(result['has_data'])

    def test_confirmed_pos_without_opening_time_fails_closed(self):
        self._pos()
        # Fault-injected imported corruption, not a valid session write path.
        self.session.flush_recordset(['start_at'])
        self.env.cr.execute('UPDATE pos_session SET start_at=NULL WHERE id=%s', [self.session.id])
        self.session.invalidate_recordset(['start_at'])
        with self.assertRaises(ValidationError):
            self._metrics()

    def test_sales_only_all_time_bounds_include_posted_invoice_dates(self):
        self._invoice(self._sale(), date='2025-09-01')
        self._invoice(self._sale(), date='2026-10-02')
        first, last = self.dashboard._baseer_source_bounds()
        self.assertEqual(first.isoformat(), '2025-09-01')
        self.assertEqual(last.isoformat(), '2026-10-02')
        result = self.dashboard.get_baseer_sales_metrics({'native': None})
        self.assertEqual(Decimal(result['cards']['sales']['value']), Decimal('200'))

    def _posted_sales_reversal_chain(self):
        invoice = self._invoice(self._sale())
        credit = invoice._reverse_moves([{
            'date': '2026-10-03', 'invoice_date': '2026-10-03',
        }], cancel=False)
        credit.action_post()
        restored = credit._reverse_moves([{
            'date': '2026-10-04', 'invoice_date': '2026-10-04',
        }], cancel=False)
        restored.action_post()
        return invoice, credit, restored

    def test_imported_pos_origin_metadata_excludes_deep_sales_linked_reversals(self):
        invoice, credit, restored = self._posted_sales_reversal_chain()
        order = self._pos()
        self.assertTrue(invoice.invoice_line_ids.sale_line_ids)
        self.assertTrue(credit.invoice_line_ids.sale_line_ids)
        self.assertTrue(restored.invoice_line_ids.sale_line_ids)
        # Defensive imported-origin fixture, NOT the native POS invoice shape:
        # attach a POS origin to a genuine posted Sales invoice. Only origin
        # metadata changes, never amounts, tax lines, invoice lines or states.
        order.flush_recordset(['account_move'])
        self.env.cr.execute('UPDATE pos_order SET account_move=%s WHERE id=%s',
                            [invoice.id, order.id])
        order.invalidate_recordset(['account_move'])
        invoice.invalidate_recordset(['pos_order_ids'])
        self.assertEqual(invoice.pos_order_ids, order)
        result = self._assert_sales(100)
        totals = {row['key']: Decimal(row['sales']['value'])
                  for row in result['source_breakdown']}
        self.assertEqual(totals['sales'], 0)
        self.assertEqual(totals['pos'], 100)
        # POS opening date moves out of the invoice window: ancestry exclusions
        # must remain global rather than admitting its accounting descendants.
        self.session.start_at = datetime(2026, 8, 1, 15)
        self._assert_sales(0)
        self._assert_sales(100, first='2026-08-01', last='2026-08-31')

    def test_reversal_shared_ancestor_budget_fails_without_partial_total(self):
        self._posted_sales_reversal_chain()
        # Only the traversal capacity is reduced; money and native workflows
        # remain actual. One candidate plus two distinct ancestors exceeds 2.
        with patch('odoo.addons.baseer_sales_dashboard.models.unified_sales.MAX_SOURCE_ROWS', 2):
            with self.assertRaises(ValidationError):
                self.dashboard._baseer_unified_deep_pos_reversal_ids(self.company)

    def test_unreadable_reversal_ancestor_fails_closed_for_ordinary_reader(self):
        invoice, _credit, _restored = self._posted_sales_reversal_chain()
        reader = new_test_user(
            self.env, login='unified_hidden_ancestor_reader',
            groups='base.group_user,point_of_sale.group_pos_user,sales_team.group_sale_salesman_all_leads,account.group_account_readonly',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        # An isolated global record-rule fixture hides the original invoice
        # while retaining its descendants. No production ACL is modified.
        self.env['ir.rule'].with_user(self.env.ref('base.user_admin')).create({
            'name': 'Unified hidden invoice ancestor test',
            'model_id': self.env['ir.model']._get_id('account.move'),
            'domain_force': repr([('id', '!=', invoice.id)]),
            'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False,
        })
        with self.assertRaises(AccessError):
            self._metrics(dashboard=self.dashboard.with_user(reader))

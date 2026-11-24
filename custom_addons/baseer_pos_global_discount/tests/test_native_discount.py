from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNativeDiscountFields(TransactionCase):
    def test_native_fields_and_per_company_product(self):
        config = self.env['pos.config'].create({'name': 'Native fixed fields'})
        legacy = self.env['product.product'].create({
            'name': 'Legacy discount', 'type': 'service', 'available_in_pos': True,
            'company_id': config.company_id.id,
        })
        config.baseer_global_discount_product_id = legacy
        config.action_baseer_setup_native_discount()
        product = config.discount_product_id
        self.assertNotEqual(product, legacy)
        self.assertEqual(product.default_code, 'BASEER-NATIVE-DISC')
        other = self.env['pos.config'].create({'name': 'Native fixed reuse'})
        other.action_baseer_setup_native_discount()
        self.assertEqual(other.discount_product_id, product)
        config.write({'baseer_fixed_discount_enabled': True, 'baseer_fixed_discount_max_amount': 10,
                      'baseer_fixed_discount_allowed': 'all'})
        self.assertEqual(config.baseer_fixed_discount_allowed, 'all')
        self.assertTrue(set(('baseer_fixed_discount_enabled', 'baseer_fixed_discount_max_amount',
                             'baseer_fixed_discount_allowed')).issubset(config._load_pos_data_fields(config)))
        fields = self.env['pos.order.line']._load_pos_data_fields(config)
        self.assertTrue(set(('baseer_discount_kind', 'baseer_discount_input',
                             'baseer_discount_approved_by_user_id', 'baseer_discount_approved_by_employee',
                             'baseer_discount_approved_by_employee_name')).issubset(fields))


from uuid import uuid4
from odoo import Command
from odoo.exceptions import UserError
from .test_global_discount import TestGlobalDiscount


@tagged('post_install', '-at_install')
class TestNativeDiscountSync(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env['account.account'].create({
            'name': 'GD QA revenue', 'code': 'GDQA001', 'account_type': 'income',
            'company_ids': [Command.set(self.env.company.ids)],
        })
        self.env.company.currency_id.rounding = 0.01
        self.tax = self.env['account.tax'].create({
            'name': 'GD VAT15', 'amount_type': 'percent', 'amount': 15,
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        self.zero = self.env['account.tax'].create({
            'name': 'GD explicit zero', 'amount_type': 'percent', 'amount': 0,
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        self.product = self.env['product.product'].create({
            'name': 'GD QA product', 'type': 'service', 'available_in_pos': True,
            'list_price': 100, 'property_account_income_id': self.account.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        self.config = self.env['pos.config'].create({
            'name': 'GD QA register', 'baseer_global_discount_account_id': self.account.id,
        })
        self.config.action_baseer_setup_global_discount()
        self.config.baseer_global_discount_product_id.property_account_income_id = self.account
        self.config.open_ui()
        self.config.current_session_id.state = 'opened'
        self.config.action_baseer_setup_native_discount()
        self.config.write({'baseer_fixed_discount_enabled': True, 'baseer_fixed_discount_allowed': 'all'})

    def _payload(self, amount=10):
        order = TestGlobalDiscount._order(self, price=100)
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product.id, 'qty': 1, 'price_unit': 50,
            'price_subtotal': 50, 'price_subtotal_incl': 50, 'tax_ids': [Command.set(self.zero.ids)],
        })
        tax = self.env['account.tax']
        bases = order._gd_tax_base_lines(order.lines)
        expected = tax._prepare_global_discount_lines(bases, order.company_id, 'fixed', amount)
        for base in expected:
            detail = base['tax_details']
            self.env['pos.order.line'].create({
                'order_id': order.id, 'product_id': self.config.discount_product_id.id,
                'uuid': str(uuid4()), 'qty': base['quantity'], 'price_unit': base['price_unit'],
                'tax_ids': [Command.set(base['tax_ids'].ids)],
                'price_subtotal': detail['total_excluded_currency'],
                'price_subtotal_incl': detail['total_included_currency'],
                'extra_tax_data': tax._export_base_line_extra_tax_data(base),
                'baseer_discount_kind': 'fixed', 'baseer_discount_input': amount,
                'baseer_discount_approved_by_user_id': self.env.user.id,
            })
        payload = {
            'uuid': order.uuid, 'session_id': order.session_id.id, 'company_id': order.company_id.id,
            'state': 'draft', 'amount_total': 155, 'amount_tax': 15, 'amount_paid': 0,
            'amount_return': 0, 'payment_ids': [],
            'lines': [Command.update(line.id, {
                'uuid': line.uuid, 'product_id': line.product_id.id, 'qty': line.qty,
                'price_unit': line.price_unit, 'discount': line.discount, 'tax_ids': line.tax_ids.ids,
                'price_subtotal': line.price_subtotal, 'price_subtotal_incl': line.price_subtotal_incl,
                'extra_tax_data': line.extra_tax_data, 'baseer_discount_kind': line.baseer_discount_kind,
                'baseer_discount_input': line.baseer_discount_input,
                'baseer_discount_approved_by_user_id': line.baseer_discount_approved_by_user_id.id or False,
            }) for line in order.lines],
        }
        return order, payload

    def test_fixed_sync_and_idempotent_note(self):
        import copy
        order, payload = self._payload()
        payload['baseer_discount_logged_signature'] = 'forged'
        self.env['pos.order'].sync_from_ui([copy.deepcopy(payload)])
        self.assertTrue(order.baseer_discount_logged_signature)
        self.assertNotEqual(order.baseer_discount_logged_signature, 'forged')
        count = len(order.message_ids.filtered(lambda m: 'خصم فاتورة ثابت' in str(m.body)))
        self.assertEqual(count, 1)
        self.env['pos.order'].sync_from_ui([copy.deepcopy(payload)])
        self.assertEqual(len(order.message_ids.filtered(lambda m: 'خصم فاتورة ثابت' in str(m.body))), 1)

    def test_rejections(self):
        import copy
        order, payload = self._payload()
        for setting in ({'baseer_fixed_discount_enabled': False}, {'baseer_fixed_discount_max_amount': 5}):
            with self.assertRaises(UserError), self.env.cr.savepoint():
                self.config.write(setting)
                self.env['pos.order'].sync_from_ui([copy.deepcopy(payload)])
        with self.assertRaises(UserError), self.env.cr.savepoint():
            forged = copy.deepcopy(payload)
            forged['lines'][-1][2]['price_unit'] *= 2
            self.env['pos.order'].sync_from_ui([forged])
        with self.assertRaises(UserError), self.env.cr.savepoint():
            forged = copy.deepcopy(payload)
            for command in forged['lines']:
                if command[2].get('baseer_discount_kind'):
                    command[2]['baseer_discount_kind'] = 'percent'
                    command[2]['baseer_discount_input'] = 30
            self.config.baseer_global_discount_max_percent = 20
            self.env['pos.order'].sync_from_ui([forged])

    def test_reject_excess_total_and_tax_group_forgery(self):
        import copy
        order, payload = self._payload()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            forged = copy.deepcopy(payload)
            for command in forged['lines']:
                if command[2].get('baseer_discount_kind'):
                    command[2]['price_subtotal_incl'] = -200
                    command[2]['baseer_discount_input'] = 400
            self.env['pos.order'].sync_from_ui([forged])
        with self.assertRaises(UserError), self.env.cr.savepoint():
            forged = copy.deepcopy(payload)
            discount_lines = [c[2] for c in forged['lines'] if c[2].get('baseer_discount_kind')]
            discount_lines[0]['tax_ids'], discount_lines[1]['tax_ids'] = discount_lines[1]['tax_ids'], discount_lines[0]['tax_ids']
            self.env['pos.order'].sync_from_ui([forged])

    def test_cashier_cannot_approve_manager_discount(self):
        import copy
        cashier = self.env['res.users'].create({
            'name': 'Native cashier', 'login': 'native-discount-cashier',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('point_of_sale.group_pos_user').id])],
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
        })
        order, payload = self._payload()
        self.config.baseer_fixed_discount_allowed = 'managers'
        for command in payload['lines']:
            if command[2].get('baseer_discount_kind'):
                command[2]['baseer_discount_approved_by_user_id'] = cashier.id
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env['pos.order'].with_user(cashier).sync_from_ui([copy.deepcopy(payload)])

    def test_native_shares_and_refund_validation(self):
        order = TestGlobalDiscount._order(self, price=7, qty=3)
        source = order.lines
        for _ in range(2):
            self.env['pos.order.line'].create({
                'order_id': order.id, 'product_id': self.product.id, 'qty': 1, 'price_unit': 7,
                'price_subtotal': 7, 'price_subtotal_incl': 8.05, 'tax_ids': [Command.set(self.tax.ids)],
            })
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product.id, 'qty': 1, 'price_unit': 5,
            'price_subtotal': 5, 'price_subtotal_incl': 5, 'tax_ids': [Command.set(self.zero.ids)],
        })
        bases = order._gd_tax_base_lines(order.lines)
        for base in self.env['account.tax']._prepare_global_discount_lines(bases, order.company_id, 'fixed', 10):
            detail = base['tax_details']
            self.env['pos.order.line'].create({
                'order_id': order.id, 'product_id': self.config.discount_product_id.id,
                'qty': base['quantity'], 'price_unit': base['price_unit'], 'tax_ids': [Command.set(base['tax_ids'].ids)],
                'price_subtotal': detail['total_excluded_currency'], 'price_subtotal_incl': detail['total_included_currency'],
                'extra_tax_data': self.env['account.tax']._export_base_line_extra_tax_data(base),
                'baseer_discount_kind': 'fixed', 'baseer_discount_input': 10,
                'baseer_discount_approved_by_user_id': self.env.user.id,
            })
        order._baseer_validate_native_discount()
        discounts = order.lines.filtered(lambda l: l.product_id == self.config.discount_product_id)
        sources = order.lines - discounts
        for tax in (self.tax, self.zero):
            group = sources.filtered(lambda l: l.tax_ids == tax)
            discount = discounts.filtered(lambda l: l.tax_ids == tax)
            self.assertAlmostEqual(sum(group.mapped('baseer_discount_share_incl')), sum(discount.mapped('price_subtotal_incl')), places=2)
            self.assertAlmostEqual(sum(group.mapped('baseer_discount_share_excl')), sum(discount.mapped('price_subtotal')), places=2)
        refund_shares = []
        for index in range(3):
            refund = TestGlobalDiscount._refund(self, order, 1, source)
            refund_line = refund.lines
            previous = source.refund_orderline_ids - refund_line
            incl = self.env.company.currency_id.round(-source.baseer_discount_share_incl / 3) if index < 2 else self.env.company.currency_id.round(-source.baseer_discount_share_incl - sum(previous.mapped('baseer_discount_share_incl')))
            excl = self.env.company.currency_id.round(-source.baseer_discount_share_excl / 3) if index < 2 else self.env.company.currency_id.round(-source.baseer_discount_share_excl - sum(previous.mapped('baseer_discount_share_excl')))
            discount = self.env['pos.order.line'].create({
                'order_id': refund.id, 'product_id': self.config.discount_product_id.id,
                'qty': -1, 'price_unit': -excl, 'price_subtotal': excl,
                'price_subtotal_incl': incl, 'tax_ids': [Command.set(self.tax.ids)],
            })
            tax_model = self.env['account.tax']
            base = refund._gd_tax_base_lines(discount)[0]
            detail = base['tax_details']
            detail['delta_total_excluded_currency'] += -excl - detail['total_excluded_currency'] - detail['delta_total_excluded_currency']
            detail['delta_total_excluded'] += -excl - detail['total_excluded'] - detail['delta_total_excluded']
            tax_detail = detail['taxes_data'][0]
            adjustment = (-incl + excl) - tax_detail['tax_amount_currency']
            tax_detail['tax_amount_currency'] += adjustment
            tax_detail['tax_amount'] += adjustment
            tax_model._fix_base_lines_tax_details_on_manual_tax_amounts([base], refund.company_id)
            discount.extra_tax_data = tax_model._export_base_line_extra_tax_data(base)
            refund._baseer_validate_native_refund_discount(refund)
            refund_shares.append(refund_line.baseer_discount_share_incl)
            with self.assertRaises(UserError), self.env.cr.savepoint():
                discount.price_subtotal_incl += 0.01
                refund._baseer_validate_native_refund_discount(refund)
        self.assertAlmostEqual(sum(refund_shares), -source.baseer_discount_share_incl, places=2)

    def test_native_report_attributes_discount_to_sources(self):
        order, payload = self._payload()
        order._baseer_validate_native_discount()
        self.env.flush_all()
        rows = self.env['report.pos.order'].search([('order_id', '=', order.id)])
        discounts = order.lines.filtered(lambda line: line.product_id == self.config.discount_product_id)
        sources = order.lines - discounts
        self.assertEqual(set(rows.ids), set(sources.ids))
        self.assertAlmostEqual(sum(rows.mapped('baseer_invoice_discount')), -sum(discounts.mapped('price_subtotal')), places=2)
        for line in sources:
            row = rows.filtered(lambda item: item.id == line.id)
            self.assertAlmostEqual(row.baseer_invoice_discount, -line.baseer_discount_share_excl, places=2)

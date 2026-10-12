"""Category grouping is an additive view of actual POS payment amounts."""

from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestPosPaymentCategory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['pos.config'].create({
            'name': 'Payment category test', 'company_id': cls.company.id,
        })
        cls.session = cls.env['pos.session'].create({'config_id': cls.config.id})
        cls.payments = cls.env['pos.payment']

    def _method(self, category=False, company=None):
        company = company or self.company
        return self.env['pos.payment.method'].with_company(company).create({
            'name': 'Payment group ' + str(uuid4()), 'company_id': company.id,
            'baseer_category_id': category.id if category else False,
        })

    def _category(self, kind='platform', company=None):
        company = company or self.company
        return self.env['baseer.pos.payment.category'].with_company(company).create({
            'name': 'Payment category ' + str(uuid4()),
            'company_id': company.id, 'kind': kind,
        })

    def _payment(self, method, amount, state='paid', session=None):
        session = session or self.session
        order = self.env['pos.order'].with_company(session.company_id).create({
            'session_id': session.id, 'company_id': session.company_id.id,
            'state': state, 'source': 'pos', 'is_refund': amount < 0,
            'amount_total': amount, 'amount_tax': 0,
            'amount_paid': amount, 'amount_return': 0,
        })
        payment = self.env['pos.payment'].with_company(session.company_id).create({
            'pos_order_id': order.id, 'payment_method_id': method.id,
            'amount': amount,
        })
        self.payments |= payment
        return payment

    def _grouped(self, reader=None):
        reader = reader if reader is not None else self.env['pos.payment']
        return reader.with_context(baseer_payment_category_report=True).read_group(
            [('id', 'in', self.payments.ids)], ['amount:sum'],
            ['baseer_payment_category_id'],
        )

    def _reader_user(self, companies):
        return self.env['res.users'].create({
            'name': 'Payment category reader', 'login': 'payment-reader-' + str(uuid4()),
            'company_id': self.company.id, 'company_ids': [Command.set(companies.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })

    def test_split_payment_uses_payment_amount_not_repeated_order_total(self):
        cash, bank = self._category('cash'), self._category('bank')
        first = self._payment(self._method(cash), 40)
        second = self.env['pos.payment'].create({
            'pos_order_id': first.pos_order_id.id,
            'payment_method_id': self._method(bank).id, 'amount': 60,
        })
        self.payments |= second
        first.pos_order_id.write({'amount_total': 100, 'amount_paid': 100})
        before = [(row.id, row.amount) for row in self.payments]
        groups = self._grouped()
        totals = {row['baseer_payment_category_id'][0]: row['amount'] for row in groups}
        self.assertEqual(totals, {cash.id: 40, bank.id: 60})
        self.assertEqual(sum(totals.values()), 100)
        self.assertEqual([(row.id, row.amount) for row in self.payments], before)

    def test_platform_new_unclassified_archived_and_refund_remain_visible(self):
        platform = self._category()
        self._payment(self._method(platform), 20)
        self._payment(self._method(platform), 30, state='done')
        archived_method = self._method(platform)
        self._payment(archived_method, -5, state='invoiced')
        archived_method.active = False
        platform.active = False
        new_category = self._category()
        self._payment(self._method(new_category), 7)
        self._payment(self._method(), 11)
        draft = self._payment(self._method(new_category), 999, state='draft')
        self._payment(self._method(new_category), 888, state='cancel')
        totals = {row['baseer_payment_category_id'][0]
                  if row['baseer_payment_category_id'] else False: row['amount']
                  for row in self._grouped()}
        self.assertEqual(totals, {platform.id: 45, new_category.id: 7, False: 11})
        self.assertIn(draft, self.env['pos.payment'].search([('id', '=', draft.id)]))
        reader = self.env['pos.payment'].with_user(self._reader_user(self.company))
        self.assertEqual(sum(row['amount'] for row in self._grouped(reader)), 63)
        drilldown = reader.with_context(baseer_payment_category_report=True).search([
            ('id', 'in', self.payments.ids),
            ('baseer_payment_category_id', '=', platform.id),
        ])
        self.assertEqual(sum(drilldown.mapped('amount')), 45)
        self.assertTrue(all(payment.baseer_payment_category_id == platform for payment in drilldown))
        field = self.env['pos.payment']._fields['baseer_payment_category_id']
        self.assertFalse(field.store)
        self.assertFalse(field.compute_sudo)

    def test_active_company_scope_excludes_real_foreign_payment(self):
        self._payment(self._method(), 15)
        foreign = self.env['res.company'].create({
            'name': 'Payment category foreign', 'currency_id': self.company.currency_id.id,
        })
        self.env['account.journal'].with_company(foreign).create({
            'name': 'Payment foreign bank', 'code': 'PCFB',
            'type': 'bank', 'company_id': foreign.id,
        })
        config = self.env['pos.config'].with_company(foreign).create({
            'name': 'Payment foreign POS', 'company_id': foreign.id,
        })
        session = self.env['pos.session'].with_company(foreign).create({'config_id': config.id})
        foreign_payment = self._payment(self._method(company=foreign), 777, session=session)
        reader = self.env['pos.payment'].with_user(
            self._reader_user(self.company | foreign),
        ).with_context(
            allowed_company_ids=[self.company.id, foreign.id],
            baseer_payment_category_report=True,
        )
        # Even a reader allowed both companies must use the active company.
        self.assertNotIn(foreign_payment, reader.search([('id', 'in', self.payments.ids)]))
        self.assertEqual(sum(row['amount'] for row in self._grouped(reader)), 15)
        self.assertEqual(sum(row['amount'] for row in self._grouped(reader.with_company(foreign))), 777)
        self.assertEqual(sum(self.payments.mapped('amount')), 792)
        limited = self.env['pos.payment'].with_user(
            self._reader_user(self.company),
        ).with_context(allowed_company_ids=self.company.ids,
                       baseer_payment_category_report=True)
        self.assertFalse(limited.search([('id', '=', foreign_payment.id)]))
        with self.assertRaises(AccessError):
            limited.with_company(foreign).search([('id', '=', foreign_payment.id)])

    def test_separate_action_has_explicit_views_and_scoped_readonly_context(self):
        action = self.env.ref('baseer_pos_summary.action_pos_payment_category')
        self.assertEqual(action.res_model, 'pos.payment')
        self.assertEqual(action.view_mode, 'pivot,graph,list,form')
        context = safe_eval(action.context)
        self.assertTrue(context['baseer_payment_category_report'])
        self.assertEqual(context['search_default_baseer_payment_category'], 1)
        for key in ('create', 'edit', 'delete'):
            self.assertFalse(context[key])
        self.assertEqual([mode for _view, mode in action.views],
                         ['pivot', 'graph', 'list', 'form'])
        self.assertTrue(all(view for view, _mode in action.views))

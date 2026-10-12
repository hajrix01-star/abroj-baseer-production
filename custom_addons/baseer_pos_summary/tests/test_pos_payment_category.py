"""Category grouping is an additive view of actual POS payment amounts."""

from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestPosPaymentCategory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        sar = cls.env.ref('base.SAR')
        sar.active = True
        cls.company.currency_id = sar
        cls.config = cls.env['pos.config'].create({
            'name': 'Payment category test', 'company_id': cls.company.id,
        })
        cls.session = cls.env['pos.session']
        cls.payments = cls.env['pos.payment']

    def _method(self, category=False, company=None):
        company = company or self.company
        method = self.env['pos.payment.method'].with_company(company).create({
            'name': 'Payment group ' + str(uuid4()), 'company_id': company.id,
            'baseer_category_id': category.id if category else False,
        })
        configs = self.env['pos.config'].with_company(company).search([
            ('company_id', '=', company.id),
            ('name', 'in', ['Payment category test', 'Payment foreign POS']),
        ])
        configs.write({'payment_method_ids': [Command.link(method.id)]})
        return method

    def _category(self, kind='platform', company=None):
        company = company or self.company
        return self.env['baseer.pos.payment.category'].with_company(company).create({
            'name': 'Payment category ' + str(uuid4()),
            'company_id': company.id, 'kind': kind,
        })

    def _payment(self, method, amount, state='paid', session=None):
        if session is None:
            if not self.session:
                self.session = self.env['pos.session'].create({'config_id': self.config.id})
            session = self.session
        order = self.env['pos.order'].with_company(session.company_id).create({
            'session_id': session.id, 'company_id': session.company_id.id,
            'state': 'draft', 'source': 'pos', 'is_refund': amount < 0,
            'amount_total': amount, 'amount_tax': 0,
            'amount_paid': amount, 'amount_return': 0,
        })
        payment = self.env['pos.payment'].with_company(session.company_id).create({
            'pos_order_id': order.id, 'payment_method_id': method.id,
            'amount': amount,
        })
        order.write({'state': state})
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
        cash_method, bank_method = self._method(cash), self._method(bank)
        first = self._payment(cash_method, 40)
        second = self.env['pos.payment'].create({
            'pos_order_id': first.pos_order_id.id,
            'payment_method_id': bank_method.id, 'amount': 60,
        })
        self.payments |= second
        first.pos_order_id.write({'amount_total': 100, 'amount_paid': 100})
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'sale'),
        ], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({
                'name': 'Payment test sales', 'code': 'PCTS',
                'type': 'sale', 'company_id': self.company.id,
            })
        partner = self.env['res.partner'].create({'name': 'Payment invoice customer'})
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'company_id': self.company.id,
            'journal_id': journal.id, 'partner_id': partner.id,
        })
        # A real draft invoice link characterizes an invoiced POS origin;
        # this does not claim to test invoice calculation or accounting posting.
        first.pos_order_id.write({'account_move': invoice.id})
        self.assertEqual(first.pos_order_id.account_move, invoice)
        before = [(row.id, row.amount) for row in self.payments]
        groups = self._grouped()
        totals = {row['baseer_payment_category_id'][0]: row['amount'] for row in groups}
        self.assertEqual(totals, {cash.id: 40, bank.id: 60})
        self.assertEqual(sum(totals.values()), 100)
        self.assertEqual([(row.id, row.amount) for row in self.payments], before)

    def test_platform_new_unclassified_archived_and_refund_remain_visible(self):
        platform = self._category()
        first_method, second_method = self._method(platform), self._method(platform)
        archived_method = self._method(platform)
        new_category = self._category()
        new_method = self._method(new_category)
        unclassified = self._method()
        draft_method, cancelled_method = self._method(new_category), self._method(new_category)
        self._payment(first_method, 20)
        self._payment(second_method, 30, state='done')
        self._payment(archived_method, -5, state='done')
        self._payment(new_method, 7)
        self._payment(unclassified, 11)
        draft = self._payment(draft_method, 999, state='draft')
        self._payment(cancelled_method, 888, state='cancel')
        # Historical closed-session fixture, not an accounting close test.
        self.session.write({'state': 'closed'})
        archived_method.active = False
        platform.active = False
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
        self.assertTrue(field.store)
        self.assertFalse(field.compute_sudo)

    def test_related_category_recomputes_without_changing_payment_money(self):
        first_category = self._category()
        second_category = self._category()
        method = self._method(first_category)
        payment = self._payment(method, 25)
        self.env.flush_all()
        before = payment.read([
            'amount', 'pos_order_id', 'payment_method_id', 'payment_date',
            'create_date', 'write_date',
        ])[0]
        self.assertEqual(payment.baseer_payment_category_id, first_category)
        with self.assertRaises(UserError):
            method.write({'baseer_category_id': second_category.id})
        # This synthetic historical session shape tests only related-field
        # recomputation after the native open-session guard no longer applies;
        # it does not claim to exercise accounting session closure/posting.
        self.session.write({'state': 'closed'})
        method.write({'baseer_category_id': second_category.id})
        self.env.flush_all()
        payment.invalidate_recordset()
        self.assertEqual(payment.baseer_payment_category_id, second_category)
        self.assertEqual(payment.read([
            'amount', 'pos_order_id', 'payment_method_id', 'payment_date',
            'create_date', 'write_date',
        ])[0], before)
        self.assertEqual(self._grouped()[0]['amount'], 25)
        self.assertEqual(self._grouped()[0]['baseer_payment_category_id'][0],
                         second_category.id)

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
        foreign_method = self._method(company=foreign)
        session = self.env['pos.session'].with_company(foreign).create({'config_id': config.id})
        foreign_payment = self._payment(foreign_method, 777, session=session)
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

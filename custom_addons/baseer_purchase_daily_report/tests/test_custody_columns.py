from decimal import Decimal
from uuid import uuid4

from odoo import Command, api
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class DailyPurchaseCustodyColumnsCase(TransactionCase):
    """Custody cards and payment-method columns reuse baseer_procurement_requests."""

    def setUp(self):
        super().setUp()
        for xmlid in (
            'baseer_procurement_requests.group_procurement_accountant',
            'baseer_procurement_requests.group_procurement_manager',
            'account.group_account_manager',
            'base.group_erp_manager',
        ):
            self.env.user.group_ids |= self.env.ref(xmlid)
        self.company = self.env.company
        self.company.currency_id.active = True
        Account = self.env['account.account']
        Journal = self.env['account.journal']
        self.custody_account = Account.create({
            'name': 'Custody columns ledger', 'code': 'DPC108', 'account_type': 'asset_current',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        bank_account = Account.create({
            'name': 'Custody columns bank', 'code': 'DPC101', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        cash_account = Account.create({
            'name': 'Custody columns cash', 'code': 'DPC102', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.payable = Account.create({
            'name': 'Custody columns payable', 'code': 'DPC200', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        self.expense = Account.create({
            'name': 'Custody columns expense', 'code': 'DPC600', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        general = Journal.create({
            'name': 'Custody columns entries', 'code': 'DPCG', 'type': 'general', 'company_id': self.company.id,
        })
        self.bank = Journal.create({
            'name': 'Custody columns bank', 'code': 'DPCB', 'type': 'bank',
            'company_id': self.company.id, 'default_account_id': bank_account.id,
        })
        self.cash = Journal.create({
            'name': 'Custody columns cash', 'code': 'DPCX', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        self.purchase = Journal.create({
            'name': 'Custody columns purchases', 'code': 'DPCP', 'type': 'purchase',
            'company_id': self.company.id, 'default_account_id': self.expense.id,
        })
        self.company.write({
            'baseer_procurement_representative_petty_cash_account_id': self.custody_account.id,
            'baseer_procurement_representative_petty_cash_journal_id': general.id,
            'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set([self.bank.id])],
        })
        self.representative = self.env['res.partner'].create({
            'name': 'Custody columns representative', 'company_id': self.company.id,
        })
        self.representative.with_company(self.company).is_purchase_representative = True
        self.custody = Journal.search([
            ('company_id', '=', self.company.id), ('baseer_custody_representative_id', '=', self.representative.id),
        ], limit=1)
        if not self.custody:
            self.custody = Journal.create({
                'name': 'Custody columns representative cash', 'code': 'DPCC', 'type': 'cash',
                'company_id': self.company.id, 'default_account_id': self.custody_account.id,
                'baseer_custody_representative_id': self.representative.id,
            })
        for journal, account in ((self.custody, self.custody_account), (self.bank, bank_account), (self.cash, cash_account)):
            (journal.outbound_payment_method_line_ids | journal.inbound_payment_method_line_ids).write({
                'payment_account_id': account.id,
            })
        self.vendor = self.env['res.partner'].create({'name': 'Custody columns vendor'})
        self.vendor.with_company(self.company).property_account_payable_id = self.payable
        self.owner = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Custody columns owner', 'login': 'custody_columns_owner',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'owner',
        })

    def _report(self, user=None):
        env = api.Environment(self.env.cr, (user or self.owner).id, {'allowed_company_ids': [self.company.id]})
        return env['baseer.purchase.daily.report']

    def _bill(self, amount, day):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'company_id': self.company.id, 'journal_id': self.purchase.id,
            'partner_id': self.vendor.id, 'invoice_date': day, 'ref': 'Custody columns',
            'invoice_line_ids': [Command.create({
                'name': 'Goods', 'quantity': 1, 'price_unit': amount,
                'account_id': self.expense.id, 'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        return bill

    def _pay(self, bill, journal, amount=None):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': journal.id, 'payment_date': bill.invoice_date,
            'payment_method_line_id': journal.outbound_payment_method_line_ids[0].id,
        })
        if amount is not None:
            wizard.amount = amount
        return wizard._create_payments().ensure_one()

    def _movements(self):
        Advance = self.env['baseer.procurement.representative.advance']
        rep = self.representative.id
        Advance.submit_funding(False, self.bank.id, rep, '1000.00', str(uuid4()), '2099-11-02')
        second = Advance.submit_funding(False, self.bank.id, rep, '500.00', str(uuid4()), '2099-11-05')
        Advance.submit_funding_reversal(second, 'Duplicate transfer', '2099-11-06', str(uuid4()))
        Advance.submit_aggregate_return(rep, self.bank.id, '50.00', str(uuid4()), '2099-11-07')
        # Activity before the reporting start is in the balance, not in the period cards.
        Advance.submit_funding(False, self.bank.id, rep, '25.00', str(uuid4()), '2026-10-20')

    def test_cards_columns_and_transfer_rows_reconcile(self):
        self._movements()
        custody_bill = self._bill(300, '2099-11-03')
        self._pay(custody_bill, self.custody)
        mixed = self._bill(200, '2099-11-04')
        self._pay(mixed, self.custody, 120)
        self._pay(mixed, self.cash, 80)
        self._bill(100, '2099-11-04')
        bank_bill = self._bill(70, '2099-11-05')
        self._pay(bank_bill, self.bank)

        payload = self._report().get_days('2099-11-01', '2099-11-30', 'all')
        custody = payload['custody']
        self.assertTrue(custody['active'])
        self.assertEqual(custody['start'], '2099-11-01')
        self.assertEqual(custody['funded'], '950.00')  # 1000 + 500 - 500 reversal - 50 return
        self.assertEqual(custody['spent'], '420.00')
        Advance = self.env['baseer.procurement.representative.advance']
        available = Advance._baseer_representative_available_amount(self.company, self.representative)
        self.assertEqual(available, Decimal('555.00'))
        self.assertEqual(custody['remaining'], '555.00')

        table = payload['table']
        keys = [column['key'] for column in table['columns']]
        bank_key = f'journal:{self.bank.id}'
        self.assertEqual(keys, ['osama', 'cash', bank_key, 'unpaid'])
        self.assertEqual(table['totals'], {'osama': '420.00', 'cash': '80.00', bank_key: '70.00', 'unpaid': '100.00'})
        self.assertEqual(table['total'], '670.00')
        self.assertEqual(sum(Decimal(value) for value in table['totals'].values()), Decimal(table['total']))
        # Consistency rules agreed for the report.
        self.assertEqual(table['totals']['osama'], custody['spent'])
        self.assertEqual(table['transfer_total'], custody['funded'])
        self.assertTrue(table['has_transfers'])
        transfers = [row for row in table['rows'] if row['kind'] == 'transfer']
        self.assertEqual([(row['date'], row['transfer']) for row in transfers], [
            ('2099-11-07', '-50.00'), ('2099-11-06', '-500.00'), ('2099-11-05', '500.00'), ('2099-11-02', '1,000.00'),
        ])
        self.assertTrue(all('amounts' not in row and 'total' not in row for row in transfers))
        days = {row['date']: row for row in table['rows'] if row['kind'] == 'day'}
        self.assertEqual(days['2099-11-04']['amounts'], {'osama': '120.00', 'cash': '80.00', 'unpaid': '100.00'})
        self.assertEqual(days['2099-11-04']['total'], '300.00')
        # Day rows of the main table carry the existing day metrics too.
        self.assertEqual((days['2099-11-04']['count'], days['2099-11-04']['residual']), (2, '100.00'))
        self.assertEqual(set(days), {day['date'] for day in payload['days']})
        # Transfer-only dates (2099-11-02, 06, 07) appear as transfer rows without purchase amounts.
        self.assertNotIn('2099-11-02', days)
        self.assertEqual([row['kind'] for row in table['rows'] if row['date'] == '2099-11-05'], ['day', 'transfer'])
        # The existing day totals are unchanged by the transfer rows.
        self.assertEqual(sum(Decimal(day['total'].replace(',', '')) for day in payload['days']), Decimal('670.00'))

        rows = {row['id']: row for row in self._report().get_day('2099-11-04', 'all', 0)['rows']}
        self.assertEqual({part['key']: part['amount'] for part in rows[mixed.id]['method_amounts']},
                         {'osama': '120.00', 'cash': '80.00'})

    def test_filters_period_start_and_labels(self):
        self._movements()
        self._pay(self._bill(40, '2099-11-03'), self.custody)
        report = self._report()
        self.assertFalse(report.get_days('2099-11-01', '2099-11-30', 'not_paid')['table']['has_transfers'])
        self.assertFalse(report.get_days('2099-11-01', '2099-11-30', 'all', 'cash')['table']['has_transfers'])
        self.assertTrue(report.get_days('2099-11-01', '2099-11-30', 'all', 'osama')['table']['has_transfers'])
        # The period cards start on 1 November 2026; earlier ranges have no period activity.
        october = report.get_days('2026-10-01', '2026-10-31', 'all')
        self.assertFalse(october['custody']['active'])
        self.assertEqual((october['custody']['funded'], october['custody']['spent']), ('0.00', '0.00'))
        self.assertFalse(october['table']['has_transfers'])
        self.env['baseer.procurement.representative.advance'].submit_funding(
            False, self.bank.id, self.representative.id, '30.00', str(uuid4()), '2026-11-10')
        clipped = report.get_days('2026-10-01', '2026-11-30', 'all')
        self.assertEqual((clipped['custody']['start'], clipped['custody']['funded'], clipped['custody']['spent']),
                         ('2026-11-01', '30.00', '0.00'))
        self.assertEqual(clipped['table']['transfer_total'], '30.00')
        self.env['res.lang']._activate_lang('ar_001')
        arabic = report.with_context(lang='ar_001').get_days('2099-11-01', '2099-11-30', 'all')['table']
        self.assertEqual(arabic['columns'][0]['label'], 'عهدة')
        self.assertIn('تحويل للعهدة', [row['label'] for row in arabic['rows'] if row['kind'] == 'transfer'])

    def test_custody_screen_link_follows_procurement_access(self):
        accountant = self.env.ref('baseer_procurement_requests.group_procurement_accountant')
        procurement_groups = self.env.ref('baseer_procurement_requests.group_procurement_manager') | accountant \
            | self.env.ref('baseer_procurement_requests.group_procurement_cashier') | self.env.ref('base.group_system')
        self.owner.sudo().group_ids -= procurement_groups
        if not (self.owner.all_group_ids & procurement_groups):
            report = self._report()
            self.assertFalse(report.get_days('2099-11-01', '2099-11-30', 'all')['custody']['can_open'])
            with self.assertRaises(AccessError):
                report.open_custody_screen()
        self.owner.sudo().group_ids |= accountant
        report = self._report()
        self.assertTrue(report.get_days('2099-11-01', '2099-11-30', 'all')['custody']['can_open'])
        action = report.open_custody_screen()
        self.assertEqual(action['tag'], 'baseer_procurement_requests.representative_petty_cash')

    def test_company_without_custody_setup_has_no_cards(self):
        other = self.env['res.company'].create({'name': 'Custody columns empty', 'currency_id': self.company.currency_id.id})
        self.owner.sudo().write({'company_ids': [Command.link(other.id)]})
        env = api.Environment(self.env.cr, self.owner.id, {'allowed_company_ids': [other.id]})
        payload = env['baseer.purchase.daily.report'].get_days('2099-11-01', '2099-11-30', 'all')
        self.assertIsNone(payload['custody'])
        self.assertEqual(payload['table']['rows'], [])

from datetime import date, datetime, timedelta

import pytz

from odoo import fields
from odoo.tests import TransactionCase, tagged

RIYADH = pytz.timezone('Asia/Riyadh')


def utc(day, hour, minute=0):
    """Naive UTC datetime string for a Riyadh wall-clock time."""
    local = RIYADH.localize(datetime(day.year, day.month, day.day, hour, minute))
    return local.astimezone(pytz.UTC).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')


@tagged('post_install', '-at_install', 'session_open_day')
class TestSessionOpenDay(TransactionCase):
    """A posted POS session is dated by its opening day in Asia/Riyadh, not by its closing entry date."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.service = self.env['baseer.dashboard2.service']
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', self.company.id)], limit=1)
        settings.pos_cutover_date = False
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', '%s:Test' % self.company.id)
        self.method = self.env['pos.payment.method'].create({'name': 'cash', 'company_id': self.company.id})
        self.journal = self.env['account.journal'].create({'name': 'POS sales', 'code': 'D2SO', 'type': 'sale', 'company_id': self.company.id})
        self.misc = self.env['account.journal'].create({'name': 'Close', 'code': 'D2SC', 'type': 'general', 'company_id': self.company.id})
        self.config = self.env['pos.config'].create({
            'name': 'Open day POS', 'company_id': self.company.id, 'journal_id': self.journal.id,
            'payment_method_ids': [(6, 0, [self.method.id])]})
        account = self.env['account.account'].with_company(self.company)
        self.cash = account.create({'code': 'D2SOC', 'name': 'Cash', 'account_type': 'asset_cash', 'company_ids': [(6, 0, [self.company.id])]})
        self.revenue = account.create({'code': 'D2SOR', 'name': 'Sales', 'account_type': 'income', 'company_ids': [(6, 0, [self.company.id])]})

    def _closing_entry(self, day, amount):
        move = self.env['account.move'].create({'journal_id': self.misc.id, 'date': day, 'line_ids': [
            (0, 0, {'name': 'cash', 'account_id': self.cash.id, 'debit': amount, 'credit': 0}),
            (0, 0, {'name': 'sale', 'account_id': self.revenue.id, 'debit': 0, 'credit': amount})]})
        move.action_post()
        return move

    def _session(self, opened, closed_on, tickets):
        """tickets: [(utc datetime string, amount)]. opened: UTC string or False."""
        self.env['pos.session'].search([('config_id', '=', self.config.id), ('state', '!=', 'closed')]).write({'state': 'closed'})
        session = self.env['pos.session'].create({'config_id': self.config.id})
        for when, amount in tickets:
            order = self.env['pos.order'].create({
                'company_id': self.company.id, 'session_id': session.id, 'date_order': when, 'state': 'paid',
                'amount_tax': 0, 'amount_total': amount, 'amount_paid': amount, 'amount_return': 0})
            self.env['pos.payment'].create({'pos_order_id': order.id, 'payment_method_id': self.method.id, 'amount': amount})
        session.write({'start_at': opened, 'state': 'closed'} if opened else {'state': 'closed'})
        session.move_id = self._closing_entry(closed_on, sum(a for _w, a in tickets))
        return session

    def _gross(self, first, last=None):
        return self.service._sales_summary([self.company.id], first, last or first)[0]['gross']

    def _customers(self, first, last=None):
        return self.service._sales_summary([self.company.id], first, last or first)[0]['customers']['value'] or 0

    def test_overnight_session_lands_fully_on_open_day(self):
        d10, d11, d12 = date(2031, 3, 10), date(2031, 3, 11), date(2031, 3, 12)
        # Opened 10 Mar 16:00 Riyadh, closed after midnight, entry dated 11 Mar.
        self._session(utc(d10, 16), d11, [
            (utc(d10, 18), 100), (utc(d10, 20), 100), (utc(d10, 23), 100),
            (utc(d11, 0, 30), 50), (utc(d11, 1, 10), 50)])
        self.assertEqual(self._gross(d10), 400)
        self.assertEqual(self._gross(d11), 0)
        self.assertEqual(self._gross(d10, d11), 400)
        # Customer counts follow the same day, including the two tickets printed after midnight.
        self.assertEqual(self._customers(d10), 5)
        self.assertEqual(self._customers(d11), 0)
        days = self.service._sales_days([self.company.id], d10, d11)[0]
        self.assertEqual(sorted(day for _cid, day in days), [d10])
        self.assertEqual(days[(self.company.id, d10)]['source'], 'pos')
        # The closing entry date alone must not select the session.
        self.assertEqual(self._gross(d12), 0)

    def test_same_day_session_is_unchanged_and_riyadh_midnight_boundary(self):
        d10, d11 = date(2031, 3, 20), date(2031, 3, 21)
        self._session(utc(d10, 12), d10, [(utc(d10, 13), 200)])
        # Opened 00:30 Riyadh on the 21st: still 20 Mar in UTC, but 21 Mar in Asia/Riyadh.
        self._session(utc(d11, 0, 30), d11, [(utc(d11, 1), 70)])
        self.assertEqual(self._gross(d10), 200)
        self.assertEqual(self._gross(d11), 70)
        self.assertEqual(self._gross(d10, d11), 270)
        self.assertEqual(self._customers(d10), 1)
        self.assertEqual(self._customers(d11), 1)

    def test_month_boundary_follows_open_day(self):
        last, first = date(2031, 4, 30), date(2031, 5, 1)
        self._session(utc(last, 17), first, [(utc(last, 18), 300), (utc(first, 1), 20)])
        april = self.service._sales_summary([self.company.id], date(2031, 4, 1), last)[0]
        may = self.service._sales_summary([self.company.id], first, date(2031, 5, 31))[0]
        self.assertEqual(april['gross'], 320)
        self.assertEqual(may['gross'], 0)

    def test_session_without_opening_time_keeps_entry_date(self):
        d10 = date(2031, 6, 10)
        self._session(False, d10, [(utc(d10, 12), 90)])
        self.assertEqual(self._gross(d10), 90)

    def test_hours_and_drilldowns_match_counts(self):
        d10, d11 = date(2031, 7, 10), date(2031, 7, 11)
        self._session(utc(d10, 17), d11, [(utc(d10, 18), 100), (utc(d11, 0, 20), 40), (utc(d11, 0, 40), 40)])
        summary, _days, _channels, hours = self.service._sales_summary([self.company.id], d10, d10)
        self.assertEqual(summary['customers']['value'], 3)
        self.assertEqual(sum(row['orders'] for row in hours.values()), 3)
        orders = self.env['pos.order'].search(self.service._customer_orders_domain([self.company.id], d10, d10))
        self.assertEqual(len(orders), 3)
        # Tickets after midnight sit in the next weekday's hour 0 cell and drill down to the same orders.
        cell = hours[(d11.weekday(), 0)]['orders']
        self.assertEqual(cell, 2)
        domain = self.service._customer_hour_domain([self.company.id], d10, d10, d11.weekday(), 0)
        self.assertEqual(len(self.env['pos.order'].search(domain)), cell)
        self.assertEqual(len(self.env['pos.order'].search(self.service._customer_orders_domain([self.company.id], d11, d11))), 0)

    def test_yesterday_and_today_cards_follow_session_open_day(self):
        today = fields.Date.context_today(self.service)
        yesterday = today - timedelta(days=1)

        def cards(mode):
            data = self.service.get_section('overview', {'company_key': str(self.company.id), 'period': {'mode': mode}})
            return data['cards']['today_sales']['value'] or 0, data['cards']['period_sales']['value'] or 0

        before_today, before_today_mtd = cards('today')
        before_yesterday, _before_yesterday_mtd = cards('yesterday')
        # Shift opened yesterday evening, closed after midnight: the entry is dated today.
        self._session(utc(yesterday, 16), today, [(utc(yesterday, 18), 4000), (utc(today, 0, 30), 128)])
        after_today, after_today_mtd = cards('today')
        after_yesterday, _after_yesterday_mtd = cards('yesterday')
        self.assertEqual(after_today - before_today, 0)
        self.assertEqual(after_yesterday - before_yesterday, 4128)
        # Month to date is cumulative, so the closed shift is counted exactly once.
        self.assertEqual(after_today_mtd - before_today_mtd, 4128 if yesterday.month == today.month else 0)

    def test_sales_vat_follows_open_day(self):
        tax_account = self.env['account.account'].with_company(self.company).create({
            'code': 'D2SOT', 'name': 'VAT', 'account_type': 'liability_current', 'company_ids': [(6, 0, [self.company.id])]})
        tax = self.env['account.tax'].create({'name': 'D2 VAT', 'amount': 15, 'amount_type': 'percent', 'type_tax_use': 'sale', 'company_id': self.company.id})
        d10, d11 = date(2031, 8, 10), date(2031, 8, 11)
        move = self.env['account.move'].create({'journal_id': self.misc.id, 'date': d11, 'line_ids': [
            (0, 0, {'name': 'cash', 'account_id': self.cash.id, 'debit': 115, 'credit': 0}),
            (0, 0, {'name': 'sale', 'account_id': self.revenue.id, 'debit': 0, 'credit': 100}),
            (0, 0, {'name': 'vat', 'account_id': tax_account.id, 'debit': 0, 'credit': 15})]})
        move.action_post()
        # Mark the VAT line as a tax line (computed from repartition lines on real invoices).
        vat_line = move.line_ids.filtered(lambda line: line.account_id == tax_account)
        self.env.cr.execute('UPDATE account_move_line SET tax_line_id = %s WHERE id = %s', (tax.id, vat_line.id))
        vat_line.invalidate_recordset(['tax_line_id'])
        self.env['pos.session'].search([('config_id', '=', self.config.id), ('state', '!=', 'closed')]).write({'state': 'closed'})
        session = self.env['pos.session'].create({'config_id': self.config.id})
        order = self.env['pos.order'].create({
            'company_id': self.company.id, 'session_id': session.id, 'date_order': utc(d10, 18), 'state': 'paid',
            'amount_tax': 15, 'amount_total': 115, 'amount_paid': 115, 'amount_return': 0})
        self.env['pos.payment'].create({'pos_order_id': order.id, 'payment_method_id': self.method.id, 'amount': 115})
        session.write({'start_at': utc(d10, 16), 'state': 'closed'})
        session.move_id = move
        self.assertEqual(self.service._sales_vat([self.company.id], d10, d10)['value'], 15)
        self.assertEqual(self.service._sales_vat([self.company.id], d11, d11)['value'], 0)

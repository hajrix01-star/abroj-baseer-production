from decimal import Decimal, ROUND_HALF_UP

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


class BaseerAccountActivity(models.AbstractModel):
    _name = 'baseer.account.activity'
    _description = 'Baseer Posted Account Activity'

    PAGE_SIZE = 100

    @staticmethod
    def _amount(value):
        return Decimal(str(value or 0))

    @classmethod
    def _format_money(cls, value, currency):
        """Round only for presentation, at the company's currency increment."""
        increment = Decimal(str(currency.rounding))
        if increment <= 0:
            raise ValidationError(_('The company currency has an invalid rounding increment.'))
        rounded = (value / increment).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * increment
        if not rounded:
            rounded = abs(rounded)
        places = int(currency.decimal_places)
        return f'{rounded:.{places}f}'

    @api.model
    def _totals(self, domain):
        grouped = self.env['account.move.line']._read_group(
            domain, [], ['debit:sum', 'credit:sum'],
        )
        debit, credit = grouped[0] if grouped else (0, 0)
        return self._amount(debit), self._amount(credit)

    @api.model
    def get_activity(self, company_id, account_id, date_from, date_to,
                     cursor_date=None, cursor_id=None):
        """Return a bounded, posted single-account ledger in company currency.

        The opening and period totals use ORM aggregations with record rules;
        details use keyset pagination. No financial rows are silently capped.
        """
        if not any(self.env.user.has_group(group) for group in (
            'account.group_account_readonly',
            'account.group_account_user',
            'account.group_account_manager',
        )):
            raise AccessError(_('Accounting access is required.'))
        if type(company_id) is not int or type(account_id) is not int:
            raise ValidationError(_('Select one company and one account.'))
        if company_id not in self.env.companies.ids:
            raise AccessError(_('The selected company is not allowed.'))

        company = self.env['res.company'].browse(company_id).exists()
        company.check_access('read')
        account = self.env['account.account'].browse(account_id).exists()
        if not account:
            raise ValidationError(_('Select an existing account.'))
        account.check_access('read')
        if company not in account.company_ids:
            raise AccessError(_('The selected account is not available for this company.'))
        self.env['account.move.line'].browse().check_access('read')
        self.env['account.move'].browse().check_access('read')

        try:
            start = fields.Date.to_date(date_from)
            end = fields.Date.to_date(date_to)
        except (TypeError, ValueError):
            raise ValidationError(_('Select valid start and end dates.')) from None
        if not start or not end or start > end:
            raise ValidationError(_('The period start must be on or before its end.'))
        fiscal = company.compute_fiscalyear_dates(start)
        if end > fiscal['date_to']:
            raise ValidationError(_('Select dates within one fiscal year.'))

        if (cursor_date is None) != (cursor_id is None):
            raise ValidationError(_('The page cursor is incomplete.'))
        if cursor_date is not None:
            try:
                cursor_day = fields.Date.to_date(cursor_date)
            except (TypeError, ValueError):
                raise ValidationError(_('The page cursor date is invalid.')) from None
            if type(cursor_id) is not int or cursor_id <= 0 or not start <= cursor_day <= end:
                raise ValidationError(_('The page cursor is outside the selected period.'))

        AML = self.env['account.move.line']
        base = (Domain('company_id', '=', company.id)
                & Domain('account_id', '=', account.id)
                & Domain('parent_state', '=', 'posted'))
        opening_start = None if account.include_initial_balance else fiscal['date_from']
        opening_domain = base & Domain('date', '<', start)
        if opening_start:
            opening_domain &= Domain('date', '>=', opening_start)
        initial_debit, initial_credit = self._totals(opening_domain)
        opening = initial_debit - initial_credit

        period = base & Domain('date', '>=', start) & Domain('date', '<=', end)
        period_debit, period_credit = self._totals(period)
        closing = opening + period_debit - period_credit

        preceding_debit = preceding_credit = Decimal('0')
        detail_domain = period
        if cursor_date is not None:
            before = (Domain('date', '<', cursor_day)
                      | (Domain('date', '=', cursor_day) & Domain('id', '<=', cursor_id)))
            preceding_debit, preceding_credit = self._totals(period & before)
            cursor_line = AML.search(period & Domain('date', '=', cursor_day)
                                     & Domain('id', '=', cursor_id), limit=1)
            if not cursor_line:
                raise ValidationError(_('The page cursor does not belong to this account and period.'))
            after = (Domain('date', '>', cursor_day)
                     | (Domain('date', '=', cursor_day) & Domain('id', '>', cursor_id)))
            detail_domain &= after

        page = AML.search(detail_domain, order='date asc, id asc', limit=self.PAGE_SIZE + 1)
        has_more = len(page) > self.PAGE_SIZE
        lines = page[:self.PAGE_SIZE]
        # Search applies account.move.line record rules; accessing linked moves
        # also requires their own record-level read permission.
        lines.mapped('move_id').check_access('read')
        running = opening + preceding_debit - preceding_credit
        currency = company.currency_id
        result_lines = []
        for line in lines:
            debit = self._amount(line.debit)
            credit = self._amount(line.credit)
            running += debit - credit
            result_lines.append({
                'id': line.id,
                'date': fields.Date.to_string(line.date),
                'move_id': line.move_id.id,
                'move_name': line.move_id.name or '',
                'label': line.name or '',
                'debit': self._format_money(debit, currency),
                'credit': self._format_money(credit, currency),
                'running': self._format_money(running, currency),
            })
        last = lines[-1] if has_more else None
        return {
            'company_name': company.display_name,
            'account_name': account.display_name,
            'currency_symbol': currency.symbol or currency.name,
            'opening': self._format_money(opening, currency),
            'debit': self._format_money(period_debit, currency),
            'credit': self._format_money(period_credit, currency),
            'closing': self._format_money(closing, currency),
            'lines': result_lines,
            'next_cursor': {'date': fields.Date.to_string(last.date), 'id': last.id} if last else None,
        }

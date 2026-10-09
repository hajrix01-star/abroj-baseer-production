"""Read-only trial balance built from the secured general-ledger snapshot."""

from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


class BaseerTrialBalance(models.AbstractModel):
    _name = 'baseer.trial.balance.report'
    _inherit = 'baseer.general.ledger.report'
    _description = 'Baseer Posted Trial Balance'

    @api.model
    def _company(self, company_id):
        # The report selector follows the active company, not another allowed
        # company silently supplied in an RPC or stored browser filter.
        if company_id != self.env.company.id:
            raise AccessError(_('The report is limited to the active company.'))
        return super()._company(company_id)

    @api.model
    def _filters(self, filters):
        company, start, end, fiscal_start, journal_ids, base = super()._filters(filters)
        # Off-balance memoranda are not part of the statutory trial balance.
        # The inherited count check still verifies complete source access.
        base &= Domain('account_id.account_type', '!=', 'off_balance')
        return company, start, end, fiscal_start, journal_ids, base

    @classmethod
    def _sides(cls, amount, currency):
        return {
            'debit': cls._money(max(amount, Decimal('0')), currency),
            'credit': cls._money(max(-amount, Decimal('0')), currency),
        }

    @api.model
    def get_report(self, filters, page=1):
        if type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid page.'))
        return self._build_trial_balance(filters, page=page)

    def _build_trial_balance(self, filters, page=1, full=False):
        (company, start, end, fiscal_start, journal_ids, prior,
         current_open, period, accounts) = self._snapshot(filters)
        currency = company.currency_id
        zero = Decimal('0')
        old_result = zero
        old_result_count = 0
        opening_debit = opening_credit = movement_debit = movement_credit = zero
        closing_debit = closing_credit = zero
        rows = []
        for account in accounts.values():
            prior_balance = self._balance(prior, account.id)
            fiscal_ytd = self._balance(current_open, account.id)
            entry = period.get(account.id, {})
            raw_debit = entry.get('debit', zero)
            raw_credit = entry.get('credit', zero)
            if account.include_initial_balance:
                opening = prior_balance + fiscal_ytd
            else:
                # Revenue, expense and Odoo's unaffected result reset only at
                # the fiscal boundary. A month inside the fiscal year keeps YTD.
                opening = fiscal_ytd
                old_result += prior_balance
                old_result_count += prior.get(account.id, {}).get('count', 0)
            closing = opening + raw_debit - raw_credit
            open_sides = self._sides(opening, currency)
            close_sides = self._sides(closing, currency)
            opening_debit += max(opening, zero)
            opening_credit += max(-opening, zero)
            movement_debit += raw_debit
            movement_credit += raw_credit
            closing_debit += max(closing, zero)
            closing_credit += max(-closing, zero)
            rows.append({
                'id': account.id, 'code': account.code or '',
                'name': account.name or '',
                'opening_debit': open_sides['debit'],
                'opening_credit': open_sides['credit'],
                'debit': self._money(raw_debit, currency),
                'credit': self._money(raw_credit, currency),
                'debit_negative': raw_debit < 0,
                'credit_negative': raw_credit < 0,
                'closing_debit': close_sides['debit'],
                'closing_credit': close_sides['credit'],
                'period_line_count': entry.get('count', 0),
                'opening_source_count': current_open.get(account.id, {}).get('count', 0)
                + (prior.get(account.id, {}).get('count', 0)
                   if account.include_initial_balance else 0),
            })
        rows.sort(key=lambda row: (row['code'], row['id']))
        if full and len(rows) > 5000:
            raise ValidationError(_(
                'The PDF is limited to 5,000 accounts. Narrow the period or selected journals.'
            ))

        rbf_sides = self._sides(old_result, currency)
        opening_debit += max(old_result, zero)
        opening_credit += max(-old_result, zero)
        closing_debit += max(old_result, zero)
        closing_credit += max(-old_result, zero)
        # A trial balance must fail closed if access rules, rounding, or a
        # source anomaly would produce a silently incomplete financial view.
        if any(self._money(d - c, currency) != self._money(zero, currency)
               for d, c in ((opening_debit, opening_credit),
                            (movement_debit, movement_credit),
                            (closing_debit, closing_credit))):
            raise AccessError(_(
                'The readable journal items do not form a balanced trial balance. '
                'Check source access rights and accounting entries.'
            ))
        self._assert_complete_source(company, end, journal_ids)
        count = len(rows)
        return {
            'company': {'id': company.id, 'name': company.display_name,
                        'currency_code': currency.name},
            'period': {'date_from': fields.Date.to_string(start),
                       'date_to': fields.Date.to_string(end),
                       'fiscal_start': fields.Date.to_string(fiscal_start)},
            'is_partial_journals': bool(journal_ids),
            'page': page, 'page_size': self.PAGE_SIZE,
            'page_count': (count + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
            'account_count': count,
            'accounts': rows if full else rows[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE],
            'rbf': {'opening_debit': rbf_sides['debit'],
                    'opening_credit': rbf_sides['credit'],
                    'closing_debit': rbf_sides['debit'],
                    'closing_credit': rbf_sides['credit'],
                    'source_line_count': old_result_count},
            'total': {
                'opening_debit': self._money(opening_debit, currency),
                'opening_credit': self._money(opening_credit, currency),
                'debit': self._money(movement_debit, currency),
                'credit': self._money(movement_credit, currency),
                'closing_debit': self._money(closing_debit, currency),
                'closing_credit': self._money(closing_credit, currency),
            },
        }

    @api.model
    def action_print(self, filters):
        if not isinstance(filters, dict) or filters.get('company_id') != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        self._filters(filters)
        return self.env.ref('baseer_trial_balance_report.action_trial_balance_pdf').report_action(
            [], data={'filters': filters}, config=False,
        )

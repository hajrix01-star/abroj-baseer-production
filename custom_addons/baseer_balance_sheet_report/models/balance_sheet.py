"""Read-only balance sheet from the verified posted general-ledger source."""

from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


class BaseerBalanceSheet(models.AbstractModel):
    _name = 'baseer.balance.sheet.report'
    _inherit = 'baseer.general.ledger.report'
    _description = 'Baseer Posted Balance Sheet'

    SECTIONS = ('assets', 'liabilities', 'equity', 'brought_forward', 'current_result')

    @api.model
    def _company(self, company_id):
        if company_id != self.env.company.id:
            raise AccessError(_('The report is limited to the active company.'))
        return super()._company(company_id)

    @api.model
    def _filters(self, filters):
        company, start, end, fiscal_start, journal_ids, base = super()._filters(filters)
        return (company, start, end, fiscal_start, journal_ids,
                base & Domain('account_id.account_type', '!=', 'off_balance'))

    @staticmethod
    def _section_for(account):
        kind = account.account_type
        if kind == 'equity_unaffected':
            return None
        if kind.startswith('asset'):
            return 'assets'
        if kind.startswith('liability'):
            return 'liabilities'
        if kind.startswith('equity'):
            return 'equity'
        if kind.startswith(('income', 'expense')):
            return 'current_result'
        raise AccessError(_('An account has an unsupported type for the balance sheet.'))

    @api.model
    def _calculation(self, filters):
        (company, _start, end, fiscal_start, journal_ids, prior,
         current_open, period, accounts) = self._snapshot(filters)
        if company.compute_fiscalyear_dates(end)['date_from'] != fiscal_start:
            raise ValidationError(_('The period must stay within one fiscal year.'))
        currency = company.currency_id
        zero = Decimal('0')
        raw = dict.fromkeys(self.SECTIONS, zero)
        section_rows = {key: [] for key in self.SECTIONS}
        source_balance = zero
        for account in accounts.values():
            account_id = account.id
            before_year = self._balance(prior, account_id)
            fiscal_movement = (self._balance(current_open, account_id)
                               + self._balance(period, account_id))
            through_cutoff = before_year + fiscal_movement
            source_balance += through_cutoff
            ordinary = self._section_for(account)
            if ordinary in ('assets', 'liabilities', 'equity'):
                raw[ordinary] += through_cutoff
                section_rows[ordinary].append((account, through_cutoff,
                                               'balance',
                                               prior.get(account_id, {}).get('count', 0)
                                               + current_open.get(account_id, {}).get('count', 0)
                                               + period.get(account_id, {}).get('count', 0)))
            elif ordinary == 'current_result':
                raw['current_result'] += fiscal_movement
                section_rows['current_result'].append((
                    account, fiscal_movement, 'current_result',
                    current_open.get(account_id, {}).get('count', 0)
                    + period.get(account_id, {}).get('count', 0),
                ))
            # The dynamic prior-year bridge includes the real, posted
            # unaffected-equity appropriation in this fiscal year exactly once.
            if not account.include_initial_balance:
                bridge = before_year
                if account.account_type == 'equity_unaffected':
                    bridge += fiscal_movement
                raw['brought_forward'] += bridge
                if (prior.get(account_id, {}).get('count', 0)
                        or (account.account_type == 'equity_unaffected'
                            and (current_open.get(account_id, {}).get('count', 0)
                                 or period.get(account_id, {}).get('count', 0)))):
                    section_rows['brought_forward'].append((
                        account, bridge, 'brought_forward',
                        prior.get(account_id, {}).get('count', 0)
                        + (current_open.get(account_id, {}).get('count', 0)
                           + period.get(account_id, {}).get('count', 0)
                           if account.account_type == 'equity_unaffected' else 0),
                    ))
        if self._money(source_balance, currency) != self._money(zero, currency):
            raise AccessError(_('The posted journal source does not balance.'))
        # Source balance is debit minus credit. Display flips liability,
        # equity and profit signs once, but never mutates source amounts.
        display = {
            key: (raw[key] if key == 'assets' else -raw[key])
            for key in self.SECTIONS
        }
        if self._money(display['assets'] - sum((display[key] for key in self.SECTIONS
                                                if key != 'assets'), zero), currency) != self._money(zero, currency):
            raise AccessError(_('The balance sheet equation does not balance.'))
        self._assert_complete_source(company, end, journal_ids)
        result = {
            'company': {'id': company.id, 'name': company.display_name,
                        'currency_code': currency.name},
            'period': {'date_from': fields.Date.to_string(_start),
                       'date_to': fields.Date.to_string(end),
                       'fiscal_start': fields.Date.to_string(fiscal_start)},
            'is_partial_journals': bool(journal_ids),
            'sections': [{
                'key': key,
                'amount': self._money(display[key], currency),
                'negative': display[key] < 0,
                'account_count': len(section_rows[key]),
            } for key in self.SECTIONS],
            'equation': {
                'assets': self._money(display['assets'], currency),
                'liabilities_equity_results': self._money(
                    sum((display[key] for key in self.SECTIONS if key != 'assets'), zero),
                    currency,
                ),
            },
        }
        return result, section_rows, currency

    def _formatted_rows(self, tuples, section, currency):
        sign = 1 if section == 'assets' else -1
        rows = []
        for account, balance, source_scope, count in tuples:
            amount = balance * sign
            rows.append({
                'id': account.id, 'code': account.code or '',
                'name': account.name or '', 'account_type': account.account_type,
                'amount': self._money(amount, currency),
                'negative': amount < 0, 'source_scope': source_scope,
                'source_line_count': count,
            })
        rows.sort(key=lambda row: (row['account_type'], row['code'], row['id']))
        return rows

    @api.model
    def get_report(self, filters):
        report, _rows, _currency = self._calculation(filters)
        return report

    @api.model
    def get_section_accounts(self, filters, section, page=1):
        if section not in self.SECTIONS or type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid balance sheet section and page.'))
        _report, section_rows, currency = self._calculation(filters)
        rows = self._formatted_rows(section_rows[section], section, currency)
        return {'section': section, 'page': page, 'page_size': self.PAGE_SIZE,
                'account_count': len(rows),
                'page_count': (len(rows) + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
                'accounts': rows[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE]}

    def _build_pdf_report(self, filters):
        report, section_rows, currency = self._calculation(filters)
        if sum(map(len, section_rows.values())) > 5000:
            raise ValidationError(_(
                'The PDF is limited to 5,000 account rows. Narrow the selected journals.'
            ))
        report['section_accounts'] = {
            key: self._formatted_rows(section_rows[key], key, currency)
            for key in self.SECTIONS
        }
        return report

    @api.model
    def get_account_action(self, filters, account_id, section):
        if type(account_id) is not int or account_id <= 0 or section not in self.SECTIONS:
            raise ValidationError(_('Select a valid account and section.'))
        report, section_rows, _currency = self._calculation(filters)
        matching = [entry for entry in section_rows[section] if entry[0].id == account_id]
        if len(matching) != 1 or not matching[0][3]:
            raise AccessError(_('The selected account has no available source entries.'))
        _account, _balance, source_scope, _count = matching[0]
        company_id = report['company']['id']
        fiscal_start = report['period']['fiscal_start']
        cutoff = report['period']['date_to']
        domain = [('company_id', '=', company_id), ('parent_state', '=', 'posted'),
                  ('account_id', '=', account_id)]
        if source_scope == 'current_result':
            domain.append(('date', '>=', fiscal_start))
        elif source_scope == 'brought_forward' and _account.account_type != 'equity_unaffected':
            domain.append(('date', '<', fiscal_start))
        domain.append(('date', '<=', cutoff))
        journal_ids = filters.get('journal_ids', [])
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items'),
                'res_model': 'account.move.line', 'views': [[False, 'list'], [False, 'form']],
                'target': 'current', 'domain': domain}

    @api.model
    def action_print(self, filters):
        if not isinstance(filters, dict) or filters.get('company_id') != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        self._filters(filters)
        return self.env.ref('baseer_balance_sheet_report.action_balance_sheet_pdf').report_action(
            [], data={'filters': filters}, config=False,
        )

"""Read-only supplier payables from posted Odoo journal items at a cutoff."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BaseerAgedPayable(models.AbstractModel):
    _name = 'baseer.aged.payable.report'
    _description = 'Baseer Supplier Aged Payables'

    PAGE_SIZE = 100
    SOURCE_BATCH = 1000
    MAX_SOURCE_LINES = 100000
    MAX_PDF_LINES = 5000
    _BUCKETS = ('not_due', 'd1_30', 'd31_60', 'd61_90', 'over_90')

    @staticmethod
    def _decimal(value):
        return Decimal(str(value or 0))

    @classmethod
    def _rounded(cls, value, currency):
        increment = cls._decimal(currency.rounding)
        if increment <= 0:
            raise ValidationError(_('The company currency has an invalid rounding increment.'))
        with localcontext() as context:
            context.prec = max(28, len(value.as_tuple().digits)
                               + len(increment.as_tuple().digits) + 4)
            rounded = ((value / increment).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                       * increment)
        return abs(rounded) if not rounded else rounded

    @classmethod
    def _money(cls, value, currency):
        amount = cls._rounded(value, currency)
        return f'{amount:,.{int(currency.decimal_places)}f}'

    @api.model
    def _check_accounting_access(self):
        if not any(self.env.user.has_group(group) for group in (
            'account.group_account_readonly',
            'account.group_account_user',
            'account.group_account_manager',
        )):
            raise AccessError(_('Accounting access is required.'))
        for model in ('res.company', 'account.account', 'account.journal',
                      'account.move', 'account.move.line',
                      'account.partial.reconcile', 'res.partner'):
            self.env[model].browse().check_access('read')

    @api.model
    def _cutoff(self, raw):
        if not isinstance(raw, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
            raise ValidationError(_('Select a valid cutoff date.'))
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise ValidationError(_('Select a valid cutoff date.')) from None

    @staticmethod
    def _page(raw):
        if type(raw) is not int or raw < 1:
            raise ValidationError(_('Select a valid page.'))
        return raw

    @api.model
    def get_context(self):
        self._check_accounting_access()
        company = self.env.company
        company.check_access('read')
        return {
            'cutoff_date': fields.Date.context_today(self).isoformat(),
            'currency_symbol': company.currency_id.symbol,
        }

    @api.model
    def _source_lines(self, company, cutoff):
        """Return a complete readable posted AR source, or fail closed.

        SQL compares row counts only. Financial values are read exclusively from
        access-controlled ORM records; custom record rules cannot silently drop
        a debt line or a reconciliation needed by the calculation.
        """
        aml = self.env['account.move.line'].with_context(active_test=False)
        domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('date', '<=', cutoff),
            ('account_id.account_type', '=', 'liability_payable'),
        ]
        count = aml.search_count(domain)
        if count > self.MAX_SOURCE_LINES:
            raise ValidationError(_(
                'This period has too many payable lines for one report. Narrow the cutoff or contact an administrator.'
            ))
        aml.flush_model(['company_id', 'parent_state', 'date', 'account_id'])
        self.env.cr.execute('''
            SELECT COUNT(*)
              FROM account_move_line AS line
              JOIN account_account AS account ON account.id = line.account_id
             WHERE line.company_id = %s AND line.parent_state = 'posted'
               AND line.date <= %s AND account.account_type = 'liability_payable'
        ''', (company.id, cutoff))
        if count != self.env.cr.fetchone()[0]:
            raise AccessError(_('The complete payable source is not available.'))
        lines = aml.search(domain, order='id', limit=self.MAX_SOURCE_LINES + 1)
        if len(lines) != count:
            raise AccessError(_('The complete payable source is not available.'))
        lines.check_access('read')
        for records in (lines.mapped('move_id'), lines.mapped('account_id'),
                        lines.mapped('journal_id'), lines.mapped('partner_id')):
            records.check_access('read')
        return lines

    @api.model
    def _partials(self, lines, cutoff, company):
        partial_model = self.env['account.partial.reconcile']
        seen = set()
        result = partial_model.browse()
        for start in range(0, len(lines), self.SOURCE_BATCH):
            ids = lines[start:start + self.SOURCE_BATCH].ids
            if not ids:
                continue
            domain = [
                ('max_date', '<=', cutoff), '|',
                ('debit_move_id', 'in', ids), ('credit_move_id', 'in', ids),
            ]
            partials = partial_model.search(domain)
            partial_model.flush_model(['max_date', 'debit_move_id', 'credit_move_id'])
            self.env.cr.execute('''
                SELECT COUNT(*) FROM account_partial_reconcile
                 WHERE max_date <= %s
                   AND (debit_move_id = ANY(%s) OR credit_move_id = ANY(%s))
            ''', (cutoff, ids, ids))
            if len(partials) != self.env.cr.fetchone()[0]:
                raise AccessError(_('The complete reconciliation source is not available.'))
            partials.check_access('read')
            for partial in partials:
                if partial.company_id.id != company.id:
                    raise AccessError(_('A reconciliation crosses the selected company.'))
                if partial.id not in seen:
                    seen.add(partial.id)
                    result |= partial
        counterpart_lines = result.mapped('debit_move_id') | result.mapped('credit_move_id')
        counterpart_lines.check_access('read')
        for records in (counterpart_lines.mapped('move_id'),
                        counterpart_lines.mapped('account_id'),
                        counterpart_lines.mapped('journal_id'),
                        counterpart_lines.mapped('partner_id')):
            records.check_access('read')
        return result

    @staticmethod
    def _kind(line, amount):
        move_type = line.move_id.move_type
        if amount > 0:
            if move_type == 'in_invoice':
                return 'invoice'
            if move_type == 'in_refund':
                return 'unusual'
            return 'direct_claim'
        if move_type == 'in_refund':
            return 'credit_note'
        if move_type == 'in_invoice':
            return 'unusual'
        return 'counter_balance'

    @staticmethod
    def _bucket(line, cutoff, amount):
        if amount < 0:
            return 'counter'
        days = (cutoff - (line.date_maturity or line.date)).days
        if days <= 0:
            return 'not_due'
        if days <= 30:
            return 'd1_30'
        if days <= 60:
            return 'd31_60'
        if days <= 90:
            return 'd61_90'
        return 'over_90'

    @staticmethod
    def _counter_age_bucket(line, cutoff):
        """Age a separate counter-balance from its posted source date, not invoice due date."""
        days = (cutoff - line.date).days
        if days <= 0:
            return 'not_due'
        if days <= 30:
            return 'd1_30'
        if days <= 60:
            return 'd31_60'
        if days <= 90:
            return 'd61_90'
        return 'over_90'

    @api.model
    def _snapshot(self, cutoff):
        self._check_accounting_access()
        company = self.env.company
        company.check_access('read')
        currency = company.currency_id
        lines = self._source_lines(company, cutoff)
        open_by_id = {line.id: self._decimal(line.balance) for line in lines}
        partials = self._partials(lines, cutoff, company)
        for partial in partials:
            amount = self._decimal(partial.amount)
            debit_id = partial.debit_move_id.id
            credit_id = partial.credit_move_id.id
            if debit_id in open_by_id:
                open_by_id[debit_id] -= amount
            if credit_id in open_by_id:
                open_by_id[credit_id] += amount

        buckets = dict.fromkeys(self._BUCKETS, Decimal('0'))
        counter_buckets = dict.fromkeys(self._BUCKETS, Decimal('0'))
        partners = defaultdict(lambda: {
            'payables': Decimal('0'), 'counter_balances': Decimal('0'),
            'net': Decimal('0'), 'open_count': 0, 'lines': [],
        })
        all_rows = []
        payables = Decimal('0')
        counter_balances = Decimal('0')
        for line in lines:
            amount = self._rounded(-open_by_id[line.id], currency)
            if not amount:
                continue
            partner_id = line.partner_id.id or False
            group = partners[partner_id]
            bucket = self._bucket(line, cutoff, amount)
            row = {
                'id': line.id,
                'partner_id': partner_id,
                'date': line.date.isoformat(),
                'date_maturity': line.date_maturity.isoformat() if line.date_maturity else '',
                'move_name': line.move_id.name or line.move_id.ref or '',
                'kind': self._kind(line, amount),
                'bucket': bucket,
                'counter_age_bucket': self._counter_age_bucket(line, cutoff) if amount < 0 else '',
                'amount': amount,
            }
            group['lines'].append(row)
            group['net'] += amount
            group['open_count'] += 1
            all_rows.append(row)
            if amount > 0:
                payables += amount
                group['payables'] += amount
                buckets[bucket] += amount
            else:
                counter_balance = -amount
                counter_balances += counter_balance
                group['counter_balances'] += counter_balance
                counter_buckets[self._counter_age_bucket(line, cutoff)] += counter_balance

        partner_rows = []
        for partner_id, values in partners.items():
            partner = self.env['res.partner'].browse(partner_id) if partner_id else None
            partner_rows.append({
                'id': partner_id,
                'name': partner.display_name if partner else _('Unassigned'),
                'payables': self._money(values['payables'], currency),
                'counter_balances': self._money(values['counter_balances'], currency),
                'net': self._money(values['net'], currency),
                'open_count': values['open_count'],
                '_lines': values['lines'],
            })
        partner_rows.sort(key=lambda row: (row['name'].casefold(), row['id'] or 0))
        return {
            'currency': currency,
            'partners': partner_rows,
            'all_rows': all_rows,
            'summary': {
                'payables': self._money(payables, currency),
                'counter_balances': self._money(counter_balances, currency),
                'net': self._money(payables - counter_balances, currency),
                'buckets': {key: self._money(value, currency)
                            for key, value in buckets.items()},
                'counter_buckets': {key: self._money(value, currency)
                                   for key, value in counter_buckets.items()},
            },
        }

    @api.model
    def get_report(self, options):
        if not isinstance(options, dict) or set(options) != {'cutoff_date', 'page'}:
            raise ValidationError(_('Select a valid cutoff date and page.'))
        cutoff = self._cutoff(options['cutoff_date'])
        page = self._page(options['page'])
        snapshot = self._snapshot(cutoff)
        partners = snapshot['partners']
        page_count = max(1, (len(partners) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if page > page_count:
            raise ValidationError(_('The requested page does not exist.'))
        visible = partners[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE]
        return {
            'cutoff_date': cutoff.isoformat(),
            'currency_symbol': snapshot['currency'].symbol,
            'summary': snapshot['summary'],
            'partners': [{key: value for key, value in row.items() if key != '_lines'}
                         for row in visible],
            'page': page,
            'page_count': page_count,
            'partner_count': len(partners),
        }

    @api.model
    def get_partner_lines(self, options):
        if not isinstance(options, dict) or set(options) != {'cutoff_date', 'partner_id', 'page'}:
            raise ValidationError(_('Select a valid partner and page.'))
        cutoff = self._cutoff(options['cutoff_date'])
        page = self._page(options['page'])
        partner_id = options['partner_id']
        if partner_id is not False and (type(partner_id) is not int or partner_id < 1):
            raise ValidationError(_('Select a valid partner.'))
        snapshot = self._snapshot(cutoff)
        partner = next((row for row in snapshot['partners'] if row['id'] == partner_id), None)
        rows = list(partner['_lines']) if partner else []
        rows.sort(key=lambda row: (row['date_maturity'] or row['date'], row['id']))
        page_count = max(1, (len(rows) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if page > page_count:
            raise ValidationError(_('The requested page does not exist.'))
        return {
            'lines': [{**{key: value for key, value in row.items() if key != 'amount'},
                       'open': self._money(row['amount'], snapshot['currency'])}
                      for row in rows[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE]],
            'page': page,
            'page_count': page_count,
        }

    @api.model
    def action_open_line(self, options):
        if not isinstance(options, dict) or set(options) != {'line_id', 'cutoff_date'}:
            raise ValidationError(_('Select a valid journal item.'))
        line_id = options['line_id']
        if type(line_id) is not int or line_id < 1:
            raise ValidationError(_('Select a valid journal item.'))
        cutoff = self._cutoff(options['cutoff_date'])
        snapshot = self._snapshot(cutoff)
        if line_id not in {row['id'] for row in snapshot['all_rows']}:
            raise AccessError(_('The journal item is not available in this report.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Items'),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('id', '=', line_id)],
            'target': 'current',
        }

    @api.model
    def action_print(self, options):
        if not isinstance(options, dict) or set(options) != {'cutoff_date'}:
            raise ValidationError(_('Select a valid cutoff date.'))
        cutoff = self._cutoff(options['cutoff_date'])
        self._check_accounting_access()
        return self.env.ref('baseer_aged_payable_report.action_aged_payable_pdf').report_action(
            [], data={'cutoff_date': cutoff.isoformat()}, config=False,
        )

    @api.model
    def _build_pdf(self, cutoff):
        snapshot = self._snapshot(cutoff)
        if len(snapshot['all_rows']) > self.MAX_PDF_LINES:
            raise ValidationError(_(
                'Too many open payable items to print at once. Narrow the report before printing.'
            ))
        currency = snapshot['currency']
        by_partner = {row['id']: row for row in snapshot['partners']}
        lines = []
        for row in sorted(snapshot['all_rows'], key=lambda item: (
            by_partner[item['partner_id']]['name'].casefold(),
            item['date_maturity'] or item['date'], item['id'],
        )):
            lines.append({
                **{key: value for key, value in row.items() if key != 'amount'},
                'partner_name': by_partner[row['partner_id']]['name'],
                'open': self._money(row['amount'], currency),
            })
        return {
            'cutoff_date': cutoff.isoformat(),
            'currency_symbol': currency.symbol,
            'summary': snapshot['summary'],
            'lines': lines,
            'generated_at': fields.Datetime.now(),
        }

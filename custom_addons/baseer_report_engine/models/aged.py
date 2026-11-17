"""As-of open-item aging, using the partner ledger's filters and conventions."""
from collections import defaultdict
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import format_date

from .engine import _analytic_share
from .ledger import _item_labels


class BaseerAgedEngine(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _aged_entries(self, options):
        date = fields.Date.to_date(options['date_to'])
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[], unreconciled=False)
        lines = self.env['account.move.line'].search(
            self._base_domain(options) + self._partner_domain(unfiltered) + [('date', '<=', date)],
            order='date, move_name, id')
        partials = self.env['account.partial.reconcile'].search([
            '|', ('debit_move_id', 'in', lines.ids), ('credit_move_id', 'in', lines.ids)]) if lines else self.env['account.partial.reconcile']
        by_line = defaultdict(list)
        for partial in partials:
            by_line[partial.debit_move_id.id].append((partial, partial.credit_move_id))
            by_line[partial.credit_move_id.id].append((partial, partial.debit_move_id))
        attribution = defaultdict(dict)
        for line in lines.filtered(lambda l: not l.partner_id):
            for partial, other in by_line[line.id]:
                if other.partner_id and partial.max_date > date:
                    pid = other.partner_id.id
                    attribution[line.id][pid] = attribution[line.id].get(pid, Decimal(0)) + Decimal(str(partial.amount))
        selected = self._selected_attribution_partners(options, attribution)
        selected_direct = set(lines.partner_id.ids)
        if options['partner_ids']:
            selected_direct &= set(options['partner_ids'])
        if options['partner_category_ids'] and selected_direct:
            selected_direct = set(self.env['res.partner'].search([('id', 'in', list(selected_direct)), ('category_id', 'in', options['partner_category_ids'])]).ids)
        entries = []
        for line in lines:
            balance = Decimal(str(line.balance))
            settled = sum((Decimal(str(p.amount)) for p, _other in by_line[line.id] if p.max_date <= date), Decimal(0))
            residual = balance - settled * (1 if balance > 0 else -1)
            if line.company_currency_id.is_zero(float(residual)):
                continue
            share = _analytic_share(line.analytic_distribution, set(options['analytic_account_ids'])) if options['analytic_account_ids'] else Decimal(1)
            allocations = {}
            if line.partner_id:
                if line.partner_id.id in selected_direct:
                    allocations[line.partner_id.id] = residual
            else:
                remaining = abs(residual)
                for pid, amount in attribution[line.id].items():
                    portion = min(remaining, amount)
                    remaining -= portion
                    if pid in selected:
                        allocations[pid] = portion if residual > 0 else -portion
                if remaining and not options['partner_ids'] and not options['partner_category_ids']:
                    allocations[0] = remaining if residual > 0 else -remaining
            aging_date = (line.date_maturity if options['aging_basis'] == 'due_date' else line.move_id.invoice_date) or line.date
            days = (date - aging_date).days
            bucket = 0 if days <= 0 else min(5, (days - 1) // options['period_length'] + 1)
            for pid, amount in allocations.items():
                # Credit balances on payable accounts represent money owed to vendors.
                value = self._ledger_convert(amount * share * (-1 if options['aged_payable'] else 1), line.company_id, date)
                entries.append((pid, line, bucket, value))
        return entries

    @api.model
    def _aged_amounts(self, values, drill=False):
        return [self._serialize_amount({'key': key, 'kind': 'ledger'}, value, self.env.company.currency_id, drill)
                for key, value in zip(('at_date', 'period1', 'period2', 'period3', 'period4', 'older', 'total'), values)]

    @api.model
    def _build_aged(self, report, options):
        entries = self._aged_entries(options)
        grouped = defaultdict(lambda: [Decimal(0)] * 7)
        for pid, _line, bucket, value in entries:
            grouped[pid][bucket] += value
            grouped[pid][6] += value
        partners = self.env['res.partner'].browse([pid for pid in grouped if pid]).exists()
        names = {partner.id: partner.display_name for partner in partners}
        rows = [{'code': 'header', 'name': report.name, 'level': 0, 'display': 'section', 'foldable': False, 'has_accounts': False, 'amounts': self._aged_amounts([0] * 7)}]
        totals = [Decimal(0)] * 7
        for pid in sorted(grouped, key=lambda x: (not bool(x), names.get(x, '').casefold(), x)):
            values = grouped[pid]
            totals = [a + b for a, b in zip(totals, values)]
            rows.append({'id': pid, 'partner_id': pid, 'code': 'partner_%s' % pid, 'name': names.get(pid) or _('Unknown Partner'), 'level': 0, 'display': 'line', 'foldable': True, 'has_accounts': True, 'amounts': self._aged_amounts(values, True)})
        total_name = _('Total Aged Payable') if options['aged_payable'] else _('Total Aged Receivable')
        rows.append({'code': 'total', 'name': total_name, 'level': 0, 'display': 'total', 'foldable': False, 'has_accounts': False, 'amounts': self._aged_amounts(totals)})
        payload = self._build(report, options)
        payload['report']['report_kind'] = 'aged'
        payload['lines'] = rows
        n = options['period_length']
        labels = [_('Invoice Date'), _('At Date')] + ['%s-%s' % (1 + i*n, (i+1)*n) for i in range(4)] + [_('Older'), _('Total')]
        keys = ['invoice_date', 'at_date', 'period1', 'period2', 'period3', 'period4', 'older', 'total']
        payload['columns'] = [{'key': k, 'label': v, 'kind': 'ledger', 'figure': k} for k, v in zip(keys, labels)]
        payload['column_groups'] = [{'label': options['columns'][0]['label'], 'colspan': 8, 'kind': 'period', 'period_key': 'c0'}]
        payload['options']['account_filter_label'] = ', '.join(dict(self._partner_type_labels())[k] for k in options['account_types'])
        return payload

    @api.model
    def _aged_page(self, options, partner_id, offset, limit):
        if type(partner_id) is not int or partner_id < 0:
            raise AccessError(_('Choose an account from this line.'))
        entries = [entry for entry in self._aged_entries(options) if entry[0] == partner_id]
        if not entries:
            raise AccessError(_('Choose an account from this line.'))
        rows = []
        for _pid, line, bucket, value in entries[offset:offset + limit]:
            move, detail, name = _item_labels(line.move_name or line.move_id.name, line.name)
            values = [Decimal(0)] * 7
            values[bucket] = values[6] = value
            rows.append({'type': 'item', 'id': line.id, 'name': name, 'move_label': move, 'detail_label': detail,
                         'invoice_date': format_date(self.env, line.move_id.invoice_date) if line.move_id.invoice_date else '',
                         'amounts': self._aged_amounts(values)})
        more = offset + limit < len(entries)
        if not more:
            totals = [Decimal(0)] * 7
            for _pid, _line, bucket, value in entries:
                totals[bucket] += value
                totals[6] += value
            partner = self.env['res.partner'].browse(partner_id)
            name = partner.display_name if partner else _('Unknown Partner')
            rows.append({'type': 'total', 'name': _('Total %s') % name, 'amounts': self._aged_amounts(totals)})
        return {'rows': rows, 'has_more': more, 'next_offset': offset + limit if more else False}

    @api.model
    def _aged_action(self, options, line_code, column_key, partner_id):
        if partner_id is False:
            partner_id = 0
        keys = ('at_date', 'period1', 'period2', 'period3', 'period4', 'older')
        if type(partner_id) is not int or partner_id < 0 or line_code != 'partner_%s' % partner_id or column_key not in keys + ('total', 'end'):
            raise ValidationError(_('The report options are not valid.'))
        entries = self._aged_entries(options)
        if not any(pid == partner_id for pid, _line, _bucket, _value in entries):
            raise AccessError(_('Choose an account from this line.'))
        ids = [line.id for pid, line, bucket, _value in entries if pid == partner_id and (column_key in ('total', 'end') or bucket == keys.index(column_key))]
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items'), 'res_model': 'account.move.line',
                'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'target': 'current', 'domain': [('id', 'in', ids)]}

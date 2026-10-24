"""Exact, bounded activity amount composition with guarded source membership."""
from decimal import Decimal
import re
from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.addons.baseer_reports_menu.report_drill import drill_result, exact_selector, positive_id
from odoo.addons.baseer_reports_menu.report_values import require_active_filters, source_money


class ActivityDrill(models.AbstractModel):
    _inherit = 'baseer.account.activity'

    def _drill_scope(self, filters, selector):
        require_active_filters(self.env, filters, {'account_id', 'date_from', 'date_to'})
        if set(filters) != {'company_id', 'account_id', 'date_from', 'date_to'}:
            raise ValidationError(_('Select an account and period.'))
        positive_id(filters['account_id'])
        if any(type(filters[key]) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', filters[key])
               for key in ('date_from', 'date_to')):
            raise ValidationError(_('Select valid report dates.'))
        kind = selector.get('kind') if type(selector) is dict else None
        if kind == 'summary':
            exact_selector(selector, {'kind', 'measure'})
            allowed = ('opening', 'debit', 'credit', 'closing')
        elif kind == 'line':
            exact_selector(selector, {'kind', 'measure', 'line_id'})
            positive_id(selector['line_id'])
            allowed = ('debit', 'credit', 'running')
        else:
            raise ValidationError(_('Select a valid report detail.'))
        if type(selector['measure']) is not str or selector['measure'] not in allowed:
            raise ValidationError(_('Select a valid report amount.'))
        summary = self.get_activity(*[filters[key] for key in ('company_id', 'account_id', 'date_from', 'date_to')])
        # Existing complete-source guard verifies hidden opening/period rows and linked records.
        self._export_source(filters)
        account = self.env['account.account'].browse(filters['account_id'])
        start, end = (fields.Date.to_date(filters[key]) for key in ('date_from', 'date_to'))
        domain = (Domain('company_id', '=', self.env.company.id) & Domain('account_id', '=', account.id)
                  & Domain('parent_state', '=', 'posted') & Domain('date', '<=', end))
        if not account.include_initial_balance:
            domain &= Domain('date', '>=', self.env.company.compute_fiscalyear_dates(start)['date_from'])
        lines = self.env['account.move.line'].with_context(active_test=False).search(domain, order='date,id')
        measure = selector['measure']
        if kind == 'line':
            target = lines.filtered(lambda line: line.id == selector['line_id'] and start <= line.date <= end)
            if len(target) != 1:
                raise AccessError(_('The source is not in this report.'))
            if measure == 'running':
                selected = lines.filtered(lambda line: (line.date, line.id) <= (target.date, target.id))
                value = sum((self._amount(line.debit) - self._amount(line.credit) for line in selected), Decimal('0'))
            else:
                selected = target
                value = self._amount(target[measure])
        else:
            value = source_money(summary[measure])
            selected = lines.filtered(lambda line: line.date < start) if measure == 'opening' else lines
            if measure in ('debit', 'credit'):
                selected = lines.filtered(lambda line: line.date >= start and self._amount(line[measure]) != 0)
        return summary, selected, value

    def _get_drilldown(self, filters, selector, page=1):
        summary, lines, value = self._drill_scope(filters, selector)
        ar = (self.env.lang or '').startswith('ar')
        measure = selector['measure']
        labels = {'opening': ('الرصيد الافتتاحي', 'Opening balance'), 'closing': ('الرصيد الختامي', 'Closing balance'),
                  'debit': ('مدين', 'Debit'), 'credit': ('دائن', 'Credit'), 'running': ('الرصيد الجاري', 'Running balance')}
        title = labels[measure][0 if ar else 1]
        basis = ('القيمة من الحساب المحدد والقيود المرحلة. الرصيد = مجموع المدين ناقص الدائن حتى حدّه؛ لا يمثل مجموع الصفحة.' if ar else
                 'Selected account and posted entries. Balance is debit less credit through its cutoff; it is not a page total.')
        columns = [{'key': 'date', 'label': 'التاريخ' if ar else 'Date'},
                   {'key': 'entry', 'label': 'القيد' if ar else 'Entry'},
                   {'key': 'amount', 'label': 'المساهمة' if ar else 'Contribution', 'numeric': True}]
        rows = []
        currency = self.env.company.currency_id
        for line in lines:
            amount = self._amount(line[measure]) if measure in ('debit', 'credit') else self._amount(line.debit) - self._amount(line.credit)
            rows.append({'key': line.id, 'cells': {'date': fields.Date.to_string(line.date), 'entry': line.move_id.name or '',
                         'amount': self._format_money(amount, currency)},
                         'source': {'kind': 'source', 'parent': dict(selector), 'line_id': line.id}})
        return drill_result(title + ' · ' + summary['account_name'], self._format_money(value, currency), basis, columns, rows, page)

    def _open_drill_source(self, filters, selector):
        exact_selector(selector, {'kind', 'parent', 'line_id'})
        if selector['kind'] != 'source':
            raise ValidationError(_('Select a valid source.'))
        positive_id(selector['line_id'])
        _summary, lines, _value = self._drill_scope(filters, selector['parent'])
        source = lines.filtered(lambda line: line.id == selector['line_id'])
        if len(source) != 1:
            raise AccessError(_('The source is not in this report detail.'))
        return {'type': 'ir.actions.act_window', 'name': _('Journal Entry'), 'res_model': 'account.move',
                'res_id': source.move_id.id, 'views': [[False, 'form']], 'target': 'current'}

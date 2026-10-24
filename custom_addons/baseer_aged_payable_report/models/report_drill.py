"""Read-only fixed drill selectors for the aged-payable collector."""

from decimal import Decimal

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.baseer_reports_menu.report_drill import drill_result, exact_selector, positive_id


_BUCKETS = {'not_due', 'd1_30', 'd31_60', 'd61_90', 'over_90'}


class AgedPayableDrill(models.AbstractModel):
    _inherit = 'baseer.aged.payable.report'

    def _drill_filters(self, filters):
        if type(filters) is not dict or set(filters) != {'company_id', 'cutoff_date'}:
            raise ValidationError(_('Select valid report filters.'))
        if type(filters['company_id']) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Select the active company report.'))
        return self._cutoff(filters['cutoff_date'])

    def _drill_selection(self, snapshot, selector):
        rows = snapshot['all_rows']
        if type(selector) is not dict or type(selector.get('kind')) is not str:
            raise ValidationError(_('Select a valid report detail.'))
        kind = selector['kind']
        if kind == 'summary':
            exact_selector(selector, ('kind', 'metric'))
            metric = selector['metric']
            if type(metric) is not str or metric not in {'payables', 'counter_balances', 'net'}:
                raise ValidationError(_('Select a valid report detail.'))
            if metric == 'payables':
                selected = [row for row in rows if row['amount'] > 0]
            elif metric == 'counter_balances':
                selected = [row for row in rows if row['amount'] < 0]
            else:
                selected = list(rows)
            return selected
        if kind == 'bucket':
            exact_selector(selector, ('kind', 'side', 'bucket'))
            side, bucket = selector['side'], selector['bucket']
            if type(side) is not str or type(bucket) is not str or side not in {'payable', 'counter'} or bucket not in _BUCKETS:
                raise ValidationError(_('Select a valid report detail.'))
            if side == 'payable':
                return [row for row in rows if row['amount'] > 0 and row['bucket'] == bucket]
            return [row for row in rows if row['amount'] < 0 and row['counter_age_bucket'] == bucket]
        if kind == 'partner':
            exact_selector(selector, ('kind', 'partner_id', 'metric'))
            partner_id, metric = selector['partner_id'], selector['metric']
            if partner_id is not False and (type(partner_id) is not int or partner_id < 1):
                raise ValidationError(_('Select a valid partner.'))
            if type(metric) is not str or metric not in {'payables', 'counter_balances', 'net'}:
                raise ValidationError(_('Select a valid report detail.'))
            selected = [row for row in rows if row['partner_id'] == partner_id]
            if metric == 'payables':
                selected = [row for row in selected if row['amount'] > 0]
            elif metric == 'counter_balances':
                selected = [row for row in selected if row['amount'] < 0]
            return selected
        if kind == 'line':
            exact_selector(selector, ('kind', 'line_id'))
            line_id = positive_id(selector['line_id'])
            selected = [row for row in rows if row['id'] == line_id]
            if not selected:
                raise AccessError(_('The journal item is not available in this report.'))
            return selected
        raise ValidationError(_('Select a valid report detail.'))

    def _drill_title(self, selector):
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        labels = {'payables': 'مديونيات الموردين' if ar else 'Payables',
                  'counter_balances': 'الأرصدة المدينة المقابلة' if ar else 'Counter-balances',
                  'net': 'الصافي' if ar else 'Net'}
        return labels.get(selector.get('metric'), 'تفاصيل مديونيات الموردين' if ar else 'Aged payable details')

    def _drill_total(self, selector, rows):
        amount = sum((row['amount'] for row in rows), Decimal('0'))
        if selector['kind'] == 'summary' and selector['metric'] == 'counter_balances':
            return -amount
        if selector['kind'] == 'bucket' and selector['side'] == 'counter':
            return -amount
        if selector['kind'] == 'partner' and selector['metric'] == 'counter_balances':
            return -amount
        return amount

    @api.model
    def _get_drilldown(self, filters, selector, page):
        cutoff = self._drill_filters(filters)
        snapshot = self._snapshot(cutoff)
        selected = self._drill_selection(snapshot, selector)
        partner_names = {row['id']: row['name'] for row in snapshot['partners']}
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        columns = [
            {'key': 'partner', 'label': 'المورد' if ar else 'Supplier'},
            {'key': 'date', 'label': 'التاريخ' if ar else 'Date'},
            {'key': 'due', 'label': 'الاستحقاق' if ar else 'Due date'},
            {'key': 'entry', 'label': 'القيد' if ar else 'Entry'},
            {'key': 'bucket', 'label': 'فئة التقادم' if ar else 'Age bucket'},
            {'key': 'open', 'label': 'المتبقي' if ar else 'Open amount', 'numeric': True},
        ]
        result_rows = []
        for row in sorted(selected, key=lambda item: (item['date_maturity'] or item['date'], item['id'])):
            result_rows.append({
                'key': str(row['id']),
                'cells': {'partner': partner_names.get(row['partner_id'], _('Unassigned')),
                          'date': row['date'], 'due': row['date_maturity'] or '—',
                          'entry': row['move_name'], 'bucket': row['counter_age_bucket'] or row['bucket'],
                          'open': self._money(row['amount'], snapshot['currency'])},
                'source': {'kind': 'source', 'parent': dict(selector), 'line_id': row['id']},
            })
        basis = ('إعادة بناء حالية للأرصدة والتسويات حتى تاريخ القطع؛ ليست لقطة مجمّدة.' if ar
                 else 'Current reconstruction of posted balances and reconciliations at the cutoff; not a frozen snapshot.')
        if ((selector['kind'] == 'summary' and selector['metric'] == 'counter_balances') or
                (selector['kind'] == 'bucket' and selector['side'] == 'counter') or
                (selector['kind'] == 'partner' and selector['metric'] == 'counter_balances')):
            basis += (' القيمة الرئيسية مقدار الرصيد المقابل، بينما السطور مصدر موقّع.' if ar
                      else ' The headline is the counter-balance magnitude; source rows remain signed.')
        return drill_result(self._drill_title(selector), self._money(self._drill_total(selector, selected), snapshot['currency']),
                            basis, columns, result_rows, page)

    @api.model
    def _open_drill_source(self, filters, selector):
        exact_selector(selector, ('kind', 'parent', 'line_id'))
        if selector['kind'] != 'source' or type(selector['parent']) is not dict:
            raise ValidationError(_('Select a valid source.'))
        cutoff = self._drill_filters(filters)
        snapshot = self._snapshot(cutoff)
        selected = self._drill_selection(snapshot, selector['parent'])
        line_id = positive_id(selector['line_id'])
        if line_id not in {row['id'] for row in selected}:
            raise AccessError(_('The journal item is not available in this report.'))
        line = self.env['account.move.line'].browse(line_id).exists()
        if not line:
            raise AccessError(_('The journal item is not available in this report.'))
        line.check_access('read')
        line.check_access_rule('read')
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items'),
                'res_model': 'account.move.line', 'view_mode': 'list,form',
                'domain': [('id', '=', line.id)], 'target': 'current'}

"""Read-only fixed drill selectors for the aged-receivable collector."""

from decimal import Decimal

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.baseer_reports_menu.report_drill import drill_result, exact_selector, positive_id


_BUCKETS = {'not_due', 'd1_30', 'd31_60', 'd61_90', 'over_90'}


class AgedReceivableDrill(models.AbstractModel):
    _inherit = 'baseer.aged.receivable.report'

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
            if type(metric) is not str or metric not in {'receivables', 'credits', 'net'}:
                raise ValidationError(_('Select a valid report detail.'))
            if metric == 'receivables':
                selected, total = [row for row in rows if row['amount'] > 0], None
            elif metric == 'credits':
                selected, total = [row for row in rows if row['amount'] < 0], None
            else:
                selected, total = list(rows), None
            return metric, selected, total
        if kind == 'bucket':
            exact_selector(selector, ('kind', 'side', 'bucket'))
            side, bucket = selector['side'], selector['bucket']
            if type(side) is not str or type(bucket) is not str or side not in {'receivable', 'credit'} or bucket not in _BUCKETS:
                raise ValidationError(_('Select a valid report detail.'))
            if side == 'receivable':
                selected = [row for row in rows if row['amount'] > 0 and row['bucket'] == bucket]
            else:
                selected = [row for row in rows if row['amount'] < 0 and row['credit_age_bucket'] == bucket]
            return f'{side}:{bucket}', selected, None
        if kind == 'partner':
            exact_selector(selector, ('kind', 'partner_id', 'metric'))
            partner_id, metric = selector['partner_id'], selector['metric']
            if partner_id is not False and (type(partner_id) is not int or partner_id < 1):
                raise ValidationError(_('Select a valid partner.'))
            if type(metric) is not str or metric not in {'receivables', 'credits', 'net'}:
                raise ValidationError(_('Select a valid report detail.'))
            selected = [row for row in rows if row['partner_id'] == partner_id]
            if metric == 'receivables':
                selected = [row for row in selected if row['amount'] > 0]
            elif metric == 'credits':
                selected = [row for row in selected if row['amount'] < 0]
            return f'partner:{partner_id}:{metric}', selected, None
        if kind == 'line':
            exact_selector(selector, ('kind', 'line_id'))
            line_id = positive_id(selector['line_id'])
            selected = [row for row in rows if row['id'] == line_id]
            if not selected:
                raise AccessError(_('The journal item is not available in this report.'))
            return f'line:{line_id}', selected, None
        raise ValidationError(_('Select a valid report detail.'))

    def _drill_title(self, selector):
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        labels = {
            'receivables': 'الذمم المدينة' if ar else 'Receivables',
            'credits': 'الأرصدة الدائنة غير المطبقة' if ar else 'Unapplied credits',
            'net': 'الصافي' if ar else 'Net',
        }
        if selector['kind'] == 'summary':
            return labels[selector['metric']]
        if selector['kind'] == 'partner':
            return labels[selector['metric']]
        return 'تفاصيل الذمم المدينة' if ar else 'Aged receivable details'

    def _drill_total(self, selector, rows):
        amount = sum((row['amount'] for row in rows), Decimal('0'))
        if selector['kind'] == 'summary' and selector['metric'] == 'credits':
            return -amount
        if selector['kind'] == 'bucket' and selector['side'] == 'credit':
            return -amount
        if selector['kind'] == 'partner' and selector['metric'] == 'credits':
            return -amount
        return amount

    @api.model
    def _get_drilldown(self, filters, selector, page):
        cutoff = self._drill_filters(filters)
        snapshot = self._snapshot(cutoff)
        _selection_key, selected, _unused_total = self._drill_selection(snapshot, selector)
        partner_names = {row['id']: row['name'] for row in snapshot['partners']}
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        columns = [
            {'key': 'partner', 'label': 'العميل' if ar else 'Customer'},
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
                'cells': {
                    'partner': partner_names.get(row['partner_id'], _('Unassigned')),
                    'date': row['date'], 'due': row['date_maturity'] or '—',
                    'entry': row['move_name'],
                    'bucket': row['credit_age_bucket'] or row['bucket'],
                    'open': self._money(row['amount'], snapshot['currency']),
                },
                'source': {'kind': 'source', 'parent': dict(selector), 'line_id': row['id']},
            })
        basis = ('إعادة بناء حالية للأرصدة والتسويات حتى تاريخ القطع؛ ليست لقطة مجمّدة.' if ar
                 else 'Current reconstruction of posted balances and reconciliations at the cutoff; not a frozen snapshot.')
        if ((selector['kind'] == 'summary' and selector['metric'] == 'credits') or
                (selector['kind'] == 'bucket' and selector['side'] == 'credit') or
                (selector['kind'] == 'partner' and selector['metric'] == 'credits')):
            basis += (' القيمة الرئيسية مقدار الرصيد الدائن، بينما السطور مصدر موقّع.' if ar
                      else ' The headline is the credit magnitude; source rows remain signed.')
        return drill_result(self._drill_title(selector), self._money(self._drill_total(selector, selected), snapshot['currency']),
                            basis, columns, result_rows, page)

    @api.model
    def _open_drill_source(self, filters, selector):
        exact_selector(selector, ('kind', 'parent', 'line_id'))
        if selector['kind'] != 'source' or type(selector['parent']) is not dict:
            raise ValidationError(_('Select a valid source.'))
        cutoff = self._drill_filters(filters)
        snapshot = self._snapshot(cutoff)
        _selection_key, selected, _unused_total = self._drill_selection(snapshot, selector['parent'])
        line_id = positive_id(selector['line_id'])
        if line_id not in {row['id'] for row in selected}:
            raise AccessError(_('The journal item is not available in this report.'))
        line = self.env['account.move.line'].browse(line_id).exists()
        if not line:
            raise AccessError(_('The journal item is not available in this report.'))
        line.check_access('read')
        line.check_access_rule('read')
        return {
            'type': 'ir.actions.act_window', 'name': _('Journal Items'),
            'res_model': 'account.move.line', 'view_mode': 'list,form',
            'domain': [('id', '=', line.id)], 'target': 'current',
        }

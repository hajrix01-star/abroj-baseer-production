"""Read-only fixed drill selectors for the tobacco-fee register."""

from decimal import Decimal

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.baseer_reports_menu.report_drill import drill_result, exact_selector, positive_id
from .tobacco_report import _format_money


class TobaccoReportDrill(models.TransientModel):
    _inherit = 'baseer.pos.tobacco.report.wizard'

    def _drill_report(self, filters):
        keys = {'company_id', 'period', 'month', 'year', 'date_from', 'date_to', 'show_products'}
        if type(filters) is not dict or set(filters) != keys:
            raise ValidationError(_('Select valid report filters.'))
        if type(filters['company_id']) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Select the active company report.'))
        company, values = self._hub_wizard_values({**filters, 'page': 1})
        wizard = self.with_company(company).new(values)
        report = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees'].with_company(
            company,
        )._build_report(wizard)
        return company, report

    def _selected(self, report, selector):
        if type(selector) is not dict or type(selector.get('kind')) is not str:
            raise ValidationError(_('Select a valid report detail.'))
        rows = report['rows']
        kind = selector['kind']
        if kind == 'summary':
            exact_selector(selector, ('kind', 'metric'))
            metric = selector['metric']
            if type(metric) is not str:
                raise ValidationError(_('Select a valid report detail.'))
            if metric == 'opening':
                return metric, []
            if metric == 'debit_total':
                return metric, [row for row in rows if row['_fee'] < 0]
            if metric == 'credit_total':
                return metric, [row for row in rows if row['_fee'] > 0]
            if metric == 'closing':
                return metric, list(rows)
            raise ValidationError(_('Select a valid report detail.'))
        if kind in {'fee_row', 'running'}:
            keys = ('kind', 'order_id', 'line_id') if kind == 'running' else ('kind', 'order_id', 'line_id', 'measure')
            exact_selector(selector, keys)
            order_id, line_id = positive_id(selector['order_id']), positive_id(selector['line_id'])
            if kind == 'fee_row' and (type(selector['measure']) is not str or selector['measure'] not in {'fee', 'debit', 'credit'}):
                raise ValidationError(_('Select a valid report detail.'))
            index = next((number for number, row in enumerate(rows)
                          if row['_order_id'] == order_id and row['_line_id'] == line_id), None)
            if index is None:
                raise AccessError(_('The POS line is not available in this report.'))
            return kind, rows[:index + 1] if kind == 'running' else [rows[index]]
        if kind == 'exception':
            exact_selector(selector, ('kind', 'order_id', 'metric'))
            order_id = positive_id(selector['order_id'])
            if type(selector['metric']) is not str or selector['metric'] not in {'computed_total', 'saved_total'}:
                raise ValidationError(_('Select a valid report detail.'))
            selected = [row for row in report['exceptions'] if row['_order_id'] == order_id]
            if not selected:
                raise AccessError(_('The POS exception is not available in this report.'))
            return kind, selected
        raise ValidationError(_('Select a valid report detail.'))

    def _total(self, selector, selected):
        if selector['kind'] == 'summary':
            if selector['metric'] == 'opening':
                return Decimal('0')
            fee = sum((row['_fee'] for row in selected), Decimal('0'))
            return -fee if selector['metric'] == 'debit_total' else fee
        if selector['kind'] == 'exception':
            return selected[0]['_computed_total' if selector['metric'] == 'computed_total' else '_saved_total']
        fee = sum((row['_fee'] for row in selected), Decimal('0'))
        if selector['kind'] == 'fee_row' and selector['measure'] == 'debit':
            return max(-fee, Decimal('0'))
        if selector['kind'] == 'fee_row' and selector['measure'] == 'credit':
            return max(fee, Decimal('0'))
        return fee

    def _fee_rows(self, report, selector, selected, ar):
        columns = [
            {'key': 'date', 'label': 'التاريخ والوقت' if ar else 'Date and time'},
            {'key': 'order', 'label': 'طلب نقطة البيع' if ar else 'POS order'},
            {'key': 'type', 'label': 'النوع' if ar else 'Type'},
            {'key': 'debit', 'label': 'خارج / مردود' if ar else 'Out / refunds', 'numeric': True},
            {'key': 'credit', 'label': 'داخل / بيع' if ar else 'In / sales', 'numeric': True},
            {'key': 'running', 'label': 'التراكمي' if ar else 'Running total', 'numeric': True},
        ]
        if report['show_products']:
            columns.insert(2, {'key': 'product', 'label': 'المنتج والكمية' if ar else 'Product and quantity'})
        rows = []
        for row in selected:
            cells = {'date': row['date'], 'order': row['order'], 'type': row['type'],
                     'debit': row['debit'], 'credit': row['credit'], 'running': row['running']}
            if report['show_products']:
                cells['product'] = row['products']
            child = {'kind': 'fee_row', 'order_id': row['_order_id'], 'line_id': row['_line_id'], 'measure': 'fee'}
            rows.append({'key': '%s:%s' % (row['_order_id'], row['_line_id']), 'cells': cells,
                         'source': {'kind': 'source', 'parent': child, 'order_id': row['_order_id'],
                                    'line_id': row['_line_id']}})
        return columns, rows

    @api.model
    def _get_drilldown(self, filters, selector, page):
        _company, report = self._drill_report(filters)
        kind, selected = self._selected(report, selector)
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        basis = ('رسوم تبغ محسوبة الآن من طلبات نقاط البيع المكتملة في النطاق المحدد.' if ar
                 else 'Tobacco fees currently calculated from completed POS orders in the selected scope.')
        if kind == 'exception':
            item = selected[0]
            columns = [{'key': 'date', 'label': 'التاريخ' if ar else 'Date'},
                       {'key': 'order', 'label': 'طلب نقطة البيع' if ar else 'POS order'},
                       {'key': 'computed', 'label': 'المعاد احتسابه' if ar else 'Recalculated', 'numeric': True},
                       {'key': 'saved', 'label': 'المحفوظ' if ar else 'Saved', 'numeric': True}]
            rows = [{'key': str(item['_order_id']),
                     'cells': {'date': item['date'], 'order': item['order'],
                               'computed': item['computed_total'], 'saved': item['saved_total']},
                     'source': {'kind': 'source', 'parent': dict(selector), 'order_id': item['_order_id'], 'line_id': False}}]
            title = 'تفاصيل اختلاف الطلب' if ar else 'Order mismatch details'
            return drill_result(title, _format_money(self._total(selector, selected)), basis, columns, rows, page)
        columns, rows = self._fee_rows(report, selector, selected, ar)
        titles = {'opening': 'رصيد بداية الفترة' if ar else 'Opening balance',
                  'debit_total': 'خارج / مردود' if ar else 'Out / refunds',
                  'credit_total': 'داخل / بيع' if ar else 'In / sales',
                  'closing': 'صافي رسوم الفترة' if ar else 'Net fees for period',
                  'fee_row': 'تفصيل رسم التبغ' if ar else 'Tobacco fee detail',
                  'running': 'الإجمالي التراكمي' if ar else 'Cumulative total'}
        if kind == 'opening':
            basis = ('هذا التقرير يعرّف رصيد البداية بصفر؛ لا توجد عملية مصدر.' if ar
                     else 'This report defines the opening balance as zero; there is no source operation.')
        elif kind == 'fee_row' and selector['measure'] in {'debit', 'credit'}:
            basis = ('المبلغ المعروض هو مقدار الدائن/المدين من رسم السطر؛ العملية المصدر معروضة حتى عند الصفر.' if ar
                     else 'The displayed value is the debit/credit magnitude of this fee line; the source operation remains shown at zero.')
        return drill_result(titles[kind], _format_money(self._total(selector, selected)), basis, columns, rows, page)

    @api.model
    def _open_drill_source(self, filters, selector):
        exact_selector(selector, ('kind', 'parent', 'order_id', 'line_id'))
        if selector['kind'] != 'source' or type(selector['parent']) is not dict:
            raise ValidationError(_('Select a valid source.'))
        _company, report = self._drill_report(filters)
        parent_kind, selected = self._selected(report, selector['parent'])
        order_id = positive_id(selector['order_id'])
        line_id = selector['line_id']
        if parent_kind == 'exception':
            valid = selected[0]['_order_id'] == order_id and line_id is False
        else:
            valid = any(row['_order_id'] == order_id and row['_line_id'] == line_id for row in selected)
        if not valid:
            raise AccessError(_('The POS source is not available in this report.'))
        order = self.env['pos.order'].browse(order_id).exists()
        if not order:
            raise AccessError(_('The POS source is not available in this report.'))
        order.check_access('read')
        order.check_access_rule('read')
        if line_id is not False:
            line = self.env['pos.order.line'].browse(positive_id(line_id)).exists()
            if not line or line.order_id != order:
                raise AccessError(_('The POS source is not available in this report.'))
            line.check_access('read')
            line.check_access_rule('read')
        return {'type': 'ir.actions.act_window', 'name': _('POS Order'), 'res_model': 'pos.order',
                'views': [[False, 'form']], 'view_mode': 'form', 'res_id': order.id, 'target': 'current'}

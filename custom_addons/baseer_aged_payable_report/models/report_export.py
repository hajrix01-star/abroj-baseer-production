"""Typed export projection of the existing historical payables collector."""

from datetime import date

from odoo import _, api, models
from odoo.exceptions import ValidationError

from odoo.addons.baseer_reports_menu.report_values import (
    export_document, require_active_filters, source_money,
)


class AgedPayableExport(models.AbstractModel):
    _inherit = 'baseer.aged.payable.report'

    @api.model
    def _get_export_document(self, filters):
        require_active_filters(self.env, filters, {'cutoff_date', 'page'})
        options = {key: filters[key] for key in ('cutoff_date', 'page') if key in filters}
        if set(options) != {'cutoff_date', 'page'}:
            raise ValidationError(_('Select a valid cutoff date and page.'))
        cutoff = self._cutoff(options['cutoff_date'])
        self._page(options['page'])
        report = self._build_pdf(cutoff)
        if len(report['lines']) > self.MAX_PDF_LINES:
            raise ValidationError(_('Too many open payable items to export. Narrow the cutoff date.'))
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        labels = (('المورد', 'التاريخ', 'الاستحقاق', 'القيد', 'النوع', 'فئة التقادم', 'المتبقي')
                  if ar else ('Supplier', 'Date', 'Due date', 'Entry', 'Type', 'Age bucket', 'Open amount'))
        kinds = ({'invoice': 'فاتورة مورد', 'credit_note': 'إشعار دائن من المورد', 'direct_claim': 'بند مستحق مباشر',
                  'counter_balance': 'رصيد مقابل غير مطبق', 'unusual': 'إشارة غير معتادة'} if ar else
                 {'invoice': 'Vendor bill', 'credit_note': 'Vendor credit note', 'direct_claim': 'Direct payable',
                  'counter_balance': 'Counter-balance', 'unusual': 'Unusual sign'})
        buckets = ({'not_due': 'حديث', 'd1_30': '1–30', 'd31_60': '31–60',
                    'd61_90': '61–90', 'over_90': '90+', 'counter': 'رصيد مقابل'} if ar else
                   {'not_due': 'Current', 'd1_30': '1–30', 'd31_60': '31–60',
                    'd61_90': '61–90', 'over_90': '90+', 'counter': 'Counter-balance'})
        columns = [{'key': key, 'label': label, 'type': kind, 'width': width} for key, label, kind, width in (
            ('partner', labels[0], 'text', 28), ('date', labels[1], 'date', 14),
            ('due', labels[2], 'date', 14), ('entry', labels[3], 'text', 24),
            ('kind', labels[4], 'text', 18), ('bucket', labels[5], 'text', 14),
            ('open', labels[6], 'money', 18),
        )]
        rows = []
        for line in report['lines']:
            cells = {
                'partner': line['partner_name'], 'date': date.fromisoformat(line['date']),
                'entry': line['move_name'], 'kind': kinds[line['kind']],
                'bucket': buckets[line['counter_age_bucket']] if line.get('counter_age_bucket') else buckets[line['bucket']],
                'open': source_money(line['open']),
            }
            if line['date_maturity']:
                cells['due'] = date.fromisoformat(line['date_maturity'])
            rows.append({'cells': cells, 'kind': 'detail'})
        totals = (('payables', 'المستحق للموردين' if ar else 'Payables'),
                  ('counter_balances', 'الأرصدة المقابلة' if ar else 'Counter-balances'),
                  ('net', 'الصافي' if ar else 'Net'))
        for key, label in totals:
            rows.append({'cells': {'partner': label, 'open': source_money(report['summary'][key])},
                         'kind': 'total'})
        return export_document(self.env, 'أعمار أرصدة الموردين' if ar else 'Aged Payables', columns, rows,
                               metadata=[('تاريخ القطع' if ar else 'Cutoff Date', report['cutoff_date'])])

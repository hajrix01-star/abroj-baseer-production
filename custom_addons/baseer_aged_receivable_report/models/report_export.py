"""Typed export projection of the existing historical receivables collector."""

from datetime import date

from odoo import _, api, models
from odoo.exceptions import ValidationError

from odoo.addons.baseer_reports_menu.report_values import (
    export_document, require_active_filters, source_money,
)


class AgedReceivableExport(models.AbstractModel):
    _inherit = 'baseer.aged.receivable.report'

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
            raise ValidationError(_('Too many open receivable items to export. Narrow the cutoff date.'))
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        labels = (('العميل', 'التاريخ', 'الاستحقاق', 'القيد', 'النوع', 'فئة التقادم', 'المتبقي')
                  if ar else ('Customer', 'Date', 'Due date', 'Entry', 'Type', 'Age bucket', 'Open amount'))
        kinds = ({'invoice': 'فاتورة', 'credit_note': 'إشعار دائن', 'direct_claim': 'بند مباشر',
                  'unapplied_credit': 'رصيد دائن غير مطبق', 'unusual': 'إشارة غير معتادة'} if ar else
                 {'invoice': 'Invoice', 'credit_note': 'Credit note', 'direct_claim': 'Direct item',
                  'unapplied_credit': 'Unapplied credit', 'unusual': 'Unusual sign'})
        buckets = ({'not_due': 'حديث', 'd1_30': '1–30', 'd31_60': '31–60',
                    'd61_90': '61–90', 'over_90': '90+', 'credit': 'رصيد دائن'} if ar else
                   {'not_due': 'Current', 'd1_30': '1–30', 'd31_60': '31–60',
                    'd61_90': '61–90', 'over_90': '90+', 'credit': 'Credit'})
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
                'bucket': buckets[line['credit_age_bucket']] if line.get('credit_age_bucket') else buckets[line['bucket']],
                'open': source_money(line['open']),
            }
            if line['date_maturity']:
                cells['due'] = date.fromisoformat(line['date_maturity'])
            rows.append({'cells': cells, 'kind': 'detail'})
        totals = (('receivables', 'المستحق من العملاء' if ar else 'Receivables'),
                  ('credits', 'الأرصدة الدائنة' if ar else 'Credits'), ('net', 'الصافي' if ar else 'Net'))
        for key, label in totals:
            rows.append({'cells': {'partner': label, 'open': source_money(report['summary'][key])},
                         'kind': 'total'})
        return export_document(self.env, 'أعمار أرصدة العملاء' if ar else 'Aged Receivables', columns, rows,
                               metadata=[('تاريخ القطع' if ar else 'Cutoff Date', report['cutoff_date'])])

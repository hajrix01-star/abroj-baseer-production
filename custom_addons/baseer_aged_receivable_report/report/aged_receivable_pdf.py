"""A4 printout from the same secured historical receivables snapshot as the UI."""

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class AgedReceivablePdf(models.AbstractModel):
    _name = 'report.baseer_aged_receivable_report.aged_receivable_pdf'
    _description = 'Baseer Customer Aged Receivables A4'

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or set(data) != {'cutoff_date'}:
            raise ValidationError(_('Select a valid cutoff date.'))
        report_model = self.env['baseer.aged.receivable.report']
        cutoff = report_model._cutoff(data['cutoff_date'])
        report = report_model._build_pdf(cutoff)
        arabic = (self.env.user.lang or '').startswith('ar')
        kind_labels = ({
            'invoice': 'فاتورة', 'credit_note': 'إشعار دائن',
            'direct_claim': 'بند مباشر', 'unapplied_credit': 'رصيد دائن',
            'unusual': 'إشارة غير معتادة',
        } if arabic else {
            'invoice': 'Invoice', 'credit_note': 'Credit note',
            'direct_claim': 'Direct item', 'unapplied_credit': 'Unapplied credit',
            'unusual': 'Unusual sign',
        })
        return {
            'doc_ids': [],
            'doc_model': 'baseer.aged.receivable.report',
            'company_record': self.env.company,
            'report': report,
            'arabic': arabic,
            'kind_labels': kind_labels,
            'generated_at': fields.Datetime.context_timestamp(
                self, report['generated_at'],
            ),
        }

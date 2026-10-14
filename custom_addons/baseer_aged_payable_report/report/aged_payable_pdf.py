"""A4 printout from the same secured historical payables snapshot as the UI."""

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class AgedPayablePdf(models.AbstractModel):
    _name = 'report.baseer_aged_payable_report.aged_payable_pdf'
    _description = 'Baseer Supplier Aged Payables A4'

    def _get_report_values(self, docids, data=None):
        # Odoo adds rendering metadata to `data` before calling this model.
        # The public action validates its original options strictly; ignore
        # framework keys here while still validating the requested cutoff.
        if docids or not isinstance(data, dict) or 'cutoff_date' not in data:
            raise ValidationError(_('Select a valid cutoff date.'))
        report_model = self.env['baseer.aged.payable.report']
        cutoff = report_model._cutoff(data['cutoff_date'])
        report = report_model._build_pdf(cutoff)
        arabic = (self.env.user.lang or '').startswith('ar')
        kind_labels = ({
            'invoice': 'فاتورة', 'credit_note': 'إشعار مدين',
            'direct_claim': 'بند مباشر', 'counter_balance': 'رصيد مقابل',
            'unusual': 'إشارة غير معتادة',
        } if arabic else {
            'invoice': 'Invoice', 'credit_note': 'Vendor credit note',
            'direct_claim': 'Direct item', 'counter_balance': 'Counter-balance',
            'unusual': 'Unusual sign',
        })
        age_labels = ({
            'not_due': 'حديث', 'd1_30': '1–30', 'd31_60': '31–60',
            'd61_90': '61–90', 'over_90': '90+',
        } if arabic else {
            'not_due': 'Current', 'd1_30': '1–30', 'd31_60': '31–60',
            'd61_90': '61–90', 'over_90': '90+',
        })
        return {
            'doc_ids': [],
            'doc_model': 'baseer.aged.payable.report',
            'company_record': self.env.company,
            'report': report,
            'arabic': arabic,
            'kind_labels': kind_labels,
            'age_labels': age_labels,
            'generated_at': fields.Datetime.context_timestamp(
                self, report['generated_at'],
            ),
        }

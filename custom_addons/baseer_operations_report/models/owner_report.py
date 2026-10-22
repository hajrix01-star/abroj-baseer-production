"""Server-formatted owner summary; the existing Hub is not wired here yet."""

from decimal import Decimal, localcontext
from hashlib import sha256

from odoo import api, fields, models

from .owner_summary import build_owner_summary


OWNER_LABELS = {
    'title': ('ملخص المبيعات والمدفوعات', 'Sales and Payments Summary'),
    'basis': ('المبيعات المسجلة تشمل غير المحصل. الخارج مدفوعات فعلية، والفرق ليس صافي الربح المحاسبي.',
              'Recorded sales include uncollected sales. Outflows are actual payments; the difference is not accounting profit.'),
    'incoming_total': ('المبيعات', 'Sales'),
    'cash_total': ('المدفوعات الفعلية', 'Actual payments'),
    'difference': ('الفرق بين المبيعات والمدفوعات', 'Sales less payments'),
    'purchase': ('المشتريات حسب فئة الصنف', 'Purchases by item category'),
    'operating_account': ('المصروفات التشغيلية', 'Operating expenses'),
    'operating_services': ('الخدمات التشغيلية', 'Operating services'),
    'employee_services': ('خدمات الموظفين', 'Employee services'),
    'payroll': ('الرواتب المدفوعة فعليًا', 'Actual salary payments'),
    'employee_advance': ('سلف الموظفين المصروفة', 'Employee advances paid'),
    'unclassified': ('مدفوعات غير مصنفة', 'Unclassified payments'),
    'unconfirmed_bill_classification': ('مدفوعات لم يتأكد تصنيف فواتيرها', 'Payments with unconfirmed bill classification'),
    'unallocated': ('مبيعات غير موزعة على طرق الدفع', 'Sales without payment-channel allocation'),
}


class OperationsOwnerReport(models.AbstractModel):
    _inherit = 'baseer.operations.report'

    def _owner_display(self, summary, company):
        """Display values are copied from Decimal results, never client math."""
        arabic = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        labels = {key: names[0 if arabic else 1] for key, names in OWNER_LABELS.items()}
        formatter = self.env['baseer.profit.loss.report']._format_money

        def money(value):
            return {'amount': formatter(value, company.currency_id), 'negative': value < 0}

        totals = [{'key': key, 'label': labels[key], **money(summary[key])}
                  for key in ('incoming_total', 'cash_total', 'difference')]
        channels = [{
            'key': sha256(row['key'].encode()).hexdigest()[:20],
            'label': labels['unallocated'] if row['key'] == 'unallocated' else row['name'],
            **money(row['amount']),
            'percentage': None if row['percentage'] is None else f"{row['percentage']:.2f}%",
        } for row in summary['channels']]
        groups = {}
        with localcontext() as context:
            context.prec = 60
            for row in summary['outflow_buckets']:
                kind = row.get('classification', row['key'])
                if kind not in labels:
                    self._deny_incomplete_source()
                group = groups.setdefault(kind, {'raw': Decimal(0), 'rows': []})
                group['raw'] += row['amount']
                label = row.get('name', labels[kind])
                if kind == 'purchase':
                    label = ' / '.join(name for _identity, name in row['category_path'])
                group['rows'].append({
                    'key': sha256(row['key'].encode()).hexdigest()[:20],
                    'label': label, **money(row['amount']),
                })
            if sum((group['raw'] for group in groups.values()), Decimal(0)) != summary['cash_total']:
                self._deny_incomplete_source()
        return {
            'totals': totals, 'channels': channels,
            'outflows': [{'key': key, 'label': labels[key], **money(group['raw']),
                          'rows': group['rows']} for key, group in groups.items()],
            'has_unclassified_outflows': summary['has_unclassified_outflows'],
        }

    @api.model
    def get_owner_snapshot(self, filters):
        """Only filters are accepted; all source facts are read in this request."""
        company, journals, periods, controls, comparisons = self._scope(filters)
        # Reuse the existing filter/period/accounting-access parser. The private
        # collectors independently enforce the owner's active-company allowlist.
        results = []
        for period in periods:
            start, end = fields.Date.to_date(period['date_from']), fields.Date.to_date(period['date_to'])
            sales = self._owner_sales(company, start, end, journals)
            cash = self._owner_cash(company, start, end, journals)
            summary = build_owner_summary(sales + cash['events'], cash['liquidity_totals'], company_id=company.id)
            results.append({
                'key': period['key'], 'date_from': period['date_from'], 'date_to': period['date_to'],
                'label': period['label'], 'display_label': period['display_label'],
                'coverage_complete': cash['coverage_complete'],
                **self._owner_display(summary, company),
            })
        complete = all(period['coverage_complete'] for period in results)
        if not complete:
            for period in results:
                for key in ('totals', 'channels', 'outflows', 'has_unclassified_outflows'):
                    period.pop(key, None)
        arabic = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        return {
            'complete': complete, 'coverage_complete': complete,
            'company_id': company.id, 'currency_code': company.currency_id.name,
            'title': OWNER_LABELS['title'][0 if arabic else 1],
            'basis': OWNER_LABELS['basis'][0 if arabic else 1],
            'source_basis': 'recorded_sales_headers_and_posted_cash',
            'not_accounting_profit': True,
            'period_controls': controls, 'comparison_controls': comparisons,
            'periods': results,
        }

    @api.model
    def action_print_owner(self, filters):
        """Validate now and rebuild again when the PDF request is rendered."""
        snapshot = self.get_owner_snapshot(filters)
        if not snapshot['complete']:
            self._deny_incomplete_source()
        layout = 'landscape' if len(snapshot['periods']) > 1 else 'portrait'
        return self.env.ref(
            f'baseer_operations_report.action_owner_pdf_{layout}'
        ).report_action([], data={'filters': filters}, config=False)

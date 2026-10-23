"""Server-formatted owner summary used by the existing Hub and PDF entry."""

from decimal import Decimal, localcontext
from datetime import date, datetime
from datetime import date, datetime
from hashlib import sha256
import json

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

    @staticmethod
    def _owner_revision_value(value):
        """Serialize only known source primitives for a non-reversible digest."""
        if isinstance(value, Decimal):
            return format(value, 'f')
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): OperationsOwnerReport._owner_revision_value(item)
                    for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [OperationsOwnerReport._owner_revision_value(item) for item in value]
        if value is None or isinstance(value, (str, int, bool)):
            return value
        raise TypeError('Unexpected owner-source revision value.')

    def _owner_period_revision(self, company, start, end, journal_ids, sales, cash, display):
        """Bind drill-down pages to the exact proved facts and visible rows."""
        facts = []
        for event in sales + cash['events']:
            facts.append(self._owner_revision_value({
                key: event[key] for key in (
                    'company_id', 'direction', 'source_model', 'source_id',
                    'line_model', 'line_id', 'payment_move_id', 'payment_line_id',
                    'date', 'amount', 'classification', 'account_id', 'account_name',
                    'service_key', 'service_name', 'category_path', 'channels',
                    'link_status', 'linked_invoice_id', 'invoice_not_readded',
                    'employee_id', 'loan_id', 'payslip_id', 'origin_payment_id',
                ) if key in event
            }))
        payload = self._owner_revision_value({
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'currency_code': company.currency_id.name,
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
            'journal_ids': sorted(journal_ids),
            'facts': sorted(facts, key=lambda item: json.dumps(
                item, sort_keys=True, separators=(',', ':'), ensure_ascii=True)),
            'display': display,
        })
        return sha256(json.dumps(
            payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        ).encode()).hexdigest()

    def _owner_period_data(self, company, start, end, journal_ids):
        """Rebuild one period from the same private, access-checked collectors."""
        sales = self._owner_sales(company, start, end, journal_ids)
        cash = self._owner_cash(company, start, end, journal_ids)
        if not cash['coverage_complete']:
            return {'coverage_complete': False}
        summary = build_owner_summary(sales + cash['events'], cash['liquidity_totals'], company_id=company.id)
        display = self._owner_display(summary, company)
        return {
            'coverage_complete': True,
            'sales': sales,
            'cash': cash,
            'summary': summary,
            'display': display,
            'revision': self._owner_period_revision(company, start, end, journal_ids, sales, cash, display),
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
            data = self._owner_period_data(company, start, end, journals)
            result = {
                'key': period['key'], 'date_from': period['date_from'], 'date_to': period['date_to'],
                'label': period['label'], 'display_label': period['display_label'],
                'coverage_complete': data['coverage_complete'],
            }
            if data['coverage_complete']:
                result.update(data['display'])
                result['revision'] = data['revision']
            results.append(result)
        complete = all(period['coverage_complete'] for period in results)
        if not complete:
            for period in results:
                for key in ('totals', 'channels', 'outflows', 'has_unclassified_outflows', 'revision'):
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

"""Fresh, paginated drill-down for the private owner summary.

Every selection is rebuilt from the same proven facts as the summary.  The
browser receives neither source identifiers nor a raw ORM domain.
"""

from decimal import Decimal, localcontext
from hashlib import sha256
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .owner_summary import _outflow_bucket


_PAGE_SIZE = 50
_MAX_PAGE = 10000
_TOTAL_KEYS = frozenset(('incoming_total', 'cash_total', 'difference'))
_OUTFLOW_KINDS = frozenset((
    'purchase', 'operating_account', 'operating_services', 'employee_services',
    'payroll', 'employee_advance', 'unclassified', 'unconfirmed_bill_classification',
))
_SOURCE_MODELS = frozenset((
    'pos.order', 'account.move', 'account.bank.statement.line', 'account.payment',
    'baseer.purchase.batch.line', 'baseer.hr.loan',
))
_SOURCE_LABELS = {
    'pos.order': ('طلب نقطة البيع', 'Point of Sale order'),
    'account.move': ('فاتورة', 'Invoice'),
    'account.bank.statement.line': ('كشف حساب بنكي', 'Bank statement line'),
    'account.payment': ('دفعة', 'Payment'),
    'baseer.purchase.batch.line': ('سطر دفعة مشتريات', 'Purchase batch line'),
    'baseer.hr.loan': ('سلفة موظف', 'Employee advance'),
}


class OperationsOwnerDetails(models.AbstractModel):
    _inherit = 'baseer.operations.report'

    @staticmethod
    def _owner_digest(value):
        return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()

    @staticmethod
    def _owner_short_digest(value):
        return sha256(value.encode()).hexdigest()[:20]

    def _owner_detail_request(self, row_key, period_key, expected_revision, page=None, event_key=None):
        if (not isinstance(row_key, str) or not row_key or len(row_key) > 160
                or not isinstance(period_key, str) or not period_key or len(period_key) > 80
                or not isinstance(expected_revision, str) or len(expected_revision) != 64
                or any(char not in '0123456789abcdef' for char in expected_revision)):
            raise ValidationError(_('Invalid owner detail request.'))
        if page is not None and (type(page) is not int or page < 1 or page > _MAX_PAGE):
            raise ValidationError(_('Invalid owner detail page.'))
        if event_key is not None and (not isinstance(event_key, str) or len(event_key) != 64
                                      or any(char not in '0123456789abcdef' for char in event_key)):
            raise ValidationError(_('Invalid owner source request.'))
        if row_key.startswith('total:'):
            if row_key[6:] not in _TOTAL_KEYS:
                raise ValidationError(_('The selected owner row is unavailable.'))
            return ('total', row_key[6:])
        if row_key.startswith('channel:') and len(row_key) == 28:
            if all(char in '0123456789abcdef' for char in row_key[8:]):
                return ('channel', row_key[8:])
        if row_key.startswith('outflow:'):
            parts = row_key.split(':')
            if len(parts) == 2 and parts[1] in _OUTFLOW_KINDS:
                return ('outflow', parts[1], None)
            if (len(parts) == 3 and parts[1] in _OUTFLOW_KINDS and len(parts[2]) == 20
                    and all(char in '0123456789abcdef' for char in parts[2])):
                return ('outflow', parts[1], parts[2])
        raise ValidationError(_('The selected owner row is unavailable.'))

    def _owner_detail_period(self, filters, period_key):
        company, journals, periods, _controls, _comparisons = self._scope(filters)
        entries = []
        for period in periods:
            start = fields.Date.to_date(period['date_from'])
            end = fields.Date.to_date(period['date_to'])
            data = self._owner_period_data(company, start, end, journals)
            if not data['coverage_complete']:
                self._deny_incomplete_source()
            entries.append((period, data))
        selected = next((entry for entry in entries if entry[0]['key'] == period_key), None)
        if not selected:
            raise ValidationError(_('The selected report period is unavailable.'))
        return company, selected[0], selected[1]

    def _owner_row_label(self, data, selection):
        kind, key, *rest = selection
        if kind == 'total':
            return next(row['label'] for row in data['display']['totals'] if row['key'] == key)
        if kind == 'channel':
            return next(row['label'] for row in data['display']['channels']
                        if row['key'] == key)
        detail_key = rest[0]
        group = next(row for row in data['display']['outflows'] if row['key'] == key)
        if detail_key is None:
            return group['label']
        return next(row['label'] for row in group['rows']
                    if row['key'] == detail_key)

    def _owner_selected_amount(self, data, selection):
        kind, key, *rest = selection
        if kind == 'total':
            return data['summary'][key]
        if kind == 'channel':
            return next(row['amount'] for row in data['summary']['channels']
                        if self._owner_short_digest(row['key']) == key)
        detail_key = rest[0]
        buckets = [row for row in data['summary']['outflow_buckets']
                   if row.get('classification', row['key']) == key]
        if detail_key is not None:
            buckets = [row for row in buckets if self._owner_short_digest(row['key']) == detail_key]
        if not buckets:
            raise ValidationError(_('The selected owner row is unavailable.'))
        with localcontext() as context:
            context.prec = 60
            return sum((row['amount'] for row in buckets), Decimal(0))

    def _owner_event_key(self, row_key, event, amount, allocation_key=''):
        return self._owner_digest({
            'row_key': row_key,
            'source_model': event['source_model'], 'source_id': event['source_id'],
            'line_model': event['line_model'], 'line_id': event['line_id'],
            'payment_line_id': event.get('payment_line_id') or 0,
            'date': fields.Date.to_string(fields.Date.to_date(event['date'])),
            'amount': format(amount, 'f'),
            'allocation_key': allocation_key,
        })

    def _owner_selected_events(self, data, row_key, selection):
        """Return server-side Decimal contributions for exactly one visible row."""
        kind, key, *rest = selection
        selected = []
        if kind == 'total':
            if key in ('incoming_total', 'difference'):
                selected.extend((event, event['amount'], '') for event in data['sales'])
            if key in ('cash_total', 'difference'):
                selected.extend((event, event['amount'].copy_negate() if key == 'difference'
                                 else event['amount'], '') for event in data['cash']['events'])
        elif kind == 'channel':
            for event in data['sales']:
                for raw_key, _name, amount in event['channels']:
                    if self._owner_short_digest(raw_key) == key:
                        selected.append((event, amount, raw_key))
        else:
            detail_key = rest[0]
            for event in data['cash']['events']:
                if event['classification'] != key:
                    continue
                raw_key, _metadata = _outflow_bucket(event)
                if detail_key is None or self._owner_short_digest(raw_key) == detail_key:
                    selected.append((event, event['amount'], raw_key))
        if not selected and kind != 'total':
            raise ValidationError(_('The selected owner row is unavailable.'))
        with localcontext() as context:
            context.prec = 60
            total = sum((amount for _event, amount, _allocation in selected), Decimal(0))
        if total != self._owner_selected_amount(data, selection):
            self._deny_incomplete_source()
        label = self._owner_row_label(data, selection)
        result = []
        for event, amount, allocation_key in selected:
            if event['source_model'] not in _SOURCE_MODELS:
                self._deny_incomplete_source()
            result.append({
                'event': event, 'amount': amount,
                'event_key': self._owner_event_key(row_key, event, amount, allocation_key),
            })
        if len({row['event_key'] for row in result}) != len(result):
            self._deny_incomplete_source()
        result.sort(key=lambda row: (
            fields.Date.to_string(fields.Date.to_date(row['event']['date'])),
            row['event']['source_model'], row['event']['source_id'],
            row['event']['line_model'], row['event']['line_id'], row['event'].get('payment_line_id') or 0,
            row['event_key'],
        ), reverse=True)
        return label, total, result

    def _owner_source_labels(self, rows, company):
        """Read only page sources through normal ACLs, in model batches."""
        grouped = {}
        for row in rows:
            event = row['event']
            grouped.setdefault(event['source_model'], set()).add(event['source_id'])
        records = {}
        arabic = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        for model_name, ids in grouped.items():
            if model_name not in _SOURCE_MODELS:
                self._deny_incomplete_source()
            source = self.env[model_name].browse(sorted(ids)).exists()
            if set(source.ids) != ids:
                self._deny_incomplete_source()
            source.check_access('read')
            for record in source:
                source_company = (record.batch_id.company_id
                                  if model_name == 'baseer.purchase.batch.line'
                                  else record.company_id)
                if source_company != company:
                    self._deny_incomplete_source()
                records[(model_name, record.id)] = '%s · %s' % (
                    _SOURCE_LABELS[model_name][0 if arabic else 1], record.display_name)
        return records

    def _owner_detail_payload(self, filters, row_key, period_key, expected_revision, page=None):
        selection = self._owner_detail_request(row_key, period_key, expected_revision, page=page)
        company, period, data = self._owner_detail_period(filters, period_key)
        identity = {'company_id': company.id, 'period_key': period_key, 'row_key': row_key,
                    'revision': data['revision']}
        if data['revision'] != expected_revision:
            return {**identity, 'changed': True}
        label, total, rows = self._owner_selected_events(data, row_key, selection)
        formatter = self.env['baseer.profit.loss.report']._format_money
        page = page or 1
        page_rows = rows[(page - 1) * _PAGE_SIZE:page * _PAGE_SIZE]
        labels = self._owner_source_labels(page_rows, company)
        return {
            **identity, 'changed': False, 'page': page, 'page_size': _PAGE_SIZE,
            'total_count': len(rows), 'label': label, 'period_label': period['display_label'],
            'amount': formatter(total, company.currency_id), 'negative': total < 0,
            'events': [{
                'event_key': row['event_key'],
                'date': fields.Date.to_string(fields.Date.to_date(row['event']['date'])),
                'label': labels[(row['event']['source_model'], row['event']['source_id'])],
                'amount': formatter(row['amount'], company.currency_id), 'negative': row['amount'] < 0,
            } for row in page_rows],
        }

    @api.model
    def get_owner_details(self, filters, row_key, period_key, expected_revision, page=1):
        return self._owner_detail_payload(filters, row_key, period_key, expected_revision, page=page)

    @api.model
    def action_owner_source(self, filters, row_key, period_key, expected_revision, event_key):
        selection = self._owner_detail_request(
            row_key, period_key, expected_revision, event_key=event_key)
        company, _period, data = self._owner_detail_period(filters, period_key)
        if data['revision'] != expected_revision:
            return {
                'company_id': company.id, 'period_key': period_key, 'row_key': row_key,
                'revision': data['revision'], 'changed': True,
            }
        _label, _total, rows = self._owner_selected_events(data, row_key, selection)
        selected = next((row for row in rows if row['event_key'] == event_key), None)
        if not selected:
            raise ValidationError(_('The selected owner source is unavailable.'))
        event = selected['event']
        source = self.env[event['source_model']].browse(event['source_id']).exists()
        if not source:
            self._deny_incomplete_source()
        source.check_access('read')
        source_company = (source.batch_id.company_id
                          if event['source_model'] == 'baseer.purchase.batch.line'
                          else source.company_id)
        if source_company != company:
            self._deny_incomplete_source()
        action = source.get_formview_action()
        context = action.get('context') if isinstance(action.get('context'), dict) else {}
        action.update({'target': 'new', 'context': {**context, 'create': False, 'edit': False}})
        return action

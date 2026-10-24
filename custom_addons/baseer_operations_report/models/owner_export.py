"""Typed export adapter; preserve every authoritative owner-summary cell."""

from decimal import Decimal
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .owner_presentation import owner_print_rows


_MONEY = re.compile(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\Z', re.ASCII)
_PERCENT = re.compile(r'-?\d+(?:\.\d{1,2})?%\Z', re.ASCII)


class OwnerExport(models.AbstractModel):
    _inherit = 'baseer.operations.report'

    @api.model
    def _get_export_document(self, filters):
        allowed = {'company_id', 'journal_ids', 'period', 'comparison', 'date_from', 'date_to'}
        if type(filters) is not dict or set(filters) - allowed:
            raise ValidationError(_('Select valid report filters.'))
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Export the report for the active company only.'))
        snapshot = self.get_owner_snapshot(filters)
        if snapshot.get('complete') is not True or snapshot['company_id'] != self.env.company.id:
            self._deny_incomplete_source()
        arabic = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        periods = snapshot['periods']
        company = self.env.company
        if company.currency_id.decimal_places not in (0, 1, 2):
            raise ValidationError(_('This export supports currencies with up to two decimal places.'))
        columns = [{'key': 'label', 'label': 'التفاصيل' if arabic else 'Details', 'type': 'text', 'width': 52}]
        period_labels = {period['key']: (('الفترة ' if arabic else 'Period ') + str(index + 1))
                         for index, period in enumerate(periods)}
        for period in periods:
            prefix = period_labels[period['key']] + '\n' if len(periods) > 1 else ''
            columns.extend([
                {'key': period['key'] + '_percentage', 'label': prefix + ('النسبة' if arabic else 'Share'), 'type': 'percent', 'width': 17},
                {'key': period['key'], 'label': prefix + ('المبلغ' if arabic else 'Amount'), 'type': 'money', 'width': 23},
            ])
        rows = []
        for row in owner_print_rows(periods):
            cells = {'label': row['label']}
            for key, cell in row['amounts'].items():
                value = cell['amount']
                if type(value) is not str or not _MONEY.fullmatch(value):
                    raise ValidationError(_('An amount cannot be exported safely.'))
                cells[key] = Decimal(value.replace(',', ''))
                percentage = cell.get('percentage')
                if percentage is not None:
                    if type(percentage) is not str or not _PERCENT.fullmatch(percentage):
                        raise ValidationError(_('A percentage cannot be exported safely.'))
                    # Unit conversion only; never recompute sales shares.
                    cells[key + '_percentage'] = Decimal(percentage[:-1]).scaleb(-2)
            rows.append({'cells': cells,
                'kind': 'total' if row['key'] == 'difference' else 'section' if row['kind'] == 'section' or row['key'].startswith('outflow:') and row['key'].count(':') == 1 else 'detail',
                'indent': 2 if row['kind'] == 'channel' else 1 if row['kind'] == 'account' else 0})
        journal_ids = filters.get('journal_ids', [])
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        journals.check_access('read')
        metadata = [('الدفاتر' if arabic else 'Journals', ', '.join(journals.mapped('display_name')) if journal_ids else ('جميع الدفاتر' if arabic else 'All journals'))]
        metadata.extend((period_labels[period['key']] if len(periods) > 1 else ('الفترة' if arabic else 'Period'),
                         period['date_from'] + ' — ' + period['date_to']) for period in periods)
        metadata.append(('وقت التصدير UTC' if arabic else 'Exported UTC', fields.Datetime.to_string(fields.Datetime.now())))
        return {'title': snapshot['title'], 'company': company.name, 'currency': snapshot['currency_code'],
            'lang': 'ar' if arabic else 'en', 'decimals': company.currency_id.decimal_places,
            'metadata': metadata, 'columns': columns, 'rows': rows, 'notes': [snapshot['basis']]}

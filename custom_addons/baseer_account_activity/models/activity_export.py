"""Complete bounded export of the existing single-account activity calculator."""

from datetime import date
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.addons.baseer_reports_menu.report_values import (
    export_document, require_active_filters, source_money,
)


class ActivityExport(models.AbstractModel):
    _inherit = 'baseer.account.activity'

    EXPORT_SOURCE_LIMIT = 5000

    @api.model
    def _export_source(self, filters):
        """Only count bypasses record rules; values remain ORM-authorized."""
        company = self.env.company
        account = self.env['account.account'].browse(filters['account_id'])
        start, end = (fields.Date.to_date(filters[key]) for key in ('date_from', 'date_to'))
        floor = None if account.include_initial_balance else company.compute_fiscalyear_dates(start)['date_from']
        domain = (Domain('company_id', '=', company.id) & Domain('account_id', '=', account.id)
                  & Domain('parent_state', '=', 'posted') & Domain('date', '<=', end))
        query = ('SELECT COUNT(*) FROM account_move_line WHERE company_id = %s '
                 'AND account_id = %s AND parent_state = %s AND date <= %s')
        params = [company.id, account.id, 'posted', end]
        if floor:
            domain &= Domain('date', '>=', floor)
            query += ' AND date >= %s'
            params.append(floor)
        aml = self.env['account.move.line'].with_context(active_test=False)
        aml.flush_model(['company_id', 'account_id', 'parent_state', 'date'])
        readable = aml.search_count(domain)
        self.env.cr.execute(query, params)
        if readable != self.env.cr.fetchone()[0]:
            raise AccessError(_('The complete posted journal source is not available for this report.'))
        if readable > self.EXPORT_SOURCE_LIMIT:
            raise ValidationError(_('The complete activity source is too large to export. Choose another account or a shorter period.'))
        source = aml.search(domain, order='date, id', limit=self.EXPORT_SOURCE_LIMIT + 1)
        if len(source) != readable:
            raise AccessError(_('The report source changed. Refresh the report and try again.'))
        expected_ids = []
        for offset in range(0, len(source), 1000):
            batch = aml.browse(source.ids[offset:offset + 1000])
            batch.check_access('read')
            moves, journals = batch.mapped('move_id'), batch.mapped('journal_id')
            moves.check_access('read')
            journals.check_access('read')
            if any(move.company_id != company for move in moves) or any(journal.company_id != company for journal in journals):
                raise AccessError(_('The complete posted journal source is not available for this report.'))
            expected_ids.extend(batch.filtered(lambda line: start <= line.date <= end).ids)
        return expected_ids

    @api.model
    def _get_export_document(self, filters):
        require_active_filters(self.env, filters, {'account_id', 'date_from', 'date_to'})
        if not {'account_id', 'date_from', 'date_to'} <= filters.keys():
            raise ValidationError(_('Choose an account and a valid period.'))
        if any(type(filters[key]) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', filters[key])
               for key in ('date_from', 'date_to')):
            raise ValidationError(_('Select valid start and end dates.'))
        # Odoo's pinned runtime uses REPEATABLE READ. Assert the invariant so
        # multiple keyset pages cannot mix concurrent edits into one document.
        self.env.cr.execute('SHOW transaction_isolation')
        if self.env.cr.fetchone()[0] not in ('repeatable read', 'serializable'):
            raise ValidationError(_('A stable report snapshot is unavailable. Please try again.'))
        arguments = [filters[key] for key in ('company_id', 'account_id', 'date_from', 'date_to')]
        # Existing calculator validates accounting group, company/account/date and ACL.
        first = self.get_activity(*arguments)
        expected_ids = self._export_source(filters)
        lines = list(first['lines'])
        next_page = first['next_cursor']
        seen = set()
        while next_page:
            token = (next_page['date'], next_page['id'])
            if (not lines or token != (lines[-1]['date'], lines[-1]['id']) or
                    token in seen or len(lines) >= self.EXPORT_SOURCE_LIMIT):
                raise ValidationError(_('The full report cannot be exported. Select a shorter period.'))
            seen.add(token)
            page = self.get_activity(*arguments, cursor_date=token[0], cursor_id=token[1])
            if any(page[key] != first[key] for key in ('opening', 'debit', 'credit', 'closing')):
                raise AccessError(_('The report source changed. Refresh the report and try again.'))
            lines.extend(page['lines'])
            next_page = page['next_cursor']
        if [line['id'] for line in lines] != expected_ids:
            raise AccessError(_('The complete posted journal source is not available for this report.'))
        arabic = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        labels = (['التاريخ', 'القيد', 'البيان', 'مدين', 'دائن', 'الرصيد الجاري'] if arabic else
                  ['Date', 'Journal entry', 'Label', 'Debit', 'Credit', 'Running balance'])
        specs = [('date', 'date', 15), ('entry', 'text', 24), ('label', 'text', 40),
                 ('debit', 'money', 20), ('credit', 'money', 20), ('running', 'money', 20)]
        columns = [{'key': key, 'label': label, 'type': kind, 'width': width}
                   for (key, kind, width), label in zip(specs, labels)]
        rows = [{'kind': 'section', 'cells': {
            'label': 'الرصيد الافتتاحي' if arabic else 'Opening balance',
            'running': source_money(first['opening']),
        }}]
        for line in lines:
            rows.append({'kind': 'detail', 'cells': {
                'date': date.fromisoformat(line['date']), 'entry': line['move_name'], 'label': line['label'],
                **{key: source_money(line[key]) for key in ('debit', 'credit', 'running')},
            }})
        rows.append({'kind': 'total', 'cells': {
            'label': 'إجمالي الفترة والرصيد الختامي' if arabic else 'Period totals and closing balance',
            'debit': source_money(first['debit']), 'credit': source_money(first['credit']),
            'running': source_money(first['closing']),
        }})
        return export_document(self.env, 'حركة حساب' if arabic else 'Account Activity', columns, rows,
            metadata=[('الحساب' if arabic else 'Account', first['account_name']),
                      ('الفترة' if arabic else 'Period', filters['date_from'] + ' — ' + filters['date_to'])],
            notes=['قيود مرحلة · شركة واحدة · سنة مالية واحدة' if arabic else
                   'Posted entries · one company · one fiscal year'])

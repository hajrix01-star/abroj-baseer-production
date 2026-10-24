"""Exact, bounded amount drilldowns; the existing report remains the authority."""

from decimal import Decimal

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.addons.baseer_reports_menu.report_drill import drill_result
from odoo.addons.baseer_reports_menu.report_values import require_active_filters


class GeneralLedgerDrill(models.AbstractModel):
    _inherit = 'baseer.general.ledger.report'

    DRILL_SOURCE_LIMIT = 5000

    def _drill_text(self, arabic, english):
        return arabic if self.env.context.get('lang', '').startswith('ar') else english

    def _drill_validate(self, filters, selector, measures):
        require_active_filters(self.env, filters, {'date_from', 'date_to', 'journal_ids'})
        if type(selector) is not dict:
            raise ValidationError(_('Select a valid report amount.'))
        kind = selector.get('kind')
        keys = {'kind', 'measure'} | ({'account_id'} if kind in ('account', 'rbf_account') else set())
        if (type(kind) is not str or kind not in measures or set(selector) != keys
                or type(selector.get('measure')) is not str or selector['measure'] not in measures[kind]):
            raise ValidationError(_('Select a valid report amount.'))
        if 'account_id' in keys and (type(selector['account_id']) is not int or selector['account_id'] <= 0):
            raise ValidationError(_('Select a valid account.'))

    def _drill_columns(self):
        return [{'key': 'label', 'label': self._drill_text('المكوّن', 'Component')},
                {'key': 'amount', 'label': self._drill_text('المبلغ', 'Amount'), 'numeric': True}]

    def _drill_measure_label(self, measure):
        labels = {
            'opening': ('الرصيد الافتتاحي', 'Opening balance'),
            'closing': ('الرصيد الختامي', 'Closing balance'),
            'debit': ('حركة المدين', 'Debit movement'), 'credit': ('حركة الدائن', 'Credit movement'),
            'opening_debit': ('الافتتاحي المدين', 'Opening debit side'),
            'opening_credit': ('الافتتاحي الدائن', 'Opening credit side'),
            'closing_debit': ('الختامي المدين', 'Closing debit side'),
            'closing_credit': ('الختامي الدائن', 'Closing credit side'),
            'amount': ('المساهمة المرحلة', 'Brought-forward contribution'),
        }
        return self._drill_text(*labels[measure])

    def _drill_component(self, key, label, amount, selector):
        return {'key': str(key), 'cells': {'label': label, 'amount': amount}, 'drill': selector}

    def _drill_rbf_accounts(self, filters):
        """Reuse the existing authoritative RBF collector, never infer signs anew."""
        first = self.get_rbf_accounts(filters, 1)
        count = first['account_count']
        if count > self.DRILL_SOURCE_LIMIT:
            raise ValidationError(_('Select a narrower period or fewer journals.'))
        rows = list(first['accounts'])
        for page in range(2, (count + self.PAGE_SIZE - 1) // self.PAGE_SIZE + 1):
            result = self.get_rbf_accounts(filters, page)
            if result['account_count'] != count:
                raise AccessError(_('The report source changed. Refresh the report.'))
            rows.extend(result['accounts'])
        if len(rows) != count or len({row['id'] for row in rows}) != count:
            raise AccessError(_('The complete report source is not available.'))
        return rows

    def _drill_account_domain(self, filters, account_id, scope):
        company, start, end, fiscal_start, _journals, base = self._filters(filters)
        account = self._accounts({account_id}, company)[account_id]
        domain = base & Domain('account_id', '=', account.id)
        if scope == 'rbf':
            if account.include_initial_balance:
                raise AccessError(_('This account is not part of the brought-forward result.'))
            domain &= Domain('date', '<', fiscal_start)
        elif scope in ('debit', 'credit'):
            domain &= Domain('date', '>=', start) & Domain('date', '<=', end) & Domain(scope, '!=', 0)
        elif scope in ('opening', 'closing'):
            domain &= Domain('date', '<', start) if scope == 'opening' else Domain('date', '<=', end)
            if not account.include_initial_balance:
                domain &= Domain('date', '>=', fiscal_start)
        else:
            raise ValidationError(_('Select a valid source scope.'))
        return domain

    def _drill_selection(self, filters, selector):
        measures = ('opening', 'debit', 'credit', 'closing')
        self._drill_validate(filters, selector, {
            'account': measures, 'total': measures,
            'rbf': ('opening', 'closing'), 'rbf_account': ('opening', 'closing'),
        })
        report = self._build_report(filters, full=True)
        kind, measure = selector['kind'], selector['measure']
        title = self._drill_text('دفتر الأستاذ العام', 'General Ledger') + ' · ' + self._drill_measure_label(measure)
        basis = self._drill_text(
            'المبلغ من التقرير. الرصيد = المدين − الدائن، مع إعادة ضبط الحسابات غير المرحلة عند بداية السنة المالية.',
            'Authoritative report amount. Balance = debit − credit; non-carry-forward accounts reset at the fiscal boundary.')
        if kind == 'total':
            rows = [self._drill_component('account:' + str(row['id']), f"{row['code']} {row['name']}", row[measure],
                    {'kind': 'account', 'account_id': row['id'], 'measure': measure}) for row in report['accounts']]
            if measure in ('opening', 'closing'):
                rows.append(self._drill_component('rbf', self._drill_text('النتيجة المرحلة', 'Result brought forward'),
                    report['rbf']['amount'], {'kind': 'rbf', 'measure': measure}))
            return {'title': title, 'value': report['total'][measure], 'basis': basis, 'rows': rows}
        if kind in ('rbf', 'rbf_account'):
            accounts = self._drill_rbf_accounts(filters)
            if kind == 'rbf':
                rows = [self._drill_component(row['id'], f"{row['code']} {row['name']}", row['amount'],
                        {'kind': 'rbf_account', 'account_id': row['id'], 'measure': measure}) for row in accounts]
                return {'title': title, 'value': report['rbf']['amount'], 'basis': basis, 'rows': rows}
            value_key, scope = 'amount', 'rbf'
        else:
            accounts, value_key, scope = report['accounts'], measure, measure
        matching = [row for row in accounts if row['id'] == selector['account_id']]
        if len(matching) != 1:
            raise AccessError(_('The account is not part of this report amount.'))
        row = matching[0]
        if scope in ('debit', 'credit'):
            basis = self._drill_text('حركة الجانب المحدد خلال الفترة فقط؛ لا تشمل الرصيد الافتتاحي.',
                                    'Selected-side movement within the period only; no opening-balance fallback.')
        return {'title': f"{row['code']} {row['name']} · {self._drill_measure_label(measure)}", 'value': row[value_key], 'basis': basis,
                'domain': self._drill_account_domain(filters, row['id'], scope),
                'contribution': scope if scope in ('debit', 'credit') else 'balance', 'sign': 1}

    def _drill_complete_lines(self, domain):
        AML = self.env['account.move.line'].with_context(active_test=False)
        if {'debit', 'credit'} - AML.fields_get(['debit', 'credit']).keys():
            raise AccessError(_('The report amount fields are not available.'))
        lines = AML.search(domain, order='date,id', limit=self.DRILL_SOURCE_LIMIT + 1)
        if len(lines) > self.DRILL_SOURCE_LIMIT:
            raise ValidationError(_('Source details are limited to 5,000 entries. Select a narrower period or fewer journals.'))
        self._verify_links(lines)
        return lines

    def _drill_source_rows(self, selection, selector):
        lines = self._drill_complete_lines(selection['domain'])
        if not lines:
            return []
        # Exact stored NUMERIC text, only after every selected source and link is authorized.
        lines.flush_recordset(['debit', 'credit'])
        self.env.cr.execute('SELECT id, debit::text, credit::text FROM account_move_line WHERE id = ANY(%s)', [lines.ids])
        amounts = {identity: (Decimal(debit), Decimal(credit)) for identity, debit, credit in self.env.cr.fetchall()}
        if set(amounts) != set(lines.ids):
            raise AccessError(_('The report source changed. Refresh the report.'))
        rows = []
        for line in lines:
            debit, credit = amounts[line.id]
            contribution = {'debit': debit, 'credit': credit, 'balance': debit - credit}[selection['contribution']]
            contribution *= selection['sign']
            rows.append({'key': str(line.id), 'cells': {
                'date': fields.Date.to_string(line.date), 'label': line.move_id.name or line.name or '',
                'debit': self._money(debit, self.env.company.currency_id),
                'credit': self._money(credit, self.env.company.currency_id),
                'amount': self._money(contribution, self.env.company.currency_id),
            }, 'source': {'kind': 'source', 'parent': dict(selector), 'line_id': line.id}})
        return rows

    def _get_drilldown(self, filters, selector, page=1):
        selection = self._drill_selection(filters, selector)
        columns = self._drill_columns()
        if 'domain' in selection:
            rows = self._drill_source_rows(selection, selector)
            columns = [
                {'key': 'date', 'label': self._drill_text('التاريخ', 'Date')},
                {'key': 'label', 'label': self._drill_text('القيد', 'Entry')},
                {'key': 'debit', 'label': self._drill_text('مدين المصدر', 'Source debit'), 'numeric': True},
                {'key': 'credit', 'label': self._drill_text('دائن المصدر', 'Source credit'), 'numeric': True},
                {'key': 'amount', 'label': self._drill_text('المساهمة الموقّعة', 'Signed contribution'), 'numeric': True},
            ]
        else:
            rows = selection['rows']
        return drill_result(selection['title'], selection['value'], selection['basis'], columns, rows, page=page)

    def _open_drill_source(self, filters, selector):
        if (type(selector) is not dict or set(selector) != {'kind', 'parent', 'line_id'}
                or selector.get('kind') != 'source' or type(selector.get('line_id')) is not int
                or selector['line_id'] <= 0):
            raise ValidationError(_('Select a valid report source.'))
        selection = self._drill_selection(filters, selector['parent'])
        if 'domain' not in selection:
            raise ValidationError(_('Select a source from the account details.'))
        lines = self._drill_complete_lines(selection['domain'])
        line = lines.filtered(lambda row: row.id == selector['line_id'])
        if len(line) != 1:
            raise AccessError(_('The source is not part of this report amount.'))
        return {'type': 'ir.actions.act_window', 'name': _('Journal Entry'),
                'res_model': 'account.move', 'res_id': line.move_id.id,
                'views': [[False, 'form']], 'target': 'current'}

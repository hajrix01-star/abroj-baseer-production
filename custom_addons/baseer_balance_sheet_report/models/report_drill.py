"""Balance-sheet display signs and fiscal bridge scopes come from its calculator."""

from odoo import _, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.addons.baseer_reports_menu.report_values import require_active_filters


class BalanceSheetDrill(models.AbstractModel):
    _inherit = 'baseer.balance.sheet.report'

    def _drill_selection(self, filters, selector):
        require_active_filters(self.env, filters, {'date_from', 'date_to', 'journal_ids'})
        if type(selector) is not dict:
            raise ValidationError(_('Select a valid balance sheet amount.'))
        kind = selector.get('kind')
        expected = {'equation': {'kind', 'equation'}, 'section': {'kind', 'section'},
                    'account': {'kind', 'section', 'account_id'}}
        if type(kind) is not str or kind not in expected or set(selector) != expected[kind]:
            raise ValidationError(_('Select a valid balance sheet amount.'))
        if kind == 'equation':
            if type(selector['equation']) is not str or selector['equation'] not in ('assets', 'liabilities_equity_results'):
                raise ValidationError(_('Select a valid balance sheet total.'))
        elif type(selector['section']) is not str or selector['section'] not in self.SECTIONS:
            raise ValidationError(_('Select a valid balance sheet section.'))
        if kind == 'account' and (type(selector['account_id']) is not int or selector['account_id'] <= 0):
            raise ValidationError(_('Select a valid account.'))
        report = self._build_pdf_report(filters)
        labels = {
            'assets': self._drill_text('الأصول', 'Assets'),
            'liabilities': self._drill_text('الالتزامات', 'Liabilities'),
            'equity': self._drill_text('حقوق الملكية', 'Equity'),
            'brought_forward': self._drill_text('النتيجة المرحلة', 'Result brought forward'),
            'current_result': self._drill_text('نتيجة السنة الحالية', 'Current-year result'),
        }
        title = self._drill_text('الميزانية العمومية', 'Balance Sheet')
        basis = self._drill_text(
            'الأصول = المدين − الدائن؛ إشارات الالتزامات وحقوق الملكية والنتائج معكوسة للعرض. كل مساهمة تلتزم بتاريخ القطع ونطاق السنة الخاص بالقسم.',
            'Assets = debit − credit; liabilities, equity and results reverse the source sign for display. Contributions retain the cutoff and section-specific fiscal scope.')
        if kind == 'equation':
            keys = ('assets',) if selector['equation'] == 'assets' else tuple(key for key in self.SECTIONS if key != 'assets')
            rows = [self._drill_component(section['key'], labels[section['key']], section['amount'],
                    {'kind': 'section', 'section': section['key']}) for section in report['sections'] if section['key'] in keys]
            return {'title': title, 'value': report['equation'][selector['equation']], 'basis': basis, 'rows': rows}
        section = selector['section']
        accounts = report['section_accounts'][section]
        if kind == 'section':
            amount = next(row['amount'] for row in report['sections'] if row['key'] == section)
            rows = [self._drill_component(row['id'], f"{row['code']} {row['name']}", row['amount'],
                    {'kind': 'account', 'section': section, 'account_id': row['id']}) for row in accounts]
            return {'title': labels[section], 'value': amount, 'basis': basis, 'rows': rows}
        matching = [row for row in accounts if row['id'] == selector['account_id']]
        if len(matching) != 1:
            raise AccessError(_('The account is not part of this balance sheet section.'))
        row = matching[0]
        _company, _start, end, fiscal_start, _journals, base = self._filters(filters)
        domain = base & Domain('account_id', '=', row['id']) & Domain('date', '<=', end)
        if row['source_scope'] == 'current_result':
            domain &= Domain('date', '>=', fiscal_start)
        elif row['source_scope'] == 'brought_forward' and row['account_type'] != 'equity_unaffected':
            domain &= Domain('date', '<', fiscal_start)
        return {'title': f"{labels[section]} · {row['code']} {row['name']}", 'value': row['amount'], 'basis': basis,
                'domain': domain, 'contribution': 'balance', 'sign': 1 if section == 'assets' else -1}

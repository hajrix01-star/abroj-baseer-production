"""Project the verified balance-sheet bridge and its supplied display signs."""

from odoo import models
from odoo.addons.baseer_reports_menu.report_values import export_document, require_active_filters, source_money


class BalanceSheetExport(models.AbstractModel):
    _inherit = 'baseer.balance.sheet.report'

    def _get_export_document(self, filters):
        require_active_filters(self.env, filters, {'company_id', 'date_from', 'date_to', 'journal_ids'})
        report = self._build_pdf_report(filters)
        arabic = (self.env.lang or '').startswith('ar')
        labels = {
            'assets': ('الأصول', 'Assets'), 'liabilities': ('الالتزامات', 'Liabilities'),
            'equity': ('حقوق الملكية', 'Equity'), 'brought_forward': ('النتيجة المرحلة', 'Result brought forward'),
            'current_result': ('نتيجة السنة الحالية', 'Current-year result'),
        }
        columns = [{'key': 'label', 'label': 'الحساب' if arabic else 'Account', 'type': 'text', 'width': 60},
                   {'key': 'amount', 'label': 'الرصيد' if arabic else 'Balance', 'type': 'money', 'width': 24}]
        rows = []
        for section in report['sections']:
            key = section['key']
            rows.append({'kind': 'section', 'cells': {'label': labels[key][0 if arabic else 1],
                         'amount': source_money(section['amount'])}})
            for account in report['section_accounts'][key]:
                rows.append({'kind': 'detail', 'indent': 1, 'cells': {
                    'label': f"{account['code']} {account['name']}".strip(), 'amount': source_money(account['amount']),
                }})
        for key, label in (('assets', 'إجمالي الأصول' if arabic else 'Total assets'),
                           ('liabilities_equity_results', 'إجمالي الالتزامات وحقوق الملكية والنتائج' if arabic
                            else 'Total liabilities, equity and results')):
            rows.append({'kind': 'total', 'cells': {'label': label, 'amount': source_money(report['equation'][key])}})
        return export_document(self.env, 'الميزانية العمومية' if arabic else 'Balance Sheet', columns, rows,
                               metadata=self._ledger_export_metadata(filters, report),
                               notes=['الأرصدة حتى نهاية الفترة، من القيود المرحلة' if arabic
                                      else 'Balances through period end, from posted entries'])

"""Project existing trial-balance values without deriving debit/credit again."""

from odoo import models
from odoo.addons.baseer_reports_menu.report_values import export_document, require_active_filters, source_money


class TrialBalanceExport(models.AbstractModel):
    _inherit = 'baseer.trial.balance.report'

    def _get_export_document(self, filters):
        require_active_filters(self.env, filters, {'company_id', 'date_from', 'date_to', 'journal_ids'})
        report = self._build_trial_balance(filters, full=True)
        arabic = (self.env.lang or '').startswith('ar')
        keys = ('opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit')
        labels = (('افتتاحي مدين', 'افتتاحي دائن', 'حركة مدين', 'حركة دائن', 'ختامي مدين', 'ختامي دائن') if arabic
                  else ('Opening debit', 'Opening credit', 'Movement debit', 'Movement credit', 'Closing debit', 'Closing credit'))
        columns = [{'key': 'label', 'label': 'الحساب' if arabic else 'Account', 'type': 'text', 'width': 42}]
        columns += [{'key': key, 'label': label, 'type': 'money', 'width': 20} for key, label in zip(keys, labels)]
        rows = []
        if report['rbf']['source_line_count']:
            rows.append({'kind': 'section', 'cells': {
                'label': 'نتيجة مرحلة من السنة السابقة' if arabic else 'Result brought forward',
                **{key: source_money(report['rbf'][key]) for key in keys if key not in ('debit', 'credit')},
            }})
        for account in report['accounts']:
            rows.append({'kind': 'detail', 'cells': {
                'label': f"{account['code']} {account['name']}".strip(),
                **{key: source_money(account[key]) for key in keys},
            }})
        rows.append({'kind': 'total', 'cells': {'label': 'الإجمالي' if arabic else 'Total',
                     **{key: source_money(report['total'][key]) for key in keys}}})
        return export_document(self.env, 'ميزان المراجعة' if arabic else 'Trial Balance', columns, rows,
                               metadata=self._ledger_export_metadata(filters, report),
                               notes=['قيود مرحلة فقط' if arabic else 'Posted entries only'])

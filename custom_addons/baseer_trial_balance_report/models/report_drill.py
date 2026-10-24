"""Trial-balance sides are net positions, never raw debit/credit source totals."""

from odoo import _, models
from odoo.exceptions import AccessError


class TrialBalanceDrill(models.AbstractModel):
    _inherit = 'baseer.trial.balance.report'

    def _drill_selection(self, filters, selector):
        measures = ('opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit')
        self._drill_validate(filters, selector, {
            'account': measures, 'total': measures,
            'rbf': ('opening_debit', 'opening_credit', 'closing_debit', 'closing_credit'),
            'rbf_account': ('amount',),
        })
        report = self._build_trial_balance(filters, full=True)
        kind, measure = selector['kind'], selector['measure']
        title = self._drill_text('ميزان المراجعة', 'Trial Balance') + ' · ' + self._drill_measure_label(measure)
        basis = self._drill_text(
            'الافتتاحي والختامي جانبا رصيد صافٍ، وليسا مجموع مدين أو دائن القيود. الجانب الصفري قد يقابله رصيد في الجانب الآخر. المساهمات تعرض المدين ناقص الدائن قبل تصنيف الجانب.',
            'Opening and closing are sides of a net position, not raw journal debit or credit totals. A zero side may have a balance on the opposite side. Contributions show debit minus credit before side classification.')
        if kind == 'total':
            rows = [self._drill_component('account:' + str(row['id']), f"{row['code']} {row['name']}", row[measure],
                    {'kind': 'account', 'account_id': row['id'], 'measure': measure}) for row in report['accounts']]
            if measure in report['rbf']:
                rows.append(self._drill_component('rbf', self._drill_text('النتيجة المرحلة', 'Result brought forward'),
                    report['rbf'][measure], {'kind': 'rbf', 'measure': measure}))
            return {'title': title, 'value': report['total'][measure], 'basis': basis, 'rows': rows}
        if kind in ('rbf', 'rbf_account'):
            accounts = self._drill_rbf_accounts(filters)
            if kind == 'rbf':
                basis = self._drill_text(
                    'جانب صافي النتيجة المرحلة يُصنّف بعد جمع المساهمات الموقّعة لجميع الحسابات، وليس بجمع جوانبها منفردة.',
                    'The brought-forward net side is classified after combining all signed account contributions, not by adding their individual debit/credit sides.')
                rows = [self._drill_component(row['id'], f"{row['code']} {row['name']}", row['amount'],
                        {'kind': 'rbf_account', 'account_id': row['id'], 'measure': 'amount'}) for row in accounts]
                return {'title': title, 'value': report['rbf'][measure], 'basis': basis, 'rows': rows}
            value_key, scope = 'amount', 'rbf'
        else:
            accounts, value_key = report['accounts'], measure
            scope = measure.split('_')[0] if '_' in measure else measure
        matching = [row for row in accounts if row['id'] == selector['account_id']]
        if len(matching) != 1:
            raise AccessError(_('The account is not part of this report amount.'))
        row = matching[0]
        if scope in ('debit', 'credit'):
            basis = self._drill_text('حركة الجانب المحدد خلال الفترة فقط؛ دون رصيد افتتاحي.',
                                    'Selected-side period movement only, without opening balance.')
        return {'title': f"{row['code']} {row['name']} · {self._drill_measure_label(measure)}", 'value': row[value_key], 'basis': basis,
                'domain': self._drill_account_domain(filters, row['id'], scope),
                'contribution': scope if scope in ('debit', 'credit') else 'balance', 'sign': 1}

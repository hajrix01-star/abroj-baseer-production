"""Small intentional demo on the existing QA only, never on original."""
import json
from pathlib import Path
from odoo import Command

assert env.cr.dbname == 'baseer_ar1_roles_20260910' and env.su
company = env['res.company'].browse(2).exists()
assert company.currency_id.name == 'SAR'
actor = env(context=dict(env.context, allowed_company_ids=company.ids, tracking_disable=True, mail_create_nolog=True))
Move = actor['account.move']
month, day, tag = '2026-02', '2026-02-10', 'FL2 CASH DEMO'
existing = Move.search([('company_id', '=', company.id), ('ref', '=like', tag + '%')])
if not existing:
    snapshot = Move._register_cash_snapshot(month)
    assert not snapshot[3], 'Demo month already has cash; choose a different empty month'
    journals = actor['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])])
    journals = journals.filtered(lambda j: j.default_account_id.account_type == 'asset_cash')
    journal = journals[:1]
    cash = journal.default_account_id
    second = (journals.default_account_id - cash)[:1]
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_loan_account_id | company.baseer_deduction_account_id
    def account(kind):
        return actor['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', kind), ('id', 'not in', private.ids)], limit=1)
    income, expense = account('income'), account('expense')
    assert cash and second and income and expense
    def entry(label, lines, state='posted'):
        move = Move.create({'company_id': company.id, 'journal_id': journal.id, 'date': day,
            'ref': tag + ' ' + label, 'line_ids': [Command.create({'name': tag + ' ' + label,
                'account_id': acc.id, 'debit': max(amount, 0), 'credit': max(-amount, 0)}) for acc, amount in lines]})
        if state == 'posted':
            move.action_post()
        elif state == 'cancel':
            move.button_cancel()
        return move
    entry('Receipts 8000', [(cash, 8000), (income, -8000)])
    entry('Payments 5000', [(expense, 5000), (cash, -5000)])
    entry('Internal transfer 1200', [(cash, 1200), (second, -1200)])
    entry('Excluded draft 99999', [(expense, 99999), (cash, -99999)], 'draft')
    entry('Excluded cancelled 99999', [(expense, 99999), (cash, -99999)], 'cancel')
snapshot = Move._register_cash_snapshot(month)
totals = snapshot[2]['meta']['exact_totals']
assert {k: totals[k] for k in ('receipts', 'payments', 'actual_net_movement')} == {
    'receipts': '8000.00', 'payments': '-5000.00', 'actual_net_movement': '3000.00'}
assert len(snapshot[3]) == 2
result = {'database': env.cr.dbname, 'company_id': company.id, 'month': month,
          'report_totals': totals, 'visible_cash_moves': sorted(snapshot[3]),
          'action_id': env.ref('baseer_financial_register.action_financial_register').id,
          'note': 'Intentional small QA-only demo; cancelled/draft/internal-transfer entries do not inflate cash cards.'}
env.cr.commit()
Path('/mnt/qa-evidence/fl2-ui-fixture.json').write_text(json.dumps(result, indent=2), encoding='utf8')
print('FL2_UI_DEMO_READY', month, 'receipts8000 payments5000 net3000')

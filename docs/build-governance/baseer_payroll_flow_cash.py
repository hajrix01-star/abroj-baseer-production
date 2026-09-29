"""Reviewed R4 native configuration of exact QA cash account; no payments."""
import json
from pathlib import Path
assert env.cr.dbname=='baseer_reports_qa_20260907'
E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10]},su=False)
j=E['account.journal'].browse(125);a=E['account.account'].browse(1244)
env.cr.execute('SELECT id FROM account_account WHERE id=1244 FOR UPDATE')
assert j.company_id.id==10 and j.type=='cash' and j.default_account_id==a and a.account_type=='asset_cash'
assert j.outbound_payment_method_line_ids.ids==[106] and j.inbound_payment_method_line_ids.ids==[105]
assert all(m.payment_account_id==a for m in j.outbound_payment_method_line_ids|j.inbound_payment_method_line_ids)
lines=E['account.move.line'].search([('account_id','=',a.id)])
assert lines.ids==[2508] and lines.move_id.id==1025 and lines.debit==150 and lines.credit==0
assert not lines.matched_debit_ids and not lines.matched_credit_ids
before=lines.read(['move_id','debit','credit','amount_residual','reconciled'])
loan=E['baseer.hr.loan'].browse(13);balance=loan.balance
a.write({'reconcile':False})
assert lines.debit==150 and lines.credit==0 and lines.amount_residual==0 and loan.balance==balance
R={'status':'passed','account_id':1244,'journal_id':125,'before':before,'after':lines.read(['move_id','debit','credit','amount_residual','reconciled']),'loan_balance_unchanged':balance,'operation':'Native reconcile=False; no payment, entry or allocation created'}
env.cr.commit()
Path('/mnt/qa-evidence/baseer_payroll_flow_cash.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(R,ensure_ascii=False))

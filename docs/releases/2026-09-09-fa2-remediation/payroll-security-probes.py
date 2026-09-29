    a=employee('ABA advance',3000,'2040-01-01')
    loan=E['baseer.hr.loan'].create({'employee_id':a.id,'amount':1000,'installment_count':2,
        'date':'2040-01-01','first_due_date':'2040-01-31','journal_id':bank.id});loan.action_disburse()
    old=E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'advance','date':'2040-02-01','reason':'Opened before recovery cycle','reviewed':True})
    repayment=E['baseer.hr.loan.repay'].create({'loan_id':loan.id,'amount':100,'date':'2040-01-02','journal_id':cash.id});repayment.action_confirm()
    reversal=E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'repayment','date':'2040-01-03','reason':'Review recovery correction','reviewed':True});reversal.action_confirm()
    check('ABA balance returned to same amount',q(1000),q(loan.balance))
    blocked('ABA history invalidates old wizard',old.action_confirm)
    blocked('fake loan reversal write tokenTrue',lambda:loan.with_context(baseer_payroll_internal=True).write({'reversal_move_id':loan.move_id.id}))
    blocked('fake loan reversal create default tokenTrue',lambda:E['baseer.hr.loan'].with_context(baseer_payroll_internal=True,default_reversal_move_id=loan.move_id.id).create({
        'employee_id':a.id,'amount':100,'date':'2040-01-01','first_due_date':'2040-01-31','journal_id':bank.id}))
    blocked('fake correction snapshot tokenTrue',lambda:E['baseer.payroll.correction'].with_context(baseer_payroll_internal=True).create({
        'loan_id':loan.id,'kind':'advance','date':'2040-02-01','reason':'Injected','source_snapshot':{'move':loan.move_id.id}}))
    blocked('fake native correction source default tokenTrue',lambda:E['account.move'].with_context(baseer_payroll_internal=True,
        default_baseer_correction_source_id=loan.move_id.id).create({'move_type':'entry','journal_id':C.baseer_payroll_journal_id.id,'date':'2040-01-31'}))
    run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2040-01-01'});run.action_approve();slip=run.slip_ids
    blocked('fake original net stored compute',lambda:slip.with_context(baseer_payroll_internal=True).write({'baseer_original_net':1}))
    blocked('fake recovery reversal write tokenTrue',lambda:loan.allocation_ids.with_context(baseer_payroll_internal=True).write({'reversal_move_id':loan.move_id.id}))
    # A loan returned to full principal can be corrected once with a fresh review.
    reverse_payroll=E['baseer.payroll.correction'].create({'slip_id':slip.id,'kind':'payroll_recovery','date':'2040-02-01','reason':'Fresh source evidence','reviewed':True});reverse_payroll.action_confirm()
    fresh=E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'advance','date':'2040-02-02','reason':'Fresh source evidence','reviewed':True});fresh.action_confirm()
    check('cancelled schedule outstanding zero',q(0),q(sum(loan.line_ids.mapped('balance'))))
    check('cancelled schedule retained amount',q(1000),q(sum(loan.line_ids.mapped('amount'))))
    check('cancelled schedule states',{'cancel'},set(loan.line_ids.mapped('state')))
    blocked('reversed advance cannot disburse again',loan.action_disburse)
    blocked('reversed source cannot reopen correction',lambda:E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'advance','date':'2040-02-02','reason':'Replay','reviewed':True}))
    R['status']='completed'
    assert all(c['pass'] for c in R['checks'])
    assert all(o.get('blocked',True) for o in R['observations'])

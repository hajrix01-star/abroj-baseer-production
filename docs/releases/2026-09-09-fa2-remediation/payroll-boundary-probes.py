    C.baseer_proration='fixed30'
    b=employee('Cross month half leave',3000,'2037-01-01')
    lt=E['hr.leave.type'].create({'name':'FA2 cross month','requires_allocation':False,'leave_validation_type':'no_validation',
        'baseer_unpaid':True,'request_unit':'half_day'})
    leave=E['hr.leave'].create({'employee_id':b.id,'holiday_status_id':lt.id,'request_date_from':'2037-08-31',
        'request_date_to':'2037-09-01','request_date_from_period':'pm','request_date_to_period':'am'})
    if leave.state!='validate':leave.action_validate()
    check('native cross month approved duration',q(1),q(leave.number_of_days))
    for month in ['2037-08-01','2037-09-01']:
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':month})
        check('cross month clipped half '+month,q(2950),q(run.slip_ids.baseer_gross))
    b.baseer_payroll_enabled=False
    c=employee('Mixed writeoff',3000,'2038-01-01')
    run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2038-01-01'});run.action_approve();slip=run.slip_ids
    action=slip.action_pay()
    w=E['account.payment.register'].with_context(**action['context']).create({'journal_id':cash.id,
        'payment_method_line_id':cash.outbound_payment_method_line_ids[:1].id,'payment_date':'2038-01-31','amount':2500,
        'payment_difference_handling':'reconcile','writeoff_account_id':C.baseer_deduction_account_id.id,'writeoff_label':'Approved noncash500'})
    p=w._create_payments()
    check('mixed native payment actual amount',q(2500),q(sum(p.mapped('amount'))))
    check('mixed paid excludes writeoff',q(2500),q(slip.baseer_paid))
    check('mixed settled entire obligation',q(3000),q(slip.baseer_settled))
    check('mixed residual',q(0),q(slip.baseer_residual))
    check('mixed stage','settled',slip.baseer_payment_state)
    check('mixed statement only cash',q(2500),q(run._baseer_payment_total()))
    for lang in ['en_US','ar_001']:
        payload,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_payroll.action_report_baseer_payment_receipt',res_ids=run.ids)
        Path('/mnt/qa-evidence/payroll-mixed-payment-'+lang+'.pdf').write_bytes(payload)
    c.baseer_payroll_enabled=False
    # One employee, three outstanding monthly salaries. 1 SAR cash settles 3 SAR
    # through a reviewed 2 SAR writeoff; rounding must conserve the 1 SAR.
    d=employee('Mixed cent allocation',1,'2039-01-01');d.version_id.baseer_allowance_total=0
    small=E['hr.payslip']
    for month in range(1,4):
        r=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':date(2039,month,1)});r.action_approve();small|=r.slip_ids
    w=E['account.payment.register'].with_context(**small.action_pay()['context']).create({'journal_id':cash.id,
        'payment_method_line_id':cash.outbound_payment_method_line_ids[:1].id,'payment_date':'2039-03-31','amount':1,
        'group_payment':True,'payment_difference_handling':'reconcile','writeoff_account_id':C.baseer_deduction_account_id.id})
    w._create_payments()
    check('three salaries cent allocation conserved',q(1),q(sum(small.mapped('baseer_paid'))))
    check('three salaries mixed settled',q(3),q(sum(small.mapped('baseer_settled'))))
    d.baseer_payroll_enabled=False
    import io
    from odoo.tools.translate import trans_export
    output=io.BytesIO();trans_export('ar_001',['baseer_payroll'],output,'po',E)
    Path('/mnt/qa-evidence/payroll-export-ar.po').write_bytes(output.getvalue())
    R['status']='completed'
    assert all(c['pass'] for c in R['checks'])

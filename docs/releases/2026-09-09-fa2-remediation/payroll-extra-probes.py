# Inserted inside the independently calculated six-month fixture; not a standalone shell script.
    def additional_probes():
        C.baseer_proration='fixed30'
        bank.outbound_payment_method_line_ids[:1].payment_account_id=bank.default_account_id
        b=employee('Half leave',3000,'2034-01-01')
        unpaid=E['hr.leave.type'].create({'name':'FA2 half unpaid','requires_allocation':False,
            'leave_validation_type':'no_validation','baseer_unpaid':True,'request_unit':'half_day'})
        leave=E['hr.leave'].create({'name':'approved half day','employee_id':b.id,'holiday_status_id':unpaid.id,
            'request_date_from':'2034-03-06','request_date_to':'2034-03-06','request_date_from_period':'am','request_date_to_period':'am'})
        if leave.state!='validate':leave.action_validate()
        check('native half day duration',q('.5'),q(leave.number_of_days))
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2034-03-01'})
        check('fixed30 half day gross',q(2950),q(run.slip_ids.baseer_gross));run.action_approve();slip=run.slip_ids
        original=[(l.id,l.account_id.id,l.partner_id.id,l.debit,l.credit) for l in slip.move_id.line_ids]
        def pay(s,amount,when):
            action=s.action_pay()
            wizard=E['account.payment.register'].with_context(**action['context']).create({'journal_id':cash.id,
                'payment_method_line_id':cash.outbound_payment_method_line_ids[:1].id,'payment_date':when,'amount':float(amount),
                'payment_difference_handling':'open','group_payment':True})
            return wizard._create_payments()
        def correct(s=None,l=None,kind='wage',amount=0,when='2034-03-31'):
            w=E['baseer.payroll.correction'].create({'slip_id':s.id if s else False,'loan_id':l.id if l else False,
                'kind':kind,'amount':amount,'date':when,'reason':'Independent documented FA2 correction','reviewed':True})
            w.action_confirm(); first=w.move_id.id;w.action_confirm();check('correction replay same native move',first,w.move_id.id)
            return w
        pay(slip,1000,'2034-03-31')
        check('partial native cash paid',q(1000),q(slip.baseer_paid))
        correct(s=slip,kind='deduction',amount=100)
        check('deduction revised net',q(2850),q(slip.baseer_net))
        check('deduction revised debt',q(1850),q(slip.baseer_residual))
        blocked('correction cannot fake refund',lambda:correct(s=slip,kind='wage',amount=-1850.01))
        pay(slip,1850,'2034-03-31');check('corrected fully paid',q(2850),q(slip.baseer_paid))
        stale=E['baseer.payroll.correction'].create({'slip_id':slip.id,'kind':'wage','amount':50,'date':'2034-03-31','reason':'stale','reviewed':True})
        correct(s=slip,amount=125.55)
        check('paid positive correction debt',q(125.55),q(slip.baseer_residual))
        blocked('stale different correction wizard',stale.action_confirm)
        pay(slip,125.55,'2034-03-31')
        check('corrected payments total',q(2975.55),q(slip.baseer_paid))
        check('original accrual preserved',original,[(l.id,l.account_id.id,l.partner_id.id,l.debit,l.credit) for l in slip.move_id.line_ids])
        check('original net retained',q(2950),q(slip.baseer_original_net))
        check('adjustment native sum',q(25.55),q(slip.baseer_adjustment))
        for lang in ['en_US','ar_001']:
            payload,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_payroll.action_report_baseer_payslips',res_ids=slip.ids)
            Path('/mnt/qa-evidence/payroll-correction-'+lang+'.pdf').write_bytes(payload)
        b.baseer_payroll_enabled=False
        c=employee('Recovery corrections',3000,'2035-01-01')
        advance=E['baseer.hr.loan'].create({'employee_id':c.id,'amount':1000,'installment_count':2,
            'date':'2035-01-01','first_due_date':'2035-01-31','journal_id':bank.id});advance.action_disburse()
        jan=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2035-01-01'});jan.action_approve();s=jan.slip_ids
        check('first payroll recovery balance',q(500),q(advance.balance))
        repay=E['baseer.hr.loan.repay'].create({'loan_id':advance.id,'amount':150,'date':'2035-02-01','journal_id':cash.id});repay.action_confirm()
        blocked('older payroll recovery reversal blocked',lambda:correct(s=s,kind='payroll_recovery',when='2035-02-02'))
        repay_reversal=correct(l=advance,kind='repayment',when='2035-02-02')
        check('repayment reverse native link',repay.move_id.id,repay_reversal.move_id.reversed_entry_id.id)
        check('repayment reversal restored receivable',q(500),q(advance.balance))
        check('repayment history retained',q(150),q(repay.move_id.line_ids.filtered(lambda line:line.account_id==cash.default_account_id).debit))
        pay(s,2500,'2035-02-02')
        rec=correct(s=s,kind='payroll_recovery',when='2035-02-03')
        check('loan recovery reversal revised net',q(3000),q(s.baseer_net))
        check('loan recovery reversal new salary debt',q(500),q(s.baseer_residual))
        check('loan recovery reversal receivable restored',q(1000),q(advance.balance))
        check('loan recovery installments reopened',q(1000),q(sum(advance.line_ids.mapped('balance'))))
        check('historical payroll source deduction preserved',q(500),q(s.baseer_loan_amount))
        blocked('second recovery reversal new wizard blocked',lambda:correct(s=s,kind='payroll_recovery',when='2035-02-03'))
        reverse=correct(l=advance,kind='advance',when='2035-02-04')
        check('advance reversal native link',advance.move_id.id,reverse.move_id.reversed_entry_id.id)
        check('reversed advance no debt',q(0),q(advance.balance))
        check('reversed advance not falsely recovered',q(0),q(advance.paid_amount))
        check('advance reversed state','cancel',advance.state)
        pay(s,500,'2035-02-04');check('recovery reversal revised salary paid',q(3000),q(s.baseer_paid))
        check('reversal history permanent',2,len(advance.allocation_ids))
        check('reversal history fully linked',2,len(advance.allocation_ids.filtered('reversal_move_id')))
        c.baseer_payroll_enabled=False
        d=employee('Partial contract',3000,'2036-02-15')
        partial=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2036-02-01'})
        check('fixed30 partial leap February 15 days',q(1500),q(partial.slip_ids.baseer_gross))
        d.baseer_payroll_enabled=False
        from odoo.addons.baseer_payroll.models.end_service import POLICY
        for start,end,reason,award in [('2020-01-01','2024-12-31','resignation','2500'),
            ('2020-01-01','2024-12-31','termination','7500'),('2020-01-01','2021-12-31','resignation','1000'),
            ('2020-01-01','2029-12-31','resignation','22500'),('2020-02-29','2025-02-27','resignation','2500')]:
            result=eos_formula(start,end,3000,reason,POLICY,True)
            check('v2 calendar '+start+' '+end+' '+reason,q(award),q(result[3]))
    observe('FA2 correction and calendar acceptance',additional_probes)

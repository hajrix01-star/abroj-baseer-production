"""HRS1 native QA workflow. Every fixture is rolled back, including failures."""
import json
import time
import traceback
from pathlib import Path
from odoo import api, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from decimal import Decimal
from psycopg2.errors import NotNullViolation

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA only'
R={'status':'started','checks':[],'timings':{}}
OUT=Path('/mnt/qa-evidence/hr_services_checks.json')

def check(name,condition):
    R['checks'].append({'name':name,'passed':bool(condition)})
    assert condition,name

def rejected(name,fn):
    try:
        with env.cr.savepoint(): fn()
    except (AccessError, UserError, ValidationError):
        check(name,True)
    else: check(name,False)

def fingerprint():
    result={}
    for table in ('account_move','account_move_line','account_payment','account_partial_reconcile','hr_employee','hr_payslip','baseer_hr_loan'):
        env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM '+table+' t')
        result[table]=env.cr.fetchone()
    return result

before=fingerprint()
try:
    admin=env.ref('base.user_admin')
    C=api.Environment(env.cr,admin.id,{'allowed_company_ids':[10],'lang':'en_US','tracking_disable':True})
    company=C['res.company'].browse(10)
    Service=C['baseer.hr.service']
    employee=C['hr.employee'].create({'name':'HRS1 QA employee','company_id':company.id})
    provider=C.ref('baseer_service_seed.provider_passports_company_10')
    defaults={'employee_id':employee.id,'service_type':'iqama_issue','partner_id':provider.id,
              'issue_date':'2026-08-20','invoice_date':'2026-08-20','gross_amount':100,
              'service_reference':'HRS1-QA','expiry_date':'2027-08-20'}
    def make(**updates): return Service.create(dict(defaults,**updates))
    service=make()
    check('current_company_default',service.company_id==company)
    check('correct_seed_mapping',service.category_map_id==C.ref('baseer_service_seed.mapping_iqama_issue_company_10'))
    check('draft_has_no_bill',service.state=='draft' and not service.bill_id)
    check('initial_default_suggests_passports',Service.default_get(['service_type','partner_id'])['partner_id']==provider.id)
    suggested=dict(defaults);suggested.pop('partner_id')
    auto=Service.create(suggested)
    check('create_missing_provider_suggested',auto.partner_id==provider)
    custom=C.ref('baseer_service_seed.provider_muqeem_company_10')
    auto.write({'partner_id':custom.id})
    auto.write({'notes':'manual provider kept'})
    check('manual_provider_survives_unrelated_edit',auto.partner_id==custom)
    auto.write({'service_type':'work_permit_issue'})
    check('changed_type_updates_suggested_provider',auto.partner_id==C.ref('baseer_service_seed.provider_hrsd_company_10'))
    auto.write({'service_type':'ticket','partner_id':custom.id})
    check('unmapped_service_accepts_manual_provider',auto.partner_id==custom)
    try:
        with env.cr.savepoint(): make(partner_id=False)
    except (ValidationError,NotNullViolation):
        check('explicit_empty_provider_not_silently_replaced',True)
    else: check('explicit_empty_provider_not_silently_replaced',False)
    probe=Service.new(dict(defaults,service_type='health_certificate_issue'))
    probe._onchange_service_type()
    check('onchange_health_certificate_balady',probe.partner_id==C.ref('baseer_service_seed.provider_balady_company_10'))
    probe.service_type='ticket';probe._onchange_service_type()
    check('onchange_unmapped_clears_stale_provider',not probe.partner_id)
    check('suggested_provider_respects_company',Service.with_context(allowed_company_ids=[6])._suggested_provider('iqama_issue').company_id.id==6)
    provider.active=False
    check('inactive_provider_not_suggested',not Service._suggested_provider('iqama_issue'))
    provider.active=True
    for key,label in Service._fields['service_type'].selection:
        values={'service_type':key,'notes':'HRS1 catalog coverage'}
        if key=='visa': values['visa_type']='issue'
        mapped=make(**values)
        check('catalog_expense_mapping_'+key,bool(mapped.category_map_id._validated_expense_account()))
    rejected('zero_amount_rejected',lambda:make(gross_amount=0))
    rejected('negative_amount_rejected',lambda:make(gross_amount=-10))
    rejected('three_decimal_amount_rejected',lambda:make(gross_amount=1.001))
    rejected('expiry_before_issue_rejected',lambda:make(expiry_date='2026-08-01'))
    rejected('foreign_provider_rejected',lambda:make(partner_id=C.ref('baseer_service_seed.provider_passports_company_6').id))
    rejected('foreign_company_create_rejected',lambda:make(company_id=6))
    rejected('state_cannot_be_forged',lambda:make(state='approved'))
    rejected('bill_cannot_be_forged',lambda:service.write({'bill_id':C['account.move'].search([],limit=1).id}))
    rejected('visa_subtype_required',lambda:make(service_type='visa'))
    visa=make(service_type='visa',visa_type='extend',gross_amount=50,service_reference='HRS1-VISA')
    start=time.monotonic(); service.action_approve(); R['timings']['approve_seconds']=round(time.monotonic()-start,6)
    bill=service.bill_id
    check('native_posted_supplier_bill',bill.move_type=='in_invoice' and bill.state=='posted')
    check('one_line_correct_expense_product',len(bill.invoice_line_ids)==1 and bill.invoice_line_ids.product_id==service.category_map_id.product_id and bill.invoice_line_ids.account_id.account_type=='expense')
    check('gross_and_tax_no_vat',Decimal(str(bill.amount_total))==100 and not bill.amount_tax)
    check('source_employee_in_bill_description',employee.name in bill.invoice_line_ids.name)
    check('invoice_date_preserved',str(bill.invoice_date)=='2026-08-20')
    check('honest_unpaid_status',service.payment_state==bill.payment_state and Decimal(str(service.balance))==100)
    first=bill.id; service.action_approve()
    check('repeat_approve_one_bill',service.bill_id.id==first)
    rejected('approved_amount_locked',lambda:service.write({'gross_amount':101}))
    rejected('approved_employee_locked',lambda:service.write({'employee_id':False}))
    rejected('approved_source_cannot_unlink',lambda:service.unlink())
    rejected('approved_source_cannot_reset',lambda:service.action_reset_draft())
    rejected('posted_service_cannot_cancel_directly',lambda:service.action_cancel())
    rejected('bill_line_amount_protected',lambda:bill.invoice_line_ids.write({'price_unit':99}))
    rejected('bill_source_protected',lambda:bill.write({'baseer_hr_service_id':False}))
    rejected('bill_cannot_delete',lambda:bill.unlink())
    rejected('bill_cannot_reset_draft',lambda:bill.button_draft())
    rejected('forged_context_cannot_edit_bill',lambda:bill.with_context(baseer_hr_service_internal=True).invoice_line_ids.write({'price_unit':99}))
    # Ordinary native register wizard, two different liquidity journals.
    journals=C['account.journal'].search([('company_id','=',10),('type','in',['bank','cash'])])
    def pay(amount,kind):
        journal=journals.filtered(lambda j:j.type==kind and j.outbound_payment_method_line_ids)[:1]
        method=journal.outbound_payment_method_line_ids.filtered(lambda m:m.code=='manual')[:1]
        assert method and journal.default_account_id
        # Fixture-only direct settlement setup, preserving production choices.
        method.payment_account_id=journal.default_account_id
        action=service.action_register_payment()
        wizard=C['account.payment.register'].with_context(action.get('context',{})).create({
            'journal_id':journal.id,'payment_method_line_id':method.id,
            'payment_date':'2026-08-20','amount':amount,'group_payment':True})
        payment=wizard._create_payments()
        env.flush_all();service.invalidate_recordset();bill.invalidate_recordset()
        return payment
    pay(40,'bank')
    check('partial_payment_native_state',service.payment_state==bill.payment_state and Decimal(str(service.balance))==60)
    pay(60,'cash')
    check('fully_paid_native_state',service.payment_state=='paid' and not service.balance and bill.payment_state=='paid')
    check('native_payment_history_two_methods',len(bill._get_reconciled_payments())==2)
    # VAT native inversion and original company principal VAT only.
    taxed=make(gross_amount=115,vat_enabled=True,service_reference='HRS1-VAT')
    taxed.action_approve()
    check('taxed_native_totals',round(taxed.bill_id.amount_total,2)==115 and round(taxed.bill_id.amount_tax,2)==15 and round(taxed.bill_id.amount_untaxed,2)==100)
    visa.action_approve()
    check('visa_single_bill_with_detail',len(visa.bill_id.invoice_line_ids)==1 and visa.visa_type=='extend')
    # Staff cost remains supported after departure.
    employee.active=False
    after_departure=make(service_type='ticket',service_reference='HRS1-DEPARTURE')
    check('archived_employee_supported',after_departure.employee_id==employee)
    after_departure.action_cancel()
    check('unbilled_draft_cancellation',after_departure.state=='cancel' and not after_departure.bill_id)
    after_departure.unlink()
    check('unbilled_canceled_deletion',not after_departure.exists())
    # A HR-only user gets a narrow summary, not accounting permissions.
    reader=C['res.users'].create({'name':'HRS1 HR only','login':'hrs1.qa.reader','company_id':10,
        'company_ids':[Command.set([10])],'group_ids':[Command.set([C.ref('hr.group_hr_user').id])]})
    H=Service.with_user(reader).with_context(allowed_company_ids=[10])
    view=H.browse(service.id)
    check('hr_reads_own_service_summary',view.payment_state=='paid' and not view.balance)
    rejected('hr_cannot_approve',lambda:H.browse(visa.id).action_approve())
    rejected('hr_cannot_open_bill',lambda:view.action_view_bill())
    rejected('hr_cannot_pay',lambda:view.action_register_payment())
    foreign=C['hr.employee'].with_context(allowed_company_ids=[6]).create({'name':'HRS1 other company','company_id':6})
    other=Service.with_context(allowed_company_ids=[6]).create(dict(defaults,employee_id=foreign.id,partner_id=C.ref('baseer_service_seed.provider_passports_company_6').id))
    check('hr_company_rule_hides_other',not H.search([('id','=',other.id)]))
    rejected('hr_direct_read_other_denied',lambda:H.browse(other.id).read(['gross_amount']))
    employee.active=True
    check('employee_services_navigation',employee.action_view_services()['res_model']=='baseer.hr.service')
    report=service.action_print()
    check('service_print_action',report['type']=='ir.actions.report')
    env.flush_all()
    R['status']='passed'
except Exception:
    R['status']='failed';R['traceback']=traceback.format_exc()
finally:
    env.cr.rollback();env.invalidate_all()
    R['rolled_back']=True
    check('financial_and_employee_history_preserved',fingerprint()==before)
    R['check_count']=len(R['checks'])
    OUT.write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in R.items() if k!='checks'},ensure_ascii=False))

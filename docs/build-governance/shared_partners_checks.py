"""SP1 focused cross-company workflow and preference permissions; full rollback."""
import json,traceback,time
from pathlib import Path
from odoo import api,Command
from odoo.exceptions import AccessError,UserError,ValidationError

assert env.cr.dbname=='baseer_reports_qa_20260907'
R={'status':'started','checks':[]}
def check(n,v):R['checks'].append({'name':n,'passed':bool(v)});assert v,n
def reject(n,fn):
    try:
        with env.cr.savepoint():fn()
    except (AccessError,UserError,ValidationError):check(n,True)
    else:check(n,False)
def fp():
    out={}
    for t in ('res_partner','res_users','account_move','account_move_line','account_payment','account_partial_reconcile','hr_employee','baseer_purchase_batch','baseer_hr_service'):
        env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM '+t+' t');out[t]=env.cr.fetchone()
    return out
before=fp()
try:
    uid=env.ref('base.user_admin').id
    def ce(cid):return api.Environment(env.cr,uid,{'allowed_company_ids':[cid],'lang':'en_US','tracking_disable':True})
    A=ce(6);B=ce(10)
    provider=A.ref('baseer_service_seed.provider_passports')
    check('shared_provider_active',provider.active and not provider.company_id)
    check('aliases_same_identity',provider.id==B.ref('baseer_service_seed.provider_passports_company_10').id==A.ref('baseer_service_seed.provider_passports_company_6').id)
    check('bilingual_name_available',provider.baseer_name_ar in provider.name and provider.baseer_name_en in provider.name and bool(provider.baseer_name_en))
    for term in (provider.baseer_name_ar,provider.baseer_name_en):
        found=A['res.partner'].name_search(term,domain=[('supplier_rank','>',0)])
        check('native_search_'+term,provider.id in [x[0] for x in found])
    simple=A['res.partner'].create({'name':'SP1 ordinary name','company_id':6})
    check('ordinary_contact_name_unchanged',simple.name=='SP1 ordinary name')
    bi=A['res.partner'].create({'baseer_name_ar':'اختبار مورد','baseer_name_en':'Supplier Test','supplier_rank':1})
    check('bilingual_create_composes_native_name','اختبار مورد' in bi.name and 'Supplier Test' in bi.name)
    bi.write({'baseer_name_en':'Updated Supplier'})
    check('bilingual_edit_composes_name','Updated Supplier' in bi.name)
    private=B['res.partner'].create({'name':'SP1 foreign private','company_id':10,'supplier_rank':1})
    for C in (A,B):
        cid=C.company.id;p=C['res.partner'].browse(provider.id)
        mapping=C.ref(f'baseer_service_seed.mapping_iqama_issue_company_{cid}')
        p.baseer_purchase_category_map_id=mapping
        check('company_category_'+str(cid),p.baseer_purchase_category_map_id==mapping)
        check('company_payable_'+str(cid),C.company in p.property_account_payable_id.company_ids)
    check('category_values_independent',A['res.partner'].browse(provider.id).baseer_purchase_category_map_id.id!=B['res.partner'].browse(provider.id).baseer_purchase_category_map_id.id)
    bills=[]
    for C in (A,B):
        cid=C.company.id
        employee=C['hr.employee'].create({'name':'SP1 employee '+str(cid),'company_id':cid})
        service=C['baseer.hr.service'].create({'employee_id':employee.id,'service_type':'iqama_issue','gross_amount':115,'vat_enabled':True,'invoice_date':'2026-09-01','issue_date':'2026-09-01'})
        check('service_auto_shared_provider_'+str(cid),service.partner_id.id==provider.id)
        if cid==6:reject('foreign_private_supplier_rejected',lambda:service.write({'partner_id':private.id}))
        service.action_approve();bill=service.bill_id;bills.append((cid,bill.id))
        check('native_bill_company_'+str(cid),bill.company_id==C.company and bill.partner_id.id==provider.id and bill.state=='posted')
        check('native_bill_expense_mapping_'+str(cid),bill.invoice_line_ids.account_id==service.category_map_id._validated_expense_account())
        check('native_tax_total_'+str(cid),round(bill.amount_total,2)==115 and round(bill.amount_tax,2)==15)
        payable=bill.line_ids.filtered(lambda l:l.account_id.account_type=='liability_payable').account_id
        check('native_payable_company_'+str(cid),C.company in payable.company_ids)
        batch=C['baseer.purchase.batch'].create({'line_ids':[Command.create({'partner_id':provider.id,'invoice_date':'2026-09-01','supplier_ref':'SP1-SAME-REF','gross_amount':50,'is_credit':True})]})
        check('batch_shared_default_category_'+str(cid),batch.line_ids.category_map_id==C.ref(f'baseer_service_seed.mapping_iqama_issue_company_{cid}'))
        batch.action_approve()
        check('batch_posted_correct_company_'+str(cid),batch.line_ids.move_id.company_id==C.company and batch.line_ids.move_id.partner_id.id==provider.id)
        duplicate=C['baseer.purchase.batch'].create({'line_ids':[Command.create({'partner_id':provider.id,'invoice_date':'2026-09-01','supplier_ref':'SP1-SAME-REF','gross_amount':50,'is_credit':True})]})
        reject('batch_duplicate_reference_same_company_'+str(cid),duplicate.action_approve)
    user=A['res.users'].create({'name':'SP1 HR user','login':'sp1.qa.hr','company_id':6,'company_ids':[Command.set([6])],'group_ids':[Command.set([A.ref('hr.group_hr_user').id])]})
    H=A['baseer.hr.service'].with_user(user)
    check('hr_sees_shared_provider',A['res.partner'].with_user(user).browse(provider.id).name==provider.name)
    check('hr_hidden_other_company_services',not H.search([('bill_id','=',bills[1][1])]))
    reject('hr_cannot_read_supplier_accounting_invoice',lambda:A['account.move'].with_user(user).browse(bills[0][1]).read(['invoice_line_ids']))
    own=A['res.users'].with_user(user).browse(user.id)
    own.write({'lang':'en_US'});check('native_user_can_set_own_english',own.lang=='en_US')
    own.write({'lang':'ar_001'});check('native_user_can_set_own_arabic',own.lang=='ar_001')
    reject('ordinary_user_cannot_change_other_language',lambda:A['res.users'].with_user(user).browse(uid).write({'lang':'en_US'}))
    R['status']='passed'
except Exception:R['status']='failed';R['traceback']=traceback.format_exc()
finally:
    env.cr.rollback();env.invalidate_all();check('all_fixtures_rolled_back',before==fp())
    R['check_count']=len(R['checks'])
    Path('/mnt/qa-evidence/shared_partners_checks.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in R.items() if k!='checks'},ensure_ascii=False))

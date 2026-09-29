"""Destructive migration rejection and future-company seed checks, full rollback."""
import json, traceback
from pathlib import Path
from odoo import api, Command
from odoo.exceptions import ValidationError
from odoo.addons.baseer_service_seed.models.catalog import PROVIDERS

assert env.cr.dbname == 'baseer_reports_qa_20260907'
E=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[6],'lang':'en_US','tracking_disable':True})
R={'status':'started','checks':[]}
def check(n,v):
    R['checks'].append({'name':n,'passed':bool(v)})
    assert v,n
def fingerprint():
    E.flush_all();out={}
    for table in ('res_partner','ir_model_data','account_move','account_move_line','account_payment','res_company'):
        E.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM '+table+' t')
        out[table]=E.cr.fetchone()
    return out
baseline=fingerprint()
def reject(name,fn):
    before=fingerprint()
    try:fn()
    except ValidationError:check(name,True)
    else:check(name,False)
    check(name+'_atomic',before==fingerprint())
def source(key):
    spec=next(p for p in PROVIDERS if p[0]==key)
    p=E['res.partner'].with_context(mail_create_nolog=True,mail_create_nosubscribe=True).create({'name':spec[1],'vat':spec[4] or False,'company_id':6,'is_company':True,'supplier_rank':1})
    alias=E['ir.model.data'].search([('module','=','baseer_service_seed'),('name','=',f'provider_{key}_company_6')])
    alias.write({'res_id':p.id})
    return p
class RollbackCase(Exception):pass
try:
    for case in ('business_fk','attachment','private_chatter','external_identity','changed_identity','property_conflict'):
        try:
            with E.cr.savepoint():
                p=source('water')
                if case=='business_fk':
                    E['account.move'].create({'move_type':'in_invoice','company_id':6,'partner_id':p.id,'invoice_date':'2026-09-01'})
                elif case=='attachment':
                    E['ir.attachment'].create({'name':'SP1 private file','type':'binary','datas':'dGVzdA==','res_model':'res.partner','res_id':p.id})
                elif case=='private_chatter':
                    p.message_post(body='SP1 confidential context')
                elif case=='external_identity':
                    E['ir.model.data'].create({'module':'sp1_test','name':'private_external_identity','model':'res.partner','res_id':p.id})
                elif case=='changed_identity':p.name='Different legal identity'
                elif case=='property_conflict':
                    # Earlier family is transferred first; later conflict must
                    # undo that transfer as well, including its alias update.
                    first=source('passports')
                    first.with_company(E['res.company'].browse(6)).baseer_purchase_category_map_id=E.ref('baseer_service_seed.mapping_iqama_issue_company_6')
                    p.with_company(E['res.company'].browse(6)).baseer_purchase_category_map_id=E.ref('baseer_service_seed.mapping_iqama_issue_company_6')
                reject(case,lambda:E['res.company']._baseer_consolidate_service_providers())
                check(case+'_source_still_exists',bool(p.exists()))
                raise RollbackCase()
        except RollbackCase:pass
        E.invalidate_all()
    before_ids={E.ref('baseer_service_seed.provider_'+p[0]).id for p in PROVIDERS}
    company=E['res.company'].create({'name':'SP1 future company','country_id':E.ref('base.sa').id,'currency_id':E.ref('base.SAR').id})
    E.cr.precommit.run();E.flush_all();company=company.with_company(company)
    after_ids={E.ref(f'baseer_service_seed.provider_{p[0]}_company_{company.id}').id for p in PROVIDERS}
    check('future_company_reuses_all20',after_ids==before_ids and len(after_ids)==20)
    water=company.env.ref('baseer_service_seed.provider_water')
    check('future_company_gets_own_category',water.baseer_purchase_category_map_id.company_id==company)
    check('future_company_gets_own_payable',company in water.property_account_payable_id.company_ids)
    company._baseer_initialize_services()
    check('future_company_idempotent',after_ids=={E.ref(f'baseer_service_seed.provider_{p[0]}_company_{company.id}').id for p in PROVIDERS})
    R['status']='passed'
except Exception:R['status']='failed';R['traceback']=traceback.format_exc()
finally:
    E.cr.rollback();E.invalidate_all();check('all_fixtures_rolled_back',baseline==fingerprint())
    R['check_count']=len(R['checks'])
    Path('/mnt/qa-evidence/shared_partners_guards.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False))

"""Native imported PO field/view values and native export round trip, clone only."""
import io,json
from pathlib import Path
from lxml import etree
from odoo.tools.translate import trans_export,PoFileReader
assert env.cr.dbname=='baseer_fix_payroll_20260909'
E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'lang':'ar_001'},su=False)
expected={'slip_id':'كشف الراتب','kind':'نوع التصحيح','date':'التاريخ','reason':'السبب'}
descriptions=E['baseer.payroll.correction'].fields_get(list(expected),['string'])
checks=[]
for key,value in expected.items():
    actual=descriptions[key]['string'];checks.append({'name':'dialog_'+key,'expected':value,'actual':actual,'pass':actual==value})
view=E['baseer.payroll.correction'].get_view(E.ref('baseer_payroll.view_baseer_payroll_correction').id,'form')
actual=etree.fromstring(view['arch']).xpath("//button[@special='cancel']")[0].get('string')
checks.append({'name':'dialog_cancel','expected':'إلغاء','actual':actual,'pass':actual=='إلغاء'})
for model,key,value in [('baseer.hr.eos','reason','سبب انتهاء الخدمة'),('baseer.hr.loan.allocation','kind','نوع السداد')]:
    actual=E[model].fields_get([key],['string'])[key]['string']
    checks.append({'name':'existing_context_preserved_'+model,'expected':value,'actual':actual,'pass':actual==value})
source=Path('/tmp/fa2-source-payroll/custom_addons/baseer_payroll/i18n/ar.po')
with source.open('rb') as stream:
    translations=list(PoFileReader(stream))
for key,value in expected.items():
    target='field_baseer_payroll_correction__'+key
    entries=[r for r in translations if r.get('imd_name')==target]
    checks.append({'name':'scoped_native_PO_'+key,'pass':any(r['value']==value for r in entries)})
out=io.BytesIO();trans_export('ar_001',['baseer_payroll'],out,'po',E)
Path('/mnt/qa-evidence/payroll-final-native-export-ar.po').write_bytes(out.getvalue())
assert all(c['pass'] for c in checks),checks
env.cr.rollback()
Path('/mnt/qa-evidence/payroll-dialog-translation-result.json').write_text(json.dumps({'status':'completed','checks':checks,'rolled_back':True},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False))

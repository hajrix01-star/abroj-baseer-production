"""Final presentation-only follow-up: native compiled EOS form and policy modifiers."""
import json
from pathlib import Path
from lxml import etree
from odoo.tools.safe_eval import safe_eval
from odoo.addons.baseer_payroll.models.end_service import POLICY,LEGACY_POLICY
assert env.cr.dbname=='baseer_fix_payroll_20260909'
E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'lang':'en_US'},su=False)
checks=[]
for policy in [LEGACY_POLICY,POLICY]:
    view=E['baseer.hr.eos'].with_context(default_policy_version=policy).get_view(E.ref('baseer_payroll.view_baseer_eos_form').id,'form')
    arch=etree.fromstring(view['arch'])
    field=arch.xpath("//field[@name='service_end_inclusive']")[0]
    button=arch.xpath("//button[@name='action_use_gregorian_policy']")[0]
    hidden=bool(safe_eval(field.get('invisible'),{'policy_version':policy,'state':'draft'}))
    button_hidden=bool(safe_eval(button.get('invisible'),{'policy_version':policy,'state':'draft'}))
    checks.append({'policy':policy,'native_form_compiled':True,'inclusive_hidden':hidden,'upgrade_button_hidden':button_hidden,
                   'pass':hidden==(policy!=POLICY) and button_hidden==(policy==POLICY)})
assert all(row['pass'] for row in checks)
env.cr.rollback()
Path('/mnt/qa-evidence/payroll-view-policy-result.json').write_text(json.dumps({'status':'completed','checks':checks,'rolled_back':True},indent=2),encoding='utf-8')
print(json.dumps(checks))

"""Read-only installed-view and empty-audit smoke; never create a MAIN fixture."""
import json
from unittest.mock import patch
from odoo.fields import Domain
assert env.cr.dbname == 'baseer_dev' and env.su
with patch.object(type(env.cr),'commit',side_effect=AssertionError('MAIN smoke is read-only')):
    module = env['ir.module.module'].search([('name','=','baseer_financial_correction')])
    assert module.state=='installed' and module.latest_version=='19.0.1.0.0'
    assert not env['baseer.financial.correction.audit'].search_count([])
    views = {}
    for lang in ('ar_001','en_US'):
        result = env['baseer.financial.correction'].with_context(lang=lang).get_view(
            view_id=env.ref('baseer_financial_correction.view_correction_form').id,view_type='form')
        assert 'action_confirm' in result['arch'] and 'payment_amount_input' in result['arch']
        assert ('تأكيد التصحيح' if lang=='ar_001' else 'Confirm correction') in result['arch']
        views[lang]=True
    for name in ('view_move_correction_entry','view_payment_correction_entry','view_batch_correction_entry',
                 'view_register_correction_entry','view_register_kanban_correction_entry'):
        view = env.ref('baseer_financial_correction.'+name)
        assert view.active and 'action_baseer_correct_operation' in view.arch_db
    domains = env.user._baseer_correction_source_domain(env.user.company_ids.ids)
    assert isinstance(domains,Domain)
    setting = env.ref('baseer_financial_correction.view_users_correction_permission')
    assert setting.active and 'baseer_allow_financial_correction' in setting.arch_db
    assert not env['res.users'].with_context(active_test=False).search_count([
        ('baseer_allow_financial_correction','=',False)])
    print(json.dumps({'status':'PASS','database':env.cr.dbname,'module':module.latest_version,
        'languages':views,'source_entries':5,'audit_empty':True,'main_business_mutations':False,
        'permission_setting_active':True,'default_enabled_preserved':True}))
    env.cr.rollback()

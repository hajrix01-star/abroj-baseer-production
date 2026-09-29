"""Read-only verification of the installed original; no financial fixture."""
import json
from unittest.mock import patch
assert env.cr.dbname == 'baseer_dev' and env.su
with patch.object(type(env.cr), 'commit', side_effect=AssertionError('MAIN smoke is read-only')):
    versions = {}
    for name, version in [('baseer_financial_correction', '19.0.1.1.0'), ('baseer_pos_summary', '19.0.1.5.1')]:
        module = env['ir.module.module'].search([('name', '=', name)])
        assert module.state == 'installed' and module.latest_version == version
        versions[name] = version
    for lang in ('ar_001', 'en_US'):
        invoice_view = env['baseer.financial.correction'].with_context(lang=lang).get_view(
            view_id=env.ref('baseer_financial_correction.view_correction_form').id, view_type='form')['arch']
        assert 'payment_cancel_ack' in invoice_view and 'action_confirm' in invoice_view
        assert ('تأكيد إلغاء العملية' if lang == 'ar_001' else 'Confirm operation cancellation') in invoice_view
        summary_view = env['baseer.pos.summary.correction'].with_context(lang=lang).get_view(
            view_id=env.ref('baseer_pos_summary.view_summary_correction_form').id, view_type='form')['arch']
        assert 'acknowledge_bookkeeping' in summary_view and '<kanban' in summary_view and 'amount_input' in summary_view
        assert ('المبلغ الصحيح' if lang == 'ar_001' else 'Correct amount') in summary_view
    assert env.ref('baseer_financial_correction.view_users_correction_permission').active
    assert not env['baseer.purchase.batch.line'].search_count([('baseer_cancelled', '=', True)])
    print(json.dumps({'status': 'PASS', 'database': env.cr.dbname, 'modules': versions,
                      'languages': ['ar_001', 'en_US'], 'native_mobile_view': True,
                      'shared_permission_setting': True, 'no_automatic_cancellations': True,
                      'main_business_mutations': False}))
    env.cr.rollback()

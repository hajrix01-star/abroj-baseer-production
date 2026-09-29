"""Run inside MAIN Odoo shell: read-only cash adapter/source parity smoke."""
import json
from decimal import Decimal
from odoo import fields

assert env.cr.dbname == 'baseer_dev'
env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
admin = env.ref('base.user_admin')
results = []
month = fields.Date.today().strftime('%Y-%m')
for company in admin.company_ids.filtered(lambda c: c.currency_id.name == 'SAR'):
    moves = env['account.move'].with_user(admin).with_context(
        allowed_company_ids=[company.id], baseer_register_cash_month=month)
    action = moves.action_open_register_cash(month)
    _, _, report, rows = moves._register_cash_snapshot(month)
    kpis = moves.baseer_financial_register_cash_kpis(action['domain'])
    visible = moves.search(action['domain'])
    assert set(visible.ids) == set(rows)
    assert sum((r['net'] for r in rows.values()), Decimal(0)) == Decimal(report['meta']['exact_totals']['actual_net_movement'])
    visible[:5].read(['baseer_register_cash_receipts', 'baseer_register_cash_payments', 'baseer_register_cash_net'])
    assert len(kpis['currency_groups'][0]['sections'][0]['cards']) == 3
    assert 'baseer_register_cash_month' not in moves.action_open_financial_register()['context']
    for language in ('en_US', 'ar_001'):
        arch = moves.with_context(lang=language).get_view(
            view_id=env.ref('baseer_financial_register.view_cash_register_kanban').id,
            view_type='kanban')['arch']
        assert ('المقبوضات الفعلية' if language == 'ar_001' else 'Actual receipts') in arch
    results.append({'company_id': company.id, 'visible_rows': len(visible),
                    'cash_report_parity': True, 'native_views_ar_en': True,
                    'all_mode_restored': True})
assert results
env.cr.rollback()
print('FL2_MAIN_SMOKE=' + json.dumps({'status': 'PASS', 'read_only': True,
      'month': month, 'companies': results}))

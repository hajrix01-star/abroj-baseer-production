"""Read-only acceptance, supplied to native `odoo shell` on the new QA only."""
import hashlib
import json
import time

from odoo.exceptions import AccessError


env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
try:
    assert env.cr.dbname == 'baseer_qa_20261023', 'wrong acceptance database'
    user = env['res.users'].browse(2).exists()
    assert user and user.active, 'owner unavailable'
    required = {1, 2, 3, 56}
    assert required.issubset(set(user.company_ids.ids)), 'owner company memberships missing'
    versions = {}
    for module in env['ir.module.module'].search([
        ('name', 'in', ['baseer_pos_print_bridge', 'baseer_operations_report']),
    ]):
        versions[module.name] = module.installed_version
    assert versions == {
        'baseer_pos_print_bridge': '19.0.7.8.26',
        'baseer_operations_report': '19.0.1.0.12',
    }, 'module version mismatch'
    assert env['ir.config_parameter'].sudo().get_param('database.is_neutralized') == 'true'
    assert not env['ir.cron'].sudo().search_count([('active', '=', True)])
    assert not env['ir.mail_server'].sudo().search_count([('active', '=', True)])
    assert not env['baseer.print.agent'].sudo().search_count([('active', '=', True)])
    assert not env['pos.config'].sudo().search_count([('baseer_direct_print_enabled', '=', True)])
    edi = env['ir.module.module'].sudo().search([
        ('name', 'in', ['account_edi', 'l10n_sa_edi', 'l10n_sa_edi_pos']),
    ])
    assert all(module.state == 'uninstalled' for module in edi), 'EDI unexpectedly active'
    results = []
    for company_id in sorted(required):
        signatures = []
        for lang in ['ar_001', 'en_US']:
            report = env['baseer.operations.report'].with_user(user).with_context(
                allowed_company_ids=user.company_ids.ids, lang=lang, tz='Asia/Riyadh',
            )
            filters = {
                'company_id': company_id, 'date_from': '2026-10-01',
                'date_to': '2026-10-31', 'journal_ids': [],
            }
            started = time.monotonic()
            data = report.get_owner_snapshot(filters)
            assert data['complete'] and data['coverage_complete'], 'incomplete report'
            assert data['company_id'] == company_id, 'company scope mismatch'
            assert data['source_basis'] == 'recorded_sales_headers_and_posted_cash'
            amounts = [[(row['key'], row['amount']) for row in period['totals']]
                       for period in data['periods']]
            signatures.append(hashlib.sha256(json.dumps(amounts, sort_keys=True).encode()).hexdigest())
            action = report.action_print_owner(filters)
            assert action['type'] == 'ir.actions.report', 'print action unavailable'
            results.append({'company': company_id, 'lang': lang, 'complete': True,
                            'seconds': round(time.monotonic() - started, 3)})
        assert signatures[0] == signatures[1], 'language changed report amounts'
    outsider = env['res.users'].sudo().search([
        ('active', '=', True), ('share', '=', False), ('company_ids', 'not in', [56]),
    ], limit=1)
    company_guard = 'no_restricted_user_fixture'
    if outsider:
        try:
            env['baseer.operations.report'].with_user(outsider).with_context(
                allowed_company_ids=outsider.company_ids.ids,
            ).get_owner_snapshot({'company_id': 56, 'date_from': '2026-10-01',
                                  'date_to': '2026-10-31', 'journal_ids': []})
        except AccessError:
            company_guard = 'PASS'
        else:
            raise AssertionError('unauthorized company was accepted')
    print('QA_REFRESH_ODOO=' + json.dumps({
        'versions': versions, 'reports': results, 'company_guard': company_guard,
        'external_submissions': 0, 'writes': 0,
    }, sort_keys=True))
finally:
    env.cr.rollback()

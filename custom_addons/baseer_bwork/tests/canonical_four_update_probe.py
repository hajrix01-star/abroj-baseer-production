"""Native exact-four update/paired-restore fixture, synthetic DBs only.

Loaded by fixed absolute path by the isolated driver, never addon init. Caller
owns environments, source archives, backups, commits and paired restore. No
provider credentials, network operation, production source or deploy entry.
"""
import ast
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from uuid import uuid4


KEY = 'baseer_bwork.canonical_four_fixture.v1'
FOUR = {'baseer_bwork', 'baseer_bwork_procurement', 'baseer_bwork_admin', 'baseer_bwork_dashboard'}
TWO = {'baseer_access_roles', 'baseer_procurement_requests'}
FLAGS = ('bwork_chat_view', 'bwork_chat_send', 'bwork_media', 'bwork_group_create',
         'bwork_group_manage', 'bwork_task_view', 'bwork_task_manage',
         'bwork_order_view', 'bwork_order_create', 'bwork_order_receive',
         'bwork_dashboard_view', 'bwork_manage_rooms')


def _guard(env):
    assert os.environ.get('BWORK_CANONICAL_FOUR_SYNTHETIC') == '1', 'Explicit synthetic fixture marker required.'
    assert re.fullmatch(r'bwork_canonical_four_ci_[a-z0-9_]+', env.cr.dbname) and len(env.cr.dbname) <= 63, \
        'Disposable exact-four database required.'
    assert env.su, 'Isolated fixture administrator required.'
    env.cr.execute("SET LOCAL lock_timeout='2s'")
    env.cr.execute("SET LOCAL statement_timeout='30s'")


def _addons(profile):
    expected = '/mnt/' + profile + '-addons'
    configured = os.environ.get('BWORK_CANONICAL_FOUR_' + profile.upper() + '_ADDONS', expected)
    assert configured == expected, 'Only fixed isolated source mounts are accepted.'
    root = Path(expected)
    assert root.is_dir() and not root.is_symlink()
    return root


def _prototype(profile):
    path = _addons(profile) / 'baseer_bwork/tools/canonical_pre_upgrade.py'
    spec = importlib.util.spec_from_file_location('bwork_four_fixture_' + profile, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _rows(env, sql, params=None):
    env.cr.execute(sql, params)
    return [list(row) for row in env.cr.fetchall()]


def _snapshot(env, attachment_id):
    env.flush_all()
    users = _rows(env, 'SELECT id,active,share,company_id,baseer_access_role,' + ','.join(FLAGS) +
                  ',bwork_permission_revision FROM res_users ORDER BY id')
    result = {'users': _hash(users),
              'userGroups': _hash(_rows(env, 'SELECT uid,gid FROM res_groups_users_rel ORDER BY uid,gid')),
              'companyMemberships': _hash(_rows(env, 'SELECT user_id,cid FROM res_company_users_rel ORDER BY user_id,cid')),
              'groupGraph': _hash(_rows(env, 'SELECT gid,hid FROM res_groups_implied_rel ORDER BY gid,hid')),
              'companies': _hash(_rows(env, 'SELECT id,name,currency_id FROM res_company ORDER BY id')),
              'tables': {}}
    # Exact business row fingerprints. No normalization of values, dates,
    # company IDs, counters, UUIDs, document amounts or posting states.
    for table in ('baseer_bwork_room', 'baseer_bwork_membership', 'baseer_bwork_message',
                  'baseer_bwork_task', 'baseer_procurement_request', 'baseer_procurement_request_line',
                  'account_move', 'account_move_line', 'account_payment', 'purchase_order',
                  'purchase_order_line', 'stock_picking', 'stock_move'):
        rows = _rows(env, 'SELECT id,md5(to_jsonb(t)::text) FROM ' + table + ' t ORDER BY id')
        assert len(rows) <= 10000, 'Synthetic fixture row bound exceeded.'
        result['tables'][table] = {'count': len(rows), 'sha256': _hash(rows)}
    result['sequenceRows'] = _hash(_rows(env, "SELECT id,code,number_next,number_increment,prefix,padding "
        "FROM ir_sequence WHERE code IN ('baseer.procurement.request','baseer.procurement.custody',"
        "'baseer.procurement.representative.petty.cash') ORDER BY id"))
    result['ledger'] = _rows(env, "SELECT value FROM ir_config_parameter WHERE key='baseer_bwork.canonical_rename.v1'")
    assert len(result['ledger']) == 1
    ledger = json.loads(result['ledger'][0][0])
    assert ledger['status'] == 'complete'
    result['identities'] = _rows(env, 'SELECT name,id FROM ir_module_module WHERE name IN %s ORDER BY name',
                                [tuple(sorted(FOUR | TWO))])
    result['tableOids'] = [[name, _rows(env, 'SELECT to_regclass(%s)::oid', [name])[0][0]]
                          for name in sorted(ledger['tables'])]
    attachment = env['ir.attachment'].browse(attachment_id).exists()
    assert attachment and attachment.store_fname
    path = Path(attachment._full_path(attachment.store_fname))
    assert path.is_file() and path.stat().st_size > 0
    result['attachment'] = {'id': attachment.id, 'checksum': attachment.checksum,
                            'store_fname': attachment.store_fname,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def _versions(env):
    rows = _rows(env, 'SELECT name,state,latest_version FROM ir_module_module WHERE name IN %s ORDER BY name',
                 [tuple(sorted(FOUR | TWO))])
    assert len(rows) == 6 and all(row[1] == 'installed' for row in rows)
    return {name: version for name, _state, version in rows}


def _fixture(env):
    rows = _rows(env, 'SELECT value FROM ir_config_parameter WHERE key=%s', [KEY])
    assert len(rows) == 1, 'Exactly one prepared synthetic fixture required.'
    return json.loads(rows[0][0])


def _assert_candidate(plan):
    assert plan['classification'] == 'canonical-ready' and plan['update_mode'] == 'canonical-four-v1'
    assert set(plan['required_closure']) == FOUR | TWO and set(plan['upgrade']) == FOUR
    assert set(plan['preserved_modules']) == TWO and not plan['install']
    assert plan['native_pre_upgrade_required'] is False
    assert {row['module'] for row in plan['preserved_sources']} == TWO


def prepare(env):
    _guard(env)
    from odoo import Command
    assert not _rows(env, 'SELECT 1 FROM ir_config_parameter WHERE key=%s', [KEY])
    versions = _versions(env)
    admin = env.ref('base.user_admin')
    company = admin.company_id
    admin.write({'baseer_access_role': 'owner', **{name: True for name in FLAGS},
                 'group_ids': [Command.link(env.ref('baseer_bwork.group_bwork_manager').id)]})
    owner_role = env.ref('baseer_access_roles.group_owner')
    google_groups = []
    for module, name in (('baseer_google_ads', 'group_gads_manager'),
                         ('baseer_google_business', 'group_gbp_manager')):
        assert not env.ref(module + '.' + name, raise_if_not_found=False)
        group = env['res.groups'].create({'name': 'Synthetic fixed Google role ' + name})
        env['ir.model.data'].create({'module': module, 'name': name, 'model': 'res.groups',
                                     'res_id': group.id, 'noupdate': True})
        google_groups.append(group.id)
    owner_role.write({'implied_ids': [Command.link(value) for value in google_groups]})
    env.flush_all()
    graph = _hash(_rows(env, 'SELECT gid,hid FROM res_groups_implied_rel ORDER BY gid,hid'))
    class RollbackSeedRisk(Exception):
        pass
    # RED: the real unchanged native seed removes these later Google grants.
    # Roll back this deliberate synthetic demonstration before the update.
    try:
        with env.cr.savepoint():
            env['baseer.access.role.seed']._setup_roles()
            assert not set(google_groups) & set(owner_role.implied_ids.ids)
            raise RollbackSeedRisk()
    except RollbackSeedRisk:
        pass
    env.invalidate_all()
    assert _hash(_rows(env, 'SELECT gid,hid FROM res_groups_implied_rel ORDER BY gid,hid')) == graph
    member = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'Synthetic exact-four member', 'login': 'bwork-four-' + uuid4().hex,
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set(env.ref('base.group_user').ids)],
        'bwork_chat_view': True, 'bwork_chat_send': True, 'bwork_task_view': True})
    rooms = []
    for index in range(3):
        room = env['baseer.bwork.room'].with_user(admin).with_company(company).create({
            'name': 'Synthetic exact-four room %s' % index, 'company_id': company.id})
        for user in (admin, member):
            env['baseer.bwork.membership'].with_user(admin).with_company(company).create({
                'room_id': room.id, 'user_id': user.id})
        rooms.append(room.id)
    partner = env['res.partner'].create({'name': 'Synthetic exact-four supplier', 'company_id': company.id})
    warehouse = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
    assert warehouse, 'Fresh existing procurement dependency warehouse required.'
    product = env['product.product'].with_company(company).create({
        'name': 'Synthetic exact-four material', 'company_id': company.id,
        'purchase_ok': True, 'is_storable': True})
    option = env['baseer.procurement.purchase.option'].with_company(company).create({
        'name': 'Synthetic exact-four unit', 'company_id': company.id,
        'product_id': product.id, 'uom_id': product.uom_id.id})
    order = env['baseer.bwork.service'].with_user(admin).with_company(company)._v2_order_create({
        'api_version': 2, 'company_id': company.id, 'warehouse_id': warehouse.id,
        'representative_partner_id': None, 'client_uuid': str(uuid4()), 'purchase_route': 'cash',
        'room_id': rooms[0], 'lines': [{'option_id': option.id, 'quantity': '2.00'}]})
    purchase = env['purchase.order'].with_company(company).create({
        'partner_id': partner.id, 'company_id': company.id,
        'order_line': [Command.create({'product_id': product.id, 'product_qty': 2, 'price_unit': 17})]})
    account_values = {'name': 'Synthetic exact-four expense', 'code': '9900771', 'account_type': 'expense'}
    account_values['company_ids' if 'company_ids' in env['account.account']._fields else 'company_id'] = (
        [Command.set(company.ids)] if 'company_ids' in env['account.account']._fields else company.id)
    expense = env['account.account'].create(account_values)
    journal = env['account.journal'].with_company(company).create({
        'name': 'Synthetic exact-four bills', 'code': 'BCDF', 'type': 'purchase', 'company_id': company.id})
    bill = env['account.move'].with_company(company).create({
        'move_type': 'in_invoice', 'partner_id': partner.id, 'journal_id': journal.id,
        'company_id': company.id, 'invoice_date': '2026-10-20',
        'invoice_line_ids': [Command.create({'name': 'Synthetic preserved bill', 'account_id': expense.id,
                                           'quantity': 2, 'price_unit': 37, 'tax_ids': [Command.clear()]})]})
    assert bill.state == 'draft' and bill.amount_total == 74 and purchase.amount_total > 0
    attachment = env['ir.attachment'].create({
        'name': 'synthetic-exact-four.txt', 'type': 'binary', 'mimetype': 'text/plain',
        'datas': base64.b64encode(b'Synthetic exact-four paired-filestore preservation proof.\n'),
        'res_model': 'res.partner', 'res_id': partner.id})
    env.flush_all()
    baseline_plan = _prototype('baseline').classify(env.cr, sorted(FOUR))
    assert set(baseline_plan['upgrade']) == FOUR | TWO and not baseline_plan['install']
    candidate_plan = _prototype('candidate').classify(env.cr, sorted(FOUR))
    _assert_candidate(candidate_plan)
    facts = {'versions': versions, 'google_groups': google_groups, 'attachment_id': attachment.id,
             'rooms': rooms, 'procurement_order': order['order']['id'], 'bill': bill.id,
             'snapshot': _snapshot(env, attachment.id), 'candidate_plan': candidate_plan}
    env['ir.config_parameter'].set_param(KEY, json.dumps(facts, sort_keys=True))
    print('BWORK_CANONICAL_FOUR_PREPARED=PASS')
    return {'baseline_full_six_plan': baseline_plan, 'candidate_plan': candidate_plan,
            'real_role_seed_loss_rolled_back': True, 'snapshot_sha256': _hash(facts['snapshot']),
            'filestore_nonempty': True, 'fixture_only': True}


def verify(env):
    _guard(env)
    facts = _fixture(env)
    plan = _prototype('candidate').classify(env.cr, sorted(FOUR))
    _assert_candidate(plan)
    assert plan == facts['candidate_plan'], 'Source proof/closure drifted between preparation and upgrade.'
    assert _snapshot(env, facts['attachment_id']) == facts['snapshot'], \
        'User/Google group/company/membership/room/document/sequence/filestore/ledger identity changed.'
    actual_versions = _versions(env)
    for name in TWO:
        assert actual_versions[name] == facts['versions'][name]
    for name in FOUR:
        expected = ast.literal_eval((_addons('candidate') / name / '__manifest__.py').read_text())['version']
        assert actual_versions[name] == expected
    print('BWORK_CANONICAL_FOUR_VERIFIED=PASS')
    return {'exact_four_upgrade': True, 'preserved_two_sources_and_versions': True,
            'google_edges_users_documents_filestore_and_identity': 'PASS', 'plan': plan,
            'snapshot_sha256': _hash(facts['snapshot'])}


def verify_restored(env):
    _guard(env)
    facts = _fixture(env)
    assert _versions(env) == facts['versions']
    assert _snapshot(env, facts['attachment_id']) == facts['snapshot']
    baseline_plan = _prototype('baseline').classify(env.cr, sorted(FOUR))
    assert set(baseline_plan['upgrade']) == FOUR | TWO
    print('BWORK_CANONICAL_FOUR_RESTORED=PASS')
    return {'paired_database_filestore_restore': 'PASS', 'baseline_versions_and_documents': 'PASS',
            'snapshot_sha256': _hash(facts['snapshot'])}

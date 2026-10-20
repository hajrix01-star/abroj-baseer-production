"""Synthetic disposable-DB probe for a REAL old-install -> native upgrade.

This file is loaded by absolute path so prepare_legacy runs against the pinned
old source, not an alias addon. It is NOT imported by production addon init.
Database name + explicit fixture marker fence every test mutation. No owner DB.
The CI leader supplies old/new addons mounts and the native CLI; this probe does
not connect, commit, deploy or start any environment itself.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_KEY = 'baseer_bwork.canonical_fixture.v1'


def _prototype():
    spec = importlib.util.spec_from_file_location('bwork_canonical_isolated_probe', ROOT / 'tools/canonical_pre_upgrade.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _guard(env):
    if not env.cr.dbname.startswith('bwork_canonical_ci_'):
        raise AssertionError('Disposable canonical CI database required.')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def _snapshot(env, old):
    prototype = _prototype()
    mapping, _ = prototype.load_mapping()
    prefix = 'baseer_bchat_' if old else 'baseer_bwork_'
    models = [row['old' if old else 'new'] for row in mapping['models']]
    env.flush_all()
    result = {'tables': {}, 'model_ids': {}, 'fields': {}, 'xmlids': {}, 'attachments': [],
              'groups': None, 'constraints': [], 'constraint_shapes': []}
    for row in mapping['models']:
        table = row['old_table' if old else 'new_table']
        if table:
            env.cr.execute('SELECT to_regclass(%s)::oid', [table])
            oid = env.cr.fetchone()[0]
            if oid is not None:
                result['tables'][row['new_table']] = [oid, *prototype._row_identity(env.cr, table)]
    env.cr.execute('SELECT id,model FROM ir_model WHERE model IN %s', [tuple(models)])
    model_map = {row['old']: row['new'] for row in mapping['models']}
    result['model_ids'] = {model_map.get(name, name): record_id for record_id, name in env.cr.fetchall()}
    field_pairs = {(row['model'], row['old']): row['new'] for row in mapping['fields']}
    env.cr.execute('SELECT id,model,name FROM ir_model_fields WHERE model IN %s OR name IN %s',
                   [tuple(models), tuple(row['old' if old else 'new'] for row in mapping['fields'])])
    result['fields'] = {model_map.get(owner, owner) + ':' + field_pairs.get((owner, name), name): record_id
                        for record_id, owner, name in env.cr.fetchall()}
    for row in mapping['xmlids']:
        module, name = row['old' if old else 'new'].split('.', 1)
        env.cr.execute('SELECT model,res_id FROM ir_model_data WHERE module=%s AND name=%s', [module, name])
        value = env.cr.fetchone()
        if value:
            result['xmlids'][row['new']] = [model_map.get(value[0], value[0]), value[1]]
    env.cr.execute(f'''SELECT a.id,a.res_id,a.checksum,a.store_fname,a.file_size,m.sha256,m.size_bytes
                        FROM ir_attachment a JOIN {prefix}media m
                          ON a.id IN (m.attachment_id,m.thumbnail_attachment_id) ORDER BY a.id''')
    result['attachments'] = [list(row) for row in env.cr.fetchall()]
    relation = env['res.users']._fields['group_ids']
    env.cr.execute(f'SELECT "{relation.column1}","{relation.column2}" FROM "{relation.relation}" ORDER BY 1,2')
    result['groups'] = _hash(env.cr.fetchall())
    table_oids = tuple(value[0] for value in result['tables'].values())
    env.cr.execute('SELECT oid FROM pg_constraint WHERE conrelid IN %s ORDER BY oid', [table_oids])
    result['constraints'] = [row[0] for row in env.cr.fetchall()]
    env.cr.execute('''SELECT t.relname,c.conname,pg_get_constraintdef(c.oid,TRUE)
                       FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
                      WHERE c.conrelid IN %s ORDER BY t.relname,c.conname''', [table_oids])
    shape_rows = env.cr.fetchall()
    assert shape_rows and len(shape_rows) == len(result['constraints'])
    objects = prototype._object_names(env.cr, mapping)
    names = {**objects, **{row['old']: row['new'] for row in mapping['fields']}}
    result['constraint_shapes'] = sorted([objects.get(table, table), objects.get(name, name),
                                          prototype._expression(definition, names)]
                                         for table, name, definition in shape_rows)
    return result


def prepare_legacy(env):
    """Create synthetic data using the REAL old private service, not new source."""
    _guard(env)
    from odoo import Command
    assert 'baseer.bchat.service' in env and 'baseer.bwork.service' not in env
    assert not env['ir.config_parameter'].sudo().search_count([('key', '=', FIXTURE_KEY)])
    admin = env.ref('base.user_admin')
    company = env['res.company'].create({'name': 'BCR SYNTHETIC ONLY'})
    admin.write({'company_ids': [Command.link(company.id)], 'group_ids': [
        Command.link(env.ref('baseer_bchat.group_bchat_manager').id)]})
    stranger = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'BCR synthetic nonmember', 'login': 'bcr-nonmember-' + uuid4().hex,
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set(env.ref('base.group_user').ids)]})
    room = env['baseer.bchat.room'].with_user(admin).with_company(company).create({
        'name': 'BCR synthetic room', 'company_id': company.id})
    member = env['baseer.bchat.membership'].with_user(admin).with_company(company).create({
        'room_id': room.id, 'user_id': admin.id})
    service = env['baseer.bchat.service'].with_user(admin).with_company(company)
    text_payload = {'api_version': 2, 'membership_id': member.id, 'client_uuid': str(uuid4()),
                    'text': 'BCR fixture must preserve literal baseer.bchat.message in BODY'}
    text_ack = service._v2_send(room.id, text_payload)
    raw = b'%PDF-1.4\nBCR-SYNTHETIC-BYTES\n%%EOF\n'
    media_metadata = {'api_version': 2, 'membership_id': member.id, 'upload_uuid': str(uuid4()),
                      'kind': 'file', 'mime': 'application/pdf', 'size': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest(), 'name': 'BCR synthetic.pdf'}
    staged = service._v2_upload(room.id, media_metadata, raw)
    media_payload = {'api_version': 2, 'membership_id': member.id, 'client_uuid': str(uuid4()),
                     'text': '', 'media_id': staged['media_id'], 'reply_to_message_id': text_ack['message_id']}
    media_ack = service._v2_send(room.id, media_payload)
    # A separate unsent upload and issued capability must survive unchanged.
    stage_metadata = {**media_metadata, 'upload_uuid': str(uuid4()), 'name': 'BCR staged.pdf'}
    stage = service._v2_upload(room.id, stage_metadata, raw)
    grant_metadata = {**media_metadata, 'upload_uuid': str(uuid4()), 'name': 'BCR capability.pdf'}
    grant = service._v2_issue_mobile_upload_grant(room.id, grant_metadata)
    env['mail.message'].create({'model': 'baseer.bchat.message', 'res_id': text_ack['message_id'],
                                'body': 'BCR literal baseer.bchat.message remains historical content'})
    env.flush_all()
    facts = {'room_id': room.id, 'company_id': company.id, 'member_id': member.id,
             'admin_id': admin.id, 'stranger_id': stranger.id, 'text_payload': text_payload,
             'text_ack': text_ack, 'media_payload': media_payload, 'media_ack': media_ack,
             'media_id': staged['media_id'], 'stage_id': stage['media_id'], 'grant_id': grant['grant_id'],
             'bytes_sha256': hashlib.sha256(raw).hexdigest(), 'snapshot': _snapshot(env, True)}
    # Synthetic non-secret fixture metadata only. Never store the grant secret.
    env['ir.config_parameter'].sudo().create({'key': FIXTURE_KEY, 'value': json.dumps(facts, default=str)})
    return {'fixture': 'BCR_SYNTHETIC_ONLY', 'prepared': True, 'snapshot_sha256': _hash(facts['snapshot'])}


def exercise_legacy_rollback(env):
    """Real SQL rollback after DDL/metadata mutation; old registry remains loaded."""
    _guard(env)
    prototype = _prototype()
    before = _snapshot(env, True)
    class InjectedFailure(Exception):
        pass
    try:
        with env.cr.savepoint():
            with patch.object(prototype, '_metadata_expressions', side_effect=InjectedFailure):
                prototype.migrate(env.cr, None)
    except InjectedFailure:
        pass
    else:
        raise AssertionError('Failure seam was not reached.')
    env.invalidate_all()
    assert _snapshot(env, True) == before
    return {'rollback_after_ddl': 'PASS', 'old_source_identity_unchanged': True}


def verify_upgraded(env):
    _guard(env)
    from odoo.exceptions import AccessError
    prototype = _prototype()
    value = env['ir.config_parameter'].sudo().search([('key', '=', FIXTURE_KEY)]).value
    assert value, 'Synthetic old-install fixture is required.'
    facts = json.loads(value)
    assert _snapshot(env, False) == facts['snapshot'], 'Lineage changed during real registry upgrade.'
    assert prototype.verify_transition(env.cr)['transition_lineage'] == 'PASS'
    service = env['baseer.bwork.service'].with_user(facts['admin_id']).with_company(facts['company_id'])
    assert service._v2_send(facts['room_id'], facts['text_payload']) == facts['text_ack']
    assert service._v2_send(facts['room_id'], facts['media_payload']) == facts['media_ack']
    raw, _, _ = service._v2_media_content(facts['media_id'])
    assert hashlib.sha256(raw).hexdigest() == facts['bytes_sha256']
    media = env['baseer.bwork.media'].sudo().browse(facts['media_id'])
    assert media.message_id.id == facts['media_ack']['message_id']
    assert media.message_id.reply_to_message_id.id == facts['text_ack']['message_id']
    assert media.attachment_id.res_model == 'baseer.bwork.media'
    assert env['baseer.bwork.media'].sudo().browse(facts['stage_id']).state == 'staged'
    assert env['baseer.bwork.mobile.upload.grant'].sudo().search_count([('grant_id', '=', facts['grant_id'])]) == 1
    stranger = env['baseer.bwork.service'].with_user(facts['stranger_id']).with_company(facts['company_id'])
    try:
        stranger._v2_media_content(facts['media_id'])
    except AccessError:
        pass
    else:
        raise AssertionError('Nonmember gained private content.')
    before = _snapshot(env, False)
    prototype.migrate(env.cr, None)
    assert _snapshot(env, False) == before, 'Repeated bootstrap was not a no-op.'
    try:
        with env.cr.savepoint():
            env.cr.execute('CREATE TABLE baseer_bchat_room(id integer PRIMARY KEY)')
            try:
                prototype.migrate(env.cr, None)
            except prototype.MigrationStopped:
                raise RuntimeError('EXPECTED_COLLISION_ROLLBACK')
            raise AssertionError('Mixed old/new schema was accepted.')
    except RuntimeError as error:
        assert str(error) == 'EXPECTED_COLLISION_ROLLBACK'
    assert _snapshot(env, False) == before
    assert service._retention_ready() is False
    return {'real_old_install_upgrade': 'PASS', 'lineage': 'PASS', 'replay': 'PASS',
            'cyclic_reply_and_media': 'PASS', 'bytes': 'PASS', 'nonmember_denial': 'PASS',
            'idempotency': 'PASS', 'collision_rollback': 'PASS', 'readiness_off': True}


def verify_fresh(env):
    _guard(env)
    prototype = _prototype()
    result = prototype.classify(env.cr, ['baseer_bwork'])
    assert result['classification'] == 'canonical-ready'
    env.cr.execute('SELECT value FROM ir_config_parameter WHERE key=%s', [prototype.LEDGER_KEY])
    ledger = json.loads(env.cr.fetchone()[0])
    assert ledger['mode'] == 'fresh' and ledger['scope'] == ['baseer_bwork']
    prototype.migrate(env.cr, None)
    assert env['baseer.bwork.service']._retention_ready() is False
    env.cr.execute("SELECT name,state FROM ir_module_module WHERE name IN ('baseer_bwork_procurement','baseer_bwork_permission_guards','baseer_bwork_document_permission_guards')")
    siblings = dict(env.cr.fetchall())
    assert siblings and any(state == 'uninstalled' for state in siblings.values())
    assert not any(name in result['install'] for name, state in siblings.items() if state == 'uninstalled')
    return {'real_fresh_install': 'PASS', 'fresh_core_only_ledger': 'PASS',
            'uninstalled_siblings_not_installed': 'PASS', 'next_callback_noop': 'PASS'}


def _facts(env):
    env.cr.execute('SELECT value FROM ir_config_parameter WHERE key=%s', [FIXTURE_KEY])
    row = env.cr.fetchone()
    assert row, 'Synthetic fixture metadata required.'
    return json.loads(row[0])


def _financial_fingerprint(env):
    """Aggregate synthetic ERP documents only; never post/receive/pay anything."""
    prototype = _prototype()
    result = {}
    for table in ('account_move', 'account_move_line', 'account_payment', 'stock_move', 'stock_picking',
                  'purchase_order', 'purchase_order_line'):
        if prototype._exists(env.cr, table):
            result[table] = prototype._data_digest(env.cr, table)
    return result


def prepare_legacy_procurement(env):
    """One old-service cash request; same factory as existing orders test case."""
    _guard(env)
    from odoo import Command
    assert 'baseer.bchat.service' in env
    assert 'bchat_order_view' in env['res.users']._fields
    assert 'baseer_access_role' in env['res.users']._fields, 'Existing access-roles fixture prerequisite unavailable.'
    facts = _facts(env)
    assert 'procurement' not in facts
    company = env['res.company'].browse(facts['company_id'])
    admin = env.ref('base.user_admin')
    user = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'BCR synthetic order operator', 'login': 'bcr-order-' + uuid4().hex,
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set([env.ref('base.group_user').id,
                                   env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id])]})
    user.write({'baseer_access_role': 'pos_cashier'})
    user.write({'group_ids': [Command.link(env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id)]})
    user.write({'bchat_order_view': True, 'bchat_order_create': True, 'bchat_order_receive': True})
    env['baseer.bchat.membership'].with_user(admin).with_company(company).create({
        'room_id': facts['room_id'], 'user_id': user.id})
    warehouse = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
    if not warehouse:
        warehouse = env['stock.warehouse'].create({'name': 'BCR synthetic warehouse', 'code': 'BC%s' % company.id,
                                                  'company_id': company.id})
    uom = env.ref('uom.product_uom_unit')
    category = env['product.category'].create({'name': 'BCR synthetic ingredient'})
    product = env['product.product'].with_company(company).create({
        'name': 'BCR synthetic material', 'company_id': company.id, 'categ_id': category.id,
        'uom_id': uom.id, 'purchase_ok': True, 'is_storable': True})
    option = env['baseer.procurement.purchase.option'].with_company(company).create({
        'name': 'BCR synthetic unit', 'company_id': company.id, 'product_id': product.id, 'uom_id': uom.id})
    payload = {'api_version': 2, 'company_id': company.id, 'warehouse_id': warehouse.id,
               'representative_partner_id': None, 'client_uuid': str(uuid4()), 'purchase_route': 'cash',
               'room_id': facts['room_id'], 'lines': [{'option_id': option.id, 'quantity': '2.00'}]}
    service = env['baseer.bchat.service'].with_user(user).with_company(company)
    finance_before = _financial_fingerprint(env)
    created = service._v2_order_create(payload)
    order = env['baseer.procurement.request'].sudo().browse(created['order']['id'])
    assert order.source_channel == 'bchat' and order.bchat_room_id.id == facts['room_id']
    assert order.bchat_message_id and order.bchat_message_id.author_user_id.id == user.id
    assert _financial_fingerprint(env) == finance_before, 'Fixture unexpectedly wrote ERP financial/stock documents.'
    mapping, _ = _prototype().load_mapping()
    permission_rows = [row for row in mapping['fields'] if row['model'] == 'res.users']
    permission_values = {row['new']: user.sudo()[row['old']] for row in permission_rows}
    env.flush_all()
    env.cr.execute('SELECT md5(to_jsonb(t)::text) FROM baseer_procurement_request_line t WHERE request_id=%s ORDER BY id', [order.id])
    lines = [row[0] for row in env.cr.fetchall()]
    facts['procurement'] = {'user_id': user.id, 'id': order.id, 'payload': payload,
                            'client_token': order.client_token, 'payload_hash': order.client_payload_hash,
                            'room_id': order.bchat_room_id.id, 'message_id': order.bchat_message_id.id,
                            'source_channel': order.source_channel, 'state': order.state,
                            'permission_values': permission_values, 'line_hashes': lines,
                            'financial_documents': finance_before}
    # Both stages are committed together by the CI shell caller after this return.
    facts['snapshot'] = _snapshot(env, True)
    env.cr.execute('UPDATE ir_config_parameter SET value=%s WHERE key=%s', [json.dumps(facts, default=str), FIXTURE_KEY])
    return {'legacy_procurement_prepared': 'PASS'}


def verify_upgraded_procurement(env):
    _guard(env)
    facts = _facts(env)
    proof = facts['procurement']
    order = env['baseer.procurement.request'].sudo().browse(proof['id'])
    assert order.exists() and order.source_channel == proof['source_channel']
    assert order.bwork_room_id.id == proof['room_id'] and order.bwork_message_id.id == proof['message_id']
    assert order.client_token == proof['client_token'] and order.client_payload_hash == proof['payload_hash']
    assert order.state == proof['state']
    user = env['res.users'].browse(proof['user_id'])
    for field, expected in proof['permission_values'].items():
        assert user.sudo()[field] == expected, 'Stored/computed permission value changed.'
    env.cr.execute('SELECT md5(to_jsonb(t)::text) FROM baseer_procurement_request_line t WHERE request_id=%s ORDER BY id', [order.id])
    assert [row[0] for row in env.cr.fetchall()] == proof['line_hashes']
    service = env['baseer.bwork.service'].with_user(user).with_company(proof['payload']['company_id'])
    replay = service._v2_order_create(proof['payload'])
    assert replay['replayed'] is True and replay['order']['id'] == order.id
    assert _financial_fingerprint(env) == proof['financial_documents']
    return {'procurement_upgrade': 'PASS', 'same_ids_fks_uuid_digest': 'PASS',
            'all_user_permission_fields': 'PASS', 'provenance_unchanged': 'PASS',
            'replay_same_request': 'PASS', 'no_financial_or_stock_document_change': 'PASS'}


def verify_legacy_restored(env):
    """Paired dump+filestore restore: logical IDs same, PG OIDs may rebase."""
    _guard(env)
    from odoo.exceptions import AccessError
    facts = _facts(env)
    expected = facts['snapshot']
    actual = _snapshot(env, True)
    for value in (expected, actual):
        value['tables'] = {table: facts[1:] for table, facts in value['tables'].items()}
        value.pop('constraints')  # Physical OIDs legitimately change on pg_restore.
    assert expected == actual, 'Restored logical IDs/constraint shapes differ.'
    prototype = _prototype()
    env.cr.execute('SELECT 1 FROM ir_config_parameter WHERE key=%s', [prototype.LEDGER_KEY])
    assert not env.cr.fetchone(), 'Canonical ledger leaked through restored old backup.'
    assert not prototype._exists(env.cr, 'baseer_bwork_room')
    service = env['baseer.bchat.service'].with_user(facts['admin_id']).with_company(facts['company_id'])
    assert service._v2_send(facts['room_id'], facts['text_payload']) == facts['text_ack']
    assert service._v2_send(facts['room_id'], facts['media_payload']) == facts['media_ack']
    raw, _, _ = service._v2_media_content(facts['media_id'])
    assert hashlib.sha256(raw).hexdigest() == facts['bytes_sha256']
    media = env['baseer.bchat.media'].sudo().browse(facts['media_id'])
    assert media.message_id.id == facts['media_ack']['message_id']
    assert media.message_id.reply_to_message_id.id == facts['text_ack']['message_id']
    assert media.attachment_id.res_model == 'baseer.bchat.media'
    assert env['baseer.bchat.media'].sudo().browse(facts['stage_id']).state == 'staged'
    assert env['baseer.bchat.mobile.upload.grant'].sudo().search_count([('grant_id', '=', facts['grant_id'])]) == 1
    stranger = env['baseer.bchat.service'].with_user(facts['stranger_id']).with_company(facts['company_id'])
    try:
        stranger._v2_media_content(facts['media_id'])
    except AccessError:
        pass
    else:
        raise AssertionError('Restored nonmember gained private content.')
    if 'procurement' in facts:
        proof = facts['procurement']
        order = env['baseer.procurement.request'].sudo().browse(proof['id'])
        assert order.bchat_room_id.id == proof['room_id'] and order.bchat_message_id.id == proof['message_id']
        assert order.source_channel == proof['source_channel'] and order.client_payload_hash == proof['payload_hash']
        replay = env['baseer.bchat.service'].with_user(proof['user_id']).with_company(
            proof['payload']['company_id'])._v2_order_create(proof['payload'])
        assert replay['replayed'] is True and replay['order']['id'] == order.id
        assert _financial_fingerprint(env) == proof['financial_documents']
    return {'legacy_restored': 'PASS', 'bytes': 'PASS', 'logical_identity': 'PASS',
            'constraint_shapes': 'PASS', 'physical_oid_rebase': 'EXPECTED', 'nonmember_denial': 'PASS'}

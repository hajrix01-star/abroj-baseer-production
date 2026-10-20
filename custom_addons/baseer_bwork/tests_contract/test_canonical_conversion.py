"""Focused source/stdlib contracts, NOT proof of an actual Odoo upgrade."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zlib import crc32


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wire = load('bwork_canonical_compat', ROOT / 'compatibility.py')
upgrade = load('bwork_canonical_upgrade', ROOT / 'tools/canonical_pre_upgrade.py')


class CanonicalConversionContract(unittest.TestCase):
    def test_authoritative_mapping_has_exact_family_and_collision_free_targets(self):
        mapping, digest = upgrade.load_mapping()
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(mapping['modules']), 4)
        self.assertEqual(len(mapping['models']), 16)
        self.assertEqual(sum(not row['abstract'] for row in mapping['models']), 14)
        self.assertEqual(len(mapping['fields']), 18)
        self.assertEqual(sum(row['stored'] for row in mapping['fields']), 15)
        self.assertEqual(len(mapping['xmlids']), 77)
        self.assertEqual(len(mapping['indexes']), 19)
        self.assertEqual(len(mapping['constraints']), 30)
        for family in ('models', 'modules', 'xmlids', 'indexes'):
            self.assertEqual(len({row['new'] for row in mapping[family]}), len(mapping[family]))
        self.assertEqual(mapping['external_dependency_exceptions'], list(wire.EXTERNAL_ADDON_DEPENDENCIES))

    def test_actual_named_models_and_prefixed_fields_match_map(self):
        mapping, _ = upgrade.load_mapping()
        definitions = set()
        for path in (ROOT / 'models').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == '_name' for x in node.targets):
                    if isinstance(node.value, ast.Constant) and str(node.value.value).startswith('baseer.bwork.'):
                        definitions.add(node.value.value)
        self.assertEqual(definitions, {row['new'] for row in mapping['models']})
        for old in mapping['modules']:
            self.assertFalse((ROOT.parent / old['old']).exists(), old['old'])
            self.assertTrue((ROOT.parent / old['new'] / '__manifest__.py').is_file())

    def test_routes_are_one_handler_with_unchanged_auth_csrf_and_limits(self):
        count = 0
        for addon in ('baseer_bwork', 'baseer_bwork_procurement', 'baseer_bwork_dashboard'):
            for path in (ROOT.parent / addon / 'controllers').glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    if not isinstance(node, ast.FunctionDef):
                        continue
                    for decorator in node.decorator_list:
                        if not isinstance(decorator, ast.Call) or ast.unparse(decorator.func) != 'http.route':
                            continue
                        arg = decorator.args[0]
                        self.assertIsInstance(arg, ast.Call)
                        self.assertEqual(ast.unparse(arg.func), 'routes')
                        self.assertEqual(len(wire.routes(arg.args[0].value)), 2)
                        options = {kw.arg: ast.literal_eval(kw.value) for kw in decorator.keywords
                                   if kw.arg in ('auth', 'type', 'csrf', 'methods')}
                        self.assertIn(options['auth'], ('user', 'none'))
                        if options['auth'] == 'none':
                            self.assertEqual(path.name, 'media_api.py')
                            self.assertIn('mobile-upload-grants/', arg.args[0].value)
                        elif arg.args[0].value == '/bwork/api/v2/rooms/<int:room_id>/uploads/<string:upload_uuid>/reconcile':
                            self.assertEqual(options['methods'], ['GET'])
                            self.assertIs(options['csrf'], False)  # Existing authenticated read contract.
                        else:
                            self.assertIs(options.get('csrf'), True)
                        count += 1
        self.assertGreater(count, 50)

    def test_legacy_url_adaptation_never_rewrites_message_or_digest(self):
        payload = {'image_url': '/bwork/api/v2/orders/image/7?company_id=2',
                   'body': '/bwork/api/v2/orders/image/7', 'payload_digest': 'bchat-bwork',
                   'nested': [{'name': '/bwork/private-name', 'id': 9}]}
        old = wire.wire_payload(payload, '/bchat/api/v2/orders')
        self.assertTrue(old['image_url'].startswith('/bchat/'))
        self.assertEqual(old['body'], payload['body'])
        self.assertEqual(old['payload_digest'], payload['payload_digest'])
        self.assertEqual(old['nested'], payload['nested'])
        self.assertTrue(payload['image_url'].startswith('/bwork/'))
        self.assertIs(wire.wire_payload(payload, '/bwork/api/v2/orders'), payload)

    def test_actual_order_controller_legacy_client_shape_and_ack_keys_survive(self):
        tree = ast.parse((ROOT.parent / 'baseer_bwork_procurement/controllers/orders.py').read_text(encoding='utf-8'))
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'BWorkOrderApi')
        function = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_response')
        function.decorator_list = []
        request = SimpleNamespace(httprequest=SimpleNamespace(path='/bchat/api/v2/orders'),
                                  make_json_response=lambda payload, **kw: (payload, kw))
        namespace = {'request': request, 'wire_payload': wire.wire_payload}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<actual-order-controller>', 'exec'), namespace)
        service_tree = ast.parse((ROOT.parent / 'baseer_bwork_procurement/models/service.py').read_text(encoding='utf-8'))
        service_cls = next(x for x in service_tree.body if isinstance(x, ast.ClassDef) and x.name == 'BWorkProcurementService')
        serializer = next(x for x in service_cls.body if isinstance(x, ast.FunctionDef) and x.name == '_order_data')
        serializer.decorator_list = []
        exec(compile(ast.Module(body=[serializer], type_ignores=[]), '<actual-order-serializer>', 'exec'), namespace)
        order = SimpleNamespace(id=41, name='SYNTHETIC_ORDER', company_id=SimpleNamespace(id=2, name='Company'),
                                requester_id=SimpleNamespace(id=3, name='Member'), state='sent', purchase_route='cash',
                                representative_partner_id=SimpleNamespace(id=False, display_name=''), requested_total='2.00',
                                currency_id=SimpleNamespace(symbol='SAR', name='SAR'), internal_submitted_at='FIXED',
                                bwork_room_id=SimpleNamespace(id=7), _purchase_route_label=lambda: 'Cash')
        service = SimpleNamespace(_label=lambda value, *args: str(value), _money=lambda value: value, _stamp=lambda value: value)
        serialized = namespace['_order_data'](service, order)
        self.assertEqual(serialized['room_id'], 7)
        self.assertFalse(any(key.startswith(('bchat_', 'bwork_')) for key in serialized))
        payload = {'api_version': 2, 'csrf_token': 'SYNTHETIC_CSRF', 'permissions': {'chat_view': True, 'revision': 17},
                   'capabilities': {'retention_version': 1, 'work_tasks_version': 1},
                   'order': serialized,
                   'client': 'bwork', 'preview_enabled': False, 'client_uuid': 'unchanged-opaque-uuid'}
        result, options = namespace['_response'](payload)
        self.assertEqual(result['order'], serialized)
        for key in ('csrf_token', 'permissions', 'capabilities', 'client', 'preview_enabled', 'client_uuid'):
            self.assertEqual(result[key], payload[key])
        self.assertIn(('Cache-Control', 'no-store'), options['headers'])
        request.httprequest.path = '/bwork/api/v2/orders'
        self.assertEqual(namespace['_response'](payload)[0], payload)

    def test_actual_push_registration_preserves_distributed_bwork_privacy_ack(self):
        tree = ast.parse((ROOT / 'models/push.py').read_text(encoding='utf-8'))
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'BWorkPushService')
        function = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_v2_push_register')
        function.decorator_list = []
        device = SimpleNamespace(account_key='SYNTHETIC_ACCOUNT_KEY', client_kind='bwork')
        register = Mock(return_value=device)
        service = SimpleNamespace(_require_any_bwork_permission=Mock(return_value=SimpleNamespace(id=7)),
                                  env={'baseer.bwork.push.device': SimpleNamespace(_register_verified=register)})
        namespace = {'_uuid4': lambda value, label: value, '_fcm_token': lambda value: value,
                     '_PUSH_TOKEN': object(), 'ProtocolError': ValueError}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<actual-push-registration>', 'exec'), namespace)
        payload = {'api_version': 2, 'installation_id': 'SYNTHETIC_UUID', 'fcm_token': 'SYNTHETIC_NOT_REAL', 'client': 'bwork'}
        result = namespace['_v2_push_register'](service, payload)
        self.assertEqual(result['client'], 'bwork')
        self.assertIs(result['preview_enabled'], False)
        self.assertEqual(result['account_key'], device.account_key)
        self.assertEqual(register.call_args.kwargs, {'client': 'bwork'})

    def test_known_uninstalled_catalog_is_not_an_active_install_or_collision_bypass(self):
        mapping, _ = upgrade.load_mapping()
        cursor = Mock()
        rows = [(1, 'baseer_bwork', 'installed'), (2, 'baseer_bwork_procurement', 'uninstalled'),
                (3, 'baseer_bwork_permission_guards', 'uninstalled')]
        cursor.fetchall.return_value = rows
        self.assertEqual(upgrade._module_state(cursor, mapping)['baseer_bwork_procurement'][1], 'uninstalled')
        cursor.fetchall.return_value = rows + [(4, 'baseer_bchat_procurement', 'uninstalled')]
        with self.assertRaisesRegex(upgrade.MigrationStopped, 'module_collision'):
            upgrade._module_state(cursor, mapping)
        cursor.fetchall.return_value = [(2, 'baseer_bwork_procurement', 'uninstalled')]
        module_rows = upgrade._module_state(cursor, mapping)
        cursor.fetchone.return_value = None
        with patch.object(upgrade, '_residual_schema'), patch.object(upgrade, '_exists', return_value=False):
            self.assertEqual(upgrade._preflight(cursor, mapping, module_rows, None), 'fresh')
            with self.assertRaisesRegex(upgrade.MigrationStopped, 'old_catalog_only_bootstrap_required'):
                upgrade._preflight(cursor, mapping, {'baseer_bchat': (1, 'uninstalled')}, None)
        self.assertEqual(set(mapping['m2m_keep']), set(mapping['m2m_columns']))
        self.assertEqual(mapping['m2m_columns']['bwork_retention_run_room_rel'], ['run_id', 'room_id'])

    def test_unknown_old_physical_or_model_catalog_stops_before_mutation(self):
        mapping, _ = upgrade.load_mapping()
        cursor = Mock()
        cursor.fetchall.return_value = [('baseer_bchat_room', 'r', None), ('baseer_bchat_orphan', 'r', None)]
        with self.assertRaisesRegex(upgrade.MigrationStopped, 'unknown_or_residual_legacy_relation'):
            upgrade._residual_schema(cursor, mapping, canonical=False)
        cursor.fetchall.side_effect = [[], [], [('baseer.bchat.custom',)]]
        with self.assertRaisesRegex(upgrade.MigrationStopped, 'unknown_or_residual_legacy_model'):
            upgrade._residual_schema(cursor, mapping, canonical=False)
        cursor.fetchall.side_effect = [[], [('baseer_bchat_unknown_fk', 'unrelated_table')]]
        with self.assertRaisesRegex(upgrade.MigrationStopped, 'unknown_or_residual_legacy_constraint'):
            upgrade._residual_schema(cursor, mapping, canonical=False)
        self.assertTrue(all(not call.args[0].lstrip().upper().startswith(('UPDATE', 'ALTER', 'INSERT'))
                            for call in cursor.execute.call_args_list))

    def test_post_loader_transition_proof_is_explicit_and_read_only(self):
        mapping, digest = upgrade.load_mapping()
        cursor = Mock()
        expected = {'data': {'baseer_bwork_message': [3, 'SYNTHETIC_DIGEST']}}
        cursor.fetchone.return_value = (json.dumps({'mode': 'renamed', 'mapping_sha256': digest, 'lineage': expected}),)
        with patch.object(upgrade, '_verify_canonical'), patch.object(upgrade, '_lineage', return_value=expected):
            self.assertEqual(upgrade.verify_transition(cursor)['transition_lineage'], 'PASS')
        with patch.object(upgrade, '_verify_canonical'), patch.object(upgrade, '_lineage', return_value={'data': {}}):
            with self.assertRaisesRegex(upgrade.MigrationStopped, 'first_transition_lineage_mismatch'):
                upgrade.verify_transition(cursor)
        self.assertTrue(all(call.args[0].lstrip().upper().startswith('SELECT') for call in cursor.execute.call_args_list))

    def test_header_aliases_identical_and_conflict_fail_closed(self):
        headers = dict(wire.response_header('X-BWork-Content-Revision', 31))
        self.assertEqual(headers['X-BChat-Content-Revision'], headers['X-BWork-Content-Revision'])
        wire.validate_headers(headers)
        wire.validate_headers({'X-BChat-Content-Revision': '31'})
        headers['X-BChat-Content-Revision'] = '32'
        with self.assertRaises(ValueError):
            wire.validate_headers(headers)
        with self.assertRaises(ValueError):
            wire.routes('/another/private/path')

    def test_upload_capability_alias_does_not_change_secret_or_id(self):
        value = 'immutable-grant.secret'
        self.assertEqual(wire.upload_token('BWorkUpload ' + value), value)
        self.assertEqual(wire.upload_token('BChatUpload ' + value), value)
        for bad in ('Bearer ' + value, 'BWorkUpload', '', None):
            with self.assertRaises(ValueError):
                wire.upload_token(bad)
        source = (ROOT / 'controllers/media_api.py').read_text(encoding='utf-8')
        self.assertIn("incoming.headers.get('Cookie') or incoming.args", source)
        self.assertIn("supplied_id != grant_id", source)

    def test_metadata_rewrite_is_exact_and_preserves_unrelated_xml_prose(self):
        names = {'baseer.bchat.message': 'baseer.bwork.message', 'bchat_media': 'bwork_media'}
        xml = '<form string="BChat historical evidence"><field name="bchat_media"/><label string="bchat_media"/></form>'
        rewritten = upgrade.rewrite_metadata(xml, names, xml=True)
        self.assertIn('name="bwork_media"', rewritten)
        self.assertIn('string="bchat_media"', rewritten)
        self.assertIn('BChat historical evidence', rewritten)
        untouched = '<form string="No change"><field name="name" /></form>'
        self.assertEqual(upgrade.rewrite_metadata(untouched, names, xml=True), untouched)
        code = "env['baseer.bchat.message'].search([('bchat_media', '=', True)])"
        self.assertIn("env['baseer.bwork.message']", upgrade.rewrite_metadata(code, names))
        self.assertEqual(upgrade.rewrite_metadata('body contains baseer.bchat.message', names), 'body contains baseer.bchat.message')
        self.assertEqual(upgrade.rewrite_metadata({'en_US': xml}, names, xml=True)['en_US'], rewritten)

    def test_reference_storage_resolves_native_nondefault_table_without_skipping_fields(self):
        mapping, _ = upgrade.load_mapping()
        self.assertEqual(mapping['reference_storage_overrides'], [
            {'model': 'ir.actions.server', 'field': 'resource_ref', 'table': 'ir_act_server'}])
        cursor = Mock()
        cursor.fetchall.return_value = [(71, 'ir.ui.menu', 'action'), (72, 'ir.actions.server', 'resource_ref')]
        storage = {('ir_ui_menu', 'action'): 'character varying',
                   ('ir_act_server', 'resource_ref'): 'character varying'}
        names = {'baseer.bchat.message': 'baseer.bwork.message'}
        with patch.object(upgrade, '_column_type', side_effect=lambda _cr, table, column: storage.get((table, column))):
            upgrade._reference_fields(cursor, names, mapping)
        updates = [call for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith('UPDATE')]
        self.assertEqual(len(updates), 2)
        self.assertIn('UPDATE "ir_ui_menu" SET "action"', updates[0].args[0])
        self.assertIn('UPDATE "ir_act_server" SET "resource_ref"', updates[1].args[0])
        self.assertTrue(all(call.args[1] == ['baseer.bwork.message', len('baseer.bchat.message') + 1,
                                            'baseer.bchat.message'] for call in updates))
        self.assertTrue(all("split_part(" in call.args[0] for call in updates))
        for owner, field, kind, code in (
                ('unknown.custom.owner', 'reference', None, 'unsupported_reference_storage'),
                ('ir.actions.server', 'other_reference', None, 'unsupported_reference_storage'),
                ('ir.actions.server', 'resource_ref', None, 'unsupported_reference_storage'),
                ('ir.actions.server', 'resource_ref', 'integer', 'unsupported_reference_type'),
                ('ir.actions.server', 'unsafe;column', 'text', 'unsupported_reference_identifier')):
            with self.subTest(owner=owner, field=field, kind=kind):
                cursor = Mock()
                cursor.fetchall.return_value = [(73, owner, field)]
                with patch.object(upgrade, '_column_type', return_value=kind):
                    with self.assertRaisesRegex(upgrade.MigrationStopped, code):
                        upgrade._reference_fields(cursor, names, mapping)
                self.assertFalse(any(call.args[0].lstrip().startswith('UPDATE')
                                     for call in cursor.execute.call_args_list))

    def test_derived_reference_requires_exact_native_field_and_absent_relation(self):
        mapping, _ = upgrade.load_mapping()
        classification = mapping['reference_derived_nonphysical'][0]
        self.assertEqual(classification, {'model': 'sale.report', 'field': 'order_reference', 'relation': 'sale_report',
                                         'field_xmlid': 'sale.field_sale_report__order_reference',
                                         'allowed_target_models': ['sale.order', 'pos.order']})
        identity = (907, 'sale.report', 'order_reference', 'reference', True)
        cursor = Mock()
        cursor.fetchall.side_effect = [[identity[:3]], [identity]]
        with patch.object(upgrade, '_column_type', return_value=None), patch.object(upgrade, '_exists', return_value=False):
            upgrade._reference_fields(cursor, {'baseer.bchat.message': 'baseer.bwork.message'}, mapping)
        self.assertFalse(any(call.args[0].lstrip().startswith('UPDATE') for call in cursor.execute.call_args_list))
        self.assertEqual(cursor.execute.call_args_list[-1].args[1], ['sale', 'field_sale_report__order_reference'])
        for resolved in ([], [(908, *identity[1:])], [(907, 'other.model', *identity[2:])],
                         [(907, 'sale.report', 'other_field', 'reference', True)],
                         [(907, 'sale.report', 'order_reference', 'char', True)],
                         [(907, 'sale.report', 'order_reference', 'reference', False)]):
            with self.subTest(identity=resolved):
                cursor = Mock()
                cursor.fetchall.side_effect = [[identity[:3]], resolved]
                with self.assertRaisesRegex(upgrade.MigrationStopped, 'unverified_derived_reference_identity'):
                    upgrade._reference_fields(cursor, {}, mapping)
        for relation, column in ((True, None), (False, 'character varying')):
            with self.subTest(physical_relation=relation, physical_column=column):
                cursor = Mock()
                cursor.fetchall.side_effect = [[identity[:3]], [identity]]
                with patch.object(upgrade, '_exists', return_value=relation), patch.object(upgrade, '_column_type', return_value=column):
                    with self.assertRaisesRegex(upgrade.MigrationStopped, 'unexpected_derived_reference_storage'):
                        upgrade._reference_fields(cursor, {}, mapping)
        for invalid in (
                dict(mapping, reference_derived_nonphysical=[classification, classification]),
                dict(mapping, reference_storage_overrides=[{'model': 'sale.report', 'field': 'order_reference', 'table': 'sale_report'}])):
            with self.assertRaisesRegex(upgrade.MigrationStopped, 'overlapping_reference_storage'):
                upgrade._reference_fields(Mock(), {}, invalid)

    def test_identifier_rules_and_injection_rejection_match_official19(self):
        value = 'baseer_bchat_mobile_upload_grant_' + 'x' * 50
        self.assertEqual(upgrade.pg_name(value), value[:54] + '_' + f'{crc32(value.encode()):08x}')
        self.assertEqual(upgrade.identifier('baseer_bwork_message'), '"baseer_bwork_message"')
        for invalid in ('a; DROP TABLE x', 'a.b', '', 'UPPER'):
            with self.assertRaises(upgrade.MigrationStopped):
                upgrade.identifier(invalid)

    def test_native_entrypoints_have_no_environment_commit_or_destructive_sql(self):
        source = (ROOT / 'tools/canonical_pre_upgrade.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for function in tree.body:
            if isinstance(function, ast.FunctionDef) and function.name != '_main':
                for call in ast.walk(function):
                    if isinstance(call, ast.Call):
                        self.assertNotIn(ast.unparse(call.func).split('.')[-1], ('commit', 'unlink', 'create', 'write'))
        for literal in ast.walk(tree):
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                self.assertNotIn('DROP CONSTRAINT', literal.value.upper())
                self.assertNotIn('DROP TABLE', literal.value.upper())
        native = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'migrate')
        self.assertEqual([arg.arg for arg in native.args.args], ['cr', 'version'])

    def test_readiness_and_ledger_are_not_permission_or_activation_seeds(self):
        mapping, _ = upgrade.load_mapping()
        self.assertEqual(mapping['compatibility']['source_channel'], wire.LEGACY_SOURCE_CHANNEL)
        manifest = ast.literal_eval((ROOT / '__manifest__.py').read_text(encoding='utf-8'))
        self.assertEqual(manifest['post_init_hook'], 'post_init_hook')
        hook = (ROOT / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('attest_fresh(env.cr)', hook)
        self.assertNotIn('group_ids', hook)
        self.assertNotIn('retention_ready', hook)

    def test_fresh_attestation_only_requires_loaded_core_but_final_verify_requires_pending_siblings(self):
        mapping, _ = upgrade.load_mapping()
        core_fields = {row['new'] for row in mapping['fields'] if not (
            row['old'].startswith('bchat_order') or row['old'] in (
                'bchat_can_order', 'bchat_room_id', 'bchat_message_id'))}
        tables = {row['new_table'] for row in mapping['models'] if row['new_table']}

        def catalog(*, procurement_loaded=False, missing_core=False, state='to install'):
            cursor = Mock()
            cursor.ledger = None

            def execute(query, params=None):
                cursor.fetchone.return_value = None
                cursor.fetchall.return_value = []
                if query.startswith('SELECT id,model FROM ir_model '):
                    cursor.fetchall.return_value = [(1, params[0][1])]
                elif query.startswith('SELECT 1 FROM ir_model_fields '):
                    field = params[1]
                    if field in core_fields and not missing_core or procurement_loaded and field.startswith('bwork_'):
                        cursor.fetchone.return_value = (1,)
                elif query.startswith('SELECT state FROM ir_module_module '):
                    cursor.fetchone.return_value = (state,)
                elif query.startswith('SELECT id,state FROM ir_module_module '):
                    cursor.fetchone.return_value = (7, 'to install')
                elif query.startswith('SELECT to_regclass('):
                    cursor.fetchone.return_value = (100 + sorted(tables).index(params[0]),)
                elif query.startswith('INSERT INTO ir_config_parameter('):
                    cursor.ledger = json.loads(params[1])

            def exists(_cursor, table, column=None):
                return table in tables if column is None else column in core_fields and not missing_core or (
                    procurement_loaded and column is not None and column.startswith('bwork_'))

            cursor.execute.side_effect = execute
            return cursor, exists

        cursor, exists = catalog()
        with patch.object(upgrade, '_safety') as safety, patch.object(upgrade, '_residual_schema') as residual, \
                patch.object(upgrade, '_column_type', return_value=None), patch.object(upgrade, '_exists', side_effect=exists):
            upgrade.attest_fresh(cursor)
        self.assertEqual(cursor.ledger['scope'], ['baseer_bwork'])
        self.assertEqual(cursor.ledger['modules'], {'baseer_bwork': 7})
        safety.assert_called_once_with(cursor, mapping)
        residual.assert_called_once_with(cursor, mapping, canonical=True)
        for state in ('installed', 'to upgrade', 'to install'):
            with self.subTest(final_state=state):
                cursor, exists = catalog(state=state)
                with patch.object(upgrade, '_safety'), patch.object(upgrade, '_residual_schema'), \
                        patch.object(upgrade, '_column_type', return_value=None), patch.object(upgrade, '_exists', side_effect=exists):
                    with self.assertRaisesRegex(upgrade.MigrationStopped, 'canonical_field_missing'):
                        upgrade._verify_canonical(cursor, mapping)
                cursor, exists = catalog(procurement_loaded=True, state=state)
                with patch.object(upgrade, '_safety'), patch.object(upgrade, '_residual_schema'), \
                        patch.object(upgrade, '_column_type', return_value=None), patch.object(upgrade, '_exists', side_effect=exists):
                    upgrade._verify_canonical(cursor, mapping)
        cursor, exists = catalog(missing_core=True)
        with patch.object(upgrade, '_safety'), patch.object(upgrade, '_residual_schema'), \
                patch.object(upgrade, '_column_type', return_value=None), patch.object(upgrade, '_exists', side_effect=exists):
            with self.assertRaisesRegex(upgrade.MigrationStopped, 'canonical_field_missing'):
                upgrade.attest_fresh(cursor)
        self.assertIsNone(cursor.ledger)


if __name__ == '__main__':
    unittest.main()

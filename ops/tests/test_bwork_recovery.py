"""Recovery protocol pure/transaction seams; no DB, Docker, owner data or secrets."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bwork_logical_recovery_tests', ROOT / 'ops/lib/bwork_recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
TABLES = ['baseer_bwork_fixture_' + str(index) for index in range(14)]
OLD_OIDS = {name: 100 + index for index, name in enumerate(TABLES)}
NEW_OIDS = {name: 1000 + index for index, name in enumerate(TABLES)}


def ledger():
    return json.dumps({'status': 'complete', 'mapping_sha256': recovery.MAPPING_SHA256,
                       'tables': {name: {'oid': value, 'retained': [1, 'same']} for name, value in OLD_OIDS.items()},
                       'modules': {'baseer_bwork': 71}, 'opaque': 'keep byte spacing 100'}, indent=2)


def proof():
    value = ledger()
    row = json.dumps({'id': 9, 'key': recovery.LEDGER_KEY, 'value': value,
                      'write_uid': 1, 'write_date': '2026-10-21 00:00:00'}, sort_keys=True)
    return {'protocol': recovery.PROTOCOL, 'schema_version': 1, 'database': 'baseer_prod',
            'source': {'commit': 'a' * 40, 'core_sha256': 'b' * 64, 'mapping_sha256': recovery.MAPPING_SHA256},
            'schema_sha256': 'c' * 64, 'sequences': [['synthetic_seq', 15, True]],
            'security': {'all': {'sha256': 'd' * 64}}, 'modules': [['baseer_bwork', 71, 'installed', '19.0']],
            'table_oids': copy.deepcopy(OLD_OIDS),
            'ledger': {'id': 9, 'value': value, 'row': row},
            'ledger_remainder': {'rows': 3, 'bytes': 91, 'sha256': 'f' * 64},
            'tables': {'ir_config_parameter': {'rows': 4, 'bytes': len(row.encode()) + 91, 'sha256': '1' * 64},
                       'financial_documents': {'rows': 10, 'bytes': 303, 'sha256': '2' * 64}}}


def restored(original):
    value = copy.deepcopy(original)
    value['table_oids'] = copy.deepcopy(NEW_OIDS)
    return value


def paired_witness(original, schema_sha256=None):
    return {'protocol': 'bwork-paired-restore-v1', 'status': 'RESTORED',
            'method': 'pg_restore-exit-on-error+paired-filestore', 'database': original['database'],
            'old_commit': original['source']['commit'], 'candidate_commit': 'f' * 40,
            'release_id': 'bwork-recovery-20261021', 'run_id': '39513209001', 'source': original['source'],
            'dump_sha256': '1' * 64, 'filestore_sha256': '2' * 64,
            'proof_sha256': hashlib.sha256(recovery.canonical(original) + b'\n').hexdigest(),
            'intent_sha256': '3' * 64, 'toolchain_sha256': '4' * 64,
            'original_schema_sha256': original['schema_sha256'],
            'restored_schema_sha256': schema_sha256 or original['schema_sha256']}


def witness_arguments(original, schema_sha256=None, witness=None):
    witness = paired_witness(original, schema_sha256) if witness is None else witness
    raw = recovery.canonical(witness).decode('utf-8')
    return {'paired_restore_json': raw, 'paired_restore_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'proof_sha256': hashlib.sha256(recovery.canonical(original) + b'\n').hexdigest()}


def post_commit(original):
    value = restored(original)
    updated, _old = recovery.ledger_transition(original['ledger']['value'], NEW_OIDS, TABLES)
    row = json.loads(original['ledger']['row'])
    row['value'] = updated
    value['ledger']['value'] = updated
    value['ledger']['row'] = json.dumps(row, sort_keys=True)
    delta = 2 * (len(updated.encode()) - len(original['ledger']['value'].encode()))
    value['tables']['ir_config_parameter']['bytes'] += delta
    value['tables']['ir_config_parameter']['sha256'] = '3' * 64
    return value


class RecoveryDataContract(unittest.TestCase):
    def test_ascii_uppercase_table_and_sequence_identifiers_keep_exact_case(self):
        self.assertEqual(recovery.quoted('Products'), '"Products"')
        self.assertEqual(recovery.quoted('Products_ID_seq'), '"Products_ID_seq"')
        query = recovery.record_query('Products')
        self.assertIn('FROM ONLY public."Products" t', query)
        self.assertIn("encode(pg_catalog.record_send(t),'hex')", query)
        self.assertIn('COLLATE "C"', query)
        self.assertEqual('SELECT last_value,is_called FROM public.' + recovery.quoted('Products_ID_seq'),
                         'SELECT last_value,is_called FROM public."Products_ID_seq"')
        self.assertEqual(recovery.quoted('_Mixed_123'), '"_Mixed_123"')
        self.assertEqual(recovery.quoted('A' * 63), '"' + 'A' * 63 + '"')

    def test_identifier_shape_length_and_injection_guards_remain_fail_closed(self):
        invalid = ('', 'A' * 64, '1Products', 'Products name', 'Products$', 'Products"',
                   'public.Products', 'Products;SELECT 1', 'Products--', 'Products/*x*/',
                   '\u00e9', 'Products\x00', None, 1, b'Products')
        for name in invalid:
            with self.subTest(name=name), self.assertRaisesRegex(recovery.RecoveryStopped, 'unsupported_identifier'):
                recovery.quoted(name)

    def test_settings_keep_public_current_schema_and_implicit_catalog_precedence(self):
        cr = MagicMock()
        recovery._settings(cr)
        statements = [call.args[0] for call in cr.execute.call_args_list]
        paths = [statement for statement in statements if statement.startswith('SET LOCAL search_path=')]
        # Explicit pg_catalog first makes current_schema() pg_catalog and hides
        # public columns from the unmodified original classifier's predicates.
        # Omitting pg_catalog keeps its implicit first lookup position, while
        # current_schema() follows the explicit public entry (PG16 contract).
        self.assertEqual(paths, ['SET LOCAL search_path=public'])
        original_spec = importlib.util.spec_from_file_location(
            'bwork_recovery_schema_contract_classifier',
            ROOT / 'custom_addons/baseer_bwork/tools/canonical_pre_upgrade.py')
        original = importlib.util.module_from_spec(original_spec)
        original_spec.loader.exec_module(original)
        cr.reset_mock()
        cr.fetchone.return_value = (1,)
        self.assertTrue(original._exists(cr, 'ir_config_parameter', 'value'))
        self.assertIn('table_schema=current_schema()', cr.execute.call_args.args[0])
        self.assertEqual(cr.execute.call_args.args[1], ['ir_config_parameter', 'value'])

    def test_classifier_checks_current_schema_and_catalog_precedence_before_original(self):
        connection = MagicMock()
        cr = connection.cursor.return_value.__enter__.return_value
        original = MagicMock()
        original.classify.return_value = {
            'classification': 'canonical-ready', 'required_closure': sorted(recovery.SIX),
            'install': [], 'native_pre_upgrade_required': False}
        context = {'classifier': original}
        for state in (('pg_catalog', 'pg_catalog'), ('public', 'public'), (None, 'pg_catalog')):
            with self.subTest(state=state):
                cr.fetchone.return_value = state
                with self.assertRaisesRegex(recovery.RecoveryStopped, 'classifier_schema'):
                    recovery._classify(connection, context)
                original.classify.assert_not_called()
        cr.fetchone.return_value = ('public', 'pg_catalog')
        result = recovery._classify(connection, context)
        self.assertEqual(result['classification'], 'canonical-ready')
        cr.execute.assert_called_with('SELECT current_schema(),(current_schemas(true))[1]')
        original.classify.assert_called_once_with(cr, sorted(recovery.FOUR))

    def test_length_framing_order_and_duplicate_rows_are_exact(self):
        rows = ['000001', '000001', '000002']
        expected = b''.join(len(row.encode()).to_bytes(8, 'big') + row.encode() for row in rows)
        actual = recovery.row_fingerprint(iter(rows), recovery.Budget())
        self.assertEqual(actual['sha256'], hashlib.sha256(expected).hexdigest())
        self.assertEqual(actual['rows'], 3)
        self.assertEqual(actual['bytes'], sum(len(row.encode()) for row in rows))
        self.assertNotEqual(actual['sha256'], recovery.row_fingerprint(rows[1:], recovery.Budget())['sha256'])

    def test_unsorted_oversized_and_expired_reads_stop(self):
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'row_order'):
            recovery.row_fingerprint(['ff', 'aa'], recovery.Budget())
        with patch.object(recovery, 'MAX_ROW', 3), self.assertRaisesRegex(recovery.RecoveryStopped, 'row_bound'):
            recovery.row_fingerprint(['1234'], recovery.Budget())
        budget = recovery.Budget()
        budget.start -= recovery.MAX_SECONDS + 1
        with self.assertRaises(recovery.RecoveryStopped):
            budget.check()
        with patch.object(recovery, 'MAX_DATA', 2), self.assertRaises(recovery.RecoveryStopped):
            recovery.row_fingerprint(['1234'], recovery.Budget())

    def test_exact_32mib_hex_boundary_preserves_incremental_reference_hash(self):
        self.assertEqual(recovery.MAX_ROW, 32 * 1024 * 1024)
        row = 'ab' * (recovery.MAX_ROW // 2)
        expected = hashlib.sha256()
        expected.update(recovery.MAX_ROW.to_bytes(8, 'big'))
        chunk = b'ab' * (1024 * 1024 // 2)
        for _ in range(32):
            expected.update(chunk)
        actual = recovery.row_fingerprint(iter([row]), recovery.Budget())
        self.assertEqual(actual, {'rows': 1, 'bytes': recovery.MAX_ROW, 'sha256': expected.hexdigest()})

    def test_cap_plus_two_and_invalid_encodings_still_fail_closed(self):
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'row_bound'):
            recovery.row_fingerprint(['ab' * (recovery.MAX_ROW // 2 + 1)], recovery.Budget())
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'row_bound'):
            recovery.row_fingerprint([''], recovery.Budget())
        for row in ('a', 'AB', 'ag', '\u00e9a'):
            with self.subTest(row=row), self.assertRaisesRegex(recovery.RecoveryStopped, 'native_row_encoding'):
                recovery.row_fingerprint([row], recovery.Budget())
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'row_encoding'):
            recovery.row_fingerprint([b'ab'], recovery.Budget())

    def test_observed_large_ordered_duplicates_keep_every_row_and_frame(self):
        # Measured aggregate size only: no production row content or identifier.
        size = 21577312
        row = '0a' * (size // 2)
        rows = [row, row, 'ff']
        expected = hashlib.sha256()
        for item in rows:
            expected.update(len(item).to_bytes(8, 'big'))
            for offset in range(0, len(item), 1024 * 1024):
                expected.update(item[offset:offset + 1024 * 1024].encode('ascii'))
        actual = recovery.row_fingerprint(iter(rows), recovery.Budget())
        self.assertEqual(actual, {'rows': 3, 'bytes': 2 * size + 2, 'sha256': expected.hexdigest()})
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'row_order'):
            recovery.row_fingerprint(['ff', row], recovery.Budget())

    def test_large_rows_do_not_relax_aggregate_row_or_deadline_budgets(self):
        row = '0a' * (21577312 // 2)
        with patch.object(recovery, 'MAX_DATA', len(row)), \
             self.assertRaisesRegex(recovery.RecoveryStopped, 'data_bound'):
            recovery.row_fingerprint([row, row], recovery.Budget())
        with patch.object(recovery, 'MAX_ROWS', 1), \
             self.assertRaisesRegex(recovery.RecoveryStopped, 'data_bound'):
            recovery.row_fingerprint([row, row], recovery.Budget())
        expired = recovery.Budget()
        expired.start -= recovery.MAX_SECONDS + 1
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'deadline'):
            recovery.row_fingerprint([row], expired)

    def test_native_binary_queries_and_strict_ledger_scalar_shape(self):
        query = recovery.record_query('ir_config_parameter', 9)
        self.assertIn("encode(pg_catalog.record_send(t),'hex')", query)
        self.assertIn('COLLATE "C"', query)
        self.assertIn('WHERE id<>9', query)
        self.assertNotIn('to_jsonb', query)
        cr = MagicMock()
        cr.__iter__.return_value = iter([])
        recovery._catalog_fingerprint(cr, 'SELECT 1 AS value', recovery.Budget())
        self.assertIn('record_send(t)', cr.execute.call_args.args[0])
        recovery.check_ledger_columns(list(recovery.LEDGER_COLUMN_TYPES.items()))
        for extra_type in (114, 1007, 701):  # json, int4[], float8 are deliberately not ledger metadata.
            changed = list(recovery.LEDGER_COLUMN_TYPES.items()) + [('unexpected', extra_type)]
            with self.subTest(extra_type=extra_type), self.assertRaises(recovery.RecoveryStopped):
                recovery.check_ledger_columns(changed)
        changed = dict(recovery.LEDGER_COLUMN_TYPES)
        changed['value'] = 114
        with self.assertRaises(recovery.RecoveryStopped):
            recovery.check_ledger_columns(list(changed.items()))
        with self.assertRaises(recovery.RecoveryStopped):
            recovery.row_fingerprint(['not native hex'], recovery.Budget())

    def test_production_or_exact_marked_synthetic_database_only(self):
        recovery.valid_database('baseer_prod')
        with patch.dict(recovery.os.environ, {}, clear=True):
            for name in ('baseer_qa', 'postgres', 'bwork_canonical_four_ci_012345abcdef'):
                with self.subTest(name=name), self.assertRaises(recovery.RecoveryStopped):
                    recovery.valid_database(name)
        with patch.dict(recovery.os.environ, {'BWORK_RECOVERY_SYNTHETIC': '1'}):
            recovery.valid_database('bwork_canonical_four_ci_012345abcdef')
            recovery.valid_database('bwork_canonical_recovery_ci_fixture')
            with self.assertRaises(recovery.RecoveryStopped):
                recovery.valid_database('bwork_canonical_four_ci_arbitrary')

    def test_only_fourteen_numeric_tokens_change_every_other_ledger_byte_survives(self):
        old = ledger()
        new, prior = recovery.ledger_transition(old, NEW_OIDS, TABLES)
        self.assertEqual(prior, OLD_OIDS)
        expected = json.loads(old)
        for name, oid in NEW_OIDS.items():
            expected['tables'][name]['oid'] = oid
        self.assertEqual(json.loads(new), expected)
        # Indentation, ordering and unrelated number/string text survive.
        before = old
        for oid in OLD_OIDS.values():
            before = before.replace('"oid": ' + str(oid), '"oid": <OID>')
        after = new
        for oid in NEW_OIDS.values():
            after = after.replace('"oid": ' + str(oid), '"oid": <OID>')
        self.assertEqual(before, after)

    def test_mapping_incomplete_missing_duplicate_and_repeated_identity_stop(self):
        for change in ('mapping', 'status', 'missing', 'duplicate', 'wrongtype'):
            value = json.loads(ledger())
            if change == 'mapping':
                value['mapping_sha256'] = '0' * 64
            elif change == 'status':
                value['status'] = 'pending'
            elif change == 'missing':
                value['tables'].pop(TABLES[0])
            elif change == 'duplicate':
                value['tables'][TABLES[0]]['oid'] = value['tables'][TABLES[1]]['oid']
            else:
                value['tables'][TABLES[0]]['oid'] = True
            with self.subTest(change=change), self.assertRaises(recovery.RecoveryStopped):
                recovery.ledger_transition(json.dumps(value), NEW_OIDS, TABLES)
        with self.assertRaises(recovery.RecoveryStopped):
            recovery.ledger_transition(ledger(), OLD_OIDS, TABLES)
        with self.assertRaises(recovery.RecoveryStopped):
            recovery.decode('{"status":1,"status":2}')

    def test_restore_comparison_allows_physical_oid_difference_only(self):
        expected = proof()
        recovery.compare_restored(expected, restored(expected), paired_witness(expected))
        for key in ('protocol', 'database', 'source', 'schema_sha256', 'tables', 'security',
                    'modules', 'sequences', 'ledger', 'ledger_remainder'):
            changed = restored(expected)
            changed[key] = None
            with self.subTest(key=key), self.assertRaises(recovery.RecoveryStopped):
                recovery.compare_restored(expected, changed, paired_witness(expected))

    def test_security_inventory_includes_default_column_extension_and_public_owners(self):
        tree = ast.parse((ROOT / 'ops/lib/bwork_recovery.py').read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_snapshot')
        assignment = next(node for node in ast.walk(function) if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'security_queries' for target in node.targets))
        queries = ast.literal_eval(assignment.value)
        self.assertIn('pg_default_acl', queries['defaultAcls'])
        self.assertIn('pg_get_userbyid', queries['defaultAcls'])
        self.assertIn('defaclacl', queries['defaultAcls'])
        self.assertIn('attacl', queries['columnAcls'])
        self.assertIn('NOT a.attisdropped', queries['columnAcls'])
        self.assertIn('extowner', queries['extensions'])
        self.assertIn('extversion', queries['extensions'])
        self.assertIn('pg_identify_object', queries['publicOwnership'])
        for key in ('defaultAcls', 'columnAcls', 'extensions', 'publicOwnership'):
            original = proof()
            original['security'][key] = {'sha256': '1' * 64}
            changed = restored(original)
            changed['security'][key]['sha256'] = '2' * 64
            with self.subTest(key=key), self.assertRaises(recovery.RecoveryStopped):
                recovery.compare_restored(original, changed, paired_witness(original))

    def test_post_commit_proves_exact_cell_and_every_other_row(self):
        expected = proof()
        actual = post_commit(expected)
        recovery.compare_post_commit(expected, actual, actual['ledger']['value'], NEW_OIDS, expected['schema_sha256'])
        cases = []
        for key in ('security', 'ledger_remainder', 'sequences'):
            changed = copy.deepcopy(actual)
            changed[key] = None
            cases.append(changed)
        changed = copy.deepcopy(actual)
        changed['tables']['financial_documents']['sha256'] = '0' * 64
        cases.append(changed)
        changed = copy.deepcopy(actual)
        row = json.loads(changed['ledger']['row'])
        row['write_date'] = 'changed'
        changed['ledger']['row'] = json.dumps(row)
        cases.append(changed)
        changed = copy.deepcopy(actual)
        changed['tables']['ir_config_parameter']['rows'] += 1
        cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(recovery.RecoveryStopped):
                recovery.compare_post_commit(expected, changed, actual['ledger']['value'], NEW_OIDS,
                                             expected['schema_sha256'])

    def test_foreign_idle_client_and_prepared_transactions_stop(self):
        cr = MagicMock()
        for answers in ([(1,)], [(0,), (1,)]):
            cr.fetchone.side_effect = answers
            with self.assertRaises(recovery.RecoveryStopped):
                recovery._quiet(cr)
        cr.fetchone.side_effect = [(0,), (0,)]
        recovery._quiet(cr)

    def test_wrong_private_stdin_hash_stops_before_source_or_connection(self):
        arguments = ['bwork_recovery.py', 'recover', '--database', 'baseer_prod', '--source-root', '/not-read',
                     '--source-commit', 'a' * 40, '--schema-sha256', 'b' * 64, '--proof-sha256', 'c' * 64]
        with patch.object(recovery.sys, 'argv', arguments), \
             patch.object(recovery.sys, 'stdin', type('Input', (), {'buffer': io.BytesIO(b'{}\n')})()), \
             patch.object(recovery, 'source_context') as source:
            with self.assertRaisesRegex(recovery.RecoveryStopped, 'proof_bytes'):
                recovery.main()
            source.assert_not_called()


class RecoveryWitnessContract(unittest.TestCase):
    def test_valid_witness_is_canonical_bounded_and_binds_actual_capture_bytes(self):
        original = proof()
        arguments = witness_arguments(original, 'e' * 64)
        context = {'identity': original['source']}
        witness = recovery.validate_paired_restore(
            arguments['paired_restore_json'], arguments['paired_restore_sha256'], original,
            arguments['proof_sha256'], context, 'baseer_prod', 'e' * 64)
        self.assertEqual(witness, paired_witness(original, 'e' * 64))
        self.assertEqual(original['schema_sha256'], 'c' * 64)

    def test_wrong_missing_stale_or_unbound_witness_stops_before_database_session(self):
        original = proof()
        valid = paired_witness(original, 'e' * 64)
        cases = []
        for key in valid:
            changed = copy.deepcopy(valid)
            changed.pop(key)
            cases.append(changed)
        for key, value in (
            ('protocol', 'other'), ('status', 'PENDING'), ('method', 'pg_restore'),
            ('database', 'baseer_qa'), ('old_commit', 'b' * 40), ('candidate_commit', 'not-a-commit'),
            ('release_id', '../other'), ('run_id', 42), ('source', {'commit': 'b' * 40}),
            ('proof_sha256', '0' * 64), ('original_schema_sha256', '0' * 64),
            ('restored_schema_sha256', '0' * 64), ('dump_sha256', 'X' * 64),
            ('filestore_sha256', ''), ('intent_sha256', None), ('toolchain_sha256', 'short')):
            changed = copy.deepcopy(valid)
            changed[key] = value
            cases.append(changed)
        changed = copy.deepcopy(valid)
        changed['unexpected'] = 'extra'
        cases.append(changed)
        for index, witness in enumerate(cases):
            connection = MagicMock()
            with self.subTest(index=index), self.assertRaises(recovery.RecoveryStopped):
                recovery.recover(connection, {'identity': original['source']}, 'baseer_prod', 'e' * 64,
                                 original, **witness_arguments(original, witness=witness))
            connection.set_session.assert_not_called()
            connection.cursor.assert_not_called()
            connection.commit.assert_not_called()

    def test_missing_direct_witness_and_tampered_transport_stop_before_database_session(self):
        original = proof()
        connection = MagicMock()
        with self.assertRaises(TypeError):
            recovery.recover(connection, {'identity': original['source']}, 'baseer_prod', 'e' * 64, original)
        good = witness_arguments(original, 'e' * 64)
        variants = []
        for key, value in (('paired_restore_json', None), ('paired_restore_json', good['paired_restore_json'] + '\n'),
                           ('paired_restore_json', ' ' * (recovery.MAX_RESTORE_WITNESS + 1)),
                           ('paired_restore_sha256', '0' * 64), ('proof_sha256', '0' * 64)):
            changed = dict(good)
            changed[key] = value
            variants.append(changed)
        for arguments in variants:
            with self.subTest(arguments=tuple(arguments)), self.assertRaises(recovery.RecoveryStopped):
                recovery.recover(connection, {'identity': original['source']}, 'baseer_prod', 'e' * 64,
                                 original, **arguments)
        connection.set_session.assert_not_called()

    def test_direct_recovery_rejects_foreign_database_and_incomplete_source_context(self):
        original = proof()
        for database, identity in (('baseer_qa', original['source']),
                                   ('baseer_prod', {'commit': 'a' * 40})):
            connection = MagicMock()
            with self.subTest(database=database, identity=identity), self.assertRaises(recovery.RecoveryStopped):
                recovery.recover(connection, {'identity': identity}, database, 'e' * 64, original,
                                 **witness_arguments(original, 'e' * 64))
            connection.set_session.assert_not_called()

    def test_schema_forensics_may_differ_only_with_witness_and_postcommit_stays_exact(self):
        original = proof()
        actual = restored(original)
        actual['schema_sha256'] = 'e' * 64
        recovery.compare_restored(original, actual, paired_witness(original, 'e' * 64))
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'restored_schema_binding'):
            recovery.compare_restored(original, actual, paired_witness(original))
        post = post_commit(original)
        post['schema_sha256'] = 'e' * 64
        recovery.compare_post_commit(original, post, post['ledger']['value'], NEW_OIDS, 'e' * 64)
        post['schema_sha256'] = 'f' * 64
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'post_commit_schema_changed'):
            recovery.compare_post_commit(original, post, post['ledger']['value'], NEW_OIDS, 'e' * 64)
        self.assertEqual(original['schema_sha256'], 'c' * 64)

    def test_cli_capture_forbids_witness_and_recover_requires_both_before_source(self):
        base = ['bwork_recovery.py', 'capture', '--database', 'baseer_prod', '--source-root', '/not-read',
                '--source-commit', 'a' * 40, '--schema-sha256', 'e' * 64]
        for flags in (['--paired-restore-json', '{}'], ['--paired-restore-sha256', 'a' * 64]):
            with self.subTest(flags=flags), patch.object(recovery.sys, 'argv', base + flags), \
                 patch.object(recovery, 'source_context') as source, \
                 self.assertRaisesRegex(recovery.RecoveryStopped, 'paired_restore_argument'):
                recovery.main()
            source.assert_not_called()
        original = proof()
        arguments = witness_arguments(original, 'e' * 64)
        recover_base = [base[0], 'recover'] + base[2:] + ['--proof-sha256', arguments['proof_sha256']]
        for flags in ([], ['--paired-restore-json', arguments['paired_restore_json']],
                      ['--paired-restore-sha256', arguments['paired_restore_sha256']]):
            with self.subTest(flags=flags), patch.object(recovery.sys, 'argv', recover_base + flags), \
                 patch.object(recovery.sys, 'stdin', type('Input', (), {
                     'buffer': io.BytesIO(recovery.canonical(original) + b'\n')})()), \
                 patch.object(recovery, 'source_context') as source, \
                 self.assertRaisesRegex(recovery.RecoveryStopped, 'paired_restore_argument'):
                recovery.main()
            source.assert_not_called()

    def test_cli_rejects_witness_content_before_importing_database_driver(self):
        original = proof()
        changed = paired_witness(original, 'e' * 64)
        changed['database'] = 'other_database'
        arguments = witness_arguments(original, witness=changed)
        argv = ['bwork_recovery.py', 'recover', '--database', 'baseer_prod', '--source-root', '/not-read',
                '--source-commit', 'a' * 40, '--schema-sha256', 'e' * 64,
                '--proof-sha256', arguments['proof_sha256'],
                '--paired-restore-json', arguments['paired_restore_json'],
                '--paired-restore-sha256', arguments['paired_restore_sha256']]
        driver = MagicMock()
        with patch.object(recovery.sys, 'argv', argv), \
             patch.object(recovery.sys, 'stdin', type('Input', (), {
                 'buffer': io.BytesIO(recovery.canonical(original) + b'\n')})()), \
             patch.object(recovery, 'source_context', return_value={'identity': original['source']}), \
             patch.dict(recovery.sys.modules, {'psycopg2': driver}), \
             self.assertRaisesRegex(recovery.RecoveryStopped, 'paired_restore_source'):
            recovery.main()
        driver.connect.assert_not_called()


class RecoveryActualSourceBinding(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bwork-recovery-source-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.core = self.root / 'custom_addons/baseer_bwork'
        (self.core / 'tools').mkdir(parents=True)
        archive = ROOT / 'custom_addons/baseer_bwork/tests_contract/fixtures/canonical_four_baseline_sources.zip'
        raw = archive.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '857110626812b2ea60a2f0a52411932c847d4837f5a8cb310da6ea35ea2f0e34')
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            mapping = source.read('custom_addons/baseer_bwork/canonical_name_map.json')
        self.assertEqual(hashlib.sha256(mapping).hexdigest(), recovery.MAPPING_SHA256)
        (self.core / 'canonical_name_map.json').write_bytes(mapping)
        (self.core / 'tools/canonical_pre_upgrade.py').write_bytes(
            b"def classify(cr, modules):\n    return {'synthetic_import': True}\n")
        (self.root / 'RELEASE_COMMIT').write_text('a' * 40 + '\n', encoding='ascii')

    def test_actual_source_path_hash_mapping_tables_and_classifier_import(self):
        context = recovery.source_context(self.root, 'a' * 40, 'baseer_prod')
        self.assertEqual(len(context['tables']), 14)
        self.assertEqual(len(set(context['tables'])), 14)
        self.assertEqual(context['identity']['mapping_sha256'], recovery.MAPPING_SHA256)
        self.assertTrue(context['classifier'].classify(None, [])['synthetic_import'])
        self.assertEqual(context['identity'], recovery.source_context(self.root, 'a' * 40, 'baseer_prod')['identity'])
        self.assertFalse((self.core / 'tools/__pycache__').exists())

    def test_wrong_marker_missing_marker_and_changed_map_fail_before_import(self):
        marker = self.root / 'RELEASE_COMMIT'
        for raw in ('b' * 40, ''):
            marker.write_text(raw, encoding='ascii')
            with self.subTest(marker=raw), self.assertRaises(recovery.RecoveryStopped):
                recovery.source_context(self.root, 'a' * 40, 'baseer_prod')
        marker.unlink()
        with self.assertRaises((recovery.RecoveryStopped, OSError)):
            recovery.source_context(self.root, 'a' * 40, 'baseer_prod')
        marker.write_text('a' * 40, encoding='ascii')
        (self.core / 'canonical_name_map.json').write_bytes(b'{}')
        with self.assertRaisesRegex(recovery.RecoveryStopped, 'mapping_source'):
            recovery.source_context(self.root, 'a' * 40, 'baseer_prod')

    def test_core_parent_and_nested_source_link_are_rejected(self):
        actual = Path.is_symlink
        for target in (self.root, self.root / 'custom_addons', self.core, self.core / 'tools'):
            with self.subTest(target=str(target)), \
                 patch.object(Path, 'is_symlink', lambda path: path == target or actual(path)), \
                 self.assertRaises(recovery.RecoveryStopped):
                recovery.source_context(self.root, 'a' * 40, 'baseer_prod')
        # _raw_file uses lstat, so a real regular-file mode cannot stand in
        # for a symlink in a fabricated detector test. On every platform,
        # explicitly exercise the lstat regular-file rejection instead.
        mode = type('Stat', (), {'st_mode': 0o120777, 'st_size': 1})()
        with patch.object(Path, 'lstat', return_value=mode), self.assertRaises(recovery.RecoveryStopped):
            recovery._raw_file(self.core / 'tools/canonical_pre_upgrade.py', 1024)


class RecoveryTransactionSeam(unittest.TestCase):
    def scenario(self, *, rowcount=1, classifier_error=False, commit_error=False, post_error=False):
        expected = proof()
        actual, post = restored(expected), post_commit(expected)
        actual['schema_sha256'] = post['schema_sha256'] = 'e' * 64
        if post_error:
            post['security'] = {'changed': True}
        connection = MagicMock()
        cr = connection.cursor.return_value.__enter__.return_value
        cr.fetchone.return_value = (expected['ledger']['value'],)
        cr.rowcount = rowcount
        if commit_error:
            connection.commit.side_effect = RuntimeError('transport failure')
        context = {'tables': TABLES, 'identity': expected['source']}
        classifier = recovery.RecoveryStopped('BWORK_RECOVERY_STOP:original_classifier') if classifier_error else None
        with patch.object(recovery, '_snapshot', side_effect=[actual, post]), \
             patch.object(recovery, '_quiet'), \
             patch.object(recovery, '_classify', side_effect=classifier, return_value={'classification': 'canonical-ready'}):
            if rowcount != 1 or classifier_error or commit_error or post_error:
                with self.assertRaises(recovery.RecoveryStopped) as caught:
                    recovery.recover(connection, context, 'baseer_prod', actual['schema_sha256'], expected,
                                     **witness_arguments(expected, actual['schema_sha256']))
                result = str(caught.exception)
            else:
                result = recovery.recover(connection, context, 'baseer_prod', actual['schema_sha256'], expected,
                                          **witness_arguments(expected, actual['schema_sha256']))
        return connection, cr, result

    def test_success_has_one_conditional_cell_update_and_one_commit(self):
        connection, cr, result = self.scenario()
        connection.commit.assert_called_once_with()
        writes = [call for call in cr.execute.call_args_list if call.args[0].startswith('UPDATE ')]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0].args[0], 'UPDATE public.ir_config_parameter SET value=%s WHERE id=%s AND key=%s AND value=%s')
        self.assertEqual(result['status'], 'RECOVERED')
        self.assertEqual(result['source_commit'], 'a' * 40)
        self.assertEqual(result['old_oids'], OLD_OIDS)
        self.assertEqual(result['new_oids'], NEW_OIDS)
        self.assertEqual(result['original_schema_sha256'], 'c' * 64)
        self.assertEqual(result['schema_sha256'], 'e' * 64)
        self.assertEqual(result['paired_restore_sha256'],
                         witness_arguments(proof(), 'e' * 64)['paired_restore_sha256'])

    def test_wrong_conditional_count_or_classifier_failure_rolls_back_without_commit(self):
        for kwargs in ({'rowcount': 0}, {'rowcount': 2}, {'classifier_error': True}):
            with self.subTest(kwargs=kwargs):
                connection, _cr, _result = self.scenario(**kwargs)
                connection.commit.assert_not_called()
                connection.rollback.assert_called()

    def test_commit_ambiguity_has_no_success_receipt_or_retry(self):
        connection, _cr, result = self.scenario(commit_error=True)
        connection.commit.assert_called_once_with()
        self.assertIn('commit_ambiguous_no_retry', result)

    def test_post_commit_difference_stops_even_after_commit(self):
        connection, _cr, result = self.scenario(post_error=True)
        connection.commit.assert_called_once_with()
        self.assertIn('post_commit_state_mismatch', result)


if __name__ == '__main__':
    unittest.main()

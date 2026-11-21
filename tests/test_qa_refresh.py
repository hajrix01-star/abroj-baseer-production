"""Offline safety-contract tests: no Docker, server, database or network access."""
import importlib.util
import copy
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import tarfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('qa_refresh', Path(__file__).resolve().parents[1] / 'ops/qa/refresh-qa.py')
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class RefreshContracts(unittest.TestCase):
    def setUp(self):
        request = patch.dict(engine.os.environ, {'QA_REFRESH_SIGNED_TAG': 'qa-refresh-20261121b-12345',
                                                 'QA_REFRESH_REVIEWED_REVISION': 'c' * 40,
                                                 'QA_REFRESH_SOURCE_COMMIT': 'd' * 40})
        request.start()
        self.addCleanup(request.stop)

    def make(self):
        return engine.Refresh('12345', 'a' * 40, 'b' * 40)

    def test_new_candidate_has_distinct_fixed_resources(self):
        self.assertEqual(engine.QDB, 'baseer_qa_20261023')
        self.assertEqual(engine.DB, 'baseer_qa_20261121b')
        self.assertEqual(engine.QODOO, 'baseer-qa-refresh-20261023-odoo-1')
        self.assertNotEqual(engine.ODOO, engine.QODOO)
        self.assertEqual(engine.SUBNET, '172.31.136.0/28')
        self.assertNotEqual(engine.PROJECT + '-odoo', engine.QVO)
        refresh = self.make()
        candidate = refresh.compose_config(refresh.release, 18140, refresh.config)
        self.assertEqual(candidate['services']['odoo']['ports'],
                         ['127.0.0.1:18140:8069', '127.0.0.1:18141:8072'])

    def test_snapshot_requires_signed_hashes_exact_inventory_and_source_identity(self):
        original_lstat = Path.lstat
        def root_lstat(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            values = list(result)
            values[4] = 0
            if stat.S_ISDIR(result.st_mode):
                values[0] = stat.S_IFDIR | 0o700
            elif stat.S_ISREG(result.st_mode):
                values[0] = stat.S_IFREG | 0o600
            return os.stat_result(values)

        def attempt(change=None):
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                refresh = self.make()
                refresh.snapshot = Path(directory)
                for name in engine.SNAPSHOT_PINS:
                    (refresh.snapshot / name).write_bytes(('original ' + name).encode())
                pins = {name: engine.digest(refresh.snapshot / name) for name in engine.SNAPSHOT_PINS}
                intent = {'live_sha': 'a' * 40, 'qa_sha': 'b' * 40}
                if change == 'source':
                    intent['live_sha'] = 'e' * 40
                (refresh.snapshot / 'prepare.intent.json').write_text(json.dumps(intent))
                inventory = dict(pins)
                if change == 'inventory':
                    inventory['live.dump'] = '0' * 64
                (refresh.snapshot / 'inventory.json').write_text(json.dumps({'archives': inventory}))
                env = {key: pins[name] for name, key in engine.SNAPSHOT_PINS.items()}
                if change == 'signed_pin':
                    env[engine.SNAPSHOT_PINS['live.dump']] = '0' * 64
                if change == 'file':
                    (refresh.snapshot / 'live.dump').write_bytes(b'tampered')
                with patch.dict(engine.os.environ, env), patch.object(Path, 'lstat', autospec=True, side_effect=root_lstat):
                    self.assertEqual(refresh.snapshot_archives(), pins)
        attempt()
        for change in ('source', 'inventory', 'signed_pin', 'file'):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                attempt(change)

    def test_captured_mount_manifest_requires_the_signed_hash_and_exact_runtime(self):
        refresh = self.make()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh.snapshot = Path(directory)
            baseline = refresh.snapshot / 'baseline'
            for name in engine.SOURCE_DIRS:
                (baseline / name).mkdir(parents=True)
                (baseline / name / 'manifest.py').write_text(name)
            manifest = {name: engine.tree_hash(baseline / name) for name in engine.SOURCE_DIRS}
            capture = refresh.snapshot / 'live-mount-manifest.json'
            capture.write_text(json.dumps(manifest))
            checksum = engine.digest(capture)
            (refresh.snapshot / 'inventory.json').write_text(json.dumps({'mount_sha256': checksum}))
            pins = {'QA_REFRESH_SNAPSHOT_MOUNT_SHA': checksum, 'QA_REFRESH_RUNTIME_BASELINE_DIR': str(baseline)}
            with patch.dict(engine.os.environ, pins), patch.object(engine, 'protected_file'):
                self.assertEqual(refresh.captured_baseline(), manifest)
                (baseline / 'custom_addons' / 'manifest.py').write_text('different')
                with self.assertRaisesRegex(RuntimeError, 'differs from the reviewed baseline'):
                    refresh.captured_baseline()
                capture.write_text('{}')
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    refresh.captured_baseline()

    def test_filestore_archive_rejects_escape_links_and_duplicate_members(self):
        def make_archive(path, bad=None):
            with tarfile.open(path, 'w') as archive:
                root = tarfile.TarInfo('.')
                root.type, root.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(root)
                item = tarfile.TarInfo('aa/' + 'a' * 40)
                item.size, item.mode = 2, 0o644
                archive.addfile(item, io.BytesIO(b'ok'))
                if bad == 'escape':
                    item = tarfile.TarInfo('../outside')
                    item.size = 0
                    archive.addfile(item, io.BytesIO())
                elif bad == 'link':
                    item = tarfile.TarInfo('bb/' + 'b' * 40)
                    item.type, item.linkname = tarfile.SYMTYPE, '../outside'
                    archive.addfile(item)
                elif bad == 'duplicate':
                    item = tarfile.TarInfo('aa/' + 'a' * 40)
                    item.size = 0
                    archive.addfile(item, io.BytesIO())
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'filestore.tar'
            make_archive(path)
            engine.verify_filestore_archive(path)
            for bad in ('escape', 'link', 'duplicate'):
                with self.subTest(bad=bad):
                    make_archive(path, bad)
                    with self.assertRaises(RuntimeError):
                        engine.verify_filestore_archive(path)

    def test_live_baseline_reads_mounted_content_and_detects_drift(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            live = Path(directory).resolve() / 'live'
            baseline = Path(directory).resolve() / 'baseline'
            for name in engine.SOURCE_DIRS:
                (live / name).mkdir(parents=True)
                (baseline / name).mkdir(parents=True)
            active = {'Id': 'stable', 'State': {'Pid': 123, 'Running': True, 'StartedAt': 'same'},
                      'Mounts': [{'Type': 'bind', 'Source': str(live / 'custom_addons'),
                                  'Destination': '/mnt/baseer-addons'},
                                 {'Type': 'bind', 'Source': str(live / 'third_party_addons'),
                                  'Destination': '/mnt/third-party-addons'}]}
            def attempt(change=None):
                first, second = copy.deepcopy(active), copy.deepcopy(active)
                if change == 'mount':
                    first['Mounts'][0]['Source'] = str(baseline / 'custom_addons')
                if change == 'restart':
                    second['State']['Pid'] = 124
                calls = []
                def hash_tree(path, *, ignore_cache=False):
                    calls.append((str(path).replace('\\', '/'), ignore_cache))
                    return {'file.py': ['changed' if change == 'content' and ignore_cache else 'original',
                                        change == 'mode' and ignore_cache]}
                with patch.object(engine, 'LIVE', live), patch.dict(engine.os.environ, {
                        'QA_REFRESH_RUNTIME_BASELINE_DIR': str(baseline)}), \
                        patch.object(engine, 'inspect', side_effect=[first, second]), \
                        patch.object(engine, 'tree_hash', side_effect=hash_tree):
                    result = self.make().verify_live_baseline(live)
                self.assertEqual(set(result), set(engine.SOURCE_DIRS))
                self.assertTrue(any('/proc/123/root/mnt/baseer-addons' in path and ignored for path, ignored in calls))
            attempt()
            for change in ('mount', 'restart', 'content', 'mode'):
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    attempt(change)

    def test_switch_requires_both_receipt_hashes_and_exact_financial_identity(self):
        # Mock POSIX ownership/mode only: receipt bytes and hashes are real.
        original_stat = Path.stat
        def root_stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            values = list(result)
            values[4] = 0
            if stat.S_ISDIR(result.st_mode):
                values[0] = stat.S_IFDIR | 0o700
            elif stat.S_ISREG(result.st_mode):
                values[0] = stat.S_IFREG | 0o600
            return os.stat_result(values)

        def attempt(change=None):
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                refresh = self.make()
                refresh.state = Path(directory)
                prepared = refresh.state / 'prepare.receipt.json'
                prepared_values = {'reviewed_revision': 'c' * 40,
                                   'signed_tag': 'qa-refresh-20261121b-12345',
                                   'source_sha': 'd' * 40, 'live_sha': 'a' * 40,
                                   'previous_qa_sha': 'b' * 40, 'snapshot': engine.SNAPSHOT}
                if change and change[0] == 'prepared_identity':
                    prepared_values[change[1]] = change[2]
                prepared.write_text(json.dumps(prepared_values))
                prepare_hash = engine.digest(prepared)
                evidence = refresh.state / 'financial-input.json'
                evidence.write_text('{"fixture":"original"}')
                workbook = refresh.state / 'financial-workbook.xlsx'
                workbook.write_bytes(b'original workbook')
                verifier = refresh.state / 'verifier.py'
                verifier.write_text('original verifier')
                finance = {'prepared_sha256': prepare_hash, 'source_sha': 'd' * 40,
                           'database': engine.DB, 'arz': 'PASS', 'shami': 'PASS', 'repeat': 'PASS',
                           'company_guard': 'PASS', 'read_only': True,
                           'input_sha256': engine.digest(evidence),
                           'workbook_sha256': engine.digest(workbook),
                           'verifier_sha256': engine.digest(verifier)}
                if change and change[0] == 'finance':
                    finance[change[1]] = change[2]
                financial = refresh.state / 'financial.receipt.json'
                financial.write_text(json.dumps(finance))
                hashes = prepare_hash + ' ' + engine.digest(financial)
                if change and change[0] == 'review':
                    hashes = change[1]
                (refresh.state / 'review.accepted').write_text(hashes)
                if change and change[0] == 'prepared':
                    prepared.write_text(json.dumps(change[1]))
                if change and change[0] == 'financial_after_review':
                    financial.write_text(financial.read_text() + ' ')
                if change and change[0] == 'evidence_after_review':
                    evidence.write_text('{"fixture":"changed"}')
                if change and change[0] == 'workbook_after_review':
                    workbook.write_bytes(b'changed workbook')
                with patch.object(Path, 'stat', autospec=True, side_effect=root_stat), \
                        patch.object(engine, 'VERIFIER', verifier):
                    refresh.start('switch')
                self.assertTrue((refresh.state / 'switch.intent.json').exists())

        attempt()
        for change in [('finance', 'source_sha', 'a' * 40), ('finance', 'database', engine.QDB),
                       ('finance', 'arz', 'FAIL'), ('finance', 'shami', 'FAIL'),
                       ('finance', 'company_guard', 'NO_FIXTURE'), ('finance', 'read_only', False),
                       ('finance', 'prepared_sha256', '0' * 64), ('review', '0' * 64),
                       ('prepared', {'reviewed_revision': 'd' * 40, 'signed_tag': 'wrong'}),
                       ('prepared_identity', 'signed_tag', 'qa-refresh-20261121b-67890'),
                       ('prepared_identity', 'reviewed_revision', 'd' * 40),
                       ('prepared_identity', 'previous_qa_sha', 'a' * 40),
                       ('prepared_identity', 'snapshot', 'another-run'),
                       ('financial_after_review',), ('evidence_after_review',),
                       ('workbook_after_review',)]:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                attempt(change)

    def test_host_and_none_networks_have_no_address_ranges(self):
        for value in ({}, {'IPAM': None}, {'IPAM': {'Config': None}}, {'IPAM': {'Config': []}}):
            self.assertEqual(engine.network_ranges(value), [])
        ranges = [{'Subnet': '172.17.0.0/16'}]
        self.assertEqual(engine.network_ranges({'IPAM': {'Config': ranges}}), ranges)

    def test_arguments_cannot_select_paths_or_shell_commands(self):
        for bad in ('../123', '1;id', '0', '1\n2', 'x', '1' * 25):
            with self.assertRaises(RuntimeError):
                engine.Refresh(bad, 'a' * 40, 'b' * 40)
        with self.assertRaises(RuntimeError):
            engine.Refresh('123', 'HEAD', 'b' * 40)

    def test_config_keeps_credentials_network_and_source_separate(self):
        refresh = self.make()
        config = refresh.compose_config(Path('/srv/baseer-qa/current'), 18134, Path('/etc/baseer-qa/odoo.conf'))
        pg, odoo = config['services']['db'], config['services']['odoo']
        self.assertEqual(pg['image'], engine.PG_IMAGE)
        self.assertEqual(odoo['image'], engine.ODOO_IMAGE)
        self.assertNotEqual(pg['env_file'], odoo['env_file'])
        self.assertEqual([v.replace('\\', '/') for v in odoo['env_file']], ['/etc/baseer-qa/runtime.env'])
        self.assertTrue(all(value.startswith('127.0.0.1:') for value in odoo['ports']))
        self.assertNotIn('ports', pg)
        self.assertEqual(pg['restart'], 'no')
        self.assertEqual(odoo['restart'], 'no')
        self.assertEqual(set(odoo['networks']), {'isolated'})
        self.assertEqual(odoo['sysctls']['net.ipv6.conf.all.disable_ipv6'], '1')
        self.assertIn('/srv/baseer-qa/current/custom_addons:/mnt/baseer-addons:ro', [v.replace('\\', '/') for v in odoo['volumes']])
        self.assertFalse(any('firebase' in value or 'production' in value for value in odoo['volumes']))
        self.assertIn('/mnt/third-party-addons/oca_dms_19', engine.ADDONS)
        subnet = engine.ipaddress.ip_network(engine.SUBNET)
        for service in (pg, odoo):
            self.assertIn(engine.ipaddress.ip_address(service['networks']['isolated']['ipv4_address']), subnet)

    def test_neutralization_is_explicit_and_keeps_user_passwords(self):
        tables = {
            'res_users': {'password': True, 'oauth_access_token': True},
            'res_users_apikeys': {'key': False, 'expiration_date': True},
            'baseer_bwork_push_device': {'active': False, 'fcm_token': False},
            'baseer_print_agent': {'active': False, 'token_fingerprint': True},
            'baseer_bank_sms_pairing': {'state': False, 'expires_at': False},
            'account_move': {'name': True, 'state': False},
            'pos_config': {'access_token': True, 'baseer_direct_print_enabled': True},
        }
        sql = engine.neutral_sql(tables)
        self.assertIn('"oauth_access_token"=NULL', sql)
        self.assertNotIn('"password"=', sql)
        self.assertNotIn('UPDATE "account_move"', sql)
        self.assertNotIn('DELETE', sql)
        self.assertIn('"expiration_date"=\'2000-01-01\'::timestamp', sql)
        self.assertIn('"fcm_token"=\'qa-revoked-\' || id::text', sql)
        self.assertIn('"state"=\'expired\'', sql)
        self.assertIn('database.uuid', sql)
        self.assertIn('database.secret', sql)
        self.assertIn('https://baseer-live-qa.tail938958.ts.net', sql)
        self.assertNotIn('account_fingerprint_secret', sql)
        self.assertTrue(sql.startswith('BEGIN;'))
        self.assertTrue(sql.endswith('COMMIT;'))

    def test_company_membership_password_and_financial_rows_are_protected(self):
        tables = {name: {} for name in ('account_move', 'res_users', 'res_users_settings',
                  'res_company_users_rel', 'res_groups_users_rel', 'ir_module_module',
                  'abroj_employee_history', 'baseer_bwork_membership', 'baseer_loan_installment', 'ir_cron')}
        queries = []
        def query(container, database, statement):
            queries.append(statement)
            return '8|somehash\n'
        with patch.object(engine, 'schema', return_value=tables), patch.object(engine, 'sql', side_effect=query):
            values = engine.fingerprints('only-test-container', 'only_test_database')
        self.assertEqual(set(values), set(tables) - {'ir_cron'})
        user_query = next(q for q in queries if 'FROM "res_users"' in q)
        self.assertNotIn("- 'password'", user_query)
        settings = next(q for q in queries if 'FROM "res_users_settings"' in q)
        self.assertIn("- 'google_calendar_token'", settings)
        self.assertNotIn("- 'id'", settings)

    def test_upgrade_fingerprint_limits_version_exception_to_report_row(self):
        statements = []
        def query(container, database, statement):
            statements.append(statement)
            return '1|digest'
        tables = {'ir_module_module': {}, 'ir_module_module_dependency': {}, 'account_move': {}}
        with patch.object(engine, 'schema', return_value=tables), patch.object(engine, 'sql', side_effect=query):
            engine.fingerprints('test', 'test_db', upgrading=True)
        module = next(q for q in statements if 'FROM "ir_module_module" t' in q)
        dependency = next(q for q in statements if 'FROM "ir_module_module_dependency" t' in q)
        account = next(q for q in statements if 'FROM "account_move" t' in q)
        self.assertIn("WHEN name = 'baseer_profit_loss_report'", module)
        self.assertIn("- 'latest_version'", module)
        self.assertIn("- 'write_date'", module)
        self.assertNotIn(' WHERE ', module)
        self.assertNotIn("- 'write_date'", dependency)
        self.assertNotIn("- 'latest_version'", dependency)
        self.assertNotIn("- 'write_date'", account)

    def test_report_module_requires_exact_installed_version(self):
        refresh = self.make()
        for version in ('19.0.1.1.2', '19.0.1.1.4'):
            with patch.object(engine, 'sql', return_value='installed|' + version):
                refresh.check_report_version(version)
            for actual in ('uninstalled|' + version, 'installed|19.0.1.1.9', '',
                           'installed|' + version + '\ninstalled|' + version):
                with patch.object(engine, 'sql', return_value=actual), self.assertRaises(RuntimeError):
                    refresh.check_report_version(version)

    def test_schema_accepts_quoted_products_identifiers_and_rejects_sql_syntax(self):
        rows = 'Products|stock_move_line_id|YES\nProducts|stock_package_destination_id|NO\n'
        with patch.object(engine, 'sql', return_value=rows):
            self.assertEqual(engine.schema('test', 'test_db'), {'Products': {
                'stock_move_line_id': True, 'stock_package_destination_id': False}})
        statements = []
        def query(container, database, statement):
            statements.append(statement)
            return '2|digest'
        with patch.object(engine, 'schema', return_value={'Products': {'stock_move_line_id': True}}), \
                patch.object(engine, 'sql', side_effect=query):
            self.assertEqual(engine.fingerprints('test', 'test_db', False), {'Products': '2|digest'})
        self.assertIn('FROM "Products" t', statements[0])
        for invalid in ('Products;DROP TABLE res_users|column|YES', 'Products|bad"column|YES',
                        '|column|YES', 'Products|a/b|YES'):
            with patch.object(engine, 'sql', return_value=invalid):
                with self.assertRaises(RuntimeError):
                    engine.schema('test', 'test_db')

    def test_resume_refuses_any_crossed_neutralization_checkpoint(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh = self.make()
            refresh.state = Path(directory)
            (refresh.state / 'prepare.receipt.json').write_text('{}')
            with patch.object(refresh, 'start') as start, patch.object(refresh, 'guards'), \
                    patch.object(refresh, 'finish_prepare') as finish, patch.object(engine, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'recovery point already crossed'):
                    refresh.resume()
                start.assert_called_once_with('resume-12345')
                finish.assert_not_called()
                run.assert_not_called()

    def test_resume_refuses_even_a_stopped_candidate_odoo(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh = self.make()
            refresh.state = Path(directory)
            with patch.object(refresh, 'start'), patch.object(refresh, 'guards'), \
                    patch.object(refresh, 'finish_prepare') as finish, patch.object(engine, 'run', return_value='stopped-container'):
                with self.assertRaisesRegex(RuntimeError, 'candidate Odoo already exists'):
                    refresh.resume()
                finish.assert_not_called()

    def test_resume_only_reuses_the_restored_snapshot(self):
        import inspect
        source = inspect.getsource(engine.Refresh.resume)
        for forbidden in ('self.dump(', 'self.restore(', 'self.archive(', 'copytree(', 'volume", "rm'):
            self.assertNotIn(forbidden, source)
        self.assertIn('self.finish_prepare(manifest)', source)

    def test_resume_intent_names_bind_the_signed_request_and_receipts_do_not_overwrite(self):
        refresh = self.make()
        self.assertEqual(refresh.recovery_stage(), 'resume-12345')
        with patch.dict(engine.os.environ, {'QA_REFRESH_SIGNED_TAG': 'qa-refresh-20261121b-67890'}):
            self.assertEqual(refresh.recovery_stage(), 'resume-67890')
        with patch.dict(engine.os.environ, {'QA_REFRESH_SIGNED_TAG': 'qa-refresh-20261121b-12/34'}):
            with self.assertRaises(RuntimeError):
                refresh.recovery_stage()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh.state = Path(directory)
            receipt = refresh.state / 'prepare.receipt.json'
            receipt.write_text('original')
            with self.assertRaisesRegex(RuntimeError, 'receipt already exists'):
                refresh.receipt('prepare', {'other': 'value'})
            self.assertEqual(receipt.read_text(), 'original')

    def test_recovery_keeps_the_original_financial_baseline(self):
        refresh = self.make()
        original = {'account_move': '10|original'}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh.state = Path(directory)
            path = refresh.state / 'protected-before.json'
            path.write_text(json.dumps(original))
            original_bytes = path.read_bytes()
            with patch.object(refresh, 'attachments', return_value=1), \
                    patch.object(engine, 'fingerprints', return_value={'account_move': '10|changed'}), \
                    patch.object(refresh, 'namespace_test') as network:
                with self.assertRaisesRegex(RuntimeError, 'protected data changed before recovery'):
                    refresh.finish_prepare({})
                network.assert_not_called()
            with patch.object(refresh, 'attachments', return_value=1), \
                    patch.object(engine, 'fingerprints', return_value=original) as fingerprints, \
                    patch.object(refresh, 'namespace_test', side_effect=RuntimeError('network boundary')):
                with self.assertRaisesRegex(RuntimeError, 'network boundary'):
                    refresh.finish_prepare({})
                fingerprints.assert_called_once()
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_upgrade_runs_after_isolation_and_rejects_changed_business_data(self):
        events = []
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh = self.make()
            refresh.state = Path(directory)
            def fingerprint(*args, **kwargs):
                if kwargs.get('upgrading'):
                    events.append('upgrade_fingerprint')
                    return {'account_move': 'changed' if events.count('upgrade_fingerprint') == 2 else 'original'}
                return {'account_move': 'original'}
            def compose(*args):
                events.append(args)
            with patch.object(refresh, 'attachments', return_value=1), \
                    patch.object(engine, 'fingerprints', side_effect=fingerprint), \
                    patch.object(refresh, 'namespace_test', side_effect=lambda: events.append('network')), \
                    patch.object(refresh, 'neutral_guard', side_effect=lambda: events.append('neutral')), \
                    patch.object(refresh, 'check_report_version'), \
                    patch.object(refresh, 'compose_run', side_effect=compose), \
                    patch.object(engine, 'schema', return_value={}), patch.object(engine, 'sql'), \
                    patch.object(refresh, 'health') as health, patch.object(refresh, 'complete_prepare') as complete:
                with self.assertRaisesRegex(RuntimeError, 'protected data changed during module upgrade'):
                    refresh.finish_prepare({})
                health.assert_not_called()
                complete.assert_not_called()
            upgrade = next(x for x in events if isinstance(x, tuple) and '-u' in x)
            self.assertLess(events.index('network'), events.index(upgrade))
            self.assertLess(events.index('neutral'), events.index(upgrade))
            self.assertEqual(upgrade[upgrade.index('-u') + 1], 'baseer_profit_loss_report')
            self.assertIn('--stop-after-init', upgrade)
            self.assertIn('--max-cron-threads=0', upgrade)

    def test_switch_failure_restores_old_configuration_and_boot_enablement(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory) / 'qa'
            config = Path(directory) / 'config'
            state = base / 'refresh' / 'test'
            for path in (base / 'current', config, state):
                path.mkdir(parents=True)
            files = {'compose.yaml': '{"old": true}', 'runtime.env': 'OLD=yes',
                     'odoo.conf': 'old configuration', 'deploy.env': 'QA_DATABASE=old'}
            for name, contents in files.items():
                (config / name).write_text(contents)
            (state / 'inventory.json').write_text(json.dumps({
                'old_source': str((base / 'current').resolve()), 'poller_active': True}))
            (state / 'app.env').write_text('POSTGRES_USER=qa_runner')
            (state / 'odoo.conf').write_text('candidate configuration')
            refresh = self.make()
            refresh.state, refresh.config, refresh.compose = state, state / 'odoo.conf', state / 'compose.json'
            refresh.release = base / 'candidate'
            events = []
            def command(args, **kwargs):
                events.append(tuple(args))
                if args[:2] == ['systemctl', 'is-enabled']:
                    return 'enabled\n'
                if args[:2] == ['systemctl', 'is-active']:
                    return 'active\n'
                return ''
            with patch.object(engine, 'BASE', base), patch.object(engine, 'CONFIG', config), \
                    patch.object(refresh, 'start'), patch.object(refresh, 'verify', side_effect=[None, RuntimeError('candidate health')]), \
                    patch.object(refresh, 'compose_run'), patch.object(engine, 'run', side_effect=command), \
                    patch.object(engine.os, 'chown', create=True), patch.object(engine.os, 'replace'), \
                    patch.object(Path, 'symlink_to'):
                with self.assertRaisesRegex(RuntimeError, 'candidate health'):
                    refresh.switch()
            for name, contents in files.items():
                self.assertEqual((config / name).read_text(), contents)
            self.assertIn(('docker', 'start', engine.QODOO), events)
            self.assertIn(('systemctl', 'enable', 'baseer-qa-refresh.service'), events)
            self.assertIn(('systemctl', 'start', engine.TIMER), events)
            self.assertTrue(json.loads((state / 'rollback.receipt.json').read_text())['old_odoo_restarted'])

    def test_network_proof_explicitly_allows_internal_qa_peer_and_records_ipv6(self):
        import inspect
        source = inspect.getsource(engine.Refresh.namespace_test)
        self.assertIn("name == 'internal_qa_peer'", source)
        targets = [('database', engine.PGIP, 5432, True), ('internal_qa_peer', '172.31.136.5', 16443, True)]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh = self.make()
            refresh.state = Path(directory)
            with patch.object(engine, 'run', return_value='{"database":true,"internal_qa_peer":true,"ipv6_disabled":true}') as run:
                refresh.namespace_probe(targets)
            self.assertIn("r['ipv6_disabled']=True", run.call_args.args[0][-1])
            self.assertTrue(json.loads((refresh.state / 'network-proof.json').read_text())['ipv6_disabled'])

    def test_referenced_blob_must_match_size_and_checksum(self):
        refresh = self.make()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh.state = Path(directory)
            root = Path(directory) / 'volume'
            data = b'attachment-evidence'
            sha = engine.hashlib.sha1(data).hexdigest()
            name = sha[:2] + '/' + sha
            blob = root / 'filestore' / engine.DB / name
            blob.parent.mkdir(parents=True)
            blob.write_bytes(data)
            for checksum in (sha, None):
                row = json.dumps([1, name, checksum, len(data)])
                with patch.object(engine, 'volume', return_value=root), patch.object(engine, 'sql', return_value=row):
                    self.assertEqual(refresh.attachments(), 1)
                proof = json.loads((refresh.state / 'attachments.json').read_text())[0]
                self.assertEqual(proof[2], sha)
                self.assertEqual(proof[4], checksum is None)
            for invalid in ([1, name, '0' * 40, len(data)], [1, name, sha, len(data) + 1],
                            [1, '../../secret', sha, len(data)]):
                with patch.object(engine, 'volume', return_value=root), patch.object(engine, 'sql', return_value=json.dumps(invalid)):
                    with self.assertRaises(RuntimeError):
                        refresh.attachments()

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'Unix root owner/mode contract')
    def test_incomplete_prepare_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh = self.make()
            refresh.state = Path(directory) / 'new-state'
            with patch.object(engine.os, 'geteuid', return_value=0):
                refresh.start('prepare')
                with self.assertRaises(FileExistsError):
                    refresh.start('prepare')
            self.assertTrue((refresh.state / 'prepare.intent.json').exists())

    def test_no_legacy_zatca_mutations_in_prepare(self):
        import inspect
        source = inspect.getsource(engine.Refresh.prepare_impl)
        self.assertNotIn('ZATCA', source)
        self.assertNotIn('qa_old_restore_', source)
        self.assertIn("manifest['old_databases'] = [QDB]", source)
        self.assertNotIn('dropdb', source)
        self.assertNotIn('volume", "rm', source)


if __name__ == '__main__':
    unittest.main()

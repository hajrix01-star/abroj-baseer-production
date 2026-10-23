"""Offline safety-contract tests: no Docker, server, database or network access."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('qa_refresh', Path(__file__).resolve().parents[1] / 'ops/qa/refresh-qa.py')
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class RefreshContracts(unittest.TestCase):
    def setUp(self):
        request = patch.dict(engine.os.environ, {'QA_REFRESH_SIGNED_TAG': 'qa-refresh-20261023-12345'})
        request.start()
        self.addCleanup(request.stop)

    def make(self):
        return engine.Refresh('12345', 'a' * 40, 'b' * 40)

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
                  'abroj_employee_history', 'baseer_bwork_membership', 'ir_cron')}
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

    def http_checkpoint(self, refresh):
        baseline = {'account_move': '10|original'}
        files = {'protected-before.json': json.dumps(baseline), 'protected-after.json': json.dumps(baseline),
                 'network-proof.json': '{"database": true}\n', 'pg.env': 'POSTGRES_USER=qa_refresh_admin',
                 'app.env': 'POSTGRES_USER=qa_runner', 'odoo.conf': 'original-config', 'compose.json': '{}'}
        for name, value in files.items():
            (refresh.state / name).write_text(value)
        def container(ident, image, env, mounts):
            return {'Id': ident, 'Image': image, 'Config': {'Env': env}, 'State': {'Running': False},
                    'HostConfig': {'RestartPolicy': {'Name': 'no'}},
                    'NetworkSettings': {'Networks': {engine.NETWORK: {}}}, 'Mounts': mounts}
        pg = container('pg-id', engine.PG_IMAGE, ['POSTGRES_USER=qa_refresh_admin'], [
            {'Destination': '/var/lib/postgresql/data', 'Type': 'volume', 'Name': engine.PROJECT + '-postgres', 'RW': True}])
        mounts = [{'Destination': '/var/lib/odoo', 'Type': 'volume', 'Name': engine.PROJECT + '-odoo', 'RW': True}]
        for target, source in (('/etc/odoo/odoo.conf', refresh.config), ('/mnt/baseer-addons', refresh.release / 'custom_addons'),
                               ('/mnt/third-party-addons', refresh.release / 'third_party_addons')):
            mounts.append({'Destination': target, 'Type': 'bind', 'Source': str(source), 'RW': False})
        odoo = container('odoo-id', engine.ODOO_IMAGE, ['POSTGRES_USER=qa_runner'], mounts)
        odoo['Mounts'].append({'Destination': '/mnt/extra-addons', 'Type': 'volume',
                              'Name': 'image-extra', 'Source': str(refresh.state / 'extra'), 'RW': True})
        network = {'Name': engine.NETWORK, 'Driver': 'bridge', 'Internal': True, 'EnableIPv6': False,
                   'IPAM': {'Config': [{'Subnet': engine.SUBNET, 'Gateway': '172.31.134.1'}]},
                   'Containers': {'pg-id': {}, 'odoo-id': {}}}
        return baseline, network, pg, odoo

    def test_http_recovery_preserves_evidence_and_installs_firewall_before_start(self):
        refresh, events = self.make(), []
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh.state = Path(directory)
            baseline, network, pg, odoo = self.http_checkpoint(refresh)
            original = {name: (refresh.state / name).read_bytes() for name in
                        ('protected-before.json', 'protected-after.json', 'network-proof.json')}
            (refresh.state / 'extra').mkdir()
            with patch.object(engine, 'inspect', side_effect=[network, pg, odoo, {'Config': {'Volumes': {'/mnt/extra-addons': {}}}}]), \
                    patch.object(engine, 'volume', return_value=refresh.state / 'extra'), \
                    patch.object(engine, 'fingerprints', return_value=baseline), \
                    patch.object(engine, 'run', side_effect=lambda args, **kwargs: events.append(tuple(args)) or 'ready'), \
                    patch.object(refresh, 'compose_run', side_effect=lambda *args: events.append(('compose',) + args)), \
                    patch.object(refresh, 'firewall', side_effect=lambda: events.append(('firewall',))), \
                    patch.object(refresh, 'namespace_test') as proof, patch.object(refresh, 'neutral_guard'), \
                    patch.object(refresh, 'health') as health, patch.object(refresh, 'receipt') as receipt, \
                    patch.object(refresh, 'attachments', return_value=8), patch.object(refresh, 'complete_prepare') as complete:
                refresh.recover_http({'old_databases': [engine.QDB]}, 'resume-12345')
            self.assertLess(events.index(('firewall',)), events.index(('compose', 'up', '-d', '--force-recreate', 'db')))
            self.assertLess(events.index(('compose', 'up', '-d', '--force-recreate', 'db')),
                            events.index(('compose', 'up', '-d', '--force-recreate', 'odoo')))
            self.assertIn(('docker', 'network', 'create', '--subnet', engine.SUBNET, engine.NETWORK), events)
            self.assertIn(('docker', 'rm', engine.PG, engine.ODOO), events)
            self.assertNotIn('--internal', str(events))
            proof.assert_called_once_with('resume-12345.network-proof.json')
            health.assert_called_once_with(18136)
            self.assertEqual(receipt.call_args.args[0], 'resume-12345-network-migration')
            self.assertEqual(complete.call_args.args[1], 8)
            for name, content in original.items():
                self.assertEqual((refresh.state / name).read_bytes(), content)
            self.assertEqual((refresh.state / 'resume-12345.prior-network-proof.json').read_bytes(), original['network-proof.json'])

    def test_http_recovery_refuses_other_network_endpoints_before_stopping_anything(self):
        refresh = self.make()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh.state = Path(directory)
            baseline, network, pg, odoo = self.http_checkpoint(refresh)
            network['Containers']['foreign-id'] = {}
            with patch.object(engine, 'inspect', side_effect=[network, pg, odoo]), \
                    patch.object(engine, 'fingerprints', return_value=baseline), patch.object(engine, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'unexpected QA network checkpoint'):
                    refresh.recover_http({}, 'resume-12345')
                run.assert_not_called()

    def test_http_recovery_refuses_nonempty_image_extra_addons(self):
        refresh = self.make()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            refresh.state = Path(directory)
            baseline, network, pg, odoo = self.http_checkpoint(refresh)
            extra = refresh.state / 'extra'
            extra.mkdir()
            (extra / 'unexpected.py').write_text('unexpected')
            with patch.object(engine, 'inspect', side_effect=[network, pg, odoo, {'Config': {'Volumes': {'/mnt/extra-addons': {}}}}]), \
                    patch.object(engine, 'volume', return_value=extra), \
                    patch.object(engine, 'fingerprints', return_value=baseline), patch.object(engine, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'unexpected image extra-addons contents'):
                    refresh.recover_http({}, 'resume-12345')
                run.assert_not_called()

    def test_resume_intent_names_bind_the_signed_request_and_receipts_do_not_overwrite(self):
        refresh = self.make()
        self.assertEqual(refresh.recovery_stage(), 'resume-12345')
        with patch.dict(engine.os.environ, {'QA_REFRESH_SIGNED_TAG': 'qa-refresh-20261023-67890'}):
            self.assertEqual(refresh.recovery_stage(), 'resume-67890')
        with patch.dict(engine.os.environ, {'QA_REFRESH_SIGNED_TAG': 'qa-refresh-20261023-12/34'}):
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

    def test_network_proof_explicitly_allows_internal_qa_peer_and_records_ipv6(self):
        import inspect
        source = inspect.getsource(engine.Refresh.namespace_test)
        self.assertIn("name == 'internal_qa_peer'", source)
        targets = [('database', engine.PGIP, 5432, True), ('internal_qa_peer', '172.31.134.5', 16443, True)]
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
        self.assertIn('databases = [QDB]', source)
        self.assertNotIn('dropdb', source)
        self.assertNotIn('volume", "rm', source)


if __name__ == '__main__':
    unittest.main()

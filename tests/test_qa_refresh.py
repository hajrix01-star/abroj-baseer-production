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
    def make(self):
        return engine.Refresh('12345', 'a' * 40, 'b' * 40)

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

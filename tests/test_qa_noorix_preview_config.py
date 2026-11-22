import importlib.util
import json
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'preview', Path(__file__).resolve().parents[1] / 'ops/qa/prepare-noorix-preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewConfigTest(unittest.TestCase):
    def setUp(self):
        self.run_id = '12345'
        self.password = 'a' * 64
        self.compose = preview._original_compose(self.run_id)
        self.runtime = ('POSTGRES_USER=qa_runner\nPOSTGRES_PASSWORD=' + self.password +
                        '\nPOSTGRES_DB=baseer_qa_20261121b\nHOST=db\nUSER=qa_runner\nPASSWORD=' +
                        self.password + '\n')
        self.deploy = ("QA_ENVIRONMENT=qa\nQA_BASE=/srv/baseer-qa\n"
                       "QA_SOURCE_REMOTE='git@example.test:repo'\n")
        self.conf = ('[options]\naddons_path=' + preview.ADDONS + '\ndata_dir=/var/lib/odoo\n'
                     'db_host=db\ndb_port=5432\ndb_user=qa_runner\ndb_password=' + self.password +
                     '\ndb_name=baseer_qa_20261121b\ndbfilter=^baseer_qa_20261121b$\n'
                     'list_db=False\nproxy_mode=True\nworkers=2\nmax_cron_threads=0\n'
                     'limit_time_cpu=120\nlimit_time_real=240\nhttp_port=8069\ngevent_port=8072\n'
                     'admin_passwd=$pbkdf2-sha512$600000$salt$hash\n')

    def build(self):
        return preview.build_preview(json.dumps(self.compose), self.runtime, self.deploy, self.conf, self.run_id)

    def test_preview_paths_and_resources_preserved(self):
        result = self.build()
        config = '/etc/baseer-qa/noorix-preview'
        self.assertEqual(set(result), {config + '/compose.yaml', config + '/runtime.env',
                                       config + '/deploy.env', config + '/odoo.conf'})
        compose = json.loads(result[config + '/compose.yaml'])
        self.assertEqual(compose['services']['db'], self.compose['services']['db'])
        self.assertEqual(compose['volumes'], self.compose['volumes'])
        self.assertEqual(compose['networks'], self.compose['networks'])
        app = compose['services']['odoo']
        self.assertEqual(app['ports'], ['127.0.0.1:18140:8069', '127.0.0.1:18141:8072'])
        self.assertEqual(app['restart'], 'no')
        self.assertIn('/srv/baseer-qa/noorix-preview/current/custom_addons:/mnt/baseer-addons:ro', app['volumes'])
        self.assertIn('QA_BASE=/srv/baseer-qa\n', result[config + '/deploy.env'])
        self.assertEqual(result[config + '/runtime.env'], self.runtime)
        self.assertEqual(result[config + '/odoo.conf'], self.conf)

    def test_unexpected_network_db_or_ports_rejected(self):
        for alter in ('network', 'port', 'restart', 'volume', 'extra'):
            with self.subTest(alter=alter):
                self.setUp()
                if alter == 'network': self.compose['networks']['isolated']['name'] = 'production'
                if alter == 'port': self.compose['services']['odoo']['ports'][0] = '0.0.0.0:18140:8069'
                if alter == 'restart': self.compose['services']['odoo']['restart'] = 'always'
                if alter == 'volume': self.compose['services']['db']['volumes'] = ['production:/var/lib/postgresql/data']
                if alter == 'extra': self.compose['services']['odoo']['privileged'] = True
                with self.assertRaises(ValueError): self.build()

    def test_identity_or_secret_discrepancies_are_rejected_without_echo(self):
        for change in ('db', 'password', 'cron', 'shell', 'duplicate', 'extra_config'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'db': self.conf = self.conf.replace('db_name=baseer_qa_20261121b', 'db_name=live')
                if change == 'password': self.conf = self.conf.replace('db_password=' + self.password, 'db_password=secret')
                if change == 'cron': self.conf = self.conf.replace('max_cron_threads=0', 'max_cron_threads=1')
                if change == 'shell': self.deploy += 'QA_TEST=$(bad)\n'
                if change == 'duplicate': self.runtime += 'HOST=live\n'
                if change == 'extra_config': self.conf += 'server_wide_modules=bad\n'
                with self.assertRaises(ValueError) as error: self.build()
                self.assertNotIn(self.password, str(error.exception))

    def test_rejects_duplicate_json_and_wrong_run(self):
        with self.assertRaises(ValueError):
            preview.build_preview('{"services":{},"services":{}}', self.runtime, self.deploy, self.conf, self.run_id)
        with self.assertRaises(ValueError):
            preview.build_preview(json.dumps(self.compose), self.runtime, self.deploy, self.conf, '../1')


if __name__ == '__main__':
    unittest.main()

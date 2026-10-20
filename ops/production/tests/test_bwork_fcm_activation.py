"""Synthetic activation contract: subprocess/path/health are mocked, no host reads."""
import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import types
import unittest
from unittest.mock import patch

OPS = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, OPS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


activation = load('activation', 'activate-bwork-fcm-runtime.py')
configure = load('configure', 'configure-bwork-fcm-runtime.py')


class TestContracts(unittest.TestCase):
    def setUp(self):
        self.value = {'appliedEnvSha256': 'a' * 64, 'oldEnvSha256': 'b' * 64,
                      'receiptSha256': 'c' * 64, 'expectedDeployRun': activation.DEPLOY,
                      'backupPath': '/srv/abroj-baseer-production/secrets/google/bwork-fcm-backups/fcm-synthetic/preimage.env'}

    def test_metadata_exact_bounded_duplicate_free(self):
        # The CLI is Linux-only; emulate Linux lexical paths for pure Windows tests.
        with patch.object(activation, 'Path', PurePosixPath), \
                patch.object(configure, 'BACKUP_ROOT', PurePosixPath('/srv/abroj-baseer-production/secrets/google/bwork-fcm-backups')):
            self.check_metadata()

    def check_metadata(self):
        self.assertEqual(activation.metadata(json.dumps(self.value).encode(), configure), self.value)
        for change in ({'expectedDeployRun': activation.APPROVAL}, {'oldEnvSha256': 'X' * 64},
                       {'extra': True}, {'backupPath': '/tmp/preimage.env'}):
            with self.assertRaises(activation.Stop):
                activation.metadata(json.dumps({**self.value, **change}).encode(), configure)
        for raw in (b'x' * 4097, b'{"a":1,"a":2}', b'{"x":"\\u0000"}'):
            with self.assertRaises((activation.Stop, configure.Refused)):
                activation.metadata(raw, configure)

    def test_no_upgrade_compact_flags_or_password_arguments(self):
        activation.safe_command(['odoo', '--database=baseer_prod'])
        for flag in ('-u', '-uall', '-i', '-ibase', '--update=all', '--init=base',
                     '--stop-after-init', '--pre-upgrade-scripts=x', '--db_password=synthetic'):
            with self.assertRaises(activation.Stop):
                activation.safe_command(['odoo', flag])

    def test_compose_target_only_and_no_db_inheritance(self):
        release = Path('/synthetic/release')
        odoo = {'command': ['odoo'], 'environment': {activation.JSON_KEY: 'synthetic'},
                'volumes': [{'type': 'bind', 'target': target, 'source': str(release / source), 'read_only': True}
                            for target, source in (('/mnt/baseer-addons', 'custom_addons'),
                                                   ('/mnt/third-party-addons', 'third_party_addons'),
                                                   ('/etc/odoo/odoo.conf', 'config/odoo.conf'))]}
        odoo['volumes'].append({'type': 'volume', 'target': '/var/lib/odoo', 'source': 'odoo-data'})
        config = {'name': activation.PROJECT, 'services': {'odoo': odoo, 'db': {}, 'odoo_data_init': {}},
                  'volumes': {'odoo-data': {'name': activation.PROJECT + '-odoo-data'}}}
        activation.validate_compose(config, release, 'synthetic')
        for service in ('db', 'odoo_data_init'):
            bad = copy.deepcopy(config)
            bad['services'][service]['environment'] = {activation.JSON_KEY: 'synthetic'}
            with self.assertRaises(activation.Stop): activation.validate_compose(bad, release, 'synthetic')
        bad = copy.deepcopy(config)
        bad['services']['odoo']['volumes'][0]['read_only'] = False
        with self.assertRaises(activation.Stop): activation.validate_compose(bad, release, 'synthetic')

    def test_deployment_receipt_duplicate_keys(self):
        with self.assertRaises(activation.Stop): activation.read_receipt_env(b'LIVE=GO\nLIVE=GO\n')

    def test_capture_never_echoes_failed_private_output(self):
        fake = types.SimpleNamespace(returncode=1, stdout=b'SYNTHETIC_PRIVATE')
        with patch.object(activation.subprocess, 'run', return_value=fake) as run:
            with self.assertRaisesRegex(activation.Stop, '^local_command_failed$'):
                activation.capture(['docker', 'inspect', 'synthetic'])
            self.assertEqual(run.call_args.kwargs['stderr'], activation.subprocess.DEVNULL)

    def test_import_pin_rejects_before_exec(self):
        with patch.object(activation, 'public_file', return_value=b'raise RuntimeError("never execute")'), \
                patch.object(Path, 'lstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFREG | 0o600)):
            with self.assertRaisesRegex(activation.Stop, '^configure_pin_mismatch$'):
                activation.load_configure()

    def test_control_file_symlink_rejected_before_open(self):
        def info(path):
            if path == Path('/synthetic/control'):
                return types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0, st_gid=0, st_nlink=1)
            return types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
        with patch.object(Path, 'lstat', info), patch.object(activation.os, 'open') as opened:
            with self.assertRaises(activation.Stop): activation.public_file(Path('/synthetic/control'))
            opened.assert_not_called()

    def test_health_fixed_loopback_no_proxy_and_bounded_failure(self):
        opener = types.SimpleNamespace(open=lambda *args, **kwargs: (_ for _ in ()).throw(OSError('private')))
        with patch.object(activation.urllib.request, 'build_opener', return_value=opener), \
                patch.object(activation.time, 'monotonic', side_effect=[0, 46]):
            with self.assertRaisesRegex(activation.Stop, '^login_health_failed$'): activation.health()


class TestActivationFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bwork-activation-synthetic-', dir=OPS / 'tests')
        self.addCleanup(self.temp.cleanup)
        self.release = Path('/synthetic/release')
        self.events = []
        self.old, self.new = b'old synthetic env', b'new synthetic env'
        self.value = {'appliedEnvSha256': activation.digest(self.new), 'oldEnvSha256': activation.digest(self.old),
                      'receiptSha256': 'c' * 64, 'backupPath': '/synthetic/backup/preimage.env'}
        self.env_path = Path('/synthetic/google.env')
        self.shared = self.release / '.env'
        self.env_bytes = self.new
        self.credential = 'synthetic-canonical-json'
        self.active = False
        self.other_id = 'db-unchanged'
        self.changed_source = False
        self.restore_failure = False
        self.up_failure = False
        self.projection_changed = False
        self.health_calls = 0
        self.fail_first_activation_health = False
        self.helper = types.SimpleNamespace(ENV_PATH=self.env_path, read_private=self.read_private,
                                            fsync_dir=lambda _: None, restore_backup=self.restore)
        volumes = [{'type': 'bind', 'target': target, 'source': str(self.release / source), 'read_only': True}
                   for target, source in (('/mnt/baseer-addons', 'custom_addons'),
                                          ('/mnt/third-party-addons', 'third_party_addons'),
                                          ('/etc/odoo/odoo.conf', 'config/odoo.conf'))]
        self.spec = {'image': 'synthetic-image', 'command': ['odoo', '--database=baseer_prod'],
                     'environment': {'HOST': 'db', activation.JSON_KEY: self.credential}, 'volumes': volumes}
        self.spec['volumes'].append({'type': 'volume', 'target': '/var/lib/odoo', 'source': 'odoo-data'})
        original_mkstemp = tempfile.mkstemp
        mocks = {'release_identity': self.identity, 'bound_environment': lambda *args: self.credential,
                 'installed_dms': lambda: False, 'dms_files': lambda *args: {},
                 'public_file': self.public_file, 'capture': self.capture, 'object_capture': self.objects,
                 'snapshots': self.snapshots, 'health': self.health, 'COMPOSE_SHA': activation.digest(b'compose')}
        for name, value in mocks.items():
            patcher = patch.object(activation, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(activation.tempfile, 'mkstemp',
                               side_effect=lambda **kw: original_mkstemp(prefix=kw['prefix'], suffix=kw['suffix'], dir=self.temp.name))
        patcher.start(); self.addCleanup(patcher.stop)
        for method in ('fchown', 'fchmod'):
            patcher = patch.object(activation.os, method, create=True)
            patcher.start(); self.addCleanup(patcher.stop)

    def read_private(self, path, **kwargs):
        if path == self.env_path: return self.env_bytes
        if path == self.shared: return b'synthetic-shared-env'
        return Path(path).read_bytes()

    def public_file(self, path, *args, **kwargs):
        if path.name == 'compose.production.yaml': return b'compose'
        if path.name == 'RELEASE_COMMIT': return activation.SOURCE.encode()
        return b'synthetic-odoo-config'

    def identity(self):
        if self.changed_source: raise activation.Stop('STOP_source_changed')
        return self.release, 'receipt-sha'

    def objects(self, args):
        if args[:3] == ['docker', 'image', 'inspect']:
            return [{'Id': 'same-image-id', 'Config': {'Entrypoint': ['/entrypoint.sh'],
                     'Env': ['PATH=/synthetic/bin'], 'Volumes': {'/var/lib/odoo': {}, '/mnt/extra-addons': {}}}}]
        if args[:3] == ['docker', 'volume', 'inspect']:
            return [{'Name': activation.PROJECT + '-odoo-data', 'Mountpoint': '/synthetic/data',
                     'Driver': 'local', 'Scope': 'local', 'Options': None},
                    {'Name': '0' * 64, 'Mountpoint': '/synthetic/anonymous',
                     'Driver': 'local', 'Scope': 'local', 'Options': None}]
        result = {'name': activation.PROJECT, 'services': {'odoo': copy.deepcopy(self.spec), 'db': {}, 'odoo_data_init': {}},
                  'volumes': {'odoo-data': {'name': activation.PROJECT + '-odoo-data'}}}
        if self.env_bytes == self.old: result['services']['odoo']['environment'].pop(activation.JSON_KEY)
        return result

    def snapshots(self):
        env = ['HOST=db', 'PATH=/synthetic/bin'] + ([activation.JSON_KEY + '=' + self.credential] if self.active else [])
        odoo = {'Id': 'new-odoo' if self.active else 'old-odoo', 'Image': 'same-image-id',
                'Config': {'Image': 'synthetic-image', 'Cmd': self.spec['command'], 'Entrypoint': ['/entrypoint.sh'],
                           'Env': env, 'Labels': {'com.docker.compose.service': 'odoo',
                                                 'com.docker.compose.project.working_dir': str(self.release)}},
                'Mounts': [{'Type': 'bind', 'Source': m['source'], 'Destination': m['target'], 'RW': False}
                           for m in self.spec['volumes'] if m['type'] == 'bind'] + [
                               {'Type': 'volume', 'Name': activation.PROJECT + '-odoo-data',
                                'Source': '/synthetic/data', 'Destination': '/var/lib/odoo', 'RW': True},
                               {'Type': 'volume', 'Name': '0' * 64, 'Source': '/synthetic/anonymous',
                                'Destination': '/mnt/extra-addons', 'RW': True}],
                'State': {'Running': True},
                'HostConfig': {'PortBindings': {'8069/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18069'}],
                                               '8072/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18072'}]}},
                'NetworkSettings': {'Networks': {activation.PROJECT + '-frontend': {}, activation.PROJECT + '-backend': {}}}}
        if self.projection_changed: odoo['Mounts'][0]['RW'] = True
        return {activation.ODOO: odoo, activation.OTHERS[0]: {'Id': self.other_id}, activation.OTHERS[1]: {'Id': 'init-unchanged'}}

    def capture(self, args, **kwargs):
        self.assertEqual(args[-8:], ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', 'odoo'])
        self.events.append('up-new' if self.env_bytes == self.new else 'up-old')
        self.active = self.env_bytes == self.new
        if self.up_failure and self.active: raise activation.Stop('local_command_failed')
        return b''

    def health(self):
        self.health_calls += 1
        self.events.append('health')
        if self.fail_first_activation_health and self.health_calls == 2:
            raise activation.Stop('login_health_failed')

    def restore(self, path, current, old):
        self.events.append('restore-env')
        self.assertEqual((current, old), (activation.digest(self.new), activation.digest(self.old)))
        if self.restore_failure: raise RuntimeError('synthetic-private-details')
        self.env_bytes = self.old

    def test_success_recreates_only_odoo_and_preserves_env(self):
        result = activation.activate(self.value, self.helper)
        self.assertEqual(result['status'], 'activated')
        self.assertEqual(self.events, ['health', 'up-new', 'health'])
        self.assertEqual(self.env_bytes, self.new)
        # Legitimate image-declared anonymous volume is accepted and kept verbatim.
        volume = next(m for m in self.snapshots()[activation.ODOO]['Mounts'] if m['Destination'] == '/mnt/extra-addons')
        self.assertEqual((volume['Type'], volume['Name'], volume['Source']), ('volume', '0' * 64, '/synthetic/anonymous'))

    def test_already_active_is_readonly(self):
        self.active = True
        self.assertEqual(activation.activate(self.value, self.helper)['status'], 'already_active')
        self.assertEqual(self.events, ['health'])

    def test_up_failure_restores_env_before_same_source_recreate(self):
        self.up_failure = True
        with self.assertRaisesRegex(activation.Stop, '^activation_failed_env_restored_same_source_healthy$'):
            activation.activate(self.value, self.helper)
        self.assertEqual(self.events, ['health', 'up-new', 'restore-env', 'up-old', 'health'])
        self.assertEqual(self.env_bytes, self.old)

    def test_health_failure_same_source_recovery_not_go(self):
        self.fail_first_activation_health = True
        with self.assertRaisesRegex(activation.Stop, '^activation_failed_env_restored_same_source_healthy$'):
            activation.activate(self.value, self.helper)
        self.assertEqual(self.events, ['health', 'up-new', 'health', 'restore-env', 'up-old', 'health'])

    def test_unknown_concurrent_source_stops_without_restore_or_restart(self):
        def fail_then_change(args, **kwargs):
            self.events.append('up-new'); self.changed_source = True
            raise activation.Stop('local_command_failed')
        with patch.object(activation, 'capture', fail_then_change):
            with self.assertRaisesRegex(activation.Stop, '^STOP_source_changed$'):
                activation.activate(self.value, self.helper)
        self.assertNotIn('restore-env', self.events)

    def test_unknown_concurrent_env_stops_without_restore(self):
        def fail_then_change(args, **kwargs):
            self.events.append('up-new'); self.env_bytes = b'unknown synthetic state'
            raise activation.Stop('local_command_failed')
        with patch.object(activation, 'capture', fail_then_change):
            with self.assertRaisesRegex(activation.Stop, '^STOP_environment_changed$'):
                activation.activate(self.value, self.helper)
        self.assertNotIn('restore-env', self.events)

    def test_env_restore_failure_stops_before_second_recreate(self):
        self.up_failure = self.restore_failure = True
        with self.assertRaises(RuntimeError): activation.activate(self.value, self.helper)
        self.assertEqual(self.events, ['health', 'up-new', 'restore-env'])

    def test_other_container_change_stops_before_recreate(self):
        original = self.snapshots
        calls = []
        def changed():
            calls.append(1)
            if len(calls) > 1: self.other_id = 'unknown-db-id'
            return original()
        with patch.object(activation, 'snapshots', changed):
            with self.assertRaisesRegex(activation.Stop, '^STOP_other_container_changed$'):
                activation.activate(self.value, self.helper)
        self.assertEqual(self.events, ['health'])

    def test_unknown_initial_extra_mount_never_up_or_restore(self):
        original = self.snapshots
        def extra_mount():
            rows = original()
            rows[activation.ODOO]['Mounts'].append({'Type': 'bind', 'Source': '/synthetic/unknown',
                                                   'Destination': '/unknown', 'RW': False})
            return rows
        with patch.object(activation, 'snapshots', extra_mount):
            with self.assertRaisesRegex(activation.Stop, '^unexpected_runtime_mount$'):
                activation.activate(self.value, self.helper)
        self.assertEqual(self.events, [])

    def test_unknown_initial_extra_env_never_up_or_restore(self):
        original = self.snapshots
        def extra_env():
            rows = original()
            rows[activation.ODOO]['Config']['Env'].append('UNKNOWN_SYNTHETIC=value')
            return rows
        with patch.object(activation, 'snapshots', extra_env):
            with self.assertRaisesRegex(activation.Stop, '^initial_non_fcm_environment_mismatch$'):
                activation.activate(self.value, self.helper)
        self.assertEqual(self.events, [])


if __name__ == '__main__':
    unittest.main()

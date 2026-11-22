import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


spec = importlib.util.spec_from_file_location(
    'preview_boot', Path(__file__).resolve().parents[1] / 'ops/qa/prepare-noorix-preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class BootSequenceTest(unittest.TestCase):
    def run_boot(self, failing_phase=None):
        events = []
        fcntl = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda fd, mode: events.append('lock'))
        def verify(*, promoted, phase='running'):
            events.append(phase)
            if phase == failing_phase:
                raise ValueError('synthetic failure')
        def docker(*args):
            events.append(args)
            if args[0] == 'inspect':
                return json.dumps([{'State': {'Running': False}}, {'State': {'Running': False}}])
            return ''
        info = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0)
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.dict(sys.modules, {'fcntl': fcntl}), patch.object(preview.os, 'O_NOFOLLOW', 0, create=True), \
             patch.object(preview.os, 'open', return_value=23), \
             patch.object(preview.os, 'close'), patch.object(preview.os, 'fstat', return_value=info), \
             patch.object(preview.subprocess, 'run'), patch.object(preview, 'docker', side_effect=docker), \
             patch.object(preview, 'verify_installed', side_effect=verify), \
             patch.object(preview.time, 'sleep'), \
             patch.object(preview.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            try:
                preview.boot_promoted()
            except ValueError:
                if failing_phase is None:
                    raise
        return events

    def test_boot_orders_firewall_static_database_and_app(self):
        events = self.run_boot()
        db_start = ('start', preview.PROJECT + '-db-1')
        app_start = ('start', preview.PROJECT + '-odoo-1')
        self.assertLess(events.index('static'), events.index(db_start))
        self.assertLess(events.index(db_start), events.index('db'))
        self.assertLess(events.index('db'), events.index(app_start))
        self.assertLess(events.index(app_start), events.index('running'))
        self.assertFalse(any(isinstance(x, tuple) and '18134' in str(x) for x in events))

    def test_preflight_failure_never_starts_container(self):
        self.assertFalse(any(isinstance(x, tuple) and x[0] == 'start'
                             for x in self.run_boot('static')))

    def test_failed_database_check_never_starts_app(self):
        events = self.run_boot('db')
        self.assertNotIn(('start', preview.PROJECT + '-odoo-1'), events)

    def test_failed_app_verification_stops_only_new_app(self):
        events = self.run_boot('running')
        self.assertIn(('stop', preview.PROJECT + '-odoo-1'), events)
        self.assertNotIn(('stop', preview.PROJECT + '-db-1'), events)


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.commit = 'a' * 40
        self.source = PurePosixPath('/srv/baseer-qa/releases/aaaaaaaaaaaa-run-123-20261122T123456Z')
        self.current = MagicMock()
        self.current.resolve.return_value = self.source
        self.current.is_symlink.return_value = True
        self.record = {'version': 1, 'database': preview.DATABASE, 'commit': self.commit,
                       'custom_tree': 'b' * 40, 'third_party_tree': 'c' * 40,
                       'report_version': '19.0.1.2.0'}

    def check(self, record=None, exists=True, allow=False):
        record = self.record if record is None else record
        def read(path, *args):
            return self.commit if path.name == 'RELEASE_COMMIT' else json.dumps(record)
        def tree(path):
            return 'b' * 40 if path.name == 'custom_addons' else 'c' * 40
        with patch.object(preview, 'protected_text', side_effect=read), \
             patch.object(preview, '_git_tree', side_effect=tree), \
             patch.object(preview.os.path, 'lexists', return_value=exists):
            return preview._promoted_source(self.current, allow_unrecorded=allow)

    def test_receipt_binds_database_commit_trees_and_version(self):
        self.assertEqual(self.check()[1], self.record)
        for field, value in (('database', 'live'), ('commit', 'b' * 40), ('custom_tree', 'd' * 40),
                             ('third_party_tree', 'd' * 40), ('report_version', 'bad'), ('version', True)):
            with self.subTest(field=field):
                altered = dict(self.record, **{field: value})
                with self.assertRaises(ValueError): self.check(altered)

    def test_new_unrecorded_release_only_accepted_when_recording(self):
        with self.assertRaises(ValueError): self.check(exists=False)
        self.assertIsNone(self.check(exists=False, allow=True)[1]['report_version'])


if __name__ == '__main__':
    unittest.main()

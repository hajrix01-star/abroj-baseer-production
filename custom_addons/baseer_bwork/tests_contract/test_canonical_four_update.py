"""Frozen Git source proof and classifier partitions, without Odoo or Docker."""
import importlib.util
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile


CORE = Path(__file__).resolve().parents[1]
FIXTURE = CORE / 'tests_contract/fixtures/canonical_four_baseline_sources.zip'
FIXTURE_SHA256 = '857110626812b2ea60a2f0a52411932c847d4837f5a8cb310da6ea35ea2f0e34'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


helper = load('bwork_four_source_contract', CORE / 'tools/canonical_four_update.py')
upgrade = load('bwork_four_classifier', CORE / 'tools/canonical_pre_upgrade.py')


class CanonicalFourSourceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = tempfile.TemporaryDirectory(prefix='bwork-four-frozen-git-')
        cls.addClassCleanup(cls.baseline.cleanup)
        cls.frozen = Path(cls.baseline.name)
        # Immutable raw-Git-LF fixture, also executable inside a deployment
        # source archive without .git. Native rehearsal independently archives
        # real baseline81; this fixture is only the standalone contract input.
        raw = FIXTURE.read_bytes()
        assert len(raw) <= 262144 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
        with zipfile.ZipFile(FIXTURE) as archive:
            members = archive.infolist()
            assert len(members) <= 150 and len({member.filename.casefold() for member in members}) == len(members)
            total, files = 0, 0
            for member in members:
                name = member.filename
                assert '\\' not in name and ':' not in name
                assert not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
                path = cls.frozen / name
                assert path.resolve().is_relative_to(cls.frozen.resolve())
                assert not stat.S_ISLNK(member.external_attr >> 16)
                if member.is_dir():
                    assert name in ('custom_addons/', 'custom_addons/baseer_bwork/') or any(
                        name.startswith('custom_addons/' + module + '/') for module in helper.PRESERVED_MODULES)
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                assert name == 'custom_addons/baseer_bwork/canonical_name_map.json' or any(
                    name.startswith('custom_addons/' + module + '/') for module in helper.PRESERVED_MODULES)
                total += member.file_size
                files += 1
                assert total <= 2 * 1024 * 1024 and member.file_size <= 1024 * 1024
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(member))
            assert files == 95

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bwork-four-check-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.addons = self.root / 'custom_addons'
        shutil.copytree(self.frozen / 'custom_addons', self.addons)
        self.core = self.addons / 'baseer_bwork'
        (self.core / 'canonical_four_update_contract.json').write_bytes(
            (CORE / 'canonical_four_update_contract.json').read_bytes())
        scope = patch.object(helper, 'CONTRACT_PATH', self.core / 'canonical_four_update_contract.json')
        scope.start()
        self.addCleanup(scope.stop)

    def test_exact_raw_git_blobs_produce_fixed_proofs(self):
        proofs = helper.verify_preserved_sources(self.addons)
        self.assertEqual([row['module'] for row in proofs], sorted(helper.PRESERVED_MODULES))
        self.assertEqual(helper.contract_sha256(), helper.CONTRACT_SHA256)
        self.assertEqual(proofs[0]['source_sha256'],
                         '94f1a77fd364d34fcdde7268b1d79fa0dcba988f6e2c28ad4320e0db599e0346')
        self.assertEqual(proofs[1]['version'], '19.0.14.0.13')

    def test_modified_missing_extra_and_crlf_source_are_rejected(self):
        path = self.addons / 'baseer_access_roles/models/role_seed.py'
        original = path.read_bytes()
        for changed in (original + b'\n# drift\n', original.replace(b'\n', b'\r\n')):
            with self.subTest(change=len(changed)):
                path.write_bytes(changed)
                with self.assertRaises(helper.CanonicalFourUpdateStopped):
                    helper.verify_preserved_sources(self.addons)
        path.unlink()
        with self.assertRaises(helper.CanonicalFourUpdateStopped):
            helper.verify_preserved_sources(self.addons)
        path.write_bytes(original)
        (path.parent / 'unexpected.py').write_bytes(b'# not reviewed\n')
        with self.assertRaises(helper.CanonicalFourUpdateStopped):
            helper.verify_preserved_sources(self.addons)

    def test_empty_directory_and_oversized_file_fail_closed(self):
        extra = self.addons / 'baseer_access_roles/empty-extra'
        extra.mkdir()
        with self.assertRaises(helper.CanonicalFourUpdateStopped):
            helper.verify_preserved_sources(self.addons)
        extra.rmdir()
        path = self.addons / 'baseer_access_roles/models/role_seed.py'
        path.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        with self.assertRaises(helper.CanonicalFourUpdateStopped):
            helper.verify_preserved_sources(self.addons)

    def test_source_and_contract_symlinks_are_rejected(self):
        path = self.addons / 'baseer_access_roles/models/role_seed.py'
        target = self.root / 'outside.py'
        path.rename(target)
        path.write_bytes(target.read_bytes())
        # Windows symlink creation can need additional OS authority; exercise
        # the same positive detector without requesting that authority here.
        actual = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda value: value == path or actual(value)):
            with self.assertRaisesRegex(helper.CanonicalFourUpdateStopped, 'source_symlink'):
                helper.verify_preserved_sources(self.addons)
        path.unlink()
        target.rename(path)
        with patch.object(Path, 'is_symlink', lambda value: value == helper.CONTRACT_PATH or actual(value)):
            with self.assertRaises(helper.CanonicalFourUpdateStopped):
                helper.contract_sha256()

    def test_contract_or_mapping_tamper_is_rejected_without_override(self):
        path = helper.CONTRACT_PATH
        raw = path.read_bytes()
        value = json.loads(raw)
        value['modules'][0]['source_sha256'] = '0' * 64
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(helper.CanonicalFourUpdateStopped):
            helper.verify_preserved_sources(self.addons)
        path.write_bytes(raw)
        (path.parent / 'canonical_name_map.json').write_bytes(b'{}')
        with self.assertRaises(helper.CanonicalFourUpdateStopped):
            helper.verify_preserved_sources(self.addons)


class ClassifierPartitionCase(unittest.TestCase):
    def classify(self, *, state='complete', requested=None, states=None, versions=None,
                 ledger_valid=True, identity_valid=True, source_valid=True, pending=None, family=None):
        mapping, digest = upgrade.load_mapping()
        states = states or {name: 'installed' for name in helper.INSTALLED_MODULES}
        proofs = [{'module': name, 'version': version, 'source_sha256': 'a' * 64}
                  for name, version in sorted(helper._VERSIONS.items())]
        ledger = {'mapping_sha256': digest, 'status': 'complete' if ledger_valid else 'incomplete',
                  'tables': {'baseer_bwork_message': {'oid': 71}}, 'modules': {'baseer_bwork': 11}}
        class Cursor:
            def execute(self, sql, params=None):
                self.sql = sql
            def fetchone(self):
                if 'ir_config_parameter' in self.sql:
                    return (json.dumps(ledger),)
                if "state IN ('to install','to upgrade','to remove')" in self.sql:
                    return (1,) if pending else None
                return (71 if identity_valid else 72,)
            def fetchall(self):
                return list((versions or helper._VERSIONS).items()) if 'latest_version' in self.sql else list(states.items())
        with patch.object(upgrade, '_safety'), \
             patch.object(upgrade, '_module_state', return_value=family or {'baseer_bwork': (11, 'installed')}), \
             patch.object(upgrade, '_preflight', return_value=state), \
             patch.object(upgrade, '_verify_canonical') as canonical, \
             patch.object(upgrade, '_canonical_four_update', return_value=helper), \
             patch.object(helper, 'verify_preserved_sources', side_effect=(None if source_valid else
                          helper.CanonicalFourUpdateStopped('canonical_four_source_digest')), return_value=proofs), \
             patch.object(helper, 'contract_sha256', return_value=helper.CONTRACT_SHA256):
            result = upgrade.classify(Cursor(), sorted(requested or helper.REQUESTED_MODULES))
            self.assertEqual(canonical.call_count, int(state == 'complete'))
            return result

    def test_completed_exact_four_keeps_full_six_identity_closure(self):
        value = self.classify()
        self.assertEqual(value['update_mode'], helper.MODE)
        self.assertEqual(set(value['upgrade']), helper.REQUESTED_MODULES)
        self.assertEqual(set(value['required_closure']), helper.INSTALLED_MODULES)
        self.assertEqual(set(value['preserved_modules']), helper.PRESERVED_MODULES)
        self.assertEqual(value['install'], [])
        self.assertFalse(value['native_pre_upgrade_required'])

    def test_old_fresh_and_other_requests_keep_full_closure(self):
        for state in ('old', 'fresh'):
            value = self.classify(state=state)
            self.assertNotIn('update_mode', value)
            self.assertEqual(set(value['upgrade']), helper.INSTALLED_MODULES)
            self.assertEqual(value['native_pre_upgrade_required'], state == 'old')
        value = self.classify(requested=helper.REQUESTED_MODULES | {'baseer_access_roles'})
        self.assertNotIn('preserved_modules', value)
        self.assertEqual(set(value['upgrade']), helper.INSTALLED_MODULES)

    def test_completed_route_rejects_incomplete_ledger_and_table_identity_drift(self):
        for kwargs in ({'ledger_valid': False}, {'identity_valid': False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(upgrade.MigrationStopped):
                self.classify(**kwargs)

    def test_pending_missing_extra_or_unrequested_install_never_falls_back(self):
        base = {name: 'installed' for name in helper.INSTALLED_MODULES}
        cases = [{**base, name: 'to upgrade'} for name in sorted(helper.INSTALLED_MODULES)] + [
                 {key: value for key, value in base.items() if key != 'baseer_access_roles'},
                 {**base, 'baseer_bwork_permission_guards': 'installed'},
                 {**base, 'baseer_bwork_dashboard': 'uninstalled'}]
        for states in cases:
            with self.subTest(states=states), self.assertRaises(upgrade.MigrationStopped):
                self.classify(states=states)

    def test_unrelated_global_pending_work_and_unknown_active_family_stop(self):
        for state in ('to install', 'to upgrade', 'to remove'):
            with self.subTest(global_pending=state), self.assertRaisesRegex(
                    upgrade.MigrationStopped, 'canonical_four_global_pending'):
                self.classify(pending=state)
        for state in ('installed', 'to install', 'to upgrade', 'to remove'):
            family = {'baseer_bwork': (11, 'installed'), 'baseer_bwork_unknown': (99, state)}
            with self.subTest(unknown_family=state), self.assertRaisesRegex(
                    upgrade.MigrationStopped, 'canonical_four_unknown_family'):
                self.classify(family=family)
        value = self.classify(family={'baseer_bwork': (11, 'installed'),
                                      'baseer_bwork_unknown': (99, 'uninstalled')})
        self.assertEqual(value['update_mode'], helper.MODE)

    def test_version_and_actual_source_drift_stop_not_full_upgrade_fallback(self):
        for kwargs in ({'versions': {**helper._VERSIONS, 'baseer_access_roles': '19.0.1.0.19'}},
                       {'source_valid': False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(upgrade.MigrationStopped):
                self.classify(**kwargs)


if __name__ == '__main__':
    unittest.main()

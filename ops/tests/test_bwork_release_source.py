"""Pure source/plan tests. No Docker, operational data or host writes."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_source', ROOT / 'ops/lib/bwork_release_source.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class SourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bwork-source-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate, self.frozen = self.root / 'stage', self.root / 'guard'
        raw = (ROOT / support.CORE / 'canonical_name_map.json').read_bytes()
        for parent in (self.candidate, self.frozen):
            core = parent / support.CORE
            core.mkdir(parents=True)
            (core / 'canonical_name_map.json').write_bytes(raw)
            (core / '__manifest__.py').write_text("{'version':'fixture'}")
        self.pairs, self.digest = support.mapping(self.frozen)
        self.approved = {'baseer_bwork', 'baseer_bwork_admin'}

    def test_prepare_only_removes_fixed_old_addon_source_in_private_copy(self):
        for row in self.pairs:
            target = self.candidate / 'custom_addons' / row['old']
            target.mkdir()
            (target / 'sentinel').write_text('source only')
        unrelated = self.candidate / 'custom_addons/unrelated'
        unrelated.mkdir()
        self.assertEqual(support.prepare(self.candidate, self.frozen, self.approved), self.digest)
        self.assertTrue(unrelated.exists())
        self.assertTrue((self.frozen / support.CORE).exists())
        self.assertTrue(all(not (self.candidate / 'custom_addons' / row['old']).exists() for row in self.pairs))

    def test_tampered_or_missing_actual_core_stops_before_preparing(self):
        manifest = self.candidate / support.CORE / '__manifest__.py'
        manifest.write_text('tampered')
        with self.assertRaisesRegex(SystemExit, 'frozen_core_mismatch'):
            support.prepare(self.candidate, self.frozen, self.approved)
        manifest.unlink()
        with self.assertRaisesRegex(SystemExit, 'frozen_core_mismatch'):
            support.prepare(self.candidate, self.frozen, self.approved)

    def test_mixed_policy_and_same_source_root_stop(self):
        with self.assertRaisesRegex(SystemExit, 'mixed_module_policy'):
            support.prepare(self.candidate, self.frozen, self.approved | {'baseer_bchat'})
        with self.assertRaisesRegex(SystemExit, 'invalid_source_roots'):
            support.prepare(self.frozen, self.frozen, self.approved)

    def plan(self, kind='old-installed'):
        return {'schema_version': 1, 'mapping_sha256': self.digest, 'classification': kind,
                'install': [], 'upgrade': sorted(self.approved), 'required_closure': sorted(self.approved),
                'native_pre_upgrade_required': kind == 'old-installed'}

    def test_installed_old_module_uses_canonical_upgrade_not_install(self):
        result = support.check_plan(self.frozen, self.approved, self.plan())
        self.assertIn('NATIVE yes', result)
        self.assertIn('UPGRADE baseer_bwork', result)
        self.assertNotIn('INSTALL', result)

    def test_fresh_is_explicit_install_without_forced_base_upgrade(self):
        plan = self.plan('fresh')
        plan['install'], plan['upgrade'] = plan['upgrade'], []
        result = support.check_plan(self.frozen, self.approved, plan)
        self.assertIn('NATIVE no', result)
        self.assertIn('INSTALL baseer_bwork', result)
        self.assertNotIn('UPGRADE', result)

    def test_scope_expansion_unknown_or_overlapping_plan_fails(self):
        for field, value in (('required_closure', ['baseer_bwork', 'baseer_access_roles']),
                             ('upgrade', ['baseer_bwork', 'unapproved']),
                             ('install', ['baseer_bwork']),
                             ('mapping_sha256', 'tampered'),
                             ('native_pre_upgrade_required', False)):
            plan = self.plan()
            plan[field] = value
            with self.subTest(field=field), self.assertRaises(SystemExit):
                support.check_plan(self.frozen, self.approved, plan)

    def test_postconditions_require_installed_canonical_not_workflow_success(self):
        with self.assertRaisesRegex(SystemExit, 'postcondition_not_installed'):
            support.check_plan(self.frozen, self.approved, self.plan(), verified=True)
        support.check_plan(self.frozen, self.approved, self.plan('canonical-ready'), verified=True)

    def test_first_transition_requires_explicit_post_loader_lineage_attestation(self):
        plan = self.plan('canonical-ready')
        with self.assertRaisesRegex(SystemExit, 'first_transition_not_attested'):
            support.check_plan(self.frozen, self.approved, plan, transition=True)
        plan.update(transition_lineage='PASS', mode='old-installed')
        support.check_plan(self.frozen, self.approved, plan, transition=True)

    def test_late_failure_fixture_is_fenced_and_fails_only_at_expected_synthetic_seam(self):
        path = ROOT / 'ops/tests/fixtures/bwork_canonical_failure/hooks.py'
        fixture_spec = importlib.util.spec_from_file_location('bwork_fixed_failure_fixture', path)
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        class Environment:
            cr = SimpleNamespace(dbname='bwork_canonical_ci_fixture')
            def __contains__(self, key):
                return key == 'baseer.bwork.service'
            def __getitem__(self, key):
                self_model = SimpleNamespace()
                self_model.sudo = lambda: self_model
                self_model.search = lambda domain: SimpleNamespace(state='installed')
                return self_model
        with patch.dict(os.environ, {'BWORK_CANONICAL_SYNTHETIC': '0'}):
            with self.assertRaisesRegex(RuntimeError, '^BWORK_CANONICAL_FAILURE_FIXTURE_FORBIDDEN$'):
                fixture.post_init_hook(Environment())
        with patch.dict(os.environ, {'BWORK_CANONICAL_SYNTHETIC': '1'}):
            with self.assertRaisesRegex(RuntimeError, '^BWORK_CANONICAL_FAILURE_DATABASE_FORBIDDEN$'):
                fixture.post_init_hook(SimpleNamespace(cr=SimpleNamespace(dbname='not_a_fixture')))
            with self.assertRaisesRegex(RuntimeError, '^BWORK_CANONICAL_EXPECTED_LATE_MODULE_FAILURE$'):
                fixture.post_init_hook(Environment())

    def test_both_wrappers_keep_same_fixed_source_and_native_boundaries(self):
        blocks = []
        for relative in ('ops/qa/baseer-qa-deploy', 'ops/production/baseer-production-deploy'):
            value = (ROOT / relative).read_text()
            start, end = value.index('bwork_source_guard()'), value.index('\nbwork_classify()')
            blocks.append(value[start:end])
            self.assertIn('archive --format=tar "$commit" .github android "custom_addons/$core" ops', value)
            self.assertIn('"$bwork_guard_root/custom_addons/$core/tools/release_guard.py"', value)
            self.assertNotIn('release_guard.py" --runtime', value)
            self.assertIn('--pre-upgrade-scripts=/mnt/baseer-addons/baseer_bwork/tools/canonical_pre_upgrade.py', value)
            self.assertLess(value.index('bwork_classify "$release"'), value.index('\ndatabase_mutated=1\n'))
            self.assertLess(value.index('\nbwork_verify "$release"'), value.index('\nwait_for_login\n'))
        self.assertEqual(blocks[0], blocks[1])


class FrozenArchiveExecutionTests(unittest.TestCase):
    """Execute the actual wrapper function against a disposable local Git repo."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bwork-archive-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = self.root / 'repository'
        self.candidate = self.root / '.stage-fixture/source'
        self.repository.mkdir()
        self.candidate.mkdir(parents=True)
        self.bash = os.environ.get('BWORK_TEST_BASH') or shutil.which('bash')
        if os.name == 'nt' and not os.environ.get('BWORK_TEST_BASH'):
            self.bash = 'C:/Program Files/Git/bin/bash.exe'
        self.assertTrue(self.bash and Path(self.bash).is_file(), 'Bash is required, not an optional skipped contract')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repository), *args],
                                       text=True, stderr=subprocess.PIPE).strip()

    def fixture(self, *, guard_failure=False, missing_archive=False, tampered=False):
        for name in ('.github', 'android', 'ops/lib', support.CORE):
            (self.repository / name).mkdir(parents=True, exist_ok=True)
        (self.repository / '.github/sentinel').write_text('fixture')
        (self.repository / 'android/sentinel').write_text('fixture')
        core = self.repository / support.CORE
        (core / 'tools').mkdir()
        (core / 'tools/release_guard.py').write_text('import sys\nsys.exit(' + ('3' if guard_failure else '0') + ')\n')
        (core / '__manifest__.py').write_text("{'version':'fixture'}")
        shutil.copyfile(ROOT / support.CORE / 'canonical_name_map.json', core / 'canonical_name_map.json')
        shutil.copyfile(ROOT / 'ops/lib/bwork_release_source.py', self.repository / 'ops/lib/bwork_release_source.py')
        shutil.copytree(core, self.candidate / support.CORE)
        if missing_archive:
            (self.repository / '.github/sentinel').unlink()
            (self.repository / '.github').rmdir()
        if tampered:
            (self.candidate / support.CORE / '__manifest__.py').write_text('tampered actual staged module')
        self.git('init', '--quiet')
        self.git('add', '--all')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '--quiet', '-m', 'synthetic frozen guard fixture')
        return self.git('rev-parse', 'HEAD')

    def run_guard(self, commit):
        wrapper = (ROOT / 'ops/qa/baseer-qa-deploy').read_text()
        block = wrapper[wrapper.index('bwork_source_guard()'):wrapper.index('\nbwork_classify()')]
        def quote(path):
            return shlex.quote(Path(path).as_posix())
        script = ('set -Eeuo pipefail\n'
                  'die() { printf "STOP:%s\\n" "$*" >&2; exit 64; }\n'
                  'python3() { ' + quote(sys.executable) + ' "$@"; }\n'
                  'stage=' + quote(self.candidate.parent) + '\n'
                  'commit=' + shlex.quote(commit) + '\n'
                  'APPROVED_MODULES=(baseer_bwork)\npolicy_modules=baseer_bwork\n' + block + '\n'
                  'bwork_source_guard ' + quote(self.candidate) + ' ' + quote(self.repository) + '\n'
                  'printf "REACHED_DB_BOUNDARY\\n"\n')
        return subprocess.run([self.bash, '-s'], input=script, text=True, encoding='utf-8',
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def test_actual_frozen_archive_success_reaches_only_next_boundary(self):
        result = self.run_guard(self.fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('REACHED_DB_BOUNDARY', result.stdout)

    def test_actual_archive_missing_required_root_stops_before_database(self):
        result = self.run_guard(self.fixture(missing_archive=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('REACHED_DB_BOUNDARY', result.stdout)

    def test_actual_archived_guard_failure_stops_before_database(self):
        result = self.run_guard(self.fixture(guard_failure=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('frozen cumulative BWork source guard rejected', result.stderr)
        self.assertNotIn('REACHED_DB_BOUNDARY', result.stdout)

    def test_actual_overlay_tamper_stops_before_database(self):
        result = self.run_guard(self.fixture(tampered=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('frozen_core_mismatch', result.stderr)
        self.assertNotIn('REACHED_DB_BOUNDARY', result.stdout)


if __name__ == '__main__':
    unittest.main()

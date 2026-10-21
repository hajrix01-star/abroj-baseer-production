"""Pure source/plan tests. No Docker, operational data or host writes."""
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
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


class CanonicalFourPlanTests(unittest.TestCase):
    """Execute the staged verifier against real, pinned consumer source bytes."""

    def setUp(self):
        SourceBoundaryTests.setUp(self)
        # The protected host guard intentionally has no Git checkout. Keep
        # these tests self-contained, using exact public source-test bytes.
        archive = (ROOT / support.CORE / 'tests_contract/fixtures/canonical_four_baseline_sources.zip').read_bytes()
        self.assertEqual(hashlib.sha256(archive).hexdigest(),
                         '857110626812b2ea60a2f0a52411932c847d4837f5a8cb310da6ea35ea2f0e34')
        self.assertLessEqual(len(archive), 262144)
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            members = source.infolist()
            self.assertLessEqual(len(members), 150)
            self.assertLessEqual(sum(member.file_size for member in members), 2 * 1024 * 1024)
            self.assertEqual(len({member.filename.casefold() for member in members}), len(members))
            for member in members:
                name = member.filename
                self.assertNotIn('\\', name)
                self.assertNotIn(':', name)
                self.assertNotIn('..', name.split('/'))
                self.assertFalse(name.startswith('/'))
                self.assertNotEqual((member.external_attr >> 16) & 0o170000, 0o120000)
                self.assertTrue(name in ('custom_addons/', support.CORE + '/',
                                         support.CORE + '/canonical_name_map.json')
                                or name.startswith(('custom_addons/baseer_access_roles/',
                                                    'custom_addons/baseer_procurement_requests/')))
            source.extractall(self.candidate)
        core = self.candidate / support.CORE
        (core / 'tools').mkdir(exist_ok=True)
        for relative in ('tools/canonical_four_update.py', 'canonical_four_update_contract.json'):
            shutil.copyfile(ROOT / support.CORE / relative, core / relative)
        helper_spec = importlib.util.spec_from_file_location('four_plan_fixture', core / 'tools/canonical_four_update.py')
        self.helper = importlib.util.module_from_spec(helper_spec)
        # Fixture construction must not pre-create the artifact whose absence
        # the actual writable-stage check_plan regression below proves.
        with patch.object(sys, 'dont_write_bytecode', True):
            helper_spec.loader.exec_module(self.helper)
        self.approved = self.helper.REQUESTED_MODULES
        _, self.digest = support.mapping(self.candidate)

    def four_plan(self):
        return dict(schema_version=1, mapping_sha256=self.digest, classification='canonical-ready',
                    native_pre_upgrade_required=False, update_mode=self.helper.MODE,
                    install=[], upgrade=sorted(self.helper.REQUESTED_MODULES),
                    required_closure=sorted(self.helper.INSTALLED_MODULES),
                    preserved_modules=sorted(self.helper.PRESERVED_MODULES),
                    preserved_sources=self.helper.verify_preserved_sources(self.candidate / 'custom_addons'),
                    source_contract_sha256=self.helper.contract_sha256())

    def test_fixed_canonical_four_upgrades_only_four_and_retains_full_closure(self):
        result = support.check_plan(self.candidate, self.approved, self.four_plan(), verified=True)
        self.assertEqual(result.splitlines()[0], 'NATIVE no')
        self.assertEqual(set(result.splitlines()[1:]), {'UPGRADE ' + name for name in self.approved})
        self.assertNotIn('UPGRADE baseer_access_roles', result)
        self.assertNotIn('UPGRADE baseer_procurement_requests', result)
        self.assertNotIn('INSTALL ', result)

    def test_actual_repeated_plan_and_verified_calls_leave_writable_source_exact(self):
        helper_path = self.candidate / support.CORE / 'tools/canonical_four_update.py'
        frozen = self.root / 'repeat-frozen'
        shutil.copytree(self.candidate, frozen)
        wrapper = (ROOT / 'ops/production/baseer-production-deploy').read_text()
        start = wrapper.index('bwork_recovery_source_guard()')
        end = wrapper.index('\nbwork_recovery_schema_hash()', start)
        guard = wrapper[start:end].split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        # Control: the former loader really writes a cache in a writable tree
        # without caller-level bytecode prevention. Keep it outside candidate.
        control = self.root / 'old-producer'
        control.mkdir()
        control_helper = control / 'canonical_four_update.py'
        control_helper.write_bytes(helper_path.read_bytes())
        with patch.dict(os.environ), patch.object(sys, 'dont_write_bytecode', False):
            os.environ.pop('PYTHONDONTWRITEBYTECODE', None)
            old_spec = importlib.util.spec_from_file_location('old_four_plan_producer', control_helper)
            old_spec.loader.exec_module(importlib.util.module_from_spec(old_spec))
            self.assertTrue(Path(importlib.util.cache_from_source(str(control_helper))).is_file())
            before = support.tree(self.candidate)
            for cycle in range(2):
                with self.subTest(cycle=cycle):
                    self.assertEqual(support.prepare(self.candidate, frozen, self.approved), self.digest)
                    for verified in (False, True):
                        result = support.check_plan(self.candidate, self.approved, self.four_plan(), verified=verified)
                        self.assertIn('NATIVE no', result)
                        self.assertEqual(support.tree(self.candidate), before)
                        self.assertFalse(list(self.candidate.rglob('__pycache__')))
                    # The checked candidate is now the next update's old
                    # release: execute the real inline comparison unchanged,
                    # with a non-ac9 identity and no legacy-cache exception.
                    with patch.object(sys, 'argv', ['bwork-source-guard',
                                      str(self.candidate / support.CORE), str(frozen / support.CORE), '1' * 40]):
                        exec(compile(guard, str(ROOT / 'ops/production/baseer-production-deploy'), 'exec'),
                             {'__name__': '__main__'})
                self.assertEqual(support.tree(self.candidate), before)
                self.assertFalse(list(self.candidate.rglob('__pycache__')))

    def test_actual_check_plan_ignores_valid_poisoned_bytecode_and_keeps_it_unchanged(self):
        # A valid timestamp/size header makes the old import loader consume
        # this sentinel, proving that -B alone would not prevent cache reads.
        from importlib._bootstrap_external import _code_to_timestamp_pyc
        helper_path = self.candidate / support.CORE / 'tools/canonical_four_update.py'
        cache = Path(importlib.util.cache_from_source(str(helper_path)))
        cache.parent.mkdir()
        metadata = helper_path.stat()
        code = compile("raise RuntimeError('POISONED_FOUR_PLAN_CACHE')\n", str(helper_path), 'exec')
        cache.write_bytes(_code_to_timestamp_pyc(code, int(metadata.st_mtime), metadata.st_size))
        with patch.dict(os.environ), patch.object(sys, 'dont_write_bytecode', False):
            os.environ.pop('PYTHONDONTWRITEBYTECODE', None)
            old_spec = importlib.util.spec_from_file_location('poisoned_old_four_plan_loader', helper_path)
            with self.assertRaisesRegex(RuntimeError, '^POISONED_FOUR_PLAN_CACHE$'):
                old_spec.loader.exec_module(importlib.util.module_from_spec(old_spec))
            before = support.tree(self.candidate)
            for verified in (False, True):
                result = support.check_plan(self.candidate, self.approved, self.four_plan(), verified=verified)
                self.assertIn('NATIVE no', result)
                self.assertEqual(support.tree(self.candidate), before)

    def test_fixed_route_rejects_forged_partition_mode_and_claimed_source(self):
        for field, replacement in (
                ('update_mode', 'allow-any-skip'), ('classification', 'fresh'),
                ('classification', 'old-installed'), ('upgrade', ['baseer_bwork']),
                ('required_closure', sorted(self.approved)), ('install', ['baseer_bwork']),
                ('preserved_modules', ['baseer_access_roles']), ('preserved_sources', []),
                ('source_contract_sha256', '0' * 64)):
            with self.subTest(field=field, value=replacement):
                plan = self.four_plan()
                plan[field] = replacement
                with self.assertRaises(SystemExit):
                    support.check_plan(self.candidate, self.approved, plan)

    def test_staged_skipped_source_tamper_is_not_authorized_by_plan_proof(self):
        plan = self.four_plan()
        manifest = self.candidate / 'custom_addons/baseer_access_roles/__manifest__.py'
        manifest.write_bytes(manifest.read_bytes() + b'\n# unexpected change\n')
        with self.assertRaisesRegex(SystemExit, 'preserved_source_verification_failed'):
            support.check_plan(self.candidate, self.approved, plan)

    def test_preserved_claims_require_fixed_mode_and_exact_policy(self):
        plan = self.four_plan()
        del plan['update_mode']
        with self.assertRaisesRegex(SystemExit, 'preserved_without_fixed_mode'):
            support.check_plan(self.candidate, self.approved, plan)
        for approved in (self.approved - {'baseer_bwork_admin'},
                         self.approved | {'baseer_access_roles'},
                         self.approved | {'baseer_sales_dashboard'}):
            with self.subTest(approved=approved), self.assertRaises(SystemExit):
                support.check_plan(self.candidate, approved, self.four_plan())

    def test_fixed_update_cannot_attest_first_legacy_transition(self):
        with self.assertRaisesRegex(SystemExit, 'invalid_canonical_update_mode'):
            support.check_plan(self.candidate, self.approved, self.four_plan(), transition=True)


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

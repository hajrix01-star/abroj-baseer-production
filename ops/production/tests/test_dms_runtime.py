"""Linux/root production-wrapper rehearsal using synthetic files and fake Docker.

No Odoo database, Docker daemon, QA or LIVE service is contacted.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_google_runtime as google_runtime


FAKE_DOCKER = google_runtime.FAKE_DOCKER
OPS = google_runtime.OPS


DMS_MODULES = ('baseer_dms_trial', 'baseer_dms_bill_link', 'baseer_dms_departments')
RUNTIME_FILE = 'config/dms-runtime.compose.json'
RUNTIME_STAMP = 'config/dms-runtime.sha256'
OCA_PATH = '/mnt/third-party-addons/oca_dms_19'


def shell_function(source, name):
    """Use the actual small policy functions, not a reimplementation."""
    marker = name + '() {\n'
    start = source.index(marker)
    end = source.index('\n}\n', start) + 3
    return source[start:end]


DMS_FAKE_DOCKER = FAKE_DOCKER.replace(
    'a = sys.argv[1:]\n',
    'a = sys.argv[1:]\n'
    'stdin_payload = sys.stdin.read() if (a[0] == "exec" and "-i" in a) else ""\n',
).replace(
    'if a[0] == "exec":\n    command = a[-1]\n',
    r'''marker = pathlib.Path(os.environ["CALL_LOG"] + ".upgraded")
if a[0] == "exec":
    command = a[-1]
    if "DMS_PROTECTED_ORIGINALS" in stdin_payload:
        counter = pathlib.Path(os.environ["CALL_LOG"] + ".snapshots")
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        snapshot = {"attachments": {"n": 2, "hash": "original"}, "versions": {"n": 1, "hash": "original"}}
        changed = os.environ.get("FAIL_ORIGINAL")
        if count > 1 and changed: snapshot[changed]["hash"] = "changed"
        print(json.dumps(snapshot, sort_keys=True))
        sys.exit(0)
    if "SELECT state" in command and any("name = '" + m + "'" in command for m in
            ("dms", "baseer_dms_trial", "baseer_dms_bill_link", "baseer_dms_departments")):
        if os.environ.get("FAIL_DMS_QUERY"): sys.exit(1)
        print("installed" if marker.exists() else os.environ.get("DMS_STATE", "uninstalled"))
        sys.exit(0)
    if "SELECT name" in command and "ir_module_module" in command:
        print(os.environ.get("INSTALLED_MODULES", ""))
        sys.exit(0)
if a[0] == "compose":
    command = a[-1]
    if "config" in a and "json" in a:
        if os.environ.get("FAIL_CONFIG"):
            print("FAKE_SECRET_MUST_NOT_ESCAPE", file=sys.stderr)
            sys.exit(1)
        effective = json.loads(os.environ["OLD_COMMAND"])
        for override in record["overrides"]:
            if override.lstrip().startswith("{"):
                effective = json.loads(override)["services"]["odoo"]["command"]
        print(json.dumps({"services": {"odoo": {"command": effective, "volumes": [
            {"target": "/mnt/third-party-addons", "read_only": True,
             "source": str(project / "third_party_addons")}
        ]}}}))
        sys.exit(0)
    if "DMS_PRODUCTION_PHASE=preflight" in command:
        if os.environ.get("FAIL_PREFLIGHT"): sys.exit(1)
        print("DMS_PRODUCTION_PREFLIGHT=GO")
        sys.exit(0)
    if "DMS_PRODUCTION_PHASE=setup" in command:
        if os.environ.get("FAIL_SETUP"): sys.exit(1)
        print("DMS_PRODUCTION_SETUP=INVALID" if os.environ.get("MALFORMED_SETUP") else "DMS_PRODUCTION_SETUP=GO")
        sys.exit(0)
    if "run" in a and (" -u " in command or " -i " in command):
        marker.touch()
if a[0] == "exec":
    command = a[-1]
''',
)


@unittest.skipUnless(hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'production ownership checks require Linux root')
class DmsRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing bounded fake fixture without inheriting/repeating
        # its Google test cases or replacing any wrapper safety checks.
        google_runtime.GoogleRuntimeTests.setUp(self)
        self.policy_dir = self.base / 'policies'
        self.policy_dir.mkdir()
        self.reviewed = self.base / 'reviewed'
        self.reviewed.mkdir()
        for module in DMS_MODULES:
            target = self.reviewed / 'custom_addons' / module
            target.mkdir(parents=True)
            shutil.copyfile(OPS.parents[1] / 'custom_addons' / module / '__manifest__.py',
                            target / '__manifest__.py')
        native = self.reviewed / 'third_party_addons' / 'oca_dms_19'
        (native / 'dms').mkdir(parents=True)
        shutil.copyfile(OPS.parents[1] / 'third_party_addons/oca_dms_19/dms/__manifest__.py',
                        native / 'dms/__manifest__.py')
        shutil.copyfile(OPS.parents[1] / 'third_party_addons/oca_dms_19/PROVENANCE.md',
                        native / 'PROVENANCE.md')
        (self.reviewed / 'ops/production').mkdir(parents=True)
        shutil.copyfile(OPS / 'dms-private-setup.py', self.reviewed / 'ops/production/dms-private-setup.py')
        self.original_command = [
            'odoo', '--config=/etc/odoo/odoo.conf',
            '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,'
            '/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
            '--database=baseer_prod', '--db-filter=^baseer_prod$', '--no-database-list',
            '--http-port=8069', '--log-level=warn',
        ]
        (self.bin / 'docker').write_text(DMS_FAKE_DOCKER)

    def seed_old_runtime(self):
        shutil.copytree(self.reviewed / 'third_party_addons', self.old / 'third_party_addons')
        shutil.copytree(self.reviewed / 'custom_addons', self.old / 'custom_addons', dirs_exist_ok=True)
        command = self.expected_command()
        runtime = self.old / RUNTIME_FILE
        runtime.write_text(json.dumps({'services': {'odoo': {'command': command}}}))
        runtime.chmod(0o600)
        stamp = self.old / RUNTIME_STAMP
        stamp.write_text(hashlib.sha256(runtime.read_bytes()).hexdigest() + '  ' + RUNTIME_FILE + '\n')
        stamp.chmod(0o600)
        return runtime.read_bytes(), stamp.read_bytes()

    def expected_command(self):
        command = self.original_command.copy()
        command[2] += ',' + OCA_PATH
        return command

    def execute(self, modules=DMS_MODULES, third_party='dms', **flags):
        policy = self.policy_dir / 'fixture-release.env'
        policy.write_text(
            f'RELEASE_ID=fixture-release\nCOMMIT={"b" * 40}\nMODULES={",".join(modules)}\n'
            f'THIRD_PARTY_MODULES={third_party}\nPOLICY_REVISION={"c" * 40}\nAPPROVED_RUN_ID=1\n'
        )
        policy.chmod(0o600)
        source = (OPS / 'baseer-production-deploy').read_text()
        for before, after in (
            ('readonly BASE=/srv/abroj-baseer-production', f'readonly BASE={self.base}'),
            ('readonly POLICY_DIR=/etc/baseer-production/release-policies', f'readonly POLICY_DIR={self.policy_dir}'),
            ('readonly LOCK_FILE=/var/lock/baseer-production-deploy.lock', f'readonly LOCK_FILE={self.base}/deploy.lock'),
            ('mktemp /run/baseer-google-odoo.XXXXXXXX.yaml', f'mktemp {self.base}/baseer-google-odoo.XXXXXXXX.yaml'),
        ):
            source = source.replace(before, after)
        fixtures = f'''
curl() {{ return 0; }}
sleep() {{ :; }}
df() {{ printf 'Avail\\n999999999\\n'; }}
verify_source_identity() {{ :; }}
fetch_reviewed_source() {{
    mkdir -p "$stage/source"
    cp -a "$old_release/." "$stage/source/"
    cp -a "{self.reviewed}/." "$stage/source/"
    rm -f "$stage/source/.env" "$stage/source/config/odoo.conf"
}}
'''
        source = source.replace('\nrequire_root\nvalidate_arguments',
                                fixtures + '\nrequire_root\nvalidate_arguments', 1)
        script = self.base / 'deploy-dms-fixture'
        script.write_text(source)
        env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                   CALL_LOG=str(self.log), GOOGLE_COUNT='2',
                   OLD_COMMAND=json.dumps(self.original_command))
        env.update({key: str(value) for key, value in flags.items()})
        result = subprocess.run(['bash', str(script), 'fixture-release', '1'], env=env,
                                text=True, capture_output=True, timeout=25)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        self.assertNotIn('fixture-secret', result.stdout + result.stderr)
        self.assertNotIn('FAKE_SECRET_MUST_NOT_ESCAPE', result.stdout + result.stderr)
        self.assertFalse(list(self.base.glob('baseer-google-odoo.*.yaml')))
        return result, calls

    def assert_rollback_pair(self, result, calls):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.base / 'current').resolve(), self.old)
        self.assertTrue(any('pg_restore' in ' '.join(call['argv']) for call in calls))
        self.assertTrue(any('tar -xf /backup/filestore-baseer_prod.tar' in ' '.join(call['argv']) for call in calls))
        self.assertTrue(any(call['argv'][0] == 'compose' and 'up' in call['argv']
                            and call['project'] == str(self.old) for call in calls))
        results = list((self.base / 'backups').glob('*/result.env'))
        self.assertEqual(len(results), 1)
        self.assertIn('LIVE=ROLLED_BACK', results[0].read_text())

    def assert_runtime_compose(self, calls, old_has_runtime=False):
        compose = [call for call in calls if call['argv'][0] == 'compose']
        self.assertTrue(compose)
        for call in compose:
            paths = call['override_paths']
            persistent = [index for index, path in enumerate(paths) if path.endswith(RUNTIME_FILE)]
            expect_runtime = old_has_runtime or call['project'] != str(self.old)
            self.assertEqual(len(persistent), int(expect_runtime))
            for index in persistent:
                self.assertEqual(call['override_modes'][index], '0o600')
                self.assertEqual(call['override_owners'][index], 0)
                payload = json.loads(call['overrides'][index])
                self.assertEqual(payload, {'services': {'odoo': {'command': self.expected_command()}}})
                self.assertEqual(paths[index], str(Path(call['project']) / RUNTIME_FILE))
            google = [text for text in call['overrides'] if not text.lstrip().startswith('{')]
            self.assertEqual(google, [f'services:\n  odoo:\n    env_file:\n      - "{self.secret}"\n'])
            self.assertNotIn('GOOGLE_', call['base_env'])
            self.assertEqual(call['argv'][call['argv'].index('--env-file') + 1],
                             call['project'] + '/.env')
        return compose

    def test_first_install_generates_private_stamped_runtime_and_disables_demo(self):
        result, calls = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_runtime_compose(calls)
        release = (self.base / 'current').resolve()
        runtime, stamp = release / RUNTIME_FILE, release / RUNTIME_STAMP
        self.assertEqual(runtime.stat().st_mode & 0o777, 0o600)
        self.assertEqual(stamp.stat().st_mode & 0o777, 0o600)
        self.assertEqual(runtime.stat().st_uid, 0)
        self.assertEqual(stamp.stat().st_uid, 0)
        self.assertEqual(stamp.read_text().split()[0], hashlib.sha256(runtime.read_bytes()).hexdigest())
        self.assertEqual((release / 'RELEASE_COMMIT').read_text().strip(), 'b' * 40)
        upgrades = [call for call in calls if call['argv'][0] == 'compose' and 'run' in call['argv']
                    and ' -i ' in call['argv'][-1]]
        self.assertEqual(len(upgrades), 1)
        self.assertIn('--without-demo=True', upgrades[0]['argv'][-1])
        for module in (*DMS_MODULES, 'dms'):
            self.assertIn(module, upgrades[0]['argv'][-1])
        self.assertTrue(any('DMS_PRODUCTION_PHASE=setup' in ' '.join(call['argv']) for call in calls))

    def test_upgrade_failure_restores_old_release_without_introducing_new_runtime(self):
        result, calls = self.execute(FAIL_UPGRADE=1)
        self.assert_rollback_pair(result, calls)
        self.assert_runtime_compose(calls)
        self.assertFalse((self.old / RUNTIME_FILE).exists())

    def test_existing_runtime_is_preserved_on_subsequent_non_dms_release_and_rollback(self):
        for fail_upgrade in (False, True):
            with self.subTest(fail_upgrade=fail_upgrade):
                original_runtime, original_stamp = self.seed_old_runtime()
                flags = {'DMS_STATE': 'installed'}
                if fail_upgrade: flags['FAIL_UPGRADE'] = 1
                result, calls = self.execute(modules=('baseer_hr_services',), third_party='', **flags)
                if fail_upgrade:
                    self.assert_rollback_pair(result, calls)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    release = (self.base / 'current').resolve()
                    self.assertNotEqual(release, self.old)
                    self.assertEqual(json.loads((release / RUNTIME_FILE).read_text()),
                                     {'services': {'odoo': {'command': self.expected_command()}}})
                self.assert_runtime_compose(calls, old_has_runtime=True)
                self.assertEqual((self.old / RUNTIME_FILE).read_bytes(), original_runtime)
                self.assertEqual((self.old / RUNTIME_STAMP).read_bytes(), original_stamp)
                if not fail_upgrade:
                    self.temp.cleanup()
                    self.setUp()

    def test_source_closure_and_preflight_prerequisites_fail_before_stop(self):
        scenarios = (
            {'missing': self.reviewed / 'third_party_addons/oca_dms_19/dms/__manifest__.py'},
            {'missing': self.reviewed / 'third_party_addons/oca_dms_19/PROVENANCE.md'},
            {'FAIL_PREFLIGHT': 1}, {'FAIL_DMS_QUERY': 1},
            {'INSTALLED_MODULES': 'baseer_missing_source'},
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                removed = scenario.get('missing')
                content = removed.read_bytes() if removed else None
                if removed: removed.unlink()
                flags = {key: value for key, value in scenario.items() if key != 'missing'}
                try:
                    result, calls = self.execute(**flags)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(any('stop' in call['argv'] for call in calls))
                    self.assertEqual((self.base / 'current').resolve(), self.old)
                finally:
                    if removed: removed.write_bytes(content)
                    if self.log.exists(): self.log.unlink()
                    # Failed preflight may leave private source staging; remove
                    # only this fixture's staging to use the next synthetic case.
                    for stage in (self.base / 'releases').glob('.stage-*'):
                        shutil.rmtree(stage)

    def test_existing_runtime_checksum_tampering_fails_before_stop(self):
        self.seed_old_runtime()
        runtime = self.old / RUNTIME_FILE
        runtime.write_text(runtime.read_text() + ' ')
        result, calls = self.execute(DMS_STATE='installed')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('stop' in call['argv'] for call in calls))
        self.assertEqual((self.base / 'current').resolve(), self.old)

    def test_metadata_setup_failure_restores_database_filestore_and_old_runtime(self):
        for flag in ('FAIL_SETUP', 'MALFORMED_SETUP'):
            with self.subTest(flag=flag):
                result, calls = self.execute(**{flag: 1})
                self.assert_rollback_pair(result, calls)
                self.assert_runtime_compose(calls)
                if flag == 'FAIL_SETUP':
                    self.temp.cleanup()
                    self.setUp()

    def test_business_attachment_or_hr_version_fingerprint_change_forces_pair_rollback(self):
        for field in ('attachments', 'versions'):
            with self.subTest(field=field):
                result, calls = self.execute(FAIL_ORIGINAL=field)
                self.assert_rollback_pair(result, calls)
                self.assert_runtime_compose(calls)
                # Independent fixtures retain one backup each; recreate only
                # the synthetic fixture before checking the second fingerprint.
                if field == 'attachments':
                    self.temp.cleanup()
                    self.setUp()


@unittest.skipUnless(hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'production ownership checks require Linux root')
class DmsPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='baseer-dms-policy-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def policy_script(self, wrapper, modules, third_party):
        source = (OPS / wrapper).read_text()
        policy = self.base / 'fixture-release.env'
        text = (f'RELEASE_ID=fixture-release\nCOMMIT={"b" * 40}\n'
                f'MODULES={modules}\nTHIRD_PARTY_MODULES={third_party}\n')
        if wrapper == 'baseer-production-deploy':
            text += f'POLICY_REVISION={"c" * 40}\nAPPROVED_RUN_ID=1\n'
        policy.write_text(text)
        policy.chmod(0o600)
        parser = 'load_policy' if wrapper == 'baseer-production-deploy' else 'parse_policy'
        call = parser if parser == 'load_policy' else f'{parser} "{policy}"'
        script = ('set -Eeuo pipefail\n'
                  'die() { printf "%s\\n" "$*" >&2; exit 1; }\n'
                  f'POLICY_DIR="{self.base}"\nrelease_id=fixture-release\n'
                  + shell_function(source, 'third_party_module_path') + '\n'
                  + shell_function(source, parser) + '\n' + call)
        return subprocess.run(['bash', '-c', script], text=True, capture_output=True, timeout=10)

    def test_exact_dms_mapping_preserves_heritage_and_rejects_arbitrary_paths(self):
        for wrapper in ('baseer-production-deploy', 'baseer-production-approve-release'):
            function = shell_function((OPS / wrapper).read_text(), 'third_party_module_path')
            for module, expected in (('dms', 'third_party_addons/oca_dms_19/dms'),
                                     ('eh_fixture', 'third_party_addons/erp_heritage_19/eh_fixture')):
                result = subprocess.run(['bash', '-c', function + '\nthird_party_module_path "$1"',
                                         'fixture', module], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)
            for module in ('dms_extra', 'oca_dms', '../dms', 'eh_../dms', 'hr', 'purchase'):
                result = subprocess.run(['bash', '-c', function + '\nthird_party_module_path "$1"',
                                         'fixture', module], capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0, module)

    def test_both_policy_parsers_require_exact_private_dms_closure(self):
        for wrapper in ('baseer-production-deploy', 'baseer-production-approve-release'):
            self.assertEqual(self.policy_script(wrapper, ','.join(DMS_MODULES), 'dms').returncode, 0)
            # Preserve unrelated heritage releases without widening the DMS boundary.
            self.assertEqual(self.policy_script(wrapper, 'baseer_hr_services', 'eh_fixture').returncode, 0)
            for modules, third_party in (
                (','.join(DMS_MODULES), 'dms_extra'),
                (','.join(DMS_MODULES), 'dms,eh_fixture'),
                (','.join(DMS_MODULES) + ',baseer_hr_services', 'dms'),
                ('baseer_dms_trial,baseer_dms_bill_link', 'dms'),
                (','.join(DMS_MODULES), ''),
                (','.join(DMS_MODULES), 'dms,dms'),
            ):
                with self.subTest(wrapper=wrapper, modules=modules, third_party=third_party):
                    self.assertNotEqual(self.policy_script(wrapper, modules, third_party).returncode, 0)

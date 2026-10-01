"""Focused Linux/root rehearsal with fake Docker; never touches production.

Run: python3 -m unittest discover -s ops/production/tests -v
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


OPS = Path(__file__).resolve().parents[1]
COMPOSE = OPS.parents[1] / "compose.production.yaml"
MODULES = (
    "baseer_purchase_batch", "baseer_financial_correction",
    "baseer_service_seed", "baseer_hr_services",
)
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv[1:]
record = {"argv": a}
if a[0] == "compose":
    files = [a[i + 1] for i, v in enumerate(a) if v == "-f"]
    project = pathlib.Path(a[a.index("--project-directory") + 1])
    record["project"] = str(project)
    record["base_env"] = (project / ".env").read_text()
    record["overrides"] = [pathlib.Path(p).read_text() for p in files[1:]]
    record["override_paths"] = files[1:]
    record["override_modes"] = [oct(pathlib.Path(p).stat().st_mode & 0o777) for p in files[1:]]
    record["override_owners"] = [pathlib.Path(p).stat().st_uid for p in files[1:]]
with open(os.environ["CALL_LOG"], "a") as f:
    f.write(json.dumps(record) + "\n")
if a[0] == "exec":
    command = a[-1]
    if "SELECT count(*)" in command:
        print(os.environ["GOOGLE_COUNT"])
        sys.exit(int(os.environ.get("QUERY_EXIT", "0")))
    if "id" in a and "-g" in a: print("101")
    elif "pg_database_size" in command: print("1024")
    elif "SELECT state" in command: print("installed")
    elif "pg_dump" in command: print("fixture dump")
    elif "-i" in a:
        sys.stdin.read()
        if "psql" in command: print("{\"protected\": true}")
elif a[0] == "run":
    if "du -sk" in a[-1]: print("1")
    if "tar -C /source -cf" in a[-1]:
        target = next(x[:-8] for x in a if x.endswith(":/target"))
        pathlib.Path(target, "filestore-baseer_prod.tar").write_text("fixture filestore")
elif a[0] == "inspect": print("odoo:fixture")
elif a[0] == "compose":
    if "config" in a and os.environ.get("FAIL_CONFIG"):
        print("FAKE_SECRET_MUST_NOT_ESCAPE", file=sys.stderr)
        sys.exit(1)
    if "ps" in a: print('{"State":"exited","ExitCode":0}')
    if "run" in a and os.environ.get("FAIL_UPGRADE"): sys.exit(1)
    if "stop" in a and os.environ.get("FAIL_STOP"): sys.exit(1)
'''


@unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "the production ownership checks require Linux root")
class GoogleRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="baseer-google-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.old = self.base / "releases" / "old"
        self.old.mkdir(parents=True)
        (self.old / "config").mkdir()
        (self.old / "config" / "odoo.conf").write_text("[options]\n")
        (self.old / ".env").write_text("POSTGRES_USER=fixture\nPOSTGRES_PASSWORD=fixture\n")
        (self.old / "RELEASE_COMMIT").write_text("a" * 40)
        shutil.copyfile(COMPOSE, self.old / "compose.production.yaml")
        for module in MODULES:
            target = self.old / "custom_addons" / module
            target.mkdir(parents=True)
            (target / "__manifest__.py").write_text("{}")
        (self.base / "current").symlink_to(self.old)
        self.secret = self.base / "secrets" / "google" / "odoo-google.env"
        self.secret.parent.mkdir(parents=True)
        self.secret.write_text("GOOGLE_OAUTH_CLIENT_SECRET=fixture-secret\nGOOGLE_MASTER_KEY=fixture-key\n")
        self.secret.chmod(0o600)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        docker = self.bin / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o700)
        jq = self.bin / "jq"
        jq.write_text('''#!/usr/bin/env python3
import json, sys
field = "State" if "State" in sys.argv[-1] else "ExitCode"
print(json.load(sys.stdin).get(field, ""))
''')
        jq.chmod(0o700)
        self.log = self.base / "calls.jsonl"

    def execute(self, rehearsal=False, **flags):
        name = "rehearse-production-recovery.sh" if rehearsal else "baseer-production-deploy"
        source = (OPS / name).read_text()
        source = source.replace("readonly BASE=/srv/abroj-baseer-production", f"readonly BASE={self.base}")
        source = source.replace("readonly LOCK_FILE=/var/lock/baseer-production-deploy.lock", f"readonly LOCK_FILE={self.base}/deploy.lock")
        source = source.replace("mktemp /run/baseer-google-odoo.XXXXXXXX.yaml", f"mktemp {self.base}/baseer-google-odoo.XXXXXXXX.yaml")
        common = "\ncurl() { return 0; }\nsleep() { :; }\ndf() { printf 'Avail\\n999999999\\n'; }\n"
        if rehearsal:
            source = source.replace("old_release=", common + "old_release=", 1)
            arguments = [str(self.old)]
        else:
            # Replace authority and network fixtures only; all production
            # preflight, compose, quiesce, recovery and cleanup code executes.
            fixtures = common + '''
verify_source_identity() { :; }
load_policy() {
    commit=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    policy_revision=cccccccccccccccccccccccccccccccccccccccc
    approved_run_id=1
    APPROVED_MODULES=(baseer_hr_services)
    APPROVED_THIRD_PARTY_MODULES=()
}
fetch_reviewed_source() {
    mkdir -p "$stage/source"
    cp -a "$old_release/." "$stage/source/"
    rm -f "$stage/source/.env" "$stage/source/config/odoo.conf"
}
'''
            if flags.pop("APPROVE_GOOGLE", False):
                fixtures = fixtures.replace("APPROVED_MODULES=(baseer_hr_services)", "APPROVED_MODULES=(baseer_google_business)")
            source = source.replace("\nrequire_root\nvalidate_arguments", fixtures + "\nrequire_root\nvalidate_arguments", 1)
            arguments = ["fixture-release", "1"]
        script = self.base / name
        script.write_text(source)
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                   CALL_LOG=str(self.log), GOOGLE_COUNT="2")
        env.update({key: str(value) for key, value in flags.items()})
        result = subprocess.run(["bash", str(script), *arguments], env=env,
                                text=True, capture_output=True, timeout=20)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)
        self.assertFalse(list(self.base.glob("baseer-google-odoo.*.yaml")), "temporary override leaked")
        return result, calls

    def assert_google_compose(self, calls):
        compose = [c for c in calls if c["argv"][0] == "compose"]
        self.assertTrue(compose)
        expected = f'services:\n  odoo:\n    env_file:\n      - "{self.secret}"\n'
        paths = set()
        for call in compose:
            self.assertEqual(call["overrides"], [expected])
            self.assertEqual(call["override_modes"], ["0o600"])
            self.assertEqual(call["override_owners"], [0])
            paths.update(call["override_paths"])
            self.assertEqual(call["argv"][call["argv"].index("--env-file") + 1], call["project"] + "/.env")
            self.assertNotIn("GOOGLE_", call["base_env"])
            self.assertNotIn("/current/", call["project"])
        self.assertEqual(len(paths), 1, "all paths must share one fixed override")
        return compose

    def test_deploy_all_compose_paths_share_odoo_only_override(self):
        result, calls = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        compose = self.assert_google_compose(calls)
        for command in ("config", "stop", "run", "up", "ps", "logs"):
            self.assertTrue(any(command in c["argv"] for c in compose), command)
        self.assertEqual(len({c["project"] for c in compose}), 2)
        # No secret --env-file is ever passed to docker exec/db/init helpers.
        self.assertFalse(any(str(self.secret) in c["argv"] for c in calls))

    def test_upgrade_failure_rolls_back_with_same_override_and_old_env(self):
        result, calls = self.execute(FAIL_UPGRADE=1)
        self.assertNotEqual(result.returncode, 0)
        compose = self.assert_google_compose(calls)
        self.assertTrue(any("up" in c["argv"] and c["project"] == str(self.old) for c in compose))
        self.assertEqual((self.base / "current").resolve(), self.old)

    def test_stop_failure_restarts_old_release_and_cleans_override(self):
        result, calls = self.execute(FAIL_STOP=1)
        self.assertNotEqual(result.returncode, 0)
        compose = self.assert_google_compose(calls)
        self.assertTrue(any("up" in c["argv"] and c["project"] == str(self.old) for c in compose))

    def test_missing_secret_fails_before_any_compose(self):
        self.secret.unlink()
        result, calls = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c["argv"][0] == "compose" for c in calls))

    def test_approved_google_install_also_requires_secret(self):
        self.secret.unlink()
        result, calls = self.execute(GOOGLE_COUNT=0, APPROVE_GOOGLE=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c["argv"][0] == "compose" for c in calls))

    def test_unsafe_secret_fails_before_stop(self):
        for kind in ("mode", "owner", "link", "directory"):
            with self.subTest(kind=kind):
                if self.secret.is_symlink() or self.secret.is_file(): self.secret.unlink()
                elif self.secret.is_dir(): self.secret.rmdir()
                self.secret.write_text("GOOGLE_MASTER_KEY=fixture-key\n")
                self.secret.chmod(0o600)
                if kind == "mode": self.secret.chmod(0o640)
                elif kind == "owner": os.chown(self.secret, 1000, 1000)
                elif kind == "link":
                    self.secret.unlink()
                    self.secret.symlink_to(self.old / ".env")
                elif kind == "directory":
                    self.secret.unlink()
                    self.secret.mkdir()
                result, calls = self.execute()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c["argv"][0] == "compose" for c in calls))

    def test_query_failure_and_malformed_result_fail_before_stop(self):
        for flags in ({"QUERY_EXIT": 1}, {"GOOGLE_COUNT": "invalid"}, {"GOOGLE_COUNT": ""}, {"GOOGLE_COUNT": "3"}):
            with self.subTest(flags=flags):
                result, calls = self.execute(**flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c["argv"][0] == "compose" for c in calls))

    def test_no_google_and_no_file_retains_base_configuration(self):
        self.secret.unlink()
        result, calls = self.execute(GOOGLE_COUNT=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c["argv"][0] == "compose" for c in calls))
        self.assertTrue(all(not c["overrides"] for c in calls if c["argv"][0] == "compose"))

    def test_config_error_is_quiet_and_precedes_stop(self):
        result, calls = self.execute(FAIL_CONFIG=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("FAKE_SECRET_MUST_NOT_ESCAPE", result.stdout + result.stderr)
        self.assertFalse(any("stop" in c["argv"] for c in calls))

    def test_rehearsal_restart_and_isolated_odoo_keep_runtime(self):
        result, calls = self.execute(rehearsal=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_google_compose(calls)
        isolated = [c for c in calls if c["argv"][0] == "run" and "REHEARSAL_MODULES=" in " ".join(c["argv"])]
        self.assertEqual(len(isolated), 1)
        self.assertIn(str(self.secret), isolated[0]["argv"])
        self.assertFalse(any(str(self.secret) in c["argv"] for c in calls if c not in isolated))

    def test_rehearsal_missing_secret_precedes_stop(self):
        self.secret.unlink()
        result, calls = self.execute(rehearsal=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c["argv"][0] == "compose" for c in calls))


if __name__ == "__main__":
    unittest.main()

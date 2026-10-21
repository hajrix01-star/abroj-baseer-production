"""Actual wrapper function control flow in isolated files, never host/DB writes.

Docker/Compose, root ownership and fsync are mocked. This is not root-filesystem
or native database acceptance; the separate native rehearsal covers the latter.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / 'ops/production/baseer-production-deploy'
TEXT = WRAPPER.read_text(encoding='utf-8')
BASH = str(Path('C:/Program Files/Git/bin/bash.exe')) if os.name == 'nt' else shutil.which('bash')


def function(name):
    start = TEXT.index('\n' + name + '() ') + 1
    closing = '\n)\n' if name == 'restore_pair' else '\n}\n'
    end = TEXT.index(closing, start) + len(closing)
    return TEXT[start:end]


class WrapperRecoveryFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bwork-recovery-wrapper-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'backup').mkdir()
        (self.root / 'backup/baseer_prod.dump').write_bytes(b'Synthetic control-flow input only.\n')

    def shell(self, body, env=None):
        prefix = ('set -uo pipefail\n'
                  'BASE=' + shlex.quote(self.root.as_posix()) + '\n'
                  'backup="$BASE/backup"\nLOG="$BASE/events"\n'
                  'TASKPY=' + shlex.quote(sys.executable.replace('\\', '/')) + '\n'
                  'python3(){ "$TASKPY" "$@"; }\n')
        # Stream the extracted shell through stdin: the combined real witness
        # and receipt functions exceed Windows Git Bash's -c argument bound.
        return subprocess.run([BASH, '-s'], input=prefix + body, text=True, capture_output=True,
                              cwd=ROOT, env={**os.environ, 'PYTHONUTF8': '1',
                                             # Git Bash must not rewrite simulated Linux
                                             # Docker paths when invoking native Python.
                                             'MSYS2_ARG_CONV_EXCL': '*', **(env or {})}, timeout=30)

    def test_actual_rollback_never_masks_an_early_pair_failure(self):
        body = '''
DB_CONTAINER=fixture-db
ODOO_VOLUME=fixture-volume
compose=(new_compose); compose_old=(old_compose)
old_release=fixture-old
release_switched=1; service_quiesced=1; database_mutated=1
sha256sum(){ [ "$FAIL" != CHECKSUM ]; }
docker(){
 case "$*" in *dropdb*) stage=DROP;; *createdb*) stage=CREATE;; *pg_restore*) stage=DATABASE;; *) stage=FILES;; esac
 printf '%s\\n' "$stage" >> "$LOG"
 [ "$FAIL" != "$stage" ]
}
bwork_recovery_prepare_restore(){ printf 'PREPARE\\n' >> "$LOG"; [ "$FAIL" != PREPARE ]; }
bwork_recovery_restore_complete(){ printf 'COMPLETE\\n' >> "$LOG"; [ "$FAIL" != COMPLETE ]; }
bwork_recovery_restore_verify(){ printf 'VERIFY\\n' >> "$LOG"; [ "$FAIL" != VERIFY ]; }
new_compose(){ :; }
old_compose(){ printf 'RESTART\\n' >> "$LOG"; }
wait_for_login(){ printf 'LOGIN\\n' >> "$LOG"; }
ln(){ :; }
'''
        for failure in ('CHECKSUM', 'PREPARE', 'DROP', 'CREATE', 'DATABASE', 'FILES', 'COMPLETE', 'VERIFY'):
            with self.subTest(failure=failure):
                events = self.root / 'events'
                if events.exists():
                    events.unlink()
                result = self.shell(body + function('restore_pair') + function('rollback') + '\nrollback 1\n',
                                    {'FAIL': failure})
                self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
                record = (self.root / 'backup/result.env').read_text()
                self.assertIn('LIVE=ROLLBACK_FAILED', record)
                self.assertNotIn('LIVE=ROLLED_BACK', record)
                actual = events.read_text().splitlines() if events.exists() else []
                self.assertNotIn('RESTART', actual)
                self.assertNotIn('LOGIN', actual)
                stages = ['PREPARE', 'DROP', 'CREATE', 'DATABASE', 'FILES', 'COMPLETE', 'VERIFY']
                expected = [] if failure == 'CHECKSUM' else stages[:stages.index(failure) + 1]
                self.assertEqual(actual, expected)

    def test_successful_pair_requires_verification_before_restart(self):
        body = '''
DB_CONTAINER=fixture-db; ODOO_VOLUME=fixture-volume
compose=(new_compose); compose_old=(old_compose); old_release=fixture-old
release_switched=1; service_quiesced=1; database_mutated=1
sha256sum(){ :; }
docker(){ :; }
bwork_recovery_prepare_restore(){ printf 'PREPARE\\n' >> "$LOG"; }
bwork_recovery_restore_complete(){ printf 'COMPLETE\\n' >> "$LOG"; }
bwork_recovery_restore_verify(){ printf 'VERIFY\\n' >> "$LOG"; }
new_compose(){ :; }
old_compose(){ printf 'RESTART\\n' >> "$LOG"; }
wait_for_login(){ printf 'LOGIN\\n' >> "$LOG"; }
ln(){ :; }
'''
        result = self.shell(body + function('restore_pair') + function('rollback') + '\nrollback 1\n')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('LIVE=ROLLED_BACK', (self.root / 'backup/result.env').read_text())
        self.assertEqual((self.root / 'events').read_text().splitlines(),
                         ['PREPARE', 'COMPLETE', 'VERIFY', 'RESTART', 'RESTART', 'LOGIN'])

    def prepare_body(self):
        (self.root / 'backup/bwork-recovery-before.json').write_text('{"fixture":true}\n')
        (self.root / 'backup/bwork-pg-toolchain.txt').write_bytes(b'fixture-toolchain\n')
        return '''
bwork_recovery_enabled=1; live_commit=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
commit=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
run_id=123; release_id=baseer-fixture-only
sha256sum(){ if [ "$1" = -c ]; then return 0; fi; printf '%064d  %s\\n' 0 "$1"; }
bwork_recovery_quiescent(){ return 0; }
bwork_recovery_pg_toolchain(){ printf 'fixture-toolchain\\n'; }
sync(){ :; } # Control flow only, not a durability claim.
''' + function('bwork_recovery_sync') + function('bwork_recovery_prepare_restore')

    def test_durable_intent_exists_before_any_identity_process_and_cannot_retry(self):
        result = self.shell(self.prepare_body() + '''
bwork_recovery_prepare_restore
first=$?
bwork_recovery_prepare_restore
second=$?
printf 'FIRST=%s SECOND=%s\\n' "$first" "$second"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('FIRST=0 SECOND=1', result.stdout)
        intent, pending = self.root / 'backup/bwork-recovery-intent.env', self.root / 'bwork-recovery-pending.env'
        self.assertTrue(intent.is_file() and pending.is_file())
        self.assertEqual(intent.read_bytes(), pending.read_bytes())
        self.assertEqual(intent.stat().st_ino, pending.stat().st_ino)
        self.assertFalse((self.root / 'backup/bwork-recovery-receipt.json').exists())

    def test_existing_global_pending_intent_blocks_even_a_new_backup(self):
        (self.root / 'bwork-recovery-pending.env').write_text('PREVIOUS=AMBIGUOUS\n')
        result = self.shell(self.prepare_body() + '\nbwork_recovery_prepare_restore\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'bwork-recovery-pending.env').read_text(), 'PREVIOUS=AMBIGUOUS\n')

    def receipt_scenario(self, change=None, classifier_failure=False, post_schema_failure=False):
        body = self.prepare_body()
        old = {'fixture_' + str(index): index + 100 for index in range(14)}
        proof = {'table_oids': old, 'source': {'commit': 'a' * 40}, 'ledger': {'value': 'fixture ledger'},
                 'database': 'baseer_prod', 'schema_sha256': 'c' * 64}
        raw = (json.dumps(proof) + '\n').encode()
        (self.root / 'backup/bwork-recovery-before.json').write_bytes(raw)
        proof_sha = hashlib.sha256(raw).hexdigest()
        plan = {'classification': 'canonical-ready', 'install': [], 'required_closure': [
            'baseer_bwork', 'baseer_bwork_admin', 'baseer_bwork_dashboard',
            'baseer_bwork_procurement', 'baseer_access_roles', 'baseer_procurement_requests']}
        (self.root / 'backup/baseer_prod.dump').write_bytes(b'fixture-dump')
        (self.root / 'backup/filestore-baseer_prod.tar').write_bytes(b'fixture-filestore')
        intent = ('RECOVERY=RESTORE_PREPARED\nPROOF_SHA256=' + proof_sha + '\nOLD_COMMIT=' + 'a' * 40 +
                  '\nCOMMIT=' + 'b' * 40 + '\nRUN_ID=123\n').encode()
        witness = {'protocol': 'bwork-paired-restore-v1', 'status': 'RESTORED',
                   'method': 'pg_restore-exit-on-error+paired-filestore', 'database': 'baseer_prod',
                   'old_commit': 'a' * 40, 'candidate_commit': 'b' * 40,
                   'release_id': 'baseer-fixture-only', 'run_id': '123', 'source': proof['source'],
                   'dump_sha256': hashlib.sha256(b'fixture-dump').hexdigest(),
                   'filestore_sha256': hashlib.sha256(b'fixture-filestore').hexdigest(),
                   'proof_sha256': proof_sha, 'intent_sha256': hashlib.sha256(intent).hexdigest(),
                   'toolchain_sha256': hashlib.sha256(b'fixture-toolchain\n').hexdigest(),
                   'original_schema_sha256': 'c' * 64, 'restored_schema_sha256': '6' * 64}
        witness_raw = json.dumps(witness, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        receipt = {'protocol': 'bwork-logical-recovery-v1', 'status': 'RECOVERED', 'database': 'baseer_prod',
                   'source_commit': 'a' * 40, 'proof_sha256': proof_sha, 'schema_sha256': '6' * 64,
                   'original_schema_sha256': 'c' * 64,
                   'paired_restore_sha256': hashlib.sha256(witness_raw).hexdigest(),
                   'source': proof['source'], 'old_oids': old,
                   'new_oids': {name: value + 1000 for name, value in old.items()},
                   'old_ledger_sha256': hashlib.sha256(b'fixture ledger').hexdigest(),
                   'new_ledger_sha256': 'd' * 64, 'post_commit_proof_sha256': 'e' * 64,
                   'original_classifier': plan}
        if change:
            receipt.update(change)
        (self.root / 'backup/bwork-schema-before.sha256').write_text('c' * 64 + '\n')
        (self.root / 'backup/bwork-filestore-before.sha256').write_text('f' * 64 + '\n')
        body += '''
sha256sum(){ if [ "$1" = -c ]; then return 0; fi; printf '%s  %s\\n' "$PROOF_SHA" "$1"; }
bwork_recovery_schema_hash(){
 count=$(cat "$BASE/schema-calls" 2>/dev/null || printf 0)
 count=$((count+1)); printf '%s' "$count" > "$BASE/schema-calls"
 if [ "$POST_SCHEMA_FAIL" = yes ] && [ "$count" -eq 3 ]; then printf 'partial-output'; return 39; fi
 printf '%064s\\n' "$SCHEMA"
}
bwork_recovery_filestore_hash(){ printf '%064s\\n' "$FILESTORE"; }
bwork_recovery_sql(){ [ "$1" = recover ] || return 1; printf '%s\\n' "$RECEIPT"; }
old_compose(){ [ "$CLASSIFIER_FAIL" = no ] || return 30; printf '%s\\n' "$PLAN"; }
compose_old=(old_compose)
'''
        body += function('bwork_recovery_witness') + function('bwork_recovery_restore_complete')
        body += function('bwork_recovery_restore_verify')
        body += '\nbwork_recovery_prepare_restore\nbwork_recovery_restore_complete\nbwork_recovery_restore_verify\n'
        return self.shell(body, {'PROOF_SHA': proof_sha, 'SCHEMA': '6' * 64, 'FILESTORE': 'f' * 64,
                                 'RECEIPT': json.dumps(receipt), 'PLAN': json.dumps(plan),
                                 'CLASSIFIER_FAIL': 'yes' if classifier_failure else 'no',
                                 'POST_SCHEMA_FAIL': 'yes' if post_schema_failure else 'no'})

    def test_receipt_context_failures_keep_global_pending_and_block_restart(self):
        for change in ({'status': 'FAILED'}, {'proof_sha256': '0' * 64}, {'source_commit': 'b' * 40},
                       {'new_oids': {}}, {'database': 'baseer_qa'}, {'schema_sha256': '0' * 64},
                       {'original_schema_sha256': '0' * 64}, {'paired_restore_sha256': '0' * 64}):
            with self.subTest(change=change):
                # Each case is its own fresh attempt; never erase an existing
                # ambiguous intent to simulate an automatic retry.
                with tempfile.TemporaryDirectory(prefix='bwork-receipt-negative-') as temporary:
                    old_root = self.root
                    self.root = Path(temporary)
                    (self.root / 'backup').mkdir()
                    try:
                        result = self.receipt_scenario(change)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertTrue((self.root / 'bwork-recovery-pending.env').is_file())
                        self.assertFalse((self.root / 'backup/bwork-recovery-result.sha256').exists())
                    finally:
                        self.root = old_root

    def test_independent_old_classifier_failure_keeps_committed_receipt_pending(self):
        result = self.receipt_scenario(classifier_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / 'bwork-recovery-pending.env').exists())
        self.assertTrue((self.root / 'backup/bwork-recovery-receipt.json').exists())
        self.assertFalse((self.root / 'backup/bwork-recovery-result.sha256').exists())

    def test_pending_clears_only_after_exact_receipt_independent_classification_and_hashes(self):
        result = self.receipt_scenario()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'bwork-recovery-pending.env').exists())
        self.assertTrue((self.root / 'backup/bwork-recovery-intent.env').is_file())
        self.assertTrue((self.root / 'backup/bwork-recovery-receipt.json').is_file())
        self.assertTrue((self.root / 'backup/bwork-restored-classification.json').is_file())
        self.assertTrue((self.root / 'backup/bwork-recovery-result.sha256').is_file())

    def test_postcommit_schema_command_failure_keeps_receipt_pending_without_success(self):
        result = self.receipt_scenario(post_schema_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / 'bwork-recovery-pending.env').exists())
        self.assertTrue((self.root / 'backup/bwork-recovery-receipt.json').exists())
        self.assertFalse((self.root / 'backup/bwork-recovery-result.sha256').exists())
        self.assertFalse((self.root / 'backup/bwork-restored-classification.json').exists())

    def witness_fixture(self):
        folder = self.root / 'backup'
        proof = {'database': 'baseer_prod', 'schema_sha256': 'c' * 64,
                 'source': {'commit': 'a' * 40}}
        raw = json.dumps(proof, sort_keys=True, separators=(',', ':')).encode() + b'\n'
        (folder / 'bwork-recovery-before.json').write_bytes(raw)
        (folder / 'baseer_prod.dump').write_bytes(b'fixture-dump')
        (folder / 'filestore-baseer_prod.tar').write_bytes(b'fixture-filestore')
        (folder / 'bwork-pg-toolchain.txt').write_bytes(b'fixture-toolchain\n')
        (folder / 'bwork-schema-before.sha256').write_bytes(('c' * 64 + '\n').encode())
        (folder / 'bwork-schema-restored.sha256').write_bytes(('6' * 64 + '\n').encode())
        intent = ('RECOVERY=RESTORE_PREPARED\nPROOF_SHA256=' + hashlib.sha256(raw).hexdigest() +
                  '\nOLD_COMMIT=' + 'a' * 40 + '\nCOMMIT=' + 'b' * 40 + '\nRUN_ID=123\n')
        (folder / 'bwork-recovery-intent.env').write_bytes(intent.encode())
        return '''
release_id=baseer-fixture-only; run_id=123
live_commit=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
commit=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
''' + function('bwork_recovery_witness')

    def test_actual_witness_create_verify_binds_files_context_and_never_overwrites(self):
        body = self.witness_fixture()
        result = self.shell(body + '\nbwork_recovery_witness create && bwork_recovery_witness verify\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = self.root / 'backup/bwork-paired-restore.json'
        raw = path.read_bytes()
        witness = json.loads(raw)
        self.assertEqual(raw, json.dumps(witness, sort_keys=True, separators=(',', ':'),
                                        ensure_ascii=False).encode())
        self.assertFalse(raw.endswith(b'\n'))
        self.assertEqual(witness['status'], 'RESTORED')
        self.assertEqual(witness['method'], 'pg_restore-exit-on-error+paired-filestore')
        self.assertEqual(witness['original_schema_sha256'], 'c' * 64)
        self.assertEqual(witness['restored_schema_sha256'], '6' * 64)
        for field, name in (('dump_sha256', 'baseer_prod.dump'),
                            ('filestore_sha256', 'filestore-baseer_prod.tar'),
                            ('toolchain_sha256', 'bwork-pg-toolchain.txt'),
                            ('intent_sha256', 'bwork-recovery-intent.env'),
                            ('proof_sha256', 'bwork-recovery-before.json')):
            self.assertEqual(witness[field], hashlib.sha256((path.parent / name).read_bytes()).hexdigest())
        result = self.shell(body + '\nbwork_recovery_witness create\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), raw)

    def test_actual_witness_rejects_changed_or_missing_pair_toolchain_intent_proof_and_schema(self):
        names = ('baseer_prod.dump', 'filestore-baseer_prod.tar', 'bwork-pg-toolchain.txt',
                 'bwork-recovery-intent.env', 'bwork-recovery-before.json',
                 'bwork-schema-before.sha256', 'bwork-schema-restored.sha256')
        for name in names:
            for missing in (False, True):
                with self.subTest(name=name, missing=missing), \
                     tempfile.TemporaryDirectory(prefix='bwork-witness-file-') as temporary:
                    old_root = self.root
                    self.root = Path(temporary)
                    (self.root / 'backup').mkdir()
                    try:
                        body = self.witness_fixture()
                        result = self.shell(body + '\nbwork_recovery_witness create\n')
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        path = self.root / 'backup' / name
                        if missing:
                            path.unlink()
                        else:
                            path.write_bytes(path.read_bytes() + b'changed')
                        result = self.shell(body + '\nbwork_recovery_witness verify\n')
                        self.assertNotEqual(result.returncode, 0)
                    finally:
                        self.root = old_root

    def test_actual_witness_rejects_stale_context_duplicate_noncanonical_and_missing_witness(self):
        cases = ('run', 'release', 'candidate', 'old', 'duplicate', 'noncanonical', 'missing', 'extra')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix='bwork-witness-context-') as temporary:
                old_root = self.root
                self.root = Path(temporary)
                (self.root / 'backup').mkdir()
                try:
                    body = self.witness_fixture()
                    result = self.shell(body + '\nbwork_recovery_witness create\n')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    path = self.root / 'backup/bwork-paired-restore.json'
                    raw = path.read_bytes()
                    suffix = ''
                    if case == 'run':
                        suffix = 'run_id=999\n'
                    elif case == 'release':
                        suffix = 'release_id=other-release\n'
                    elif case == 'candidate':
                        suffix = 'commit=' + 'd' * 40 + '\n'
                    elif case == 'old':
                        suffix = 'live_commit=' + 'd' * 40 + '\n'
                    elif case == 'duplicate':
                        path.write_bytes(raw[:-1] + b',"status":"RESTORED"}')
                    elif case == 'noncanonical':
                        path.write_text(json.dumps(json.loads(raw), indent=2), encoding='utf-8')
                    elif case == 'missing':
                        path.unlink()
                    else:
                        witness = json.loads(raw)
                        witness['extra'] = True
                        path.write_text(json.dumps(witness, sort_keys=True, separators=(',', ':')), encoding='utf-8')
                    result = self.shell(body + '\n' + suffix + 'bwork_recovery_witness verify\n')
                    self.assertNotEqual(result.returncode, 0)
                finally:
                    self.root = old_root

    def test_archive_render_uses_explicit_stdout_only_argv(self):
        body = '''
DB_CONTAINER=fixture-db; bwork_recovery_schema_key=FixtureOnly
docker(){
 if [ "$*" = 'exec fixture-db pg_restore --help' ]; then
   [ "$RESTRICT" = yes ] && printf '%s\\n' '--restrict-key'
   return 0
 fi
 local wanted='exec -i fixture-db timeout 120 pg_restore --schema-only --no-owner --no-privileges --file=-'
 [ "$RESTRICT" != yes ] || wanted+=' --restrict-key=FixtureOnly'
 [ "$*" = "$wanted" ] || return 64
 cat >/dev/null
 printf 'synthetic raw schema\\n'
}
''' + function('bwork_recovery_archive_schema_hash') + '''
bwork_recovery_archive_schema_hash
'''
        expected = hashlib.sha256(b'synthetic raw schema\n').hexdigest()
        for restrict in ('yes', 'no'):
            with self.subTest(restrict=restrict):
                result = self.shell(body, {'RESTRICT': restrict})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_archive_render_failure_with_output_is_not_accepted_as_a_hash(self):
        body = '''
DB_CONTAINER=fixture-db; bwork_recovery_schema_key=FixtureOnly
docker(){
 if [ "$*" = 'exec fixture-db pg_restore --help' ]; then printf '%s\\n' '--restrict-key'; return 0; fi
 printf 'partial schema output\\n'
 return 41
}
''' + function('bwork_recovery_archive_schema_hash') + '''
if value="$(bwork_recovery_archive_schema_hash)"; then printf 'ACCEPTED=%s\\n' "$value"; exit 90; fi
'''
        result = self.shell(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('ACCEPTED=', result.stdout)

    def test_source_keeps_nonretryable_intent_and_postcommit_old_classifier(self):
        before = function('bwork_recovery_prepare_restore')
        verify = function('bwork_recovery_restore_verify')
        self.assertIn('set -o noclobber', before)
        self.assertIn('sync -f "$BASE"', before)
        self.assertNotIn('bwork_recovery_sql recover', before)
        self.assertLess(verify.index('bwork_recovery_sql recover'), verify.index('--classify'))
        self.assertLess(verify.index('bwork-recovery-result.sha256'), verify.index('rm -- "$BASE/bwork-recovery-pending.env"'))
        self.assertIn('a previous recovery has an unresolved durable intent', TEXT)
        self.assertNotRegex(function('rollback'), r'restore_pair[^\n]*\|\|')
        fetch = function('fetch_reviewed_source')
        self.assertLess(fetch.index('bwork_source_guard "$stage/source" "$fetch_repo"'),
                        fetch.index('bwork_recovery_source_guard "$fetch_repo"'))
        self.assertLess(fetch.index('bwork_recovery_source_guard "$fetch_repo"'),
                        fetch.index('rm -rf -- "$fetch_repo"'))
        self.assertNotIn('bwork_recovery_source_guard', function('bwork_source_guard'))

    def test_git_lf_artifact_pins_match_actual_source_bytes(self):
        # Execute this source-binding test from the raw Git-LF archive, as CI
        # and production do; checkout CRLF hashes must never be promoted.
        helper_sha = hashlib.sha256((ROOT / 'ops/lib/bwork_recovery.py').read_bytes()).hexdigest()
        pinned = re.search(r'^readonly BWORK_RECOVERY_HELPER_SHA256=([a-f0-9]{64})$', TEXT, re.M)
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned[1], helper_sha)
        wrapper_sha = hashlib.sha256(WRAPPER.read_bytes()).hexdigest()
        installer = (ROOT / 'ops/production/upgrade-bwork-deploy-wrapper.sh').read_text()
        target = re.search(r'^readonly NEW_SHA=([a-f0-9]{64})$', installer, re.M)
        self.assertIsNotNone(target)
        self.assertEqual(target[1], wrapper_sha)

    def test_quiescence_rejects_named_bind_alias_and_parent_filestore_writers(self):
        body = '''
ODOO_VOLUME=fixture-volume
docker(){
 case "$1" in
  volume) printf '/var/lib/docker/volumes/fixture-volume/_data\\n';;
  ps) [ "$FAIL_LIST" = no ] || return 1; printf '%064d\\n' 1;;
  inspect) printf '%s\\n' "$MOUNTS";;
  *) return 1;;
 esac
}
''' + function('bwork_recovery_quiescent') + '\nbwork_recovery_quiescent\n'
        safe = [{'Name': 'fixture-volume', 'Source': '/var/lib/docker/volumes/fixture-volume/_data', 'RW': False}]
        cases = [(safe, 'no', True), ([], 'yes', False)]
        for source in ('/var/lib/docker/volumes/fixture-volume/_data',
                       '/var/lib/docker/volumes/fixture-volume/_data/filestore', '/var/lib/docker', '/'):
            cases.append(([{'Type': 'bind', 'Source': source, 'RW': True}], 'no', False))
        cases.append(([{'Name': 'fixture-volume', 'RW': True}], 'no', False))
        for mounts, fail, expected in cases:
            with self.subTest(mounts=mounts, fail=fail):
                result = self.shell(body, {'MOUNTS': json.dumps(mounts), 'FAIL_LIST': fail})
                self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

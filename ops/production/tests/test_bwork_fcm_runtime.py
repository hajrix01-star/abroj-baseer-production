"""Offline synthetic tests only; Linux-root file tests never touch production paths."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

OPS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('bwork_fcm_runtime', OPS / 'configure-bwork-fcm-runtime.py')
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def credential(**changes):
    # Shape-only fake key for Python dotenv tests; Node tests generate real ephemeral RSA.
    value = {'type': 'service_account', 'project_id': 'bchat-9cab1',
             'token_uri': 'https://oauth2.googleapis.com/token',
             'client_email': 'offline-test@bchat-9cab1.iam.gserviceaccount.com',
             'private_key': '-----BEGIN PRIVATE KEY-----\n'
             + base64.b64encode(b'synthetic-not-a-real-key' * 20).decode('ascii')
             + '\n-----END PRIVATE KEY-----\n'}
    value.update(changes)
    return json.dumps(value).encode('utf-8')


class TestParser(unittest.TestCase):
    def test_account_canonical_roundtrip(self):
        compact = runtime.canonical_account(credential())
        self.assertEqual(json.loads(compact), json.loads(credential()))
        self.assertFalse(any(c in compact for c in (b"'", b'\r', b'\n', b'$')))

    def test_wrong_identity_email_and_key_are_rejected(self):
        for changes in ({'type': 'authorized_user'}, {'project_id': 'another'},
                        {'token_uri': 'https://attacker.invalid/token'},
                        {'client_email': 'test@another.iam.gserviceaccount.com'},
                        {'private_key': 'secret'}, {'private_key': '-----BEGIN RSA PRIVATE KEY-----'}):
            with self.subTest(changes=list(changes)):
                with self.assertRaises(runtime.Refused):
                    runtime.canonical_account(credential(**changes))

    def test_duplicate_json_nul_size_and_dotenv_interpolation_are_rejected(self):
        inputs = [b'{"type":"service_account","type":"service_account"}',
                  credential(extra='\0'), credential(extra="can't"), credential(extra='$SECRET'),
                  b'\0', b' ' * (runtime.MAX_INPUT + 1), b'{"x":NaN}']
        for raw in inputs:
            with self.assertRaises(runtime.Refused):
                runtime.canonical_account(raw)

    def test_prefix_and_existing_google_bytes_are_unchanged(self):
        for before in (b'', b'# old\r\nGOOGLE_MASTER_KEY=synthetic\r\n',
                       b'GOOGLE_OAUTH_CLIENT_SECRET=synthetic-no-newline'):
            after = runtime.appended_environment(before, runtime.canonical_account(credential()))
            self.assertTrue(after.startswith(before))
            self.assertEqual(len(runtime.configured_lines(after)), 1)
            self.assertEqual(runtime.appended_environment(after, runtime.canonical_account(credential())), after)

    def test_existing_duplicate_and_malformed_fcm_keys_fail_closed(self):
        key = runtime.JSON_KEY
        samples = [key + b'=old\n', runtime.FILE_KEY + b'=\n', key + b'=a\n' + key + b'=b\n',
                   b'export ' + key + b'=old\n', key + b' : old\n', b'X' + key + b'=old\n',
                   b'OTHER=mentions-' + key + b'\n', b'\0']
        for before in samples:
            with self.assertRaises(runtime.Refused):
                runtime.appended_environment(before, runtime.canonical_account(credential()))

    def test_comment_is_preserved_not_configured(self):
        before = b'# BWORK_FCM_SERVICE_ACCOUNT_JSON=not-active\n'
        self.assertEqual(runtime.configured_lines(before), [])
        self.assertTrue(runtime.appended_environment(before, runtime.canonical_account(credential())).startswith(before))

    def test_environment_cap(self):
        with self.assertRaises(runtime.Refused):
            runtime.appended_environment(b'A' * runtime.MAX_ENV, runtime.canonical_account(credential()))

    def test_apply_missing_or_mismatched_validated_hash_precedes_environment_read(self):
        raw = credential()
        with patch.object(runtime, 'read_private') as read:
            for expected in (None, '', 'not-a-hash', '0' * 64):
                with self.assertRaises(runtime.Refused):
                    runtime.apply_account(raw, expected)
            read.assert_not_called()

    def test_cli_missing_apply_hash_refused_before_lock(self):
        with patch.object(runtime.sys, 'argv', ['configure-bwork-fcm-runtime.py', '--apply']), \
                patch.object(runtime.sys, 'platform', 'linux'), \
                patch.object(runtime.os, 'geteuid', return_value=0, create=True), \
                patch.object(runtime, 'production_lock') as lock, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(runtime.main(), 1)
            lock.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['code'], 'validated_input_hash_required')


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'private ownership/atomic tests require Linux root; pure tests run everywhere')
class TestPrivateFiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bwork-fcm-offline-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.env = self.root / 'odoo-google.env'
        self.original = b'# existing\r\nGOOGLE_MASTER_KEY=synthetic-not-private\r\n'
        self.env.write_bytes(self.original)
        self.env.chmod(0o600)
        self.backups = self.root / 'bwork-fcm-backups'

    def apply(self):
        raw = credential()
        # Synthetic hash binding tests plumbing, NOT a claim that the fake PEM is RSA/OAuth-valid.
        return runtime.apply_account(raw, runtime.sha(raw), self.env, self.backups, self.root)

    def restore(self, applied, **changes):
        values = {'backup': Path(applied['backup']), 'expected_current': applied['sha256'],
                  'expected_backup': applied['backupSha256'], 'env_path': self.env,
                  'backup_root': self.backups, 'boundary': self.root}
        values.update(changes)
        return runtime.restore_backup(**values)

    def test_apply_idempotence_private_backups_and_restore(self):
        applied = self.apply()
        self.assertEqual(applied['status'], 'applied')
        self.assertTrue(self.env.read_bytes().startswith(self.original))
        backup = Path(applied['backup'])
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)
        receipt_before = (backup.parent / 'receipt.json').read_bytes()
        self.assertEqual(self.apply()['status'], 'no_change')
        self.assertEqual(len(list(self.backups.iterdir())), 1)
        self.assertEqual(self.restore(applied)['status'], 'restored')
        self.assertEqual(self.env.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertEqual((self.env.stat().st_uid, self.env.stat().st_gid), (0, 0))
        self.assertEqual((backup.parent / 'receipt.json').read_bytes(), receipt_before)

    def test_symlink_file_hardlink_mode_and_unsafe_parent_refused(self):
        self.env.chmod(0o640)
        with self.assertRaises(runtime.Refused): self.apply()
        self.env.chmod(0o600)
        target = self.root / 'target'
        self.env.rename(target)
        self.env.symlink_to(target)
        with self.assertRaises(runtime.Refused): self.apply()
        self.env.unlink()
        os.link(target, self.env)
        with self.assertRaises(runtime.Refused): self.apply()
        self.env.unlink()
        target.rename(self.env)
        self.root.chmod(0o777)
        with self.assertRaises(runtime.Refused): self.apply()
        self.root.chmod(0o700)

    def test_symlink_backup_directory_refused(self):
        other = self.root / 'other'
        other.mkdir(mode=0o700)
        self.backups.symlink_to(other)
        with self.assertRaises(runtime.Refused): self.apply()
        self.assertEqual(self.env.read_bytes(), self.original)

    def test_atomic_replace_failure_preserves_preimage_and_receipt(self):
        with patch.object(runtime.os, 'replace', side_effect=OSError('synthetic failure')):
            with self.assertRaisesRegex(runtime.Refused, '^update_failed_rollback_verified$'):
                self.apply()
        self.assertEqual(self.env.read_bytes(), self.original)
        self.assertEqual(len(list(self.backups.glob('*/receipt.json'))), 1)
        self.assertFalse(list(self.root.glob('.bwork-fcm-*')))

    def test_post_write_failure_rolls_back(self):
        with patch.object(runtime, 'verify_applied', side_effect=runtime.Refused('synthetic')):
            with self.assertRaisesRegex(runtime.Refused, '^update_failed_rollback_verified$'):
                self.apply()
        self.assertEqual(self.env.read_bytes(), self.original)

    def test_rollback_failure_is_stop(self):
        actual_replace = runtime.atomic_replace
        calls = []
        def fail_second(path, raw):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('synthetic rollback failure')
            actual_replace(path, raw)
        with patch.object(runtime, 'atomic_replace', side_effect=fail_second), \
                patch.object(runtime, 'verify_applied', side_effect=runtime.Refused('synthetic')):
            with self.assertRaisesRegex(runtime.Refused, '^STOP_rollback_failed$'):
                self.apply()
        self.assertTrue(self.env.read_bytes().startswith(self.original))

    def test_restore_rejects_wrong_hash_or_changed_current(self):
        applied = self.apply()
        for changes in ({'expected_current': '0' * 64}, {'expected_backup': '0' * 64},
                        {'backup': self.root / 'preimage.env'}):
            with self.assertRaises(runtime.Refused): self.restore(applied, **changes)
        installed = self.env.read_bytes()
        self.env.write_bytes(installed + b'GOOGLE_NEW=synthetic\n')
        with self.assertRaises(runtime.Refused):
            self.restore(applied, expected_current=runtime.sha(self.env.read_bytes()))
        self.assertEqual(self.env.read_bytes(), installed + b'GOOGLE_NEW=synthetic\n')

    def test_restore_rejects_tampered_backup_or_receipt(self):
        applied = self.apply()
        backup = Path(applied['backup'])
        original_backup = backup.read_bytes()
        backup.write_bytes(b'altered')
        with self.assertRaises(runtime.Refused): self.restore(applied)
        backup.write_bytes(original_backup)
        receipt = backup.parent / 'receipt.json'
        content = json.loads(receipt.read_bytes())
        content['environment'] = '/different/path'
        receipt.write_text(json.dumps(content))
        with self.assertRaises(runtime.Refused): self.restore(applied)

    def test_restore_write_failure_returns_to_installed_state(self):
        applied = self.apply()
        installed = self.env.read_bytes()
        with patch.object(runtime.os, 'replace', side_effect=OSError('synthetic')):
            with self.assertRaisesRegex(runtime.Refused, '^restore_failed_rollback_verified$'):
                self.restore(applied)
        self.assertEqual(self.env.read_bytes(), installed)

    def test_lock_same_inode_busy_and_unsafe_inode(self):
        lock = self.root / 'production.lock'
        lock.write_bytes(b'')
        lock.chmod(0o600)
        original_check = runtime.check_parents
        def fixture_parents(path, boundary=None):
            original_check(path, self.root)
        with patch.object(runtime, 'LOCK_PATH', lock), patch.object(runtime, 'check_parents', fixture_parents):
            with runtime.production_lock():
                with self.assertRaisesRegex(runtime.Refused, '^production_lock_busy$'):
                    with runtime.production_lock(): self.fail('second lock acquired')
            lock.chmod(0o666)
            with self.assertRaises(runtime.Refused):
                with runtime.production_lock(): self.fail('unsafe lock acquired')
            lock.chmod(0o600)
            target = self.root / 'real.lock'
            lock.rename(target)
            lock.symlink_to(target)
            with self.assertRaises(runtime.Refused):
                with runtime.production_lock(): self.fail('symlink lock acquired')

    def test_lock_replacement_is_refused(self):
        lock = self.root / 'production.lock'
        lock.write_bytes(b'')
        lock.chmod(0o600)
        original_check, original_open = runtime.check_parents, runtime.os.open
        def fixture_parents(path, boundary=None):
            original_check(path, self.root)
        def race(path, flags, *args, **kwargs):
            fd = original_open(path, flags, *args, **kwargs)
            if Path(path) == lock:
                lock.unlink()
                lock.write_bytes(b'new inode')
                lock.chmod(0o600)
            return fd
        with patch.object(runtime, 'LOCK_PATH', lock), patch.object(runtime, 'check_parents', fixture_parents), \
                patch.object(runtime.os, 'open', side_effect=race):
            with self.assertRaisesRegex(runtime.Refused, '^lock_changed$'):
                with runtime.production_lock(): self.fail('replaced lock acquired')


@unittest.skipUnless(shutil.which('node'), 'Node is required for offline RSA/OAuth contract tests')
class TestOfflineNode(unittest.TestCase):
    def test_crypto_request_and_redacted_results(self):
        script = r'''
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const probe = require(process.argv[1]);
(async () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const pem = privateKey.export({ type: 'pkcs8', format: 'pem' });
  const config = { type: 'service_account', project_id: 'bchat-9cab1',
    client_email: 'synthetic@bchat-9cab1.iam.gserviceaccount.com',
    token_uri: 'https://oauth2.googleapis.com/token', private_key: pem };
  const raw = Buffer.from(JSON.stringify(config));
  const account = probe.validateAccount(raw);
  for (const change of [{project_id:'other'}, {token_uri:'https://evil.invalid'},
      {client_email:'synthetic@evil.invalid'}, {private_key:'not-a-key'}, {extra:'\0'}]) {
    assert.throws(() => probe.validateAccount(Buffer.from(JSON.stringify({...config,...change}))));
  }
  assert.throws(() => probe.strictJson('{"a":1,"a":2}'));
  assert.throws(() => probe.strictJson('{"nested":{"x":1,"x":2}}'));
  assert.throws(() => probe.strictJson('{"x":"\\u0000"}'));
  const weak = crypto.generateKeyPairSync('rsa', { modulusLength:1024 }).privateKey.export({type:'pkcs8',format:'pem'});
  assert.throws(() => probe.validateAccount(Buffer.from(JSON.stringify({...config,private_key:weak}))));
  const ec = crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'}).privateKey.export({type:'pkcs8',format:'pem'});
  assert.throws(() => probe.validateAccount(Buffer.from(JSON.stringify({...config,private_key:ec}))));
  let assertion;
  const ok = await probe.authenticate(account, async (url, opts) => {
    assert.equal(url,'https://oauth2.googleapis.com/token'); assert.equal(opts.redirect,'error');
    assert.equal(opts.method,'POST'); assert.ok(opts.signal instanceof AbortSignal);
    assert.equal(opts.body.get('grant_type'),'urn:ietf:params:oauth:grant-type:jwt-bearer');
    assertion = opts.body.get('assertion');
    const [header,claims,sig] = assertion.split('.');
    assert.deepEqual(JSON.parse(Buffer.from(header,'base64url')), {alg:'RS256',typ:'JWT'});
    const body=JSON.parse(Buffer.from(claims,'base64url'));
    assert.equal(body.iat,1000); assert.equal(body.exp,1300); assert.equal(body.aud,url);
    assert.equal(body.scope,'https://www.googleapis.com/auth/firebase.messaging');
    assert.ok(crypto.verify('RSA-SHA256',Buffer.from(header+'.'+claims),publicKey,Buffer.from(sig,'base64url')));
    return new Response(JSON.stringify({access_token:'synthetic-access-token-never-print',token_type:'Bearer'}),{status:200});
  },1000);
  const proof={rawInputSha256:crypto.createHash('sha256').update(raw).digest('hex'),rsa2048Verified:true};
  assert.deepEqual(ok,{authSuccess:true,http:200,project:'bchat-9cab1',...proof});
  const denied=await probe.authenticate(account,async()=>new Response(JSON.stringify({error:'invalid_grant',error_description:pem}),{status:400}));
  assert.deepEqual(denied,{authSuccess:false,http:400,project:'bchat-9cab1',...proof,errorCode:'invalid_grant'});
  const arbitrary=await probe.authenticate(account,async()=>new Response(JSON.stringify({error:pem}),{status:400}));
  assert.equal(arbitrary.errorCode,'oauth_rejected');
  await assert.rejects(()=>probe.authenticate(account,async()=>new Response('x'.repeat(65537),{status:200})));
  await assert.rejects(()=>probe.authenticate(account,async()=>{throw new Error('synthetic private network error');}));
  const visible=JSON.stringify({ok,denied,arbitrary});
  assert.ok(!visible.includes(pem)); assert.ok(!visible.includes(assertion));
  assert.ok(!visible.includes('synthetic-access-token-never-print'));
  process.stdout.write('offline-node-PASS');
})().catch(()=>{process.stderr.write('offline-node-FAIL');process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script, str(OPS / 'probe-bwork-fcm-provider.cjs')],
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'offline-node-PASS', ''))


if __name__ == '__main__':
    unittest.main()

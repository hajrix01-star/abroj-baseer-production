#!/usr/bin/env python3
"""Root-only, locked update of the Odoo-only Google env seam; never restarts Odoo.

Apply reads the owner-approved service account from stdin, not argv/environment.
The operator must bind --expected-validated-input-sha256 to the independently
accepted Node OAuth proof (same raw input, RSA2048 verified and auth success).
An arbitrary caller-supplied hash is NOT itself proof of RSA/OAuth validation.
Backups/receipts are private, create-once and retained (not chattr immutable).
External env recovery is separate from release/database rollback.
"""
import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

ENV_PATH = Path('/srv/abroj-baseer-production/secrets/google/odoo-google.env')
BACKUP_ROOT = ENV_PATH.parent / 'bwork-fcm-backups'
LOCK_PATH = Path('/var/lock/baseer-production-deploy.lock')
MAX_INPUT = 16 * 1024
MAX_ENV = 128 * 1024
PROJECT = 'bchat-9cab1'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
JSON_KEY = b'BWORK_FCM_SERVICE_ACCOUNT_JSON'
FILE_KEY = b'BWORK_FCM_SERVICE_ACCOUNT_FILE'
KEYS = (JSON_KEY, FILE_KEY)


class Refused(Exception):
    """Only fixed public error codes may leave this process."""


def require(condition, code):
    if not condition:
        raise Refused(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        require(b'\0' not in raw, 'invalid_json')
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused('invalid_json')))
    except (UnicodeError, ValueError, TypeError):
        raise Refused('invalid_json') from None


def canonical_account(raw):
    require(0 < len(raw) <= MAX_INPUT, 'credential_size')
    account = strict_json(raw)
    require(isinstance(account, dict), 'invalid_account')
    require(account.get('type') == 'service_account' and account.get('project_id') == PROJECT
            and account.get('token_uri') == TOKEN_URI, 'account_identity')
    email = account.get('client_email')
    require(isinstance(email, str) and re.fullmatch(
        r'[A-Za-z0-9._-]+@bchat-9cab1\.iam\.gserviceaccount\.com', email), 'account_email')
    key = account.get('private_key')
    require(isinstance(key, str) and len(key) <= 8192, 'private_key_shape')
    match = re.fullmatch(r'-----BEGIN PRIVATE KEY-----\n([A-Za-z0-9+/=\n]+)\n-----END PRIVATE KEY-----\n?', key)
    require(match is not None, 'private_key_shape')
    try:
        require(len(base64.b64decode(match[1].replace('\n', ''), validate=True)) >= 256,
                'private_key_shape')
    except ValueError:
        raise Refused('private_key_shape') from None
    compact = json.dumps(account, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode('ascii')
    # No dotenv interpolation, shell quote, literal newline or decoded NUL in any field.
    require(not any(part in compact for part in (b"'", b'$', b'\r', b'\n', b'\\u0000')),
            'unsafe_dotenv_value')
    require(strict_json(compact) == account, 'json_roundtrip')
    return compact


def configured_lines(raw):
    require(len(raw) <= MAX_ENV and b'\0' not in raw, 'environment_size_or_nul')
    found = []
    for line in raw.splitlines():
        stripped = line.lstrip(b' \t')
        if not stripped or stripped.startswith(b'#'):
            continue
        match = re.match(rb'(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=', stripped)
        # A misspelled/malformed attempt cannot be used to hide an existing FCM key.
        if any(key in stripped for key in KEYS):
            require(match is not None and match[1] in KEYS, 'malformed_fcm_key')
        if match and match[1] in KEYS:
            found.append((match[1], line))
    require(len(found) <= 1, 'duplicate_fcm_key')
    return found


def appended_environment(before, compact):
    line = JSON_KEY + b"='" + compact + b"'"
    existing = configured_lines(before)
    if existing:
        require(existing == [(JSON_KEY, line)], 'fcm_already_configured')
        return before
    after = before + (b'' if not before or before.endswith(b'\n') else b'\n') + line + b'\n'
    require(len(after) <= MAX_ENV and after.startswith(before), 'environment_size_or_prefix')
    require(configured_lines(after) == [(JSON_KEY, line)], 'environment_postcondition')
    return after


def check_parents(path, boundary=Path('/')):
    path, boundary = Path(path), Path(boundary)
    require(path.is_absolute() and '..' not in path.parts and boundary in (path, *path.parents), 'unsafe_path')
    for parent in ((path,) if path == boundary else path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == 0 and info.st_gid == 0 and info.st_mode & 0o022 == 0,
                'unsafe_parent')
        if parent == boundary:
            break


def read_private(path, cap=MAX_ENV, boundary=Path('/')):
    check_parents(path, boundary)
    before = Path(path).lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == before.st_gid == 0
            and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1, 'unsafe_private_file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        current = os.fstat(fd)
        require((before.st_dev, before.st_ino) == (current.st_dev, current.st_ino), 'file_changed')
        require(current.st_size <= cap, 'private_file_size')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(cap + 1)
        require(len(raw) <= cap, 'private_file_size')
        return raw
    finally:
        os.close(fd)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_private(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def atomic_replace(path, raw):
    """Only this operation's exclusive temporary file may be removed."""
    fd, temporary = tempfile.mkstemp(prefix='.bwork-fcm-', dir=path.parent)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.lexists(temporary):
            os.unlink(temporary)


def verify_applied(path, expected, before, boundary):
    actual = read_private(path, boundary=boundary)
    require(actual == expected and actual.startswith(before), 'write_verification')
    configured_lines(actual)


def replace_with_rollback(path, before, after, boundary):
    require(read_private(path, boundary=boundary) == before, 'current_file_changed')
    try:
        atomic_replace(path, after)
        verify_applied(path, after, before, boundary)
    except Exception:
        # Never overwrite a concurrent/unrecognised state during recovery.
        try:
            current = read_private(path, boundary=boundary)
            require(current in (before, after), 'rollback_state_changed')
            if current == after:
                atomic_replace(path, before)
            require(read_private(path, boundary=boundary) == before, 'rollback_verification')
        except Exception:
            raise Refused('STOP_rollback_failed') from None
        raise Refused('update_failed_rollback_verified') from None


def apply_account(raw, validated_input_sha, env_path=ENV_PATH, backup_root=BACKUP_ROOT, boundary=Path('/')):
    require(isinstance(validated_input_sha, str)
            and re.fullmatch(r'[a-f0-9]{64}', validated_input_sha), 'validated_input_hash_required')
    require(0 < len(raw) <= MAX_INPUT and sha(raw) == validated_input_sha, 'validated_input_hash_mismatch')
    compact = canonical_account(raw)
    before = read_private(env_path, boundary=boundary)
    after = appended_environment(before, compact)
    if after == before:
        return {'status': 'no_change', 'project': PROJECT, 'sha256': sha(before)}
    check_parents(backup_root, boundary)
    if not os.path.lexists(backup_root):
        os.mkdir(backup_root, 0o700)
        os.chown(backup_root, 0, 0)
        fsync_dir(backup_root.parent)
    info = backup_root.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 0
            and stat.S_IMODE(info.st_mode) == 0o700, 'unsafe_backup_directory')
    bundle = Path(tempfile.mkdtemp(prefix='fcm-', dir=backup_root))
    os.chown(bundle, 0, 0)
    backup = bundle / 'preimage.env'
    create_private(backup, before)
    receipt = {'version': 1, 'environment': str(env_path), 'backup': str(backup),
               'beforeSha256': sha(before), 'installedSha256': sha(after),
               'beforeBytes': len(before), 'installedBytes': len(after),
               'uid': 0, 'gid': 0, 'mode': '0600', 'createdUtc': int(time.time())}
    create_private(bundle / 'receipt.json', json.dumps(receipt, sort_keys=True).encode('ascii') + b'\n')
    fsync_dir(bundle)
    fsync_dir(backup_root)
    require(read_private(backup, boundary=boundary) == before, 'backup_verification')
    replace_with_rollback(env_path, before, after, boundary)
    return {'status': 'applied', 'project': PROJECT, 'sha256': sha(after),
            'backup': str(backup), 'backupSha256': sha(before),
            'receiptSha256': sha(read_private(bundle / 'receipt.json', boundary=boundary))}


def restore_backup(backup, expected_current, expected_backup, env_path=ENV_PATH,
                   backup_root=BACKUP_ROOT, boundary=Path('/')):
    require(all(re.fullmatch(r'[a-fA-F0-9]{64}', v or '') for v in (expected_current, expected_backup)),
            'invalid_hash')
    backup = Path(backup)
    require(backup.is_absolute() and '..' not in backup.parts and backup.name == 'preimage.env'
            and backup.parent.parent == backup_root, 'unowned_backup')
    for directory in (backup_root, backup.parent):
        check_parents(directory, boundary)
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 0
                and stat.S_IMODE(info.st_mode) == 0o700, 'unsafe_backup_directory')
    before = read_private(backup, boundary=boundary)
    receipt = strict_json(read_private(backup.parent / 'receipt.json', cap=8192, boundary=boundary))
    require(isinstance(receipt, dict) and receipt.get('version') == 1
            and receipt.get('environment') == str(env_path) and receipt.get('backup') == str(backup)
            and receipt.get('beforeSha256') == sha(before) == expected_backup.lower()
            and receipt.get('beforeBytes') == len(before)
            and (receipt.get('uid'), receipt.get('gid'), receipt.get('mode')) == (0, 0, '0600'),
            'backup_receipt_mismatch')
    current = read_private(env_path, boundary=boundary)
    require(sha(current) == expected_current.lower() == receipt.get('installedSha256')
            and len(current) == receipt.get('installedBytes'), 'restore_current_mismatch')
    # The backup must be the exact prefix of the installed, one-key-only addition.
    require(current.startswith(before) and len(configured_lines(current)) == 1
            and not configured_lines(before), 'restore_partition_mismatch')
    # Restoration reverses the prefix relation, so verify equality separately.
    require(read_private(env_path, boundary=boundary) == current, 'current_file_changed')
    try:
        atomic_replace(env_path, before)
        require(read_private(env_path, boundary=boundary) == before, 'restore_verification')
    except Exception:
        try:
            actual = read_private(env_path, boundary=boundary)
            require(actual in (before, current), 'rollback_state_changed')
            if actual == before:
                atomic_replace(env_path, current)
            require(read_private(env_path, boundary=boundary) == current, 'rollback_verification')
        except Exception:
            raise Refused('STOP_rollback_failed') from None
        raise Refused('restore_failed_rollback_verified') from None
    return {'status': 'restored', 'project': PROJECT, 'sha256': sha(before)}


@contextlib.contextmanager
def production_lock():
    import fcntl
    path = LOCK_PATH
    check_parents(path.parent)
    # Ubuntu's sole permitted alias; no arbitrary parent symlink traversal.
    if path.parent.is_symlink():
        alias = path.parent.lstat()
        require(path.parent == Path('/var/lock') and os.readlink(path.parent) in ('/run/lock', '../run/lock')
                and alias.st_uid == alias.st_gid == 0, 'unsafe_lock_alias')
        path = Path('/run/lock') / path.name
    check_parents(path.parent)
    parent = path.parent.lstat()
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == parent.st_gid == 0
            and (parent.st_mode & 0o022 == 0 or bool(parent.st_mode & stat.S_ISVTX)), 'unsafe_lock_parent')
    # The deploy wrapper owns/creates this inode. Inspect must never create it.
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == before.st_gid == 0
            and before.st_nlink == 1 and before.st_mode & 0o022 == 0, 'unsafe_lock_file')
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        current = os.fstat(fd)
        require((before.st_dev, before.st_ino) == (current.st_dev, current.st_ino), 'lock_changed')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('production_lock_busy') from None
        linked = path.lstat()
        require((current.st_dev, current.st_ino) == (linked.st_dev, linked.st_ino), 'lock_changed')
        yield
    finally:
        os.close(fd)


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('invalid_arguments')


def main():
    parser = QuietParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--restore', metavar='PRIVATE_PREIMAGE_PATH')
    parser.add_argument('--expected-current-sha256')
    parser.add_argument('--expected-backup-sha256')
    parser.add_argument('--expected-validated-input-sha256')
    try:
        args = parser.parse_args()
        require(sys.platform.startswith('linux') and os.geteuid() == 0, 'linux_root_required')
        require(bool(args.restore) == bool(args.expected_current_sha256)
                == bool(args.expected_backup_sha256), 'invalid_arguments')
        require(args.apply == bool(args.expected_validated_input_sha256), 'validated_input_hash_required')
        with production_lock():
            if args.apply:
                result = apply_account(sys.stdin.buffer.read(MAX_INPUT + 1), args.expected_validated_input_sha256)
            elif args.restore:
                result = restore_backup(args.restore, args.expected_current_sha256, args.expected_backup_sha256)
            else:
                raw = read_private(ENV_PATH)
                keys = configured_lines(raw)
                result = {'status': 'inspected', 'project': PROJECT, 'configured': bool(keys),
                          'sha256': sha(raw), 'bytes': len(raw)}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Refused as error:
        print(json.dumps({'status': 'refused', 'code': str(error)}))
    except Exception:
        print(json.dumps({'status': 'refused', 'code': 'runtime_failure'}))
    return 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Remove old deployment backups, retaining the newest three per environment."""
import datetime as dt
import fcntl
import hashlib
import os
import re
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path

ROOTS = (Path('/srv/abroj-baseer-production/backups'), Path('/srv/baseer-qa/backups'))
LOCKS = ('/var/lock/baseer-production-deploy.lock', '/var/lock/baseer-qa-deploy.lock')
PATTERN = re.compile(r'pre-[0-9a-f]{12}-[0-9]+-([0-9]{8}T[0-9]{6}Z)')


def valid_recovery_pair(folder, expected):
    manifest = folder / 'recovery.sha256'
    if manifest.is_symlink() or not manifest.is_file():
        return False
    entries = {}
    try:
        for line in manifest.read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
            if not match:
                return False
            path = Path(match.group(2))
            if not path.is_absolute():
                path = folder / path
            if path.parent != folder or path.name not in expected or path.name in entries:
                return False
            entries[path.name] = match.group(1)
        if set(entries) != set(expected):
            return False
        for name, digest in entries.items():
            path = folder / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                return False
            result = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(chunk)
            if result.hexdigest() != digest:
                return False
    except (OSError, UnicodeError):
        return False
    return True


def candidates(root, now, expected):
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise RuntimeError(f'unsafe backup root: {root}')
    found = []
    for item in root.iterdir():
        match = PATTERN.fullmatch(item.name)
        if not match or item.is_symlink() or not item.is_dir():
            continue
        try:
            timestamp = dt.datetime.strptime(match.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc)
        except ValueError as exc:
            raise RuntimeError(f'invalid backup timestamp: {item}') from exc
        if timestamp > now:
            raise RuntimeError(f'backup timestamp is in the future: {item}')
        found.append((timestamp, item.name, item))
    found.sort(reverse=True)
    verified = [path for _, _, path in found if valid_recovery_pair(path, expected)]
    if len(verified) < 3:
        raise RuntimeError(f'fewer than three verified recovery pairs: {root}')
    protected = set(verified[:3]) | {path for _, _, path in found[:3]}
    return [path for timestamp, _, path in found if path not in protected and path in verified and now - timestamp > dt.timedelta(days=7)]


def main():
    if sys.argv[1:] not in ([], ['--apply']):
        raise SystemExit('usage: backup-retention.py [--apply]')
    with ExitStack() as stack:
        for lock in LOCKS:
            handle = stack.enter_context(open(lock, 'a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = dt.datetime.now(dt.timezone.utc)
        pairs = (('baseer_prod.dump', 'filestore-baseer_prod.tar'), ('database.dump', 'filestore.tar'))
        targets = [path for root, pair in zip(ROOTS, pairs) for path in candidates(root, now, pair)]
        for target in targets:
            print(('DELETE ' if sys.argv[1:] else 'WOULD_DELETE ') + str(target), flush=True)
            if sys.argv[1:]:
                shutil.rmtree(target)
        print(f'COUNT={len(targets)}', flush=True)


if __name__ == '__main__':
    main()

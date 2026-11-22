#!/usr/bin/env python3
"""Remove old deployment backups, retaining the newest three per environment."""
import datetime as dt
import fcntl
import os
import re
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path

ROOTS = (Path('/srv/abroj-baseer-production/backups'), Path('/srv/baseer-qa/backups'))
LOCKS = ('/var/lock/baseer-production-deploy.lock', '/var/lock/baseer-qa-deploy.lock')
PATTERN = re.compile(r'pre-[0-9a-f]{12}-[0-9]+-([0-9]{8}T[0-9]{6}Z)')


def candidates(root, now):
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
    return [path for timestamp, _, path in found[3:] if now - timestamp > dt.timedelta(days=7)]


def main():
    if sys.argv[1:] not in ([], ['--apply']):
        raise SystemExit('usage: backup-retention.py [--apply]')
    with ExitStack() as stack:
        for lock in LOCKS:
            handle = stack.enter_context(open(lock, 'a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = dt.datetime.now(dt.timezone.utc)
        targets = [path for root in ROOTS for path in candidates(root, now)]
        for target in targets:
            print(('DELETE ' if sys.argv[1:] else 'WOULD_DELETE ') + str(target), flush=True)
            if sys.argv[1:]:
                shutil.rmtree(target)
        print(f'COUNT={len(targets)}', flush=True)


if __name__ == '__main__':
    main()

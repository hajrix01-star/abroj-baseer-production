import datetime as dt
import hashlib
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    import fcntl
except ImportError:
    sys.modules['fcntl'] = types.SimpleNamespace()
spec = importlib.util.spec_from_file_location('retention', Path(__file__).parents[1] / 'backup-retention.py')
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)
PAIR = ('database.dump', 'filestore.tar')
NOW = dt.datetime(2026, 11, 22, tzinfo=dt.timezone.utc)


def backup(root, days, number, complete=True):
    date = NOW - dt.timedelta(days=days)
    folder = root / f'pre-0123456789ab-{number}-{date:%Y%m%dT%H%M%SZ}'
    folder.mkdir()
    if complete:
        lines = []
        for name in PAIR:
            data = (name + str(number)).encode()
            (folder / name).write_bytes(data)
            lines.append(f'{hashlib.sha256(data).hexdigest()}  {folder / name}\n')
        (folder / 'recovery.sha256').write_text(''.join(lines), encoding='utf-8')
    return folder


class RetentionTest(unittest.TestCase):
    def test_keeps_three_verified_and_removes_only_expired(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            folders = [backup(root, 8+i, 100+i) for i in range(5)]
            (root / 'manual-important').mkdir()
            self.assertEqual(set(retention.candidates(root, NOW, PAIR)), set(folders[3:]))
            backup(root, 7, 200)
            self.assertNotIn(root / 'manual-important', retention.candidates(root, NOW, PAIR))

    def test_incomplete_recent_backups_cannot_replace_verified_floor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            folders = [backup(root, 8+i, 100+i) for i in range(4)]
            for i in range(3):
                backup(root, i, 200+i, complete=False)
            self.assertEqual(retention.candidates(root, NOW, PAIR), [folders[3]])
            (folders[0] / PAIR[0]).write_text('corrupted')
            self.assertEqual(retention.candidates(root, NOW, PAIR), [])
            (folders[1] / PAIR[0]).write_text('corrupted')
            with self.assertRaises(RuntimeError):
                retention.candidates(root, NOW, PAIR)

    def test_exactly_seven_days_and_future(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for i in range(4):
                backup(root, 7-i, 200+i)
            self.assertEqual(retention.candidates(root, NOW, PAIR), [])
            backup(root, -1, 300)
            with self.assertRaises(RuntimeError):
                retention.candidates(root, NOW, PAIR)

    @unittest.skipUnless(hasattr(sys.modules['fcntl'], 'flock'), 'requires Linux file locks')
    def test_apply_and_held_deployment_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            prod, qa = base / 'prod', base / 'qa'
            prod.mkdir()
            qa.mkdir()
            prod_pair = ('baseer_prod.dump', 'filestore-baseer_prod.tar')
            lock_paths = (str(base / 'prod.lock'), str(base / 'qa.lock'))
            global PAIR
            original_pair = PAIR
            try:
                PAIR = prod_pair
                prod_backups = [backup(prod, 8+i, 100+i) for i in range(4)]
                PAIR = original_pair
                qa_backups = [backup(qa, 8+i, 200+i) for i in range(4)]
            finally:
                PAIR = original_pair
            class Clock(dt.datetime):
                @classmethod
                def now(cls, tz=None):
                    return NOW
            with mock.patch.object(retention, 'ROOTS', (prod, qa)), mock.patch.object(retention, 'LOCKS', lock_paths), mock.patch.object(retention.dt, 'datetime', Clock), mock.patch.object(sys, 'argv', ['backup-retention.py', '--apply']):
                with open(lock_paths[0], 'a') as held:
                    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(BlockingIOError):
                        retention.main()
                    self.assertTrue(prod_backups[-1].exists())
                retention.main()
            self.assertFalse(prod_backups[-1].exists())
            self.assertFalse(qa_backups[-1].exists())
            self.assertTrue(all(p.exists() for p in prod_backups[:3] + qa_backups[:3]))


if __name__ == '__main__':
    unittest.main()

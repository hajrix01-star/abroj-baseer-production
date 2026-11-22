import datetime as dt
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.modules.setdefault('fcntl', types.SimpleNamespace())
spec = importlib.util.spec_from_file_location('retention', Path(__file__).parents[1] / 'backup-retention.py')
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)


class RetentionTest(unittest.TestCase):
    def test_age_and_minimum_and_unknown_names(self):
        now = dt.datetime(2026, 11, 22, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            names = []
            for i in range(5):
                date = now - dt.timedelta(days=8 + i)
                name = f'pre-0123456789ab-{100 + i}-{date:%Y%m%dT%H%M%SZ}'
                (root / name).mkdir()
                names.append(name)
            (root / 'manual-important').mkdir()
            result = retention.candidates(root, now)
            self.assertEqual({p.name for p in result}, set(names[3:]))
            for i in range(4):
                date = now - dt.timedelta(days=i)
                (root / f'pre-0123456789ab-{200 + i}-{date:%Y%m%dT%H%M%SZ}').mkdir()
            self.assertEqual({p.name for p in retention.candidates(root, now)}, set(names))

    def test_future_backup_fails_closed(self):
        now = dt.datetime(2026, 11, 22, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'pre-0123456789ab-123-20261123T000000Z').mkdir()
            with self.assertRaises(RuntimeError):
                retention.candidates(root, now)

    def test_exactly_seven_days_is_not_deleted(self):
        now = dt.datetime(2026, 11, 22, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for i in range(4):
                date = now - dt.timedelta(days=7-i)
                (root / f'pre-0123456789ab-{200+i}-{date:%Y%m%dT%H%M%SZ}').mkdir()
            self.assertEqual(retention.candidates(root, now), [])


if __name__ == '__main__':
    unittest.main()

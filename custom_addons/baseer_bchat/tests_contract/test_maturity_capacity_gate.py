"""Synthetic gate tests only: these are not measured Odoo samples."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import statistics
import unittest

ADDON = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capacity_gate', ADDON / 'tools/check_maturity_capacity.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def fixture():
    value = {
        'schema_version': 1, 'status': 'ok', 'error': None,
        'scope': 'odoo_service_db_json_commit_not_http_or_device',
        'database': 'bchat_maturity_test_20261017',
        'limits': {'statement_timeout_ms': 10000, 'lock_timeout_ms': 2000, 'total_budget_seconds': 300},
        'fixture': {'users': 50, 'rooms': 100, 'primary_members': 50, 'seed_messages': 500,
                    'final_messages': 531, 'ordinary_actor_verified': True, 'marker_verified': True},
        'sample_plan': {'warmups_per_operation': 1, 'sequential_per_operation': 10,
                        'concurrent_rounds': 10, 'workers_per_round': 2},
        'invariants': dict.fromkeys(('seed_exact', 'each_send_once', 'concurrent_initial_pids_distinct',
                                    'history_page_bounded', 'room_list_exact', 'search_page_bounded'), True),
        'cleanup': {'completed': True, 'marker_verified': True}, 'elapsed_ms': 1000,
        'samples': [], 'summary': {},
    }
    for op in gate.OPERATIONS:
        for i in range(1 if op == 'concurrent_send' else 0, 21 if op == 'concurrent_send' else 11):
            pid = 100 + (i % 2)
            value['samples'].append({
                'operation': op, 'sample': i, 'warmup': i == 0,
                'round': (i + 1) // 2 if op == 'concurrent_send' else None,
                'worker': 1 + (i - 1) % 2 if op == 'concurrent_send' else None,
                'page': {'send': 'write', 'history': 'latest', 'rooms': 'rooms100',
                         'search': 'search_hits', 'concurrent_send': 'write'}[op],
                'request_utf8_bytes': 80, 'response_utf8_bytes': 1000,
                'row_count': 100 if op == 'rooms' else 30 if op in ('history', 'search') else 1,
                'result': 'ok', 'error': None, 'elapsed_ms': 3 + i, 'attempt_count': 1,
                'initial_backend_pid': pid, 'final_backend_pid': pid,
                'attempts': [{'number': 1, 'backend_pid': pid, 'isolation': 'repeatable read',
                              'elapsed_ms': 2 + i, 'result': 'ok', 'sqlstate': None}],
            })
        measured = [s for s in value['samples'] if s['operation'] == op and not s['warmup']]
        value['summary'][op] = {
            'samples': len(measured), 'median_ms': statistics.median(s['elapsed_ms'] for s in measured),
            'max_ms': max(s['elapsed_ms'] for s in measured),
            'row_count_min': min(s['row_count'] for s in measured),
            'row_count_max': max(s['row_count'] for s in measured), 'response_utf8_bytes_max': 1000,
        }
    return value


class CapacityEvidenceGateTests(unittest.TestCase):
    def test_complete_synthetic_shape(self):
        self.assertEqual(gate.validate(fixture())['samples'], 64)

    def test_missing_failed_duplicate_and_fake_concurrency_are_rejected(self):
        changes = [lambda v: v['samples'].pop(),
                   lambda v: v['samples'][0].update(result='error'),
                   lambda v: v['samples'].__setitem__(1, deepcopy(v['samples'][0])),
                   lambda v: v['samples'][-1].update(initial_backend_pid=v['samples'][-2]['initial_backend_pid'])]
        for change in changes:
            with self.subTest(change=change):
                value = fixture()
                change(value)
                with self.assertRaises(ValueError):
                    gate.validate(value)

    def test_deadlock_timeout_and_unaccounted_retry_are_rejected(self):
        for sqlstate in ('40P01', '55P03', '57014', None):
            value = fixture()
            sample = value['samples'][0]
            sample['attempts'].insert(0, dict(sample['attempts'][0], result='serialization_retry', sqlstate=sqlstate))
            sample['attempts'][1]['number'] = 2
            sample['attempt_count'] = 2
            with self.subTest(sqlstate=sqlstate), self.assertRaises(ValueError):
                gate.validate(value)

    def test_wrong_scope_limits_identity_or_cleanup_rejected(self):
        for key, replacement in [('scope', 'device'), ('database', 'live'), ('elapsed_ms', float('nan')),
                                 ('cleanup', {'completed': False, 'marker_verified': True})]:
            value = fixture()
            value[key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.validate(value)
        for key in ('statement_timeout_ms', 'lock_timeout_ms', 'total_budget_seconds'):
            value = fixture()
            value['limits'][key] *= 2
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.validate(value)

    def test_unbounded_page_or_unverified_actor_rejected(self):
        value = fixture()
        value['fixture']['ordinary_actor_verified'] = False
        with self.assertRaises(ValueError):
            gate.validate(value)
        for key, replacement in [('row_count', 31), ('response_utf8_bytes', 131073), ('elapsed_ms', -1)]:
            value = fixture()
            next(s for s in value['samples'] if s['operation'] == 'history')[key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.validate(value)

    def test_summaries_must_match_raw_samples(self):
        for key in ('samples', 'median_ms', 'max_ms', 'row_count_max', 'response_utf8_bytes_max'):
            value = fixture()
            value['summary']['history'][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.validate(value)

    def test_raw_serialization_retry_is_allowed_with_total_elapsed(self):
        value = fixture()
        sample = value['samples'][0]
        sample['attempts'][0]['elapsed_ms'] = 1
        sample['attempts'].insert(0, dict(sample['attempts'][0], result='serialization_retry', sqlstate='40001'))
        sample['attempts'][1]['number'] = 2
        sample['attempt_count'] = 2
        self.assertEqual(gate.validate(value)['samples'], 64)

    def test_positive_samples_cannot_have_impossible_total_elapsed(self):
        for elapsed in (0, 100):
            value = fixture()
            value['elapsed_ms'] = elapsed
            with self.subTest(elapsed=elapsed), self.assertRaises(ValueError):
                gate.validate(value)


if __name__ == '__main__':
    unittest.main()

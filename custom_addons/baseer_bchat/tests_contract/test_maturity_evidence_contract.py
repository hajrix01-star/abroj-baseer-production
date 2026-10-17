"""Behavior of the evidence gate; synthetic logs are NOT ORM execution evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


ADDON = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bchat_maturity_evidence', ADDON / 'tools/check_maturity_evidence.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class MaturityEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        expected, _kinds = gate.expected_tests(ADDON)
        self.lines = ['INFO fixture odoo.addons.baseer_bchat.tests.%s: Starting %s ...' % key for key in sorted(expected)]
        self.lines.append('0 failed, 0 error(s) of %s tests' % len(expected))
        one = {'initial_backend_pid': 17, 'isolation': 'repeatable read', 'attempts': 1, 'state': 'ok'}
        two = dict(one, initial_backend_pid=18)
        quota_loser = dict(two, state='rate_limited', status=429, retry_after_seconds=60)
        self.probes = {
            'database': 'bchat_maturity_test_20261017',
            'permissions': {'phases': [{'first': deepcopy(one), 'second': deepcopy(two)} for _ in range(5)],
                            'message_count': 1, 'task_revision': 2, 'sequence_continuity': True},
            'social': {'phases': {name: [deepcopy(one), deepcopy(two)] for name in gate.SOCIAL_PHASES},
                       'room_preference_rows': 1, 'diagnostic_events': 10, 'diagnostic_idempotent_events': 1,
                       'daily_quota_winners': 1},
        }
        self.probes['social']['phases']['diagnostic_distinct_devices_daily_quota'] = [one, quota_loser]

    def verify(self):
        return gate.verify(ADDON, '\n'.join(self.lines), 'BCHAT_REAL_PROBES=' + json.dumps(self.probes), 'a' * 40)

    def test_complete_synthetic_evidence_shape_is_accepted(self):
        report = self.verify()
        self.assertEqual(report['real_postgres_phases'], 10)
        self.assertGreater(report['core_test_kinds']['http'], 0)
        self.assertGreater(report['core_test_kinds']['orm'], 0)
        self.assertGreater(report['core_test_kinds']['basecase'], 0)
        _expected, kinds = gate.expected_tests(ADDON)
        self.assertEqual(kinds[('test_mobile_upload_grants',
                               'BChatMobileUploadGrantCase.test_grant_is_single_use_scope_and_direct_model_access_is_denied')], 'orm')

    def test_missing_test_start_is_rejected(self):
        del self.lines[0]
        with self.assertRaisesRegex(ValueError, 'Missing core test starts'):
            self.verify()

    def test_skipped_test_is_rejected_even_with_clean_summary(self):
        self.lines.append('INFO fixture odoo.addons.baseer_bchat.tests.test_text_v2: skipped Example.test_one : HR missing')
        with self.assertRaisesRegex(ValueError, 'skip'):
            self.verify()

    def test_failing_summary_and_summary_count_mismatch_are_rejected(self):
        original = self.lines[-1]
        for replacement in ('1 failed, 0 error(s) of 200 tests', '0 failed, 1 error(s) of 200 tests', '0 failed, 0 error(s) of 1 tests'):
            self.lines[-1] = replacement
            with self.assertRaises(ValueError):
                self.verify()
        self.lines[-1] = original

    def test_missing_probe_completion_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'completion'):
            gate.verify(ADDON, '\n'.join(self.lines), 'container exited 0', 'a' * 40)

    def test_missing_phase_or_stale_daily_count_is_rejected(self):
        self.probes['social']['diagnostic_events'] = 11
        with self.assertRaisesRegex(ValueError, 'Incomplete social'):
            self.verify()
        self.probes['social']['diagnostic_events'] = 10
        del self.probes['social']['phases']['diagnostic_same_uuid']
        with self.assertRaisesRegex(ValueError, 'Incomplete social'):
            self.verify()

    def test_same_connection_or_non_rr_is_rejected(self):
        rows = self.probes['permissions']['phases'][0]
        rows['second']['initial_backend_pid'] = 17
        with self.assertRaisesRegex(ValueError, 'independent RR'):
            self.verify()
        rows['second']['initial_backend_pid'] = 18
        rows['first']['isolation'] = 'read committed'
        with self.assertRaisesRegex(ValueError, 'independent RR'):
            self.verify()

    def test_quota_needs_explicit_429_not_two_successes(self):
        self.probes['social']['phases']['diagnostic_distinct_devices_daily_quota'][1]['state'] = 'ok'
        with self.assertRaisesRegex(ValueError, 'one winner'):
            self.verify()


if __name__ == '__main__':
    unittest.main()

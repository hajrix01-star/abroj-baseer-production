"""Behavior of the evidence gate; synthetic logs are NOT ORM execution evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import unittest


ADDON = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bchat_maturity_evidence', ADDON / 'tools/check_maturity_evidence.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def message_social_fixture():
    first = {'state': 'ok', 'attempts': 1, 'initial_backend_pid': 41, 'isolation': 'repeatable read'}
    second = dict(first, initial_backend_pid=42)
    one = dict(first, result={'api_version': 2, 'reaction_revision': 1, 'operation_revision': 1})
    conflict = dict(second, state='revision_conflict', status=409, result=None)
    saved = {'api_version': 2, 'saved': True, 'saved_revision': 1, 'operation_revision': 1,
             'client_uuid': '00000000-0000-4000-8000-000000000044'}
    return {
        'database': 'bchat_maturity_test_20261017', 'independent_backends': 2,
        'phases': {
            'reaction_absent_cas': [one, conflict],
            'saved_same_uuid': [dict(first, result=dict(saved, replayed=False)),
                                dict(second, result=dict(saved, replayed=True))],
            'legacy_social_empty_mentions': [dict(first, result={'api_version': 2, 'message_id': 71}),
                                             dict(second, result={'api_version': 2, 'message_id': 71})],
            'explicit_mentions_same_uuid': [dict(first, result={'api_version': 2, 'message_id': 72}),
                                            dict(second, result={'api_version': 2, 'message_id': 72})],
        },
        'reaction_rows': 1, 'reaction_revision': 1, 'saved_rows': 1, 'saved_revision': 1,
        'legacy_social_message_count': 1, 'explicit_message_count': 1, 'mention_rows': 1,
        'operation_receipts': 2, 'receipt_timestamps_unchanged': True,
        'fresh_mention_replay_verified': True, 'fresh_mention_digest_conflict_rejected': True,
        'fresh_replay_witness': 'direct_read_only_helper_not_forced_unique_violation',
        'cleanup_completed': True,
    }


class MaturityEvidenceGateTests(unittest.TestCase):
    def test_isolated_images_are_valid_sha256_and_match_the_existing_project_pin(self):
        workflow = (ADDON.parents[1] / '.github/workflows/bchat-cumulative-contracts.yml').read_text(encoding='utf-8')
        runner = (ADDON / 'tools/run_maturity_isolated.sh').read_text(encoding='utf-8')
        existing = (ADDON.parents[1] / '.github/workflows/test-baseer-aged-receivable.yml').read_text(encoding='utf-8')
        images = re.findall(r'(?:odoo|postgres)@sha256:[0-9a-f]+', workflow)
        self.assertEqual(len(images), 3)  # Native body plus isolated Odoo/PG.
        for image in images:
            self.assertRegex(image, r'@sha256:[0-9a-f]{64}$')
            self.assertIn(image, runner)
        postgres = next(image for image in images if image.startswith('postgres@'))
        self.assertIn(postgres, existing)
        self.assertIn('preparation.log', workflow)
        self.assertIn('--kill-after=15s --signal=TERM 16m', runner)
        self.assertIn('--kill-after=15s --signal=TERM 4m', runner)
        self.assertIn('statement_timeout=45000 -c lock_timeout=10000', runner)
        self.assertIn('failure-db-state.log', runner)
        self.assertIn('pg_blocking_pids(pid)', runner)
        self.assertIn('timeout --kill-after=2s 5s docker inspect', runner)
        self.assertNotIn('query FROM pg_stat_activity', runner)

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
                            'message_count': 1, 'task_revision': 2, 'sequence_continuity': True,
                            'skip_locked_exclusion': {
                                'initial_backend_pids': [17, 18], 'isolations': ['repeatable read', 'repeatable read'],
                                'statement_timeout_ms': 3000, 'lock_timeout_ms': 2000,
                                'locked_excluded': True, 'claimed_after_release': True,
                                'provider_calls_while_locked': 0, 'provider_calls_after_release': 1,
                                'final_state': 'sent', 'synthetic_fixture_removed_before_races': True},
                            'room_lock_compatibility': {
                                'initial_backend_pids': [33, 34], 'isolations': ['repeatable read', 'repeatable read'],
                                'statement_timeout_ms': 3000, 'lock_timeout_ms': 2000,
                                'hint_writer_completed_while_room_locked': True,
                                'permission_hint_created': True, 'room_hint_created': True,
                                'mutation_excluded': True, 'read_share_excluded': True,
                                'mutation_exclusion_sqlstate': '55P03', 'read_share_exclusion_sqlstate': '55P03',
                                'claimed_after_release': True, 'fixture_marker_verified': True,
                                'original_permission_restored': True}},
            'social': {'phases': {name: [deepcopy(one), deepcopy(two)] for name in gate.SOCIAL_PHASES},
                       'room_preference_rows': 1, 'diagnostic_events': 10, 'diagnostic_idempotent_events': 1,
                       'daily_quota_winners': 1},
            'message_social': message_social_fixture(),
        }
        self.probes['social']['phases']['diagnostic_distinct_devices_daily_quota'] = [one, quota_loser]

    def verify(self):
        return gate.verify(ADDON, '\n'.join(self.lines), 'BCHAT_REAL_PROBES=' + json.dumps(self.probes), 'a' * 40)

    def test_complete_synthetic_evidence_shape_is_accepted(self):
        report = self.verify()
        self.assertEqual(report['real_postgres_phases'], 10)
        self.assertEqual(report['message_social_real_postgres_phases'], 4)
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

    def test_message_social_completion_and_each_rr_phase_are_required(self):
        del self.probes['message_social']
        with self.assertRaisesRegex(ValueError, 'message social'):
            self.verify()
        self.probes['message_social'] = message_social_fixture()
        for name in gate.MESSAGE_SOCIAL_PHASES:
            original = deepcopy(self.probes['message_social']['phases'][name])
            for mutation in ('missing', 'same_pid', 'wrong_isolation', 'failed'):
                rows = deepcopy(original)
                if mutation == 'missing':
                    rows.pop()
                elif mutation == 'same_pid':
                    rows[1]['initial_backend_pid'] = rows[0]['initial_backend_pid']
                elif mutation == 'wrong_isolation':
                    rows[1]['isolation'] = 'read committed'
                else:
                    rows[0]['state'] = '40P01'
                self.probes['message_social']['phases'][name] = rows
                with self.subTest(phase=name, mutation=mutation), self.assertRaises(ValueError):
                    self.verify()
            self.probes['message_social']['phases'][name] = original

    def test_message_social_counts_fresh_helper_and_cleanup_cannot_be_omitted(self):
        for key in ('receipt_timestamps_unchanged', 'fresh_mention_replay_verified',
                    'fresh_mention_digest_conflict_rejected', 'cleanup_completed'):
            value = message_social_fixture()
            value[key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_message_social(value)
        for key in ('mention_rows', 'explicit_message_count', 'operation_receipts', 'reaction_revision'):
            value = message_social_fixture()
            value[key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_message_social(value)
        value = message_social_fixture()
        value['phases']['saved_same_uuid'][1]['result']['replayed'] = False
        with self.assertRaises(ValueError):
            gate.verify_message_social(value)
        value = message_social_fixture()
        value['fresh_replay_witness'] = 'forced_unique_violation'
        with self.assertRaises(ValueError):
            gate.verify_message_social(value)

    def test_message_social_response_revisions_are_strict_integers(self):
        for phase, indexes, fields in (
                ('reaction_absent_cas', (0,), ('reaction_revision', 'operation_revision')),
                ('saved_same_uuid', (0, 1), ('saved_revision', 'operation_revision'))):
            for index in indexes:
                for field in fields:
                    for invalid in (True, 1.0, '1'):
                        value = message_social_fixture()
                        value['phases'][phase][index]['result'][field] = invalid
                        with self.subTest(phase=phase, row=index, field=field, invalid=invalid), self.assertRaises(ValueError):
                            gate.verify_message_social(value)

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

    def test_skip_locked_primitive_cannot_be_dropped_or_faked_by_the_same_connection(self):
        witness = self.probes['permissions'].pop('skip_locked_exclusion')
        with self.assertRaisesRegex(ValueError, 'SKIP LOCKED'):
            self.verify()
        self.probes['permissions']['skip_locked_exclusion'] = witness
        witness['initial_backend_pids'] = [17, 17]
        with self.assertRaisesRegex(ValueError, 'SKIP LOCKED'):
            self.verify()
        witness['initial_backend_pids'] = [17, 18]
        witness['provider_calls_while_locked'] = 1
        with self.assertRaisesRegex(ValueError, 'SKIP LOCKED'):
            self.verify()
        witness['provider_calls_while_locked'] = 0
        witness['synthetic_fixture_removed_before_races'] = False
        with self.assertRaisesRegex(ValueError, 'SKIP LOCKED'):
            self.verify()

    def test_missing_phase_or_stale_daily_count_is_rejected(self):
        self.probes['social']['diagnostic_events'] = 11
        with self.assertRaisesRegex(ValueError, 'Incomplete social'):
            self.verify()
        self.probes['social']['diagnostic_events'] = 10
        del self.probes['social']['phases']['diagnostic_same_uuid']
        with self.assertRaisesRegex(ValueError, 'Incomplete social'):
            self.verify()

    def test_room_fk_compatibility_and_real_mutator_reader_exclusion_are_required(self):
        witness = self.probes['permissions'].pop('room_lock_compatibility')
        with self.assertRaisesRegex(ValueError, 'room-lock'):
            self.verify()
        self.probes['permissions']['room_lock_compatibility'] = witness
        for key, wrong in (
                ('initial_backend_pids', [33, 33]),
                ('isolations', ['read committed', 'repeatable read']),
                ('hint_writer_completed_while_room_locked', False),
                ('permission_hint_created', False), ('room_hint_created', False),
                ('mutation_excluded', False), ('read_share_excluded', False),
                ('mutation_exclusion_sqlstate', '40P01'), ('read_share_exclusion_sqlstate', '40001'),
                ('claimed_after_release', False), ('original_permission_restored', False)):
            original = witness[key]
            witness[key] = wrong
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'room-lock'):
                self.verify()
            witness[key] = original

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

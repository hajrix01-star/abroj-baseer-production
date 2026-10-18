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


def receipt_delivery_fixture():
    first = {'state': 'ok', 'attempts': 1, 'initial_backend_pid': 51, 'isolation': 'repeatable read'}
    result = {'api_version': 2, 'message_id': 81, 'delivered_at': '2026-10-18 01:02:03',
              'read_at': None, 'unread_count': 2, 'last_message_id': 82, 'replayed': False}
    return {'database': 'bchat_maturity_test_20261017',
            'late_commit': {'writer_pids': [61, 62], 'writer_isolations': ['repeatable read', 'repeatable read'],
                'low_receipt_id': 71, 'high_receipt_id': 72, 'first_page_only_high': True,
                'continuation_excludes_late_low': True, 'reset_finds_late_low': True,
                'canonical_has_current_epoch': True, 'writer_fixture': 'protected_seed_no_feed_send_claim',
                'reads': [{'backend_pid': 63, 'isolation': 'repeatable read', 'transaction_id': 1001,
                           'after_id': 0, 'receipt_ids': [72], 'next_after_id': 72},
                          {'backend_pid': 63, 'isolation': 'repeatable read', 'transaction_id': 1002,
                           'after_id': 72, 'receipt_ids': [], 'next_after_id': 0},
                          {'backend_pid': 63, 'isolation': 'repeatable read', 'transaction_id': 1003,
                           'after_id': 0, 'receipt_ids': [71, 72], 'next_after_id': 72}]},
            'ack_two_devices': [dict(first, result=result),
                                dict(first, initial_backend_pid=52, result=dict(result, replayed=True))],
            'receipt_rows': 1, 'stable_delivered_timestamp': True, 'read_not_fabricated': True,
            'original_receipts_unchanged': True, 'cleanup_counts': {'remaining_owned': 0}, 'cleanup_completed': True}


def membership_cancel_fixture():
    # Gate-test input only. This fabricated log is never retained as runtime evidence.
    value = {'database': 'bchat_maturity_test_20261017', 'phases': {},
             'cleanup': {'remaining_rooms': 0, 'remaining_users': 0}}
    token = '00000000-0000-4000-8000-000000000088'
    for name in gate.MEMBERSHIP_CANCEL_PHASES:
        cancel_first = name in ('cancel_before_original', 'late_original_payload_conflict')
        conflict = name == 'late_original_payload_conflict'
        current = 1 if cancel_first else (3 if name == 'rr_wait_applied_current' else 2)
        cancelled = {'api_version': 2, 'room_id': 1, 'membership_id': 2,
                     'client_uuid': token, 'expected_revision': 1, 'cancelled': True}
        rows = []
        for index in range(2):
            initial = {'backend_pid': 71 + index, 'txid': 2001 + index,
                       'isolation': 'repeatable read', 'snapshot_revision': 1}
            row = {'state': 'ok', 'initial': initial, 'attempts': 1,
                   'retry_sqlstates': [], 'fresh': None,
                   'final_backend_pid': 71 + index, 'final_txid': 2001 + index}
            if conflict and index:
                row.update(state='idempotency_conflict', status=409)
            elif cancel_first:
                row['result'] = dict(cancelled)
            else:
                advanced = name == 'rr_wait_applied_current' and index == 1
                row['result'] = {'api_version': 2, 'client_uuid': token, 'room_id': 1, 'membership_id': 2,
                                 'operation_revision': 2, 'revision': 2 if index == 0 else current,
                                 'replayed': bool(index), 'pinned': not advanced,
                                 'archived': not advanced, 'muted': advanced}
                if index:
                    row['fresh'] = {'backend_pid': 73, 'txid': 2003,
                                    'read_only': 'on', 'isolation': 'repeatable read'}
            rows.append(row)
        value['phases'][name] = {
            'transactions': rows,
            'advisory_wait': None if conflict else {'backend_pid': 72, 'wait_event_type': 'Lock',
                'wait_event': 'advisory', 'ungranted_advisory_locks': 1},
            'postcheck': {'preference_revisions': [] if current == 1 else [current],
                'operation_count': 2 if current == 3 else 1,
                'original_result': {'cancelled': True} if cancel_first else {'revision': 2},
                'change_hint_delta': 0 if current == 1 else current - 1}}
    return value


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
            'receipt_delivery': receipt_delivery_fixture(),
            'membership_cancel': membership_cancel_fixture(),
        }
        self.probes['social']['phases']['diagnostic_distinct_devices_daily_quota'] = [one, quota_loser]

    def verify(self):
        return gate.verify(ADDON, '\n'.join(self.lines), 'BCHAT_REAL_PROBES=' + json.dumps(self.probes), 'a' * 40)

    def test_complete_synthetic_evidence_shape_is_accepted(self):
        report = self.verify()
        self.assertEqual(report['real_postgres_phases'], 10)
        self.assertEqual(report['message_social_real_postgres_phases'], 4)
        self.assertEqual(report['receipt_delivery_real_postgres_phases'], 2)
        self.assertEqual(report['membership_cancel_real_postgres_phases'], 4)
        self.assertGreater(report['core_test_kinds']['http'], 0)
        self.assertGreater(report['core_test_kinds']['orm'], 0)
        self.assertGreater(report['core_test_kinds']['basecase'], 0)
        _expected, kinds = gate.expected_tests(ADDON)
        self.assertEqual(kinds[('test_mobile_upload_grants',
                               'BChatMobileUploadGrantCase.test_grant_is_single_use_scope_and_direct_model_access_is_denied')], 'orm')

    def test_receipt_delivery_witness_cannot_be_omitted(self):
        del self.probes['receipt_delivery']
        with self.assertRaisesRegex(ValueError, 'receipt delivery'):
            self.verify()

    def test_cancel_all_phases_and_actual_witnesses_are_required(self):
        del self.probes['membership_cancel']
        with self.assertRaisesRegex(ValueError, 'cancellation'):
            self.verify()
        for name in gate.MEMBERSHIP_CANCEL_PHASES:
            value = membership_cancel_fixture()
            del value['phases'][name]
            with self.subTest(phase=name), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)
        for key, bad in (('backend_pid', 71), ('backend_pid', True), ('txid', 2001),
                         ('isolation', 'read committed'), ('snapshot_revision', True)):
            value = membership_cancel_fixture()
            value['phases']['cancel_before_original']['transactions'][1]['initial'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)

    def test_cancel_retry_is_serialization_only_and_bounded(self):
        for attempts, retries in ((True, []), (7, ['40001'] * 6), (2, []), (2, ['40P01'])):
            value = membership_cancel_fixture()
            value['phases']['cancel_before_original']['transactions'][0].update(
                attempts=attempts, retry_sqlstates=retries)
            with self.subTest(attempts=attempts, retries=retries), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)
        value = membership_cancel_fixture()
        value['phases']['cancel_before_original']['transactions'][0].update(attempts=2, retry_sqlstates=['40001'])
        gate.verify_membership_cancel(value)

    def test_cancel_strict_receipt_and_late_conflict_cannot_be_weakened(self):
        for key, bad in (('api_version', True), ('room_id', True), ('membership_id', 0),
                         ('expected_revision', True), ('cancelled', 1), ('cancelled', False),
                         ('client_uuid', 'not-a-uuid'), ('snapshot', {})):
            value = membership_cancel_fixture()
            value['phases']['cancel_before_original']['transactions'][0]['result'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)
        for key, bad in (('status', 200), ('status', 409.0), ('state', 'revision_conflict'), ('result', {})):
            value = membership_cancel_fixture()
            value['phases']['late_original_payload_conflict']['transactions'][1][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)
        for key, bad in (('api_version', 2.0), ('cancelled', 1), ('expected_revision', True)):
            value = membership_cancel_fixture()
            value['phases']['cancel_before_original']['transactions'][1]['result'][key] = bad
            with self.subTest(second_key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)

    def test_cancel_advisory_wait_and_fresh_primary_snapshot_are_mandatory(self):
        for key, bad in (('backend_pid', True), ('backend_pid', 71), ('wait_event_type', 'IO'),
                         ('wait_event', 'relation'), ('ungranted_advisory_locks', True),
                         ('ungranted_advisory_locks', 0)):
            value = membership_cancel_fixture()
            value['phases']['original_before_cancel']['advisory_wait'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)
        for key, bad in (('backend_pid', 72), ('backend_pid', True), ('txid', 2002),
                         ('read_only', 'off'), ('isolation', 'read committed')):
            value = membership_cancel_fixture()
            value['phases']['rr_wait_applied_current']['transactions'][1]['fresh'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)

    def test_cancel_fresh_snapshot_may_reuse_closed_winner_but_never_current_retry(self):
        value = membership_cancel_fixture()
        waiter = value['phases']['rr_wait_applied_current']['transactions'][1]
        waiter.update(attempts=2, retry_sqlstates=['40001'], final_backend_pid=74, final_txid=2004)
        waiter['fresh'].update(backend_pid=71, txid=2005)
        gate.verify_membership_cancel(value)
        for key, bad in (('backend_pid', 74), ('txid', 2004)):
            altered = deepcopy(value)
            altered['phases']['rr_wait_applied_current']['transactions'][1]['fresh'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(altered)
        for key in ('final_backend_pid', 'final_txid'):
            for bad in (None, True, 0):
                altered = deepcopy(value)
                altered['phases']['rr_wait_applied_current']['transactions'][1][key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    gate.verify_membership_cancel(altered)

    def test_cancel_applied_room_membership_and_revision2_bits_remain_exact(self):
        for key, bad in (('room_id', None), ('room_id', True), ('room_id', 3),
                         ('membership_id', None), ('membership_id', False), ('membership_id', 3),
                         ('pinned', False), ('archived', 1), ('muted', True)):
            value = membership_cancel_fixture()
            value['phases']['original_before_cancel']['transactions'][1]['result'][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)

    def test_cancel_applied_current_ack_cannot_be_replaced_by_old_or_cancelled_result(self):
        for key, bad in (('revision', 2), ('revision', 3.0), ('operation_revision', True),
                         ('replayed', 1), ('client_uuid', '00000000-0000-4000-8000-000000000089'),
                         ('cancelled', False), ('pinned', True), ('archived', 0), ('muted', False)):
            value = membership_cancel_fixture()
            value['phases']['rr_wait_applied_current']['transactions'][1]['result'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)

    def test_cancel_counts_immutable_result_and_cleanup_are_strict(self):
        for key, bad in (('preference_revisions', [2]), ('operation_count', True),
                         ('change_hint_delta', True), ('original_result', {'cancelled': 1})):
            value = membership_cancel_fixture()
            value['phases']['cancel_before_original']['postcheck'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)
        for key, bad in (('remaining_rooms', True), ('remaining_rooms', 1), ('remaining_users', '0')):
            value = membership_cancel_fixture(); value['cleanup'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.verify_membership_cancel(value)
        value = membership_cancel_fixture()
        value['phases']['original_before_cancel']['postcheck']['original_result']['revision'] = 2.0
        with self.assertRaises(ValueError): gate.verify_membership_cancel(value)

    def test_receipt_late_commit_ids_backends_reset_and_truthful_fixture_are_required(self):
        for key, bad in (('writer_pids', [61, 61]), ('writer_pids', [True, 62]),
                         ('writer_isolations', ['read committed', 'repeatable read']),
                         ('low_receipt_id', True), ('low_receipt_id', 72), ('high_receipt_id', '72'),
                         ('first_page_only_high', False), ('continuation_excludes_late_low', False),
                         ('reset_finds_late_low', False), ('canonical_has_current_epoch', False),
                         ('writer_fixture', 'normal_service_concurrency')):
            value = receipt_delivery_fixture(); value['late_commit'][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                gate.verify_receipt_delivery(value)

    def test_receipt_ack_requires_independent_rr_stable_timestamps_and_no_read(self):
        for key, bad in (('initial_backend_pid', 51), ('initial_backend_pid', True), ('isolation', 'read committed'),
                         ('attempts', True), ('attempts', 7), ('state', '40P01')):
            value = receipt_delivery_fixture(); value['ack_two_devices'][1][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError): gate.verify_receipt_delivery(value)

    def test_receipt_fresh_reader_transactions_and_raw_page_ids_cannot_be_faked(self):
        for index, key, bad in ((0, 'backend_pid', 61), (0, 'transaction_id', True),
                                (1, 'transaction_id', 1001), (1, 'after_id', 0),
                                (0, 'receipt_ids', [71, 72]), (2, 'receipt_ids', [72]),
                                (0, 'next_after_id', 0), (1, 'receipt_ids', [71])):
            value = receipt_delivery_fixture(); value['late_commit']['reads'][index][key] = bad
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                gate.verify_receipt_delivery(value)
        for key, bad in (('api_version', True), ('message_id', 1.0), ('unread_count', True),
                         ('read_at', '2026-10-18 01:02:03'), ('replayed', False),
                         ('delivered_at', '2026-02-31 01:02:03'), ('delivered_at', '2026-10-18 01:02:04')):
            value = receipt_delivery_fixture(); value['ack_two_devices'][1]['result'][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError): gate.verify_receipt_delivery(value)

    def test_receipt_ack_counts_and_cleanup_must_be_actual_booleans_integers(self):
        for key, bad in (('receipt_rows', True), ('receipt_rows', 2), ('stable_delivered_timestamp', 1),
                         ('read_not_fabricated', False), ('original_receipts_unchanged', False),
                         ('cleanup_counts', {'remaining_owned': True}), ('cleanup_counts', {'remaining_owned': 1}),
                         ('cleanup_completed', False)):
            value = receipt_delivery_fixture(); value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError): gate.verify_receipt_delivery(value)

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

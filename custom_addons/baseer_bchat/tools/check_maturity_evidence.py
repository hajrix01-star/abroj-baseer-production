"""Fail closed on missing core tests, skips or explicit real-RR probe evidence.

The pinned Odoo result logs Starting Class.method and a failed/error/test summary.
See odoo/odoo 19.0 odoo/tests/{loader,result}.py. No success is inferred from a
container exit code alone. ORM/HTTP and pure BaseCase tests remain distinguishable.
"""
import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import re


SOCIAL_PHASES = {
    'absent_room_preference_cas', 'preview_same_uuid', 'diagnostic_same_uuid',
    'diagnostic_distinct_devices_daily_quota', 'direct_reverse_pair',
}
MESSAGE_SOCIAL_PHASES = {
    'reaction_absent_cas', 'saved_same_uuid', 'legacy_social_empty_mentions', 'explicit_mentions_same_uuid',
}
MEMBERSHIP_CANCEL_PHASES = {
    'cancel_before_original', 'original_before_cancel',
    'rr_wait_applied_current', 'late_original_payload_conflict',
}


def verify_membership_cancel(value):
    """Validate retained real witnesses, never infer PG execution from a process exit."""
    if not isinstance(value, dict) or value.get('database') != 'bchat_maturity_test_20261017':
        raise ValueError('Missing membership cancellation real PostgreSQL proof')
    phases = value.get('phases')
    if not isinstance(phases, dict) or set(phases) != MEMBERSHIP_CANCEL_PHASES:
        raise ValueError('Missing membership cancellation phases')

    def integer(item, minimum=1, maximum=None):
        return type(item) is int and item >= minimum and (maximum is None or item <= maximum)

    def cancellation(result):
        return (isinstance(result, dict) and set(result) == {
            'api_version', 'room_id', 'membership_id', 'client_uuid', 'expected_revision', 'cancelled'}
            and type(result['api_version']) is int and result['api_version'] == 2
            and integer(result['room_id'], maximum=2147483647)
            and integer(result['membership_id'], maximum=2147483647)
            and type(result['expected_revision']) is int and result['expected_revision'] == 1
            and isinstance(result['client_uuid'], str)
            and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', result['client_uuid'])
            and result['cancelled'] is True)

    for name, phase in phases.items():
        if not isinstance(phase, dict):
            raise ValueError('Invalid membership cancellation phase')
        rows = phase.get('transactions')
        if not isinstance(rows, list) or len(rows) != 2:
            raise ValueError('Cancellation requires two genuine transactions')
        pids, transactions = set(), set()
        for row in rows:
            initial = row.get('initial') if isinstance(row, dict) else None
            if (not isinstance(initial, dict) or not integer(initial.get('backend_pid'))
                    or not integer(initial.get('txid')) or initial.get('isolation') != 'repeatable read'
                    or type(initial.get('snapshot_revision')) is not int or initial['snapshot_revision'] != 1
                    or not integer(row.get('attempts'), maximum=6)
                    or not isinstance(row.get('retry_sqlstates'), list)
                    or len(row['retry_sqlstates']) != row['attempts'] - 1
                    or any(state != '40001' for state in row['retry_sqlstates'])
                    or (row.get('state') == 'ok' and (not integer(row.get('final_backend_pid'))
                        or not integer(row.get('final_txid'))))):
                raise ValueError('Cancellation requires independent real RR with bounded serialization-only retries')
            pids.add(initial['backend_pid'])
            transactions.add(initial['txid'])
        if len(pids) != 2 or len(transactions) != 2:
            raise ValueError('Cancellation reused a PostgreSQL backend or transaction')
        first, second = rows
        conflict = name == 'late_original_payload_conflict'
        cancel_first = name in ('cancel_before_original', 'late_original_payload_conflict')
        if first.get('state') != 'ok' or second.get('state') != ('idempotency_conflict' if conflict else 'ok'):
            raise ValueError('Unexpected cancellation race outcome')
        if cancel_first:
            if (not cancellation(first.get('result'))
                    or (conflict and (type(second.get('status')) is not int or second['status'] != 409
                                      or second.get('result') is not None))
                    or (not conflict and (not cancellation(second.get('result'))
                                          or first['result'] != second['result']))):
                raise ValueError('Cancellation did not fence the exact original intent')
        else:
            expected_current = 3 if name == 'rr_wait_applied_current' else 2
            for index, row in enumerate(rows):
                result = row.get('result')
                if (not isinstance(result, dict) or 'cancelled' in result
                        or type(result.get('api_version')) is not int or result['api_version'] != 2
                        or type(result.get('operation_revision')) is not int or result['operation_revision'] != 2
                        or type(result.get('revision')) is not int or result['revision'] != (2 if index == 0 else expected_current)
                        or not integer(result.get('room_id'), maximum=2147483647)
                        or not integer(result.get('membership_id'), maximum=2147483647)
                        or result.get('replayed') is not bool(index)
                        or not isinstance(result.get('client_uuid'), str)
                        or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', result['client_uuid'])):
                    raise ValueError('Cancellation replay lost the applied/current revision')
            if any(first['result'][key] != second['result'][key] for key in ('client_uuid', 'room_id', 'membership_id')):
                raise ValueError('Cancellation replay belongs to another intent')
            fresh = second.get('fresh')
            if (not isinstance(fresh, dict) or not integer(fresh.get('backend_pid'))
                    or fresh['backend_pid'] == second['final_backend_pid']
                    or not integer(fresh.get('txid')) or fresh['txid'] == second['final_txid']
                    or fresh.get('read_only') != 'on' or fresh.get('isolation') != 'repeatable read'):
                raise ValueError('Cancellation needs a separate primary read-only replay snapshot')
            for index, row in enumerate(rows):
                advanced = name == 'rr_wait_applied_current' and index == 1
                if any(row['result'].get(key) is not expected for key, expected in (
                        ('pinned', not advanced), ('archived', not advanced), ('muted', advanced))):
                    raise ValueError('Cancellation replay returned the wrong current snapshot')
        wait = phase.get('advisory_wait')
        if conflict:
            if wait is not None:
                raise ValueError('Late-conflict phase cannot invent an advisory waiter')
        elif (not isinstance(wait, dict) or type(wait.get('backend_pid')) is not int
                or wait['backend_pid'] != second['initial']['backend_pid']
                or wait.get('wait_event_type') != 'Lock' or wait.get('wait_event') != 'advisory'
                or not integer(wait.get('ungranted_advisory_locks'))):
            raise ValueError('Missing genuine cancellation advisory-lock wait')
        post = phase.get('postcheck')
        current = 1 if cancel_first else (3 if name == 'rr_wait_applied_current' else 2)
        if (not isinstance(post, dict) or post.get('preference_revisions') != ([] if current == 1 else [current])
                or any(type(item) is not int for item in post.get('preference_revisions', []))
                or type(post.get('operation_count')) is not int or post['operation_count'] != (2 if current == 3 else 1)
                or type(post.get('change_hint_delta')) is not int or post['change_hint_delta'] != (0 if current == 1 else current - 1)
                or post.get('original_result') != ({'cancelled': True} if cancel_first else {'revision': 2})
                or (cancel_first and post['original_result'].get('cancelled') is not True)
                or (not cancel_first and type(post['original_result'].get('revision')) is not int)):
            raise ValueError('Cancellation changed preference/journal/hint counts')
    cleanup = value.get('cleanup')
    if (not isinstance(cleanup, dict) or set(cleanup) != {'remaining_rooms', 'remaining_users'}
            or any(type(item) is not int or item != 0 for item in cleanup.values())):
        raise ValueError('Cancellation cleanup is missing or incomplete')


def verify_message_social(value):
    if not isinstance(value, dict) or value.get('database') != 'bchat_maturity_test_20261017':
        raise ValueError('Missing message social real-race proof')
    phases = value.get('phases', {})
    if set(phases) != MESSAGE_SOCIAL_PHASES:
        raise ValueError('Missing message social phases')
    for rows in phases.values():
        if (not isinstance(rows, list) or len(rows) != 2
                or any(not isinstance(row, dict) or type(row.get('initial_backend_pid')) is not int or row['initial_backend_pid'] <= 0
                       or row.get('isolation') != 'repeatable read' or type(row.get('attempts')) is not int
                       or not 1 <= row['attempts'] <= 6 for row in rows)
                or len({row['initial_backend_pid'] for row in rows}) != 2):
            raise ValueError('Message social phases require independent real RR connections')
        for row in rows:
            if row.get('state') == 'ok' and (not isinstance(row.get('result'), dict)
                                            or type(row['result'].get('api_version')) is not int
                                            or row['result']['api_version'] != 2):
                raise ValueError('Message social successful response must be API v2')
    reaction = phases['reaction_absent_cas']
    if sorted(row.get('state', '') for row in reaction) != ['ok', 'revision_conflict']:
        raise ValueError('Message reaction CAS needs exactly one winner')
    loser = next(row for row in reaction if row['state'] == 'revision_conflict')
    winner = next(row for row in reaction if row['state'] == 'ok')
    if loser.get('status') != 409 or loser.get('result') is not None:
        raise ValueError('Message reaction loser must be explicit revision 409')
    result = winner.get('result', {})
    if any(type(result.get(key)) is not int or result[key] != 1
           for key in ('reaction_revision', 'operation_revision')):
        raise ValueError('Message reaction winner lost initial revision')
    saved = phases['saved_same_uuid']
    if (any(row.get('state') != 'ok'
            or any(type(row.get('result', {}).get(key)) is not int or row['result'][key] != 1
                   for key in ('operation_revision', 'saved_revision'))
            or row['result'].get('saved') is not True
            or type(row['result'].get('replayed')) is not bool for row in saved)
            or sorted(row['result']['replayed'] for row in saved) != [False, True]
            or not isinstance(saved[0]['result'].get('client_uuid'), str)
            or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', saved[0]['result']['client_uuid'])
            or saved[0]['result'].get('client_uuid') != saved[1]['result'].get('client_uuid')):
        raise ValueError('Saved same UUID must persist once and replay once')
    for name in ('legacy_social_empty_mentions', 'explicit_mentions_same_uuid'):
        rows = phases[name]
        if (any(row.get('state') != 'ok' or not isinstance(row.get('result'), dict)
                or type(row['result'].get('message_id')) is not int or row['result']['message_id'] <= 0 for row in rows)
                or rows[0]['result'] != rows[1]['result']):
            raise ValueError('Message UUID proof lost stable canonical ACK')
    for key, expected in {
            'reaction_rows': 1, 'reaction_revision': 1, 'saved_rows': 1, 'saved_revision': 1,
            'legacy_social_message_count': 1, 'explicit_message_count': 1, 'mention_rows': 1,
            'operation_receipts': 2}.items():
        if type(value.get(key)) is not int or value[key] != expected:
            raise ValueError('Message social count/revision proof missing: ' + key)
    if (any(value.get(key) is not True for key in (
            'receipt_timestamps_unchanged', 'fresh_mention_replay_verified',
            'fresh_mention_digest_conflict_rejected', 'cleanup_completed'))
            or value.get('fresh_replay_witness') != 'direct_read_only_helper_not_forced_unique_violation'
            or type(value.get('independent_backends')) is not int or value['independent_backends'] < 2):
        raise ValueError('Message social receipt/fresh-helper/cleanup proof incomplete')


def verify_receipt_delivery(value):
    if not isinstance(value, dict) or value.get('database') != 'bchat_maturity_test_20261017':
        raise ValueError('Missing receipt delivery real PostgreSQL proof')
    late = value.get('late_commit', {})
    pids = late.get('writer_pids')
    if (not isinstance(pids, list) or len(pids) != 2
            or any(type(pid) is not int or pid <= 0 for pid in pids) or len(set(pids)) != 2
            or late.get('writer_isolations') != ['repeatable read', 'repeatable read']
            or any(type(late.get(key)) is not int or not 0 < late[key] <= 2147483647
                   for key in ('low_receipt_id', 'high_receipt_id'))
            or late['low_receipt_id'] >= late['high_receipt_id']
            or any(late.get(key) is not True for key in (
                'first_page_only_high', 'continuation_excludes_late_low',
                'reset_finds_late_low', 'canonical_has_current_epoch'))
            or late.get('writer_fixture') != 'protected_seed_no_feed_send_claim'):
        raise ValueError('Receipt delivery late-commit/reset proof incomplete')
    reads = late.get('reads')
    if not isinstance(reads, list) or len(reads) != 3:
        raise ValueError('Receipt delivery needs three fresh reader snapshots')
    transactions = set()
    for index, row in enumerate(reads):
        if (not isinstance(row, dict) or type(row.get('backend_pid')) is not int or row['backend_pid'] <= 0
                or row['backend_pid'] in pids or row.get('isolation') != 'repeatable read'
                or type(row.get('transaction_id')) is not int or row['transaction_id'] <= 0
                or type(row.get('after_id')) is not int
                or row['after_id'] != (late['high_receipt_id'] if index == 1 else 0)):
            raise ValueError('Receipt delivery reader transaction/after cursor invalid')
        transactions.add(row['transaction_id'])
        ids = row.get('receipt_ids')
        if (not isinstance(ids, list) or len(ids) > 30
                or any(type(item) is not int or not row['after_id'] < item <= 2147483647 for item in ids)
                or ids != sorted(set(ids)) or type(row.get('next_after_id')) is not int
                or row['next_after_id'] != (ids[-1] if ids else 0)):
            raise ValueError('Receipt delivery reader page evidence invalid')
    if (len(transactions) != 3 or late['high_receipt_id'] not in reads[0]['receipt_ids']
            or late['low_receipt_id'] in reads[0]['receipt_ids']
            or late['low_receipt_id'] in reads[1]['receipt_ids']
            or late['low_receipt_id'] not in reads[2]['receipt_ids']):
        raise ValueError('Receipt delivery late commit was not witnessed across fresh snapshots')
    rows = value.get('ack_two_devices')
    if (not isinstance(rows, list) or len(rows) != 2
            or any(not isinstance(row, dict) or row.get('state') != 'ok'
                   or type(row.get('initial_backend_pid')) is not int or row['initial_backend_pid'] <= 0
                   or row.get('isolation') != 'repeatable read' or type(row.get('attempts')) is not int
                   or not 1 <= row['attempts'] <= 6 for row in rows)
            or len({row['initial_backend_pid'] for row in rows}) != 2):
        raise ValueError('Receipt delivery ACK needs two genuine RR backends')
    results = [row.get('result') for row in rows]
    fields = {'api_version', 'message_id', 'delivered_at', 'read_at', 'unread_count', 'last_message_id', 'replayed'}
    for result in results:
        if (not isinstance(result, dict) or not fields <= set(result)
                or type(result['api_version']) is not int or result['api_version'] != 2
                or any(type(result.get(key)) is not int or not 0 < result[key] <= 2147483647
                       for key in ('message_id', 'last_message_id'))
                or type(result['unread_count']) is not int or result['unread_count'] < 0
                or type(result['replayed']) is not bool or result['read_at'] is not None
                or not isinstance(result['delivered_at'], str)
                or not re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d', result['delivered_at'])):
            raise ValueError('Receipt delivery ACK result shape invalid')
        try:
            datetime.strptime(result['delivered_at'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise ValueError('Receipt delivery ACK timestamp invalid') from None
    if (sorted(result['replayed'] for result in results) != [False, True]
            or any(results[0][key] != results[1][key] for key in fields - {'replayed'})
            or type(value.get('receipt_rows')) is not int or value['receipt_rows'] != 1
            or any(value.get(key) is not True for key in (
                'stable_delivered_timestamp', 'read_not_fabricated', 'original_receipts_unchanged', 'cleanup_completed'))
            or not isinstance(value.get('cleanup_counts'), dict)
            or type(value['cleanup_counts'].get('remaining_owned')) is not int
            or value['cleanup_counts']['remaining_owned'] != 0):
        raise ValueError('Receipt delivery ACK stable replay/count/cleanup proof incomplete')


def expected_tests(addon):
    imports = ast.parse((addon / 'tests/__init__.py').read_text(encoding='utf-8'))
    expected = set()
    kinds = {}
    cases = []
    for node in imports.body:
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        for alias in node.names:
            if not alias.name.startswith('test_'):
                continue
            tree = ast.parse((addon / 'tests' / (alias.name + '.py')).read_text(encoding='utf-8'))
            for case in (item for item in tree.body if isinstance(item, ast.ClassDef)):
                cases.append((alias.name, case))
    inheritance = {case.name: [ast.unparse(base) for base in case.bases] for _module, case in cases}
    if len(inheritance) != len(cases):
        raise ValueError('Ambiguous test inheritance; update the inventory resolver')
    resolved = {'HttpCase': 'http', 'TransactionCase': 'orm', 'BaseCase': 'basecase'}

    def classify(name, seen=()):
        if name in resolved:
            return resolved[name]
        if name in seen or name not in inheritance:
            raise ValueError('Unknown test base: ' + name)
        bases = {classify(base, seen + (name,)) for base in inheritance[name]}
        if len(bases) != 1:
            raise ValueError('Ambiguous test base: ' + name)
        resolved[name] = bases.pop()
        return resolved[name]

    for module, case in cases:
        for method in (item for item in case.body if isinstance(item, ast.FunctionDef) and item.name.startswith('test_')):
            key = (module, case.name + '.' + method.name)
            expected.add(key)
            kinds[key] = classify(case.name)
    if len(expected) < 100:
        raise ValueError('Core test inventory unexpectedly shrank')
    return expected, kinds


def verify(addon, orm_log, probe_log, source_commit):
    if not re.fullmatch(r'[0-9a-f]{40}', source_commit):
        raise ValueError('Frozen source commit required')
    expected, kinds = expected_tests(addon)
    starts = re.findall(r'odoo\.addons\.baseer_bchat\.tests\.(test_\w+)(?:\.\w+)*: Starting (\w+\.test_\w+) \.\.\.', orm_log)
    missing = expected - set(starts)
    if missing:
        raise ValueError('Missing core test starts: ' + repr(sorted(missing)))
    if re.search(r'odoo\.addons\.baseer_bchat\.tests\.[^\n]*: skipped ', orm_log):
        raise ValueError('Unexpected core skip; HR is installed in this fixture')
    summaries = re.findall(r'(\d+) failed, (\d+) error\(s\) of (\d+) tests', orm_log)
    if not summaries or any(int(fail) or int(error) for fail, error, _count in summaries):
        raise ValueError('Missing or failed Odoo test summary')
    if int(summaries[-1][2]) != len(expected):
        raise ValueError('Odoo summary/inventory count differ')
    results = re.findall(r'^BCHAT_REAL_PROBES=(.+)$', probe_log, re.MULTILINE)
    if len(results) != 1:
        raise ValueError('Missing or duplicate real-probe completion')
    probes = json.loads(results[0])
    if probes.get('database') != 'bchat_maturity_test_20261017':
        raise ValueError('Unexpected probe database')
    permissions, social = probes['permissions'], probes['social']
    skip_locked = permissions.get('skip_locked_exclusion', {})
    pids = skip_locked.get('initial_backend_pids', [])
    if (len(pids) != 2 or any(type(pid) is not int or pid <= 0 for pid in pids) or len(set(pids)) != 2
            or skip_locked.get('isolations') != ['repeatable read', 'repeatable read']
            or skip_locked.get('statement_timeout_ms') != 3000 or skip_locked.get('lock_timeout_ms') != 2000
            or skip_locked.get('locked_excluded') is not True or skip_locked.get('claimed_after_release') is not True
            or skip_locked.get('provider_calls_while_locked') != 0 or skip_locked.get('provider_calls_after_release') != 1
            or skip_locked.get('final_state') != 'sent'
            or skip_locked.get('synthetic_fixture_removed_before_races') is not True):
        raise ValueError('Missing genuine dispatcher SKIP LOCKED exclusion/release proof')
    room_lock = permissions.get('room_lock_compatibility', {})
    room_pids = room_lock.get('initial_backend_pids', [])
    if (len(room_pids) != 2 or any(type(pid) is not int or pid <= 0 for pid in room_pids)
            or len(set(room_pids)) != 2
            or room_lock.get('isolations') != ['repeatable read', 'repeatable read']
            or room_lock.get('statement_timeout_ms') != 3000 or room_lock.get('lock_timeout_ms') != 2000
            or any(room_lock.get(key) is not True for key in (
                'hint_writer_completed_while_room_locked', 'permission_hint_created', 'room_hint_created',
                'mutation_excluded', 'read_share_excluded', 'claimed_after_release',
                'fixture_marker_verified', 'original_permission_restored'))
            or room_lock.get('mutation_exclusion_sqlstate') != '55P03'
            or room_lock.get('read_share_exclusion_sqlstate') != '55P03'):
        raise ValueError('Missing genuine room-lock FK compatibility and writer/reader exclusion proof')
    if (len(permissions['phases']) != 5 or permissions['message_count'] != 1
            or permissions['task_revision'] != 2 or permissions['sequence_continuity'] is not True):
        raise ValueError('Incomplete permission/sequence proof')
    if (set(social['phases']) != SOCIAL_PHASES or social['room_preference_rows'] != 1
            or social['diagnostic_events'] != 10 or social['diagnostic_idempotent_events'] != 1
            or social['daily_quota_winners'] != 1):
        raise ValueError('Incomplete social CAS/quota/idempotency proof')
    phases = [list(phase.values()) for phase in permissions['phases']] + list(social['phases'].values())
    for phase in phases:
        if (len(phase) != 2 or len({row['initial_backend_pid'] for row in phase}) != 2
                or any(type(row['initial_backend_pid']) is not int or row['initial_backend_pid'] <= 0 for row in phase)
                or any(row.get('isolation') != 'repeatable read' or not 1 <= row['attempts'] <= 6 for row in phase)):
            raise ValueError('Each phase needs two actual independent RR transactions with bounded attempts')
    quota = social['phases']['diagnostic_distinct_devices_daily_quota']
    if sorted(row['state'] for row in quota) != ['ok', 'rate_limited']:
        raise ValueError('Cross-device final daily slot did not have one winner')
    denied = next(row for row in quota if row['state'] == 'rate_limited')
    if denied.get('status') != 429 or not denied.get('retry_after_seconds'):
        raise ValueError('Quota refusal must be explicit 429 with retry guidance')
    verify_message_social(probes.get('message_social'))
    verify_receipt_delivery(probes.get('receipt_delivery'))
    verify_membership_cancel(probes.get('membership_cancel'))
    return {
        'source_commit': source_commit, 'core_tests': len(expected), 'skipped': 0,
        'core_test_kinds': {kind: sum(value == kind for value in kinds.values()) for kind in sorted(set(kinds.values()))},
        'real_postgres_phases': 10, 'dispatcher_skip_locked_proof': True,
        'room_lock_compatibility_proof': True, 'probes': probes,
        'message_social_real_postgres_phases': 4, 'fresh_mention_read_only_helper_proof': True,
        'receipt_delivery_real_postgres_phases': 2,
        'membership_cancel_real_postgres_phases': 4,
        'limitations': ['Core module only; procurement bridge not executed',
                        'Synthetic DB and provider boundary; no live/OEM/FCM delivery or phone performance acceptance'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--orm-log', type=Path, required=True)
    parser.add_argument('--probe-log', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = verify(args.root, args.orm_log.read_text(encoding='utf-8'), args.probe_log.read_text(encoding='utf-8'), args.source_commit)
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('BCHAT_CORE_ORM_EVIDENCE=PASS tests=%s phases=10 message_social_phases=4 receipt_delivery_phases=2 membership_cancel_phases=4 skips=0' % evidence['core_tests'])


if __name__ == '__main__':
    main()

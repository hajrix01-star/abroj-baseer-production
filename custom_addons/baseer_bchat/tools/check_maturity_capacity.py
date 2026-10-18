#!/usr/bin/env python3
"""Validate bounded real service/DB samples; this gate is not a device benchmark."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import statistics

PREFIX = 'BCHAT_MATURITY_CAPACITY='
OPERATIONS = ('send', 'history', 'rooms', 'search', 'concurrent_send')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def duration(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 300000


def close(actual, expected):
    return duration(actual) and abs(actual - expected) <= .002


def validate(value):
    require(type(value) is dict and type(value.get('schema_version')) is int
            and value['schema_version'] == 1, 'capacity schema')
    require(value.get('status') == 'ok' and value.get('error') is None, 'capacity failed')
    require(value.get('scope') == 'odoo_service_db_json_commit_not_http_or_device', 'scope')
    require(value.get('database') == 'bchat_maturity_test_20261017', 'synthetic database')
    require(value.get('limits') == {
        'statement_timeout_ms': 10000, 'lock_timeout_ms': 2000, 'total_budget_seconds': 300,
    }, 'bounded deadlines')
    fixture = value.get('fixture', {})
    for key, expected in {'users': 50, 'rooms': 100, 'primary_members': 50,
                          'seed_messages': 500, 'final_messages': 531}.items():
        require(type(fixture.get(key)) is int and fixture[key] == expected, 'fixture ' + key)
    require(fixture.get('ordinary_actor_verified') is True and fixture.get('marker_verified') is True,
            'ordinary authenticated actor/fixture marker')
    require(value.get('sample_plan') == {
        'warmups_per_operation': 1, 'sequential_per_operation': 10,
        'concurrent_rounds': 10, 'workers_per_round': 2,
    }, 'sample plan')
    invariants = value.get('invariants', {})
    for key in ('seed_exact', 'each_send_once', 'concurrent_initial_pids_distinct',
                'history_page_bounded', 'room_list_exact', 'search_page_bounded'):
        require(invariants.get(key) is True, 'invariant ' + key)
    require(value.get('cleanup') == {'completed': True, 'marker_verified': True}, 'synthetic cleanup')
    require(duration(value.get('elapsed_ms')), 'total elapsed')
    samples = value.get('samples')
    require(type(samples) is list and len(samples) == 64, '64 raw samples required')
    groups = {op: [] for op in OPERATIONS}
    seen = set()
    rounds = {}
    for sample in samples:
        require(type(sample) is dict, 'sample object')
        op = sample.get('operation')
        require(op in groups and sample.get('result') == 'ok' and sample.get('error') is None,
                'no omitted/failed sample')
        require(type(sample.get('warmup')) is bool and integer(sample.get('sample')), 'sample identity')
        require(duration(sample.get('elapsed_ms')), 'sample elapsed')
        require(integer(sample.get('request_utf8_bytes'), maximum=65536), 'request size')
        require(integer(sample.get('response_utf8_bytes'), 1, 131072), 'response size')
        expected_page = {'send': 'write', 'history': 'latest', 'rooms': 'rooms100',
                         'search': 'search_hits', 'concurrent_send': 'write'}[op]
        require(sample.get('page') == expected_page, 'page contract')
        count = sample.get('row_count')
        require(integer(count), 'row count')
        if op in ('history', 'search'):
            require(1 <= count <= 30, 'bounded nonempty read page')
        else:
            require(count == (100 if op == 'rooms' else 1), 'exact room/write result')
        if op == 'concurrent_send':
            require(sample['warmup'] is False and integer(sample.get('round'), 1, 10)
                    and integer(sample.get('worker'), 1, 2), 'two-worker round identity')
            identity = (op, sample['round'], sample['worker'])
            rounds.setdefault(sample['round'], []).append(sample)
        else:
            require(sample.get('round') is None and sample.get('worker') is None, 'sequential identity')
            require((sample['warmup'] and sample['sample'] == 0)
                    or (not sample['warmup'] and 1 <= sample['sample'] <= 10), 'sample number')
            identity = (op, sample['sample'])
        require(identity not in seen, 'duplicate raw sample')
        seen.add(identity)
        attempts = sample.get('attempts')
        require(type(attempts) is list and 1 <= len(attempts) <= 6
                and type(sample.get('attempt_count')) is int and sample['attempt_count'] == len(attempts),
                'attempt inventory')
        for number, attempt in enumerate(attempts, 1):
            require(type(attempt) is dict and type(attempt.get('number')) is int and attempt['number'] == number
                    and integer(attempt.get('backend_pid'), 1)
                    and attempt.get('isolation') == 'repeatable read'
                    and duration(attempt.get('elapsed_ms')), 'real RR attempt')
            if number == len(attempts):
                require(attempt.get('result') == 'ok' and attempt.get('sqlstate') is None, 'final attempt')
            else:
                require(attempt.get('result') == 'serialization_retry' and attempt.get('sqlstate') == '40001',
                        'only serialization retry; deadlocks/timeouts fail')
        require(integer(sample.get('initial_backend_pid'), 1) and integer(sample.get('final_backend_pid'), 1)
                and sample['initial_backend_pid'] == attempts[0]['backend_pid']
                and sample.get('final_backend_pid') == attempts[-1]['backend_pid'], 'PID provenance')
        require(sum(a['elapsed_ms'] for a in attempts) <= sample['elapsed_ms'] + .01,
                'elapsed includes retries and commit')
        groups[op].append(sample)
    require(set(rounds) == set(range(1, 11)), 'all concurrent rounds')
    for pair in rounds.values():
        require(len(pair) == 2 and len({s['initial_backend_pid'] for s in pair}) == 2,
                'independent concurrent connections')
    # Sequential calls cannot overlap. Concurrent pairs may overlap, but even
    # their longest member must fit in the observed wall-clock total.
    lower_bound = sum(s['elapsed_ms'] for s in samples if s['operation'] != 'concurrent_send')
    lower_bound += sum(max(s['elapsed_ms'] for s in pair) for pair in rounds.values())
    require(lower_bound <= value['elapsed_ms'] + .1, 'total elapsed includes every measured round')
    summaries = value.get('summary', {})
    require(set(summaries) == set(OPERATIONS), 'summary operations')
    for op, raw in groups.items():
        warmups = [s for s in raw if s['warmup']]
        measured = [s for s in raw if not s['warmup']]
        require(len(warmups) == (0 if op == 'concurrent_send' else 1)
                and len(measured) == (20 if op == 'concurrent_send' else 10), 'raw sample inventory')
        summary = summaries[op]
        require(type(summary) is dict and summary.get('samples') == len(measured), 'summary count')
        require(close(summary.get('median_ms'), statistics.median(s['elapsed_ms'] for s in measured))
                and close(summary.get('max_ms'), max(s['elapsed_ms'] for s in measured)), 'summary timings')
        require(summary.get('row_count_min') == min(s['row_count'] for s in measured)
                and summary.get('row_count_max') == max(s['row_count'] for s in measured)
                and summary.get('response_utf8_bytes_max') == max(s['response_utf8_bytes'] for s in measured),
                'summary counts/sizes')
    return {'schema_version': 1, 'status': 'ok', 'samples': len(samples),
            'summary': summaries, 'limits': value['limits'], 'fixture': fixture,
            'limitations': ['Synthetic service/DB/JSON/commit only; not HTTP, production cold start or device.',
                            'Small explicit sample; median/max are observations, not SLA or general capacity.']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.source_commit), 'frozen source required')
    rows = [line[len(PREFIX):] for line in args.log.read_text(encoding='utf-8').splitlines()
            if line.startswith(PREFIX)]
    require(len(rows) == 1, 'exactly one final real capacity result required')
    evidence = validate(json.loads(rows[0]))
    evidence['source_commit'] = args.source_commit
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('BCHAT_CAPACITY_GATE=PASS samples=64 scope=synthetic_service_db_only')


if __name__ == '__main__':
    main()

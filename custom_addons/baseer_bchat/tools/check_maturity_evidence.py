"""Fail closed on missing core tests, skips or explicit real-RR probe evidence.

The pinned Odoo result logs Starting Class.method and a failed/error/test summary.
See odoo/odoo 19.0 odoo/tests/{loader,result}.py. No success is inferred from a
container exit code alone. ORM/HTTP and pure BaseCase tests remain distinguishable.
"""
import argparse
import ast
import json
from pathlib import Path
import re


SOCIAL_PHASES = {
    'absent_room_preference_cas', 'preview_same_uuid', 'diagnostic_same_uuid',
    'diagnostic_distinct_devices_daily_quota', 'direct_reverse_pair',
}


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
                or any(row.get('isolation') != 'repeatable read' or not 1 <= row['attempts'] <= 6 for row in phase)):
            raise ValueError('Each phase needs two actual independent RR transactions with bounded attempts')
    quota = social['phases']['diagnostic_distinct_devices_daily_quota']
    if sorted(row['state'] for row in quota) != ['ok', 'rate_limited']:
        raise ValueError('Cross-device final daily slot did not have one winner')
    denied = next(row for row in quota if row['state'] == 'rate_limited')
    if denied.get('status') != 429 or not denied.get('retry_after_seconds'):
        raise ValueError('Quota refusal must be explicit 429 with retry guidance')
    return {
        'source_commit': source_commit, 'core_tests': len(expected), 'skipped': 0,
        'core_test_kinds': {kind: sum(value == kind for value in kinds.values()) for kind in sorted(set(kinds.values()))},
        'real_postgres_phases': 10, 'probes': probes,
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
    print('BCHAT_CORE_ORM_EVIDENCE=PASS tests=%s phases=10 skips=0' % evidence['core_tests'])


if __name__ == '__main__':
    main()

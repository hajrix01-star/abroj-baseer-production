#!/usr/bin/env python3
"""Fixed BWork source/plan checks for the reviewed deployment wrappers.

No database connections, policy execution, environment or credentials. Removing
old addon source here affects ONLY the private, not-yet-active staging copy.
The SQL classifier must still prove installed closure before any DB mutation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


CORE = 'custom_addons/baseer_bwork'
CONSUMERS = {'baseer_access_roles', 'baseer_procurement_requests',
             'baseer_bwork_admin', 'baseer_bwork_dashboard'}


def require(condition, code):
    if not condition:
        raise SystemExit('BWORK_RELEASE_SOURCE=STOP:' + code)


def modules(value):
    result = value.split(',')
    require(bool(result) and len(set(result)) == len(result)
            and all(re.fullmatch(r'(baseer|abroj)_[a-z0-9_]+', item) for item in result),
            'invalid_module_list')
    return set(result)


def mapping(root):
    path = root / CORE / 'canonical_name_map.json'
    require(path.is_file() and not path.is_symlink(), 'mapping_missing')
    raw = path.read_bytes()
    value = json.loads(raw)
    require(value.get('schema_version') == 1 and value.get('migration_id') == 'BCR-20261020-v1',
            'mapping_identity')
    pairs = value['modules']
    require(len(pairs) == 4 and len({row['old'] for row in pairs}) == 4
            and len({row['new'] for row in pairs}) == 4, 'module_mapping_cardinality')
    require(all(re.fullmatch(r'baseer_bchat(?:_[a-z0-9_]+)?', row['old'])
                and row['new'] == row['old'].replace('baseer_bchat', 'baseer_bwork', 1)
                for row in pairs), 'module_mapping_names')
    require(any(row['new'] == 'baseer_bwork' for row in pairs), 'core_mapping_absent')
    return pairs, hashlib.sha256(raw).hexdigest()


def tree(root):
    require(root.is_dir() and not root.is_symlink(), 'core_missing')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'source_symlink')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def prepare(candidate, frozen, approved):
    require(candidate != frozen and candidate.is_dir() and frozen.is_dir(), 'invalid_source_roots')
    require(tree(candidate / CORE) == tree(frozen / CORE), 'frozen_core_mismatch')
    pairs, digest = mapping(frozen)
    require('baseer_bwork' in approved, 'canonical_core_not_approved')
    require(not ({row['old'] for row in pairs} & approved), 'mixed_module_policy')
    # Exact fixed-map paths in a private stage, never live/current/data roots.
    for row in pairs:
        target = candidate / 'custom_addons' / row['old']
        require(target.parent.resolve() == (candidate / 'custom_addons').resolve(), 'unsafe_old_path')
        if target.exists() or target.is_symlink():
            tree(target)  # Reject nested symlinks before a recursive removal.
            shutil.rmtree(target)
    require(tree(candidate / CORE) == tree(frozen / CORE), 'prepared_core_mismatch')
    return digest


def check_plan(root, approved, value, *, verified=False, transition=False):
    pairs, digest = mapping(root)
    require(value.get('schema_version') == 1 and value.get('mapping_sha256') == digest,
            'classification_mapping_mismatch')
    kind = value.get('classification')
    require(kind in ('old-installed', 'fresh', 'canonical-ready'), 'classification_failed')
    allowed = {row['new'] for row in pairs} | CONSUMERS
    sets = {}
    for key in ('install', 'upgrade', 'required_closure'):
        items = value.get(key)
        require(isinstance(items, list) and all(isinstance(x, str) for x in items)
                and len(set(items)) == len(items) and set(items) <= allowed, 'invalid_' + key)
        sets[key] = set(items)
    require(sets['required_closure'] and sets['required_closure'] <= approved,
            'installed_closure_not_approved')
    require(not (sets['install'] & sets['upgrade'])
            and sets['install'] | sets['upgrade'] == sets['required_closure'], 'invalid_classification_partition')
    require(value.get('native_pre_upgrade_required') is (kind == 'old-installed'), 'invalid_native_boundary')
    if verified or transition:
        require(kind == 'canonical-ready' and not sets['install'], 'postcondition_not_installed')
    if transition:
        require(value.get('transition_lineage') == 'PASS' and value.get('mode') == 'old-installed',
                'first_transition_not_attested')
    lines = ['NATIVE ' + ('yes' if kind == 'old-installed' else 'no')]
    lines += ['UPGRADE ' + name for name in sorted(sets['upgrade'])]
    lines += ['INSTALL ' + name for name in sorted(sets['install'])]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'requested', 'plan', 'verified', 'verified-transition'))
    parser.add_argument('--candidate-root', required=True)
    parser.add_argument('--guard-root')
    parser.add_argument('--modules', required=True)
    parser.add_argument('--plan')
    args = parser.parse_args()
    candidate = Path(args.candidate_root).resolve()
    approved = modules(args.modules)
    if args.action == 'prepare':
        require(args.guard_root is not None, 'guard_root_missing')
        print(prepare(candidate, Path(args.guard_root).resolve(), approved))
    elif args.action == 'requested':
        pairs, _ = mapping(candidate)
        requested = approved & ({row['new'] for row in pairs} | CONSUMERS)
        require('baseer_bwork' in requested, 'core_not_requested')
        print(','.join(sorted(requested)))
    else:
        require(args.plan is not None, 'plan_missing')
        path = Path(args.plan)
        require(path.is_file() and path.stat().st_size <= 65536, 'plan_size')
        print(check_plan(candidate, approved, json.loads(path.read_text()),
                         verified=args.action == 'verified', transition=args.action == 'verified-transition'))


if __name__ == '__main__':
    main()

"""Fixed source proof for an already completed canonical four-addon update.

No database, environment, Git/network execution, configuration override or
source mutation. Contract digests were generated from raw Git blobs at the
fixed baseline, never an autocrlf checkout. Hash rows are UTF-8 compact JSON,
sorted by relative POSIX path: [path, raw byte length, SHA256(raw bytes)].
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat


MODE = 'canonical-four-v1'
REQUESTED_MODULES = frozenset({'baseer_bwork', 'baseer_bwork_procurement',
                               'baseer_bwork_admin', 'baseer_bwork_dashboard'})
PRESERVED_MODULES = frozenset({'baseer_access_roles', 'baseer_procurement_requests'})
INSTALLED_MODULES = REQUESTED_MODULES | PRESERVED_MODULES
BASELINE_COMMIT = '81fdd415521670b8c7ad681e97dd583e6f9c85e0'
MAPPING_SHA256 = '8a7bb0128e426fa6819898f943b0a4e6dc9d1d73a2b789f75bf63f060e2d08fd'
CONTRACT_PATH = Path(__file__).resolve().parents[1] / 'canonical_four_update_contract.json'
CONTRACT_SHA256 = '3db6efa6ce31502892bb0c9d0e2aed30563f8f057404b45ce90fd0158ed6498e'
_VERSIONS = {'baseer_access_roles': '19.0.1.0.20',
             'baseer_procurement_requests': '19.0.14.0.13'}


class CanonicalFourUpdateStopped(RuntimeError):
    """Fixed reason codes only; never expose source/configuration content."""


def _require(condition, code):
    if not condition:
        raise CanonicalFourUpdateStopped('canonical_four_' + code)


def _read(path, bound):
    _require(not path.is_symlink(), 'source_symlink')
    before = path.stat()
    _require(stat.S_ISREG(before.st_mode) and before.st_size <= bound, 'source_file_bound')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as source:
        opened = os.fstat(source.fileno())
        _require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'source_changed')
        raw = source.read(bound + 1)
        after = os.fstat(source.fileno())
    _require(len(raw) <= bound and len(raw) == before.st_size
             and (after.st_size, after.st_mtime_ns, after.st_ino) ==
                 (before.st_size, before.st_mtime_ns, before.st_ino), 'source_changed')
    return raw


def _contract():
    raw = _read(CONTRACT_PATH, 8192)
    _require(hashlib.sha256(raw).hexdigest() == CONTRACT_SHA256, 'contract_digest')
    value = json.loads(raw)
    _require(type(value) is dict and set(value) == {
        'schema_version', 'mode', 'baseline_commit', 'mapping_sha256', 'modules'}, 'contract_shape')
    _require(type(value['schema_version']) is int and value['schema_version'] == 1
             and value['mode'] == MODE and value['baseline_commit'] == BASELINE_COMMIT
             and value['mapping_sha256'] == MAPPING_SHA256, 'contract_identity')
    mapping = _read(CONTRACT_PATH.parent / 'canonical_name_map.json', 131072)
    _require(hashlib.sha256(mapping).hexdigest() == MAPPING_SHA256, 'mapping_digest')
    rows = value['modules']
    _require(type(rows) is list and len(rows) == 2 and
             [row.get('module') for row in rows if type(row) is dict] == sorted(PRESERVED_MODULES),
             'contract_modules')
    for row in rows:
        _require(set(row) == {'module', 'version', 'files', 'bytes', 'source_sha256'}
                 and row['version'] == _VERSIONS[row['module']]
                 and type(row['files']) is int and 0 < row['files'] <= 128
                 and type(row['bytes']) is int and 0 < row['bytes'] <= 2 * 1024 * 1024
                 and type(row['source_sha256']) is str and len(row['source_sha256']) == 64
                 and all(char in '0123456789abcdef' for char in row['source_sha256']), 'contract_module')
    return rows


def contract_sha256():
    try:
        _contract()
        return CONTRACT_SHA256
    except (OSError, ValueError, TypeError, KeyError):
        raise CanonicalFourUpdateStopped('canonical_four_invalid_contract') from None


def _tree(directory, expected):
    _require(directory.is_dir() and not directory.is_symlink(), 'source_directory')
    rows, total, directory_count = [], 0, 0
    def unreadable(_error):
        _require(False, 'source_unreadable')
    for root, directories, files in os.walk(directory, followlinks=False, onerror=unreadable):
        parent = Path(root)
        directory_count += len(directories)
        _require(directory_count <= expected['files'] * 2 and bool(directories or files), 'source_directory_bound')
        for name in directories:
            _require(not (parent / name).is_symlink(), 'source_symlink')
        for name in files:
            _require(len(rows) < expected['files'], 'source_file_count')
            path = parent / name
            raw = _read(path, expected['bytes'] - total)
            total += len(raw)
            rows.append([path.relative_to(directory).as_posix(), len(raw), hashlib.sha256(raw).hexdigest()])
    rows.sort(key=lambda row: row[0])
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    _require(len(rows) == expected['files'] and total == expected['bytes']
             and digest == expected['source_sha256'], 'source_digest')
    manifest = ast.literal_eval(_read(directory / '__manifest__.py', expected['bytes']).decode('utf-8'))
    _require(type(manifest) is dict and manifest.get('version') == expected['version'], 'source_version')
    return {'module': expected['module'], 'version': expected['version'], 'source_sha256': digest}


def verify_preserved_sources(addons_root):
    """Independently verify the actual two staged trees against frozen Git LF."""
    try:
        root = Path(addons_root)
        _require(root.is_dir() and not root.is_symlink(), 'addons_root')
        return [_tree(root / row['module'], row) for row in _contract()]
    except (OSError, ValueError, TypeError, KeyError, SyntaxError):
        raise CanonicalFourUpdateStopped('canonical_four_invalid_source') from None

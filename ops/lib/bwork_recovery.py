#!/usr/bin/env python3
"""Privileged, proof-bound logical recovery for the completed BWork mapping.

The protected root wrapper owns quiescence, source/helper authenticity, paired
backup/schema/filestore verification and durable intent/receipt files. This
helper has no file/proof-path option, ORM import, public route, migration hook,
role write, generic identity reset or retry. Capture/recover transport bounded
canonical JSON through stdout/stdin. Raw business/credential rows are hashed
in memory only and never included in the proof or diagnostics.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


PROTOCOL = 'bwork-logical-recovery-v1'
MAPPING_SHA256 = '8a7bb0128e426fa6819898f943b0a4e6dc9d1d73a2b789f75bf63f060e2d08fd'
LEDGER_KEY = 'baseer_bwork.canonical_rename.v1'
FOUR = frozenset({'baseer_bwork', 'baseer_bwork_procurement', 'baseer_bwork_admin', 'baseer_bwork_dashboard'})
SIX = FOUR | {'baseer_access_roles', 'baseer_procurement_requests'}
MAX_PROOF = 8 * 1024 * 1024
MAX_RESTORE_WITNESS = 16 * 1024
MAX_ROW = 16 * 1024 * 1024
MAX_DATA = 2 * 1024 * 1024 * 1024
MAX_ROWS = 5000000
MAX_TABLES = 4096
MAX_SECONDS = 300
ROW_FORMAT = 'pg-record-send-hex-v1'
LEDGER_COLUMN_TYPES = {'id': 23, 'key': 1043, 'value': 25, 'create_uid': 23,
                       'write_uid': 23, 'create_date': 1114, 'write_date': 1114}


class RecoveryStopped(RuntimeError):
    """Fixed reason code only, without database contents or credentials."""


def require(condition, code):
    if not condition:
        raise RecoveryStopped('BWORK_RECOVERY_STOP:' + code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, TypeError, UnicodeError):
        raise RecoveryStopped('BWORK_RECOVERY_STOP:invalid_json') from None


def valid_database(name):
    if name == 'baseer_prod':
        return
    synthetic = (re.fullmatch(r'bwork_canonical_recovery_ci_[a-z0-9_]+', name) or
                 re.fullmatch(r'bwork_canonical_four_ci_[a-f0-9]{12}', name))
    require(bool(synthetic) and len(name) <= 63 and os.environ.get('BWORK_RECOVERY_SYNTHETIC') == '1',
            'database_boundary')


def hex_digest(value):
    return type(value) is str and bool(re.fullmatch(r'[a-f0-9]{64}', value))


def quoted(name):
    require(type(name) is str and bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,62}', name)), 'unsupported_identifier')
    return '"' + name + '"'


class Budget:
    def __init__(self):
        self.start = time.monotonic()
        self.bytes = 0
        self.rows = 0

    def check(self, row_bytes=0):
        self.bytes += row_bytes
        self.rows += int(row_bytes > 0)
        require(self.bytes <= MAX_DATA and self.rows <= MAX_ROWS, 'data_bound')
        require(time.monotonic() - self.start <= MAX_SECONDS, 'deadline')


def row_fingerprint(rows, budget):
    """Frame sorted native record_send hex, retaining every native field bit."""
    value, count, size, previous = hashlib.sha256(), 0, 0, None
    for row in rows:
        require(type(row) is str, 'row_encoding')
        raw = row.encode('utf-8')
        require(0 < len(raw) <= MAX_ROW and (previous is None or previous <= raw), 'row_bound_or_order')
        require(len(raw) % 2 == 0 and bool(re.fullmatch(r'[0-9a-f]+', row)), 'native_row_encoding')
        budget.check(len(raw))
        value.update(len(raw).to_bytes(8, 'big'))
        value.update(raw)
        previous = raw
        count += 1
        size += len(raw)
    budget.check()
    return {'rows': count, 'bytes': size, 'sha256': value.hexdigest()}


def _raw_file(path, bound):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= bound, 'source_file')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino), 'source_race')
        raw = stream.read(bound + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) == info.st_size and len(raw) <= bound and
            (info.st_size, info.st_mtime_ns, info.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino),
            'source_changed')
    return raw


def source_context(root, commit, database):
    require(type(commit) is str and bool(re.fullmatch(r'[a-f0-9]{40}', commit)), 'source_commit')
    root = Path(root)
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(), 'source_root')
    marker = root / 'RELEASE_COMMIT'
    if database == 'baseer_prod' or marker.exists():
        require(_raw_file(marker, 64).decode().strip() == commit, 'source_marker')
    core = root / 'custom_addons/baseer_bwork'
    require(not (root / 'custom_addons').is_symlink() and core.is_dir() and not core.is_symlink(), 'core_source')
    rows, total, directories_seen = [], 0, 0
    def unreadable(_error):
        require(False, 'unreadable_source')
    for parent, directories, files in os.walk(core, followlinks=False, onerror=unreadable):
        parent = Path(parent)
        directories_seen += len(directories)
        require(directories_seen <= 4096, 'source_directory_bound')
        for name in directories:
            require(not (parent / name).is_symlink(), 'source_link')
        for name in files:
            require(len(rows) < 4096, 'source_file_bound')
            path = parent / name
            raw = _raw_file(path, 64 * 1024 * 1024 - total)
            total += len(raw)
            rows.append([path.relative_to(core).as_posix(), len(raw), hashlib.sha256(raw).hexdigest()])
    rows.sort(key=lambda row: row[0])
    mapping_raw = _raw_file(core / 'canonical_name_map.json', 131072)
    require(hashlib.sha256(mapping_raw).hexdigest() == MAPPING_SHA256, 'mapping_source')
    mapping = decode(mapping_raw)
    tables = sorted(row['new_table'] for row in mapping['models'] if row['new_table'])
    require(len(tables) == len(set(tables)) == 14, 'mapping_tables')
    for name in tables:
        quoted(name)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('bwork_recovery_original_classifier', core / 'tools/canonical_pre_upgrade.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    return {'identity': {'commit': commit, 'core_sha256': digest(rows), 'mapping_sha256': MAPPING_SHA256},
            'tables': tables, 'classifier': original}


def _fields(text, start):
    """Locate object value spans using Python's JSON parser, not replacements."""
    decoder = json.JSONDecoder()
    def whitespace(offset):
        while offset < len(text) and text[offset] in ' \t\r\n':
            offset += 1
        return offset
    start = whitespace(start)
    require(text[start] == '{', 'ledger_object')
    offset, result = whitespace(start + 1), {}
    while text[offset] != '}':
        key, end = decoder.raw_decode(text, offset)
        require(type(key) is str and key not in result, 'ledger_key')
        offset = whitespace(end)
        require(text[offset] == ':', 'ledger_separator')
        value_start = whitespace(offset + 1)
        _value, value_end = decoder.raw_decode(text, value_start)
        result[key] = (value_start, value_end)
        offset = whitespace(value_end)
        if text[offset] == ',':
            offset = whitespace(offset + 1)
        else:
            require(text[offset] == '}', 'ledger_separator')
    return result


def ledger_transition(raw, current_oids, tables):
    """Replace only the fourteen numeric OID tokens; every other byte survives."""
    require(type(raw) is str and len(raw.encode()) <= 65536, 'ledger_bound')
    old = decode(raw)
    require(type(old) is dict and old.get('status') == 'complete' and
            old.get('mapping_sha256') == MAPPING_SHA256 and type(old.get('tables')) is dict and
            set(old['tables']) == set(tables) == set(current_oids) and len(tables) == 14, 'ledger_identity')
    expected, spans, prior_oids = copy.deepcopy(old), [], {}
    root_fields = _fields(raw, 0)
    table_fields = _fields(raw, root_fields['tables'][0])
    for name in tables:
        require(type(old['tables'][name]) is dict, 'ledger_table_shape')
        before = old['tables'][name].get('oid')
        after = current_oids[name]
        require(type(before) is int and type(after) is int and before > 0 and after > 0, 'ledger_oid')
        prior_oids[name] = before
        expected['tables'][name]['oid'] = after
        fields = _fields(raw, table_fields[name][0])
        start, end = fields['oid']
        require(raw[start:end] == str(before), 'ledger_oid_token')
        spans.append((start, end, str(after)))
    require(len(set(prior_oids.values())) == len(set(current_oids.values())) == 14, 'duplicate_oid')
    require(prior_oids != current_oids, 'duplicate_or_unneeded_recovery')
    result = raw
    for start, end, value in sorted(spans, reverse=True):
        result = result[:start] + value + result[end:]
    require(decode(result) == expected, 'ledger_unexpected_difference')
    return result, prior_oids


def _quiet(cr):
    cr.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
               "AND pid<>pg_backend_pid() AND backend_type='client backend'")
    require(cr.fetchone()[0] == 0, 'foreign_database_client')
    cr.execute('SELECT count(*) FROM pg_prepared_xacts WHERE database=current_database()')
    require(cr.fetchone()[0] == 0, 'prepared_transaction')


def _settings(cr):
    # The original classifier uses current_schema() for public-column checks.
    # Keep public explicit and pg_catalog implicit: catalog lookup still comes
    # first, without making current_schema() report pg_catalog.
    for statement in ("SET LOCAL statement_timeout='30s'", "SET LOCAL lock_timeout='2s'",
                      "SET LOCAL work_mem='16MB'", "SET LOCAL temp_file_limit='512MB'",
                      "SET LOCAL TIME ZONE 'UTC'", "SET LOCAL datestyle='ISO, YMD'",
                      "SET LOCAL intervalstyle='postgres'", "SET LOCAL bytea_output='hex'",
                      "SET LOCAL extra_float_digits=3", "SET LOCAL search_path=public",
                      'SET LOCAL row_security=off'):
        cr.execute(statement)


def _stream(connection, query, budget, index):
    with connection.cursor(name='bwork_recovery_rows_' + str(index)) as rows:
        # One row per server-cursor fetch bounds client memory even when a
        # row approaches MAX_ROW; the row/operation deadlines remain enforced.
        rows.itersize = 1
        rows.execute(query)
        return row_fingerprint((row[0] for row in rows), budget)


def record_query(table, excluding_id=None):
    where = ''
    if excluding_id is not None:
        require(type(excluding_id) is int and excluding_id > 0, 'ledger_row_id')
        where = ' WHERE id<>' + str(excluding_id)
    expression = "encode(pg_catalog.record_send(t),'hex')"
    return ('SELECT ' + expression + ' FROM ONLY public.' + quoted(table) + ' t' + where +
            ' ORDER BY (' + expression + ') COLLATE "C"')


def check_ledger_columns(columns):
    require(len(columns) == len(LEDGER_COLUMN_TYPES) and dict(columns) == LEDGER_COLUMN_TYPES,
            'unsupported_ledger_column_shape')


def _catalog_fingerprint(cr, query, budget):
    expression = "encode(pg_catalog.record_send(t),'hex')"
    cr.execute('SELECT ' + expression + ' FROM (' + query + ') t ORDER BY (' + expression + ') COLLATE "C"')
    return row_fingerprint((row[0] for row in cr), budget)


def _snapshot(connection, context, database, schema_sha256, budget=None):
    budget = budget or Budget()
    with connection.cursor() as cr:
        _settings(cr)
        _quiet(cr)
        cr.execute("SELECT current_database(),current_setting('server_encoding'),pg_database_size(current_database()),"
                   "current_setting('server_version_num')::integer,"
                   "(SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user)")
        actual, encoding, size, postgres_version, privileged = cr.fetchone()
        require(actual == database and encoding == 'UTF8' and size <= MAX_DATA and privileged, 'database_capability_or_bound')
        cr.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public','pg_catalog','information_schema') "
                   "AND nspname NOT LIKE 'pg_toast%%' AND nspname NOT LIKE 'pg_temp_%%'")
        require(not cr.fetchall(), 'unsupported_user_schema')
        cr.execute('SELECT count(*) FROM pg_largeobject_metadata')
        require(cr.fetchone()[0] == 0, 'unsupported_large_objects')
        cr.execute("SELECT relname,relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname='public' ORDER BY relname")
        relations = cr.fetchall()
        require(len(relations) <= 20000 and all(kind in ('r','p','m','v','S','i','I','c')
                                               for _name, kind in relations), 'unsupported_relation_kind_or_bound')
        tables = [name for name, kind in relations if kind in ('r', 'p', 'm')]
        require(len(tables) <= MAX_TABLES and 'ir_config_parameter' in tables, 'table_inventory_bound')
        cr.execute("SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
                   "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_type t ON t.oid=a.atttypid "
                   "JOIN pg_namespace tn ON tn.oid=t.typnamespace "
                   "LEFT JOIN pg_proc s ON s.oid=t.typsend LEFT JOIN pg_namespace sn ON sn.oid=s.pronamespace "
                   "LEFT JOIN pg_type e ON e.oid=t.typelem LEFT JOIN pg_namespace en ON en.oid=e.typnamespace "
                   "LEFT JOIN pg_proc es ON es.oid=e.typsend LEFT JOIN pg_namespace esn ON esn.oid=es.pronamespace "
                   "WHERE n.nspname='public' "
                   "AND c.relkind IN ('r','p','m') AND a.attnum>0 AND NOT a.attisdropped "
                   "AND (tn.nspname<>'pg_catalog' OR t.oid>=16384 OR t.typsend=0 OR s.oid IS NULL OR s.oid>=16384 "
                   "OR sn.nspname<>'pg_catalog' OR (t.typelem<>0 AND (e.oid IS NULL OR e.oid>=16384 "
                   "OR en.nspname<>'pg_catalog' OR e.typsend=0 OR es.oid IS NULL OR es.oid>=16384 OR esn.nspname<>'pg_catalog'))) LIMIT 1")
        require(cr.fetchone() is None, 'unsupported_column_type')
        cr.execute("SELECT a.attname,a.atttypid FROM pg_attribute a WHERE a.attrelid='public.ir_config_parameter'::regclass "
                   "AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum")
        check_ledger_columns(cr.fetchall())
        cr.execute('SELECT id,value,to_jsonb(t)::text FROM public.ir_config_parameter t WHERE key=%s', [LEDGER_KEY])
        ledger_rows = cr.fetchall()
        require(len(ledger_rows) == 1, 'ledger_row_count')
        ledger_id, ledger_value, ledger_row = ledger_rows[0]
        ledger = decode(ledger_value)
        require(ledger.get('status') == 'complete' and ledger.get('mapping_sha256') == MAPPING_SHA256
                and set(ledger.get('tables', {})) == set(context['tables']), 'ledger_state')
        cr.execute("SELECT name,id,state,latest_version FROM public.ir_module_module WHERE name IN %s ORDER BY name",
                   [tuple(sorted(SIX))])
        modules = cr.fetchall()
        require(len(modules) == 6 and all(row[2] == 'installed' for row in modules), 'module_closure')
        cr.execute("SELECT 1 FROM public.ir_module_module WHERE state IN ('to install','to upgrade','to remove') LIMIT 1")
        require(cr.fetchone() is None, 'global_pending_modules')
        cr.execute("SELECT name FROM public.ir_module_module WHERE name LIKE 'baseer_bwork%%' "
                   "AND state IN ('installed','to install','to upgrade','to remove')")
        require({row[0] for row in cr.fetchall()} == FOUR, 'unknown_active_family')
        oids = {}
        for table in context['tables']:
            cr.execute('SELECT to_regclass(%s)::oid', ['public.' + table])
            oid = cr.fetchone()[0]
            require(type(oid) is int and oid > 0, 'missing_canonical_table')
            oids[table] = oid
        require(len(set(oids.values())) == 14, 'duplicate_canonical_identity')
        sequences = []
        for name, kind in relations:
            if kind == 'S':
                cr.execute('SELECT last_value,is_called FROM public.' + quoted(name))
                value, called = cr.fetchone()
                sequences.append([name, value, called])
        # Native schema bytes are independently hashed/bound by the wrapper.
        # Own/ACL/security metadata is separately proved, not omitted by its
        # --no-owner/--no-privileges schema-dump transport.
        security_queries = {
            'database': "SELECT datname,pg_get_userbyid(datdba) AS owner,encoding,datcollate,datctype,"
                        "datistemplate,datallowconn,datconnlimit,datacl::text FROM pg_database WHERE datname=current_database()",
            'schemas': "SELECT nspname,pg_get_userbyid(nspowner) AS owner,nspacl::text FROM pg_namespace WHERE nspname='public'",
            'relations': "SELECT c.relname,pg_get_userbyid(c.relowner) AS owner,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity "
                         "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'",
            'functions': "SELECT p.oid::regprocedure::text AS identity,pg_get_userbyid(p.proowner) AS owner,p.proacl::text,"
                         "p.prosecdef,p.proleakproof FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'",
            'types': "SELECT t.typname,pg_get_userbyid(t.typowner) AS owner,t.typacl::text "
                     "FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'",
            'columnAcls': "SELECT c.relname,a.attname,a.attacl::text FROM pg_attribute a "
                          "JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                          "WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped AND a.attacl IS NOT NULL",
            'defaultAcls': "SELECT pg_get_userbyid(a.defaclrole) AS role,coalesce(n.nspname,'*') AS schema,"
                           "a.defaclobjtype,a.defaclacl::text FROM pg_default_acl a "
                           "LEFT JOIN pg_namespace n ON n.oid=a.defaclnamespace",
            'extensions': "SELECT e.extname,pg_get_userbyid(e.extowner) AS owner,n.nspname AS schema,e.extversion "
                          "FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace",
            'publicOwnership': "SELECT i.type,i.schema,i.identity,pg_get_userbyid(d.refobjid) AS owner "
                               "FROM pg_shdepend d CROSS JOIN LATERAL pg_identify_object(d.classid,d.objid,d.objsubid) i "
                               "WHERE d.dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                               "AND d.deptype='o' AND i.schema='public'",
            'roles': 'SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolconnlimit,'
                     'rolvaliduntil,rolbypassrls,rolconfig FROM pg_roles',
            'roleMemberships': "SELECT pg_get_userbyid(roleid) AS role,pg_get_userbyid(member) AS member,"
                               "pg_get_userbyid(grantor) AS grantor,to_jsonb(t)-'oid'-'roleid'-'member'-'grantor' AS options FROM pg_auth_members t",
            'roleSettings': "SELECT CASE WHEN setdatabase=0 THEN '*' ELSE current_database() END AS database,"
                            "CASE WHEN setrole=0 THEN '*' ELSE pg_get_userbyid(setrole) END AS role,setconfig "
                            "FROM pg_db_role_setting WHERE setdatabase=0 OR setdatabase=(SELECT oid FROM pg_database WHERE datname=current_database())",
            'policies': "SELECT schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname='public'",
        }
        security = {name: _catalog_fingerprint(cr, query, budget) for name, query in security_queries.items()}
    data = {}
    for index, name in enumerate(tables):
        data[name] = _stream(connection, record_query(name), budget, index)
    remainder = _stream(connection, record_query('ir_config_parameter', ledger_id), budget, len(tables))
    with connection.cursor() as cr:
        _quiet(cr)
    return {'protocol': PROTOCOL, 'schema_version': 1, 'database': database,
            'row_format': ROW_FORMAT, 'postgres_version': postgres_version,
            'source': context['identity'], 'schema_sha256': schema_sha256,
            'tables': data, 'sequences': sequences, 'security': security,
            'modules': [list(row) for row in modules], 'table_oids': oids,
            'ledger': {'id': ledger_id, 'value': ledger_value, 'row': ledger_row},
            'ledger_remainder': remainder}


def _classify(connection, context):
    with connection.cursor() as cr:
        cr.execute('SELECT current_schema(),(current_schemas(true))[1]')
        require(cr.fetchone() == ('public', 'pg_catalog'), 'classifier_schema')
        result = context['classifier'].classify(cr, sorted(FOUR))
    require(result['classification'] == 'canonical-ready' and set(result['required_closure']) == SIX
            and not result['install'] and result['native_pre_upgrade_required'] is False, 'original_classifier')
    return result


def validate_paired_restore(raw, witness_sha256, proof, proof_sha256, context, database, schema_sha256):
    """Bind the protected wrapper's authenticated restore, not a SQL oracle.

    The root wrapper independently verifies private pair/intent/toolchain files
    and the active release/run. This helper accepts no unbound witness digest.
    """
    valid_database(database)
    require(type(raw) is str and len(raw) <= MAX_RESTORE_WITNESS, 'paired_restore_bound')
    encoded = raw.encode('utf-8')
    require(len(encoded) <= MAX_RESTORE_WITNESS, 'paired_restore_bound')
    require(hex_digest(witness_sha256) and hashlib.sha256(encoded).hexdigest() == witness_sha256,
            'paired_restore_bytes')
    witness = decode(raw)
    hashes = {'dump_sha256', 'filestore_sha256', 'proof_sha256', 'intent_sha256', 'toolchain_sha256',
              'original_schema_sha256', 'restored_schema_sha256'}
    fields = hashes | {'protocol', 'status', 'method', 'database', 'old_commit', 'candidate_commit',
                       'release_id', 'run_id', 'source'}
    require(type(witness) is dict and set(witness) == fields and canonical(witness) == encoded,
            'paired_restore_shape')
    require(witness['protocol'] == 'bwork-paired-restore-v1' and witness['status'] == 'RESTORED'
            and witness['method'] == 'pg_restore-exit-on-error+paired-filestore', 'paired_restore_method')
    require(all(hex_digest(witness[key]) for key in hashes), 'paired_restore_digest')
    require(type(witness['candidate_commit']) is str and
            bool(re.fullmatch(r'[a-f0-9]{40}', witness['candidate_commit'])) and
            type(witness['release_id']) is str and
            bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,127}', witness['release_id'])) and
            type(witness['run_id']) is str and bool(re.fullmatch(r'[0-9]{1,20}', witness['run_id'])),
            'paired_restore_release')
    require(type(proof) is dict and hex_digest(proof_sha256) and
            hashlib.sha256(canonical(proof) + b'\n').hexdigest() == proof_sha256 and
            witness['proof_sha256'] == proof_sha256, 'paired_restore_proof')
    identity = context['identity']
    require(type(identity) is dict and set(identity) == {'commit', 'core_sha256', 'mapping_sha256'} and
            type(identity['commit']) is str and bool(re.fullmatch(r'[a-f0-9]{40}', identity['commit'])) and
            hex_digest(identity['core_sha256']) and identity['mapping_sha256'] == MAPPING_SHA256,
            'paired_restore_identity')
    require(witness['database'] == database == proof.get('database') and
            witness['source'] == proof.get('source') == identity and
            witness['old_commit'] == identity['commit'], 'paired_restore_source')
    require(witness['original_schema_sha256'] == proof.get('schema_sha256') and
            witness['restored_schema_sha256'] == schema_sha256, 'paired_restore_schema')
    return witness


def compare_restored(proof, actual, witness):
    require(type(proof) is dict and set(proof) == set(actual), 'proof_shape')
    # Native pg_restore reassigns relation OIDs and may reparse/deparse schema
    # expressions differently. Raw schema hashes remain forensic identities,
    # authenticated by the paired restore witness; no SQL is normalized here.
    require(witness['original_schema_sha256'] == proof['schema_sha256'] and
            witness['restored_schema_sha256'] == actual['schema_sha256'], 'restored_schema_binding')
    require(all(proof[key] == actual[key] for key in proof if key not in ('table_oids', 'schema_sha256')),
            'restored_state_mismatch')


def compare_post_commit(proof, actual, new_value, new_oids, restored_schema_sha256):
    """Explicit single-cell permission, never a broad snapshot normalizer."""
    require(set(proof) == set(actual), 'post_commit_shape')
    require(actual['schema_sha256'] == restored_schema_sha256, 'post_commit_schema_changed')
    for key in proof:
        if key not in ('ledger', 'table_oids', 'tables', 'schema_sha256'):
            require(proof[key] == actual[key], 'post_commit_state_mismatch')
    expected_row = decode(proof['ledger']['row'])
    expected_row['value'] = new_value
    require(actual['ledger']['id'] == proof['ledger']['id'] and actual['ledger']['value'] == new_value
            and decode(actual['ledger']['row']) == expected_row, 'post_commit_ledger_cell')
    require(actual['table_oids'] == new_oids and set(actual['tables']) == set(proof['tables']), 'post_commit_identity')
    for name in proof['tables']:
        if name != 'ir_config_parameter':
            require(actual['tables'][name] == proof['tables'][name], 'post_commit_table_changed')
    old_table, new_table = proof['tables']['ir_config_parameter'], actual['tables']['ir_config_parameter']
    # record_send keeps the text field's length prefix at four bytes; only its
    # UTF-8 payload length changes. Hex transport doubles that exact delta.
    delta = 2 * (len(new_value.encode('utf-8')) - len(proof['ledger']['value'].encode('utf-8')))
    require(old_table['rows'] == new_table['rows'] and old_table['bytes'] + delta == new_table['bytes'],
            'post_commit_ledger_table_shape')


def capture(connection, context, database, schema_sha256):
    budget = Budget()
    connection.set_session(readonly=True, isolation_level='REPEATABLE READ', autocommit=False)
    try:
        with connection.cursor() as cr:
            _settings(cr)
            _quiet(cr)
        _classify(connection, context)
        budget.check()
        proof = _snapshot(connection, context, database, schema_sha256, budget)
        require(proof['table_oids'] == {name: facts['oid'] for name, facts in decode(proof['ledger']['value'])['tables'].items()},
                'capture_unexplained_oid')
        return proof
    finally:
        connection.rollback()


def recover(connection, context, database, schema_sha256, proof, *, paired_restore_json,
            paired_restore_sha256, proof_sha256):
    witness = validate_paired_restore(paired_restore_json, paired_restore_sha256, proof, proof_sha256,
                                      context, database, schema_sha256)
    budget = Budget()
    connection.set_session(readonly=False, isolation_level='REPEATABLE READ', autocommit=False)
    committed = False
    try:
        actual = _snapshot(connection, context, database, schema_sha256, budget)
        compare_restored(proof, actual, witness)
        new_value, old_oids = ledger_transition(proof['ledger']['value'], actual['table_oids'], context['tables'])
        require(proof['table_oids'] == old_oids, 'proof_original_oid_mismatch')
        validate_paired_restore(paired_restore_json, paired_restore_sha256, proof, proof_sha256,
                               context, database, schema_sha256)
        with connection.cursor() as cr:
            _quiet(cr)
            cr.execute('SELECT value FROM public.ir_config_parameter WHERE id=%s AND key=%s FOR UPDATE',
                       [proof['ledger']['id'], LEDGER_KEY])
            require(cr.fetchone() == (proof['ledger']['value'],), 'ledger_concurrent_change')
            cr.execute('UPDATE public.ir_config_parameter SET value=%s WHERE id=%s AND key=%s AND value=%s',
                       [new_value, proof['ledger']['id'], LEDGER_KEY, proof['ledger']['value']])
            require(cr.rowcount == 1, 'conditional_update_count')
        _classify(connection, context)
        budget.check()
        try:
            connection.commit()
            committed = True
        except Exception:
            raise RecoveryStopped('BWORK_RECOVERY_STOP:commit_ambiguous_no_retry') from None
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ', autocommit=False)
        post = _snapshot(connection, context, database, schema_sha256, budget)
        compare_post_commit(proof, post, new_value, actual['table_oids'], schema_sha256)
        classification = _classify(connection, context)
        budget.check()
        return {'protocol': PROTOCOL, 'status': 'RECOVERED', 'database': database,
                'source': context['identity'], 'source_commit': context['identity']['commit'],
                'schema_sha256': schema_sha256,
                'original_schema_sha256': proof['schema_sha256'],
                'paired_restore_sha256': paired_restore_sha256, 'proof_sha256': proof_sha256,
                'old_ledger_sha256': hashlib.sha256(proof['ledger']['value'].encode()).hexdigest(),
                'new_ledger_sha256': hashlib.sha256(new_value.encode()).hexdigest(),
                'old_oids': old_oids, 'new_oids': actual['table_oids'],
                'post_commit_proof_sha256': digest(post), 'original_classifier': classification}
    except RecoveryStopped:
        if not committed:
            connection.rollback()
        raise
    except Exception:
        if not committed:
            connection.rollback()
        raise RecoveryStopped('BWORK_RECOVERY_STOP:' + ('post_commit_failed_no_retry' if committed else 'verification_failed')) from None
    finally:
        if committed:
            connection.rollback()  # Read-only post-commit verification transaction only.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'recover'))
    parser.add_argument('--database', required=True)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--schema-sha256', required=True)
    parser.add_argument('--proof-sha256')
    parser.add_argument('--paired-restore-json')
    parser.add_argument('--paired-restore-sha256')
    args = parser.parse_args()
    valid_database(args.database)
    require(hex_digest(args.schema_sha256), 'schema_digest')
    require((args.action == 'recover') == (args.proof_sha256 is not None), 'proof_argument')
    proof = None
    if args.action == 'recover':
        require(hex_digest(args.proof_sha256), 'proof_digest')
        raw = sys.stdin.buffer.read(MAX_PROOF + 1)
        require(len(raw) <= MAX_PROOF and hashlib.sha256(raw).hexdigest() == args.proof_sha256, 'proof_bytes')
        proof = decode(raw)
        require(raw == canonical(proof) + b'\n', 'proof_canonical_bytes')
    require((args.action == 'recover') == (args.paired_restore_json is not None) and
            (args.action == 'recover') == (args.paired_restore_sha256 is not None), 'paired_restore_argument')
    context = source_context(args.source_root, args.source_commit, args.database)
    if args.action == 'recover':
        validate_paired_restore(args.paired_restore_json, args.paired_restore_sha256, proof, args.proof_sha256,
                               context, args.database, args.schema_sha256)
    import configparser
    import psycopg2
    config = configparser.ConfigParser()
    config.read('/etc/odoo/odoo.conf')
    options = config['options'] if config.has_section('options') else {}
    connection = psycopg2.connect(dbname=args.database, connect_timeout=10,
        host=os.environ.get('HOST') or options.get('db_host') or 'db',
        port=os.environ.get('PORT') or options.get('db_port') or '5432',
        user=os.environ.get('USER') or options.get('db_user') or 'odoo',
        password=os.environ.get('PASSWORD') or options.get('db_password'))
    try:
        result = (capture(connection, context, args.database, args.schema_sha256) if args.action == 'capture'
                  else recover(connection, context, args.database, args.schema_sha256, proof,
                               paired_restore_json=args.paired_restore_json,
                               paired_restore_sha256=args.paired_restore_sha256, proof_sha256=args.proof_sha256))
        if args.action == 'recover':
            result['proof_sha256'] = args.proof_sha256
        output = canonical(result) + b'\n'
        require(len(output) <= MAX_PROOF, 'proof_output_bound')
        sys.stdout.buffer.write(output)
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except RecoveryStopped as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    except Exception:
        print('BWORK_RECOVERY_STOP:unexpected_failure', file=sys.stderr)
        raise SystemExit(2)

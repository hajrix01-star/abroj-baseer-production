"""BCR fixed-map SQL-only native pre-upgrade prototype.

Run ONLY through the reviewed, quiesced --pre-upgrade-scripts boundary with a
canonical -u list. Never import this from an addon __init__, HTTP or a cron.
The caller owns commit/rollback and the paired DB+filestore restore boundary.
Odoo's later per-module commits mean the WHOLE upgrade is not atomic.
"""
import hashlib
import io
import json
import re
import tokenize
from pathlib import Path
from xml.etree import ElementTree
from zlib import crc32


MAP_PATH = Path(__file__).resolve().parents[1] / 'canonical_name_map.json'
LEDGER_KEY = 'baseer_bwork.canonical_rename.v1'
LOCK_KEY = 'baseer-bwork-canonical-rename-v1'
_IDENTIFIER = re.compile(r'^[a-z_][a-z_0-9]*$')


class MigrationStopped(RuntimeError):
    """Fail closed with a fixed code; never log payloads or credentials."""


def _stop(code):
    raise MigrationStopped(code)


def identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        _stop('invalid_identifier')
    return '"' + value + '"'


def pg_name(value):
    # Exact official Odoo19 make_identifier convention (ASCII schema names).
    return value if len(value) <= 63 else f'{value[:54]}_{crc32(value.encode()):08x}'


def load_mapping():
    raw = MAP_PATH.read_bytes()
    mapping = json.loads(raw)
    if mapping.get('schema_version') != 1 or mapping.get('migration_id') != 'BCR-20261020-v1':
        _stop('invalid_mapping')
    for family in ('modules', 'models', 'fields', 'xmlids', 'indexes'):
        pairs = mapping[family]
        if len({row['old'] if family != 'fields' else (row['model'], row['old']) for row in pairs}) != len(pairs):
            _stop('duplicate_mapping')
    return mapping, hashlib.sha256(raw).hexdigest()


def _exists(cr, table, column=None):
    if column is None:
        cr.execute('SELECT to_regclass(%s)', [table])
        return cr.fetchone()[0] is not None
    cr.execute('''SELECT 1 FROM information_schema.columns
                   WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s''',
               [table, column])
    return bool(cr.fetchone())


def _column_type(cr, table, column):
    cr.execute('''SELECT data_type FROM information_schema.columns
                   WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s''',
               [table, column])
    row = cr.fetchone()
    return row[0] if row else None


def _row_identity(cr, table):
    cr.execute(f'''SELECT count(*), md5(COALESCE(string_agg(id::text, ',' ORDER BY id), ''))
                     FROM {identifier(table)}''')
    return list(cr.fetchone())


def _safety(cr, mapping):
    keys = mapping['compatibility']
    cr.execute('SELECT key,value FROM ir_config_parameter WHERE key IN %s',
               [(keys['old_ready_key'], keys['new_ready_key'])])
    ready = dict(cr.fetchall())
    if len(ready) > 1:
        _stop('readiness_key_collision')
    if any(value != '0' for value in ready.values()):
        _stop('readiness_not_off')
    if _exists(cr, 'baseer_bwork_retention_policy'):
        cr.execute('SELECT 1 FROM baseer_bwork_retention_policy WHERE enabled IS TRUE LIMIT 1')
        if cr.fetchone():
            _stop('retention_policy_enabled')
    if _exists(cr, 'baseer_bwork_retention_run'):
        cr.execute("SELECT 1 FROM baseer_bwork_retention_run WHERE state IN ('queued','running') LIMIT 1")
        if cr.fetchone():
            _stop('retention_work_active')


def _module_state(cr, mapping):
    cr.execute("SELECT id,name,state FROM ir_module_module WHERE name LIKE 'baseer_bchat%' OR name LIKE 'baseer_bwork%'")
    rows = {name: (record_id, state) for record_id, name, state in cr.fetchall()}
    supported = {x[k] for x in mapping['modules'] for k in ('old', 'new')}
    active = {'installed', 'to upgrade', 'to install', 'to remove'}
    for name, (_, state) in rows.items():
        if name.startswith('baseer_bchat') and name not in supported and state in active:
            _stop('unsupported_installed_old_closure')
    for row in mapping['modules']:
        old, new = rows.get(row['old']), rows.get(row['new'])
        if old and new:
            _stop('module_collision')
        if old and old[1] not in ('installed', 'to upgrade', 'uninstalled'):
            _stop('unsupported_old_module_state')
        if new and new[1] not in ('installed', 'to upgrade', 'uninstalled'):
            _stop('unsupported_new_module_state')
    return rows


def _preflight(cr, mapping, module_rows, ledger):
    _residual_schema(cr, mapping, canonical=False)
    active = ('installed', 'to upgrade')
    old_modules = [x for x in mapping['modules'] if module_rows.get(x['old'], (None, None))[1] in active]
    new_modules = [x for x in mapping['modules'] if module_rows.get(x['new'], (None, None))[1] in active]
    old_tables = [x for x in mapping['models'] if x['old_table'] and _exists(cr, x['old_table'])]
    new_tables = [x for x in mapping['models'] if x['new_table'] and _exists(cr, x['new_table'])]
    if old_tables and new_tables:
        _stop('mixed_tables')
    if old_modules and any(x['new'] in module_rows for x in mapping['modules']):
        _stop('mixed_modules')
    if not old_modules and not new_modules:
        if not old_tables and not new_tables and not ledger and any(x['old'] in module_rows for x in mapping['modules']):
            _stop('old_catalog_only_bootstrap_required')
        if old_tables or new_tables or ledger:
            _stop('orphaned_schema')
        cr.execute("SELECT 1 FROM ir_model WHERE model LIKE 'baseer.bchat.%' OR model IN %s LIMIT 1",
                   [tuple(x['new'] for x in mapping['models'])])
        if cr.fetchone():
            _stop('orphaned_model_metadata')
        return 'fresh'
    if new_modules:
        if not ledger or old_tables or len(new_tables) != 14:
            _stop('unverified_canonical_state')
        return 'complete'
    if ledger or len(old_tables) != 14 or not any(x['old'] == 'baseer_bchat' for x in old_modules):
        _stop('partial_old_schema')
    for row in mapping['models']:
        cr.execute('SELECT model FROM ir_model WHERE model IN %s', [(row['old'], row['new'])])
        found = {value[0] for value in cr.fetchall()}
        if row['new'] in found or (not row['abstract'] and row['old'] not in found):
            _stop('model_collision_or_missing')
    for row in mapping['fields']:
        cr.execute('SELECT name FROM ir_model_fields WHERE model=%s AND name IN %s',
                   [row['model'], (row['old'], row['new'])])
        names = {value[0] for value in cr.fetchall()}
        owner = 'baseer_bchat_procurement' if row['old'].startswith('bchat_order') or row['old'] in (
            'bchat_can_order', 'bchat_order_operator_eligible', 'bchat_room_id', 'bchat_message_id') else 'baseer_bchat'
        expected = module_rows.get(owner, (None, None))[1] in active
        if row['new'] in names or (expected and row['old'] not in names) or (not expected and row['old'] in names):
            _stop('field_collision_or_missing')
        if row['stored'] and _exists(cr, row['table']):
            if _exists(cr, row['table'], row['new']):
                _stop('column_collision')
            if expected and not _exists(cr, row['table'], row['old']):
                _stop('column_missing')
    return 'old'


def _residual_schema(cr, mapping, *, canonical):
    """Reject unknown legacy schema before mutation, not just mapped objects."""
    tables = {row['old_table'] for row in mapping['models'] if row['old_table']}
    sequences = {table + '_id_seq' for table in tables}
    canonical_tables = {row['new_table'] for row in mapping['models'] if row['new_table']} | set(mapping['canonical_existing_tables'])
    canonical_sequences = {table + '_id_seq' for table in canonical_tables}
    cr.execute('''SELECT c.relname,c.relkind,t.relname FROM pg_class c
                   JOIN pg_namespace n ON n.oid=c.relnamespace
                   LEFT JOIN pg_index i ON i.indexrelid=c.oid LEFT JOIN pg_class t ON t.oid=i.indrelid
                  WHERE n.nspname=current_schema()
                    AND (c.relname LIKE 'baseer_bchat%%' OR c.relname LIKE 'baseer_bwork%%')''')
    for name, kind, index_owner in cr.fetchall():
        if name.startswith('baseer_bchat'):
            allowed = not canonical and ((kind == 'r' and name in tables) or (kind == 'S' and name in sequences)
                                          or (kind == 'i' and index_owner in tables))
        else:
            allowed = ((kind == 'r' and name in canonical_tables) or (kind == 'S' and name in canonical_sequences)
                       or (kind == 'i' and index_owner in canonical_tables))
        if not allowed:
            _stop('unknown_or_residual_legacy_relation')
    cr.execute('''SELECT c.conname,t.relname FROM pg_constraint c
                   JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
                  WHERE n.nspname=current_schema() AND c.conname LIKE 'baseer_bchat%%' ''')
    if any(canonical or table not in tables for _, table in cr.fetchall()):
        _stop('unknown_or_residual_legacy_constraint')
    cr.execute("SELECT model FROM ir_model WHERE model LIKE 'baseer.bchat.%%'")
    known = {row['old'] for row in mapping['models']}
    if any(canonical or row[0] not in known for row in cr.fetchall()):
        _stop('unknown_or_residual_legacy_model')
    cr.execute("SELECT model FROM ir_model WHERE model LIKE 'baseer.bwork.%%'")
    canonical_models = {row['new'] for row in mapping['models']} | set(mapping['canonical_existing_models'])
    if any(row[0] not in canonical_models for row in cr.fetchall()):
        _stop('unknown_canonical_model')
    for table, column in mapping['metadata_exact_columns']:
        if _column_type(cr, table, column) in ('text', 'character varying', 'character'):
            cr.execute(f'''SELECT 1 FROM {identifier(table)}
                            WHERE {identifier(column)} LIKE %s
                              AND {identifier(column)} NOT IN %s LIMIT 1''',
                       ['baseer.bchat.%', tuple(known)])
            if cr.fetchone():
                _stop('unknown_legacy_model_reference')
    if canonical:
        old_modules = tuple(row['old'] for row in mapping['modules'])
        cr.execute('SELECT 1 FROM ir_model_data WHERE module IN %s LIMIT 1', [old_modules])
        if cr.fetchone():
            _stop('old_xmlid_namespace_remaining')


def _rename_exact_column_values(cr, table, column, pairs):
    kind = _column_type(cr, table, column)
    if not kind:
        return
    if kind not in ('character varying', 'text', 'character'):
        _stop('unexpected_metadata_column_type')
    for old, new in pairs.items():
        if old != new:
            cr.execute(f'UPDATE {identifier(table)} SET {identifier(column)}=%s WHERE {identifier(column)}=%s',
                       [new, old])


def _expression(value, names):
    """Only exact quoted identifier tokens/dotted paths; no arbitrary prose."""
    if not isinstance(value, str):
        return value
    def quoted(match):
        quote, token = match.group(1), match.group(2)
        if token in names:
            token = names[token]
        elif token.partition('.')[0] in names and token.startswith('baseer_bchat'):
            module, separator, tail = token.partition('.')
            token = names[module] + separator + tail
        elif '.' in token:
            token = '.'.join(names.get(part, part) for part in token.split('.'))
        return quote + token + quote
    result = re.sub(r"(['\"])([a-zA-Z_][a-zA-Z_0-9.]*)\1", quoted, value)
    # Bare field/method names in native invisible/readonly/compute expressions.
    # Tokenization is not evaluation and never visits business-content columns.
    offsets = [0]
    for line in result.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    edits = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(result).readline):
            if token.type == tokenize.NAME and token.string in names:
                target = names[token.string]
                if _IDENTIFIER.fullmatch(target):
                    start = offsets[token.start[0] - 1] + token.start[1]
                    end = offsets[token.end[0] - 1] + token.end[1]
                    edits.append((start, end, target))
    except (tokenize.TokenError, IndentationError):
        _stop('invalid_metadata_expression')
    for start, end, target in reversed(edits):
        result = result[:start] + target + result[end:]
    return result


def rewrite_metadata(value, names, *, xml=False):
    if isinstance(value, dict):
        return {names.get(key, key): rewrite_metadata(item, names, xml=xml) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_metadata(item, names, xml=xml) for item in value]
    if not isinstance(value, str):
        return value
    if not xml:
        return names.get(value, _expression(value, names))
    try:
        root = ElementTree.fromstring(value)
    except ElementTree.ParseError:
        _stop('invalid_view_metadata_xml')
    changed = False
    for node in root.iter():
        for attribute in ('name', 'model', 'ref', 'action', 'inherit_id', 'groups', 'field', 'domain', 't-name', 't-call',
                          'context', 'invisible', 'readonly', 'required', 'filter_domain', 'default_order'):
            if attribute in node.attrib:
                old = node.attrib[attribute]
                # Views may have comma-separated group XMLIDs, not business text.
                parts = []
                for part in old.split(','):
                    module, separator, tail = part.partition('.')
                    target = names.get(part)
                    if target is None and module.startswith('baseer_bchat') and module in names:
                        target = names[module] + separator + tail
                    parts.append(target if target is not None else _expression(part, names))
                new = ','.join(parts)
                if new != old:
                    node.attrib[attribute] = new
                    changed = True
        if node.tag == 'field' and node.attrib.get('name') in ('model', 'res_model') and node.text in names:
            node.text = names[node.text]
            changed = True
    return ElementTree.tostring(root, encoding='unicode') if changed else value


def _metadata_expressions(cr, mapping, names):
    for table, column in mapping['metadata_expression_columns']:
        kind = _column_type(cr, table, column)
        if not kind:
            continue
        if kind not in ('text', 'character varying', 'jsonb', 'json'):
            _stop('unsupported_expression_type')
        cr.execute(f'SELECT id,{identifier(column)} FROM {identifier(table)} WHERE {identifier(column)} IS NOT NULL')
        # Metadata only; never SELECT mail body, attachment bytes or business text.
        for record_id, value in cr.fetchall():
            new = rewrite_metadata(value, names, xml=(table, column) == ('ir_ui_view', 'arch_db'))
            if new != value:
                if kind in ('json', 'jsonb'):
                    new = json.dumps(new, ensure_ascii=False)
                cr.execute(f'UPDATE {identifier(table)} SET {identifier(column)}=%s WHERE id=%s', [new, record_id])


def _verify_derived_reference(cr, field_id, model, column, classification):
    """One proven native query projection, never a generic missing-table skip."""
    relation = classification['relation']
    identifier(relation)
    identifier(column)
    module, name = classification['field_xmlid'].split('.', 1)
    cr.execute('''SELECT f.id,f.model,f.name,f.ttype,f.store
                    FROM ir_model_data d JOIN ir_model_fields f ON f.id=d.res_id
                   WHERE d.module=%s AND d.name=%s AND d.model='ir.model.fields' ''', [module, name])
    if cr.fetchall() != [(field_id, model, column, 'reference', True)]:
        _stop('unverified_derived_reference_identity')
    # to_regclass rejects tables AND views; a surprising new physical projection
    # must be reviewed rather than silently left unconverted.
    if _exists(cr, relation) or _column_type(cr, relation, column) is not None:
        _stop('unexpected_derived_reference_storage')


def _reference_fields(cr, model_names, mapping):
    # ir_model_fields does not expose a model's custom _table. Resolve only
    # catalog-proven owner+field exceptions; unknown storage must still STOP.
    overrides = {(row['model'], row['field']): row['table']
                 for row in mapping['reference_storage_overrides']}
    if len(overrides) != len(mapping['reference_storage_overrides']):
        _stop('duplicate_reference_storage')
    derived = {(row['model'], row['field']): row for row in mapping['reference_derived_nonphysical']}
    if len(derived) != len(mapping['reference_derived_nonphysical']) or set(derived) & set(overrides):
        _stop('overlapping_reference_storage')
    cr.execute("SELECT id,model,name FROM ir_model_fields WHERE ttype='reference' AND store IS TRUE")
    for field_id, model, column in cr.fetchall():
        if (model, column) in derived:
            _verify_derived_reference(cr, field_id, model, column, derived[(model, column)])
            continue
        table = overrides.get((model, column), model_names.get(model, model).replace('.', '_'))
        if not _IDENTIFIER.fullmatch(table) or not _IDENTIFIER.fullmatch(column):
            _stop('unsupported_reference_identifier')
        kind = _column_type(cr, table, column)
        if kind is None:
            _stop('unsupported_reference_storage')
        if kind not in ('text', 'character varying'):
            _stop('unsupported_reference_type')
        for old, new in model_names.items():
            cr.execute(f'''UPDATE {identifier(table)} SET {identifier(column)}=%s || substring({identifier(column)} from %s)
                            WHERE split_part({identifier(column)}, ',', 1)=%s''',
                       [new, len(old) + 1, old])


def _object_names(cr, mapping):
    """Catalog-backed exact object map; all OIDs and constraints survive."""
    names = {}
    for row in mapping['models']:
        if row['old_table']:
            names[row['old_table']] = row['new_table']
            names[row['old_table'] + '_id_seq'] = row['new_table'] + '_id_seq'
    for row in mapping['indexes']:
        names[row['old']] = row['new']
    for row in mapping['constraints']:
        old_table = row['model'].replace('.', '_')
        new_table = old_table.replace('baseer_bchat_', 'baseer_bwork_', 1)
        names[pg_name(old_table + '_' + row['old'])] = pg_name(new_table + '_' + row['new'])
    for row in mapping['fields']:
        if row['stored']:
            names[pg_name(row['table'] + '__' + row['old'] + '_index')] = pg_name(
                row['table'] + '__' + row['new'] + '_index')
            names[pg_name(row['table'] + '_' + row['old'] + '_fkey')] = pg_name(
                row['table'] + '_' + row['new'] + '_fkey')
    # Enumerate concrete object suffixes, including ORM FK/index/PK identifiers.
    old_tables = [row['old_table'] for row in mapping['models'] if row['old_table']]
    cr.execute('''SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname=current_schema() AND c.relkind IN ('i','S')''')
    for (name,) in cr.fetchall():
        for old_table in old_tables:
            if name.startswith(old_table + '_') and name not in names:
                names[name] = pg_name(name.replace(old_table, old_table.replace('baseer_bchat_', 'baseer_bwork_', 1), 1))
                break
    cr.execute('''SELECT c.conname FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
                   WHERE n.nspname=current_schema()''')
    for (name,) in cr.fetchall():
        for old_table in old_tables:
            if name.startswith(old_table + '_') and name not in names:
                names[name] = pg_name(name.replace(old_table, old_table.replace('baseer_bchat_', 'baseer_bwork_', 1), 1))
                break
    return names


def _rename_objects(cr, object_names):
    cr.execute('''SELECT c.oid,c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname=current_schema()''')
    relations = {name: (oid, kind) for oid, name, kind in cr.fetchall()}
    cr.execute('''SELECT c.oid,t.relname,c.conname FROM pg_constraint c
                   JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
                   WHERE n.nspname=current_schema()''')
    constraints = cr.fetchall()
    for old, new in object_names.items():
        if old != new and old in relations and new in relations:
            _stop('relation_object_collision')
    for _, table, old in constraints:
        new = object_names.get(old, old)
        if new != old and any(other_table == table and other == new for _, other_table, other in constraints):
            _stop('constraint_collision')
    # Constraint rename also renames its backing index, preserving both OIDs.
    for _, table, old in constraints:
        new = object_names.get(old, old)
        if new != old:
            cr.execute(f'ALTER TABLE {identifier(table)} RENAME CONSTRAINT {identifier(old)} TO {identifier(new)}')
    for old, (oid, kind) in relations.items():
        new = object_names.get(old, old)
        if new == old:
            continue
        cr.execute('SELECT relname FROM pg_class WHERE oid=%s', [oid])
        current = cr.fetchone()[0]
        if current == new:
            continue
        if current != old or kind not in ('r', 'S', 'i'):
            _stop('unexpected_relation_state')
        command = {'r': 'TABLE', 'S': 'SEQUENCE', 'i': 'INDEX'}[kind]
        cr.execute(f'ALTER {command} {identifier(old)} RENAME TO {identifier(new)}')


def _constraint_metadata(cr, mapping, object_names):
    # Native Odoo19 compares stored constraint comments to source definitions.
    # Preserve the constraint OID instead of provoking later DROP/recreation for
    # the exact field rename. Unknown custom comments are not silently rewritten.
    for row in mapping['constraints']:
        table = row['model'].replace('.', '_').replace('baseer_bchat_', 'baseer_bwork_', 1)
        name = pg_name(table + '_' + row['new'])
        if not _exists(cr, table):
            continue
        cr.execute('''SELECT c.oid,obj_description(c.oid,'pg_constraint') FROM pg_constraint c
                       WHERE c.conrelid=to_regclass(%s) AND c.conname=%s''', [table, name])
        current = cr.fetchone()
        if current and row['old_definition'] != row['new_definition']:
            if current[1] not in (row['old_definition'], row['new_definition']):
                _stop('unexpected_constraint_comment')
            cr.execute(f'COMMENT ON CONSTRAINT {identifier(name)} ON {identifier(table)} IS %s',
                       [row['new_definition']])
    _rename_exact_column_values(cr, 'ir_model_constraint', 'name', object_names)


def _xmlid_target(module, name, model, mapping, module_names, model_names, field_names):
    explicit = {x['old']: x['new'] for x in mapping['xmlids']}
    target = explicit.get(module + '.' + name, module_names.get(module, module) + '.' + name)
    target_module, target_name = target.split('.', 1)
    if module != '__export__':  # User export identities are opaque compatibility IDs.
        for old, new in model_names.items():
            old_u, new_u = old.replace('.', '_'), new.replace('.', '_')
            if target_name == 'model_' + old_u:
                target_name = 'model_' + new_u
            if target_name.startswith('field_' + old_u + '__'):
                target_name = 'field_' + new_u + '__' + target_name[len('field_' + old_u + '__'):]
            if target_name.startswith('selection__' + old_u + '__'):
                target_name = 'selection__' + new_u + '__' + target_name[len('selection__' + old_u + '__'):]
        if model == 'ir.model.fields':
            # Rename field metadata XMLIDs on unchanged res.users/company/request.
            for owner, names in field_names.items():
                prefix = 'field_' + model_names.get(owner, owner).replace('.', '_') + '__'
                for old, new in names.items():
                    if target_name == prefix + old:
                        target_name = prefix + new
        if model == 'ir.model.fields.selection':
            for owner, names in field_names.items():
                prefix = 'selection__' + model_names.get(owner, owner).replace('.', '_') + '__'
                for old, new in names.items():
                    if target_name.startswith(prefix + old + '__'):
                        target_name = prefix + new + target_name[len(prefix + old):]
        if module == 'base' and name.startswith('module_') and name[7:] in module_names:
            target_name = 'module_' + module_names[name[7:]]
    return target_module, target_name


def _xmlids(cr, mapping, module_names, model_names, field_names):
    cr.execute('SELECT id,module,name,model,res_id FROM ir_model_data')
    rows = cr.fetchall()
    targets = {}
    plan = []
    for record_id, module, name, model, res_id in rows:
        target_module, target_name = _xmlid_target(module, name, model, mapping, module_names, model_names, field_names)
        key = (target_module, target_name)
        if key in targets:
            _stop('xmlid_collision')
        targets[key] = record_id
        if (module, name) != key:
            plan.append([*key, record_id])
    for params in plan:
        cr.execute('UPDATE ir_model_data SET module=%s,name=%s WHERE id=%s', params)


def _digest_rows(rows):
    value = json.dumps(rows, sort_keys=True, default=str, separators=(',', ':'))
    return {'count': len(rows), 'sha256': hashlib.sha256(value.encode()).hexdigest()}


def _data_digest(cr, table, *, rename_fields=None, columns=None, provenance=None):
    params = []
    if columns is None:
        expression = 'to_jsonb(t)'
    else:
        projection = ','.join(identifier(name) for name in ['id', *columns])
        table = f'(SELECT {projection} FROM {identifier(table)})'
        expression = 'to_jsonb(t)'
    for old, new in (rename_fields or {}).items():
        expression = f'(({expression}) - %s) || jsonb_build_object(%s,to_jsonb(t)->%s)'
        params.extend([old, new, old])
    source = table if columns is not None else identifier(table)
    where = ' WHERE source_channel=%s' if provenance is not None else ''
    if provenance is not None:
        params.append(provenance)
    cr.execute(f'''SELECT count(*),encode(sha256(convert_to(COALESCE(string_agg(
                      encode(sha256(convert_to(({expression})::text,'UTF8')),'hex'), ',' ORDER BY id),''),'UTF8')),'hex')
                    FROM {source} t{where}''', params)
    return list(cr.fetchone())


def _lineage(cr, mapping, *, canonical):
    """Aggregate proof only: no message, file or personal payload returned."""
    module_names = {x['old']: x['new'] for x in mapping['modules']}
    model_names = {x['old']: x['new'] for x in mapping['models']}
    field_names = {}
    for item in mapping['fields']:
        field_names.setdefault(item['model'], {})[item['old']] = item['new']
    models = tuple(x['new' if canonical else 'old'] for x in mapping['models'])
    result = {'data': {}}
    table_oids = []
    for row in mapping['models']:
        table = row['new_table' if canonical else 'old_table']
        if not table:
            continue
        cr.execute('SELECT to_regclass(%s)::oid', [table])
        table_oids.append(cr.fetchone()[0])
        # Server-side aggregate includes immutable UUID/digest/critical FK/state
        # and content hash without reading any content into the caller process.
        result['data'][row['new_table']] = _data_digest(cr, table)
    for table in mapping['canonical_existing_tables']:
        if _exists(cr, table):
            result['data'][table] = _data_digest(cr, table)
    result['m2m'] = {}
    for table, columns in mapping['m2m_columns'].items():
        if _exists(cr, table):
            first, second = (identifier(column) for column in columns)
            cr.execute(f'''SELECT count(*),encode(sha256(convert_to(COALESCE(string_agg(
                           {first}::text || ':' || {second}::text, ',' ORDER BY {first},{second}),''),'UTF8')),'hex')
                             FROM {identifier(table)}''')
            result['m2m'][table] = list(cr.fetchone())
    for table in ('res_users', 'res_company'):
        selected = [row for row in mapping['fields'] if row['table'] == table and row['stored']
                    and _exists(cr, table, row['new' if canonical else 'old'])]
        columns = [row['new' if canonical else 'old'] for row in selected]
        rename = {} if canonical else {row['old']: row['new'] for row in selected}
        result['data'][table + ':permission_columns'] = _data_digest(cr, table, columns=columns, rename_fields=rename)
    if _exists(cr, 'baseer_procurement_request', 'source_channel'):
        rename = {} if canonical else {row['old']: row['new'] for row in mapping['fields']
                                       if row['table'] == 'baseer_procurement_request' and row['stored']}
        result['data']['baseer_procurement_request:provenance'] = _data_digest(
            cr, 'baseer_procurement_request', rename_fields=rename,
            provenance=mapping['compatibility']['source_channel'])
    cr.execute('SELECT id,model FROM ir_model WHERE model IN %s ORDER BY id', [models])
    result['models'] = _digest_rows([[record_id, model_names.get(name, name)] for record_id, name in cr.fetchall()])
    field_list = tuple(x['new' if canonical else 'old'] for x in mapping['fields'])
    cr.execute('''SELECT id,model,name,relation FROM ir_model_fields
                   WHERE model IN %s OR relation IN %s OR name IN %s ORDER BY id''', [models, models, field_list])
    fields = []
    for record_id, owner, name, relation in cr.fetchall():
        fields.append([record_id, model_names.get(owner, owner), field_names.get(owner, {}).get(name, name),
                       model_names.get(relation, relation)])
    result['fields'] = _digest_rows(fields)
    owner_modules = tuple(set(module_names) | set(module_names.values()) | {'baseer_bwork_admin', 'baseer_bwork_dashboard'})
    base_names = tuple('module_' + name for name in owner_modules)
    cr.execute('''SELECT id,module,name,model,res_id FROM ir_model_data
                   WHERE module IN %s OR (module='base' AND name IN %s) ORDER BY id''', [owner_modules, base_names])
    ids = []
    for record_id, module, name, model, res_id in cr.fetchall():
        target = _xmlid_target(module, name, model, mapping, module_names, model_names, field_names)
        ids.append([record_id, *target, model_names.get(model, model), res_id])
    result['xmlids'] = _digest_rows(ids)
    cr.execute('SELECT id,name FROM ir_module_module WHERE name IN %s ORDER BY id', [owner_modules])
    result['modules'] = _digest_rows([[record_id, module_names.get(name, name)] for record_id, name in cr.fetchall()])
    # Fixed official Odoo19 group-membership table; never grants or actor details.
    cr.execute('SELECT uid,gid FROM res_groups_users_rel ORDER BY uid,gid')
    result['groups'] = _digest_rows(cr.fetchall())
    cr.execute('''SELECT oid,conrelid,confrelid,contype,conkey,confkey,confdeltype,confupdtype,
                         condeferrable,condeferred,convalidated FROM pg_constraint
                   WHERE conrelid IN %s OR confrelid IN %s ORDER BY oid''', [tuple(table_oids), tuple(table_oids)])
    result['constraints'] = _digest_rows(cr.fetchall())
    return result


def verify_transition(cr):
    """ONE-TIME quiesced proof after the FULL loader, read-only/no marker.

    Protected ops must call this only for its recorded old-installed transition,
    before reopening. Normal later classify/verify do not freeze business counts.
    """
    mapping, digest = load_mapping()
    _verify_canonical(cr, mapping)
    cr.execute('SELECT value FROM ir_config_parameter WHERE key=%s', [LEDGER_KEY])
    row = cr.fetchone()
    try:
        ledger = json.loads(row[0]) if row else None
    except (TypeError, ValueError):
        _stop('invalid_ledger')
    if (not ledger or ledger.get('mapping_sha256') != digest or ledger.get('mode') != 'renamed'
            or ledger.get('lineage') != _lineage(cr, mapping, canonical=True)):
        _stop('first_transition_lineage_mismatch')
    return {'transition_lineage': 'PASS', 'mapping_sha256': digest, 'mode': 'old-installed'}


def migrate(cr, installed_version):
    """Native Odoo entrypoint; caller MUST keep all workers quiesced."""
    del installed_version
    mapping, digest = load_mapping()
    cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', [LOCK_KEY])
    _safety(cr, mapping)
    cr.execute('SELECT value FROM ir_config_parameter WHERE key=%s FOR UPDATE', [LEDGER_KEY])
    row = cr.fetchone()
    try:
        ledger = json.loads(row[0]) if row else None
    except (TypeError, ValueError):
        _stop('invalid_ledger')
    if ledger and (ledger.get('mapping_sha256') != digest or ledger.get('status') != 'complete'):
        _stop('ledger_mismatch')
    modules = _module_state(cr, mapping)
    state = _preflight(cr, mapping, modules, ledger)
    if state == 'fresh':
        return
    if state == 'complete':
        for table, facts in ledger['tables'].items():
            cr.execute('SELECT to_regclass(%s)::oid', [table])
            if cr.fetchone()[0] != facts['oid']:
                _stop('completed_identity_mismatch')
        for name, expected_id in ledger['modules'].items():
            if modules.get(name, (None,))[0] != expected_id:
                _stop('completed_module_identity_mismatch')
        _verify_canonical(cr, mapping)
        return
    module_names = {x['old']: x['new'] for x in mapping['modules']}
    model_names = {x['old']: x['new'] for x in mapping['models']}
    field_names = {}
    for item in mapping['fields']:
        field_names.setdefault(item['model'], {})[item['old']] = item['new']
    tables = {}
    for item in mapping['models']:
        if item['old_table']:
            cr.execute('SELECT to_regclass(%s)::oid', [item['old_table']])
            tables[item['new_table']] = {'oid': cr.fetchone()[0], 'rows': _row_identity(cr, item['old_table'])}
    lineage = _lineage(cr, mapping, canonical=False)
    # Explicit noncommitting SQL; no ORM permissions/inverses or content writers.
    object_names = _object_names(cr, mapping)
    _rename_objects(cr, object_names)
    for item in mapping['fields']:
        if item['stored'] and _exists(cr, item['table'], item['old']):
            cr.execute(f'ALTER TABLE {identifier(item["table"])} RENAME COLUMN {identifier(item["old"])} TO {identifier(item["new"])}')
    _constraint_metadata(cr, mapping, object_names)
    for owner, names in field_names.items():
        for old, new in names.items():
            cr.execute('UPDATE ir_model_fields SET name=%s WHERE model=%s AND name=%s', [new, owner, old])
            if _exists(cr, 'ir_model_fields', 'relation_field'):
                cr.execute('UPDATE ir_model_fields SET relation_field=%s WHERE relation=%s AND relation_field=%s',
                           [new, owner, old])
            if _exists(cr, 'ir_attachment', 'res_field'):
                cr.execute('UPDATE ir_attachment SET res_field=%s WHERE res_model=%s AND res_field=%s', [new, owner, old])
    _xmlids(cr, mapping, module_names, model_names, field_names)
    for table, column in mapping['metadata_exact_columns']:
        _rename_exact_column_values(cr, table, column, model_names)
    _reference_fields(cr, model_names, mapping)
    names = {**model_names, **module_names, **mapping['identifiers'],
             **{x['old']: x['new'] for x in mapping['xmlids']}}
    for fields in field_names.values():
        names.update(fields)
    _metadata_expressions(cr, mapping, names)
    _rename_exact_column_values(cr, 'ir_ui_view', 'key', {x['old']: x['new'] for x in mapping['xmlids']})
    for old, new in module_names.items():
        if _exists(cr, 'ir_ui_view', 'key'):
            cr.execute("UPDATE ir_ui_view SET key=%s || substring(key from %s) WHERE split_part(key,'.',1)=%s",
                       [new, len(old) + 1, old])
    _rename_exact_column_values(cr, 'ir_module_module_dependency', 'name', module_names)
    _rename_exact_column_values(cr, 'ir_module_module', 'name', module_names)
    keys = mapping['compatibility']
    cr.execute('UPDATE ir_config_parameter SET key=%s WHERE key=%s', [keys['new_ready_key'], keys['old_ready_key']])
    for table, facts in tables.items():
        if _row_identity(cr, table) != facts['rows']:
            _stop('post_migration_identity_mismatch')
    result = {'status': 'complete', 'mode': 'renamed', 'lineage': lineage,
              'mapping_sha256': digest, 'tables': tables,
              'modules': {module_names[name]: value[0] for name, value in modules.items() if name in module_names}}
    cr.execute('INSERT INTO ir_config_parameter(key,value) VALUES(%s,%s)',
               [LEDGER_KEY, json.dumps(result, sort_keys=True, separators=(',', ':'))])


def _verify_canonical(cr, mapping, *, fresh_core_only=False):
    """Read-only proof; the core post-init cannot attest later sibling loads.

    Only fresh attestation narrows required NEW field presence to loaded core.
    Old fields/columns and residual identifiers are always rejected globally.
    Default verification still checks every installed/upgrading/planned owner.
    """
    _safety(cr, mapping)
    _residual_schema(cr, mapping, canonical=True)
    for row in mapping['models']:
        if row['old_table'] and (_exists(cr, row['old_table']) or not _exists(cr, row['new_table'])):
            _stop('canonical_table_postcondition')
        cr.execute('SELECT id,model FROM ir_model WHERE model IN %s', [(row['old'], row['new'])])
        names = {name for _, name in cr.fetchall()}
        if row['old'] in names or (not row['abstract'] and row['new'] not in names):
            _stop('canonical_model_postcondition')
    for row in mapping['fields']:
        cr.execute('SELECT 1 FROM ir_model_fields WHERE model=%s AND name=%s LIMIT 1', [row['model'], row['old']])
        if cr.fetchone() or (row['stored'] and _exists(cr, row['table'], row['old'])):
            _stop('canonical_field_postcondition')
        owner = 'baseer_bwork_procurement' if row['old'].startswith('bchat_order') or row['old'] in (
            'bchat_can_order', 'bchat_order_operator_eligible', 'bchat_room_id', 'bchat_message_id') else 'baseer_bwork'
        cr.execute('SELECT state FROM ir_module_module WHERE name=%s', [owner])
        module = cr.fetchone()
        required = owner == 'baseer_bwork' if fresh_core_only else (
            module and module[0] in ('installed', 'to upgrade', 'to install'))
        if required:
            cr.execute('SELECT 1 FROM ir_model_fields WHERE model=%s AND name=%s LIMIT 1', [row['model'], row['new']])
            if not cr.fetchone() or (row['stored'] and not _exists(cr, row['table'], row['new'])):
                _stop('canonical_field_missing')
    for table, column in mapping['metadata_exact_columns']:
        if _column_type(cr, table, column) in ('text', 'character varying', 'character'):
            cr.execute(f'SELECT 1 FROM {identifier(table)} WHERE {identifier(column)} IN %s LIMIT 1',
                       [tuple(row['old'] for row in mapping['models'])])
            if cr.fetchone():
                _stop('old_model_reference_remaining')


def attest_fresh(cr):
    """Core fresh-install metadata attestation, never a whole-release receipt.

    Called by the native core post-init hook only. Other addons may not yet be
    loaded. No policy/role/cron/content row is created or changed.
    """
    mapping, digest = load_mapping()
    cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', [LOCK_KEY])
    _verify_canonical(cr, mapping, fresh_core_only=True)
    cr.execute('SELECT 1 FROM ir_config_parameter WHERE key=%s', [LEDGER_KEY])
    if cr.fetchone():
        _stop('fresh_ledger_already_exists')
    old_names = tuple(row['old'] for row in mapping['modules'])
    cr.execute('SELECT 1 FROM ir_module_module WHERE name IN %s LIMIT 1', [old_names])
    if cr.fetchone():
        _stop('old_module_on_fresh_install')
    cr.execute("SELECT id,state FROM ir_module_module WHERE name='baseer_bwork'")
    core = cr.fetchone()
    if not core or core[1] != 'to install':
        _stop('not_native_fresh_install')
    tables = {}
    for row in mapping['models']:
        if row['new_table']:
            cr.execute('SELECT to_regclass(%s)::oid', [row['new_table']])
            tables[row['new_table']] = {'oid': cr.fetchone()[0]}
    result = {'status': 'complete', 'mode': 'fresh', 'scope': ['baseer_bwork'],
              'mapping_sha256': digest, 'tables': tables, 'modules': {'baseer_bwork': core[0]}}
    cr.execute('INSERT INTO ir_config_parameter(key,value) VALUES(%s,%s)',
               [LEDGER_KEY, json.dumps(result, sort_keys=True, separators=(',', ':'))])


def classify(cr, requested_modules):
    """Read-only fixed-scope install/upgrade classification for protected ops."""
    mapping, digest = load_mapping()
    allowed = {row['new'] for row in mapping['modules']} | {
        'baseer_access_roles', 'baseer_procurement_requests', 'baseer_bwork_admin', 'baseer_bwork_dashboard'}
    if (not isinstance(requested_modules, (list, tuple)) or not requested_modules
            or len(requested_modules) > len(allowed) or len(set(requested_modules)) != len(requested_modules)
            or any(name not in allowed for name in requested_modules)):
        _stop('unsupported_requested_modules')
    _safety(cr, mapping)
    modules = _module_state(cr, mapping)
    cr.execute('SELECT value FROM ir_config_parameter WHERE key=%s', [LEDGER_KEY])
    row = cr.fetchone()
    try:
        ledger = json.loads(row[0]) if row else None
    except (ValueError, TypeError):
        _stop('invalid_ledger')
    if ledger and (ledger.get('mapping_sha256') != digest or ledger.get('status') != 'complete'):
        _stop('ledger_mismatch')
    state = _preflight(cr, mapping, modules, ledger)
    if state == 'complete':
        _verify_canonical(cr, mapping)
        for table, facts in ledger['tables'].items():
            cr.execute('SELECT to_regclass(%s)::oid', [table])
            if cr.fetchone()[0] != facts['oid']:
                _stop('completed_identity_mismatch')
        for name, expected_id in ledger['modules'].items():
            if modules.get(name, (None,))[0] != expected_id:
                _stop('completed_module_identity_mismatch')
    cr.execute('SELECT name,state FROM ir_module_module WHERE name IN %s', [tuple(sorted(allowed))])
    existing = dict(cr.fetchall())
    rename = {row['old']: row['new'] for row in mapping['modules']}
    scope = set(requested_modules)
    # Installed consumers must be upgraded together, never silently autoinstalled.
    scope.update(rename.get(name, name) for name, (_, value) in modules.items()
                 if name in rename and value in ('installed', 'to upgrade'))
    scope.update(name for name, value in existing.items() if value in ('installed', 'to upgrade'))
    installs, upgrades = [], []
    for name in sorted(scope):
        old = next((row['old'] for row in mapping['modules'] if row['new'] == name), None)
        status = modules.get(old, (None, None))[1] if old else None
        status = status or existing.get(name)
        if status in ('installed', 'to upgrade'):
            upgrades.append(name)
        elif status in (None, 'uninstalled') and name in requested_modules:
            installs.append(name)
        else:
            _stop('unsupported_closure_state')
    return {'schema_version': 1, 'mapping_sha256': digest,
            'classification': {'old': 'old-installed', 'fresh': 'fresh', 'complete': 'canonical-ready'}[state],
            'install': installs, 'upgrade': upgrades, 'required_closure': sorted(scope),
            'native_pre_upgrade_required': state == 'old'}


def _main():
    """Transport-only CLI; native migrate()/attest_fresh() never read secrets."""
    import argparse
    import configparser
    import os
    import sys
    parser = argparse.ArgumentParser(description='Fixed BWork read-only classification/verification')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--classify', action='store_true')
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--verify-transition', action='store_true')
    parser.add_argument('--modules', required=True)
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    try:
        import psycopg2
        configuration = configparser.ConfigParser()
        configuration.read('/etc/odoo/odoo.conf')
        options = configuration['options'] if configuration.has_section('options') else {}
        values = {'dbname': args.database, 'connect_timeout': 10,
                  'host': os.environ.get('HOST') or options.get('db_host') or 'db',
                  'port': os.environ.get('PORT') or options.get('db_port') or '5432',
                  'user': os.environ.get('USER') or options.get('db_user') or 'odoo',
                  'password': os.environ.get('PASSWORD') or options.get('db_password')}
        with psycopg2.connect(**values) as connection:
            connection.set_session(readonly=True, isolation_level='READ COMMITTED', autocommit=False)
            with connection.cursor() as cr:
                cr.execute("SET LOCAL statement_timeout='30000ms'")
                cr.execute("SET LOCAL lock_timeout='5000ms'")
                result = classify(cr, args.modules.split(','))
                if (args.verify or args.verify_transition) and result['classification'] != 'canonical-ready':
                    _stop('verification_requires_canonical_ready')
                if args.verify_transition:
                    result.update(verify_transition(cr))
            connection.rollback()
        output = json.dumps(result, sort_keys=True, separators=(',', ':'))
        if len(output.encode()) > 65536:
            _stop('classification_too_large')
        print(output)
    except Exception as error:
        code = str(error) if isinstance(error, MigrationStopped) else 'classification_failed'
        print(json.dumps({'schema_version': 1, 'error': code}, separators=(',', ':')))
        sys.exit(2)


if __name__ == '__main__':
    _main()

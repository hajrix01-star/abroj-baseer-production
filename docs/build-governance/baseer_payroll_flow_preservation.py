"""Read-only BP-S2 preservation comparison against the coherent preinstall dump.

Run after the October UI/concurrency preview is complete. Temporary COPY tables
are rolled back. Evidence reports changed field names and safe accounting values,
never credentials or portal tokens.
"""
import hashlib
import json
import re
import traceback
from decimal import Decimal
from pathlib import Path

import om_payroll_ops as ops


ROOT = ops.ROOT
OUT = ROOT / 'docs/releases/2026-09-08-baseer-payroll-flow'
BACKUP = ROOT / '.local-backups/baseer-payroll-flow-20260908/preinstall/database.dump'
PREVIEW = ROOT / 'docs/build-governance/baseer_payroll_flow_preview.json'
RESULT = OUT / 'preservation.json'
ops.OUT = OUT
R = {'status': 'started', 'database': ops.QA, 'tables': {}, 'violations': []}
RESIDUAL = {'amount_residual', 'amount_residual_currency'}
MATCHING = RESIDUAL | {'matching_number', 'full_reconcile_id', 'reconciled'}
WRITE_META = {'write_uid', 'write_date'}
CLEARING_LINES = {2628, 2870, 2872, 2874, 2876}
OLD_PAYMENTS = {272, 310, 311, 312, 313}
SAFE_VALUES = MATCHING | WRITE_META | {
    'state', 'payment_account_id', 'reconcile', 'paid_amount', 'balance',
    'amount', 'debit', 'credit', 'is_matched', 'is_reconciled',
}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def parse_json(output):
    # PostgreSQL json_agg(row) can contain physical newlines between objects.
    # Decode the complete object, ignoring surrounding psql command tags.
    start = output.find('{')
    if start >= 0:
        return json.JSONDecoder().raw_decode(output[start:])[0]
    raise RuntimeError('SQL did not return its expected evidence object')


def compare(table):
    dump = ops.run(['docker', 'exec', ops.DB, 'pg_restore', '--data-only', '--table=' + table,
                    '-f', '-', '/tmp/om-payroll-before.dump'], capture_output=True, text=True).stdout
    match = re.search(r'COPY public\.' + re.escape(table) + r' \((.*?)\) FROM stdin;\n(.*?)^\\\.$', dump, re.S | re.M)
    if not match:
        raise RuntimeError('Backup is missing table ' + table)
    columns, values = match.groups()
    values = values.rstrip('\n')
    # Only original backup columns are compared; new schema fields are not old-data changes.
    prefix = ('BEGIN; CREATE TEMP TABLE bp_flow_before AS SELECT ' + columns + ' FROM ' + table +
              ' WITH NO DATA; COPY bp_flow_before (' + columns + ') FROM stdin;\n' + (values + '\n' if values else '') + '\\.\n')
    safe_keys = ','.join("'" + key + "'" for key in sorted(SAFE_VALUES))
    query = prefix + """
        SELECT json_build_object(
          'before_count', (SELECT count(*) FROM bp_flow_before),
          'after_count', (SELECT count(*) FROM TABLE_NAME),
          'original_ids', (SELECT coalesce(json_agg(id ORDER BY id),'[]'::json) FROM bp_flow_before),
          'new_ids', (SELECT coalesce(json_agg(a.id ORDER BY a.id),'[]'::json) FROM TABLE_NAME a
                      LEFT JOIN bp_flow_before b USING(id) WHERE b.id IS NULL),
          'missing_ids', (SELECT coalesce(json_agg(b.id ORDER BY b.id),'[]'::json) FROM bp_flow_before b
                          LEFT JOIN TABLE_NAME a USING(id) WHERE a.id IS NULL),
          'changes', (SELECT coalesce(json_agg(d ORDER BY d.id),'[]'::json) FROM (
            SELECT b.id, array_agg(k.key ORDER BY k.key) AS changed_fields,
              coalesce(jsonb_object_agg(k.key, jsonb_build_object('before',k.value,'after',to_jsonb(a)->k.key))
                FILTER (WHERE k.key IN (SAFE_KEYS)), '{}'::jsonb) AS safe_values
            FROM bp_flow_before b JOIN (SELECT ORIGINAL_COLUMNS FROM TABLE_NAME) a USING(id)
            CROSS JOIN LATERAL jsonb_each(to_jsonb(b)) k
            WHERE k.value IS DISTINCT FROM (to_jsonb(a)->k.key)
            GROUP BY b.id
          ) d)
        ); ROLLBACK;
    """.replace('TABLE_NAME', table).replace('SAFE_KEYS', safe_keys).replace('ORIGINAL_COLUMNS', columns)
    return parse_json(ops.sql(ops.QA, query))


def violation(message):
    R['violations'].append(message)


try:
    assert ops.QA == 'baseer_reports_qa_20260907'
    assert BACKUP.is_file() and PREVIEW.is_file()
    local_hash = digest(BACKUP)
    container_hash = ops.run(['docker', 'exec', ops.DB, 'sha256sum', '/tmp/om-payroll-before.dump'],
                             capture_output=True, text=True).stdout.split()[0]
    assert local_hash == container_hash, 'Container dump is not the frozen BP-S2 preinstall backup'
    R['backup_sha256'] = local_hash
    R['backup_path'] = BACKUP.relative_to(ROOT).as_posix()
    preview = json.loads(PREVIEW.read_text(encoding='utf-8'))
    run_id = preview['run_id']
    assert isinstance(run_id, int) and run_id > 0
    R['october_run_id'] = run_id
    lineage = parse_json(ops.sql(ops.QA, """
        SELECT json_build_object(
          'valid_run', (SELECT company_id=10 AND baseer_month='2026-10-01'::date AND state='done'
                        FROM hr_payslip_run WHERE id=RUN_ID),
          'allocations', (SELECT coalesce(json_agg(json_build_object(
              'id', a.id, 'loan_id',a.loan_id,'line_id',a.line_id,'payslip_id',a.payslip_id,
              'move_id',a.move_id,'amount',a.amount)), '[]'::json)
            FROM baseer_hr_loan_allocation a JOIN hr_payslip s ON s.id=a.payslip_id
            WHERE s.payslip_run_id=RUN_ID AND s.company_id=10),
          'principal_lines', (SELECT coalesce(json_agg(DISTINCT l.id),'[]'::json)
            FROM account_move_line l JOIN baseer_hr_loan loan ON loan.move_id=l.move_id
            JOIN baseer_hr_loan_allocation a ON a.loan_id=loan.id
            JOIN hr_payslip s ON s.id=a.payslip_id
            WHERE s.payslip_run_id=RUN_ID AND s.company_id=10 AND l.debit>0)
        );
    """.replace('RUN_ID', str(run_id))))
    assert lineage['valid_run'], 'Preview must be the approved October QA run'
    assert sum((Decimal(str(row['amount'])) for row in lineage['allocations']), Decimal('0')) == Decimal('600.00'), 'Expected October recovery of the existing 600 advance balance'
    loan_ids = {row['loan_id'] for row in lineage['allocations']}
    installment_ids = {row['line_id'] for row in lineage['allocations']}
    principal_ids = set(lineage['principal_lines'])
    R['authorized_october_loan_recovery'] = lineage
    R['reconciliation_metadata_note'] = (
        'Native reconciliation also updates write_date and may use the stored-compute user for write_uid. '
        'These audit fields are allowed only on the five named outstanding lines and the source-proven October loan principal lines; '
        'all original debit, credit, account, partner, dates and move links remain protected by exact comparison.'
    )
    allowance = {
        'account_move_line': {**{key: MATCHING | WRITE_META for key in CLEARING_LINES}, 2508: RESIDUAL,
                              **{key: MATCHING | WRITE_META for key in principal_ids}},
        'account_payment': {key: {'state', 'is_matched', 'is_reconciled'} | WRITE_META for key in OLD_PAYMENTS},
        'account_payment_method_line': {110: {'payment_account_id'} | WRITE_META},
        'account_account': {1244: {'reconcile'} | WRITE_META},
        'baseer_hr_loan': {key: {'paid_amount', 'balance', 'state'} | WRITE_META for key in loan_ids},
        'baseer_hr_loan_line': {key: {'paid_amount', 'balance', 'state'} | WRITE_META for key in installment_ids},
    }
    tables = ['account_move', 'account_move_line', 'account_payment', 'account_account',
              'account_payment_method_line', 'baseer_hr_loan', 'baseer_hr_loan_line',
              'baseer_hr_loan_allocation', 'baseer_hr_loan_defer', 'hr_payslip', 'hr_payslip_run']
    for table in tables:
        result = compare(table)
        R['tables'][table] = result
        if result['missing_ids']:
            violation(table + ': original rows were removed: ' + str(result['missing_ids']))
        for row in result['changes']:
            allowed = allowance.get(table, {}).get(row['id'], set())
            unexpected = set(row['changed_fields']) - allowed
            row['allowed_fields'] = sorted(allowed)
            row['allowed_change'] = not unexpected
            if unexpected:
                violation(table + '/' + str(row['id']) + ': unexpected fields ' + ', '.join(sorted(unexpected)))
        result['original_rows_exact'] = not result['missing_ids'] and not result['changes']
    assert loan_ids.issubset(set(R['tables']['baseer_hr_loan']['original_ids'])), 'October recovery must target preexisting advances'
    assert principal_ids.issubset(set(R['tables']['account_move_line']['original_ids'])), 'October recovery must preserve existing principal entries'
    # Explicit values prevent an allowed field-name match from hiding an incorrect operation.
    checks = parse_json(ops.sql(ops.QA, """
        SELECT json_build_object(
          'method_110_direct_bank', (SELECT payment_account_id=1415 FROM account_payment_method_line WHERE id=110),
          'cash_1244_nonreconcilable', (SELECT reconcile IS FALSE FROM account_account WHERE id=1244),
          'old_payments_paid', (SELECT count(*)=5 AND bool_and(state='paid' AND is_matched)
                               FROM account_payment WHERE id IN (272,310,311,312,313)),
          'cleared_outstanding_zero', (SELECT count(*)=5 AND bool_and(amount_residual=0 AND amount_residual_currency=0)
                                      FROM account_move_line WHERE id IN (2628,2870,2872,2874,2876)),
          'cash_derived_residual_zero', (SELECT amount_residual=0 AND amount_residual_currency=0 FROM account_move_line WHERE id=2508)
        );
    """))
    R['authorized_result_checks'] = checks
    for name, passed in checks.items():
        if not passed:
            violation('Authorized operation result failed: ' + name)
    ops.snapshot('baseer_dev', 'main-preservation-after')
    main_before = json.loads((OUT / 'main-before.json').read_text(encoding='utf-8'))
    main_after = json.loads((OUT / 'main-preservation-after.json').read_text(encoding='utf-8'))
    R['main_exact'] = main_before == main_after
    if not R['main_exact']:
        violation('Main database snapshot changed')
    R['status'] = 'passed' if not R['violations'] else 'failed'
except Exception:
    R['status'] = 'failed'
    # No subprocess stderr is included: COPY errors can contain source-row values.
    R['error_type'] = type(__import__('sys').exc_info()[1]).__name__
    R['error_location'] = traceback.extract_tb(__import__('sys').exc_info()[2])[-1].lineno
finally:
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': R['status'], 'main_exact': R.get('main_exact'),
                      'changed_original_ids': {table: [row['id'] for row in value['changes']]
                                               for table, value in R['tables'].items()},
                      'violations': R['violations'], 'error_type': R.get('error_type'),
                      'error_location': R.get('error_location')}, ensure_ascii=False, indent=2))
if R['status'] != 'passed':
    raise SystemExit(1)

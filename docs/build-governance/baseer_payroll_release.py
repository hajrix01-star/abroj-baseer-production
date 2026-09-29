"""Freeze the addon artifact and compare pre-existing QA financial records."""
import hashlib,json,re,zipfile
from pathlib import Path
import om_payroll_ops as ops
ROOT=ops.ROOT
OUT=ROOT/'docs/releases/2026-09-08-baseer-payroll'
ops.OUT=OUT
ops.snapshot('baseer_dev','main-after')
ops.snapshot(ops.QA,'qa-after')
preservation={}
for table in ['account_move','account_move_line','account_payment','res_company','res_partner','res_users','res_groups_users_rel','res_company_users_rel']:
    dump=ops.run(['docker','exec',ops.DB,'pg_restore','--data-only','--table='+table,'-f','-','/tmp/om-payroll-before.dump'],capture_output=True,text=True).stdout
    match=re.search(r'COPY public\.'+table+r' \((.*?)\) FROM stdin;\n(.*?)\n\\\.',dump,re.S)
    if not match: raise RuntimeError('Missing backup table '+table)
    columns,values=match.groups()
    safe=', '.join(c for c in columns.split(', ') if c not in ('password','totp_secret'))
    query='BEGIN; CREATE TEMP TABLE bp_before AS SELECT '+columns+' FROM '+table+' WITH NO DATA; COPY bp_before ('+columns+') FROM stdin;\n'+values+'\n\\.\n'
    query+="SELECT json_build_object('before_count',(SELECT count(*) FROM bp_before),'original_rows_missing_or_changed',(SELECT count(*) FROM (SELECT row_to_json(b)::text FROM (SELECT "+safe+' FROM bp_before)b EXCEPT SELECT row_to_json(a)::text FROM (SELECT '+safe+' FROM '+table+")a)d),'after_count',(SELECT count(*) FROM "+table+')); ROLLBACK;'
    try:
        payload=ops.sql(ops.QA,query)
    except Exception as exc:
        print(table, getattr(exc,'stderr','').splitlines()[0])
        raise
    preservation[table]=json.loads(payload[payload.index('{'):payload.rindex('}')+1])
    if table in ('res_partner','res_users'):
        detail='BEGIN; CREATE TEMP TABLE bp_before AS SELECT '+columns+' FROM '+table+' WITH NO DATA; COPY bp_before ('+columns+') FROM stdin;\n'+values+'\n\\.\n'
        detail+="SELECT coalesce(json_agg(d),'[]'::json) FROM (SELECT b.id,array_agg(k.key ORDER BY k.key) changed_fields FROM (SELECT "+safe+' FROM bp_before)b JOIN (SELECT '+safe+' FROM '+table+")a USING(id) CROSS JOIN LATERAL jsonb_each(to_jsonb(b)) k WHERE k.value IS DISTINCT FROM (to_jsonb(a)->k.key) GROUP BY b.id)d; ROLLBACK;"
        out=ops.sql(ops.QA,detail)
        preservation[table]['details']=json.loads(out[out.index('['):out.rindex(']')+1])
        if table=='res_partner':
            query='BEGIN; CREATE TEMP TABLE bp_before AS SELECT '+columns+' FROM '+table+' WITH NO DATA; COPY bp_before ('+columns+') FROM stdin;\n'+values+'\n\\.\n'
            query+="SELECT count(*) FROM bp_before b JOIN res_partner a USING(id) CROSS JOIN LATERAL (SELECT key,value FROM jsonb_each(coalesce(b.property_stock_customer,'{}'::jsonb)) WHERE a.property_stock_customer->key IS DISTINCT FROM value UNION ALL SELECT key,value FROM jsonb_each(coalesce(b.property_stock_supplier,'{}'::jsonb)) WHERE a.property_stock_supplier->key IS DISTINCT FROM value)d; ROLLBACK;"
            lines=ops.sql(ops.QA,query).splitlines()
            count=int(next(line for line in lines if line.isdigit()))
            preservation[table]['original_company_stock_property_values_changed']=count
            assert count==0
preservation['main_exact']=json.loads((OUT/'main-before.json').read_text())==json.loads((OUT/'main-after.json').read_text())
for table in ['account_move','account_move_line','account_payment']:
    assert preservation[table]['original_rows_missing_or_changed']==0,table
assert preservation['main_exact']
ops.write('preservation.json',preservation)
upstream=json.loads((ROOT/'docs/releases/2026-09-08-om-payroll/source.json').read_text())
assert all(hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()==f['sha256'] for f in upstream['files'])
addon=ROOT/'custom_addons/baseer_payroll'
files=[p for p in sorted(addon.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
archive=OUT/'baseer_payroll-19.0.1.0.0.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(addon.parent))
manifest={'version':'19.0.1.0.0','target':'baseer_reports_qa_20260907 only','git_commit':None,'git_note':'Workspace has no commits; exact source and artifact hashes freeze this QA candidate.','upstream_commit':upstream['commit'],'upstream_files_unchanged':len(upstream['files']),'archive':archive.name,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
ops.write('candidate.json',manifest)
print(json.dumps({'preservation':preservation,'source_files':len(files),'archive_sha256':manifest['archive_sha256']},indent=2))

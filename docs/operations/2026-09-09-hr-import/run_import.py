"""Local HR1 orchestration, private payload/evidence, no secrets in stdout."""
import argparse
import base64
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PRIVATE=ROOT/'.local-backups/hr-import-20260909'
SHA='a8eda338b31b9947ab69ff275c75f39cd7c5cb3d9922e46309564a8017e8ce13'

def prepare():
    source=PRIVATE/'source.json'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==SHA
    data=json.loads(source.read_text(encoding='utf-8-sig'))
    companies={
        '7e64301f-c87e-4d98-9881-35328ace117b':{'id':1,'source_name':'ARZ','target_name':'ARZ'},
        '4af6969a-161f-4e13-8acc-103d8aa26a70':{'id':2,'source_name':'مشويات المعلم الشامي','target_name':'المعلم الشامي'},
        '3c032ff1-c00d-4784-99ae-a9bf53e09e0d':{'id':3,'source_name':'دوحة المستهلك','target_name':'دوحة المستهلك'},
    }
    assert data['database']=='baseer_erp_test' and data['asOf']=='2026-09-09'
    assert len(data['employees'])==51
    for c in data['companies']:
        assert c['nameAr']==companies[c['id']]['source_name']
    groups=defaultdict(list)
    for e in data['employees']:
        assert e['companyId'] in companies and e['nameAr'].strip()
        groups[(e['companyId'],e['nameAr'])].append(e)
    allowed_merges={
        frozenset(['0d2bbb02-a06e-4732-b197-b861de371094','8dd464b4-221e-4418-9f41-93988d6e85a4']),
        frozenset(['61047d8e-7aca-4669-9eb1-5bf8196868b1','c6111acb-4e22-4560-b04a-91848d375a25']),
    }
    rows=[]
    for _, es in sorted(groups.items()):
        es.sort(key=lambda e:(e['employeeNumber'],e['id']))
        if len(es)>1:
            assert frozenset(e['id'] for e in es) in allowed_merges
            assert all(e['status'] in ('ARCHIVED','TERMINATED') for e in es)
        row={k:es[0][k] for k in ['id','companyId','nameAr','nameEn','employeeNumber','status']}
        row['source_records']=[{k:e[k] for k in ['id','employeeNumber','status']} for e in es]
        rows.append(row)
    assert len(rows)==49
    assert sum(e['status'] in ('ACTIVE','ON_LEAVE') for e in rows)==34
    payload={'scope':'names_only','source_sha256':SHA,'companies':companies,'employees':rows}
    (PRIVATE/'names-payload.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    return payload

def run(commit=False):
    payload=prepare()
    encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()
    script=HERE/'import_orm.py'
    script_sha=hashlib.sha256(script.read_bytes()).hexdigest()
    payload_sha=hashlib.sha256((PRIVATE/'names-payload.json').read_bytes()).hexdigest()
    if commit:
        review=json.loads((HERE/'ACCEPTANCE.json').read_text(encoding='utf8'))
        assert review['decision']=='GO' and review['script_sha256']==script_sha and review['payload_sha256']==payload_sha
        dry=json.loads((PRIVATE/'rollback-result.json').read_text(encoding='utf8'))
        assert dry['script_sha256']==script_sha and dry['payload_sha256']==payload_sha
    text='import json,base64\nPAYLOAD=json.loads(base64.b64decode('+repr(encoded)+'))\nCOMMIT='+repr(commit)+'\n'+script.read_text(encoding='utf8')
    args=['docker','exec','-i','baseer_odoo_dev-odoo-1','/entrypoint.sh','odoo','shell',
          '--config=/etc/odoo/odoo.local.conf',
          '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
          '--database=baseer_dev','--no-http','--max-cron-threads=0','--log-level=error']
    r=subprocess.run(args,input=text,encoding='utf8',capture_output=True)
    mode='committed' if commit else 'rollback'
    (PRIVATE/(mode+'-stdout.txt')).write_text(r.stdout,encoding='utf8')
    (PRIVATE/(mode+'-stderr.txt')).write_text(r.stderr,encoding='utf8')
    lines=[s for s in r.stdout.splitlines() if s.startswith('HR1_RESULT=')]
    if r.returncode or len(lines)!=1:
        print(r.stderr[-4500:])
        raise RuntimeError('HR1 failed, inspect private logs')
    result=json.loads(lines[0].split('=',1)[1])
    result.update(script_sha256=script_sha,payload_sha256=payload_sha)
    (PRIVATE/(mode+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    public={k:v for k,v in result.items() if k!='mapping'}
    (HERE/(mode+'-summary.json')).write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(public,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--commit',action='store_true')
    options=parser.parse_args()
    run(options.commit)

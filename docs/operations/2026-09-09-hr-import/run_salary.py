"""HR2 private salary conversion and gated native ORM import."""
import argparse
import base64
import hashlib
import json
import subprocess
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PRIVATE=ROOT/'.local-backups/hr-import-20260909'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def q(n):return D(n).quantize(D('.01'),rounding=ROUND_HALF_UP)

def prepare():
    analysis=json.loads((PRIVATE/'salary-analysis.json').read_text(encoding='utf8'))
    names=json.loads((PRIVATE/'names-payload.json').read_text(encoding='utf8'))
    ids={r['id']:e for e in names['employees'] for r in e['source_records']}
    target_ids={r['source_id']:r['target_id'] for r in json.loads((PRIVATE/'committed-result.json').read_text(encoding='utf8'))['mapping']}
    baselines=json.loads((PRIVATE/'salary-target-before.json').read_text(encoding='utf8'))
    decisions=json.loads((PRIVATE/'salary-decisions.json').read_text(encoding='utf8')) if (PRIVATE/'salary-decisions.json').exists() else {}
    rows=[];totals={};missing=[]
    for original in analysis['employees']:
        a=dict(original);name=ids[a['sourceEmployeeId']]
        assert set(a['sourceEmployeeIds'])=={s['id'] for s in name['source_records']}
        if not a.get('rounded') and decisions.get(a['sourceEmployeeId']):
            selected=[c for c in a['noorixSalaryCandidates'] if c['baseerEmployeeId']==decisions[a['sourceEmployeeId']]]
            assert len(selected)==1
            a.update(selected[0]);a['salaryAuthority']='Owner-selected merged historical source salary'
        company_id=names['companies'][a['companyId']]['id']
        row={'name':name['nameAr'],'company_id':company_id,
            'active':name['status'] in ('ACTIVE','ON_LEAVE'),
            'employee_xmlids':['baseer_legacy_hr_import.employee_'+a['companyId'].replace('-','')+'_'+sid.replace('-','') for sid in a['sourceEmployeeIds']],
            'job_title':a.get('jobTitle') or None, 'salary':None}
        row['baseline']=baselines[str(target_ids[a['sourceEmployeeId']])]
        if a.get('rounded'):
            r=a['rounded'];g=q(r['gross']);b=q(r['basic']);allow=q(r['allowanceTotal']);ot=q(r['overtimeReconciledToGross'])
            assert allow==sum(q(r[k]) for k in ['foodAllowance','housingAllowance','transportAllowance','otherAllowance'])
            assert g==b+allow+ot and min(g,b,allow,ot)>=0
            h=a.get('scheduledHoursPerDay');days=a.get('scheduledWorkDays') or 26
            mode='inclusive' if a['compensationMethod']=='INCLUSIVE_OVERTIME' else 'fixed'
            target_basic=g-allow
            if mode=='inclusive' and g:
                assert h and 0<h<=12 and 1<=days<=31
                k=(max(D(h)-8,D(0))*min(days,26)+max(days-26,0)*D(h))/208
                target_basic=q((g-allow*(1+k))/(1+D('1.5')*k))
            assert target_basic==b and q(g-target_basic-allow)==ot, 'Source components not reproducible in Odoo'
            source_key=a.get('selectedProfileId') or ('noorix_'+a['noorixEmployeeId']+'_20260902')
            row['salary']={'gross':str(g),'basic':str(b),'allowances':str(allow),'overtime':str(ot),
                'mode':mode,'daily_hours':h,'work_days':days,
                'effective_date':a.get('effectiveFrom') or '2026-09-09',
                'effective_date_kind':'source' if a.get('effectiveFrom') else 'import_cutover_not_source_effective_date',
                'identity':source_key,'source_authority':a['salaryAuthority'],
                'allowance_breakdown':{k:r[k] for k in ['foodAllowance','housingAllowance','transportAllowance','otherAllowance']}}
            if not row['baseline']['pending']:
                row['salary']['keep_target_calendar']=True
                row['salary']['effective_date']=row['baseline']['date_version']
                row['salary']['effective_date_kind']='preserve_user_schedule_version_date'
                if mode=='inclusive' and D(h)!=D(str(row['baseline']['hours'])):
                    if decisions.get('schedule_policy')!='keep_recalculate':
                        row['salary']=None
                        missing.append({'source_id':a['sourceEmployeeId'],'reason':'changed_schedule_policy_pending','active':row['active']})
                        rows.append(row)
                        continue
                    nh=D(str(row['baseline']['hours']))
                    assert 0<nh<=12
                    nk=(max(nh-8,D(0))*min(days,26)+max(days-26,0)*nh)/208
                    nb=q((g-allow*(1+nk))/(1+D('1.5')*nk));no=q(g-nb-allow)
                    row['salary'].update(source_basic=str(b),source_overtime=str(ot),basic=str(nb),overtime=str(no),daily_hours=float(nh),recalculated_for_owner_schedule=True)
            group=totals.setdefault(str(company_id),{'current':{'employees':0,'gross':'0.00','basic':'0.00','allowances':'0.00','overtime':'0.00'},'archived':{'employees':0,'gross':'0.00','basic':'0.00','allowances':'0.00','overtime':'0.00'}})['current' if row['active'] else 'archived']
            group['employees']+=1
            for key in ('gross','basic','allowances','overtime'):group[key]=str(q(group[key])+D(row['salary'][key]))
        else:
            missing.append({'source_id':a['sourceEmployeeId'],'reason':'merged_historical_salary_conflict','active':row['active']})
        rows.append(row)
    assert len(rows)==49
    payload={'scope':'salary_and_jobs','employees':rows,'totals':totals,'missing':missing,
             'source_hashes':{f:sha(PRIVATE/f) for f in ['source.json','noorix-salary-source.json','salary-analysis.json','names-payload.json','salary-source-engine-check.json','salary-target-before.json']}}
    (PRIVATE/'salary-payload.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    return payload

def run(commit=False):
    payload=prepare();script=HERE/'salary_orm.py'
    hashes={'script_sha256':sha(script),'driver_sha256':sha(Path(__file__)),
            'payload_sha256':sha(PRIVATE/'salary-payload.json')}
    if commit:
        approval=json.loads((HERE/'HR2-ACCEPTANCE.json').read_text(encoding='utf8'))
        assert approval['decision']=='GO'
        assert all(approval[k]==v for k,v in hashes.items())
        dry=json.loads((PRIVATE/'salary-rollback-result.json').read_text(encoding='utf8'))
        assert all(dry[k]==v for k,v in hashes.items())
    encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()
    code='import json,base64\nPAYLOAD=json.loads(base64.b64decode('+repr(encoded)+'))\nCOMMIT='+repr(commit)+'\n'+script.read_text(encoding='utf8')
    args=['docker','exec','-i','baseer_odoo_dev-odoo-1','/entrypoint.sh','odoo','shell',
          '--config=/etc/odoo/odoo.local.conf',
          '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
          '--database=baseer_dev','--no-http','--max-cron-threads=0','--log-level=error']
    r=subprocess.run(args,input=code,encoding='utf8',capture_output=True)
    mode='committed' if commit else 'rollback'
    for label,value in [('stdout',r.stdout),('stderr',r.stderr)]:
        (PRIVATE/('salary-'+mode+'-'+label+'.txt')).write_text(value,encoding='utf8')
    lines=[s for s in r.stdout.splitlines() if s.startswith('HR2_RESULT=')]
    if r.returncode or len(lines)!=1:
        print(r.stderr[-4500:]);raise RuntimeError('Salary import failed, inspect private logs')
    result=json.loads(lines[0].split('=',1)[1]);result.update(hashes)
    (PRIVATE/('salary-'+mode+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    public={k:v for k,v in result.items() if k not in ('mapping','missing')}
    public['pending_historical_conflicts']=sum(not r['active'] for r in result['missing'])
    public['pending_current_schedule_decisions']=sum(r['active'] for r in result['missing'])
    (HERE/('salary-'+mode+'-summary.json')).write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(public,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',action='store_true')
    run(parser.parse_args().commit)

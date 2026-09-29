"""SP1 explicit reviewed deletion; dry-run by default, all-or-nothing checks."""
import json,traceback,time
from pathlib import Path
assert env.cr.dbname=='baseer_reports_qa_20260907'
commit=globals().get('SP1_COMMIT',False)
R={'status':'started','commit':commit}
out=Path('/mnt/qa-evidence/shared_partners_consolidate'+('_applied' if commit else '_dryrun')+'.json')
try:
    inventory=json.loads(Path('/mnt/qa-evidence/shared_partners_inventory.json').read_text())
    source_ids=sorted({x['id'] for x in inventory['seed']})
    sources=env['res.partner'].sudo().with_context(active_test=False).browse(source_ids).exists()
    assert len(sources)==len(source_ids),'Unexpected source inventory drift'
    names,props=env['res.company']._baseer_provider_properties(sources)
    start=time.monotonic()
    result=env['res.company']._baseer_consolidate_service_providers()
    assert result['deleted']==len(source_ids),result
    assert {x['source_id'] for x in result['lineage']}==set(source_ids)
    assert not sources.exists(),'Old sources must be deleted, not archived'
    canonical_ids={x['canonical_id'] for x in result['lineage']}
    assert len(canonical_ids)==20
    for line in result['lineage']:
        partner=env['res.partner'].browse(line['canonical_id'])
        assert not partner.company_id and partner.active
        assert partner.baseer_name_ar and partner.baseer_name_en
        assert env.ref('baseer_service_seed.'+line['alias'])==partner
        for field in names:
            for cid,value in (props[line['source_id']][field] or {}).items():
                actual=partner.with_company(env['res.company'].browse(int(cid)))[field]
                if partner._fields[field].type=='many2one':actual=actual.id or False
                assert actual==value,(line['source_id'],field,cid,value,actual)
    env.flush_all()
    env.cr.execute("SELECT count(*) FROM ir_model_data WHERE model='res.partner' AND res_id IN %s",[tuple(source_ids)])
    assert env.cr.fetchone()[0]==0,'Dangling old partner external IDs'
    again=env['res.company']._baseer_consolidate_service_providers()
    assert not again['deleted'],'Migration must be idempotent'
    env['res.company']._baseer_initialize_services()
    env.flush_all()
    assert not sources.exists()
    assert env['res.partner'].sudo().search_count([('id','in',list(canonical_ids)),('company_id','=',False),('active','=',True)])==20
    R.update(status='passed',result=result,explicit_properties_verified=True,no_dangling_xmlids=True,idempotent=True,seconds=round(time.monotonic()-start,3))
    if commit:env.cr.commit()
except Exception:
    R.update(status='failed',traceback=traceback.format_exc());env.cr.rollback()
finally:
    if not commit or R['status']!='passed':env.cr.rollback()
    out.write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in R.items() if k!='result'},ensure_ascii=False))

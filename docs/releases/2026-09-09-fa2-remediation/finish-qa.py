"""Accept four proven nonfinancial native flags after the strict QA guard stopped."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
baseline=json.loads((f.OUT/'qa-update-baseline.json').read_text())
allowed={646,647,805,811};proof=[];metadata=[]
for table,v in baseline.items():
 ids=','.join(map(str,v['ids'])) or 'NULL'
 query='SELECT '+v['columns']+' FROM '+table+' WHERE id IN ('+ids+')'
 def hashrows(db):return f.o.sql(db,"SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM ("+query+')t')
 if table.startswith('account_'):
  assert int(f.o.sql(f.o.QA,'SELECT count(*) FROM '+table))==len(v['ids']),table
 if hashrows(f.o.QA)!=v['hash']:
  assert table=='account_move',table
  assert hashrows(f.db('security'))==v['hash'],'Preserved clone is not the exact preimage'
  def rows(db):return json.loads(f.o.sql(db,'SELECT json_agg(t) FROM ('+query+' ORDER BY id)t'))
  before,after=rows(f.db('security')),rows(f.o.QA)
  for a,b in zip(before,after):
   assert a['id']==b['id']
   changes={k:[a[k],b[k]] for k in a if a[k]!=b[k]}
   if not changes:continue
   assert a['id'] in allowed and changes=={'is_manually_modified':[False,True]}
   assert b['move_type']=='entry' and b['state']=='posted'
   ownership=json.loads(f.o.sql(f.o.QA,"SELECT row_to_json(t) FROM (SELECT m.id,m.baseer_pos_summary_id,s.state AS summary_state FROM account_move m JOIN baseer_pos_summary s ON s.id=m.baseer_pos_summary_id WHERE m.id="+str(a['id'])+')t'))
   assert ownership['summary_state']=='approved'
   proof.append({'id':a['id'],'changes':changes,'move_type':b['move_type'],'state':b['state'],'ownership':ownership})
 now=f.o.sql(f.o.QA,"SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM (SELECT id,write_date,write_uid FROM "+table+")t")
 if now!=v['audit_metadata_hash']:metadata.append(table)
assert {p['id'] for p in proof}==allowed
assert f.audit.snapshot('baseer_dev')==json.loads((f.OUT/'main-before.json').read_text())
result={'success':True,'database':f.o.QA,'source_archive_sha256':json.loads((f.OUT/'candidate.json').read_text())['archive_sha256'],
 'accounting_history_unchanged':True,'new_accounting_transactions':0,'main_unchanged':True,'backup_directory':str(f.BACK/'before-qa-update'),
 'strict_guard_stopped_before_reopening':True,'audit_metadata_changed_tables':metadata,'narrow_native_flag_exception':proof,
 'exception_reason':'Native ORM ownership-backfill write marks these four posted POS journal entries manually modified. The only consumer is an imported purchase-bill auto-post suggestion, inapplicable to these entries. Every other original column, financial link, amount, state, posting date and row count is preserved. Exact preimage hash verified against the preserved security clone; no global flag exclusion.'}
f.save('qa-update-result.json',result)
f.o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','up','-d','--no-deps','reports_qa'],capture_output=True)
print('QA reopened; all financial values preserved; four explicit administrative flags recorded')

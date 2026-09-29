"""Remove only the five disposable FA2 databases after evidence collection."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
names=['baseer_fix_'+s+'_20260909' for s in ('core','payroll','sales','security','main')]
assert set(names).isdisjoint({f.o.QA,'baseer_dev'})
f.o.run(['docker','stop','baseer_odoo_dev-fa2_review-1'],capture_output=True)
results=[]
for database in names:
 assert f.o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='"+database+"'")=='0',database
 if f.o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+database+"'")=='1':
  f.o.sql('postgres','DROP DATABASE '+database)
 assert f.o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+database+"'")=='0'
 results.append({'database':database,'removed':True})
script='''
import pathlib,shutil
root=pathlib.Path('/var/lib/odoo/filestore').resolve()
names=NAMES
for name in names:
 path=(root/name).resolve()
 assert path.parent==root and path.name==name and name.startswith('baseer_fix_')
 if path.exists():shutil.rmtree(path)
print('Removed five isolated filestores')
'''.replace('NAMES',repr(names))
f.o.run(['docker','exec','-i',f.o.CONTAINER,'python3','-'],input=script,text=True,capture_output=True)
f.save('clone-cleanup.json',{'clones':results,'filestores_removed':True,'review_service_stopped':True,'source_and_backup_archives_retained':True})
print('Cleaned five FA2 clones; live databases and backup archives retained')
